# -*- coding: utf-8 -*-
"""
合并所有装置的电流突变信息

读取多个装置的 .current_mutation.csv 文件，合并到一个文件中。

输出:
    - 电流突变信息汇总.csv: 包含所有装置的每相电流正负突变信息
"""
import argparse
import csv
from pathlib import Path


def parse_current_mutation_csv(csv_path):
    """
    读取电流突变CSV文件

    参数:
        csv_path: 电流突变CSV文件路径（由calculate_rms.py生成）

    返回:
        data: 包含厂站、套别和各相电流突变信息的字典
    """
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if rows:
            return rows[0]
    return None


def merge_current_mutations(csv_files, output_path):
    """
    合并多装置电流突变信息

    参数:
        csv_files: 电流突变CSV文件列表
        output_path: 输出CSV文件路径
    """
    all_data = []

    # 读取所有电流突变文件
    for csv_path in csv_files:
        if not csv_path.exists():
            print(f"  警告: 文件不存在，跳过: {csv_path}")
            continue

        data = parse_current_mutation_csv(csv_path)
        if data:
            all_data.append(data)
            print(f"  已读取: {csv_path.name}")

    if not all_data:
        print("  错误: 没有有效的电流突变数据")
        return

    # 确定所有字段
    fieldnames = ['厂站', '套别']
    for phase in ['A相', 'B相', 'C相']:
        fieldnames.extend([
            f'{phase}电流正突变最大值',
            f'{phase}正突变发生时间',
            f'{phase}电流负突变最小值',
            f'{phase}负突变发生时间'
        ])

    # 生成合并文件
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for data in all_data:
            writer.writerow(data)

    print(f"\n  已生成电流突变信息汇总: {output_path}")
    print(f"  共包含 {len(all_data)} 套装置")


def main():
    parser = argparse.ArgumentParser(description='合并多装置电流突变信息')
    parser.add_argument('csv_files', nargs='+', help='电流突变CSV文件列表（*.current_mutation.csv）')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='输出文件路径(默认为项目目录/output/电流突变信息汇总.csv)')

    args = parser.parse_args()

    csv_files = [Path(f) for f in args.csv_files]

    # 确定输出路径
    if args.output:
        output_path = Path(args.output)
    else:
        # 默认输出到项目目录下的output
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent.parent.parent
        output_dir = project_root / 'output'
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / '电流突变信息汇总.csv'

    print("=" * 60)
    print("合并多装置电流突变信息")
    print("=" * 60)
    print(f"输入文件数: {len(csv_files)}")
    print(f"输出文件: {output_path.absolute()}")
    print()

    merge_current_mutations(csv_files, output_path)

    print("\n" + "=" * 60)
    print("合并完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
