---
name: protection-risk-assessment
description: >
  继电保护运行风险评估智能体。当用户询问厂站/间隔/保护装置的运行风险、缺陷超时、设备健康度，
  或要求"评估一下XX站XX线路保护风险"、"今天有哪些危急缺陷超时"、"给出本周风险简报"时使用。
  ⚠️ 整合静态台账、实时运行状态、保信定值、压板/模拟量、历史告警、检修记录六源数据（不可仅用台账+告警），
  走"规则驱动层（告警状态机 + 检修过滤 + 频发抖动）→ 智能诊断层 → FAHP 风险融合层"三段式评估，
  按间隔（一次设备）聚合输出四级（危急/严重/一般/提示）结构化风险简报，活页可追溯。
  在线模式下必须完成六源数据采集后再分析，禁止跳过任何一源。
---

# 继电保护运行风险评估智能体 v2

## Overview

基于多源数据实时融合分析的自动化风险评估引擎。把离散的"缺陷 + 告警 + 监测 + 检修"拼成连续风险趋势，按**间隔（一次设备）**聚合，给运行、调度人员交付**结构化风险简报**。

**三层递进：合规研判（确定性规则 + 告警状态机 + 检修过滤）→ 健康度（数据/知识双驱动）→ 综合量化（FAHP）**

### 关键修订（v1 → v2）

| 问题 | v1（旧）| v2（新）|
|---|---|---|
| 告警抖动 | 简单 `value=告警` 即纳入 | **告警状态机 + 24h ≥ 5 次频发抖动升级** |
| 检修时段 | 不区分 | **自动过滤检修窗口内告警** |
| 站归属错配 | 按告警 JSON station_name 直接拉 | **以台账 station_name 为权威**，告警错标装置不进入评估 |
| 输出粒度 | 单套保护简报 | **按间隔聚合**，含双套独立运行综合 |

## When to Use

用户口径（自然语言直接触发，无需记忆命令）：

- "评估一下 **500kV 皋城变** 皋文 5325 线保护的运行风险"
- "今天有哪些 **间隔** 存在危急缺陷超时风险？"
- "**本周** 全网有哪些严重风险？"
- "**红石变** 保护运行风险"
- "**XX保护装置** 健康度如何？最近有什么异常？"
- "这条线路的 **通道** 状态是否正常？"
- "定值区号是否与 **调度定值单** 一致？"
- 复查风险简报 → "展开 220kV 红马 2C51 间隔的追溯明细"

**不要用于：** 单次录波波形溯因（→ latent-faults），定值单/计算书校核（→ setting-check），倒闸操作票审查（→ safety-ticket-audit），保护误动跳闸分析（→ over-trip-analysis）。

## 数据获取

本技能支持**在线模式**和**离线模式**两种数据获取方式。

### 在线模式（Agent 对话中使用）—— 强制执行六源数据采集

> ⚠️ **核心约束：必须先完成全部六源数据采集，才能进入分析阶段。**
> **推荐方式：调用 `risk_assessment_collect(stName=<厂站名>)` 一次性获取六源数据。**

**推荐方式（一步到位，与客户端离线脚本逻辑一致）：**

调用 `risk_assessment_collect(stName=<厂站名>)` 工具，内部自动完成以下六源采集并返回结构化数据包：
1. 台账 → 获取厂站所有保护装置列表（含 uniqueCode）
2. 运行状态 → 查询校核状态、设备状态、通信状态
3. 保信定值 → 获取每台装置的实时定值（当前值/标准值/上下限）
4. 压板/模拟量 → 获取硬压板、软压板、模拟量数据
5. 告警 → 获取今日告警记录和保护告警状态
6. 检修 → 获取检修工作记录

**注意：调用此工具后，无需再单独调用 ledger_query 或 status_query。**

**手动方式（仅当编排工具不可用时使用）：**

| # | 维度 | 工具调用 | 返回数据 |
|---|---|---|---|
| 1 | 静态台账 | `ledger_query(stName=厂站名)` | 设备列表（含 uniqueCode、型号、厂家、投运年限等） |
| 2 | 运行状态 | `status_query(voltageType, protectType, stName)` | 主保/后备/重合闸/校核状态统计 |
| 3 | 保信定值 | `ledger_query(uniqueCode, queryType=bx_setting)` | 装置实时定值（当前值/标准值/上下限） |
| 4 | 硬压板 | `ledger_query(uniqueCode, queryType=hard_press)` | 硬压板状态 |
|   | 软压板 | `ledger_query(uniqueCode, queryType=soft_press)` | 软压板状态 |
|   | 模拟量 | `ledger_query(uniqueCode, queryType=analog)` | 模拟量数据 |
| 5 | 装置历史告警 | `ledger_query(uniqueCode, queryType=history, starttime=today_start, endtime=today_end)` | 告警记录（含 soeTime、告警类型） |
|   | 保护告警 | `ledger_query(uniqueCode, queryType=protect_alarm)` | 保护告警（动作/复归） |
| 6 | 检修记录 | `ledger_query(uniqueCode, queryType=maintenance)` | 检修工作记录 |

**六源数据采集流程：**

> **推荐：调用 `risk_assessment_collect(stName=<厂站名>)` 一步完成六源采集。**
> 
> 以下手动流程仅作备选参考。

#### 阶段一：数据采集（必须完成全部 6 步后才能进入阶段二）

```
第1步 ▸ 台账采集
  调用 ledger_query(stName=<厂站名>) 或 risk_assessment_collect(stName=<厂站名>) 获取设备列表。
  ├─ 产出: 设备清单 (uniqueCode[], voltageType, protectType)

第2步 ▸ 运行状态采集（不可跳过）
  调用 status_query(voltageType=..., protectType=..., stName=<厂站名>)。
  ├─ 产出: 全站运行状态统计数据

第3步 ▸ 定值采集（不可跳过）
  调用 ledger_query(uniqueCode=<code>, queryType=bx_setting)。
  ├─ 产出: 每台装置的定值数据

第4步 ▸ 压板+模拟量采集（不可跳过）
  调用 ledger_query(uniqueCode=<code>, queryType=hard_press)
        ledger_query(uniqueCode=<code>, queryType=soft_press)
        ledger_query(uniqueCode=<code>, queryType=analog)
  ├─ 产出: 每台装置的压板状态和模拟量数据

第5步 ▸ 告警数据采集
  调用 ledger_query(uniqueCode=<code>, queryType=history, starttime=<today 00:00:00>, endtime=<now>)
        ledger_query(uniqueCode=<code>, queryType=protect_alarm)
  ├─ 产出: 每台装置今日告警记录和保护告警状态

第6步 ▸ 检修数据采集（不可跳过）
  调用 ledger_query(uniqueCode=<code>, queryType=maintenance)。
  ├─ 产出: 每台装置的检修工作记录
```

#### 阶段二：数据完整性校验 → 风险评估

```
第7步 ▸ 六源完整性自检（进入分析前必须执行）
  逐项核对六源数据是否已采集:
    [ ] 台账     — 是否已获取设备列表?
    [ ] 运行状态 — 是否已调用 status_query?
    [ ] 定值     — 是否已对每台设备调用 bx_setting?
    [ ] 压板     — 是否已对每台设备调用 hard_press + soft_press + analog?
    [ ] 告警     — 是否已对每台设备调用 history + protect_alarm?
    [ ] 检修     — 是否已对每台设备调用 maintenance?
  
  如果任何一项未完成 → 回到阶段一补全对应步骤。
  六项全部完成 → 进入第8步。

第8步 ▸ 执行风险评估
  将采集的六源数据按照本技能的规则引擎进行评估:
    - 告警状态机（信号持续/频发抖动判断）
    - 规则驱动层（A1-E4 确定性规则命中）
    - 检修时段过滤（检修窗口内告警降级）
    - 健康度评分（H1-H4 维度打分）
    - FAHP 风险融合（五维加权综合）

第9步 ▸ 输出结构化风险简报
  按间隔聚合输出，含四级风险等级、健康度、置信度、处置建议。
```

**在线模式禁止行为：**
- ❌ 只采集台账和告警就输出结论 → 六源不完整，结论不可靠
- ❌ 跳过 status_query → 缺少运行状态，无法判断 B3 通讯异常、A3 参数异常
- ❌ 跳过 bx_setting → 缺少定值数据，无法检测 E4 定值漂移
- ❌ 跳过 hard_press/soft_press/analog → 缺少压板/模拟量，无法检测 E1/E2/E3/D3 规则
- ❌ 跳过 maintenance → 缺少检修记录，无法执行检修过滤和 F1/F2 检修后规则
- ❌ 在数据采集中途就开始分析 → 必须完成全部 6 步采集后统一分析

### 离线模式（直接运行脚本）

使用本地 JSON 文件进行批量分析：

```bash
# 全网扫描
python skills/protection-risk-assessment/scripts/run_risk_assessment.py --scope all

# 指定厂站
python skills/protection-risk-assessment/scripts/run_risk_assessment.py --station 红石变

# 带检修工作清单
python skills/protection-risk-assessment/scripts/run_risk_assessment.py \
    --station 红石变 \
    --maintenance-file 保护装置信息/保护装置检修工作.json

# 仅输出简报，不展开活页
python skills/protection-risk-assessment/scripts/run_risk_assessment.py \
    --station 红石变 --briefing-only
```

### 数据格式映射

在线模式获取的数据字段与离线 JSON 的对应关系：

#### 台账 (inventory)
| 离线 JSON 字段 | 在线工具返回字段 | 说明 |
|---|---|---|
| `station_name` | `ledger_query` 返回的 `stName` | 厂站名 |
| `device_name` | `ledger_query` 返回的 `onceDeviceName` | 需归一化处理 |
| `protection_type` | `ledger_query` 返回的 `protectType` | 保护类型 |
| `set` | `ledger_query` 返回的 `protectCover` | 套别（1/2） |
| `model` | `ledger_query` 返回的 `protectModel` | 保护型号 |

#### 运行状态 (real_time_status)
| 离线 JSON 字段 | 在线工具返回字段 | 说明 |
|---|---|---|
| `check_status` | `status_query` 返回的 `checkStatus` | 校核状态（正常/异常/参数异常） |
| `oss_status` | `status_query` 返回的 `ossStatus` | 设备状态（运行中/检修中） |
| `ied_status` | `status_query` 返回的 `iedStatus` | 通信状态（正常/断开） |
| 主保护/后备/重合闸 | `status_query` 返回的 `status1~13` | 保护投入/退出状态 |

#### 定值 (real_time_values)
| 离线 JSON 字段 | 在线工具返回字段 | 说明 |
|---|---|---|
| `settings[].current_value` | `bx_setting` 返回的 `value` | 当前定值 |
| `settings[].standard_value` | `bx_setting` 返回的 `stdvalue` | 标准值 |
| `settings[].max_value` | `bx_setting` 返回的 `maxvalue` | 上限 |
| `settings[].min_value` | `bx_setting` 返回的 `minvalue` | 下限 |

#### 压板 (press_board)
| 离线 JSON 字段 | 在线工具返回字段 | 说明 |
|---|---|---|
| `hard_press[].value` | `hard_press` 返回的 `value` | 硬压板状态 |
| `soft_press[].value` | `soft_press` 返回的 `value` | 软压板状态 |
| `analog[].value` | `analog` 返回的 `value` | 模拟量数值 |

#### 告警 (alarms)
| 离线 JSON 字段 | 在线工具返回字段 | 说明 |
|---|---|---|
| `alarm_priority` | `history` 返回的 `alarmLevel` | 告警级别 |
| `status_name` | `history` 返回的 `alarmContent` | 告警内容 |
| `value` (告警/复归) | `protect_alarm` 返回的 `value` | 1=动作，0=复归 |
| `timestamp` | `history` 返回的 `soeTime` | 告警时间 |

#### 检修 (maintenance)
| 离线 JSON 字段 | 在线工具返回字段 | 说明 |
|---|---|---|
| `start_time` | `maintenance` 返回的 `confirmBeginTime` | 检修开始时间 |
| `end_time` | `maintenance` 返回的 `realEndTime` | 检修结束时间 |
| `work_type` | `maintenance` 返回的 `declareWorkContent` | 工作内容描述 |

设备名归一化规则（v2）：
- 在线返回 `onceDeviceName` = "220kV崔挥2C55线路第一套保护PCS931A-G" → primary_device = "崔挥2C55线", set_index = 1
- 离线 JSON `device_name` = "崔挥 2C55 线" → primary_device = "崔挥2C55线"
- 两者归一到同一 (station, primary_device, set_index) 键

## 工作流程

**在线模式（推荐使用 `risk_assessment_collect` 工具）**：

```
用户询问 → risk_assessment_collect(stName=厂站) → 六源自检 → 按台账归一 → 告警状态机 → 规则驱动层 → 检修过滤 → 健康度评分 → FAHP融合 → 间隔聚合 → 简报输出
```

**离线模式**（直接运行脚本）：

```dot
digraph risk_flow_offline {
    rankdir=TB;
    node [shape=box];
    "用户自然语言询问" -> "意图解析\n(对象识别+时间窗)";
    "意图解析" -> "加载 DataPackage\n(含检修清单)";
    "加载 DataPackage" -> "按台账归一\n筛选间隔";
    "按台账归一" -> "告警状态机\n(信号消除/频发抖动)";
    "告警状态机" -> "规则驱动层\n合规研判";
    "规则驱动层" -> "检修时段过滤";
    "检修时段过滤" -> "智能诊断层\n健康度打分";
    "智能诊断层" -> "风险融合层\nFAHP量化";
    "风险融合层" -> "间隔级聚合\n(双套独立运行)";
    "间隔级聚合" -> "结构化风险简报\n四级 + 活页追溯";
}
```

```dot
digraph risk_flow_offline {
    rankdir=TB;
    node [shape=box];
    "用户自然语言询问" -> "意图解析\n(对象识别+时间窗)";
    "意图解析" -> "加载 DataPackage\n(含检修清单)";
    "加载 DataPackage" -> "按台账归一\n筛选间隔";
    "按台账归一" -> "告警状态机\n(信号消除/频发抖动)";
    "告警状态机" -> "规则驱动层\n合规研判";
    "规则驱动层" -> "检修时段过滤";
    "检修时段过滤" -> "智能诊断层\n健康度打分";
    "智能诊断层" -> "风险融合层\nFAHP量化";
    "风险融合层" -> "间隔级聚合\n(双套独立运行)";
    "间隔级聚合" -> "结构化风险简报\n四级 + 活页追溯";
}
```

**核心算法：**

1. **按台账归一筛选**：`select_targets()` 仅以台账中存在的 (station, primary_device) 为评估范围，避免数据采集错标的"挂错站"装置污染评估。
2. **告警状态机**（详见 `references/alarm_state_machine.md`）：
   - 同一 `(装置, status_name)` 时间序列最后一条 = 告警 → 信号持续
   - 最后一条 = 复归 → 信号已消除（默认不计入）
   - 24h 内同一 status_name 告警次数 ≥ 5 → **频发抖动**，无论是否已复归都升级到"严重"（B5）
3. **检修时段过滤**（详见 `references/maintenance_filtering.md`）：
   - 告警 timestamp 落在维护窗口内 → 完全不计入风险
   - 检修窗口内的频抖也过滤
4. **规则驱动层**（详见 `references/risk_dimension_rules.md`）：A1-A5 / B1-B5 / C1-C2 / D1-D3 共 14 条确定性规则。
5. **智能诊断层**（详见 `references/device_health_index.md`）：活跃告警 + 频发抖动 + 参数异常 + 定值漂移 = HealthIndex ∈ [0,100]。
6. **风险融合层**（详见 `references/fahp_methodology.md`）：FAHP 准则层权重 [二次设备 0.40 / 通道 0.27 / 反措 0.20 / 定值 0.13] → 综合分 → 四级映射。
7. **间隔级聚合**：双套独立运行综合判断（任一危急 → 整间隔危急；双套严重 → 整间隔严重）。

**置信度（confidence ∈ [0,1]）：**
- 数据完整度（多源齐备）× 规则命中强度 × 活跃告警密度，三元乘积；写入简报尾部。

## 输出：间隔风险简报模板

```
【{危急/严重/一般/提示}】 间隔风险简报
● 风险等级：🔴/🟠/🟡/⚪ 危急/严重/一般/提示
● 间隔：[厂站] → [primary_device]
● 包含装置：第1套（FAHP X，健康度 Y） 第2套（FAHP X，健康度 Y）...
● 风险概述：基于规则与诊断结果 1-2 句概括核心风险点
● 核心建议：1./2./3. 三条以内具体可操作建议
● 推理追溯：[展开] confidence: 0.83 综合FAHP: 78.5 间隔规则: 双套独立运行...
```

完整字段约束见 `references/briefing_template.md`，案例见 `references/briefing_examples.md`。

## 典型场景的处置建议模板

从 `references/action_knowledge_base.md` 匹配，按规则 ID 取前置建议（≤3 条）。

## 权威性说明

- **`scripts/` 目录**：风险评估的核心算法实现，是最终执行逻辑的权威来源
- **`references/` 目录**：背景知识文档，帮助理解规则设计原理，但不直接参与执行
- 当 `references/` 与 `scripts/` 存在差异时，以 `scripts/` 为准

## 输出与追溯

**简报正文（按间隔聚合）** + **活页附件**（每间隔一份 HTML + JSON 推理链）：
- `out/<时间戳>/briefing.md` —— 主简报（最终交付物）
- `out/<时间戳>/<间隔名>.html` —— 活页 HTML，可点击展开每条规则的原始数据
- `out/<时间戳>/<间隔名>.json` —— 该间隔的完整推理链（规则命中、双套综合、置信度）

## Common Mistakes

- ❌ **只采集台账+告警就输出结论（最严重错误）** → 风险评估必须基于六源数据！缺少运行状态无法判断通讯/参数异常(B3/A3)；缺少定值无法检测漂移(E4)；缺少压板/模拟量无法检测不一致和越限(E1/E2/E3/D3)；缺少检修记录无法执行检修过滤和F1/F2规则。六源缺一不可，严禁在数据不全的情况下输出评估结果。
- ❌ **把告警 JSON station_name 当评估目标** → 真实场景存在数据采集错标，必须以台账 station_name 为权威。
- ❌ **简单 `value=告警` 即视为危急** → 必须看时序：
   - 告警→复归 → 已消除，不算
   - 24h 内告警→复归→告警→...≥5 次 → **频发抖动**，应判严重
- ❌ **不结合检修时段** → 检修窗口内的告警几乎都是预期现象，必须过滤。
- ❌ **按单套装置输出** → 应按间隔聚合；同间隔双套失守是更危险信号。
- ❌ **把"参数异常"与"装置故障"混为一谈** → 实时状态 `check_status=参数异常` 是参数无法读取，离线告警，需结合告警记录交叉确认。
- ❌ **风险等级跳跃式赋值** → 必须经过 FAHP 综合分映射。
- ❌ **跳过 status_query 只查台账/告警** → 缺少校核状态、OSS状态等运行状态数据，B3/A3 规则将完全失效。
- ❌ **告警查询不限制时间窗口** → history 必须传入 starttime/endtime（今日窗口），否则告警状态机无法区分"今日持续"与"历史已复归"。

## 相关技能（按需调用）

| 场景 | 调用 |
|---|---|
| 校核定值与计算书 | `setting-check` |
| COMTRADE 录波隐患 | `latent-faults-analysis` |
| 二次安全措施审查 | `secondary-safety-measures-audit` |
| 误动跳闸溯因 | `over-trip-analysis` |

## Real-World Impact

将"离散的缺陷/告警/在线监测/检修数据"打通为"按间隔聚合的连续风险趋势"——把运行人员每天翻看多张表 → 一份按间隔组织的四级**风险简报**的认知负担从小时级压缩到分钟级。告警状态机 + 检修过滤减少假警报、频发抖动识别捕获传统 SCADA 难以察觉的"装置软硬件不稳定"。

简报中所有结论可点击展开原始数据，避免黑箱 AI 的"我说是就是"。
