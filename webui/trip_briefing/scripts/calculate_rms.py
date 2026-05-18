# -*- coding: utf-8 -*-
"""
从CSV文件提取RMS统计值和开关量事件

输出文件:
    - 原文件名.rms.csv: 模拟通道RMS统计值（转置格式）
    - 原文件名.events.csv: 状态通道变化事件(绝对时间)

RMS统计值包括:
    - 最大值: RMS数据的最大值
    - 最小值: RMS数据的最小值
    - 最大差值: RMS相邻点之间的最大差值
    - 第一次正突变值: 第一个大于阈值的区间内的最大值
    - 第一次正突变发生时间: 第一次正突变最大值对应的时间
    - 第一次正突变索引号: 第一次正突变最大值对应的索引
    - 第一次负突变值: 第一个小于-阈值的区间内的最小值
    - 第一次负突变发生时间: 第一次负突变最小值对应的时间
    - 第一次负突变索引号: 第一次负突变最小值对应的索引
    - 正负突变间隔时间: 两个极值点的时间间隔(ms)
    - 基准电流相名称: 电流正突变值最大的一相的通道名
    - 基准电流相正突变值: 基准电流相的正突变值
    - 基准电流相正突变时间: 基准电流相的正突变时间
"""
import argparse
import datetime
import os
from pathlib import Path

import numpy as np
import pandas as pd

from webui.trip_briefing.scripts.parse_dat_to_csv import parse_cfg


def is_current_channel(col_name):
    """
    判断一个通道是否是电流通道

    参数:
        col_name: 通道名称

    返回:
        bool: 是否是电流通道
    """
    col_name_lower = str(col_name).lower()
    keywords = ['电流', 'ia', 'ib', 'ic', 'i_a', 'i_b', 'i_c', 'i0']
    return any(keyword in col_name_lower for keyword in keywords)


def is_protection_current_channel(col_name):
    """
    判断一个通道是否是保护电流通道（排除通道电流）

    参数:
        col_name: 通道名称

    返回:
        bool: 是否是保护电流通道
    """
    if not is_current_channel(col_name):
        return False
    # 排除名称中包含"通道"的电流通道
    col_name_lower = str(col_name).lower()
    if '通道' in col_name_lower or 'channel' in col_name_lower:
        return False
    return True


def find_first_positive_mutation(rms_diffs, threshold):
    """
    查找第一次正突变：第一次大于阈值到第一次小于阈值这段区间的最大值

    参数:
        rms_diffs: RMS差值数组
        threshold: 阈值（RMS最大值的20%）

    返回:
        (max_value, max_idx): 区间内的最大值及其索引，如果没有则返回(None, None)
    """
    n = len(rms_diffs)
    i = 0

    # 查找第一个大于阈值的点
    while i < n:
        if rms_diffs[i] > threshold:
            break
        i += 1

    if i >= n:
        return None, None  # 没有找到大于阈值的点

    # 从i开始，查找区间的最大值，直到第一次小于阈值
    start_idx = i
    max_value = rms_diffs[i]
    max_idx = i

    i += 1
    while i < n:
        if rms_diffs[i] < threshold:
            break  # 第一次小于阈值，区间结束
        if rms_diffs[i] > max_value:
            max_value = rms_diffs[i]
            max_idx = i
        i += 1

    return max_value, max_idx


def find_first_negative_mutation(rms_diffs, threshold):
    """
    查找第一次负突变：第一次小于-阈值到第一次大于-阈值这段区间的最小值

    参数:
        rms_diffs: RMS差值数组
        threshold: 阈值（RMS最大值的20%）

    返回:
        (min_value, min_idx): 区间内的最小值及其索引，如果没有则返回(None, None)
    """
    n = len(rms_diffs)
    i = 0
    neg_threshold = -threshold

    # 查找第一个小于-阈值的点
    while i < n:
        if rms_diffs[i] < neg_threshold:
            break
        i += 1

    if i >= n:
        return None, None  # 没有找到小于-阈值的点

    # 从i开始，查找区间的最小值，直到第一次大于-阈值
    start_idx = i
    min_value = rms_diffs[i]
    min_idx = i

    i += 1
    while i < n:
        if rms_diffs[i] > neg_threshold:
            break  # 第一次大于-阈值，区间结束
        if rms_diffs[i] < min_value:
            min_value = rms_diffs[i]
            min_idx = i
        i += 1

    return min_value, min_idx


def find_second_positive_mutation(rms_diffs, threshold, first_pos_end_idx):
    """
    查找第二次正突变：在第一次正突变结束后，等待电流恢复，再检测到正突变

    检测逻辑：正突变1 → 负突变1 → 电流恢复平稳 → 正突变2

    参数:
        rms_diffs: RMS差值数组
        threshold: 阈值
        first_pos_end_idx: 第一次正突变结束的索引

    返回:
        (max_value, max_idx): 第二次正突变的最大值及其索引
    """
    n = len(rms_diffs)
    if first_pos_end_idx is None or first_pos_end_idx >= n:
        return None, None

    # 从第一次正突变结束位置之后开始搜索
    # 需要找到：电流恢复（diff回到阈值以内持续一段时间）后的下一次正突变
    # 恢复判定：连续10个点（约半周波）差值绝对值 < threshold * 0.5
    recovery_length = 10
    recovery_threshold = threshold * 0.5
    search_start = first_pos_end_idx + 1

    i = search_start
    while i < n - recovery_length:
        # 检查是否有一段恢复期
        recovered = True
        for j in range(recovery_length):
            if i + j >= n:
                recovered = False
                break
            if abs(rms_diffs[i + j]) > recovery_threshold:
                recovered = False
                break

        if recovered:
            # 恢复期后，查找第二次正突变
            search_from = i + recovery_length
            return find_first_positive_mutation(rms_diffs[search_from:], threshold)
            # 注意：返回的索引需要加上偏移

        i += 1

    return None, None


def find_second_negative_mutation(rms_diffs, threshold, second_pos_end_idx):
    """
    查找第二次负突变：在第二次正突变之后

    参数:
        rms_diffs: RMS差值数组
        threshold: 阈值
        second_pos_end_idx: 第二次正突变结束的索引

    返回:
        (min_value, min_idx): 第二次负突变的最小值及其索引
    """
    n = len(rms_diffs)
    if second_pos_end_idx is None or second_pos_end_idx >= n:
        return None, None

    search_from = second_pos_end_idx + 1
    if search_from >= n:
        return None, None

    return find_first_negative_mutation(rms_diffs[search_from:], threshold)


def _get_output_path(csv_path, suffix, output_dir=None):
    """根据是否指定output_dir，计算输出文件路径"""
    csv_path = Path(csv_path)
    if output_dir:
        # 保持子目录结构：保护录波/厂站/套别 或 故障录波
        out = Path(output_dir)
        csv_parts = csv_path.parts
        for i, part in enumerate(csv_parts):
            if '保护录波' in part or '故障录波' in part:
                if i + 1 < len(csv_parts):
                    rel = Path(*csv_parts[i + 1:-1])  # 去掉文件名，保留子目录
                    out = out / rel
                break
        os.makedirs(out, exist_ok=True)
        return out / csv_path.with_suffix(suffix).name
    else:
        return csv_path.with_suffix(suffix)


def extract_statistics_and_events(csv_path, output_dir=None, dataframe=None, cfg=None):
    """
    从CSV文件提取RMS统计值和开关量事件

    参数:
        csv_path: CSV/CFG 文件路径（用于推导输出路径）
        output_dir: 输出目录
        dataframe: 可选，直接传入 DataFrame 跳过 CSV 读取
        cfg: 可选，直接传入 Cfg 对象跳过 CFG 解析

    输出:
        - 原文件名.rms.csv: 模拟通道RMS统计值（转置：通道为列，统计项为行）
        - 原文件名.events.csv: 状态通道变化事件
    """
    csv_path = Path(csv_path)

    if cfg is None:
        cfg_path = csv_path.with_suffix('.cfg')
        cfg = parse_cfg(cfg_path)

    if dataframe is not None:
        data = dataframe
    else:
        data = pd.read_csv(csv_path)

    # 保存原始时间ms列（用于RMS中间结果）
    original_time_ms = data['时间ms'].copy()

    # 获取起始时间戳并计算绝对时间
    start_time = datetime.datetime.strptime(cfg.first_data_timestamp, "%d/%m/%Y,%H:%M:%S.%f")
    time_stamp = pd.to_timedelta(data.iloc[:, 1], unit='ms')
    # 使用concat避免fragmentation警告
    data = pd.concat([data.iloc[:, [0]], pd.DataFrame({"绝对时间": time_stamp + start_time}), data.iloc[:, 2:]], axis=1)

    # 保存原始数据副本用于事件提取（不过滤）
    data_for_events = data.copy()

    # === RMS计算：过滤非初始采样率的数据点 ===
    # 获取初始采样率
    if cfg.sampling_rates:
        initial_sample_rate = cfg.sampling_rates[0][0]  # 第一个采样率段的采样率
    else:
        initial_sample_rate = 1200

    # 构建采样率映射：每个采样点对应的采样率
    if cfg.sampling_rates:
        sample_rates_map = {}
        current_start = 1  # 采样序号从1开始
        for rate, end_sample in cfg.sampling_rates:
            for sample_idx in range(current_start, end_sample + 1):
                sample_rates_map[sample_idx] = rate
            current_start = end_sample + 1

        # 标记需要保留的行（采样率为初始采样率）
        rows_to_keep = []
        for idx in data.index:
            sample_no = data.iloc[idx, 0]  # 原始序号
            if sample_rates_map.get(sample_no, initial_sample_rate) == initial_sample_rate:
                rows_to_keep.append(idx)

        # 过滤数据（仅用于RMS计算）
        original_length = len(data)
        data = data.loc[rows_to_keep].reset_index(drop=True)
        filtered_count = original_length - len(data)
        if filtered_count > 0:
            print(f"  RMS计算: 已过滤 {filtered_count} 个非{int(initial_sample_rate)}Hz采样点")

    # 获取采样率
    sample_rate = initial_sample_rate
    samples_per_cycle = int(sample_rate / cfg.frequency)

    # 计算每个通道的RMS统计值
    analog_columns = data.columns[2:2 + cfg.analog_channels].tolist()

    # 计算RMS（使用滚动窗口，前后各半周波）
    # 注意：过滤后数据边界会产生NaN，这些NaN在统计时会自动被dropna()排除
    analog_data = data.iloc[:, 2:2 + cfg.analog_channels] ** 2
    rms_data = np.sqrt(analog_data.rolling(window=samples_per_cycle, center=True).mean())

    # RMS中间结果不再保存（已弃用）

    stats = {
        'RMS最大值': {},
        'RMS最小值': {},
        'RMS最大差值': {},
        '第一次正突变值': {},
        '第一次正突变发生时间': {},
        '第一次正突变索引号': {},
        '第一次负突变值': {},
        '第一次负突变发生时间': {},
        '第一次负突变索引号': {},
        '正负突变间隔时间': {},
        '第二次正突变值': {},
        '第二次正突变发生时间': {},
        '第二次正突变索引号': {},
        '第二次负突变值': {},
        '第二次负突变发生时间': {},
        '第二次负突变索引号': {},
    }

    # 用于存储所有电流通道的信息，用于找出基准电流相
    current_channel_info = []

    # 用于存储所有电流通道的负突变信息，用于找出最早的负突变
    current_neg_mutation_info = []

    # 获取绝对时间列（用于计算差值发生时间）
    abs_times = data["绝对时间"].values

    for col in analog_columns:
        # 获取RMS值及对应的原始索引
        rms_series = rms_data[col].dropna()
        if len(rms_series) == 0:
            continue

        # 获取非空值的原始索引
        valid_indices = rms_series.index.values

        # 1. 最大值和最小值
        max_val = rms_series.max()
        min_val = rms_series.min()

        # 2. 计算前后半周波RMS差值
        # diff[i] = rms[i + half_cycle_samples] - rms[i]
        # 用半周波后的RMS值减去当前RMS值，用于检测故障突变
        rms_values = rms_series.values
        # 半周波对应的RMS点数 = 一个周波的采样点数 / 2
        half_cycle_samples = samples_per_cycle // 2  # 对于9600Hz/50Hz = 96点

        # 构造差值数组（末尾half_cycle_samples个点无法计算）
        rms_diffs = []
        diff_indices = []  # 记录差值对应的RMS索引
        for i in range(len(rms_values) - half_cycle_samples):
            # 计算半周波后的RMS变化量
            diff = rms_values[i + half_cycle_samples] - rms_values[i]
            rms_diffs.append(diff)
            diff_indices.append(i)  # 对应rms_values中的索引

        rms_diffs = np.array(rms_diffs)

        if len(rms_diffs) == 0:
            continue

        # 3. 阈值计算：RMS最大值的20%
        threshold = 0.2 * max_val

        # 4. 第一次正突变及其信息
        first_pos_diff, first_pos_diff_idx = find_first_positive_mutation(rms_diffs, threshold)

        # 5. 第一次负突变及其信息
        first_neg_diff, first_neg_diff_idx = find_first_negative_mutation(rms_diffs, threshold)

        # 保存统计结果
        stats['RMS最大值'][col] = max_val
        stats['RMS最小值'][col] = min_val
        stats['RMS最大差值'][col] = max_val - min_val  # RMS最大值 - RMS最小值

        # 正突变
        first_pos_diff_time = None
        first_pos_diff_original_idx = None
        if first_pos_diff is not None:
            rms_idx_for_first_pos_diff = diff_indices[first_pos_diff_idx]
            first_pos_diff_original_idx = valid_indices[rms_idx_for_first_pos_diff]
            first_pos_diff_time = pd.Timestamp(abs_times[first_pos_diff_original_idx])

            stats['第一次正突变值'][col] = first_pos_diff
            stats['第一次正突变发生时间'][col] = first_pos_diff_time.strftime('%Y-%m-%d %H:%M:%S.%f')
            stats['第一次正突变索引号'][col] = first_pos_diff_original_idx
        else:
            stats['第一次正突变值'][col] = None
            stats['第一次正突变发生时间'][col] = None
            stats['第一次正突变索引号'][col] = None

        # 负突变
        first_neg_diff_time = None
        first_neg_diff_original_idx = None
        if first_neg_diff is not None:
            rms_idx_for_first_neg_diff = diff_indices[first_neg_diff_idx]
            first_neg_diff_original_idx = valid_indices[rms_idx_for_first_neg_diff]
            first_neg_diff_time = pd.Timestamp(abs_times[first_neg_diff_original_idx])

            stats['第一次负突变值'][col] = first_neg_diff
            stats['第一次负突变发生时间'][col] = first_neg_diff_time.strftime('%Y-%m-%d %H:%M:%S.%f')
            stats['第一次负突变索引号'][col] = first_neg_diff_original_idx
        else:
            stats['第一次负突变值'][col] = None
            stats['第一次负突变发生时间'][col] = None
            stats['第一次负突变索引号'][col] = None

        # 时间间隔（毫秒）
        if first_pos_diff is not None and first_neg_diff is not None:
            time_interval_ms = abs(first_pos_diff_original_idx - first_neg_diff_original_idx) * (1000 / sample_rate)
            stats['正负突变间隔时间'][col] = time_interval_ms
        else:
            stats['正负突变间隔时间'][col] = None

        # === 第二次突变检测（重合闸后） ===
        # 检测序列：正突变1 → 负突变1 → 电流恢复 → 正突变2 → 负突变2
        second_pos_diff = None
        second_pos_diff_idx = None
        second_neg_diff = None
        second_neg_diff_idx = None

        if first_pos_diff is not None and first_neg_diff is not None:
            # 第一次正突变结束位置（正突变区间之后）
            first_pos_end = first_pos_diff_idx + half_cycle_samples
            # 在第一次正突变结束后的数据中查找第二次正突变
            search_start = max(first_pos_end, first_neg_diff_idx)
            if search_start < len(rms_diffs):
                sec_pos_val, sec_pos_local_idx = find_second_positive_mutation(
                    rms_diffs, threshold, search_start)
                if sec_pos_val is not None and sec_pos_local_idx is not None:
                    second_pos_diff = sec_pos_val
                    second_pos_diff_idx = search_start + sec_pos_local_idx
                    # 记录第二次正突变时间和索引
                    rms_idx_for_sec_pos = diff_indices[second_pos_diff_idx]
                    sec_pos_original_idx = valid_indices[rms_idx_for_sec_pos]
                    sec_pos_time = pd.Timestamp(abs_times[sec_pos_original_idx])
                    stats['第二次正突变值'][col] = second_pos_diff
                    stats['第二次正突变发生时间'][col] = sec_pos_time.strftime('%Y-%m-%d %H:%M:%S.%f')
                    stats['第二次正突变索引号'][col] = sec_pos_original_idx

                    # 查找第二次负突变
                    sec_neg_val, sec_neg_local_idx = find_second_negative_mutation(
                        rms_diffs, threshold, second_pos_diff_idx + half_cycle_samples)
                    if sec_neg_val is not None and sec_neg_local_idx is not None:
                        second_neg_diff = sec_neg_val
                        second_neg_diff_idx = second_pos_diff_idx + half_cycle_samples + sec_neg_local_idx
                        if second_neg_diff_idx < len(diff_indices):
                            rms_idx_for_sec_neg = diff_indices[second_neg_diff_idx]
                            sec_neg_original_idx = valid_indices[rms_idx_for_sec_neg]
                            sec_neg_time = pd.Timestamp(abs_times[sec_neg_original_idx])
                            stats['第二次负突变值'][col] = second_neg_diff
                            stats['第二次负突变发生时间'][col] = sec_neg_time.strftime('%Y-%m-%d %H:%M:%S.%f')
                            stats['第二次负突变索引号'][col] = sec_neg_original_idx

        # 如果没有检测到第二次突变，填充None
        for key in ['第二次正突变值', '第二次正突变发生时间', '第二次正突变索引号',
                     '第二次负突变值', '第二次负突变发生时间', '第二次负突变索引号']:
            if col not in stats[key]:
                stats[key][col] = None

        # 保存电流通道信息，用于后续找出基准电流相（仅保护电流）
        if is_protection_current_channel(col) and first_pos_diff is not None:
            current_channel_info.append({
                'name': col,
                'pos_diff_value': first_pos_diff,
                'pos_diff_time': first_pos_diff_time
            })

        # 保存电流通道负突变信息，用于找出最早的负突变（仅保护电流）
        if is_protection_current_channel(col) and first_neg_diff is not None:
            current_neg_mutation_info.append({
                'name': col,
                'neg_diff_value': first_neg_diff,
                'neg_diff_time': first_neg_diff_time
            })

    # === 找出基准电流相：电流正突变值最大的一相 ===
    ref_current_name = None
    ref_current_pos_value = None
    ref_current_pos_time = None

    if current_channel_info:
        # 按正突变值降序排序
        current_channel_info.sort(key=lambda x: x['pos_diff_value'], reverse=True)
        ref_channel = current_channel_info[0]
        ref_current_name = ref_channel['name']
        ref_current_pos_value = ref_channel['pos_diff_value']
        ref_current_pos_time = ref_channel['pos_diff_time']

    # === 找出最早的电流负突变：所有电流通道中负突变时间最早的一相 ===
    earliest_neg_current_name = None
    earliest_neg_current_value = None
    earliest_neg_current_time = None

    if current_neg_mutation_info:
        # 按负突变时间升序排序
        current_neg_mutation_info.sort(key=lambda x: x['neg_diff_time'])
        earliest_neg_channel = current_neg_mutation_info[0]
        earliest_neg_current_name = earliest_neg_channel['name']
        earliest_neg_current_value = earliest_neg_channel['neg_diff_value']
        earliest_neg_current_time = earliest_neg_channel['neg_diff_time']

    # 在统计结果中增加基准电流相信息（作为单独的统计项）
    stats['基准电流相名称'] = {}
    stats['基准电流相正突变值'] = {}
    stats['基准电流相正突变时间'] = {}

    # 在统计结果中增加最早电流负突变信息（作为单独的统计项）
    stats['最早负突变电流相名称'] = {}
    stats['最早负突变电流相值'] = {}
    stats['最早负突变电流相时间'] = {}

    # 为每个通道都设置基准电流相信息（所有通道都相同）
    for col in analog_columns:
        stats['基准电流相名称'][col] = ref_current_name
        stats['基准电流相正突变值'][col] = ref_current_pos_value
        if ref_current_pos_time is not None:
            stats['基准电流相正突变时间'][col] = ref_current_pos_time.strftime('%Y-%m-%d %H:%M:%S.%f')
        else:
            stats['基准电流相正突变时间'][col] = None

        # 设置最早电流负突变信息
        stats['最早负突变电流相名称'][col] = earliest_neg_current_name
        stats['最早负突变电流相值'][col] = earliest_neg_current_value
        if earliest_neg_current_time is not None:
            stats['最早负突变电流相时间'][col] = earliest_neg_current_time.strftime('%Y-%m-%d %H:%M:%S.%f')
        else:
            stats['最早负突变电流相时间'][col] = None

    # === 1. 生成电流每相最大正负突变信息文件 ===
    # 按厂站-套别组织，每相分别列出正突变最大值和负突变最小值
    current_mutation_data = []

    # 首先识别A/B/C相电流通道（仅保护电流，排除通道电流）
    phase_info = {}
    for col in analog_columns:
        if is_protection_current_channel(col):
            col_name = str(col).lower()
            # 判断相别
            phase = None
            if 'ia' in col_name or 'a相' in col_name or '_a' in col_name:
                phase = 'A相'
            elif 'ib' in col_name or 'b相' in col_name or '_b' in col_name:
                phase = 'B相'
            elif 'ic' in col_name or 'c相' in col_name or '_c' in col_name:
                phase = 'C相'

            if phase:
                if phase not in phase_info:
                    phase_info[phase] = []
                phase_info[phase].append({
                    'name': col,
                    'pos_value': stats['第一次正突变值'].get(col),
                    'pos_time': stats['第一次正突变发生时间'].get(col),
                    'neg_value': stats['第一次负突变值'].get(col),
                    'neg_time': stats['第一次负突变发生时间'].get(col)
                })

    # 对于每相，选择正突变值最大的通道作为该相的代表
    phase_mutation = {}
    for phase in ['A相', 'B相', 'C相']:
        if phase in phase_info and phase_info[phase]:
            # 按正突变值降序排序，选择最大的
            valid_channels = [ch for ch in phase_info[phase] if ch['pos_value'] is not None]
            if valid_channels:
                valid_channels.sort(key=lambda x: float(x['pos_value']) if x['pos_value'] is not None else -999, reverse=True)
                best_channel = valid_channels[0]
                phase_mutation[phase] = best_channel
            else:
                # 没有正突变，找负突变
                valid_channels_neg = [ch for ch in phase_info[phase] if ch['neg_value'] is not None]
                if valid_channels_neg:
                    valid_channels_neg.sort(key=lambda x: float(x['neg_value']) if x['neg_value'] is not None else 999)
                    best_channel = valid_channels_neg[0]
                    phase_mutation[phase] = best_channel

    # 构建电流突变信息行
    # 从目录结构中提取厂站和套别信息
    station_name = "未知厂站"
    set_name = "未知套别"
    try:
        parts = csv_path.parts
        for i, part in enumerate(parts):
            if '保护录波' in part and i + 2 < len(parts):
                station_name = parts[i + 1]
                set_name = parts[i + 2]
                break
    except:
        pass

    current_mutation_row = {
        '厂站': station_name,
        '套别': set_name
    }

    for phase in ['A相', 'B相', 'C相']:
        if phase in phase_mutation:
            info = phase_mutation[phase]
            # 格式化数值，保留3位小数
            pos_value_formatted = f"{float(info['pos_value']):.3f}" if info['pos_value'] is not None else None
            neg_value_formatted = f"{float(info['neg_value']):.3f}" if info['neg_value'] is not None else None
            current_mutation_row[f'{phase}电流正突变最大值'] = pos_value_formatted
            current_mutation_row[f'{phase}正突变发生时间'] = info['pos_time']
            current_mutation_row[f'{phase}电流负突变最小值'] = neg_value_formatted
            current_mutation_row[f'{phase}负突变发生时间'] = info['neg_time']
        else:
            current_mutation_row[f'{phase}电流正突变最大值'] = None
            current_mutation_row[f'{phase}正突变发生时间'] = None
            current_mutation_row[f'{phase}电流负突变最小值'] = None
            current_mutation_row[f'{phase}负突变发生时间'] = None

    # 保存电流突变信息文件
    current_mutation_df = pd.DataFrame([current_mutation_row])
    current_mutation_path = _get_output_path(csv_path, '.current_mutation.csv', output_dir)
    current_mutation_df.to_csv(current_mutation_path, index=False, encoding='utf-8-sig')
    print(f"  已生成电流突变信息文件: {current_mutation_path}")

    # === 2. 生成简化的 rms.csv（移除基准电流相和最早负突变信息） ===
    # 只保留基本统计项
    basic_stats = {}
    for key in ['RMS最大值', 'RMS最小值', 'RMS最大差值',
                '第一次正突变值', '第一次正突变发生时间', '第一次正突变索引号',
                '第一次负突变值', '第一次负突变发生时间', '第一次负突变索引号',
                '正负突变间隔时间',
                '第二次正突变值', '第二次正突变发生时间', '第二次正突变索引号',
                '第二次负突变值', '第二次负突变发生时间', '第二次负突变索引号']:
        if key in stats:
            basic_stats[key] = stats[key]

    # 构造统计结果DataFrame（转置格式：统计项为行，通道为列）
    stats_df = pd.DataFrame(basic_stats)
    stats_df.index.name = '通道'

    # 转置：通道作为列，统计项作为行
    stats_df = stats_df.T
    stats_df.index.name = '统计项'

    # 格式化数值（保留3位小数）- 根据统计项名称判断
    for idx in stats_df.index:
        # 跳过发生时间、索引号行（但"间隔时间"行需要格式化）
        if '发生时间' not in idx and '索引号' not in idx:
            # 使用apply格式化该行的所有值
            stats_df.loc[idx] = stats_df.loc[idx].apply(
                lambda x: f"{float(x):.3f}" if pd.notna(x) and x is not None else x
            )

    # 保存统计值文件（转置）
    stats_path = _get_output_path(csv_path, '.rms.csv', output_dir)
    try:
        stats_df.to_csv(stats_path, encoding='utf-8-sig')
        print(f"  已生成统计值文件: {stats_path}")
    except PermissionError:
        print(f"  警告: 无法保存统计值文件（文件被占用）: {stats_path}")

    if ref_current_name is not None:
        print(f"  基准电流相: {ref_current_name}, 正突变值: {ref_current_pos_value:.3f}")
    else:
        print(f"  基准电流相: 未找到有效的电流正突变")

    if earliest_neg_current_name is not None:
        print(f"  最早负突变电流相: {earliest_neg_current_name}, 负突变值: {earliest_neg_current_value:.3f}")
    else:
        print(f"  最早负突变电流相: 未找到有效的电流负突变")

    # 检测状态变化事件（变1=动作，变0=返回）- 使用原始数据（不过滤采样率）
    digital_data = data_for_events.iloc[:, 2 + cfg.analog_channels:]
    shifted = digital_data.shift(1).bfill()
    changes_01 = digital_data.ne(shifted) & (digital_data == 1)  # 0→1 变1
    changes_10 = digital_data.ne(shifted) & (digital_data == 0)  # 1→0 变0
    changes_01.set_index(data_for_events["绝对时间"], inplace=True)
    changes_10.set_index(data_for_events["绝对时间"], inplace=True)

    # 变1事件（动作）
    true_positions_01 = changes_01.stack()
    events_01 = true_positions_01[true_positions_01].reset_index()
    events_01[0] = events_01[0].replace(True, '动作')

    # 变0事件（返回）
    true_positions_10 = changes_10.stack()
    events_10 = true_positions_10[true_positions_10].reset_index()
    events_10[0] = events_10[0].replace(True, '返回')

    # 合并并按时间排序
    true_events = pd.concat([events_01, events_10], ignore_index=True)
    true_events.rename(columns={'level_1': '通道名称', 0: '内容', 'level_0': '绝对时间'}, inplace=True)
    true_events.sort_values('绝对时间', inplace=True)
    true_events.reset_index(drop=True, inplace=True)

    # 保存事件文件
    events_path = _get_output_path(csv_path, '.events.csv', output_dir)
    try:
        true_events.to_csv(events_path, index=False)
        print(f"  已生成事件文件: {events_path}")
        print(f"  检测到 {len(true_events)} 个事件")
    except PermissionError:
        print(f"  警告: 无法保存事件文件（文件被占用）: {events_path}")
        print(f"  检测到 {len(true_events)} 个事件")

    return stats_path, events_path


def merge_current_mutation_files(csv_files, output_dir=None):
    """
    合并所有装置的电流突变信息到一个CSV文件

    参数:
        csv_files: 原始CSV文件列表
        output_dir: 输出目录（可选）

    输出:
        在事故文件夹目录生成合并的电流突变信息文件
    """
    all_mutation_data = []

    for csv_file in csv_files:
        csv_path = Path(csv_file)
        # 优先从output_dir读取，否则从输入文件同目录读取
        current_mutation_path = _get_output_path(csv_path, '.current_mutation.csv', output_dir)

        if current_mutation_path.exists():
            try:
                df = pd.read_csv(current_mutation_path, encoding='utf-8-sig')
                all_mutation_data.append(df)
            except Exception as e:
                print(f"  读取电流突变文件失败: {current_mutation_path}, 错误: {e}")

    if all_mutation_data:
        # 合并所有数据
        merged_df = pd.concat(all_mutation_data, ignore_index=True)

        # 确定输出目录
        if output_dir:
            output_path = Path(output_dir) / '电流突变信息汇总.csv'
        else:
            # 取第一个CSV文件所在目录的父目录（事故文件夹）
            first_csv_path = Path(csv_files[0])
        # 尝试找到事故文件夹目录（保护录波的父目录）
        output_dir = first_csv_path.parent
        for part in first_csv_path.parts:
            if '保护录波' in part:
                idx = first_csv_path.parts.index(part)
                if idx + 1 < len(first_csv_path.parts):
                    output_dir = Path(*first_csv_path.parts[:idx])
                break

        output_path = output_dir / '电流突变信息汇总.csv'
        merged_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"\n已生成合并的电流突变信息文件: {output_path}")
    else:
        print("\n未找到任何电流突变信息文件，跳过合并")


def main():
    parser = argparse.ArgumentParser(description='从CSV提取RMS统计值和开关量事件')
    parser.add_argument('csv_files', nargs='+', help='CSV文件路径（可多个）')
    parser.add_argument('--sample-rate', '-s', type=float, default=1200.0,
                        help='采样率Hz (默认: 1200)')
    parser.add_argument('--merge-current-mutation', '-m', action='store_true',
                        help='合并所有装置的电流突变信息到一个CSV文件')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='输出目录（默认：输出到输入文件同目录）')

    args = parser.parse_args()

    print("=" * 60)
    print("RMS统计值和事件提取")
    print("=" * 60)

    for csv_file in args.csv_files:
        csv_path = Path(csv_file)

        if not csv_path.exists():
            print(f"  文件不存在: {csv_path}")
            continue

        print(f"\n处理: {csv_path.name}")
        try:
            extract_statistics_and_events(csv_path, output_dir=args.output)
        except Exception as e:
            print(f"  错误: {e}")
            import traceback
            traceback.print_exc()

    # 合并电流突变信息
    if args.merge_current_mutation:
        merge_current_mutation_files(args.csv_files, output_dir=args.output)

    print("\n" + "=" * 60)
    print("提取完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
