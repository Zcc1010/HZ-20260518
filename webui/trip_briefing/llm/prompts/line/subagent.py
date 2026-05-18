# -*- coding: utf-8 -*-
"""线路保护 Subagent Prompt"""


def build_subagent_prompt(
    hdr_content: str,
    rms_content: str,
    events_content: str,
    station: str,
    set_number: str,
) -> str:
    return f"""# 线路保护 Subagent Prompt 模板

## 任务

给定本套保护装置的录波文件（hdr + rms.csv + events.csv），按 HDR/Events/RMS 三个区块提取本套装置的关键信息，生成标准化的 Markdown 段落。

## 设备信息

- 厂站: {station}
- 套别: {set_number}

## 输入数据

### HDR 文件内容
{hdr_content if hdr_content else '[HDR文件缺失]'}

### RMS CSV 文件内容
{rms_content if rms_content else '[RMS文件缺失]'}

### Events CSV 文件内容
{events_content if events_content else '[Events文件缺失]'}

## 输出格式

**重要：直接输出 Markdown 内容，不要用 ```markdown``` 代码围栏包裹。**

严格按照以下 Markdown 格式输出。有数据的字段填写实际值，无数据的标注`[无数据]`，有推测规则的标注`[推测为XXX]`。

**精简原则**：
- 当整个区块无数据时（如 HDR 文件缺失），只写一行 `[HDR文件缺失]`，**不要**逐字段列出 [无数据]
- Events 表只列出"动作"事件，省略"返回"事件（减少冗余）
- RMS 信息只列出有突变值的通道

输出格式模板：

## {station}_{set_number}

**装置型号**: {{型号}}，{{程序版本}}，{{智能站/常规站}}
**制造厂家**: {{厂家名称}}
**故障时间**: {{年}}-{{月}}-{{日}} {{时}}:{{分}}:{{秒}}.{{毫秒}}

### HDR信息
（如果 HDR 有内容：正常列出设备信息、TripInfo、DigitalEvent、FaultInfo、定值信息）
（如果 HDR 缺失或内容为空：只写 `[HDR文件缺失]`，不要展开子字段）

### Events信息
| 绝对时间 | 通道名称 | 内容 |
|----------|----------|------|
| HH:MM:SS.mmm | {{通道名}} | 动作 |

### RMS信息
**电流RMS最大值**: IA: {{一次值}}kA（二次值{{值}}A）, IB: {{一次值}}kA（二次值{{值}}A）, IC: {{一次值}}kA（二次值{{值}}A）, 3I0: {{一次值}}kA（二次值{{值}}A）
（无CT变比时只显示二次值: IA: {{值}}A [无CT变比]）
**电压RMS最小值**: UA: {{一次值}}kV（二次值{{值}}V）, UB: {{一次值}}kV（二次值{{值}}V）, UC: {{一次值}}kV（二次值{{值}}V）
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

## 字段提取规则

### 时间格式规范
- **日期**：只写一次（在段落开头故障时间字段中）
- **绝对时间**：格式 `HH:MM:SS.mmm`
- **严禁输出相对时间**（如 `0ms`、`15ms`），所有时间必须为绝对时间 `HH:MM:SS.mmm`
- HDR 中时间是偏移量（如 `0ms`、`11ms`），需转换为绝对时间：绝对时间 = 故障起始时间 + ms偏移量

### 关键提取规则
1. 厂站名和套别：从目录结构或文件名中提取
2. 装置型号：从 HDR `<DeviceInfo>` 提取，根据型号后缀判断智能站/常规站（含 FA/DA/DG → 智能站，其他 → 常规站）
3. 故障时间：从 HDR `<FaultStartTime>` 提取
4. TripInfo：从 HDR `<TripInfo>` 提取，偏移量转绝对时间
5. DigitalEvent：从 HDR `<DigitalEvent>` 提取
6. 定值信息：从 HDR `<SettingValue>` 提取关键定值（含 CT一次额定值、CT二次额定值、PT一次额定值）
7. Events信息：从 events.csv 提取，保持原始通道名，只陈述事实
8. RMS信息：从 rms.csv 提取最大值/最小值/突变（按第一次/第二次分组，列出所有超过阈值的通道）
9. CT变比和PT变比：从 HDR `<SettingValue>` 提取 CT一次额定值/CT二次额定值/PT一次额定值（**不从 CFG 提取**，CFG 通常为 1:1 不准确）
10. FaultInfo：从 HDR `<FaultInfo>` 提取故障相电流、最大差动电流、故障相电压、最大零序电流，全部换算为一次值
11. 一次值换算：电流一次值(kA) = 二次值(A) × CT一次额定值 / CT二次额定值 / 1000；电压一次值(kV) = 二次值(V) × PT一次额定值(kV) / PT二次额定值(V)。无变比时只显示二次值并标注 [无CT变比] 或 [无PT变比]

## 编码处理
HDR 可能为 GB18030 或 UTF-8 编码。若读取乱码，尝试另一种编码重新解析。

## 错误处理
- 文件缺失：标注`[本套文件缺失]`
- 字段无数据：标注`[无数据]`
- 有推测规则且可推测：标注`[推测为XXX]`

## 数据来源标注
在段落末尾标注数据来源文件。
"""
