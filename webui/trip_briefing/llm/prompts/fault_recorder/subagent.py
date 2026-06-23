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

## 核心原则（必须遵守）

1. **严禁编造数据**：所有数据必须来自输入文件，不得凭空推测或编造。无数据时标注 `[无数据]`。
2. **数据溯源**：关键数据必须标注来源文件和字段名。
3. **保留原始值**：提取的数据必须与源文件一致，不得修改或"修正"原始数值。
4. **只提取故障设备相关内容**，忽略其他线路/设备的数据。

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
- **数字状态（DigitalStatus）只列出值为1的条目**，值为0的条目全部省略（包括"备用: 0"、未动作的保护功能等），不要逐条列出
- 录波器段落中的开关动作信息：同一设备同一事件（如断路器B相位置/总位置）只保留首次出现的一对（分位+合位），不要重复列出

## {label}

**录波器型号**: {{型号}}
**故障时间**: {{年}}-{{月}}-{{日}} {{时}}:{{分}}:{{秒}}.{{毫秒}}

### HDR信息
（如果 HDR 有内容：正常列出设备信息、TripInfo、FaultInfo、定值信息）
（如果 HDR 缺失或内容为空：只写 `[HDR文件缺失]`，不要展开子字段）

**HDR FaultInfo 提取字段**（全部从 HDR 中提取）:
- faultTime: 故障起始时间
- station: 厂站名
- recorderName: 录波器名称
- primaryDevice: 故障设备名称（线路名）
- faultPhase: 故障相别（如AN=A相接地）
- tripPhase: 跳闸相别
- faultPhaseVoltage: 故障相电压（HDR中的值+单位）
- faultPhaseCurrent: 故障相电流（HDR中的值+单位）
- maxFaultCurrent: 最大故障电流
- zeroVoltage: 零序/N相电压
- faultDistance: 故障测距（注意：0.00也是有效数据，必须如实填写）
- faultImpedance: 故障阻抗
- faultType: 瞬时故障/永久故障（从HDR"故障性质"字段取）
- isInsideZone: 区内/区外故障
- reclosingStatus: 重合闸情况（从HDR"重合闸是否成功"取）
- switchAction: 开关动作情况
- ctRatio: CT变比
- ptRatio: PT变比

**TripInfo**（从HDR提取，将value=1的作为动作事件，value=0的作为返回事件，配对输出）:

| 动作名称 | 动作时间 | 相别 | 持续时间(ms) |
|----------|----------|------|-------------|

### Events信息
| 绝对时间 | 通道名称 | 内容 |
|----------|----------|------|

**数字量信号事件（故障设备相关）**:
- 保护启动信号、保护动作信号、开关跳闸/位置信号、重合闸信号
- 去除"收"信号、告警信号
- 只取包含故障设备名称关键词的信号通道

| 通道名称 | 动作时间 | 返回时间 | 持续时间(ms) |
|----------|----------|----------|-------------|

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
8. CT变比和PT变比：从 HDR `<SettingValue>` 提取（**不从 CFG 提取**）：

   | 字段名 | 说明 | 单位 |
   |--------|------|------|
   | CT一次额定值 | CT 一次侧额定电流 | A |
   | CT二次额定值 | CT 二次侧额定电流（通常 1A 或 5A） | A |
   | PT一次额定值 | PT 一次侧额定电压 | kV |

   **CT变比** = CT一次额定值 / CT二次额定值（如 3000/1）
9. FaultInfo：从 HDR `<FaultInfo>` 提取故障相电流、故障相电压，全部换算为一次值
10. 一次值换算：电流一次值(kA) = 二次值(A) × CT一次额定值 / CT二次额定值 / 1000；无变比时标注 [无CT变比]
11. 数值型字段必须忠实于原始数据，即使值为0也要如实填写，不得省略或替换

## 错误处理
- 文件缺失：标注`[录波文件缺失]`
- 字段无数据：标注`[无数据]`
"""
