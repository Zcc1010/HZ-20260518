# -*- coding: utf-8 -*-
"""
自动选线算法

数据源优先级:
- P1:故障录波器(一次扫描所有出线,默认)
- P2:各下级出线保护装置录波(多文件)
- P3:P1 + P2 融合

嫌疑评分 = w1×40 (故障电流幅值分)
         + w2×25 (突变时间差分)
         + w3×20 (保护动作元件匹配分)
         + w4×15 (距离/阻抗合理性分)

默认权重:40/25/20/15
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_WEIGHTS = {"i_max": 40, "mutation_time": 25, "protection": 20, "impedance": 15}


def _score_i_max(line: dict) -> float:
    """故障电流幅值分"""
    i_max = line.get("i_max_a", 0)
    in_a = line.get("in_a", 600)
    if i_max > 2 * in_a:
        return 1.0
    if i_max > 1.2 * in_a:
        return 0.5
    return 0.0


def _score_mutation_time(line: dict, t_ref_ms: float = 0) -> float:
    """突变时间差分"""
    t = line.get("mutation_time_ms")
    if t is None:
        return 0.0
    delta = abs(t - t_ref_ms)
    if delta <= 5:
        return 1.0
    if delta <= 20:
        return 0.7
    if delta <= 50:
        return 0.3
    return 0.0


def _score_protection_match(line: dict) -> float:
    """保护动作元件匹配分"""
    if not line.get("protection_match"):
        return 0.0
    zone = line.get("protection_zone", "I")
    return {"I": 1.0, "II": 0.7, "III": 0.3}.get(zone, 0.5)


def _score_impedance(line: dict) -> float:
    """距离/阻抗合理性分"""
    imp = line.get("impedance_km")
    length = line.get("line_length_km")
    if imp is None or length is None:
        return 0.0
    if 0 < imp < length:
        return 1.0
    return 0.0


def _infer_t_ref(candidates: List[dict]) -> float:
    """从候选列表中推断参考突变时间(取最小值)"""
    times = [c.get("mutation_time_ms") for c in candidates if c.get("mutation_time_ms") is not None]
    return min(times) if times else 0.0


def score_line(line: dict, weights: Optional[Dict[str, int]] = None,
               t_ref_ms: Optional[float] = None) -> float:
    """计算单条线路的嫌疑分数(0~100)

    t_ref_ms 为 None 时,使用该线路自身的 mutation_time_ms 作为参考(单点调用场景)
    """
    w = weights or DEFAULT_WEIGHTS
    if t_ref_ms is None:
        t_ref_ms = line.get("mutation_time_ms", 0) or 0
    s_i = _score_i_max(line) * w["i_max"]
    s_t = _score_mutation_time(line, t_ref_ms) * w["mutation_time"]
    s_p = _score_protection_match(line) * w["protection"]
    s_z = _score_impedance(line) * w["impedance"]
    return round(s_i + s_t + s_p + s_z, 2)


def rank_candidates(candidates: List[dict], weights: Optional[Dict[str, int]] = None) -> List[dict]:
    """按嫌疑分数降序排列候选线路"""
    t_ref = _infer_t_ref(candidates)
    scored = [{**c, "score": score_line(c, weights, t_ref)} for c in candidates]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def select_topk(candidates: List[dict], k: int = 3,
                weights: Optional[Dict[str, int]] = None) -> List[dict]:
    """选取得分最高的 K 条候选线路"""
    ranked = rank_candidates(candidates, weights)
    return ranked[:k]


def main():
    parser = argparse.ArgumentParser(description="自动选线")
    parser.add_argument("--candidates-json", required=True)
    parser.add_argument("--topk", type=int, default=3)
    parser.add_argument("--weights", help="自定义权重 JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    candidates = json.loads(Path(args.candidates_json).read_text(encoding="utf-8"))
    weights = json.loads(args.weights) if args.weights else None
    topk = select_topk(candidates, k=args.topk, weights=weights)

    Path(args.output).write_text(
        json.dumps({"candidates": topk, "all_count": len(candidates)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 {args.output},Top-{args.topk} 候选 {len(topk)} 条")


if __name__ == "__main__":
    main()
