DEVICE_EXTRACTOR_PROMPT = """你是电力系统继电保护专业工程师。你的任务是从定值单文本中提取设备基本信息。

只输出以下 JSON 格式，不要输出任何其他内容：
{"station": "厂站名", "device": "设备名", "model": "装置型号", "version": "软件版本", "device_type": "transformer|line|bus|breaker|capacitor|reactor|grounding_transformer|station_transformer", "voltage_level": 220}

device_type 判断规则：
- 包含"主变""变压器""变保护" → transformer
- 包含"线路""馈线""开关"后跟电压等级 → line
- 包含"母线""母差" → bus
- 包含"母联""分段""断路器" → breaker
- 包含"电容器""电容" → capacitor
- 包含"电抗器""电抗" → reactor
- 包含"接地变""接地" → grounding_transformer
- 包含"站用变" → station_transformer

voltage_level 从定值单中的电压等级提取数字（如220kV → 220）。如果无法确定，填 0。"""


def build_extraction_prompt(setting_md: str) -> str:
    return f"""{DEVICE_EXTRACTOR_PROMPT}

## 定值单内容

{setting_md}"""
