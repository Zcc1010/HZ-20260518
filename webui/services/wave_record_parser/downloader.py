# -*- coding: utf-8 -*-
"""通过故障事件ID下载录波文件。

从 download_wave_files.py 提取核心逻辑，只保留单事件下载功能。
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

BASE_URL = "http://10.34.38.113:8020"
EVENT_DETAIL_URL = f"{BASE_URL}/fault/event/getDetails"
WAVE_DOWNLOAD_URL = "http://10.34.38.122:18162/download/wave/v1/getRecorderFile"
GZFILE_DOWNLOAD_URL = "http://10.138.4.27:8201/fault/fault.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Content-Type": "application/json",
}


def _sanitize_filename(name: str) -> str:
    """去除文件夹名称中的非法字符。"""
    forbidden = r'<>:"/\|?*'
    for ch in forbidden:
        name = name.replace(ch, "_")
    name = name.strip().rstrip(".")
    return name if name else "unknown"


class EventDownloader:
    """通过故障事件ID下载录波文件。"""

    def __init__(self, cookie: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        if cookie:
            for item in cookie.split("; "):
                if "=" in item:
                    k, v = item.split("=", 1)
                    self.session.cookies.set(k, v)

    def fetch_event_detail(self, event_id: str) -> Optional[dict[str, Any]]:
        """获取单个事件详情。"""
        url = f"{EVENT_DETAIL_URL}/{event_id}"
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"获取事件详情失败 (id={event_id}): {e}")

        if isinstance(data, dict) and "data" in data:
            inner = data["data"]
        else:
            inner = data
        return inner

    def download_protection_wave(self, absolute_path: str, short_name: str, save_dir: str) -> bool:
        """下载保护录波文件 (base64->ZWAV)。"""
        save_path = os.path.join(save_dir, f"{short_name}.ZWAV")
        if os.path.exists(save_path):
            return True

        url = f"{WAVE_DOWNLOAD_URL}?fileName={quote(absolute_path, safe='')}"
        try:
            resp = self.session.get(url, timeout=60)
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            print(f"    [ERROR] 请求失败: {short_name}.ZWAV - {e}", flush=True)
            return False

        inner = result.get("data", result)
        if isinstance(inner, dict):
            b64_str = inner.get("data", inner)
        else:
            b64_str = inner

        if not b64_str or not isinstance(b64_str, str):
            print(f"    [WARN] 无数据: {short_name}.ZWAV", flush=True)
            return False

        try:
            file_bytes = base64.b64decode(b64_str)
            with open(save_path, "wb") as f:
                f.write(file_bytes)
            return True
        except Exception as e:
            print(f"    [ERROR] 解码失败: {short_name}.ZWAV - {e}", flush=True)
            return False

    def download_gz_wave(self, filepath: str, filename: str, save_dir: str) -> bool:
        """下载故障录波器录波文件 (直链下载)。"""
        save_path = os.path.join(save_dir, filename)
        if os.path.exists(save_path):
            return True

        url = f"{GZFILE_DOWNLOAD_URL}?fileName={quote(filepath, safe='')}"
        try:
            resp = self.session.get(url, timeout=120, stream=True)
            resp.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"    [ERROR] 下载失败: {filename} - {e}", flush=True)
            return False

    def write_info_md(self, event: dict[str, Any], save_dir: str) -> None:
        """生成 _故障事件信息.md。"""
        md_path = os.path.join(save_dir, "_故障事件信息.md")
        lines = [
            "# 故障事件信息",
            "",
            "| 字段 | 值 |",
            "|------|----|",
        ]
        skip_keys = {"actions", "fxCount", "fxzsyhwtCount", "pushState"}
        for key, value in event.items():
            if key in skip_keys:
                continue
            if value is None:
                value = ""
            lines.append(f"| {key} | {value} |")

        lines.append("")
        lines.append(f"> 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def download_event(self, event_id: str, output_dir: str) -> str:
        """下载单个故障事件的所有录波文件。

        Args:
            event_id: 故障事件ID
            output_dir: 输出目录

        Returns:
            下载文件所在目录的路径
        """
        # 获取事件详情
        detail = self.fetch_event_detail(event_id)
        if detail is None:
            raise RuntimeError(f"无法获取事件详情: {event_id}")

        # 从详情中提取事件信息（用于生成 md）
        event_info = detail if isinstance(detail, dict) else {}

        # 确定目录名
        equipment_name = _sanitize_filename(
            event_info.get("equipmentName", "") or f"event_{event_id}"
        )
        save_dir = os.path.join(output_dir, equipment_name)
        os.makedirs(save_dir, exist_ok=True)

        # ---- 下载保护录波 (ZWAV) ----
        protection_dir = os.path.join(save_dir, "保护录波")
        wave_list: list[dict] = detail.get("list") or detail.get("data", {}).get("list") or []
        sequences = detail.get("data", {}).get("sequences", [])
        seq_waves: list[dict] = []
        for seq in sequences:
            for _st_name, equipments in seq.items():
                for equip in equipments:
                    for w in equip.get("waves", []):
                        seq_waves.append(w)

        # 合并去重
        seen: set[str] = set()
        merged_waves: list[dict] = []
        for w in wave_list + seq_waves:
            sn = w.get("shortName", "")
            if sn and sn not in seen:
                seen.add(sn)
                merged_waves.append(w)

        if merged_waves:
            os.makedirs(protection_dir, exist_ok=True)
            for w in merged_waves:
                ap = w.get("absolutePath", "")
                sn = w.get("shortName", "")
                if ap and sn:
                    self.download_protection_wave(ap, sn, protection_dir)

        # ---- 下载故障录波器录波 ----
        fault_dir = os.path.join(save_dir, "故障录波")
        fault_list: list[dict] = detail.get("faultList") or []
        if fault_list:
            os.makedirs(fault_dir, exist_ok=True)
            for item in fault_list:
                fp = item.get("filepath", "")
                oss_info = item.get("ossFileInfo", {})
                fname = oss_info.get("fileName", "")
                if not fname:
                    fname = fp.rsplit("/", 1)[-1] if fp else "unknown"
                if fp:
                    self.download_gz_wave(fp, fname, fault_dir)

        # 写入信息 MD
        self.write_info_md(event_info, save_dir)

        return save_dir
