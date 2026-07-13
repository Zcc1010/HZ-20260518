---
name: setting-parser
description: >
  调度定值单解析工具。当用户需要从 PDF/Excel 调度定值单中提取定值项、控制字、设备参数，
  或要求"解析这份定值单"、"把定值单转成JSON"、"统计定值单异常"时使用。
  使用 LLM 自动识别定值项结构，输出标准化 JSON，支持统计分析和异常检测。
---

# 调度定值单解析工具

## Overview

从 PDF/Excel 调度定值单中自动识别定值项、控制字、设备参数，输出结构化 JSON。
支持统计分析、异常检测、定值项描述生成。

## When to Use

用户口径（自然语言直接触发）：

- "解析这份**定值单**"
- "把定值单转成 **JSON**"
- "这份定值单里有哪些**定值项**？"
- "统计一下这些定值单的**异常**"
- "帮我看看定值单里有没有**超限**的值"
- "**差动保护电流定值**是什么意思？"

**不要用于：** 定值单与计算书校核（→ setting-check），运行风险评估（→ protection-risk-assessment）。

## 使用方式

### 1. 解析定值单

```bash
setting-parser parse 定值单/*.pdf --output-dir output/parsed/
```

支持格式：PDF（主要）、Excel

### 2. 统计分析

```bash
setting-parser stats output/parsed/*.json --anomaly-check --summary-output output/report.md
```

功能：
- 描述性统计（定值项数量、范围、分组）
- 异常检测（与说明书 min/max 对比、控制字合法性）
- LLM 总结报告

### 3. 查询定值项描述

```bash
setting-parser describe "差动保护电流定值" --from output/parsed/锦绣变*PCS-931*.json
```

### 4. 知识库管理

```bash
setting-parser kb list              # 列出可用知识库
setting-parser kb lookup PCS-931    # 查询特定型号知识库
```

## 配置

需要设置环境变量（OpenAI 兼容 LLM）：

```bash
export SETTING_PARSER_LLM_API_KEY=sk-xxx
export SETTING_PARSER_LLM_BASE_URL=https://api.openai.com/v1
export SETTING_PARSER_LLM_MODEL=qwen-plus
```

## 输出格式

每份定值单输出一个 `*.json`，包含：

| 字段 | 说明 |
|---|---|
| `device` | 设备信息（厂站、电压等级、间隔、套别） |
| `protection_device` | 保护装置信息（厂家、型号、固件版本） |
| `equipment_params` | 设备参数（CT/PT变比、额定电流） |
| `settings[]` | 定值项列表（名称、值、单位、知识库引用） |
| `control_words[]` | 控制字列表（名称、值、含义） |
| `trip_matrix` | 跳闸矩阵（如有） |
| `parse_warnings` | 解析警告 |

## 知识库复用

默认复用 `setting-check` 的说明书知识库，可通过 `--kb-path` 覆盖。

## 相关技能（按需调用）

| 场景 | 调用 |
|---|---|
| 定值单与计算书校核 | `setting-check` |
| 运行风险评估 | `protection-risk-assessment` |
| 保护装置说明书解析 | `extract-manual` |

## Real-World Impact

将"人工逐条抄录定值单"转为"自动结构化提取"——把定值单从 PDF/Excel 文档转为可查询、可统计、可对比的 JSON 格式，为下游分析（校核、统计、异常检测）提供标准化数据源。
