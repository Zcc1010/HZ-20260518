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
    """根据 settingValueType 构造定值单下载链接。"""
    import base64
    from urllib.parse import encodeURIComponent

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
            "从二次设备台账自动下载定值单并解析。"
            "输入设备名称（如'安庆变5789线'），自动完成：查询台账→下载定值单PDF→AI解析→返回结构化JSON。\n"
            "参数：deviceName(设备名,必填), stName(厂站名,可选用于精确匹配)。\n"
            "当用户要求分析/解析某个设备的定值单时调用此工具。"
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
            return await self._download_and_parse(device_name, st_name)
        except Exception as exc:
            logger.error("setting_parse_device failed: {}", exc)
            return f"定值单解析失败：{exc}"

    async def _download_and_parse(self, device_name: str, st_name: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            # 1. 搜索设备
            search_body: dict[str, Any] = {"onceDeviceName": device_name, "limit": 10, "page": 1}
            if st_name:
                search_body["stName"] = st_name

            resp = await client.post(f"{LEDGER_API}/getPageList", json=search_body)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            records = data.get("records") or data.get("list") or []

            if not records:
                return f"未找到设备：{device_name}。请检查设备名称是否正确。"

            # 取第一个匹配设备
            device = records[0]
            unique_code = device.get("uniqueCode", "")
            actual_name = device.get("onceDeviceName", device_name)
            station = device.get("stName", "")

            if not unique_code:
                return f"设备 {actual_name} 缺少 uniqueCode，无法查询定值单。"

            # 2. 获取定值单详情
            detail_resp = await client.get(f"{LEDGER_API}/getDzDetailByUniqueCode/{unique_code}")
            detail_resp.raise_for_status()
            detail_data = detail_resp.json().get("data", {})

            detail_list = detail_data.get("dingZhiDetail", []) if isinstance(detail_data, dict) else []
            equipment = detail_list[0] if detail_list else (detail_data if isinstance(detail_data, dict) else {})

            pdf_file = detail_data.get("pdfFileName", "") or ""
            setting_code = equipment.get("settingValueCode", "") or ""
            setting_type = str(equipment.get("settingValueType", "") or "")

            # 3. 构造下载 URL
            download_url = _build_setting_pdf_url(pdf_file, setting_code, setting_type)
            if not download_url:
                return (
                    f"设备 {actual_name}（{station}）无法构造定值单下载链接。\n"
                    f"pdfFileName={pdf_file}, settingValueCode={setting_code}, settingValueType={setting_type}\n"
                    "请手动下载定值单文件后上传解析。"
                )

            # 4. 下载文件
            logger.info("Downloading setting sheet from: {}", download_url)
            try:
                file_resp = await client.get(download_url, follow_redirects=True)
                file_resp.raise_for_status()
            except Exception as exc:
                return f"定值单文件下载失败：{exc}\n下载地址：{download_url}\n请手动下载后上传解析。"

            content_type = file_resp.headers.get("content-type", "")
            content = file_resp.content

            if not content or len(content) < 100:
                return f"定值单文件内容为空或过小（{len(content)} bytes），可能链接无效。\n下载地址：{download_url}"

            # 确定文件扩展名
            if "pdf" in content_type or download_url.endswith(".pdf"):
                ext = ".pdf"
            elif "html" in content_type or download_url.endswith("2html") or b"<html" in content[:500].lower():
                ext = ".html"
            elif "excel" in content_type or "spreadsheet" in content_type:
                ext = ".xlsx"
            else:
                ext = ".pdf"  # 默认

            # 5. 保存到临时目录并运行解析
            with tempfile.TemporaryDirectory(prefix="setting_parse_") as tmpdir:
                tmp_path = Path(tmpdir)
                file_name = f"{actual_name}_定值单{ext}"
                file_path = tmp_path / file_name
                file_path.write_bytes(content)

                output_dir = tmp_path / "output"
                output_dir.mkdir()

                # 运行 setting-parser
                skill_dir = self._resolve_skill_dir()
                cmd = [
                    "python", "-m", "setting_parser.cli", "parse",
                    str(file_path),
                    "--output-dir", str(output_dir),
                ]

                proc = await asyncio.to_thread(
                    _run_subprocess, cmd, 600, str(skill_dir)
                )

                if proc.returncode != 0:
                    return (
                        f"定值单文件已下载（{file_name}, {len(content)} bytes），但解析失败。\n"
                        f"错误：{proc.stderr or proc.stdout}\n"
                        f"请手动上传文件进行解析。"
                    )

                # 读取解析结果
                json_files = list(output_dir.rglob("*.json"))
                if not json_files:
                    return "解析完成但未生成结果文件。"

                results = []
                for jf in json_files:
                    try:
                        import json
                        with open(jf, "r", encoding="utf-8") as f:
                            results.append(json.load(f))
                    except Exception:
                        results.append(jf.read_text(encoding="utf-8"))

                import json
                if len(results) == 1:
                    result_text = json.dumps(results[0], ensure_ascii=False, indent=2)
                else:
                    result_text = json.dumps(results, ensure_ascii=False, indent=2)

                # 截断过长的结果
                if len(result_text) > 8000:
                    result_text = result_text[:8000] + "\n... (结果过长，已截断)"

                return (
                    f"=== 定值单解析完成 ===\n"
                    f"设备: {actual_name}（{station}）\n"
                    f"文件: {file_name}（{len(content)} bytes）\n"
                    f"来源: {self._source_label(setting_type)}\n\n"
                    f"{result_text}"
                )

    @staticmethod
    def _source_label(setting_type: str) -> str:
        return {"0": "定值系统", "1": "华东定值单", "2": "OMS定值单"}.get(setting_type, "未知")

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


def _run_subprocess(cmd: list[str], timeout: int = 600, cwd: str | None = None):
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
