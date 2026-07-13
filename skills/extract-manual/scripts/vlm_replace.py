#!/usr/bin/env python3
"""
从 .vlm_cache.json 读取 VLM 描述，替换 md 文件中的图片引用。
用法:
    python vlm_replace.py <input.md> <cache.json> <images_dir> [-o output.md]
"""

import argparse
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_md")
    parser.add_argument("cache_json")
    parser.add_argument("images_dir")
    parser.add_argument("-o", "--output", default=None)
    args = parser.parse_args()

    md_path = Path(args.input_md)
    cache = json.loads(Path(args.cache_json).read_text(encoding="utf-8"))
    img_dir = Path(args.images_dir)
    out_path = Path(args.output) if args.output else md_path.parent / (md_path.stem + "_vlm.md")

    md_text = md_path.read_text(encoding="utf-8")
    count = 0

    def replace_img(match):
        nonlocal count
        img_rel = match.group(2)
        img_name = Path(img_rel).name
        if img_name in cache:
            count += 1
            desc = cache[img_name]
            return (
                f"<details>\n<summary>图片: {img_name}</summary>\n\n"
                f"![]({img_rel})\n\n</details>\n\n"
                f"**图片描述：**\n\n{desc}"
            )
        return match.group(0)

    result = re.sub(r"!\[([^\]]*)\]\((images/[^)]+)\)", replace_img, md_text)
    out_path.write_text(result, encoding="utf-8")
    print(f"{md_path.name} -> {out_path.name} ({count} 张图片已替换, {len(result)} 字符)")


if __name__ == "__main__":
    main()
