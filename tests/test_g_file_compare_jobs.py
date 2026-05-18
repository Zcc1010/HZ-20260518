import asyncio
import json
import shutil
import sqlite3
from pathlib import Path


def _write_g_file(path, *, object_id="b1", keyid="k1"):
    xml = (
        '<G facName="测试厂站">'
        f'<Breaker id="{object_id}" key_name="线路一/开关1" keyid="{keyid}" x="1" y="2" />'
        '</G>'
    )
    path.write_bytes(xml.encode("gbk"))


def _install_app_skill(app_root):
    source = Path(__file__).resolve().parents[1] / "skills" / "g-file-contrast"
    target = app_root / "skills" / "g-file-contrast"
    shutil.copytree(source, target)
    return target


def test_create_compare_job_uses_app_root_and_single_app_jobs_table(tmp_path):
    from webui.services.g_file_compare.service import GFileCompareService

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app_root = tmp_path / "agentplayground" / "g-file-compare"

    d5000_file = tmp_path / "D5000.xlsx"
    d5000_file.write_text("legacy\n", encoding="utf-8")
    new_gen_file = tmp_path / "new-gen.xlsx"
    new_gen_file.write_text("next\n", encoding="utf-8")

    service = GFileCompareService(app_root=app_root)
    service.initialize()

    job = service.create_job(d5000_file, new_gen_file, run_in_background=False)

    assert job["id"]
    assert job["app_id"] == "g-file-compare"
    assert job["status"] == "queued"
    assert not (workspace / "agentplayground").exists()
    assert (app_root / "app.db").exists()
    job_root = app_root / "jobs" / job["id"]
    assert (job_root / "inputs" / "d5000" / "D5000.xlsx").read_text(encoding="utf-8") == "legacy\n"
    assert (job_root / "inputs" / "new-gen" / "new-gen.xlsx").read_text(encoding="utf-8") == "next\n"
    manifest = json.loads((job_root / "inputs.json").read_text(encoding="utf-8"))
    assert manifest["d5000"]["relative_path"] == "inputs/d5000/D5000.xlsx"
    assert manifest["new_gen"]["relative_path"] == "inputs/new-gen/new-gen.xlsx"

    with sqlite3.connect(app_root / "app.db") as conn:
        jobs_row = conn.execute(
            "SELECT status, d5000_file_name, new_gen_file_name FROM jobs WHERE id = ?",
            (job["id"],),
        ).fetchone()
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert jobs_row == ("queued", "D5000.xlsx", "new-gen.xlsx")
    assert tables == {"jobs"}


def test_completed_compare_job_exposes_download_metadata(tmp_path):
    from webui.services.g_file_compare.service import GFileCompareService

    app_root = tmp_path / "agentplayground" / "g-file-compare"

    d5000_file = tmp_path / "d5000.txt"
    d5000_file.write_text("alpha\n", encoding="utf-8")
    new_gen_file = tmp_path / "new-gen.txt"
    new_gen_file.write_text("beta\n", encoding="utf-8")

    service = GFileCompareService(app_root=app_root)
    service.initialize()

    job = service.create_job(d5000_file, new_gen_file, run_in_background=False)
    report = app_root / "jobs" / job["id"] / "report.txt"
    report.write_text("# compare report\n", encoding="utf-8")

    service.mark_completed(job["id"], report)
    listed = service.list_jobs()

    assert len(listed) == 1
    assert listed[0]["result_file_name"] == "report.txt"
    assert listed[0]["download_url"].startswith("/api/files/d/")


def test_non_completed_compare_jobs_do_not_expose_download_metadata(tmp_path):
    from webui.services.g_file_compare.service import GFileCompareService

    app_root = tmp_path / "agentplayground" / "g-file-compare"
    d5000_file = tmp_path / "d5000.txt"
    d5000_file.write_text("alpha\n", encoding="utf-8")
    new_gen_file = tmp_path / "new-gen.txt"
    new_gen_file.write_text("beta\n", encoding="utf-8")

    service = GFileCompareService(app_root=app_root)
    service.initialize()

    queued = service.create_job(d5000_file, new_gen_file, run_in_background=False)
    failed = service.mark_failed(queued["id"], "boom")

    assert failed is not None
    assert failed["download_url"] is None
    assert service.find_result_attachment("missing-token") is None


def test_stale_processing_jobs_are_marked_failed_on_initialize(tmp_path):
    from webui.services.g_file_compare.service import GFileCompareService

    app_root = tmp_path / "agentplayground" / "g-file-compare"
    service = GFileCompareService(app_root=app_root)
    service.initialize()

    d5000_file = tmp_path / "d5000.txt"
    d5000_file.write_text("alpha\n", encoding="utf-8")
    new_gen_file = tmp_path / "new-gen.txt"
    new_gen_file.write_text("beta\n", encoding="utf-8")
    job = service.create_job(d5000_file, new_gen_file, run_in_background=False)
    service.mark_processing(job["id"])

    recovered = GFileCompareService(app_root=app_root)
    recovered.initialize()

    loaded = recovered.get_job(job["id"])
    assert loaded is not None
    assert loaded["status"] == "failed"
    assert loaded["error_message"] == "服务重启导致任务中断，请重新提交"


def test_process_queue_runs_one_job_at_a_time(tmp_path):
    from webui.services.g_file_compare.service import GFileCompareService

    app_root = tmp_path / "agentplayground" / "g-file-compare"
    _install_app_skill(app_root)
    service = GFileCompareService(app_root=app_root)
    service.initialize()

    d5000_file = tmp_path / "d5000.txt"
    _write_g_file(d5000_file, object_id="d1")
    new_gen_file = tmp_path / "new-gen.txt"
    _write_g_file(new_gen_file, object_id="n1")
    first = service.create_job(d5000_file, new_gen_file, run_in_background=False)
    second = service.create_job(d5000_file, new_gen_file, run_in_background=False)

    asyncio.run(service.process_queue())

    jobs = {job["id"]: job for job in service.list_jobs()}
    assert jobs[first["id"]]["status"] == "completed"
    assert jobs[second["id"]]["status"] == "completed"
    assert (app_root / "jobs" / first["id"] / "result.json").exists()
    assert (app_root / "jobs" / second["id"] / "result.json").exists()
    assert "d5000.txt" in (app_root / "jobs" / first["id"] / "report.txt").read_text(encoding="utf-8")
