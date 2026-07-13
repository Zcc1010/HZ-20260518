# 告警严重程度映射表

> 把 `alarm_priority + status_name` 字典化的关键告警 → 触发规则层。
> 当 status_name 命中表中条目时，自动触发对应的规则 ID。

## 一、按 status_name 查表

| status_name（关键词匹配） | alarm_priority | 触发规则 | 默认等级 |
|---|---|---|---|
| CPU严重故障 / CPU板卡 / RAM错误 | 严重告警 | A1 | 危急 |
| 板卡故障 / 电源故障 | 严重告警 | A1 | 危急 |
| 装置报警（含"严重"） | 严重告警 | A2 | 严重 |
| 装置报警（普通） | 运行异常 | A2 | 一般 |
| 参数异常 / 参数读取失败 | 运行异常 | A3 | 严重（本体）/ 一般（通讯） |
| 通道一通道异常 | 严重告警 | B1 | 一般 |
| 通道二通道异常 | 严重告警 | B1 | 一般 |
| 通道一通道故障 / 通道二通道故障 | 严重告警 | B1 | 严重 |
| 通道一无有效帧 / 通道二无有效帧 | 严重告警 | B1 | 严重 |
| 通道故障（不区分通道） | 严重告警 | B1 | 严重 |
| 纵联保护闭锁 | 严重告警 | B2 | 严重 |
| 闭锁主保护 | 严重告警 | B2 | 危急 |
| 通讯中断 / 通讯状态异常 | 运行异常 | B3 | 严重 |
| 异常（无更具体 status_name） | 运行异常 | A2 / B4 | 一般 |

## 二、双通道时间维度升级

| 情形 | 升级 |
|---|---|
| 单通道告警持续 ≥ 24h 未复归 | 一般 → 严重 |
| 单通道告警持续 ≥ 72h 未复归 | 严重 → 危急 |
| 双通道同时告警 | 严重 → 危急 |

持续时长 = `当前时间 - timestamp`。

## 三、按 value 字段过滤

| value | 含义 | 是否计入 |
|---|---|---|
| 告警 | 未复归（仍处于告警状态） | ✅ 强信号 |
| 复归 | 已自动消失 | ⚠️ 仅作为趋势（频次） |

未复归告警 = 一次性"装置当下存在异常"——**核心信号源**。

## 四、命名归一化

不同厂家/不同时期告警名称不完全一致，建议做关键词归一化：

```python
def normalize_alarm(status_name: str) -> str:
    s = status_name.upper()
    if "CPU" in s or "RAM" in s or "ROM" in s or "FLASH" in s or "板卡" in status_name:
        return "CPU_板卡严重故障"
    if "闭锁主保护" in status_name:
        return "闭锁主保护"
    if "纵联保护闭锁" in status_name:
        return "纵联保护闭锁"
    # ... 其他
    return status_name
```

实现见 `scripts/run_risk_assessment.py:normalize_alarm()`。

## 五、如何扩展

发现新告警 keyword → 追加到本文档第一节；新增规则 → 在 `references/risk_dimension_rules.md` 添加规则 ID 并在本表"触发规则"列引用。

保持两个文档的双向引用同步——任何 status_name 必须能映射到规则 ID，反之规则 ID 命中的 status_name 必须在表中。
