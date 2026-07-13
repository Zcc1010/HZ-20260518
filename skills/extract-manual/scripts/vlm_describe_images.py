#!/usr/bin/env python3
"""
用 MiniMax VLM API (understand_image 兼容接口) 批量识别图片。
从 Markdown 文件中提取图片引用，逐一调用 VLM 获取描述，
然后将图片替换为文字描述，输出 enriched markdown。

用法:
    python vlm_describe_images.py <input.md> <images_dir> -o <output.md>
"""

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

API_HOST = os.environ.get("MINIMAX_API_HOST", "https://api.minimaxi.com")
API_KEY = os.environ.get(
    "MINIMAX_API_KEY",
    "sk-cp-1BtMqYI118P7K_7gFMsgfkcCcyzU-_TfB6JqU2RZ42HcrZruBEdKO5oUCLqWkpAGrINIFUPPX68VVm2cetuLKsaLFrvLYxgcFlesnKjke6TdwQ1WMN9PXWI",
)

PROMPT_TEMPLATE = """你是一名电力系统继电保护专家。请详细描述这张图片的内容。

这是一个继电保护装置说明书中的图片。请按以下要求描述：
1. 如果是**逻辑框图/保护逻辑图**：请逐步描述逻辑流程，包括每个逻辑门（与门、或门、非门、延时元件等）的功能、输入输出信号名称、动作条件、时间参数等。用文字形式还原逻辑关系。
2. 如果是**接线图/端子图**：请描述接线方式、端子编号、连接关系。
3. 如果是**原理图/电路图**：请描述电路结构、元件参数、工作原理。
4. 如果是**外观图/面板图**：请描述设备外观、面板布局、指示灯/按键位置。
5. 如果是**表格截图**：请完整还原表格内容。
6. 如果是**框图/系统图**：请描述系统组成、各模块功能和连接关系。

请用中文回答，尽可能详细和准确。"""

def extract_images(md_text):
    """提取 markdown 中的图片引用，返回 [(full_match, image_path), ...]"""
    pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
    return re.findall(pattern, md_text)


def describe_image(image_path, prompt):
    """调用 MiniMax VLM API 识别单张图片"""
    abs_path = str(Path(image_path).resolve())

    with open(abs_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode("ascii")

    ext = Path(image_path).suffix.lstrip(".")
    mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}
    mime = f"image/{mime_map.get(ext, 'jpeg')}"

    url = f"{API_HOST}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "MiniMax-VL-01",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_data}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 4096,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        return f"[VLM ERROR {resp.status_code}]: {resp.text[:200]}"
    return resp.json()["choices"][0]["message"]["content"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_md", help="输入 Markdown 文件")
    parser.add_argument("images_dir", help="图片目录")
    parser.add_argument("-o", "--output", help="输出文件（默认覆盖输入）")
    parser.add_argument("--cache", default=None, help="缓存 JSON 文件路径")
    parser.add_argument("--prompt", default=None, help="自定义 prompt")
    args = parser.parse_args()

    md_path = Path(args.input_md)
    img_dir = Path(args.images_dir)
    out_path = Path(args.output) if args.output else md_path
    cache_path = Path(args.cache) if args.cache else md_path.parent / ".vlm_cache.json"

    prompt = args.prompt or PROMPT_TEMPLATE

    md_text = md_path.read_text(encoding="utf-8")
    images = extract_images(md_text)

    if not images:
        print("未找到图片引用")
        return

    print(f"找到 {len(images)} 张图片")

    # 加载缓存
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"加载缓存: {len(cache)} 条")

    # 逐张识别
    for i, (alt_text, img_rel) in enumerate(images):
        img_file = img_dir / Path(img_rel).name
        if not img_file.exists():
            # 尝试相对于 md 文件的位置
            img_file = md_path.parent / img_rel

        if not img_file.exists():
            print(f"  [{i+1}/{len(images)}] 图片不存在: {img_rel}")
            continue

        img_key = str(img_file.name)
        if img_key in cache:
            print(f"  [{i+1}/{len(images)}] 缓存命中: {img_key}")
            continue

        print(f"  [{i+1}/{len(images)}] 识别中: {img_key} ...", end="", flush=True)
        t0 = time.time()
        desc = describe_image(str(img_file), prompt)
        elapsed = time.time() - t0
        print(f" {elapsed:.1f}s ({len(desc)} 字)")

        cache[img_key] = desc
        # 每张都保存缓存
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    # 替换图片为描述
    def replace_img(match):
        alt = match.group(1)
        path = match.group(2)
        img_file = img_dir / Path(path).name
        if not img_file.exists():
            img_file = md_path.parent / path
        img_key = str(img_file.name)
        if img_key in cache:
            desc = cache[img_key]
            return f"<details>\n<summary>原图: {alt or path}</summary>\n\n![{alt}]({path})\n\n</details>\n\n**图片描述：**\n\n{desc}"
        return match.group(0)

    result = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_img, md_text)
    out_path.write_text(result, encoding="utf-8")
    print(f"\n输出: {out_path} ({len(result)} 字符)")


if __name__ == "__main__":
    main()
