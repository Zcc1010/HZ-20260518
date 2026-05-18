# -*- coding: utf-8 -*-
"""高性能 COMTRADE 解析器 - 直接调用解析函数，避免 subprocess 开销"""
import logging
import struct
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from webui.trip_briefing.scripts.parse_dat_to_csv import parse_cfg, Cfg
from webui.trip_briefing.scripts.calculate_rms import extract_statistics_and_events

logger = logging.getLogger(__name__)


def parse_dat_fast(dat_path: str, cfg: Optional[Cfg] = None):
    """
    高性能二进制 DAT 文件解析。

    使用 numpy.frombuffer 一次性解析整个文件，比逐条 struct.unpack_from 快 10-50x。

    Args:
        dat_path: DAT 文件路径
        cfg: 可选的 Cfg 对象，为 None 时自动从同名 .cfg 加载

    Returns:
        list[tuple]: 采样数据列表 [(sample_no, time_ms, *analog_values, *digital_values), ...]
    """
    dat_path = Path(dat_path)
    cfg_path = dat_path.with_suffix('.cfg')

    if cfg is None:
        cfg = parse_cfg(str(cfg_path))

    if cfg.data_file_type.upper() == 'ASCII':
        # ASCII 格式用原始方法
        from webui.trip_briefing.scripts.parse_dat_to_csv import parse_dat_ascii
        return parse_dat_ascii(str(dat_path), cfg), cfg

    # 二进制格式 - 高性能解析
    with open(dat_path, 'rb') as f:
        data = f.read()

    n_analog = cfg.analog_channels
    n_digital = cfg.digital_channels
    n_digital_words = (n_digital + 15) // 16

    # 每个采样点的字节数: 4(序号) + 4(时间戳) + 2*N(模拟) + 2*M(数字字)
    bytes_per_sample = 8 + 2 * n_analog + 2 * n_digital_words
    num_samples = len(data) // bytes_per_sample

    # 构建 numpy dtype 一次性解析
    dtype_fields = [
        ('sample_no', '<u4'),
        ('timestamp_us', '<u4'),
    ]
    for i in range(n_analog):
        dtype_fields.append((f'analog_{i}', '<i2'))
    for i in range(n_digital_words):
        dtype_fields.append((f'digital_word_{i}', '<u2'))

    dt = np.dtype(dtype_fields)

    # 一次性读取所有采样点
    raw = np.frombuffer(data, dtype=dt, count=num_samples)

    # 向量化解析：比逐样本 Python 循环快 50-60x
    a_arr = np.array([ch['a'] for ch in cfg.analog_channel_info], dtype=np.float64)
    b_arr = np.array([ch['b'] for ch in cfg.analog_channel_info], dtype=np.float64)

    # 采样序号 & 时间戳（微秒→毫秒）
    sample_nos = raw['sample_no'].astype(np.float64)
    timestamps = raw['timestamp_us'].astype(np.float64) / 1000.0

    # 模拟通道缩放：a * raw + b
    analog_data = np.empty((num_samples, n_analog), dtype=np.float64)
    for j in range(n_analog):
        analog_data[:, j] = raw[f'analog_{j}'].astype(np.float64) * a_arr[j] + b_arr[j]

    # 数字通道位解包
    digital_data = np.zeros((num_samples, n_digital), dtype=np.float64)
    for w in range(n_digital_words):
        word = raw[f'digital_word_{w}'].astype(np.uint32)
        for bit in range(16):
            idx = w * 16 + bit
            if idx < n_digital:
                digital_data[:, idx] = (word >> bit) & 1

    # 拼接所有列为 2D numpy 数组（比 .tolist() 快，pd.DataFrame 可直接接受）
    result = np.column_stack([sample_nos, timestamps, analog_data, digital_data])
    return result, cfg


def process_comtrade(cfg_path: str, output_dir: Optional[str] = None) -> bool:
    """
    处理单个 COMTRADE 文件：解析 DAT → 计算 RMS/Events。

    跳过中间 CSV 写入，直接将 DataFrame 传递给 RMS 计算函数，
    显著减少 I/O 开销（对大文件可节省 10+ 秒）。

    Args:
        cfg_path: CFG 文件路径
        output_dir: 输出目录（默认与输入同目录）

    Returns:
        成功返回 True
    """
    import pandas as pd

    cfg_path = Path(cfg_path)
    dat_path = cfg_path.with_suffix('.dat')

    if not dat_path.exists():
        logger.error(f"DAT 文件不存在: {dat_path}")
        return False

    # Step 1: 解析 DAT 文件（返回 numpy 2D 数组）
    cfg = parse_cfg(str(cfg_path))
    samples, _ = parse_dat_fast(str(dat_path), cfg)

    # Step 2: 构造 DataFrame（直接从 numpy 数组，跳过 CSV 中转）
    columns = (
        ['序号', '时间ms']
        + [ch['name'] + ch['unit'] for ch in cfg.analog_channel_info]
        + [ch['name'] for ch in cfg.digital_channel_info]
    )
    # 去重列名（模拟 pd.read_csv 的行为：同名列追加 .1, .2, ...）
    seen: dict[str, int] = {}
    unique_columns = []
    for col in columns:
        if col in seen:
            seen[col] += 1
            unique_columns.append(f"{col}.{seen[col]}")
        else:
            seen[col] = 0
            unique_columns.append(col)
    df = pd.DataFrame(samples, columns=unique_columns)

    # Step 3: 计算 RMS 和 Events（直接传 DataFrame，跳过 CSV 读写）
    try:
        extract_statistics_and_events(
            str(cfg_path), output_dir=output_dir,
            dataframe=df, cfg=cfg,
        )
    except Exception as e:
        logger.error(f"RMS/Events 计算失败 {cfg_path.name}: {e}")
        return False

    return True


def process_all_comtrade(work_dir: Path) -> Tuple[int, int]:
    """
    处理工作目录下所有 COMTRADE 文件。

    Args:
        work_dir: 工作目录

    Returns:
        (成功数, 失败数)
    """
    cfg_files = sorted(work_dir.rglob("*.cfg"))
    if not cfg_files:
        logger.warning("未找到 .cfg 文件")
        return 0, 0

    print(f"  找到 {len(cfg_files)} 个 CFG 文件", flush=True)

    success = 0
    failed = 0
    for cfg in cfg_files:
        try:
            if process_comtrade(str(cfg)):
                success += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"处理失败 {cfg.name}: {e}")
            failed += 1

    print(f"  解析完成: {success} 成功, {failed} 失败", flush=True)
    return success, failed
