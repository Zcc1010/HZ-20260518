"""Copy an existing trip briefing job to workspace for AI access.

Usage:
    python scripts/copy_briefing_to_workspace.py              # copy the latest job
    python scripts/copy_briefing_to_workspace.py <job_id>     # copy a specific job
    python scripts/copy_briefing_to_workspace.py --list        # list all completed jobs
"""

import json
import shutil
import sys
import time
from pathlib import Path


def find_app_root() -> Path:
    app_root = Path.home() / ".nanobot" / "agentplayground" / "wave-record-parser"
    if app_root.exists():
        return app_root
    raise FileNotFoundError(f"wave-record-parser directory not found: {app_root}")


def list_completed_jobs(app_root: Path) -> list[tuple[str, str, str]]:
    """Return list of (job_id, zip_name, created_at) for completed jobs."""
    jobs_dir = app_root / "jobs"
    results = []
    for job_dir in sorted(jobs_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        briefing = job_dir / "output" / "跳闸简报.md"
        if not briefing.exists():
            continue
        # Read manifest for zip name
        manifest = job_dir / "inputs.json"
        zip_name = ""
        created_at = ""
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            files = data.get("files", [])
            if files:
                zip_name = files[0].get("filename", "")
            created_at = data.get("created_at", "")
        results.append((job_dir.name, zip_name, created_at))
    return results


def copy_comtrade_files(src_dir: Path, dest_dir: Path) -> int:
    """Recursively copy COMTRADE-related files. Returns count of files copied."""
    COMTRADE_EXTS = {".cfg", ".dat", ".hdr", ".inf", ".rms.csv", ".events.csv"}
    count = 0
    for f in src_dir.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        is_comtrade = ext in COMTRADE_EXTS or f.name.lower().endswith((".rms.csv", ".events.csv"))
        if not is_comtrade:
            continue
        rel = f.relative_to(src_dir)
        dest_f = dest_dir / rel
        dest_f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(f), str(dest_f))
        count += 1
    return count


def copy_job_to_workspace(app_root: Path, job_id: str) -> None:
    job_root = app_root / "jobs" / job_id
    if not job_root.exists():
        print(f"Error: job not found: {job_id}")
        sys.exit(1)

    briefing_src = job_root / "output" / "跳闸简报.md"
    if not briefing_src.exists():
        print(f"Error: briefing not found for job {job_id}")
        sys.exit(1)

    workspace_dir = app_root.parent.parent / "workspace"
    if not workspace_dir.exists():
        print(f"Error: workspace not found: {workspace_dir}")
        sys.exit(1)

    dest = workspace_dir / "跳闸简报"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    # Copy briefing
    shutil.copy2(str(briefing_src), str(dest / "跳闸简报.md"))
    print(f"  [OK] 跳闸简报.md")

    # Copy paragraphs
    para_src = job_root / "output" / "段落"
    if para_src.is_dir():
        shutil.copytree(str(para_src), str(dest / "段落"))
        para_count = len(list((dest / "段落").glob("*.md")))
        print(f"  [OK] 段落/ ({para_count} files)")

    # Copy COMTRADE source files
    extracted = job_root / "extracted"
    if extracted.is_dir():
        src_dest = dest / "录波源文件"
        count = copy_comtrade_files(extracted, src_dest)
        print(f"  [OK] 录波源文件/ ({count} files)")

    # Write metadata
    manifest = job_root / "inputs.json"
    zip_name = ""
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        files = data.get("files", [])
        if files:
            zip_name = files[0].get("filename", "")

    info = {
        "zip_name": zip_name,
        "job_id": job_id,
        "copied_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (dest / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] info.json")
    print(f"\nDone! Workspace: {dest}")


def main():
    app_root = find_app_root()

    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        jobs = list_completed_jobs(app_root)
        if not jobs:
            print("No completed jobs found.")
            return
        print(f"Found {len(jobs)} completed jobs:\n")
        for job_id, zip_name, created_at in jobs:
            print(f"  {job_id}  {zip_name}  {created_at}")
        print(f"\nUsage: python {sys.argv[0]} <job_id>")
        return

    if len(sys.argv) > 1:
        job_id = sys.argv[1]
    else:
        # Default: pick the latest job
        jobs = list_completed_jobs(app_root)
        if not jobs:
            print("No completed jobs found.")
            sys.exit(1)
        job_id = jobs[-1][0]
        print(f"Using latest job: {job_id}")

    print(f"Copying job {job_id} to workspace...")
    copy_job_to_workspace(app_root, job_id)


if __name__ == "__main__":
    main()
