# -*- coding: utf-8 -*-
"""
从原始采样CSV提取故障发展过程量化数据

输入:
    - 原始采样CSV（parse_dat_to_csv.py 产出）
    - RMS统计文件（calculate_rms.py 产出，提供突变参考）

输出:
    - 原文件名.development.json：分阶段RMS、相间相关系数、关键事件时刻、发展性判读

用途:
    - Subagent 直接读取 JSON 填入段落「故障发展过程数据」区块
    - 主 Agent 据此写入 §四/§X·五 故障发展过程

算法：
    1. 自动检测故障元件（电压最低侧/电流最大侧）
    2. 分阶段窗口（起始/发展/全盛/切除）的三相V/I的RMS
    3. 全盛期相间相关系数
    4. 关键事件时刻（电流启动/电压塌缩/发展转折/切除）
    5. 发展性判读（发展性/非发展性）
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# 阈值常量
# ============================================================
CURRENT_ONSET_THRESHOLD = 5.0   # 电流启动阈值(A，二次值)
VOLTAGE_COLLAPSE_THRESHOLD = 30.0  # 电压塌缩阈值(V，二次值)
VOLTAGE_NORMAL_MIN = 80.0       # 正常电压下限(V，二次值)
PREFAULT_CHECK_SAMPLES = 100    # 检查有无预故障段的样本数
STAGE_MIN_SPAN_MS = 50          # 阶段最短时间跨度(ms)，小于此值合并


def find_fault_side(df, current_cols, voltage_cols):
    """
    自动定位故障元件（电压最低/电流最大的侧）

    返回:
        dict: { 'side_name': str, 'va': col, 'vb': col, 'vc': col,
                'ia': col, 'ib': col, 'ic': col }
        或 None（找不到）
    """
    # 按前缀分组：找出同时有三相电压和三组电流的侧
    # 先从列名提取前缀（如"低压1分支"、"高压侧"等）
    sides = {}
    for col in voltage_cols:
        # 尝试提取前缀：去掉 "电压"、"Ul1aV" 等后缀
        prefix = _extract_side_prefix(col)
        if prefix:
            sides.setdefault(prefix, {})['voltage_cols'] = sides.get(prefix, {}).get('voltage_cols', []) + [col]

    for col in current_cols:
        prefix = _extract_side_prefix(col)
        if prefix:
            sides.setdefault(prefix, {})['current_cols'] = sides.get(prefix, {}).get('current_cols', []) + [col]

    # 过滤：至少各有3相
    valid_sides = {}
    for prefix, groups in sides.items():
        v_cols = groups.get('voltage_cols', [])
        c_cols = groups.get('current_cols', [])
        if len(v_cols) >= 3 and len(c_cols) >= 3:
            valid_sides[prefix] = {
                'va': v_cols[0], 'vb': v_cols[1], 'vc': v_cols[2],
                'ia': c_cols[0], 'ib': c_cols[1], 'ic': c_cols[2]
            }

    if not valid_sides:
        # 退化为全部通道选取前三组电压/电流
        if len(voltage_cols) >= 3 and len(current_cols) >= 3:
            return {
                'side_name': '故障元件[自动检测]',
                'va': voltage_cols[0], 'vb': voltage_cols[1], 'vc': voltage_cols[2],
                'ia': current_cols[0], 'ib': current_cols[1], 'ic': current_cols[2]
            }
        return None

    # 选择故障侧：电压最低的侧
    best_side = None
    best_min_v = float('inf')
    for prefix, cols in valid_sides.items():
        v_data = df[[cols['va'], cols['vb'], cols['vc']]].values
        min_v = np.min(np.abs(v_data))
        if min_v < best_min_v:
            best_min_v = min_v
            best_side = prefix
            best_cols = cols

    if best_side:
        result = dict(best_cols)
        result['side_name'] = best_side
        return result
    return None


def _extract_side_prefix(col_name):
    """从列名提取侧别前缀（如"低压1分支"、"高压侧"）"""
    col = str(col_name)
    # 常见后缀模式
    suffixes = ['Ul1aV', 'Ul1bV', 'Ul1cV', 'Il1aA', 'Il1bA', 'Il1cA',
                'Ua', 'Ub', 'Uc', 'Ia', 'Ib', 'Ic',
                '电压', '电流', 'UA', 'UB', 'UC', 'IA', 'IB', 'IC',
                'aV', 'bV', 'cV', 'aA', 'bA', 'cA']
    for sfx in suffixes:
        if col.endswith(sfx):
            return col[:-len(sfx)].rstrip('_ ')
    # 如果没有任何后缀匹配，尝试取前几个字符
    if '_' in col:
        return col.rsplit('_', 1)[0]
    return None


def compute_stage_rms(df, cols, t_start, t_end):
    """计算指定时间窗口内各通道的RMS"""
    mask = (df['时间ms'] >= t_start) & (df['时间ms'] <= t_end)
    window = df.loc[mask, cols]
    if len(window) == 0:
        return {c: 0.0 for c in cols}
    return {c: round(float(np.sqrt(np.mean(window[c].values ** 2))), 2) for c in cols}


def detect_stage_boundaries(df, fault_cols, dt_ms):
    """
    检测故障发展阶段边界

    逻辑：
      起始 = 录波起点 → 电流首次越阈值（如无预故障段，起始自 t=0）
      发展 = 两相电流大（第二相卷入）→ 三相均大且电压均塌缩
      全盛 = 三相均大+电压全塌缩 → 录波末尾

    返回:
        dict: { '起始': [t0, t1], '发展': [t1, t2], '全盛': [t2, t3] }
    """
    t = df['时间ms'].values
    va = df[fault_cols['va']].values
    vb = df[fault_cols['vb']].values
    vc = df[fault_cols['vc']].values
    ia = df[fault_cols['ia']].values
    ib = df[fault_cols['ib']].values
    ic = df[fault_cols['ic']].values

    n = len(t)
    stages = {}

    # 1. 电流首次启动时刻（任意相 |I| > CURRENT_ONSET_THRESHOLD）
    onset_idx = 0
    for i in range(n):
        if max(abs(ia[i]), abs(ib[i]), abs(ic[i])) > CURRENT_ONSET_THRESHOLD:
            onset_idx = i
            break
    onset_t = float(t[onset_idx]) if onset_idx > 0 else 0.0

    # 2. 起始阶段 → 发展：第二相卷入（至少两相电流 > 阈值）
    start_start = 0.0  # 起始自录波起点
    development_idx = onset_idx
    found_dev = False
    for i in range(onset_idx + 1, n):
        big_count = sum([
            1 if abs(ia[i]) > CURRENT_ONSET_THRESHOLD * 0.8 else 0,
            1 if abs(ib[i]) > CURRENT_ONSET_THRESHOLD * 0.8 else 0,
            1 if abs(ic[i]) > CURRENT_ONSET_THRESHOLD * 0.8 else 0
        ])
        if big_count >= 2:
            development_idx = i
            found_dev = True
            break
    if not found_dev:
        development_idx = onset_idx
    development_t = float(t[development_idx])

    # 3. 发展 → 全盛：三相电流均 > 阈值 且 三相电压均持续塌缩
    full_idx = development_idx
    for i in range(development_idx + 1, n):
        all_current_big = (
            abs(ia[i]) > CURRENT_ONSET_THRESHOLD and
            abs(ib[i]) > CURRENT_ONSET_THRESHOLD and
            abs(ic[i]) > CURRENT_ONSET_THRESHOLD
        )
        all_voltage_collapse = (
            abs(va[i]) < VOLTAGE_COLLAPSE_THRESHOLD and
            abs(vb[i]) < VOLTAGE_COLLAPSE_THRESHOLD and
            abs(vc[i]) < VOLTAGE_COLLAPSE_THRESHOLD
        )
        if all_current_big and all_voltage_collapse:
            full_idx = i
            break
    full_t = float(t[full_idx])

    stages['起始'] = [round(start_start, 1), round(development_t, 1)]
    stages['发展'] = [round(development_t, 1), round(full_t, 1)]
    stages['全盛'] = [round(full_t, 1), round(float(t[-1]), 1)]

    # 过滤过短阶段（< STAGE_MIN_SPAN_MS），但保留至少两个阶段
    filtered = {}
    for name, (s, e) in stages.items():
        if e - s >= STAGE_MIN_SPAN_MS:
            filtered[name] = [s, e]
    # 如果只剩一个阶段（不太可能），回退到原始三分法
    if len(filtered) < 2:
        return stages
    return filtered


def detect_key_events(df, fault_cols, dt_ms):
    """提取关键事件时刻（电压塌缩需持续判定，避免噪声误检）"""
    t = df['时间ms'].values
    va = df[fault_cols['va']].values
    vb = df[fault_cols['vb']].values
    vc = df[fault_cols['vc']].values
    ia = df[fault_cols['ia']].values
    ib = df[fault_cols['ib']].values
    ic = df[fault_cols['ic']].values
    n = len(t)

    # 持续塌缩所需的最小连续样本数（约5ms窗口）
    min_sustain = max(3, int(5.0 / dt_ms))

    events = {}

    # 电流启动
    onset_phase = None
    onset_t = None
    for i in range(n):
        for ph, val in [('a', ia[i]), ('b', ib[i]), ('c', ic[i])]:
            if abs(val) > CURRENT_ONSET_THRESHOLD:
                onset_phase = ph
                onset_t = float(t[i])
                break
        if onset_t is not None:
            break
    events['current_onset_ms'] = onset_t
    events['current_onset_phase'] = onset_phase

    # 各相电压持续塌缩时刻（连续 min_sustain 个样本绝对值 < 阈值）
    v_collapse = {}
    for ph, v_arr in [('a', va), ('b', vb), ('c', vc)]:
        col_t = None
        sustain_count = 0
        for i in range(n):
            if abs(v_arr[i]) < VOLTAGE_COLLAPSE_THRESHOLD:
                sustain_count += 1
                if sustain_count >= min_sustain and col_t is None:
                    # 回退到持续序列的第一个样本
                    col_t = float(t[i - min_sustain + 1])
            else:
                sustain_count = 0
                col_t = None  # 重置：尚未形成持续塌缩
        v_collapse[ph] = col_t
    events['voltage_collapse_ms'] = v_collapse

    # 切除时刻：优先检测跳闸相关数字通道的上升沿
    clear_t = None
    trip_cols = [c for c in df.columns if '跳' in str(c) or 'trip' in str(c).lower()]
    for tc in trip_cols:
        trip_vals = df[tc].values
        for i in range(1, n):
            if trip_vals[i] == 1 and trip_vals[i - 1] == 0:
                clear_t = float(t[i])
                break
        if clear_t is not None:
            break

    if clear_t is None:
        # 回退：电流归零时刻
        for i in range(n - 1, -1, -1):
            if max(abs(ia[i]), abs(ib[i]), abs(ic[i])) < 1.0:
                clear_t = float(t[i])
            else:
                break
    events['clear_ms'] = clear_t

    return events


def compute_phase_correlation(df, fault_cols, t_start, t_end):
    """计算全盛期三相电流相间相关系数"""
    mask = (df['时间ms'] >= t_start) & (df['时间ms'] <= t_end)
    window = df.loc[mask]
    if len(window) < 10:
        return None

    ia = window[fault_cols['ia']].values
    ib = window[fault_cols['ib']].values
    ic = window[fault_cols['ic']].values

    return {
        'ab': round(float(np.corrcoef(ia, ib)[0, 1]), 3),
        'bc': round(float(np.corrcoef(ib, ic)[0, 1]), 3),
        'ca': round(float(np.corrcoef(ic, ia)[0, 1]), 3)
    }


def make_judgment(stages, phase_corr, fault_cols):
    """生成发展性判读（启发式）"""
    stage_names = list(stages.keys())
    n_stages = len(stage_names)

    if n_stages <= 1:
        return "非发展性故障，单一阶段"

    has_arc = False
    if phase_corr:
        vals = [abs(v) for v in phase_corr.values()]
        if all(v < 0.65 for v in vals):
            has_arc = True

    # 构造演化链
    chain_parts = []
    for name in stage_names:
        chain_parts.append(name)
    chain = "→".join(chain_parts)

    judgment = f"发展性故障：{chain}"
    if has_arc:
        judgment += "；全盛期呈电弧性/不稳定短路特征"
    return judgment


def process_csv(csv_path, output_dir):
    """处理单个CSV文件，生成 development.json"""
    print(f"\n处理: {csv_path.name}")

    df = pd.read_csv(csv_path)
    dt_ms = float(np.median(np.diff(df['时间ms'].values)))
    fs = round(1000.0 / dt_ms, 1)

    # 排除非模拟通道列
    skip_cols = {'时间ms', '采样序号'}
    all_cols = [c for c in df.columns if c not in skip_cols]

    # 分类：电压 / 电流 / 开关量
    voltage_cols = [c for c in all_cols if _is_voltage(c)]
    current_cols = [c for c in all_cols if _is_current(c)]
    digital_cols = [c for c in all_cols if c not in voltage_cols and c not in current_cols]

    # 自动检测故障侧
    fault_cols = find_fault_side(df, current_cols, voltage_cols)
    if fault_cols is None:
        result = {
            'sample_rate_hz': fs,
            'has_prefault': False,
            'error': '未找到可分析的三相电压/电流通道',
            'stages': {},
            'key_events': {},
            'phase_correlation': None,
            'judgment': '无法分析（通道识别失败）'
        }
    else:
        side_name = fault_cols.pop('side_name')

        # 检查有无预故障段（前100样本电压是否正常）
        has_prefault = False
        if len(df) >= PREFAULT_CHECK_SAMPLES:
            va_pre = df[fault_cols['va']].iloc[:PREFAULT_CHECK_SAMPLES]
            vb_pre = df[fault_cols['vb']].iloc[:PREFAULT_CHECK_SAMPLES]
            vc_pre = df[fault_cols['vc']].iloc[:PREFAULT_CHECK_SAMPLES]
            if (np.mean(np.abs(va_pre)) > VOLTAGE_NORMAL_MIN and
                np.mean(np.abs(vb_pre)) > VOLTAGE_NORMAL_MIN and
                np.mean(np.abs(vc_pre)) > VOLTAGE_NORMAL_MIN):
                has_prefault = True

        # 分阶段
        stages = detect_stage_boundaries(df, fault_cols, dt_ms)

        # 各阶段RMS
        stage_rms = {}
        for name, (s, e) in stages.items():
            rms_vals = compute_stage_rms(df,
                [fault_cols['va'], fault_cols['vb'], fault_cols['vc'],
                 fault_cols['ia'], fault_cols['ib'], fault_cols['ic']],
                s, e)
            stage_rms[name] = {
                'window_ms': [round(s, 1), round(e, 1)],
                'Ul1a_rms': rms_vals.get(fault_cols['va'], 0),
                'Ul1b_rms': rms_vals.get(fault_cols['vb'], 0),
                'Ul1c_rms': rms_vals.get(fault_cols['vc'], 0),
                'Il1a_rms': rms_vals.get(fault_cols['ia'], 0),
                'Il1b_rms': rms_vals.get(fault_cols['ib'], 0),
                'Il1c_rms': rms_vals.get(fault_cols['ic'], 0),
            }

        # 关键事件
        key_events = detect_key_events(df, fault_cols, dt_ms)

        # 全盛期相关系数
        phase_corr = None
        if '全盛' in stages:
            full_s, full_e = stages['全盛']
            phase_corr = compute_phase_correlation(df, fault_cols, full_s, full_e)

        # 判读
        judgment = make_judgment(stages, phase_corr, fault_cols)

        result = {
            'sample_rate_hz': fs,
            'has_prefault': has_prefault,
            'fault_side': side_name,
            'fault_cols': {
                'va': fault_cols['va'], 'vb': fault_cols['vb'], 'vc': fault_cols['vc'],
                'ia': fault_cols['ia'], 'ib': fault_cols['ib'], 'ic': fault_cols['ic']
            },
            'stages': stage_rms,
            'key_events': key_events,
            'phase_correlation': phase_corr,
            'judgment': judgment
        }

    # 写入JSON
    out_name = csv_path.stem + '.development.json'
    out_path = Path(output_dir) / out_name
    os.makedirs(output_dir, exist_ok=True)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  → {out_path}")
    print(f"  采样率: {fs}Hz, 预故障段: {'有' if result.get('has_prefault') else '无'}")
    print(f"  判读: {result.get('judgment', 'N/A')}")
    return out_path


def _is_voltage(col_name):
    """判断是否为电压通道"""
    c = str(col_name).lower()
    keywords = ['电压', 'ua', 'ub', 'uc', 'ul', 'u_a', 'u_b', 'u_c', 'u0', '零压', 'v']
    # 排除电流
    if _is_current(col_name):
        return False
    return any(kw in c for kw in keywords)


def _is_current(col_name):
    """判断是否为电流通道"""
    c = str(col_name).lower()
    keywords = ['电流', 'ia', 'ib', 'ic', 'il', 'i_a', 'i_b', 'i_c', 'i0', '零流']
    return any(kw in c for kw in keywords)


def main():
    parser = argparse.ArgumentParser(description='从原始采样CSV提取故障发展过程量化数据')
    parser.add_argument('csv_files', nargs='+', help='原始采样CSV文件路径（可多个）')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='输出目录（默认：项目目录/output）')
    parser.add_argument('--fault-side', '-f', type=str, default=None,
                        help='手动指定故障侧前缀（如"低压1分支"），跳过自动检测')

    args = parser.parse_args()

    print("=" * 60)
    print("故障发展过程分析")
    print("=" * 60)

    for csv_file in args.csv_files:
        csv_path = Path(csv_file)
        if not csv_path.exists():
            print(f"  文件不存在: {csv_path}")
            continue

        output_dir = args.output
        if output_dir is None:
            output_dir = str(Path.cwd() / 'output')

        try:
            process_csv(csv_path, output_dir)
        except Exception as e:
            print(f"  错误: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("分析完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
