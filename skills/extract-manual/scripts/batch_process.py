#!/usr/bin/env python3
"""
批量处理保护装置说明书 PDF：提取 → 切割 → MinerU → VLM → 合并
用法:
    python batch_process.py --pdf-dir "/path/to/pdfs" [--output-dir output] [--skip-existing]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent

def get_device_type(pdf_name):
    """从 PDF 文件名推断设备类型"""
    name = pdf_name.lower()
    if "线路" in name or "输电线路" in name:
        return "线路保护"
    elif "变压器" in name or "主变" in name:
        return "变压器保护"
    elif "母线" in name or "母联" in name or "分段" in name:
        return "母线保护"
    elif "电容器" in name or "电容" in name:
        return "电容器保护"
    else:
        return "其他保护"

def get_model_name(pdf_name):
    """从 PDF 文件名提取型号名"""
    # 去掉.pdf后缀
    name = Path(pdf_name).stem
    return name

def run_cmd(cmd, desc="", timeout=600):
    """运行命令"""
    print(f"  [{desc}] {cmd[:100]}...")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        print(f"  WARNING: {desc} failed: {result.stderr[:200]}")
        return False
    if result.stdout.strip():
        for line in result.stdout.strip().split('\n')[-3:]:
            print(f"    {line}")
    return True

def process_one_pdf(pdf_path, output_dir, skip_existing=False):
    """处理单个 PDF"""
    pdf_path = Path(pdf_path)
    pdf_name = pdf_path.stem
    device_type = get_device_type(pdf_path.name)
    model_name = get_model_name(pdf_path.name)

    # 输出目录
    out_dir = Path(output_dir) / pdf_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # 复制原 PDF
    pdf_dest = out_dir / pdf_path.name
    if not pdf_dest.exists():
        shutil.copy2(pdf_path, pdf_dest)
        print(f"  复制 PDF → {pdf_dest}")

    # 检查是否已有输出
    if skip_existing and (out_dir / "保护原理.md").exists():
        print(f"  跳过（已存在）: {pdf_name}")
        return True

    # 临时目录
    temp_dir = Path("temp") / f"{model_name}_{device_type}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # === 阶段1: markitdown 提取 ===
    md_file = temp_dir / "markitdown.md"
    if not md_file.exists():
        print(f"\n=== 阶段1: markitdown 提取 ===")
        run_cmd(f'markitdown "{pdf_path}" -o "{md_file}"', "markitdown")

    if not md_file.exists():
        print(f"  ERROR: markitdown 提取失败: {pdf_name}")
        return False

    # 提取 markitdown 各段供后续合并用
    md_lines = md_file.read_text(encoding="utf-8").split('\n')
    print(f"  markitdown: {len(md_lines)} 行")

    # === 阶段1.2-1.3: 章节切割 (需要子代理，标记待处理) ===
    sections_file = temp_dir / "sections.json"
    sections_done = (temp_dir / f"{model_name}_{device_type}_概述.md").exists()

    # === 阶段2: MinerU 提取 ===
    mineru_dir = temp_dir / "mineru"
    mineru_md = None
    for f in mineru_dir.glob("*.md"):
        mineru_md = f
        break

    if not mineru_md:
        print(f"\n=== 阶段2: MinerU 提取 ===")
        try:
            run_cmd(
                f'magic-pdf -p "{pdf_path}" -o "{mineru_dir}" -m vlm',
                "MinerU vlm", timeout=1800
            )
            for f in mineru_dir.glob("*.md"):
                mineru_md = f
        except Exception as e:
            print(f"  MinerU 失败: {e}")

    # 检查结果
    results = {
        "pdf": str(pdf_path),
        "output_dir": str(out_dir),
        "temp_dir": str(temp_dir),
        "device_type": device_type,
        "markitdown": md_file.exists(),
        "sections": sections_file.exists(),
        "mineru": mineru_md is not None,
        "split_done": sections_done,
    }

    status_file = temp_dir / "_status.json"
    status_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n--- {pdf_name} ---")
    for k, v in results.items():
        print(f"  {k}: {v}")

    # 标记需要子代理完成的步骤
    pending = []
    if not sections_file.exists():
        pending.append("子代理章节切割")
    if not sections_done:
        pending.append("脚本split_sections.py")
    pending.append("子代理VLM图片识别(Qwen3.6-VL-Plus)")
    pending.append("脚本vlm_replace.py")
    pending.append("子代理合并重写")

    if pending:
        print(f"\n  ⏳ 待手动/子代理完成:")
        for p in pending:
            print(f"    - {p}")

    return True

def main():
    parser = argparse.ArgumentParser(description="批量处理保护装置说明书")
    parser.add_argument("--pdf-dir", required=True, help="PDF 文件目录")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument("--skip-existing", action="store_true", help="跳过已有输出的文件")
    parser.add_argument("--filter", default=None, help="只处理包含此关键字的文件")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    pdfs = sorted(pdf_dir.glob("*.pdf"))

    if args.filter:
        pdfs = [p for p in pdfs if args.filter in p.name]

    print(f"找到 {len(pdfs)} 个 PDF:")
    for p in pdfs:
        print(f"  - {p.name}")

    success = 0
    failed = 0
    for pdf in pdfs:
        try:
            if process_one_pdf(pdf, args.output_dir, args.skip_existing):
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"完成: {success}, 失败: {failed}")

if __name__ == "__main__":
    main()
