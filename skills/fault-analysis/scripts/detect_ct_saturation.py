# -*- coding: utf-8 -*-
"""
CT 饱和检测(主变场景定制)

复用 latent-faults/scripts/harmonic_analysis.py,
针对主变各侧电流做 0~40ms 窗口的饱和嫌疑判定。

判定条件:
- 基波 > 2In
- 2次谐波/基波 > 15%
- OR HDR 中 CT 饱和标志 = 1

输出:每侧每相的饱和嫌疑标记 + 严重度
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List


def check_phase_saturation(fundamental_a: float, second_harmonic_pct: float, in_a: float) -> dict:
    """检查单相 CT 饱和

    参数:
        fundamental_a: 基波幅值(二次值,A)
        second_harmonic_pct: 2次谐波/基波 百分比
        in_a: 额定电流(二次值,A)

    返回:
        {"saturated": bool, "severity": float, "fundamental_a": float, "2nd_pct": float}
    """
    saturated = (fundamental_a > 2 * in_a) and (second_harmonic_pct > 15.0)
    if not saturated:
        severity = 0.0
    else:
        amp_factor = min(fundamental_a / (5 * in_a), 1.0) if in_a > 0 else 0.0
        harm_factor = min(second_harmonic_pct / 50.0, 1.0)
        severity = round(0.5 * amp_factor + 0.5 * harm_factor, 3)
    return {
        "saturated": saturated,
        "severity": severity,
        "fundamental_a": fundamental_a,
        "2nd_pct": second_harmonic_pct,
    }


def detect_saturation_for_csv(csv_path: str, side: str, in_a: float, window_ms: float = 40.0) -> dict:
    """对单个电流 CSV 检测 CT 饱和

    参数:
        csv_path: 谐波分析结果 CSV(含 <通道>_1, <通道>_2 列)
        side: 主变侧标识(高压侧/中压侧/低压侧)
        in_a: 该侧额定电流
        window_ms: 检测窗口(故障后 0~window_ms)

    返回:
        {side: {phase: {saturated, severity, ...}}}
    """
    import csv

    result = {side: {}}
    harmonics_path = Path(csv_path)

    with open(harmonics_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        phases = ["A", "B", "C"]
        max_fund = {p: 0.0 for p in phases}
        max_2nd_pct = {p: 0.0 for p in phases}

        for row in reader:
            try:
                t_ms = float(row.get("时间ms", row.get("t_ms", 0)))
            except (ValueError, KeyError):
                continue
            if t_ms > window_ms:
                break
            for p in phases:
                f1_key = f"I{p}_1"
                f2_key = f"I{p}_2"
                if f1_key in row and f2_key in row:
                    try:
                        f1 = abs(float(row[f1_key]))
                        f2 = abs(float(row[f2_key]))
                        if f1 > max_fund[p]:
                            max_fund[p] = f1
                            max_2nd_pct[p] = (f2 / f1 * 100) if f1 > 0 else 0.0
                    except ValueError:
                        continue

        for p in phases:
            result[side][p] = check_phase_saturation(
                fundamental_a=max_fund[p],
                second_harmonic_pct=max_2nd_pct[p],
                in_a=in_a,
            )

    return result


def main():
    parser = argparse.ArgumentParser(description="CT 饱和检测(主变场景)")
    parser.add_argument("--harmonics-csv", required=True, help="谐波分析结果 CSV")
    parser.add_argument("--side", required=True, help="主变侧:高压侧/中压侧/低压侧")
    parser.add_argument("--in-a", type=float, required=True, help="该侧额定电流(A)")
    parser.add_argument("--window-ms", type=float, default=40.0, help="检测窗口(ms)")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    args = parser.parse_args()

    result = detect_saturation_for_csv(args.harmonics_csv, args.side, args.in_a, args.window_ms)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {args.output}")


if __name__ == "__main__":
    main()