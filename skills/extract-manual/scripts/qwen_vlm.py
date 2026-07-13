#!/usr/bin/env python3
"""
用 Qwen3.6-VL-Plus (阿里云百炼) 批量识别图片。
从 Markdown 文件中提取图片引用，提取上下文，逐一调用 VLM 获取描述。
结果存为 .vlm_cache.json，可用 vlm_replace.py 替换回 md。

用法:
    python qwen_vlm.py <input.md> <images_dir> [-o output.md] [--cache cache.json]
"""

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path

import requests

API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
API_KEY = "sk-0624027854264cb79b4270a146a416f5"
MODEL = "qwen3.6-plus"

PROMPT_TEMPLATE = """以下是继电保护装置说明书中"{section}"章节的图片。图片前后文字上下文：

前文：
{before}

后文：
{after}

请直接描述图片内容，不要添加开场白或总结。要求：
- 逻辑框图：逐个列出每个逻辑门编号(G1/G2...)的门类型（与门/或门）、每个输入信号名称、输出信号名称。按功能模块分组描述。
- 阻抗特性图/曲线图：说明坐标轴、动作区定义（圆内/外为动作区）、方向性含义、关键参数点
- 表格：完整还原表格行列内容
- 接线图/原理图：描述结构、元件、连接关系
- 外观图：描述布局、指示灯、按键位置
表达完整即可，不要冗长。每张描述控制在500-1000字。"""


def extract_images_with_context(md_text, context_lines=10):
    lines = md_text.split('\n')
    results = []
    for i, line in enumerate(lines):
        m = re.match(r'!\[([^\]]*)\]\((images/([^)]+))\)', line)
        if m:
            alt, img_rel, img_name = m.group(1), m.group(2), m.group(3)
            before = '\n'.join(lines[max(0, i - context_lines):i])
            after = '\n'.join(lines[i + 1:min(len(lines), i + 1 + context_lines)])
            results.append((img_name, img_rel, before, after))
    return results


def describe_image(image_path, prompt):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    ext = Path(image_path).suffix.lstrip(".")
    mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}
    mime = f"image/{mime_map.get(ext, 'jpeg')}"

    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": prompt}
            ]}],
            "max_tokens": 4096
        },
        timeout=300
    )

    if resp.status_code != 200:
        return f"[VLM ERROR {resp.status_code}]: {resp.text[:200]}"
    return resp.json()["choices"][0]["message"]["content"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_md", help="输入 Markdown 文件")
    parser.add_argument("images_dir", help="图片目录")
    parser.add_argument("-o", "--output", default=None, help="输出文件")
    parser.add_argument("--cache", default=None, help="缓存 JSON 路径")
    parser.add_argument("--section", default="保护原理", help="章节名（用于 prompt）")
    parser.add_argument("--max-retry", type=int, default=2, help="最大重试次数")
    args = parser.parse_args()

    md_path = Path(args.input_md)
    img_dir = Path(args.images_dir)
    out_path = Path(args.output) if args.output else None
    cache_path = Path(args.cache) if args.cache else md_path.parent / ".vlm_cache.json"

    md_text = md_path.read_text(encoding="utf-8")
    images = extract_images_with_context(md_text)

    if not images:
        print("未找到图片引用")
        return

    print(f"找到 {len(images)} 张图片")

    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            print(f"加载缓存: {len(cache)} 条")
        except json.JSONDecodeError:
            print("缓存 JSON 损坏，重新开始")
            cache = {}

    for i, (img_name, img_rel, before, after) in enumerate(images):
        img_file = img_dir / img_name
        if not img_file.exists():
            img_file = md_path.parent / img_rel
        if not img_file.exists():
            print(f"  [{i+1}/{len(images)}] 图片不存在: {img_rel}")
            continue

        if img_name in cache:
            print(f"  [{i+1}/{len(images)}] 缓存命中: {img_name}")
            continue

        prompt = PROMPT_TEMPLATE.format(
            section=args.section,
            before=before[:500],
            after=after[:500]
        )

        desc = None
        for attempt in range(args.max_retry):
            try:
                print(f"  [{i+1}/{len(images)}] 识别中: {img_name} ...", end="", flush=True)
                t0 = time.time()
                desc = describe_image(str(img_file), prompt)
                elapsed = time.time() - t0
                print(f" {elapsed:.1f}s ({len(desc)} 字)")
                break
            except Exception as e:
                print(f" 失败(第{attempt+1}次): {e}")
                time.sleep(2)

        if desc and not desc.startswith("[VLM ERROR"):
            cache[img_name] = desc
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        elif desc:
            print(f"  跳过(错误): {desc[:100]}")

    # 替换回 md
    if out_path:
        def replace_img(match):
            img_rel = match.group(2)
            img_name = Path(img_rel).name
            if img_name in cache:
                return (
                    f"![]({img_rel})\n\n"
                    f"> **图片描述：**\n"
                    + "\n".join(f"> {line}" for line in cache[img_name].split('\n'))
                )
            return match.group(0)

        result = re.sub(r'!\[([^\]]*)\]\((images/[^)]+)\)', replace_img, md_text)
        out_path.write_text(result, encoding="utf-8")
        replaced = sum(1 for _, _, _, _ in images if _ in cache)
        print(f"\n输出: {out_path} ({replaced} 张图片已替换, {len(result)} 字符)")


if __name__ == "__main__":
    main()
