#!/usr/bin/env python3
"""Tee stdin to stdout and rotate output file by local date."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import sys
from typing import TextIO


def dated_path(target: pathlib.Path, day: dt.date) -> pathlib.Path:
    suffix = target.suffix
    stem = target.stem if suffix else target.name
    filename = f"{stem}-{day.isoformat()}{suffix or '.log'}"
    return target.with_name(filename)


def open_log(path: pathlib.Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    args = parser.parse_args()

    target = pathlib.Path(os.path.expanduser(args.target))
    current_day = dt.datetime.now().date()
    current_path = dated_path(target, current_day)
    handle = open_log(current_path)

    try:
        for line in sys.stdin:
            now_day = dt.datetime.now().date()
            if now_day != current_day:
                handle.close()
                current_day = now_day
                current_path = dated_path(target, current_day)
                handle = open_log(current_path)

            sys.stdout.write(line)
            sys.stdout.flush()
            handle.write(line)
            handle.flush()
    finally:
        handle.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
