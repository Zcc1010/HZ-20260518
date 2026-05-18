#!/usr/bin/env python3
"""Run a G file compare job from an Agent Playground app workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from compare_g_files import build_result, render_html_report


def _resolve_job_root(app_root: Path, job_id: str) -> Path:
    root = app_root.expanduser().resolve()
    job_root = (root / "jobs" / job_id).resolve()
    try:
        job_root.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"job root is outside app root: {job_root}") from exc
    return job_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Agent Playground G file compare job.")
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--coord-tolerance", type=float, default=0.001)
    return parser.parse_args()


def _resolve_input(job_root: Path, manifest: dict[str, object], key: str) -> tuple[str, Path]:
    item = manifest.get(key)
    if not isinstance(item, dict):
        raise FileNotFoundError(f"missing {key} input metadata in inputs.json")

    relative_path = item.get("relative_path")
    file_name = item.get("file_name")
    if not isinstance(relative_path, str) or not relative_path:
        raise FileNotFoundError(f"missing {key} relative_path in inputs.json")

    input_path = (job_root / relative_path).resolve()
    try:
        input_path.relative_to(job_root)
    except ValueError as exc:
        raise PermissionError(f"{key} input is outside job root: {input_path}") from exc
    if not input_path.is_file():
        raise FileNotFoundError(f"missing {key} input: {input_path}")

    display_name = file_name if isinstance(file_name, str) and file_name else input_path.name
    return display_name, input_path


def main() -> int:
    args = parse_args()
    job_root = _resolve_job_root(args.app_root, args.job_id)
    manifest_path = job_root / "inputs.json"
    report_path = job_root / "report.html"
    result_path = job_root / "result.json"

    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing inputs manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    d5000_name, d5000_path = _resolve_input(job_root, manifest, "d5000")
    xyd_name, xyd_path = _resolve_input(job_root, manifest, "new_gen")

    result = build_result(d5000_path, xyd_path, args.coord_tolerance)
    result["job_id"] = args.job_id
    result["metadata"]["d5000_file"] = d5000_name
    result["metadata"]["xyd_file"] = xyd_name
    report_path.write_text(render_html_report(result), encoding="utf-8")
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(report_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
