# -*- coding: utf-8 -*-
"""
多装置时序对比工具

读取多个装置的events.csv文件，生成按绝对时间排序的时序对比表。

输出:
    - 多装置时序对比表.csv: 包含绝对时间(微秒)、相对时间(ms,3位小数)、各装置事件
"""
import argparse
import csv
from pathlib import Path
from datetime import datetime


def parse_event_csv(csv_path):
    """
    读取事件CSV文件

    参数:
        csv_path: 事件CSV文件路径（由calculate_rms.py生成）

    返回:
        device_name: 装置名称
        events: 事件列表，每个事件包含绝对时间、通道名称、内容
    """
    events = []
    # 去掉 .events 后缀获取装置名（stem已去掉.csv，只需去掉.events）
    device_name = csv_path.stem.removesuffix('.events')

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        headers = next(reader)

        for row in reader:
            if not row or len(row) < 3:
                continue
            # 解析绝对时间
            time_str = row[0]
            try:
                # 尝试解析多种时间格式
                for fmt in ['%Y-%m-%d %H:%M:%S.%f', '%Y/%m/%d %H:%M:%S.%f',
                           '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S']:
                    try:
                        abs_time = datetime.strptime(time_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue

                events.append({
                    'abs_time': abs_time,
                    'channel': row[1],
                    'content': row[2]
                })
            except (ValueError, IndexError):
                continue

    return device_name, events


def compare_devices(csv_files, output_path):
    """
    对比多装置事件，生成时序对比表

    参数:
        csv_files: 事件CSV文件列表
        output_path: 输出CSV文件路径
    """
    device_events = {}

    # 读取所有事件文件
    for csv_path in csv_files:
        if not csv_path.exists():
            print(f"  警告: 文件不存在，跳过: {csv_path}")
            continue

        device_name, events = parse_event_csv(csv_path)
        if events:
            device_events[device_name] = events
            print(f"  {device_name}: {len(events)} 个事件")

    if not device_events:
        print("  错误: 没有有效的事件数据")
        return

    # 收集所有事件并按绝对时间排序
    all_events = []
    for device_name, events in device_events.items():
        for evt in events:
            all_events.append({
                'device': device_name,
                'abs_time': evt['abs_time'],
                'channel': evt['channel'],
                'content': evt['content']
            })

    # 按绝对时间排序
    all_events.sort(key=lambda x: x['abs_time'])

    # 获取第一个事件时间作为基准
    base_time = all_events[0]['abs_time']

    # 生成对比表
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)

        # 表头（装置名称不带 .events 后缀）
        device_names = list(device_events.keys())
        headers = ['绝对时间', '相对时间(ms)'] + list(device_names)
        writer.writerow(headers)

        # 输出每个时间点的事件
        for evt in all_events:
            # 相对时间保留3位小数
            rel_time_ms = round((evt['abs_time'] - base_time).total_seconds() * 1000, 3)

            # 绝对时间精确到微秒
            row = [
                evt['abs_time'].strftime('%Y-%m-%d %H:%M:%S.%f'),
                rel_time_ms
            ]

            # 为每个装置填充该时间点的事件
            for device_name in device_names:
                if evt['device'] == device_name:
                    row.append(f"{evt['channel']}: {evt['content']}")
                else:
                    row.append('')

            writer.writerow(row)

    print(f"\n  已生成对比表: {output_path}")
    print(f"  时间范围: {all_events[0]['abs_time'].strftime('%Y-%m-%d %H:%M:%S.%f')} ~ "
          f"{all_events[-1]['abs_time'].strftime('%Y-%m-%d %H:%M:%S.%f')}")
    print(f"  总事件数: {len(all_events)}")


def main():
    parser = argparse.ArgumentParser(description='多装置时序对比')
    parser.add_argument('csv_files', nargs='+', help='事件CSV文件列表（*.events.csv）')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='输出文件路径(默认为当前目录/多装置时序对比表.csv)')

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
        output_path = output_dir / '多装置时序对比表.csv'

    print("=" * 60)
    print("多装置时序对比")
    print("=" * 60)
    print(f"输入文件数: {len(csv_files)}")
    print(f"输出文件: {output_path.absolute()}")
    print()

    compare_devices(csv_files, output_path)

    print("\n" + "=" * 60)
    print("对比完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
