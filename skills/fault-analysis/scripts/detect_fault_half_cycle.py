"""
基于半周波差值和的故障突变点检测算法
每周波24点，半周波12点
通过计算前后半周波的差值和，找出故障发生和恢复时刻
"""

import pandas as pd
import numpy as np
from pathlib import Path


def detect_fault_by_half_cycle(csv_file: str, value_column: str = None,
                               samples_per_cycle: int = 24):
    """
    基于半周波差值和检测故障点

    Parameters:
    ----------
    csv_file : str
        CSV文件路径
    value_column : str
        要检测的列名（模拟量通道）
    samples_per_cycle : int
        每周波采样点数，默认24

    Returns:
    -------
    dict
        检测结果
    """
    # 读取数据，尝试多种编码
    encodings = ['utf-8', 'gb18030', 'gbk', 'utf-8-sig']
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv(csv_file, encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if df is None:
        return {'error': '无法读取CSV文件，编码不支持'}

    # 自动选择列
    if value_column is None:
        # 优先选择常见通道
        for col in ['IA', 'UA', 'IB', 'UB', 'IC', 'UC', '保护电流Ia', '保护电流Ib', '保护电流Ic']:
            if col in df.columns:
                value_column = col
                break
        if value_column is None:
            # 取第一个数值列
            for col in df.columns:
                if df[col].dtype in [np.float64, np.int64]:
                    value_column = col
                    break

    if value_column not in df.columns:
        return {'error': f'列 {value_column} 不存在'}

    # 过滤掉目标列为空的行，保留原始索引
    df_valid = df[df[value_column].notna()].copy()
    if len(df_valid) == 0:
        return {'error': f'列 {value_column} 没有有效数据'}

    # 获取原始索引
    original_indices = df_valid.index.values
    values = df_valid[value_column].values
    half_cycle = samples_per_cycle // 2  # 半周波点数

    # 创建原始索引到有效索引的映射
    orig_to_eff = {orig: eff for eff, orig in enumerate(original_indices)}

    # 计算差值和 - 与RMS窗口保持一致
    # RMS计算用的是半周波（12个点），这里计算：
    # 当前半周波(i到i+11) 与 前一个半周波(i-12到i-1) 的差值和
    # diff_sum = sum(values[i:i+half_cycle]) - sum(values[i-half_cycle:i])
    # 简化: value[i] = value[i-12] + value[i+11]
    # 即: diff_sum = values[i+11] - values[i-12]
    diff_sums = []
    indices = []

    for i in range(half_cycle, len(values) - half_cycle):
        # 与RMS窗口一致：当前半周波与前半周波的差值
        diff_sum = values[i + half_cycle - 1] - values[i - half_cycle]

        diff_sums.append(diff_sum)
        indices.append(original_indices[i])  # 记录原始索引位置

    diff_sums = np.array(diff_sums)
    indices = np.array(indices)

    if len(diff_sums) == 0:
        return {'error': '数据长度不足以计算半周波差值'}

    # 找出差值和的最大值和最小值对应的索引
    max_idx = np.argmax(diff_sums)  # 差值和最大的位置
    min_idx = np.argmin(diff_sums)  # 差值和最小的位置

    # 无论升高型还是降低型故障，时间最早的极值点是故障开始，最晚的是故障结束
    if indices[max_idx] < indices[min_idx]:
        # 最大值在前：升高型故障（如电流）
        fault_start_idx = indices[max_idx]
        fault_end_idx = indices[min_idx]
        max_diff = diff_sums[max_idx]
        min_diff = diff_sums[min_idx]
    else:
        # 最小值在前：降低型故障（如电压）
        fault_start_idx = indices[min_idx]
        fault_end_idx = indices[max_idx]
        max_diff = diff_sums[max_idx]
        min_diff = diff_sums[min_idx]

    # 获取对应的值（使用原始索引到有效索引的映射）
    fault_start_eff_idx = orig_to_eff[fault_start_idx]
    fault_end_eff_idx = orig_to_eff[fault_end_idx]
    fault_start_value = values[fault_start_eff_idx]
    fault_end_value = values[fault_end_eff_idx]

    # 计算采样率（假设第一列是时间）
    time_col = None
    for tc in ['相对时间', 'time', 'timestamp', '绝对时间']:
        if tc in df_valid.columns:
            time_col = tc
            break

    if time_col and len(df_valid) > 1:
        time_values = df_valid[time_col].values
        fault_start_time = time_values[fault_start_eff_idx]
        fault_end_time = time_values[fault_end_eff_idx]
        time_unit = 'ms'
    else:
        fault_start_time = fault_start_idx
        fault_end_time = fault_end_idx
        time_unit = 'index'

    # 提取故障期间的值
    fault_values = values[fault_start_eff_idx:fault_end_eff_idx+1]
    fault_max = np.max(fault_values) if len(fault_values) > 0 else fault_start_value
    fault_min = np.min(fault_values) if len(fault_values) > 0 else fault_start_value

    # 计算故障前后的正常值
    before_start = max(0, fault_start_eff_idx - 24)
    before_end = fault_start_eff_idx
    before_values = values[before_start:before_end+1]
    normal_value = np.mean(before_values) if len(before_values) > 0 else 0

    after_start = min(len(values)-1, fault_end_eff_idx + 1)
    after_end = min(len(values)-1, fault_end_eff_idx + 25)
    after_values = values[after_start:after_end+1]
    recovery_value = np.mean(after_values) if len(after_values) > 0 else 0

    return {
        'channel': value_column,
        'fault_start_index': fault_start_idx,  # 原始CSV索引
        'fault_start_time': fault_start_time,
        'fault_start_value': fault_start_value,
        'fault_end_index': fault_end_idx,  # 原始CSV索引
        'fault_end_time': fault_end_time,
        'fault_end_value': fault_end_value,
        'fault_duration_samples': fault_end_eff_idx - fault_start_eff_idx,
        'max_diff_sum': max_diff,
        'min_diff_sum': min_diff,
        'fault_max': fault_max,
        'fault_min': fault_min,
        'normal_value': normal_value,
        'recovery_value': recovery_value,
        'time_unit': time_unit,
        'diff_sums': diff_sums,
        'indices': indices,
    }


def print_result(result: dict):
    """打印检测结果"""
    if 'error' in result:
        print(f"错误: {result['error']}")
        return

    print("=" * 70)
    print(f"【{result['channel']}】突变点检测结果")
    print("=" * 70)
    print("")
    print(f"{'参数':<20}{'值':<30}")
    print("-" * 50)

    # 处理时间显示
    start_time = result['fault_start_time']
    end_time = result['fault_end_time']
    if isinstance(start_time, (int, float)):
        print(f"{'故障发生时刻':<20}{start_time:.1f} {result['time_unit']}")
        print(f"{'故障切除时刻':<20}{end_time:.1f} {result['time_unit']}")
        duration = end_time - start_time
        print(f"{'故障持续':<20}{duration:.1f} {result['time_unit']}")
    else:
        print(f"{'故障发生时刻':<20}{start_time}")
        print(f"{'故障切除时刻':<20}{end_time}")
        print(f"{'故障持续':<20}{result['fault_duration_samples']} 点")

    print(f"{'故障发生索引':<20}{result['fault_start_index']}")
    print(f"{'故障发生值':<20}{result['fault_start_value']:.4f}")
    print(f"{'最大差值和':<20}{result['max_diff_sum']:.4f}")
    print("")
    print(f"{'故障切除索引':<20}{result['fault_end_index']}")
    print(f"{'故障切除值':<20}{result['fault_end_value']:.4f}")
    print(f"{'最小差值和':<20}{result['min_diff_sum']:.4f}")
    print("")
    print(f"{'持续采样点数':<20}{result['fault_duration_samples']}")
    print("")
    print(f"{'故障前正常值':<20}{result['normal_value']:.4f}")
    print(f"{'恢复后值':<20}{result['recovery_value']:.4f}")
    print(f"{'故障期间最大值':<20}{result['fault_max']:.4f}")
    print(f"{'故障期间最小值':<20}{result['fault_min']:.4f}")
    print("")
    if result['normal_value'] != 0:
        print(f"{'突变倍数':<20}{result['fault_max'] / result['normal_value']:.2f}x")
    print("=" * 70)


def detect_all_channels(csv_file: str, samples_per_cycle: int = 24):
    """检测所有通道"""
    # 尝试多种编码
    encodings = ['utf-8', 'gb18030', 'gbk', 'utf-8-sig']
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv(csv_file, encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if df is None:
        print(f"错误: 无法读取CSV文件")
        return {}

    # 找出模拟量通道
    analog_channels = []
    skip_cols = ['相对时间', '绝对时间', 'time', 'timestamp']

    for col in df.columns:
        if col not in skip_cols:
            if df[col].dtype in [np.float64, np.int64]:
                analog_channels.append(col)

    print(f"文件: {Path(csv_file).name}")
    print(f"采样点数: {len(df)}")
    print(f"每周波点数: {samples_per_cycle}")
    print(f"检测通道数: {len(analog_channels)}")
    print("")

    results = {}
    for ch in analog_channels:
        result = detect_fault_by_half_cycle(csv_file, ch, samples_per_cycle)
        if 'error' not in result:
            results[ch] = result
            print_result(result)
            print("")

    return results


def save_results_to_csv(csv_file: str, results: dict):
    """保存检测结果到CSV文件"""
    # 保存汇总结果
    summary_file = Path(csv_file).with_suffix('.fault_detection.csv')

    rows = []
    for ch, result in results.items():
        rows.append({
            '通道': result['channel'],
            '故障发生时刻': result['fault_start_time'],
            '故障发生索引': result['fault_start_index'],
            '故障发生值': result['fault_start_value'],
            '故障切除时刻': result['fault_end_time'],
            '故障切除索引': result['fault_end_index'],
            '故障切除值': result['fault_end_value'],
            '故障持续时间(点)': result['fault_duration_samples'],
            '最大差值和': result['max_diff_sum'],
            '最小差值和': result['min_diff_sum'],
            '故障前正常值': result['normal_value'],
            '恢复后值': result['recovery_value'],
            '故障期间最大值': result['fault_max'],
            '故障期间最小值': result['fault_min'],
        })

    df_out = pd.DataFrame(rows)
    df_out.to_csv(summary_file, index=False, encoding='utf-8-sig')
    print(f"\n汇总结果已保存到: {summary_file}")

    # 保存每个采样点的差值详细数据
    detail_file = Path(csv_file).with_suffix('.fault_detail.csv')

    detail_rows = []
    for ch, result in results.items():
        indices = result['indices']
        diff_sums = result['diff_sums']
        for idx, diff_val in zip(indices, diff_sums):
            detail_rows.append({
                '通道': result['channel'],
                '索引位置': idx,
                '差值和': diff_val,
            })

    df_detail = pd.DataFrame(detail_rows)
    df_detail.to_csv(detail_file, index=False, encoding='utf-8-sig')
    print(f"详细数据已保存到: {detail_file}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python detect_fault_half_cycle.py <rms_file.csv> [channel_name]")
        print("")
        print("示例:")
        print("  python detect_fault_half_cycle.py rms.csv")
        print("  python detect_fault_half_cycle.py rms.csv IA")
        print("  python detect_fault_half_cycle.py rms.csv IA --samples 48")
        sys.exit(0)

    csv_file = sys.argv[1]
    channel = sys.argv[2] if len(sys.argv) > 2 else None
    samples = 24

    # 解析参数
    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--samples' and i+1 < len(sys.argv):
            samples = int(sys.argv[i+1])
            i += 2
        else:
            i += 1

    if channel:
        result = detect_fault_by_half_cycle(csv_file, channel, samples)
        print_result(result)
    else:
        results = detect_all_channels(csv_file, samples)
        # 保存结果到CSV
        if results:
            save_results_to_csv(csv_file, results)
