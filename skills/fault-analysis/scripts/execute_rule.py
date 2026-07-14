"""
规则执行引擎

用于执行继电保护隐患辨识规则
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum


class Severity(Enum):
    """严重程度"""
    CRITICAL = "危急"
    MAJOR = "严重"
    MINOR = "一般"


@dataclass
class RuleResult:
    """规则执行结果"""
    rule_id: str
    rule_name: str
    category: str
    source: str
    severity: Severity
    matched: bool
    evidence: Dict[str, Any]
    remediation: str
    code_location: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "category": self.category,
            "source": self.source,
            "severity": self.severity.value,
            "matched": self.matched,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "code_location": self.code_location
        }


@dataclass
class ChannelMapping:
    """通道映射结果"""
    event_id: str
    device_id: str
    timestamp: str
    channels: Dict[str, str]  # 通道名称 -> 标准类型
    events: List[Dict[str, Any]]  # 事件列表


@dataclass
class RuleContext:
    """规则执行上下文"""
    channel_mapping: ChannelMapping
    metadata: Dict[str, Any]  # 装置信息等


class RuleEngine:
    """规则引擎"""

    def __init__(self):
        self.rules: Dict[str, callable] = {}

    def register_rule(self, rule_id: str, rule_func: callable):
        """注册规则"""
        self.rules[rule_id] = rule_func

    def execute_rule(self, rule_id: str, context: RuleContext) -> RuleResult:
        """执行单个规则"""
        if rule_id not in self.rules:
            raise ValueError(f"Rule {rule_id} not found")

        return self.rules[rule_id](context)

    def execute_all(self, category: Optional[str] = None, context: Optional[RuleContext] = None) -> List[RuleResult]:
        """执行所有规则或指定类别的规则"""
        results = []
        for rule_id, rule_func in self.rules.items():
            if category is None or rule_id.startswith(f"rule_{category}"):
                try:
                    result = rule_func(context)
                    results.append(result)
                except Exception as e:
                    # 规则执行失败不影响其他规则
                    print(f"Rule {rule_id} execution failed: {e}")
        return results

    def get_matched_rules(self, results: List[RuleResult], sort_by_severity: bool = True) -> List[RuleResult]:
        """获取匹配的规则"""
        matched = [r for r in results if r.matched]

        if sort_by_severity:
            severity_order = {
                Severity.CRITICAL: 0,
                Severity.MAJOR: 1,
                Severity.MINOR: 2
            }
            matched.sort(key=lambda r: severity_order.get(r.severity, 99))

        return matched


# ============================================================================
# 示例规则实现
# ============================================================================
# 说明：本引擎为通用隐患规则执行框架。当前已实现的两类执行路径：
#   1. 通用引擎路径：通过 RuleEngine.register_rule + execute_all 执行，
#      适用于事件流驱动的离散隐患规则（如 rule_06_001 GOOSE 链路异常）。
#   2. 越级分析直接调用路径：rule_03008/03009/03010 位于 scripts/rules/，
#      由 over_trip_analysis.py 直接 import 调用（因其输入参数结构不同、
#      依赖跨设备对齐与候选选线结果，不适合走通用 RuleContext）。
# 两者共用 Severity/RuleResult 数据模型。新增通用规则时优先注册到引擎；
# 新增需复杂上下文的规则时可独立实现并在此说明。

def check_goose_link_abnormal(context: RuleContext) -> RuleResult:
    """
    Rule 06001: GOOSE通信链路异常

    判定条件:
    1. 检测到GOOSE总告警信号
    2. 同时检测到GOOSE接收链路异常信号
    3. 时间差在±100ms内
    """
    events = context.channel_mapping.events

    # 查找GOOSE总告警
    goose_alarm = None
    link_alarm = None

    for event in events:
        signal_name = event.get("signal_name", "")
        if "GOOSE总告警" in signal_name or "GOOSE告警" in signal_name:
            goose_alarm = event
        if "GOOSE接收" in signal_name and "链路异常" in signal_name:
            link_alarm = event

    matched = False
    evidence = {}

    if goose_alarm and link_alarm:
        time_diff = abs(goose_alarm.get("relative_time_ms", 0) - link_alarm.get("relative_time_ms", 0))
        if time_diff <= 100:
            matched = True
            device = context.channel_mapping.device_id
            time_str = f"+{goose_alarm.get('relative_time_ms')}ms"
            evidence = {
                "device": device,
                "time": time_str,
                "signals": [goose_alarm.get("signal_name"), link_alarm.get("signal_name")],
                "time_diff_ms": time_diff
            }

    return RuleResult(
        rule_id="rule_06_001",
        rule_name="GOOSE通信链路异常",
        category="communication",
        source="技术规范 C.6.2",
        severity=Severity.MAJOR,
        matched=matched,
        evidence=evidence,
        remediation="检查GOOSE网络配置，确认光纤连接正常，检查交换机端口状态",
        code_location="scripts/execute_rule.py:check_goose_link_abnormal()"
    )


# ============================================================================
# 规则注册
# ============================================================================

def create_default_engine() -> RuleEngine:
    """创建默认规则引擎"""
    engine = RuleEngine()

    # 注册规则
    engine.register_rule("rule_06_001", check_goose_link_abnormal)

    return engine


# ============================================================================
# 命令行接口
# ============================================================================

if __name__ == "__main__":
    # 测试用例
    test_context = RuleContext(
        channel_mapping=ChannelMapping(
            event_id="2024-06-28-16-33-20",
            device_id="23号",
            timestamp="2024-06-28T16:33:20",
            channels={},
            events=[
                {"signal_name": "GOOSE总告警", "relative_time_ms": 95},
                {"signal_name": "链路1GOOSE接收A网链路异常", "relative_time_ms": 95}
            ]
        ),
        metadata={}
    )

    engine = create_default_engine()
    result = engine.execute_rule("rule_06_001", test_context)

    print(f"规则: {result.rule_name}")
    print(f"匹配: {result.matched}")
    print(f"严重程度: {result.severity.value}")
    print(f"证据: {result.evidence}")
