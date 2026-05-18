from __future__ import annotations

import datetime as dt
import os
from collections import deque
from pathlib import Path


def get_log_base_path(default_dir: Path) -> Path:
    """Return the configured base log path, falling back to <dir>/webui.log."""
    configured = os.environ.get("WEBUI_LOG_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return default_dir / "webui.log"


def dated_log_path(base_path: Path, day: dt.date | None = None) -> Path:
    day = day or dt.datetime.now().date()
    suffix = base_path.suffix or ".log"
    stem = base_path.stem if base_path.suffix else base_path.name
    return base_path.with_name(f"{stem}-{day.isoformat()}{suffix}")


def iter_existing_log_paths(base_path: Path, lookback_days: int = 7) -> list[Path]:
    """Return existing log files from oldest to newest."""
    paths: list[Path] = []
    today = dt.datetime.now().date()
    for offset in range(lookback_days - 1, -1, -1):
        candidate = dated_log_path(base_path, today - dt.timedelta(days=offset))
        if candidate.exists():
            paths.append(candidate)
    if base_path.exists() and base_path not in paths:
        paths.append(base_path)
    return paths


def latest_log_path(base_path: Path, lookback_days: int = 7) -> Path:
    existing = iter_existing_log_paths(base_path, lookback_days=lookback_days)
    if existing:
        return existing[-1]
    return dated_log_path(base_path)


def read_recent_log_lines(
    base_path: Path,
    *,
    lines: int = 500,
    keyword: str = "",
    lookback_days: int = 7,
) -> tuple[str, Path]:
    """Read recent log lines across the newest available rotated files."""
    log_paths = iter_existing_log_paths(base_path, lookback_days=lookback_days)
    if not log_paths:
        return "", latest_log_path(base_path, lookback_days=lookback_days)

    last_lines: deque[str] = deque(maxlen=lines)
    for path in log_paths:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            if keyword:
                for line in fh:
                    if keyword in line:
                        last_lines.append(line)
            else:
                for line in fh:
                    last_lines.append(line)

    return "".join(last_lines), log_paths[-1]
