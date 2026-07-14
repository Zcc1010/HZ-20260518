# -*- coding: utf-8 -*-
"""
跨设备时间对齐

读取多个装置的 events.csv,基于首次电流正突变时间做对齐,输出统一时间轴。

CLI:
    python align_cross_device.py \
      --events-json output/aligned_input.json \
      --ref-strategy fault_recorder_first \
      --output aligned.json
"""
import argparse
import json
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class SyncQuality(Enum):
    GOOD = "good"
    NEEDS_VERIFY = "待核实: 时钟漂移"
    FAILED = "对齐失败"


def find_first_positive_mutation(events: List[dict]) -> Optional[dict]:
    """找到该设备最早的正突变事件(delta > 0)"""
    positives = [e for e in events if e.get("delta", 0) > 0]
    if not positives:
        return None
    return min(positives, key=lambda e: e["time"])


def compute_offsets(
    events_by_device: Dict[str, List[dict]],
    ref_strategy: str = "fault_recorder_first",
) -> Tuple[datetime, Dict[str, float]]:
    """计算每台设备相对参考时间的偏移"""
    ref_time: Optional[datetime] = None
    if ref_strategy == "fault_recorder_first" and "fault_recorder" in events_by_device:
        first = find_first_positive_mutation(events_by_device["fault_recorder"])
        if first:
            ref_time = first["time"]

    if ref_time is None:
        all_firsts = []
        for dev, evts in events_by_device.items():
            first = find_first_positive_mutation(evts)
            if first:
                all_firsts.append(first["time"])
        if not all_firsts:
            raise ValueError("无任何设备的电流正突变事件,无法对齐")
        ref_time = min(all_firsts)

    offsets: Dict[str, float] = {}
    for dev, evts in events_by_device.items():
        first = find_first_positive_mutation(evts)
        if first is None:
            negatives = [e for e in evts if e.get("delta", 0) < 0]
            if negatives:
                first = min(negatives, key=lambda e: e["time"])
        if first is None:
            offsets[dev] = 0.0
        else:
            offsets[dev] = (first["time"] - ref_time).total_seconds() * 1000.0

    return ref_time, offsets


def apply_offsets(events_by_device: Dict[str, List[dict]], offsets: Dict[str, float]) -> List[dict]:
    """应用偏移,生成统一时间轴上的事件列表(aligned_time_ms 为秒内毫秒偏移)"""
    aligned = []
    for dev, evts in events_by_device.items():
        offset_ms = offsets.get(dev, 0.0)
        for e in evts:
            if "time" in e:
                t = e["time"]
                t_ms = t.second * 1000.0 + t.microsecond / 1000.0
                aligned.append({
                    "device": dev,
                    "channel": e.get("channel", ""),
                    "value": e.get("value"),
                    "aligned_time_ms": round(t_ms - offset_ms, 3),
                    "raw_time": t.isoformat(),
                })
    aligned.sort(key=lambda x: x["aligned_time_ms"])
    return aligned


def check_sync_quality(offsets: Dict[str, float], tolerance_ms: float = 100.0) -> Dict[str, SyncQuality]:
    """检查每台设备的时间同步质量"""
    quality: Dict[str, SyncQuality] = {}
    for dev, off in offsets.items():
        if abs(off) > tolerance_ms:
            quality[dev] = SyncQuality.NEEDS_VERIFY
        else:
            quality[dev] = SyncQuality.GOOD
    return quality


def main():
    parser = argparse.ArgumentParser(description="跨设备时间对齐")
    parser.add_argument("--events-json", required=True,
                        help="输入 JSON:{device_id: [events]}")
    parser.add_argument("--ref-strategy", default="fault_recorder_first",
                        choices=["fault_recorder_first", "earliest"])
    parser.add_argument("--tolerance-ms", type=float, default=100.0)
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    args = parser.parse_args()

    events = json.loads(Path(args.events_json).read_text(encoding="utf-8"))
    for dev, evts in events.items():
        for e in evts:
            if isinstance(e.get("time"), str):
                e["time"] = datetime.fromisoformat(e["time"])

    ref_time, offsets = compute_offsets(events, args.ref_strategy)
    aligned = apply_offsets(events, offsets)
    quality = {k: v.value for k, v in check_sync_quality(offsets, args.tolerance_ms).items()}

    out = {
        "ref_time": ref_time.isoformat(),
        "ref_strategy": args.ref_strategy,
        "sync_quality": quality,
        "offsets_ms": {k: round(v, 3) for k, v in offsets.items()},
        "aligned_events": aligned,
    }
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {args.output}")


if __name__ == "__main__":
    main()