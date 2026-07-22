"""Ledger query tool — query secondary equipment ledger via external API."""

from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

BASE_URL = "http://10.34.38.113:8020"
OUT_API_BASE = "http://10.34.38.113:8050"
LEDGER_API_BASE = f"{BASE_URL}/ledger/equipment/secondary"
PAGE_SIZE = 20
AUTO_PAGE_THRESHOLD = 100

# yearCategory 自然语言映射
_YEAR_CATEGORY_ALIASES = {
    "15年以上": "15年及以上",
    "超过15年": "15年及以上",
    "大于15年": "15年及以上",
    "15年以上": "15年及以上",
    "超15年": "15年及以上",
    "12年以上": "12年~15年",
    "12到15年": "12年~15年",
    "12年至15年": "12年~15年",
    "12年到15年": "12年~15年",
    "12-15年": "12年~15年",
    "12年内": "12年以内",
    "12年以内": "12年以内",
    "不到12年": "12年以内",
    "小于12年": "12年以内",
}

_YEAR_CATEGORY_VALID = {"12年以内", "12年~15年", "15年及以上"}

# 查询类型 → 接口映射
# id_source: 从基本信息中提取的 ID 字段名
#   - "onceDeviceId" → 状态类查询（硬压板/软压板/模拟量/开入量/综合状态）
#   - "baoXinId"     → 保信类查询（装置历史/保护事件/保护告警）
#   - "tongFenId"    → 缺陷查询
#   - None           → 使用 uniqueCode
QUERY_TYPE_MAP = {
    "basic": {"label": "基本信息", "method": "GET",
              "url": f"{LEDGER_API_BASE}/getDzDetailByUniqueCode/{{uniqueCode}}"},
    "status": {"label": "综合状态", "method": "GET",
               "url": f"{OUT_API_BASE}/open.api/dispatch/defence/device/mul_new",
               "params": {"methodName": "mulStatusNew"}, "id_source": "baoXinId", "id_param": "onceDeviceId"},
    "hard_press": {"label": "硬压板", "method": "GET",
                   "url": f"{OUT_API_BASE}/open.api/dispatch/defence/device/qj/last",
                   "params": {"methodName": "lastEnableForhard"}, "id_source": "baoXinId", "id_param": "onceDeviceId"},
    "soft_press": {"label": "软压板", "method": "GET",
                   "url": f"{OUT_API_BASE}/open.api/dispatch/defence/device/qj/last",
                   "params": {"methodName": "lastEnable"}, "id_source": "baoXinId", "id_param": "onceDeviceId"},
    "analog": {"label": "模拟量", "method": "GET",
               "url": f"{OUT_API_BASE}/open.api/dispatch/defence/device/qj/last",
               "params": {"methodName": "lastAnalog"}, "id_source": "baoXinId", "id_param": "onceDeviceId"},
    "digital": {"label": "开入量", "method": "GET",
                "url": f"{OUT_API_BASE}/open.api/dispatch/defence/device/qj/last",
                "params": {"methodName": "lastStatus"}, "id_source": "baoXinId", "id_param": "onceDeviceId"},
    "setting": {"label": "定值单", "method": "GET",
                "url": f"{BASE_URL}/dingzhi/getSettingValue",
                "params": {"exType": "false"}, "id_source": "uniqueCode", "id_param": "devId"},
    "bx_setting": {"label": "保信定值", "method": "GET",
                   "url": f"{OUT_API_BASE}/open.api/dispatch/defence/device/qj/last",
                   "params": {"methodName": "lastSetting"}, "id_source": "baoXinId", "id_param": "onceDeviceId"},
    "wave": {"label": "保信录波", "method": "GET",
             "url": f"{BASE_URL}/baoXin/getLbList",
             "id_source": "uniqueCode", "id_param": "uniqueCode"},
    "event": {"label": "保信事件", "method": "GET",
              "url": f"{BASE_URL}/fault/event/getEventByUniqueCode/{{uniqueCode}}",
              "id_source": "uniqueCode"},
    "maintenance": {"label": "检修记录", "method": "POST",
                    "url": f"{BASE_URL}/oss/jhjx/getJhjxListByUniqueCode",
                    "id_source": "uniqueCode", "id_param": "uniqueCode",
                    "json_keys": {"isProtectDev": 2}},
    "history": {"label": "装置历史", "method": "POST",
                "url": f"{BASE_URL}/baoxin/alarm/listAllTypeIedAlarm",
                "id_source": "baoXinId", "id_param": "id",
                "json_keys": {"pageSize": 20, "pageIndex": 0, "sortField": "soeTime", "sortOrder": "desc"}},
    "protect_event": {"label": "保护事件", "method": "POST",
                      "url": f"{BASE_URL}/baoxin/alarm/lastEvent",
                      "id_source": "baoXinId", "id_param": "iedid",
                      "json_keys": {"value": 1}},
    "protect_alarm": {"label": "保护告警", "method": "POST",
                      "url": f"{BASE_URL}/baoxin/alarm/lastAlarm",
                      "id_source": "baoXinId", "id_param": "iedid",
                      "json_keys": {"value": 1}},
    "defect": {"label": "缺陷信息", "method": "POST",
               "url": f"{BASE_URL}/tongFen/defectInfo/getDefectInfoListBySecDeviceId",
               "id_source": "tongFenId", "id_param": "secDeviceId"},
}

QUERY_TYPE_DESC = "、".join(f"{k}({v['label']})" for k, v in QUERY_TYPE_MAP.items())


@tool_parameters(
    tool_parameters_schema(
        stName=StringSchema("厂站名称，如：古泉换流站"),
        stVoltageType=StringSchema("厂站电压等级，如：1000kV、500kV、220kV"),
        onceVoltageType=StringSchema("一次设备电压等级"),
        onceDeviceType=StringSchema("一次设备类型"),
        onceDeviceName=StringSchema("一次设备名称"),
        protectType=StringSchema("保护类型"),
        protectModel=StringSchema("保护型号"),
        protectCover=StringSchema("套别：1=第一套，2=第二套"),
        manufacturer=StringSchema("生产厂家"),
        yearCategory=StringSchema("投运年限，可选值：12年以内、12年~15年、15年及以上（支持别名：超过15年、15年以上等自动映射）"),
        unitName=StringSchema("运维单位（即地区），如用户说'合肥地区'则填'合肥'，'安庆地区'则填'安庆'"),
        uniqueCode=StringSchema("设备唯一编码（查询详情时必填）"),
        onceDeviceId=StringSchema("一次设备ID（从列表结果获取，仅用于状态类查询跳过基本信息请求）"),
        queryType=StringSchema(f"查询类型，可选值：{QUERY_TYPE_DESC}，不填则返回设备列表"),
        eventValue=StringSchema("保护事件/保护告警的状态筛选：1=动作（默认），0=复归。仅对protect_event和protect_alarm有效"),
        isProtectDev=StringSchema("检修记录筛选：0=保护设备，1=非保护设备，2=全部（默认）。仅对maintenance有效"),
        alarmTypes=StringSchema("装置历史告警类型筛选，多个用逗号分隔。可选：异常告警、保护事件、保护遥信。不填则全部。仅对history有效"),
        starttime=StringSchema("开始时间，格式：yyyy-MM-dd HH:mm:ss。仅对history有效"),
        endtime=StringSchema("结束时间，格式：yyyy-MM-dd HH:mm:ss。仅对history有效"),
    )
)
class LedgerQueryTool(Tool):
    """查询二次设备台账信息。可按条件搜索列表，或通过uniqueCode+queryType获取指定类型的详情。"""

    @property
    def name(self) -> str:
        return "ledger_query"

    @property
    def description(self) -> str:
        return (
            "查询二次设备台账信息。两种用法：\n"
            "1. 搜索列表：传stName等筛选条件，不传uniqueCode，返回设备列表。\n"
            "2. 查询详情：传uniqueCode和queryType，返回指定类型的详情。"
            f"queryType可选：{QUERY_TYPE_DESC}。\n"
            "注意：用户说的'地区'指运维单位（unitName），如'合肥地区'='合肥'，'安庆地区'='安庆'。\n"
            "注意区分：setting=定值单（PDF文档），bx_setting=保信定值（装置实时定值，含当前值/标准值/上下限）。\n"
            "关于'反措'：反措（反事故措施）是电力系统为防止事故再次发生而采取的技术改造措施。"
            "常见反措类型包括：保护装置更换/升级、二次回路改造、保护定值修改、软件版本升级、"
            "硬件更换（如CT/PT更换）、防误闭锁改造等。当用户查询反措相关记录时，"
            "应查询检修记录（maintenance），并从工作内容中识别上述关键词。\n"
            "重要限制：搜索到结果后请直接展示给用户，不要重复搜索。"
            "每次用户提问最多调用本工具3次。搜索列表后不要对每台设备逐一查询详情。"
            "如需全面采集多台设备数据，应使用risk_assessment_collect工具。"
            "yearCategory支持自然语言（如'超过15年'自动映射为'15年及以上'）。"
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        unique_code = (kwargs.get("uniqueCode") or "").strip()
        once_device_id = (kwargs.get("onceDeviceId") or "").strip()
        query_type = (kwargs.get("queryType") or "").strip()

        if unique_code or once_device_id:
            if not query_type:
                return f"请指定queryType，可选值：{QUERY_TYPE_DESC}"
            event_value = (kwargs.get("eventValue") or "").strip()
            is_protect_dev = (kwargs.get("isProtectDev") or "").strip()
            alarm_types = (kwargs.get("alarmTypes") or "").strip()
            starttime = (kwargs.get("starttime") or "").strip()
            endtime = (kwargs.get("endtime") or "").strip()
            return await self._fetch_detail(unique_code, query_type, once_device_id, event_value, is_protect_dev, alarm_types, starttime, endtime)

        query_params: dict[str, str] = {}
        for key in (
            "stName", "stVoltageType", "onceVoltageType", "onceDeviceType",
            "onceDeviceName", "protectType", "protectModel", "protectCover",
            "manufacturer", "yearCategory", "unitName",
        ):
            val = kwargs.get(key)
            if val is not None and str(val).strip():
                val_str = str(val).strip()
                if key == "unitName":
                    query_params["unitCode"] = val_str
                elif key == "yearCategory":
                    # 自然语言映射
                    normalized = _YEAR_CATEGORY_ALIASES.get(val_str, val_str)
                    if normalized not in _YEAR_CATEGORY_VALID:
                        return f"yearCategory 值无效：'{val_str}'，可选值：12年以内、12年~15年、15年及以上"
                    query_params[key] = normalized
                else:
                    query_params[key] = val_str

        if not query_params:
            return "请提供至少一个查询条件，如厂站名称、电压等级、套别等。"

        return await self._search(query_params)

    # ------------------------------------------------------------------
    # 搜索列表
    # ------------------------------------------------------------------
    async def _search(self, params: dict[str, str]) -> str:
        all_records: list[dict] = []
        page = 1
        total: int | None = None

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                req_params = {**params, "limit": PAGE_SIZE, "page": page}
                try:
                    resp = await client.post(f"{LEDGER_API_BASE}/getPageList", json=req_params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    logger.error("Ledger API error on page {}: {}", page, exc)
                    if page == 1:
                        return f"台账查询接口请求失败：{exc}"
                    break

                body = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(body, dict):
                    records = body.get("records") or body.get("list") or body.get("rows") or []
                    if total is None:
                        total = body.get("total") or body.get("totalCount") or 0
                elif isinstance(body, list):
                    records = body
                    if total is None:
                        total = len(body)
                else:
                    return f"台账查询返回了未知格式的数据：{str(data)[:500]}"

                all_records.extend(records)

                if not records:
                    break
                if total is not None and len(all_records) >= total:
                    break
                if len(all_records) >= AUTO_PAGE_THRESHOLD:
                    break
                page += 1

        count = len(all_records)
        if count == 0:
            return "未找到匹配的设备记录。请检查查询条件后重试。"

        lines: list[str] = []
        if total and total > count:
            lines.append(f"共 {total} 条记录，当前返回前 {count} 条（如需更多结果请缩小查询范围）：\n")
        else:
            lines.append(f"共 {count} 条记录：\n")

        # 当结果超过30条时，只返回精简列表（避免token过多导致AI反复调用）
        _detail_threshold = 30

        for i, rec in enumerate(all_records, 1):
            name = rec.get("onceDeviceName") or rec.get("stName") or "未知"
            st = rec.get("stName", "")
            voltage = rec.get("stVoltageType") or rec.get("onceVoltageType", "")
            ptype = rec.get("protectType", "")
            model = rec.get("protectModel", "")
            cover = rec.get("protectCover", "")
            cover_label = f"第{cover}套" if cover else ""
            mfr = rec.get("manufacturer", "")
            year_cat = rec.get("yearCategory", "")
            code = rec.get("uniqueCode", "")
            once_id = rec.get("onceDeviceId", "")

            if count <= _detail_threshold:
                parts = [f"{i}. {name}"]
                if st:
                    parts.append(f"厂站: {st}")
                if voltage:
                    parts.append(f"电压: {voltage}")
                if ptype:
                    parts.append(f"保护类型: {ptype}")
                if model:
                    parts.append(f"型号: {model}")
                if cover_label:
                    parts.append(f"套别: {cover_label}")
                if mfr:
                    parts.append(f"厂家: {mfr}")
                if year_cat:
                    parts.append(f"投运年限: {year_cat}")
                if code:
                    parts.append(f"uniqueCode: {code}")
                if once_id:
                    parts.append(f"onceDeviceId: {once_id}")
                lines.append(" | ".join(parts))
            else:
                # 精简格式
                parts = [f"{i}. {name}"]
                if st:
                    parts.append(st)
                if model:
                    parts.append(model)
                if year_cat:
                    parts.append(year_cat)
                lines.append(" | ".join(parts))

        if count >= AUTO_PAGE_THRESHOLD:
            lines.append(f"\n结果较多（>{AUTO_PAGE_THRESHOLD}条），建议添加更多筛选条件缩小范围。")

        if count > 0:
            lines.append(f"\n[搜索完成，共{count}条结果。请直接向用户展示结果，无需再次查询。如需查看详情，使用uniqueCode+queryType查询。]")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 单类型详情
    # ------------------------------------------------------------------
    async def _fetch_detail(self, unique_code: str, query_type: str, once_device_id: str = "", event_value: str = "", is_protect_dev: str = "", alarm_types: str = "", starttime: str = "", endtime: str = "") -> str:
        if query_type not in QUERY_TYPE_MAP:
            return f"未知的queryType: {query_type}，可选值：{QUERY_TYPE_DESC}"

        spec = QUERY_TYPE_MAP[query_type]
        async with httpx.AsyncClient(timeout=30) as client:
            # basic 类型直接请求
            if query_type == "basic":
                if not unique_code:
                    return "查询基本信息需要uniqueCode。"
                url = spec["url"].format(uniqueCode=unique_code)
                data = await self._do_request(client, spec["method"], url)
                if data is None:
                    return f"未找到编码为 {unique_code} 的设备。"
                return self._format_basic(data)

            # --- 非 basic 类型 ---
            id_source = spec.get("id_source")

            # 情况 A：需要 uniqueCode 的查询（URL 内嵌或作为参数）
            if id_source == "uniqueCode":
                if not unique_code:
                    return f"查询{spec['label']}需要uniqueCode。"
                id_val = unique_code
            # 情况 B：需要从基本信息提取 ID（baoXinId / tongFenId）
            elif id_source:
                if not unique_code:
                    return f"查询{spec['label']}需要uniqueCode。"
                basic = await self._do_request(
                    client, "GET",
                    f"{LEDGER_API_BASE}/getDzDetailByUniqueCode/{unique_code}"
                )
                if basic is None:
                    return f"未找到编码为 {unique_code} 的设备。"
                # API 返回 {"pdfFileName":"...", "dingZhiDetail":[{...}]}，ID 嵌套在 dingZhiDetail[0] 中
                detail_list = basic.get("dingZhiDetail", []) if isinstance(basic, dict) else []
                equipment = detail_list[0] if detail_list else (basic if isinstance(basic, dict) else {})
                id_val = str(equipment.get(id_source, "") or "")
                if not id_val:
                    return f"基本信息中未找到 {id_source}，无法查询{spec['label']}。"
            # 情况 C：无 id_source（仅 URL 内嵌 uniqueCode 的 event 类型）
            else:
                id_val = ""

            # 构建请求
            url = spec["url"].format(uniqueCode=unique_code)
            params = dict(spec.get("params", {}))
            json_body = None

            # 将 ID 写入请求参数（仅当 id_source 有定义且需要额外传参时）
            id_param = spec.get("id_param")
            if id_source and id_param:
                if spec["method"] == "GET":
                    params[id_param] = id_val
                else:
                    json_body = {id_param: id_val}

            # POST 请求合并固定参数
            if spec["method"] == "POST" and "json_keys" in spec:
                if json_body is None:
                    json_body = {}
                for k, v in spec["json_keys"].items():
                    json_body[k] = v
                # 保护事件/保护告警支持 动作(1)/复归(0) 筛选
                if query_type in ("protect_event", "protect_alarm") and event_value in ("0", "1"):
                    json_body["value"] = int(event_value)
                # 检修记录支持 是否保护设备 筛选
                if query_type == "maintenance" and is_protect_dev in ("0", "1", "2"):
                    json_body["isProtectDev"] = int(is_protect_dev)
                # 装置历史支持告警类型和时间筛选
                if query_type == "history":
                    _TYPE_MAP = {"异常告警": "1", "保护事件": "2", "保护遥信": "3"}
                    if alarm_types:
                        selected = [t.strip() for t in alarm_types.split(",") if t.strip()]
                        type_values = [_TYPE_MAP[t] for t in selected if t in _TYPE_MAP]
                        if type_values:
                            json_body["types"] = ",".join(type_values)
                            json_body["typeStr"] = selected
                    if starttime:
                        json_body["starttime"] = starttime
                    if endtime:
                        json_body["endtime"] = endtime

            data = await self._do_request(client, spec["method"], url, params=params, json_body=json_body)

        if data is None:
            return f"{spec['label']}查询失败。"

        # 定值单：额外获取基本信息构造 PDF 预览链接
        if query_type == "setting" and unique_code:
            basic = await self._do_request(
                client, "GET",
                f"{LEDGER_API_BASE}/getDzDetailByUniqueCode/{unique_code}"
            )
            if basic and isinstance(basic, dict):
                detail_list = basic.get("dingZhiDetail", [])
                equipment = detail_list[0] if detail_list else basic
                pdf_file = basic.get("pdfFileName", "") or ""
                setting_code = equipment.get("settingValueCode", "") or ""
                setting_type = str(equipment.get("settingValueType", "") or "")
                preview_url = self._build_setting_pdf_url(pdf_file, setting_code, setting_type)
                result = self._format_result(spec["label"], data, query_type)
                if preview_url:
                    result += f"\n\n定值单PDF预览：{preview_url}"
                return result

        return self._format_result(spec["label"], data, query_type)

    # ------------------------------------------------------------------
    # 定值单 PDF 链接构造
    # ------------------------------------------------------------------
    @staticmethod
    def _build_setting_pdf_url(pdf_file_name: str, setting_code: str, setting_type: str) -> str:
        """根据 settingValueType 构造定值单 PDF 预览链接。"""
        import base64
        from urllib.parse import encodeURIComponent

        if setting_type == "0":
            # 定值系统定值单
            if setting_code:
                return f"http://10.138.4.27:8448/ahTransFersysRoot/FileViewServlet?index1={setting_code}&type=2html"
        elif setting_type == "1":
            # 华东定值单
            if pdf_file_name:
                raw_url = f"http://10.34.38.113/hddzd/{pdf_file_name}"
                encoded = base64.b64encode(encodeURIComponent(raw_url).encode()).decode()
                return f"http://10.34.38.113:8012/onlinePreview?url={encoded}"
        elif setting_type == "2":
            # OMS 定值单
            if pdf_file_name:
                raw_url = f"http://10.34.38.113/omsdzd/{pdf_file_name}"
                encoded = base64.b64encode(encodeURIComponent(raw_url).encode()).decode()
                return f"http://10.34.38.113:8012/onlinePreview?url={encoded}"
        return ""

    # ------------------------------------------------------------------
    # HTTP 辅助
    # ------------------------------------------------------------------
    async def _do_request(
        self, client: httpx.AsyncClient, method: str, url: str,
        params: dict | None = None, json_body: dict | None = None,
    ) -> Any | None:
        try:
            if method == "POST":
                resp = await client.post(url, params=params, json=json_body)
            else:
                resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data) if isinstance(data, dict) else data
        except Exception as exc:
            logger.warning("{} {} failed: {}", method, url, exc)
            return None

    # ------------------------------------------------------------------
    # 格式化
    # ------------------------------------------------------------------
    def _format_basic(self, body: dict) -> str:
        lines = ["=== 基本信息 ==="]
        # API 返回 {"pdfFileName":"...", "dingZhiDetail":[{...}]}，字段嵌套在 dingZhiDetail[0] 中
        detail_list = body.get("dingZhiDetail", []) if isinstance(body, dict) else []
        equipment = detail_list[0] if detail_list else body

        fields = [
            ("设备名称", "onceDeviceName"), ("厂站", "stName"),
            ("厂站电压等级", "stVoltageType"), ("一次设备电压等级", "onceVoltageType"),
            ("一次设备类型", "onceDeviceType"), ("保护类型", "protectType"),
            ("保护型号", "protectModel"), ("套别", "protectCover"),
            ("生产厂家", "manufacturer"), ("运维单位", "unitName"),
            ("设备状态", "status"), ("投运年限", "yearCategory"),
            ("调控云ID", "dcloudId"), ("唯一编码", "uniqueCode"),
            ("一次设备编码", "onceDeviceCode"),
            ("一次设备ID", "onceDeviceId"), ("保信ID", "baoXinId"), ("统分ID", "tongFenId"),
        ]
        for label, key in fields:
            val = equipment.get(key)
            if val is not None and str(val).strip():
                if key == "protectCover":
                    val = f"第{val}套"
                lines.append(f"  {label}: {val}")

        setting_list = body.get("settingValueList") or equipment.get("settingValueList")
        if isinstance(setting_list, list) and setting_list:
            lines.append(f"\n  定值比对（初始，共 {len(setting_list)} 项）：")
            for sv in setting_list[:10]:
                name = sv.get("name", "")
                expected = sv.get("expectedValue", sv.get("standardValue", ""))
                actual = sv.get("actualValue", sv.get("currentValue", ""))
                status = sv.get("status", "")
                lines.append(f"    - {name}: 标准值={expected}, 实际值={actual}, 状态={status}")
            if len(setting_list) > 10:
                lines.append(f"    ... 还有 {len(setting_list) - 10} 项")
        return "\n".join(lines)

    def _format_result(self, label: str, data: Any, query_type: str) -> str:
        lines = [f"=== {label} ==="]

        # 综合状态等接口返回 JSON 字符串，需要解析
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                lines.append(f"  {data}")
                return "\n".join(lines)

        # dict 类型直接展平
        if isinstance(data, dict):
            # 综合状态等 dict 结果
            for k, v in data.items():
                if v is not None:
                    lines.append(f"  {k}: {v}")
            # 可能包含 list 的 dict
            inner_list = data.get("list") or data.get("records") or data.get("rows")
            if isinstance(inner_list, list):
                self._format_list_items(inner_list, lines, query_type)
            return "\n".join(lines)

        # list 类型
        if isinstance(data, list):
            if not data:
                lines.append("  无数据")
                return "\n".join(lines)
            self._format_list_items(data, lines, query_type)
            return "\n".join(lines)

        lines.append(f"  {data}")
        return "\n".join(lines)

    def _format_list_items(self, items: list, lines: list[str], query_type: str) -> None:
        limit = 15
        for item in items[:limit]:
            if not isinstance(item, dict):
                lines.append(f"  - {item}")
                continue

            if query_type in ("hard_press", "soft_press", "analog", "digital"):
                name = item.get("name", item.get("desc", ""))
                val = item.get("value", item.get("status", ""))
                lines.append(f"  - {name}: {val}")

            elif query_type == "setting":
                name = item.get("name", "")
                val = item.get("value", item.get("settingValue", ""))
                lines.append(f"  - {name}: {val}")

            elif query_type == "bx_setting":
                name = item.get("name", "")
                val = item.get("value", "")
                unit = item.get("unit", "")
                std = item.get("stdvalue", "")
                vmax = item.get("maxvalue", "")
                vmin = item.get("minvalue", "")
                step = item.get("stepsize", "")
                last = item.get("lastVal", "")
                t = item.get("time", "")
                parts = [f"{name}"]
                if val != "":
                    parts.append(f"当前值: {val}")
                if unit:
                    parts.append(f"单位: {unit}")
                if std != "":
                    parts.append(f"标准值: {std}")
                if vmax != "":
                    parts.append(f"最大值: {vmax}")
                if vmin != "":
                    parts.append(f"最小值: {vmin}")
                if step != "":
                    parts.append(f"步长: {step}")
                if last != "":
                    parts.append(f"上次值: {last}")
                if t:
                    parts.append(f"时间: {t}")
                lines.append(f"  - {' | '.join(parts)}")

            elif query_type == "wave":
                fname = item.get("fileName", item.get("shortName", ""))
                time = item.get("recordTime", item.get("createTime", ""))
                lines.append(f"  - {fname}  ({time})")

            elif query_type in ("history", "protect_event", "protect_alarm"):
                desc = item.get("description", item.get("eventName", item.get("alarmName", "")))
                time = item.get("soeTime", item.get("eventTime", item.get("alarmTime", "")))
                atype = item.get("typeStr", item.get("type", ""))
                val = item.get("value")
                status_label = "动作" if val == 1 else ("复归" if val == 0 else "")
                prefix = f"[{atype}] " if atype else ""
                suffix = f" ({status_label})" if status_label else ""
                lines.append(f"  - {prefix}{desc}  {time}{suffix}")

            elif query_type == "event":
                desc = item.get("description", item.get("eventName", ""))
                time = item.get("eventTime", item.get("soeTime", ""))
                lines.append(f"  - {desc}  {time}")

            elif query_type == "maintenance":
                ticket = item.get("ticketNumber", "")
                device = item.get("deviceName", "")
                content = item.get("declareWorkContent", "")
                begin = item.get("confirmBeginTime", item.get("realBeginTime", ""))
                status = item.get("status", "")
                parts = [p for p in [ticket, device, content, begin, status] if p]
                lines.append(f"  - {' | '.join(parts) if parts else str(list(item.values())[:5])}")

            elif query_type == "defect":
                desc = item.get("defectDesc", item.get("description", ""))
                time = item.get("foundTime", item.get("createTime", ""))
                level = item.get("defectLevel", item.get("level", ""))
                lines.append(f"  - [{level}] {desc}  {time}")

            else:
                # 通用：取前几个字段
                preview = " | ".join(f"{k}: {v}" for k, v in list(item.items())[:5] if v is not None)
                lines.append(f"  - {preview}")

        if len(items) > limit:
            lines.append(f"  ... 还有 {len(items) - limit} 条")
