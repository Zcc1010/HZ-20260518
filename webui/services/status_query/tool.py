"""Status query tool — query protection device running status via external API."""

from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

BASE_URL = "http://10.34.38.113:8020"
STATUS_API = f"{BASE_URL}/baoXin/mulStatusNew/getPageList"
PAGE_SIZE = 50
AUTO_PAGE_THRESHOLD = 200

# 电压等级
VOLTAGE_TYPES = {"1000kV", "500kV", "220kV"}

# 保护类型
PROTECT_TYPES = {"线路保护", "母线保护", "变压器保护", "断路器保护"}

# 状态值映射（用户可读 → 编码）
STATUS_MAP = {
    "投入": "1", "退出": "2", "未知": "0", "无效": "3",
    "1": "1", "2": "2", "0": "0", "3": "3",
}

# 校核状态映射
CHECK_STATUS_MAP = {
    "正常": "1", "校核正常": "1",
    "异常": "2", "校核异常": "2",
    "参数异常": "3",
    "配置异常": "4",
}

# 设备状态
OSS_STATUS_LIST = ["检修中", "运行中", "待投运", "无状态"]

# 通信状态
IED_STATUS_MAP = {"正常": "1", "断开": "0", "1": "1", "0": "0"}

# 硬压板监测
YBJZ_MAP = {"已监视": "1", "未监视": "0", "1": "1", "0": "0"}


def _norm_status(val: str | None) -> str:
    """将用户输入的状态文本转为编码。"""
    if not val or not val.strip():
        return ""
    v = val.strip()
    return STATUS_MAP.get(v, v)


def _norm_check_status(val: str | None) -> list[str]:
    """将校核状态文本转为编码列表。"""
    if not val or not val.strip():
        return []
    parts = [p.strip() for p in val.replace("、", ",").replace("，", ",").split(",") if p.strip()]
    result = []
    for p in parts:
        code = CHECK_STATUS_MAP.get(p, p)
        if code in ("1", "2", "3", "4"):
            result.append(code)
    return result


def _norm_ied_status(val: str | None) -> str:
    if not val or not val.strip():
        return ""
    return IED_STATUS_MAP.get(val.strip(), "")


def _norm_ybjz(val: str | None) -> str:
    if not val or not val.strip():
        return ""
    return YBJZ_MAP.get(val.strip(), "")


def _norm_oss_status(val: str | None) -> str:
    if not val or not val.strip():
        return ""
    v = val.strip()
    return v if v in OSS_STATUS_LIST else ""


# 不同保护类型的 status 参数含义映射
# key: (protectType, 用户可读参数名) → queryParams 中的字段名
STATUS_FIELD_MAP = {
    # === 线路保护 500kV/1000kV (line_high) ===
    ("线路保护", "主保护"): "status1",
    ("线路保护", "后备保护"): "status2",
    ("线路保护", "跳闸出口"): "status6",
    ("线路保护", "重合闸功能"): "status3",
    ("线路保护", "重合闸状态"): "status4",
    ("线路保护", "合闸出口"): "status5",
    # === 母线保护 ===
    ("母线保护", "主保护"): "status1",
    ("母线保护", "失灵经母差跳闸"): "status2",
    ("母线保护", "失灵保护"): "status2",
    ("母线保护", "选择性方式"): "status13",
    ("母线保护", "互联方式"): "status11",
    ("母线保护", "分列方式"): "status12",
    # === 变压器保护 ===
    ("变压器保护", "主保护"): "status1",
    ("变压器保护", "高压侧后备保护"): "status2",
    ("变压器保护", "高后备"): "status2",
    ("变压器保护", "间隙保护"): "status2",
    ("变压器保护", "高后备间隙保护"): "status2",
    ("变压器保护", "零序过流"): "status3",
    ("变压器保护", "高后备零序过流"): "status3",
    ("变压器保护", "中压侧后备保护"): "status4",
    ("变压器保护", "中后备"): "status4",
    ("变压器保护", "低压侧后备保护"): "status5",
    ("变压器保护", "低后备"): "status5",
    ("变压器保护", "高压侧出口"): "status6",
    ("变压器保护", "中压侧出口"): "status7",
    ("变压器保护", "低压侧出口"): "status8",
    ("变压器保护", "低压绕组后备保护"): "status9",
    ("变压器保护", "公共绕组后备保护"): "status10",
    # === 断路器保护 ===
    ("断路器保护", "充电过流保护"): "status1",
    ("断路器保护", "失灵保护"): "status2",
    ("断路器保护", "重合闸功能"): "status3",
    ("断路器保护", "重合闸状态"): "status4",
    ("断路器保护", "合闸出口"): "status5",
    ("断路器保护", "跳闸出口"): "status6",
}

# 通用映射（不依赖 protectType）
COMMON_STATUS_FIELDS = {
    "主保护": "status1",
}


def _resolve_status_field(protect_type: str, label: str) -> str | None:
    """根据保护类型和用户可读的状态名称，返回 queryParams 字段名。"""
    key = (protect_type, label)
    if key in STATUS_FIELD_MAP:
        return STATUS_FIELD_MAP[key]
    # 兜底：通用映射
    return COMMON_STATUS_FIELDS.get(label)


TOOL_DESC = """查询保护设备运行状态统计数据。数据来自保信综合状态页面。

必填参数：voltageType（电压等级）和 protectType（保护类型）。

voltageType 可选：1000kV、500kV、220kV
protectType 可选：线路保护、母线保护、变压器保护、断路器保护

筛选参数说明（均为可选，用自然语言描述即可）：
- stName: 厂站名称，如"安庆"、"古泉"
- iedName: 装置名称
- unitName: 运维单位
- 主保护: 投入/退出/未知/无效
- 后备保护: 投入/退出/未知/无效（线路保护用）
- 失灵保护/失灵经母差跳闸: 投入/退出/未知/无效（母线/断路器用）
- 跳闸出口/合闸出口: 投入/退出/未知/无效
- 重合闸功能/重合闸状态: 投入/退出/未知/无效
- 高压侧后备保护/中压侧后备保护/低压侧后备保护: 变压器用
- 高压侧出口/中压侧出口/低压侧出口: 变压器用
- 选择性方式/互联方式/分列方式: 220kV母线用
- checkStatus: 校核状态，如"异常"、"正常"、"参数异常"、"配置异常"，多个用逗号分隔
- ossStatus: 设备状态，如"运行中"、"检修中"
- iedStatus: 通信状态，如"正常"、"断开"
- isYbjz: 硬压板监测，如"已监视"、"未监视"

示例用法：
- 查安庆的220kV线路保护：voltageType=220kV, protectType=线路保护, stName=安庆
- 500kV母线保护校核异常：voltageType=500kV, protectType=母线保护, checkStatus=异常
- 变压器保护主保护退出：protectType=变压器保护, 主保护=退出
"""


@tool_parameters(
    tool_parameters_schema(
        voltageType=StringSchema("电压等级：1000kV、500kV、220kV"),
        protectType=StringSchema("保护类型：线路保护、母线保护、变压器保护、断路器保护"),
        stName=StringSchema("厂站名称，支持模糊匹配，如：安庆、古泉"),
        iedName=StringSchema("装置名称"),
        unitName=StringSchema("运维单位"),
        mainProtect=StringSchema("主保护状态：投入/退出/未知/无效"),
        backupProtect=StringSchema("后备保护状态：投入/退出/未知/无效（线路保护用）"),
        failProtect=StringSchema("失灵保护状态：投入/退出/未知/无效（母线保护/断路器保护用）"),
        tripExport=StringSchema("跳闸出口状态：投入/退出/未知/无效"),
        closeExport=StringSchema("合闸出口状态：投入/退出/未知/无效"),
        recloseFunc=StringSchema("重合闸功能状态：投入/退出/未知/无效"),
        recloseStatus=StringSchema("重合闸状态：投入/退出/未知/无效"),
        highBackup=StringSchema("高压侧后备保护状态：投入/退出/未知/无效（变压器用）"),
        midBackup=StringSchema("中压侧后备保护状态：投入/退出/未知/无效（变压器用）"),
        lowBackup=StringSchema("低压侧后备保护状态：投入/退出/未知/无效（变压器用）"),
        highExport=StringSchema("高压侧出口状态：投入/退出/未知/无效（变压器用）"),
        midExport=StringSchema("中压侧出口状态：投入/退出/未知/无效（变压器用）"),
        lowExport=StringSchema("低压侧出口状态：投入/退出/未知/无效（变压器用）"),
        lowWindingBackup=StringSchema("低压绕组后备保护状态：投入/退出/未知/无效（变压器用）"),
        commonWindingBackup=StringSchema("公共绕组后备保护状态：投入/退出/未知/无效（变压器用）"),
        selectMode=StringSchema("选择性方式：投入/退出/未知（220kV母线用）"),
        interconnectMode=StringSchema("互联方式：投入/退出/未知（220kV母线用）"),
        splitMode=StringSchema("分列方式：投入/退出/未知（220kV母线用）"),
        chargeOvercurrent=StringSchema("充电过流保护状态：投入/退出/未知/无效（断路器用）"),
        checkStatus=StringSchema("校核状态：正常/异常/参数异常/配置异常，多个用逗号分隔"),
        ossStatus=StringSchema("设备状态：检修中/运行中/待投运/无状态"),
        iedStatus=StringSchema("通信状态：正常/断开"),
        isYbjz=StringSchema("硬压板监测：已监视/未监视"),
    )
)
class StatusQueryTool(Tool):
    """查询保护设备运行状态统计数据。按电压等级和保护类型查询，支持多种筛选条件。"""

    @property
    def name(self) -> str:
        return "status_query"

    @property
    def description(self) -> str:
        return TOOL_DESC

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        voltage_type = (kwargs.get("voltageType") or "").strip()
        protect_type = (kwargs.get("protectType") or "").strip()

        if not voltage_type:
            return "请指定电压等级(voltageType)，可选：1000kV、500kV、220kV"
        if voltage_type not in VOLTAGE_TYPES:
            return f"电压等级'{voltage_type}'不正确，可选：1000kV、500kV、220kV"

        if not protect_type:
            return "请指定保护类型(protectType)，可选：线路保护、母线保护、变压器保护、断路器保护"
        if protect_type not in PROTECT_TYPES:
            return f"保护类型'{protect_type}'不正确，可选：线路保护、母线保护、变压器保护、断路器保护"

        # 构建查询参数
        params: dict[str, Any] = {
            "voltageType": voltage_type,
            "protectType": protect_type,
            "limit": PAGE_SIZE,
            "page": 1,
        }

        # 通用筛选
        st_name = (kwargs.get("stName") or "").strip()
        ied_name = (kwargs.get("iedName") or "").strip()
        unit_name = (kwargs.get("unitName") or "").strip()
        if st_name:
            params["stName"] = st_name
        if ied_name:
            params["iedName"] = ied_name
        if unit_name:
            params["unitName"] = unit_name

        # 校核状态
        check_raw = (kwargs.get("checkStatus") or "").strip()
        check_codes = _norm_check_status(check_raw)
        if check_codes:
            params["checkStatusList"] = check_codes

        # 设备状态
        oss = _norm_oss_status(kwargs.get("ossStatus"))
        if oss:
            params["ossStatus"] = oss

        # 通信状态
        ied = _norm_ied_status(kwargs.get("iedStatus"))
        if ied:
            params["iedStatus"] = ied

        # 硬压板监测
        ybjz = _norm_ybjz(kwargs.get("isYbjz"))
        if ybjz:
            params["isYbjz"] = ybjz

        # 状态类筛选（根据保护类型映射到正确的 status 字段）
        status_params = {
            "主保护": kwargs.get("mainProtect"),
            "后备保护": kwargs.get("backupProtect"),
            "失灵保护": kwargs.get("failProtect"),
            "失灵经母差跳闸": kwargs.get("failProtect"),
            "跳闸出口": kwargs.get("tripExport"),
            "合闸出口": kwargs.get("closeExport"),
            "重合闸功能": kwargs.get("recloseFunc"),
            "重合闸状态": kwargs.get("recloseStatus"),
            "高压侧后备保护": kwargs.get("highBackup"),
            "高后备": kwargs.get("highBackup"),
            "间隙保护": kwargs.get("highBackup"),
            "中压侧后备保护": kwargs.get("midBackup"),
            "中后备": kwargs.get("midBackup"),
            "低压侧后备保护": kwargs.get("lowBackup"),
            "低后备": kwargs.get("lowBackup"),
            "高压侧出口": kwargs.get("highExport"),
            "中压侧出口": kwargs.get("midExport"),
            "低压侧出口": kwargs.get("lowExport"),
            "低压绕组后备保护": kwargs.get("lowWindingBackup"),
            "公共绕组后备保护": kwargs.get("commonWindingBackup"),
            "选择性方式": kwargs.get("selectMode"),
            "互联方式": kwargs.get("interconnectMode"),
            "分列方式": kwargs.get("splitMode"),
            "充电过流保护": kwargs.get("chargeOvercurrent"),
        }

        for label, raw_val in status_params.items():
            if not raw_val or not str(raw_val).strip():
                continue
            code = _norm_status(str(raw_val))
            if not code:
                continue
            field = _resolve_status_field(protect_type, label)
            if field:
                params[field] = code

        return await self._query(params)

    async def _query(self, params: dict[str, Any]) -> str:
        all_records: list[dict] = []
        page_num = 1
        total: int | None = None

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params["page"] = page_num
                try:
                    resp = await client.post(STATUS_API, json=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    logger.error("Status API error on page {}: {}", page_num, exc)
                    if page_num == 1:
                        return f"运行状态查询接口请求失败：{exc}"
                    break

                body = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(body, dict):
                    records = body.get("list") or body.get("records") or []
                    if total is None:
                        total = body.get("total") or 0
                elif isinstance(body, list):
                    records = body
                    if total is None:
                        total = len(body)
                else:
                    return f"运行状态查询返回了未知格式：{str(data)[:500]}"

                all_records.extend(records)

                if not records:
                    break
                if total is not None and len(all_records) >= total:
                    break
                if len(all_records) >= AUTO_PAGE_THRESHOLD:
                    break
                page_num += 1

        count = len(all_records)
        if count == 0:
            return "未找到匹配的记录。请检查查询条件后重试。"

        # 格式化输出
        voltage = params.get("voltageType", "")
        protect = params.get("protectType", "")
        header = f"共 {count} 条记录"
        if total and total > count:
            header += f"（共{total}条，已返回前{count}条）"
        header += f" | {voltage} {protect}\n"

        # 根据保护类型选择展示列
        columns = self._get_display_columns(protect, voltage)

        # 中文表头
        headers = [_get_column_label(protect, voltage, col) for col in columns]

        lines = [header]
        lines.append(" | ".join(headers))
        lines.append("-" * 80)

        for i, rec in enumerate(all_records, 1):
            row_parts = [str(i)]
            for col in columns:
                val = rec.get(col, "")
                if val is None:
                    val = ""
                # 状态字段转可读文本
                if col in ("status1", "status2", "status3", "status4", "status5",
                           "status6", "status7", "status8", "status9", "status10",
                           "status11", "status12", "status13"):
                    val = _status_to_text(str(val))
                elif col == "checkStatus":
                    val = _check_status_to_text(str(val))
                row_parts.append(str(val))
            lines.append(" | ".join(row_parts))

        return "\n".join(lines)

    def _get_display_columns(self, protect_type: str, voltage_type: str = "") -> list[str]:
        """根据保护类型和电压等级返回展示列。"""
        base = ["序号", "stName", "iedName", "unitName"]
        tail = ["checkStatus", "ossStatus", "abnormalTime"]
        is_220 = voltage_type == "220kV"

        if protect_type == "线路保护":
            cols = ["status1", "status2"]
            if is_220:
                cols += ["status3", "status4", "status5"]
            cols.append("status6")
            return base + cols + tail
        elif protect_type == "母线保护":
            cols = ["status1", "status2"]
            if is_220:
                cols += ["status13", "status11", "status12"]
            return base + cols + tail
        elif protect_type == "变压器保护":
            if is_220:
                return base + ["status1", "status2", "status3", "status4", "status5",
                               "status6", "status7", "status8"] + tail
            return base + ["status1", "status2", "status4", "status5",
                           "status6", "status7", "status8", "status9", "status10"] + tail
        elif protect_type == "断路器保护":
            return base + ["status1", "status2", "status3", "status4", "status5", "status6"] + tail
        return base + ["status1"] + tail


def _status_to_text(code: str) -> str:
    return {"0": "未知", "1": "投入", "2": "退出", "3": "无效"}.get(code, code)


def _check_status_to_text(code: str) -> str:
    return {"1": "正常", "2": "异常", "3": "参数异常", "4": "配置异常"}.get(code, code)


# 通用列标签（不依赖保护类型）
_COMMON_LABELS = {
    "序号": "序号",
    "stName": "厂站",
    "iedName": "装置名称",
    "unitName": "运维单位",
    "checkStatus": "校核状态",
    "ossStatus": "设备状态",
    "abnormalTime": "异常发生时间",
    "status1": "主保护",
}

# 按 (保护类型, 电压等级, 字段名) 定义的标签覆盖
_COLUMN_LABEL_MAP: dict[tuple[str, str, str], str] = {
    # === 线路保护 500kV/1000kV ===
    ("线路保护", "500kV", "status2"): "后备保护",
    ("线路保护", "500kV", "status6"): "跳闸出口",
    ("线路保护", "1000kV", "status2"): "后备保护",
    ("线路保护", "1000kV", "status6"): "跳闸出口",
    # === 线路保护 220kV ===
    ("线路保护", "220kV", "status2"): "后备保护",
    ("线路保护", "220kV", "status3"): "重合闸功能",
    ("线路保护", "220kV", "status4"): "重合闸状态",
    ("线路保护", "220kV", "status5"): "合闸出口",
    ("线路保护", "220kV", "status6"): "跳闸出口",
    # === 母线保护 500kV/1000kV ===
    ("母线保护", "500kV", "status2"): "失灵经母差跳闸",
    ("母线保护", "1000kV", "status2"): "失灵经母差跳闸",
    # === 母线保护 220kV ===
    ("母线保护", "220kV", "status2"): "失灵保护",
    ("母线保护", "220kV", "status13"): "选择性方式",
    ("母线保护", "220kV", "status11"): "互联方式",
    ("母线保护", "220kV", "status12"): "分列方式",
    # === 变压器保护 500kV/1000kV ===
    ("变压器保护", "500kV", "status2"): "高压侧后备保护",
    ("变压器保护", "500kV", "status4"): "中压侧后备保护",
    ("变压器保护", "500kV", "status5"): "低压侧后备保护",
    ("变压器保护", "500kV", "status6"): "高压侧出口",
    ("变压器保护", "500kV", "status7"): "中压侧出口",
    ("变压器保护", "500kV", "status8"): "低压侧出口",
    ("变压器保护", "500kV", "status9"): "低压绕组后备保护",
    ("变压器保护", "500kV", "status10"): "公共绕组后备保护",
    ("变压器保护", "1000kV", "status2"): "高压侧后备保护",
    ("变压器保护", "1000kV", "status4"): "中压侧后备保护",
    ("变压器保护", "1000kV", "status5"): "低压侧后备保护",
    ("变压器保护", "1000kV", "status6"): "高压侧出口",
    ("变压器保护", "1000kV", "status7"): "中压侧出口",
    ("变压器保护", "1000kV", "status8"): "低压侧出口",
    ("变压器保护", "1000kV", "status9"): "低压绕组后备保护",
    ("变压器保护", "1000kV", "status10"): "公共绕组后备保护",
    # === 变压器保护 220kV ===
    ("变压器保护", "220kV", "status2"): "高后备(间隙保护)",
    ("变压器保护", "220kV", "status3"): "高后备(零序过流)",
    ("变压器保护", "220kV", "status4"): "中后备保护",
    ("变压器保护", "220kV", "status5"): "低后备",
    ("变压器保护", "220kV", "status6"): "高压侧出口",
    ("变压器保护", "220kV", "status7"): "中压侧出口",
    ("变压器保护", "220kV", "status8"): "低压侧出口",
    # === 断路器保护 ===
    ("断路器保护", "", "status1"): "充电过流保护",
    ("断路器保护", "", "status2"): "失灵保护",
    ("断路器保护", "", "status3"): "重合闸功能",
    ("断路器保护", "", "status4"): "重合闸状态",
    ("断路器保护", "", "status5"): "合闸出口",
    ("断路器保护", "", "status6"): "跳闸出口",
}


def _get_column_label(protect_type: str, voltage_type: str, field: str) -> str:
    """返回列的中文标签。"""
    if field in _COMMON_LABELS:
        return _COMMON_LABELS[field]
    key = (protect_type, voltage_type, field)
    if key in _COLUMN_LABEL_MAP:
        return _COLUMN_LABEL_MAP[key]
    # 兜底：尝试不带电压的通用映射
    key_any = (protect_type, "", field)
    if key_any in _COLUMN_LABEL_MAP:
        return _COLUMN_LABEL_MAP[key_any]
    return field
