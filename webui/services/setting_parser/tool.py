"""setting_parse_device tool — 从台账自动下载定值单并解析。

Agent 调用此工具后，自动完成：查询台账 → 下载定值单文件 → 解析 → 返回结构化结果。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

BASE_URL = "http://10.34.38.113:8020"
LEDGER_API = f"{BASE_URL}/ledger/equipment/secondary"


def _build_setting_pdf_url(pdf_file_name: str, setting_code: str, setting_type: str) -> str:
    """根据 settingValueType 构造定值单下载链接。

    type 0（定值系统）：使用定值系统 FileViewServlet 预览。
    type 1/2 返回直接下载 PDF 的 URL。
    """
    if setting_type == "0":
        # 定值系统：使用 FileViewServlet 预览
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
        deviceName=StringSchema("一次设备名称，如：安庆变5789线、红马2C51线"),
        stName=StringSchema("厂站名称（可选，用于精确匹配），如：安庆变"),
    )
)
class SettingParseDeviceTool(Tool):
    """从二次设备台账自动下载定值单文件并解析为结构化 JSON。"""

    @property
    def name(self) -> str:
        return "setting_parse_device"

    @property
    def description(self) -> str:
        return (
            "下载并解析设备的定值单文件（PDF文档）。注意：这是「定值单」（调度下发的整定通知单PDF），不是装置运行时的「定值数据」。\n"
            "输入设备名称（如'安庆变5789线'），自动完成：查询台账→下载定值单PDF→提取文本→返回内容。\n"
            "支持三种定值单来源：定值系统（220kV）、华东定值单、OMS定值单。\n"
            "会自动尝试多种设备名称格式（去空格、加厂站前缀等）。\n"
            "参数：deviceName(设备名,必填), stName(厂站名,可选用于精确匹配)。\n"
            "触发条件：用户说「解析定值单」「查看定值单」「下载定值单」「定值单内容」「定值单分析」等涉及定值单文档的操作时调用此工具。"
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
            result = await self._download_and_parse(device_name, st_name)
            logger.info("[setting_parse_device] result ({} chars): {}...", len(result), result[:200])
            return result
        except Exception as exc:
            logger.error("setting_parse_device failed: {}", exc)
            return f"定值单解析失败：{exc}"

    async def _download_and_parse(self, device_name: str, st_name: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            # 1. 搜索设备（自动尝试多种名称格式）
            records = await self._search_device(client, device_name, st_name)
            if not records:
                logger.warning("[setting_parse_device] 未找到设备: device_name={}, st_name={}", device_name, st_name)
                return (
                    f"未找到设备：{device_name}，请确认设备名称是否正确。"
                )

            logger.info("[setting_parse_device] 找到 {} 个设备，逐一处理", len(records))

            # 2. 逐一处理每个匹配设备
            results: list[str] = []
            for idx, device in enumerate(records):
                actual_name = device.get("onceDeviceName", device_name)
                station = device.get("stName", "")
                cover = device.get("protectCover", "")
                cover_label = f"第{cover}套" if cover else ""
                model = device.get("protectModel", "")
                unique_code = device.get("uniqueCode", "")

                header_parts = [actual_name]
                if station:
                    header_parts.append(station)
                if cover_label:
                    header_parts.append(cover_label)
                if model:
                    header_parts.append(model)
                header = " | ".join(header_parts)

                if not unique_code:
                    results.append(f"=== {header} ===\n缺少 uniqueCode，无法查询定值单。")
                    continue

                try:
                    result = await self._process_single_device(client, device, device_name)
                    results.append(f"=== {header} ===\n{result}")
                except Exception as exc:
                    logger.error("[setting_parse_device] 处理设备 {} 失败: {}", actual_name, exc)
                    results.append(f"=== {header} ===\n定值单解析失败：{exc}")

            if not results:
                return f"设备 {device_name} 的定值单解析均失败。"

            if len(results) == 1:
                # 单设备：去掉头部的 === ... === 行
                return results[0].split("\n", 1)[-1] if results[0].startswith("===") else results[0]

            # 多设备：返回所有结果
            return f"找到 {len(results)} 个设备的定值单：\n\n" + "\n\n---\n\n".join(results)

    async def _process_single_device(
        self, client: httpx.AsyncClient, device: dict, fallback_name: str,
    ) -> str:
        """处理单个设备的定值单下载和解析。"""
        unique_code = device.get("uniqueCode", "")
        actual_name = device.get("onceDeviceName", fallback_name)
        station = device.get("stName", "")

        # 1. 获取定值单详情
        logger.info("[setting_parse_device] 获取设备详情: {} uniqueCode={}", actual_name, unique_code)
        detail_resp = await client.get(f"{LEDGER_API}/getDzDetailByUniqueCode/{unique_code}")
        detail_resp.raise_for_status()
        detail_data = detail_resp.json().get("data", {})
        logger.info("[setting_parse_device] 设备详情获取完成, settingValueType={}", detail_data.get("dingZhiDetail", [{}])[0].get("settingValueType", "") if isinstance(detail_data, dict) else "")

        detail_list = detail_data.get("dingZhiDetail", []) if isinstance(detail_data, dict) else []
        equipment = detail_list[0] if detail_list else (detail_data if isinstance(detail_data, dict) else {})

        pdf_file = detail_data.get("pdfFileName", "") or ""
        setting_code = equipment.get("settingValueCode", "") or ""
        setting_type = str(equipment.get("settingValueType", "") or "")

        # 2. type 0 或类型未知：尝试获取定值单PDF文件
        if setting_type == "0" or not setting_type:
            if setting_code:
                try:
                    pdf_url = f"{BASE_URL}/dingzhi/get220kVSettingBookFilePdfX"
                    logger.info("[setting_parse_device] 尝试220kV API: settingCode={}", setting_code)
                    pdf_resp = await client.post(pdf_url, json=[setting_code], timeout=30)
                    logger.info("[setting_parse_device] 220kV API 响应: status={}, size={}", pdf_resp.status_code, len(pdf_resp.content))
                    if pdf_resp.status_code == 200 and len(pdf_resp.content) > 100:
                        result = await self._parse_pdf_content(
                            pdf_resp.content, f"{actual_name}_定值单.pdf", actual_name, station,
                            "定值系统（220kV）",
                        )
                        if result:
                            return result
                    else:
                        logger.warning("[setting_parse_device] 220kV API 返回无效: status={}, size={}",
                                       pdf_resp.status_code, len(pdf_resp.content))
                except Exception as exc:
                    logger.warning("[setting_parse_device] 220kV API 失败: {}", exc)
            else:
                logger.info("[setting_parse_device] 设备 {} 无 settingValueCode，跳过220kV API", actual_name)

            return f"设备 {actual_name}（{station}）在定值系统中未找到定值单PDF文件，无法自动解析。"

        # 3. type 1/2：构造下载 URL
        download_url = _build_setting_pdf_url(pdf_file, setting_code, setting_type)
        if not download_url:
            logger.warning(
                "[setting_parse_device] 无法构造下载URL: device={}, pdfFile={}, settingCode={}, settingType={}",
                actual_name, pdf_file, setting_code, setting_type,
            )
            return f"设备 {actual_name}（{station}）无法构造定值单下载链接。"

        # 4. 下载文件
        logger.info("Downloading setting sheet from: {}", download_url)
        try:
            file_resp = await client.get(download_url, follow_redirects=True)
            file_resp.raise_for_status()
        except Exception as exc:
            return f"定值单文件下载失败：{exc}"

        content_type = file_resp.headers.get("content-type", "")
        content = file_resp.content

        if not content or len(content) < 100:
            return f"定值单文件内容为空或过小（{len(content)} bytes），可能链接无效。\n下载地址：{download_url}"

        # 确定文件扩展名
        if "pdf" in content_type or download_url.endswith(".pdf"):
            ext = ".pdf"
        elif "excel" in content_type or "spreadsheet" in content_type:
            ext = ".xlsx"
        else:
            ext = ".pdf"

        # 5. 解析定值单 PDF
        file_name = f"{actual_name}_定值单{ext}"
        return await self._parse_pdf_content(
            content, file_name, actual_name, station,
            self._source_label(setting_type),
        )

    async def _parse_pdf_content(
        self, content: bytes, file_name: str, device_name: str, station: str, source_label: str,
    ) -> str:
        """下载定值单 PDF 后提取文本，返回给 agent 按 schema 解析。"""
        if not content or len(content) < 100:
            return ""
        try:
            # 0. 确保 setting-parser 模块可导入
            import sys
            skill_dir = self._resolve_skill_dir()
            if skill_dir not in sys.path:
                sys.path.insert(0, skill_dir)

            # 1. PDF 文本提取（在线程池中运行，避免阻塞）
            logger.info("[setting_parse_device] 开始提取PDF文本: {} ({} bytes)", file_name, len(content))
            extracted = await asyncio.to_thread(self._extract_pdf, content, file_name, skill_dir)
            if not extracted or not extracted.markdown.strip():
                logger.warning("[setting_parse_device] PDF文本提取结果为空")
                return (
                    f"定值单PDF已获取（{file_name}, {len(content)} bytes），但文本提取结果为空。"
                )
            logger.info("[setting_parse_device] PDF文本提取完成: {} chars", len(extracted.markdown))

            # 2. 返回文本 + schema，让 agent 按固定格式解析
            from setting_parser.output_schema import PARSER_INSTRUCTION

            text = extracted.markdown
            if len(text) > 12000:
                text = text[:12000] + "\n... (内容过长，已截断)"

            return (
                f"=== 定值单已获取 ===\n"
                f"设备: {device_name}（{station}）\n"
                f"来源: {source_label}\n"
                f"文件: {file_name}（{len(content)} bytes）\n\n"
                f"{PARSER_INSTRUCTION}\n\n"
                f"--- 定值单原文 ---\n\n"
                f"{text}"
            )
        except Exception as exc:
            logger.warning("[setting_parse_device] PDF 文本提取异常: {}", exc)
            return f"定值单PDF文本提取异常：{exc}"

    @staticmethod
    def _extract_pdf(content: bytes, file_name: str, skill_dir: str):
        """同步提取 PDF 文本，供 asyncio.to_thread 调用。"""
        import sys
        if skill_dir not in sys.path:
            sys.path.insert(0, skill_dir)
        with tempfile.TemporaryDirectory(prefix="setting_parse_") as tmpdir:
            file_path = Path(tmpdir) / file_name
            file_path.write_bytes(content)
            from setting_parser.extractors.pdf import extract_pdf_markdown
            return extract_pdf_markdown(str(file_path), use_ocr=True)

    @staticmethod
    def _resolve_skill_dir() -> str:
        """查找 setting-parser skill 目录。"""
        import os
        candidates = [
            Path(os.environ.get("NANOBOT_SKILLS_DIR", "")) / "setting-parser" if os.environ.get("NANOBOT_SKILLS_DIR") else None,
            Path(__file__).parent.parent.parent.parent / "skills" / "setting-parser",
            Path.home() / ".nanobot" / "skills" / "setting-parser",
            Path.cwd() / "skills" / "setting-parser",
        ]
        for d in candidates:
            if d and d.is_dir():
                return str(d)
        return str(candidates[1])  # fallback

    async def _search_device(
        self, client: httpx.AsyncClient, device_name: str, st_name: str,
    ) -> list[dict]:
        """搜索设备，自动尝试多种名称格式。"""
        # 构造候选搜索名：原名、去空格、厂站+设备
        candidates = [device_name]
        no_space = device_name.replace(" ", "")
        if no_space != device_name:
            candidates.append(no_space)
        # 如果有厂站名，尝试 "厂站+设备" 格式
        if st_name:
            prefixed = f"{st_name}{no_space}"
            if prefixed not in candidates:
                candidates.append(prefixed)

        for name in candidates:
            search_body: dict[str, Any] = {"onceDeviceName": name, "limit": 10, "page": 1}
            if st_name:
                search_body["stName"] = st_name
            try:
                resp = await client.post(f"{LEDGER_API}/getPageList", json=search_body)
                resp.raise_for_status()
                data = resp.json().get("data", {})
                records = data.get("records") or data.get("list") or []
                if records:
                    logger.info("[setting_parse_device] 搜索 '{}'", name)
                    return records
            except Exception as exc:
                logger.warning("[setting_parse_device] 搜索 '{}' 失败: {}", name, exc)

        # 所有候选都未找到，尝试不限厂站名
        if st_name:
            for name in candidates[:2]:
                search_body = {"onceDeviceName": name, "limit": 10, "page": 1}
                try:
                    resp = await client.post(f"{LEDGER_API}/getPageList", json=search_body)
                    resp.raise_for_status()
                    data = resp.json().get("data", {})
                    records = data.get("records") or data.get("list") or []
                    if records:
                        logger.info("[setting_parse_device] 搜索 '{}' (不限厂站)", name)
                        return records
                except Exception:
                    pass

        return []

    @staticmethod
    def _source_label(setting_type: str) -> str:
        return {"0": "定值系统", "1": "华东定值单", "2": "OMS定值单"}.get(setting_type, "未知")

