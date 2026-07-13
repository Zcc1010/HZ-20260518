# 告警状态机规则

> 把"value=告警 / 复归 + timestamp"作为时序信号做状态机分析，
> 而不是简单地"value=告警 才计入"。
> 这是防护运行风险评估与调度监控规则的最大差异：
> 现场告警数据**大量抖动是常态**，必须过滤抖动、
> 识别"真持续"和"假持续"，再叠加频发抖动升级。

## 一、基本概念

| 字段 | 含义 | 时间 |
|---|---|---|
| `device_name` | 装置名 | - |
| `status_name` | 告警语义（如"通道一通道异常"） | - |
| `value` | 该次记录的类型 | "告警" / "复归" |
| `timestamp` | 告警发生/复归时间 | ISO 顺序 |

**基本假设**：
- 同一 `(装置, status_name)` 时间序列即一台装置"这一类信号"的演变史
- 时间序列最后一条决定当前状态

## 二、规则

### A. 当前状态判定

| 最后一条 value | 当前状态 | 判定 |
|---|---|---|
| 告警 | is_persistent=True | 信号持续活跃，纳入风险 |
| 复归 | is_persistent=False | 信号已消除，**默认不纳入风险** |

### B. 频发抖动（Flapping）升级

| 条件 | 处理 |
|---|---|
| 24h 内，同一 `(装置, status_name)` 的"告警"次数 ≥ 5 次 | **无论是否已复归，纳入风险**，规则 ID = B5 |

频发抖动表征装置**软硬件不稳定**：
- 采样板卡虚焊
- 光纤通道间歇性中断（如收发光功率临界）
- 主板通讯模块老化

这种抖动一旦在生产中存在，对保护正确动作的**置信度**显著下降，
**即使当前复归也应升级到"严重"**。

### C. 检修时段过滤

| 告警 timestamp 落在某条检修 start..end 窗口内 | 该告警**不计风险** |
|---|---|

实现：`scripts/load_local_data.py:alarm_in_maintenance_window`。
数据源：`load_maintenance(json_path)` 加载的检修工作清单（待用户提供样本）。

### D. 跨信号聚合升级

同一装置**多个** `status_name` 同时频发抖动（≥ 2 个）
→ 触发 **B5 跨信号频发抖动** 规则，等级"严重"。

这表征装置**整体不稳定**，而非单个信号偶发抖动。

## 三、24h 时间窗口的实现

```python
from datetime import datetime, timedelta

now = datetime.now()       # 评估发生时间
window_start = now - timedelta(hours=24)

flap_count = 0
for alarm in status_alarms:   # 同 status_name 子集
    ts = parse_ts(alarm["timestamp"])
    if alarm_in_maintenance_window(alarm["timestamp"], maint_records):
        continue
    if ts >= window_start and alarm["value"] == "告警":
        flap_count += 1

is_flapping = flap_count >= 5
```

## 四、字段映射

| 告警原文 | 状态机字段 |
|---|---|
| `value="告警"` | `is_persistent=True` |
| `value="复归"` | `is_persistent=False` |
| `alarm_priority=严重告警` | 直接当作"严重信号源" |
| `alarm_priority=运行异常` | 直接当作"一般信号源" |
| `status_name` 命中规则关键词 | 触发对应 rule_id（B1/B2/B3/A2...） |
| `timestamp` 在检修窗口 | 该告警忽略 |

## 五、决策矩阵

| is_persistent | is_flapping | in_maintenance | 最终等级 |
|---|---|---|---|
| True | False | True | 提示（检修） |
| True | False | False | base_level（按规则关键词） |
| False | True | True | 提示（检修时段抖动） |
| False | True | False | **严重**（B5 频发抖动） |
| False | False | * | 提示（已消除且非抖动） |

## 六、参数可调

| 参数 | 默认 | 位置 |
|---|---|---|
| `FLAP_THRESHOLD` | 5 次 | `scripts/run_risk_assessment.py` |
| `FLAP_WINDOW_HOURS` | 24 h | 同上 |

修改后需重跑评估脚本生效。

## 七、为什么不在 EMS 系统直接做

调度自动化系统的告警显示是"实时面板"，值班员点开即看；
本智能体的告警状态机是"评估引擎"输入特征，是为**多源融合 + 检修过滤 + 频发抖动识别**
三层叠加服务的——放在 EMS 系统内做会引入复杂时序逻辑，
且 EMS 通常只显示当前态，不存历史时序。

这是典型的"AI 评估层"职责，而非"实时监控层"。

## 八、与告警严重程度映射表的关系

`references/alarm_severity_table.md` 定义关键词→规则 ID + 默认等级；
本规则定义的"频发抖动升级"是该映射的**纵向扩展**——
把同一信号的时序行为升档或降档。

两个文档保持同步更新：
- 关键词改 → alarm_severity_table.md
- 时序行为改 → 本文档
