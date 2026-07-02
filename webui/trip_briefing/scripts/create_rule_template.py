#!/usr/bin/env python3
"""
规则模板生成器

用于创建新的规则文件（.md 和 .py）
"""

import os
from pathlib import Path


# 规则模板
RULE_MD_TEMPLATE = """# Rule {rule_id}: {rule_name}

## 规则来源
- 文档: {document_name}
- 条款: {clause}
- 条款内容: {clause_content}

## 判定条件
{conditions}

## 严重程度
{severity}

## 整改建议
{remediation}

## 代码引用
- 实现: `backend/app/services/rules/{category}/rule_{rule_id}.py`
- 函数: {function_name}
- 测试: `tests/rules/{category}/test_rule_{rule_id}.py`
"""

RULE_PY_TEMPLATE = '''"""
{rule_name}

Rule ID: {rule_id}
Category: {category}
"""

from dataclasses import dataclass
from typing import Dict, Any, List
from .execute_rule import RuleContext, RuleResult, Severity


def check(context: RuleContext) -> RuleResult:
    """
    {rule_name}

    判定条件:
{conditions_py}
    """
    events = context.channel_mapping.events
    channels = context.channel_mapping.channels

    matched = False
    evidence = {{}}

    # TODO: 实现规则逻辑

    return RuleResult(
        rule_id="{rule_id_full}",
        rule_name="{rule_name}",
        category="{category}",
        source="{document_name} {clause}",
        severity=Severity.{severity_upper},
        matched=matched,
        evidence=evidence,
        remediation="{remediation}",
        code_location="backend/app/services/rules/{category}/rule_{rule_id}.py:check()"
    )
'''

TEST_PY_TEMPLATE = '''"""
测试 {rule_name}

Rule ID: {rule_id}
"""

import pytest
from scripts.execute_rule import RuleContext, ChannelMapping, create_default_engine


class TestRule{rule_id}:
    """测试规则 {rule_id}"""

    @pytest.fixture
    def passing_context(self):
        """通过用例：不存在该隐患"""
        return RuleContext(
            channel_mapping=ChannelMapping(
                event_id="test_event_pass",
                device_id="test_device",
                timestamp="2024-01-01T00:00:00",
                channels={{}},
                events=[
                    # TODO: 添加正常事件
                ]
            ),
            metadata={{}
        )

    @pytest.fixture
    def failing_context(self):
        """失败用例：存在该隐患"""
        return RuleContext(
            channel_mapping=ChannelMapping(
                event_id="test_event_fail",
                device_id="test_device",
                timestamp="2024-01-01T00:00:00",
                channels={{}},
                events=[
                    # TODO: 添加异常事件
                ]
            ),
            metadata={{}
        })

    def test_passing_case(self, passing_context):
        """测试正常情况"""
        engine = create_default_engine()
        result = engine.execute_rule("{rule_id_full}", passing_context)
        assert not result.matched

    def test_failing_case(self, failing_context):
        """测试异常情况"""
        engine = create_default_engine()
        result = engine.execute_rule("{rule_id_full}", failing_context)
        assert result.matched
        assert result.severity == Severity.{severity_upper}
'''


CATEGORY_MAPPING = {
    "01": ("device_body", "装置本体缺陷"),
    "02": ("primary_secondary", "一二次设备状态不对应"),
    "03": ("protection_behavior", "保护动作行为异常"),
    "04": ("sampling", "采样回路异常"),
    "05": ("io_circuit", "开入开出回路异常"),
    "06": ("communication", "通信通道异常"),
    "07": ("setting", "定值异常"),
}


def create_rule_files(
    rule_id: str,
    rule_name: str,
    category: str,
    document_name: str,
    clause: str,
    clause_content: str,
    conditions: list,
    severity: str,
    remediation: str,
    output_dir: str = "."
):
    """
    创建规则文件

    Args:
        rule_id: 规则编号，如 "06001"
        rule_name: 规则名称
        category: 类别代码，如 "communication"
        document_name: 来源文档名称
        clause: 条款号
        clause_content: 条款内容
        conditions: 判定条件列表
        severity: 严重程度 (危急/严重/一般)
        remediation: 整改建议
        output_dir: 输出目录
    """
    # 解析类别
    category_code = rule_id[:2]
    if category_code not in CATEGORY_MAPPING:
        raise ValueError(f"Invalid rule_id prefix: {category_code}")

    category_code_name, category_cn = CATEGORY_MAPPING[category_code]

    # 格式化条件
    conditions_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(conditions))
    conditions_py = "\n".join(f"    # {i+1}. {c}" for i, c in enumerate(conditions))

    # 严重程度映射
    severity_mapping = {
        "危急": "CRITICAL",
        "严重": "MAJOR",
        "一般": "MINOR"
    }
    severity_upper = severity_mapping.get(severity, "MINOR")

    # 函数名
    function_name = f"check_{category_code_name}_{rule_id}"

    # 创建目录
    category_dir = Path(output_dir) / category_code_name
    category_dir.mkdir(parents=True, exist_ok=True)

    # 生成文件名
    rule_suffix = f"rule_{rule_id}_{category_code_name}"
    md_file = category_dir / f"{rule_suffix}.md"
    py_file = category_dir / f"{rule_suffix}.py"
    test_file = category_dir / f"test_{rule_suffix}.py"

    # 写入 .md 文件
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(RULE_MD_TEMPLATE.format(
            rule_id=rule_id,
            rule_name=rule_name,
            document_name=document_name,
            clause=clause,
            clause_content=clause_content,
            conditions=conditions_text,
            severity=severity,
            remediation=remediation,
            category=category_code_name,
            function_name=function_name
        ))

    # 写入 .py 文件
    with open(py_file, "w", encoding="utf-8") as f:
        f.write(RULE_PY_TEMPLATE.format(
            rule_id=rule_id,
            rule_id_full=f"rule_{rule_id}",
            rule_name=rule_name,
            category=category_code_name,
            document_name=document_name,
            clause=clause,
            conditions_py=conditions_py,
            severity=severity,
            severity_upper=severity_upper,
            remediation=remediation,
            function_name=function_name
        ))

    # 写入测试文件
    with open(test_file, "w", encoding="utf-8") as f:
        f.write(TEST_PY_TEMPLATE.format(
            rule_id=rule_id,
            rule_id_full=f"rule_{rule_id}",
            rule_name=rule_name,
            severity_upper=severity_upper
        ))

    print(f"Created rule files:")
    print(f"  - {md_file}")
    print(f"  - {py_file}")
    print(f"  - {test_file}")


if __name__ == "__main__":
    # 示例：创建 GOOSE通信链路异常 规则
    create_rule_files(
        rule_id="06001",
        rule_name="GOOSE通信链路异常",
        category="communication",
        document_name="继电保护及二次回路隐患缺陷在线辨识技术规范",
        clause="C.6.2",
        clause_content="GOOSE通信链路异常判定条件",
        conditions=[
            "检测到GOOSE总告警信号",
            "同时检测到GOOSE接收链路异常信号",
            "时间差在±100ms内"
        ],
        severity="严重",
        remediation="检查GOOSE网络配置，确认光纤连接正常，检查交换机端口状态",
        output_dir="../rules"
    )
