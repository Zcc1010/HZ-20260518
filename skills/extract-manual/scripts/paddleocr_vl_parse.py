#!/usr/bin/env python3
"""PaddleOCR-VL-1.5 云端文档解析，输出合并的 Markdown + 图片到指定目录。"""

import json
import os
import sys
import time
import requests

JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
TOKEN = "0aa00367237db9d9073384b62c96be680f61ff74"
MODEL = "PaddleOCR-VL-1.5"

def parse_file(file_path, output_dir):
    headers = {"Authorization": f"bearer {TOKEN}"}
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    print(f"Processing: {file_path}")

    if file_path.startswith("http"):
        headers["Content-Type"] = "application/json"
        payload = {"fileUrl": file_path, "model": MODEL, "optionalPayload": optional_payload}
        job_response = requests.post(JOB_URL, json=payload, headers=headers)
    else:
        data = {"model": MODEL, "optionalPayload": json.dumps(optional_payload)}
        with open(file_path, "rb") as f:
            files = {"file": f}
            job_response = requests.post(JOB_URL, headers=headers, data=data, files=files)

    assert job_response.status_code == 200, f"Submit failed: {job_response.text}"
    job_id = job_response.json()["data"]["jobId"]
    print(f"Job submitted: {job_id}")

    while True:
        resp = requests.get(f"{JOB_URL}/{job_id}", headers=headers)
        assert resp.status_code == 200
        state = resp.json()["data"]["state"]
        if state == "done":
            print(f"Done, pages: {resp.json()['data']['extractProgress']['extractedPages']}")
            jsonl_url = resp.json()["data"]["resultUrl"]["jsonUrl"]
            break
        elif state == "failed":
            print(f"Failed: {resp.json()['data']['errorMsg']}")
            sys.exit(1)
        else:
            try:
                p = resp.json()['data']['extractProgress']
                print(f"  {state}: {p.get('extractedPages','?')}/{p.get('totalPages','?')}")
            except KeyError:
                print(f"  {state}...")
        time.sleep(5)

    # Download and save results
    os.makedirs(output_dir, exist_ok=True)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    jsonl_resp = requests.get(jsonl_url)
    jsonl_resp.raise_for_status()
    lines = jsonl_resp.text.strip().split('\n')

    all_md = []
    img_counter = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        result = json.loads(line)["result"]
        for res in result["layoutParsingResults"]:
            md_text = res["markdown"]["text"]

            # Download images and fix references
            for img_path, img_url in res["markdown"].get("images", {}).items():
                img_bytes = requests.get(img_url).content
                img_name = f"img_{img_counter:04d}.jpg"
                img_local = os.path.join(images_dir, img_name)
                with open(img_local, "wb") as f:
                    f.write(img_bytes)
                md_text = md_text.replace(f"({img_path})", f"(images/{img_name})")
                img_counter += 1

            all_md.append(md_text)

    # Save merged markdown
    merged = "\n\n".join(all_md)
    out_path = os.path.join(output_dir, "paddleocr_vl.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(merged)
    print(f"Saved: {out_path} ({len(merged)} chars, {img_counter} images)")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python paddleocr_vl_parse.py <pdf_path> <output_dir>")
        sys.exit(1)
    parse_file(sys.argv[1], sys.argv[2])
