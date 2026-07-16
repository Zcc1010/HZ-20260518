"""setting_download_test tool — 仅测试定值单下载，不做解析。

用于排查定值单获取环节的问题。
"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

BASE_URL = "http://10.34.38.113:8020"
LEDGER_API = f"{BASE_URL}/ledger/equipment/secondary"


def _build_download_url(pdf_file_name: str, setting_code: str, setting_type: str) -> str:
    if setting_type == "0":
        if setting_code:
            return f"http://10.138.4.27:8448/ahTransFersysRoot/FileViewServlet?index1={setting_code}&type=2html"
    elif setting_type == "1":
        if pdf_file_name:
            return f"http://10.34.38.113/hddzd/{pdf_file_name}"
    elif setting_type == "2":
        if pdf_file_name:
            return f"http://10.34.38.113/omsdzd/{pdf_file_name}"
    return ""


@tool_parameters(
    tool_parameters_schema(
        deviceName=StringSchema("一次设备名称，如：鼎滨4D25线、安庆变5789线"),
        stName=StringSchema("厂站名称（可选），如：鼎滨变"),
    )
)
class SettingDownloadTestTool(Tool):
    """测试定值单下载功能，仅查询台账和下载PDF文件，不做解析。用于排查定值单获取问题。"""

    @property
    def name(self) -> str:
        return "setting_download_test"

    @property
    def description(self) -> str:
        return (
            "测试定值单下载功能。输入设备名称，自动查询台账、获取定值单详情、尝试下载PDF文件。"
            "不做解析，仅返回每个步骤的结果，用于排查定值单获取问题。\n"
            "参数：deviceName(设备名,必填), stName(厂站名,可选)。\n"
            "当需要排查定值单下载问题时调用此工具。"
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        device_name = (kwargs.get("deviceName") or "").strip()
        st_name = (kwargs.get("stName") or "").strip()

        if not device_name:
            return "错误：请提供设备名称(deviceName)。"

        try:
            return await self._test_download(device_name, st_name)
        except Exception as exc:
            logger.error("setting_download_test failed: {}", exc)
            return f"测试失败：{exc}"

    async def _test_download(self, device_name: str, st_name: str) -> str:
        lines: list[str] = []
        lines.append(f"=== 定值单下载测试 ===")
        lines.append(f"设备名: {device_name}")
        lines.append(f"厂站名: {st_name or '(未指定)'}")
        lines.append("")

        async with httpx.AsyncClient(timeout=60) as client:
            # Step 1: 搜索设备
            candidates = [device_name]
            no_space = device_name.replace(" ", "")
            if no_space != device_name:
                candidates.append(no_space)
            if st_name:
                prefixed = f"{st_name}{no_space}"
                if prefixed not in candidates:
                    candidates.append(prefixed)

            records = []
            used_name = ""
            for name in candidates:
                search_body: dict[str, Any] = {"onceDeviceName": name, "limit": 10, "page": 1}
                if st_name:
                    search_body["stName"] = st_name
                lines.append(f"[步骤1] 搜索设备: {name} ...")
                try:
                    resp = await client.post(f"{LEDGER_API}/getPageList", json=search_body)
                    resp.raise_for_status()
                    data = resp.json().get("data", {})
                    records = data.get("records") or data.get("list") or []
                    lines.append(f"  → 找到 {len(records)} 条记录")
                    if records:
                        used_name = name
                        break
                except Exception as exc:
                    lines.append(f"  → 搜索失败: {exc}")

            if not records:
                # 不限厂站再试一轮
                if st_name:
                    for name in candidates[:2]:
                        lines.append(f"[步骤1] 搜索设备(不限厂站): {name} ...")
                        try:
                            resp = await client.post(f"{LEDGER_API}/getPageList", json={"onceDeviceName": name, "limit": 10, "page": 1})
                            resp.raise_for_status()
                            data = resp.json().get("data", {})
                            records = data.get("records") or data.get("list") or []
                            lines.append(f"  → 找到 {len(records)} 条记录")
                            if records:
                                used_name = name
                                break
                        except Exception:
                            pass

            if not records:
                lines.append("")
                lines.append("结论：未找到设备，请检查设备名称。")
                return "\n".join(lines)

            device = records[0]
            unique_code = device.get("uniqueCode", "")
            actual_name = device.get("onceDeviceName", device_name)
            station = device.get("stName", "")
            lines.append(f"  → 使用设备: {actual_name} ({station})")
            lines.append(f"  → uniqueCode: {unique_code}")
            lines.append("")

            if not unique_code:
                lines.append("结论：设备缺少 uniqueCode，无法继续。")
                return "\n".join(lines)

            # Step 2: 获取定值单详情
            lines.append(f"[步骤2] 获取定值单详情: uniqueCode={unique_code} ...")
            try:
                detail_resp = await client.get(f"{LEDGER_API}/getDzDetailByUniqueCode/{unique_code}")
                detail_resp.raise_for_status()
                detail_data = detail_resp.json().get("data", {})
            except Exception as exc:
                lines.append(f"  → 获取详情失败: {exc}")
                lines.append("")
                lines.append("结论：获取定值单详情失败。")
                return "\n".join(lines)

            detail_list = detail_data.get("dingZhiDetail", []) if isinstance(detail_data, dict) else []
            equipment = detail_list[0] if detail_list else (detail_data if isinstance(detail_data, dict) else {})

            pdf_file = detail_data.get("pdfFileName", "") or ""
            setting_code = equipment.get("settingValueCode", "") or ""
            setting_type = str(equipment.get("settingValueType", "") or "")

            lines.append(f"  → pdfFileName: {pdf_file or '(空)'}")
            lines.append(f"  → settingValueCode: {setting_code or '(空)'}")
            lines.append(f"  → settingValueType: {setting_type or '(空)'}")
            lines.append("")

            # Step 3: 尝试下载
            if setting_type == "0" or not setting_type:
                lines.append(f"[步骤3] type=0 (定值系统), 尝试220kV API ...")
                if not setting_code:
                    lines.append("  → 无 settingValueCode，无法调用220kV API")
                    lines.append("")
                    lines.append("结论：定值系统类型，但缺少 settingValueCode，无法获取PDF。")
                    return "\n".join(lines)

                pdf_url = f"{BASE_URL}/dingzhi/get220kVSettingBookFilePdfX"
                lines.append(f"  → POST {pdf_url}")
                lines.append(f"  → body: [{setting_code}]")
                try:
                    pdf_resp = await client.post(pdf_url, json=[setting_code], timeout=30)
                    lines.append(f"  → 响应: status={pdf_resp.status_code}, size={len(pdf_resp.content)} bytes")
                    if pdf_resp.status_code == 200 and len(pdf_resp.content) > 100:
                        lines.append(f"  → PDF下载成功！")
                        lines.append("")
                        lines.append(f"结论：220kV API 成功获取PDF（{len(pdf_resp.content)} bytes）。")
                    else:
                        lines.append(f"  → 返回内容无效")
                        lines.append(f"  → 响应体前300字: {pdf_resp.text[:300]}")
                        lines.append("")
                        lines.append("结论：220kV API 返回无效内容。")
                except Exception as exc:
                    lines.append(f"  → 请求失败: {exc}")
                    lines.append("")
                    lines.append("结论：220kV API 请求失败。")

            elif setting_type in ("1", "2"):
                source = "华东定值单" if setting_type == "1" else "OMS定值单"
                download_url = _build_download_url(pdf_file, setting_code, setting_type)
                lines.append(f"[步骤3] type={setting_type} ({source}) ...")
                if not download_url:
                    lines.append(f"  → 无法构造下载URL (pdfFileName={pdf_file or '(空)'})")
                    lines.append("")
                    lines.append(f"结论：{source}类型，但无法构造下载链接。")
                    return "\n".join(lines)

                lines.append(f"  → GET {download_url}")
                try:
                    file_resp = await client.get(download_url, follow_redirects=True)
                    file_resp.raise_for_status()
                    ct = file_resp.headers.get("content-type", "")
                    lines.append(f"  → 响应: status={file_resp.status_code}, size={len(file_resp.content)} bytes")
                    lines.append(f"  → content-type: {ct}")
                    if len(file_resp.content) > 100:
                        lines.append(f"  → 文件下载成功！")
                        lines.append("")
                        lines.append(f"结论：{source}文件下载成功（{len(file_resp.content)} bytes, {ct}）。")
                    else:
                        lines.append(f"  → 内容过小或为空")
                        lines.append(f"  → 响应体前300字: {file_resp.text[:300]}")
                        lines.append("")
                        lines.append(f"结论：{source}文件内容无效。")
                except Exception as exc:
                    lines.append(f"  → 下载失败: {exc}")
                    lines.append("")
                    lines.append(f"结论：{source}文件下载失败。")
            else:
                lines.append(f"[步骤3] 未知 settingValueType={setting_type}")
                lines.append("")
                lines.append(f"结论：未知的定值单类型 {setting_type}。")

        return "\n".join(lines)
