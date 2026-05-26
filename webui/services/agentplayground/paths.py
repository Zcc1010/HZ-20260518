from __future__ import annotations

from pathlib import Path

from webui.services.agentplayground.models import APP_ID_G_FILE_COMPARE, APP_ID_WAVE_RECORD_PARSER, APP_ID_SETTING_CHECK


def default_agentplayground_root(workspace: str | Path) -> Path:
    workspace_root = Path(workspace).expanduser().resolve()
    return workspace_root.parent / "agentplayground"


def default_app_root(workspace: str | Path, app_id: str) -> Path:
    return default_agentplayground_root(workspace) / app_id


def default_g_file_compare_app_root(workspace: str | Path) -> Path:
    return default_app_root(workspace, APP_ID_G_FILE_COMPARE)


def default_wave_record_parser_app_root(workspace: str | Path) -> Path:
    return default_app_root(workspace, APP_ID_WAVE_RECORD_PARSER)


def default_setting_check_app_root(workspace: str | Path) -> Path:
    return default_app_root(workspace, APP_ID_SETTING_CHECK)
