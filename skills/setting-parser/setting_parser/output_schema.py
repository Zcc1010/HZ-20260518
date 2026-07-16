"""定值单解析输出 schema — 单一来源，tool 和 prompt 共用。"""

# 解析输出的 JSON schema
PARSER_OUTPUT_SCHEMA = {
    "device": {
        "station": "变电站名",
        "voltage_kv": 220,
        "equipment_type": "线路保护|母线保护|变压器保护|其他",
        "equipment_name": "线路/母线/主变名",
        "protection_set": "第一套|第二套|单套",
    },
    "protection_device": {
        "vendor": "厂家名",
        "model_raw": "原型号字符串",
        "model_base": "基础型号（如 PCS-931）",
        "firmware_version": "软件版本",
        "device_id": "装置 ID",
    },
    "equipment_params": {
        "ct_ratio_primary": 3200,
        "ct_ratio_secondary": 1,
        "pt_ratio_primary": 220,
        "pt_ratio_secondary": None,
    },
    "settings": [
        {
            "item_no": "序号",
            "name_raw": "定值项原名",
            "value": "原值字符串",
            "value_numeric": 0.0,
            "unit": "单位",
            "function": "所属保护功能",
        }
    ],
    "control_words": [
        {
            "name_raw": "控制字原名",
            "value": "0/1 或 hex",
            "meaning": "投退含义",
        }
    ],
    "parse_warnings": [],
}

# 解析规则说明
PARSER_OUTPUT_RULES = """规则：
1. 抽不到的字段填 null，在 parse_warnings 记录
2. value_numeric 仅在明显是数字时填，否则为 null
3. 一次值和二次值都有时，value 填二次值（定值单通常以二次值为准）
4. 只输出 JSON，不要解释文字"""

# schema 的 JSON 字符串（供 prompt 使用）
import json

PARSER_OUTPUT_SCHEMA_JSON = json.dumps(PARSER_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)

# 完整的解析指令（schema + 规则）
PARSER_INSTRUCTION = f"""请从定值单内容中抽取结构化数据，严格按以下 JSON schema 输出：

```json
{PARSER_OUTPUT_SCHEMA_JSON}
```

{PARSER_OUTPUT_RULES}"""
