import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from webui.api.routes import config as config_routes


def _make_services(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return SimpleNamespace(
        config=SimpleNamespace(
            agents=SimpleNamespace(defaults=SimpleNamespace(workspace=str(workspace)))
        )
    )


@pytest.mark.asyncio
async def test_upload_to_s3_accepts_file_at_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(config_routes, "_load_s3", lambda: {"enabled": False, "bucket": ""})
    svc = _make_services(tmp_path)
    payload = b"a" * config_routes._MAX_UPLOAD_BYTES
    file = UploadFile(filename="ok.bin", file=io.BytesIO(payload))

    result = await config_routes.upload_to_s3(
        file=file,
        _admin={"username": "tester"},
        svc=svc,
    )

    saved = tmp_path / "workspace" / "uploads" / "tester"
    assert result["filename"] == "ok.bin"
    assert saved.exists()
    assert len(list(saved.iterdir())) == 1


@pytest.mark.asyncio
async def test_upload_to_s3_rejects_file_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(config_routes, "_load_s3", lambda: {"enabled": False, "bucket": ""})
    svc = _make_services(tmp_path)
    payload = b"a" * (config_routes._MAX_UPLOAD_BYTES + 1)
    file = UploadFile(filename="too-large.bin", file=io.BytesIO(payload))

    with pytest.raises(HTTPException) as exc_info:
        await config_routes.upload_to_s3(
            file=file,
            _admin={"username": "tester"},
            svc=svc,
        )

    assert exc_info.value.status_code == 413
    assert "32MB" in str(exc_info.value.detail)
