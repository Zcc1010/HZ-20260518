#!/usr/bin/env python3
"""
前置检查脚本 —— 主 Agent 生成简报前强制执行。
检查步骤 0 (parse_folder_name.py) 和步骤 5 (Subagent 段落) 的产物。
缺失任一项 → 返回非零退出码，主 Agent 必须停止。
"""

import sys, os, json, argparse
from pathlib import Path

def check_step0(analysis_dir: str) -> bool:
    """检查 parse_folder_name.py 是否已执行并产出 JSON。"""
    base = Path(analysis_dir)
    # 查找 device_metadata.json 或其他 parse_folder_name 产物
    candidates = list(base.glob("device_metadata.json")) + list(base.glob("parse_folder_*.json"))
    if candidates:
        print(f"✓ 步骤0: parse_folder_name.py 已执行 ({candidates[0].name})")
        return True
    # 如果没有 JSON，检查是否手动执行过（可通过段落中的前置条件推断）
    print("✗ 步骤0: device_metadata.json 缺失 — 请先执行 parse_folder_name.py")
    return False

def check_step5(analysis_dir: str, expected_devices: list = None) -> bool:
    """检查段落文件是否存在且包含三区块。"""
    base = Path(analysis_dir)
    
    # 段落可能在 analysis_dir/段落/ 或 analysis_dir 本身下的 .md 文件
    if (base / "段落").exists():
        para_dir = base / "段落"
    elif list(base.glob("*.md")):
        para_dir = base
    else:
        print(f"✗ 步骤5: 段落目录不存在 ({base})")
        return False

    para_files = list(para_dir.glob("*.md"))
    if not para_files:
        print("✗ 步骤5: 无 .md 段落文件")
        return False

    all_ok = True
    required_blocks = ["前置条件", "HDR信息", "Events信息", "RMS信息"]
    # 故障发展过程数据 区块（SKILL 规则 #18）：必须存在，或显式标注无原始波形
    fd_required = True
    # 故障录波器 和 纯监测设备 可豁免 HDR信息 块
    exempt_hdr_devices = {"故障录波器", "录波器", "监测"}

    for pf in para_files:
        with open(pf, encoding='utf-8') as f:
            content = f.read()
        
        fname = pf.name
        is_exempt = any(kw in fname or kw in content[:500] for kw in exempt_hdr_devices)
        
        blocks_to_check = [b for b in required_blocks if not (b == "HDR信息" and is_exempt)]
        missing = [b for b in blocks_to_check if b not in content]
        # 故障发展过程数据 区块：复杂/发展性故障必须；单一阶段故障允许缺
        has_fd_block = ("故障发展过程数据" in content) or ("无原始波形，故障发展过程无法量化" in content)
        if not has_fd_block:
            print(f"    ⚠ {pf.name}: 缺「故障发展过程数据」（单一阶段故障可省略）")
        if missing:
            print(f"✗ 步骤5: {pf.name} 缺区块 {missing}")
            all_ok = False
        else:
            print(f"  ✓ {pf.name}")

    if expected_devices:
        found = {pf.stem for pf in para_files}
        missing = set(expected_devices) - found
        if missing:
            print(f"✗ 步骤5: 缺以下装置段落: {missing}")
            all_ok = False

    if all_ok:
        print(f"✓ 步骤5: {len(para_files)} 份段落完整")
    return all_ok


def check_step6(analysis_dir):
    """步骤6: 故障发展过程数据 (development.json) — 复杂/发展性故障强制；单一阶段故障不阻断"""
    output_dir = Path(analysis_dir) / 'output'
    if not output_dir.is_dir():
        print("  ⚠ 步骤6: output/ 目录不存在（单一阶段故障可忽略；复杂/发展性故障须补充）")
        return True  # 不阻断：单一阶段故障不需要 development.json

    dev_files = list(output_dir.glob('*.development.json'))
    if not dev_files:
        print("  ⚠ 步骤6: 无 *.development.json（单一阶段故障可忽略；复杂/发展性故障须补充）")
        return True  # 不阻断
    print(f"  ✓ 步骤6: {len(dev_files)} 份 development.json")
    return True


def main():
    parser = argparse.ArgumentParser(description="SKILL 流程前置检查")
    parser.add_argument("analysis_dir", help="分析目录（含 段落/ 子目录）")
    parser.add_argument("--devices", nargs="*", help="预期装置名称列表（可选）")
    args = parser.parse_args()

    errors = []
    if not check_step0(args.analysis_dir):
        errors.append("步骤0")
    if not check_step5(args.analysis_dir, args.devices):
        errors.append("步骤5")
    if not check_step6(args.analysis_dir):
        errors.append("步骤6")

    if errors:
        print(f"\n❌ 前置检查失败: {', '.join(errors)} 未完成")
        print("主 Agent 必须停止。请先执行缺失的步骤。")
        sys.exit(1)

    print("\n✅ 前置检查通过，主 Agent 可以生成简报。")
    sys.exit(0)

if __name__ == "__main__":
    main()
