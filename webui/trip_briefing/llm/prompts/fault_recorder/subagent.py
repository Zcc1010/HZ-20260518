# -*- coding: utf-8 -*-
"""故障录波 Subagent Prompt"""


def build_subagent_prompt(
    hdr_content: str,
    rms_content: str,
    events_content: str,
    station: str,
    set_number: str = "",
) -> str:
    label = f"故障录波_{station}" if not set_number else f"故障录波_{station}_{set_number}"
    return f"""# 故障录波 Subagent Prompt 模板

## 任务

给定故障录波器的录波文件（hdr + rms.csv + events.csv），按 HDR/Events/RMS 三个区块提取关键信息，生成标准化的 Markdown 段落。

## 设备信息

- 厂站: {station}

## 输入数据

### HDR 文件内容
{hdr_content if hdr_content else '[HDR文件缺失]'}

### RMS CSV 文件内容
{rms_content if rms_content else '[RMS文件缺失]'}

### Events CSV 文件内容
{events_content if events_content else '[Events文件缺失]'}

## 输出格式

**重要：直接输出 Markdown 内容，不要用 ```markdown``` 代码围栏包裹。**

严格按照以下 Markdown 格式输出。有数据的字段填写实际值，无数据的标注`[无数据]`。

**精简原则**：
- 当整个区块无数据时（如 HDR 文件缺失），只写一行 `[HDR文件缺失]`，**不要**逐字段列出 [无数据]
- Events 表只列出"动作"事件，省略"返回"事件
- RMS 信息只列出有突变值的通道

## {label}

**录波器型号**: {{型号}}
**故障时间**: {{年}}-{{月}}-{{日}} {{时}}:{{分}}:{{秒}}.{{毫秒}}

### HDR信息
（如果 HDR 有内容：正常列出设备信息、TripInfo、FaultInfo、定值信息）
（如果 HDR 缺失或内容为空：只写 `[HDR文件缺失]`，不要展开子字段）

### Events信息
| 绝对时间 | 通道名称 | 内容 |
|----------|----------|------|

### RMS信息
**电流RMS最大值**（一次值）: IA: {{一次值}}kA（二次值{{值}}A）, IB: ..., IC: ..., 3I0: ...
（无CT变比时只显示二次值: IA: {{值}}A [无CT变比]）
**电压RMS最小值**（一次值）: UA: {{一次值}}kV（二次值{{值}}V）, UB: ..., UC: ..., 3U0: ...
（无PT变比时只显示二次值: UA: {{值}}V [无PT变比]）

**电流电压突变**:
**第一次突变**（故障发生时）:
- {{通道名}}正突变: +{{值}}A @ HH:MM:SS.mmm
- {{通道名}}负突变: -{{值}}A @ HH:MM:SS.mmm
- ...（列出所有突变幅度超过阈值的通道）

**第二次突变**（重合后，如有）:
- {{通道名}}正突变: +{{值}}A @ HH:MM:SS.mmm
- ...（无第二次突变时不输出此分组）

> 数据来源: {{hdr文件名}} + {{rms文件名}} + {{events文件名}}

## 关键提取规则

1. 厂站名：{label}
2. 录波器型号：从 HDR `<DeviceInfo>` 提取
3. 故障时间：从 HDR `<FaultStartTime>` 提取
4. TripInfo：从 HDR `<TripInfo>` 提取，偏移量转绝对时间
- **严禁输出相对时间**（如 `0ms`、`15ms`），所有时间必须为绝对时间 `HH:MM:SS.mmm`
5. 定值信息：从 HDR `<FaultInfo>` 或 `<TripInfo>` 提取故障测距和相别
6. Events信息：从 events.csv 提取
7. RMS信息：从 rms.csv 提取电流最大值、电压最小值、突变（按第一次/第二次分组），全部换算为一次值
8. CT变比和PT变比：从 HDR `<SettingValue>` 提取 CT一次额定值/CT二次额定值/PT一次额定值（**不从 CFG 提取**）
9. FaultInfo：从 HDR `<FaultInfo>` 提取故障相电流、故障相电压，全部换算为一次值
10. 一次值换算：电流一次值(kA) = 二次值(A) × CT一次额定值 / CT二次额定值 / 1000；无变比时标注 [无CT变比]

## 错误处理
- 文件缺失：标注`[录波文件缺失]`
- 字段无数据：标注`[无数据]`
"""
