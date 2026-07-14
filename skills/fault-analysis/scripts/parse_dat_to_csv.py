# -*- coding: utf-8 -*-
import argparse
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pandas as pd


@dataclass
class Cfg:
    station_name: str = ''
    rec_dev_id: str = ''
    rev_year: str = ''
    total_channels: int = 0
    analog_channels: int = 0
    digital_channels: int = 0
    analog_channel_info: List[dict] = field(default_factory=list)
    digital_channel_info: List[dict] = field(default_factory=list)
    frequency: float = 0.0
    sampling_rates: List[tuple] = field(default_factory=list)
    first_data_timestamp: str = ''
    trigger_timestamp: str = ''
    data_file_type: str = ''
    time_multiplier: float = 1.0


def detect_cfg_format(lines):
    """
    检测CFG格式版本

    返回:
        tuple: (rev_year, format_type)
        - rev_year: 版本年号 ('1991', '1999', '2013')
        - format_type: 'old' (1991只有2字段) 或 'new' (1999/2013有3字段)
    """
    parts = lines[0].strip().split(',')
    if len(parts) >= 3:
        return parts[2], 'new'
    else:
        # 1991格式只有站名和设备ID，无版本年号字段
        return '1991', 'old'


def parse_cfg(cfg_path):
    """
    解析COMTRADE CFG文件，返回Cfg对象
    使用gb18030编码和errors='replace'处理中文

    参数:
        cfg_path (str): CFG配置文件路径

    返回:
        Cfg: 包含所有CFG信息的对象
    """
    cfg = Cfg()
    with open(cfg_path, 'r', encoding='gb18030', errors='replace') as f:
        lines = f.readlines()

    # 检测格式版本
    rev_year, format_type = detect_cfg_format(lines)

    # 第1行：站名，设备ID，版本年号
    parts = lines[0].strip().split(',')
    cfg.station_name = parts[0]  # 厂站位置名称或文件形成的位置名称
    cfg.rec_dev_id = parts[1] if len(parts) > 1 else ''  # 装置的标识编号或名称
    cfg.rev_year = rev_year  # 由标准版本的年号规定的COMTRADE标准文件版本，只可是1991，1999和2013中的一个

    if format_type == 'old':
        print(f"  [警告] CFG文件为1991格式，缺少版本年号字段，部分字段可能缺失")

    # 第2行：总通道数，模拟通道数，数字通道数
    ch_line = lines[1].strip()
    match = re.search(r'(\d+)A,\s*(\d+)D', ch_line)

    cfg.analog_channels = int(match.group(1))
    cfg.digital_channels = int(match.group(2))
    cfg.total_channels = cfg.analog_channels + cfg.digital_channels

    # 解析模拟通道信息
    line_idx = 2
    for i in range(cfg.analog_channels):
        parts = lines[line_idx].strip().split(',')
        # 处理1991格式可能缺少的字段
        a_val = float(parts[5]) if len(parts) > 5 and parts[5] else 1.0
        b_val = float(parts[6]) if len(parts) > 6 and parts[6] else 0.0
        primary_val = float(parts[10]) if len(parts) > 10 and parts[10] else 1.0
        secondary_val = float(parts[11]) if len(parts) > 11 and parts[11] else 1.0
        ps_val = parts[12] if len(parts) > 12 else 'S'

        ch_info = {
            'index': int(parts[0]),  # 模拟通道索引号
            'name': parts[1],  # 通道标识
            'phase': parts[2] if len(parts) > 2 else '',  # 通道相别标识（A\B\C）
            'component': parts[3] if len(parts) > 3 else '',  # 被监视的电路元件
            'unit': parts[4] if len(parts) > 4 else '',  # 通道单位
            'a': a_val,  # 通道增益系数
            'b': b_val,  # 通道偏移量
            'skew': parts[7] if len(parts) > 7 else '0',  # 从采样时刻开始的通道时滞 $(\mu s)$
            'min': int(parts[8]) if len(parts) > 8 and parts[8] else -1000000,  # 该通道数值范围的最小值
            'max': int(parts[9]) if len(parts) > 9 and parts[9] else 1000000,  # 该通道数值范围的最大值
            'primary': primary_val,  # 通道电压或电流互感器变比一次系数
            'secondary': secondary_val,  # 通道电压或电流互感器变比二次系数
            'ps': ps_val,  # 一次(P)还是二次(S)值的标识
        }
        cfg.analog_channel_info.append(ch_info)
        line_idx += 1

    # 解析数字通道（从模拟通道之后开始）
    for i in range(cfg.digital_channels):
        if line_idx >= len(lines):
            # 数字通道信息不足，创建默认通道
            for j in range(cfg.digital_channels - i):
                cfg.digital_channel_info.append({
                    'index': i + j + 1,
                    'name': f'数字通道{i + j + 1}',
                    'ph': '',
                    'ccbm': '',
                    'y': 0
                })
            print(f"  [警告] 数字通道信息不足，缺少{cfg.digital_channels - i}个通道定义")
            break
        parts = lines[line_idx].strip().split(',')
        ch = {
            'index': int(parts[0]) if parts[0] else i + 1,  # 状态通道索引编号
            'name': parts[1] if len(parts) > 1 else f'数字通道{i + 1}',  # 通道名
            'ph': parts[2] if len(parts) > 2 else '',  # 通道相别标识
            'ccbm': parts[3] if len(parts) > 3 else '',  # 被监视电路元件
            'y': int(parts[4]) if len(parts) > 4 and parts[4] else 0  # 状态通道正常状态
        }
        cfg.digital_channel_info.append(ch)
        line_idx += 1

    # 线路频率定义行
    if line_idx < len(lines):
        try:
            cfg.frequency = float(lines[line_idx])
        except ValueError:
            cfg.frequency = 50.0  # 默认50Hz
            print(f"  [警告] 线路频率解析失败，使用默认值50Hz")
    else:
        cfg.frequency = 50.0
    line_idx += 1

    # 采样率数量
    if line_idx < len(lines):
        sampling_rate_count = int(lines[line_idx]) if lines[line_idx].strip().isdigit() else 1
    else:
        sampling_rate_count = 1
    line_idx += 1

    # 获取采样率
    for i in range(sampling_rate_count):
        if line_idx >= len(lines):
            cfg.sampling_rates.append((1200.0, 0))  # 默认采样率
            break
        parts = lines[line_idx].strip().split(',')
        if len(parts) >= 2:
            try:
                rate = float(parts[0])
                end_sample = int(parts[1])
                cfg.sampling_rates.append((rate, end_sample))
            except ValueError:
                cfg.sampling_rates.append((1200.0, 0))
        else:
            cfg.sampling_rates.append((1200.0, 0))
        line_idx += 1

    # 日期/时标
    if line_idx < len(lines):
        cfg.first_data_timestamp = lines[line_idx].strip()
    else:
        cfg.first_data_timestamp = '01/01/00,00:00:00.000'
        print(f"  [警告] 首数据时标缺失")
    line_idx += 1

    if line_idx < len(lines):
        cfg.trigger_timestamp = lines[line_idx].strip()
    else:
        cfg.trigger_timestamp = '01/01/00,00:00:00.000'
    line_idx += 1

    # 数据文件类型
    if line_idx < len(lines):
        cfg.data_file_type = lines[line_idx].strip()
    else:
        cfg.data_file_type = 'BINARY'
        print(f"  [警告] 数据文件类型缺失，假定为BINARY")
    line_idx += 1

    # 时标倍率因子（可选，默认为1）
    if line_idx < len(lines):
        try:
            cfg.time_multiplier = float(lines[line_idx])
        except ValueError:
            cfg.time_multiplier = 1.0
    else:
        cfg.time_multiplier = 1.0

    return cfg


def parse_dat_ascii(dat_path, cfg):
    """
    解析ASCII格式的DAT文件

    ASCII格式：每行一个采样点，逗号分隔
    格式：n,timestamp,A1,A2,...,Ak,D1,D2,...,Dm

    参数:
        dat_path (str): DAT文件路径
        cfg (Cfg): CFG配置对象

    返回:
        list: 二维列表，每行为一个采样点的所有通道值
    """
    samples = []
    with open(dat_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            sample = []
            # 采样序号
            sample.append(int(parts[0]))
            # 时间戳（微秒转毫秒）
            timestamp_us = int(parts[1]) if parts[1] else 0
            sample.append(timestamp_us / 1000)
            # 模拟通道值
            for j in range(cfg.analog_channels):
                raw_value = float(parts[2 + j]) if parts[2 + j] else 0
                actual_value = raw_value * cfg.analog_channel_info[j]['a'] + cfg.analog_channel_info[j]['b']
                sample.append(actual_value)
            # 状态通道值
            for j in range(cfg.digital_channels):
                idx = 2 + cfg.analog_channels + j
                val = int(parts[idx]) if idx < len(parts) and parts[idx] else 0
                sample.append(val)
            samples.append(sample)
    return samples


def parse_dat_binary(dat_path, cfg):
    """
    解析BINARY格式的DAT文件

    COMTRADE BINARY格式每个采样点包含：
    - 4字节：采样序号
    - 4字节：时间戳（微秒）
    - 2字节×N：模拟通道值（16位有符号整数）
    - 2字节×M：数字通道值（打包）

    参数:
        dat_path (str): DAT文件路径
        cfg (Cfg): CFG配置对象

    返回:
        list: 二维列表，每行为一个采样点的所有通道值
    """
    # 读取二进制数据
    with open(dat_path, 'rb') as f:
        data = f.read()

    # 计算每个采样点占用的字节数
    bytes_per_sample = 8 + 2 * cfg.analog_channels + 2 * ((cfg.digital_channels + 15) // 16)
    # 总采样点数
    num_samples = len(data) // bytes_per_sample

    samples = []
    format_str = '<I I ' + 'h' * cfg.analog_channels + 'H' * ((cfg.digital_channels + 15) // 16)
    # 遍历每个采样点
    for i in range(num_samples):
        sample = []
        offset = i * bytes_per_sample
        unpacked_data = struct.unpack_from(format_str, data, offset)
        sample.append(unpacked_data[0])
        sample.append(unpacked_data[1] / 1000)
        offset = 2
        # 读取模拟通道值
        for j in range(cfg.analog_channels):
            actual_value = (unpacked_data[j + offset] * cfg.analog_channel_info[j]['a']
                            + cfg.analog_channel_info[j]['b'])  # 应用缩放和偏移
            sample.append(actual_value)
        offset += cfg.analog_channels
        digital_states = []
        # 读取状态通道值
        while offset < len(unpacked_data):
            word = unpacked_data[offset]
            for bit in range(16):
                if len(digital_states) < cfg.digital_channels:
                    digital_states.append((word >> bit) & 1)
            offset += 1
        sample.extend(digital_states)
        samples.append(sample)
    return samples


def parse_dat(dat_path, output_dir=None):
    """
    解析DAT文件（自动识别ASCII或BINARY格式），返回采样值列表

    参数:
        dat_path (str): DAT文件路径
        output_dir (str, optional): 输出目录，为None时输出到输入文件同目录

    返回:
        DataFrame: 包含所有采样点的数据框
    """
    dat_path = Path(dat_path)
    cfg_path = dat_path.with_suffix('.cfg')
    cfg = parse_cfg(cfg_path)

    # 根据CFG中的数据类型选择解析方法
    data_type = cfg.data_file_type.upper()
    if data_type == 'ASCII':
        samples = parse_dat_ascii(dat_path, cfg)
    else:  # BINARY, BINARY32, FLOAT32
        samples = parse_dat_binary(dat_path, cfg)

    columns = ['序号', '时间ms'] + [ch['name'] + ch['unit'] for ch in cfg.analog_channel_info] + \
              [ch['name'] for ch in cfg.digital_channel_info]
    df = pd.DataFrame(samples, columns=columns)
    if output_dir:
        csv_path = Path(output_dir) / dat_path.with_suffix('.csv').name
    else:
        csv_path = dat_path.with_suffix('.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    return df


def main():
    """
    主函数：解析命令行参数并执行解析流程
    """
    parser = argparse.ArgumentParser(description='COMTRADE DAT文件原始采样点解析')
    parser.add_argument('cfg_files', nargs='+', help='CFG配置文件路径（可多个）')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='输出目录（默认：项目目录/output，保持原路径结构）')

    args = parser.parse_args()

    print("=" * 115)
    print("COMTRADE DAT原始采样点解析")
    print("=" * 115)

    for cfg_file in args.cfg_files:
        cfg_path = Path(cfg_file).with_suffix('.cfg')
        dat_path = cfg_path.with_suffix('.dat')

        # 检查文件是否存在
        if not cfg_path.exists():
            print(f"\n错误: CFG文件不存在: {cfg_path}")
            continue

        if not dat_path.exists():
            print(f"\n错误: DAT文件不存在: {dat_path}")
            continue

        print(f"\n处理: {cfg_path.name}")
        print(f"CFG文件: {cfg_path}")
        print(f"DAT文件: {dat_path}")

        try:
            # 解析DAT文件获取通道信息和采样率
            output_dir = args.output
            if output_dir is None:
                # 默认输出到当前工作目录下的 output，保持原路径结构
                output_dir = str(Path.cwd() / 'output')
            else:
                # 保持子目录结构：从cfg路径提取 厂站/套别 相对路径
                cfg_parts = Path(cfg_path).parts
                for i, part in enumerate(cfg_parts):
                    if '保护录波' in part or '故障录波' in part:
                        # 取 保护录波/厂站/套别 或 故障录波 子路径
                        rel_parts = cfg_parts[i:]
                        if len(rel_parts) > 1:
                            output_dir = str(Path(output_dir) / Path(*rel_parts[1:-1]))
                        break
            os.makedirs(output_dir, exist_ok=True)
            df = parse_dat(str(dat_path), output_dir=output_dir)

            csv_name = Path(cfg_path).with_suffix('.csv').name
            print(f"  通道数: {len(df.columns)}, 采样点数: {df.shape[0]}")
            print(f"  已生成: {csv_name}")
        except Exception as e:
            print(f"  错误: {e}")

    print("\n" + "=" * 115)
    print("解析完成")
    print("=" * 115)


if __name__ == '__main__':
    main()
