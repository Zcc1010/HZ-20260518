"""[TripBriefingTool] patch — register trip briefing read/write tools into the agent loop.

Adds ``trip_briefing_read`` and ``trip_briefing_write`` tools for reading and
modifying trip briefing reports from the wave record parser service.

Also patches ``_resolve_path`` to allow file tools to access the agentplayground
directory when ``restrictToWorkspace`` is enabled.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

# Keywords that identify agentplayground report paths
_REPORT_PATH_MARKERS = ("agentplayground", "跳闸简报", "定值校核")

# Extra directory that file tools should always be able to access
_AGENTPLAYGROUND_DIR = (Path.home() / ".nanobot" / "agentplayground").resolve()


def _is_report_path(path: str) -> bool:
    """Check if a file path looks like an agentplayground report file."""
    return any(m in path for m in _REPORT_PATH_MARKERS) and path.endswith(".md")


def _patch_edit_file_redirect(tools) -> None:
    """Wrap edit_file.execute to redirect agentplayground report edits to trip_briefing_write."""
    edit_tool = tools.get("edit_file")
    if edit_tool is None:
        return

    orig_execute = edit_tool.execute

    async def _redirected_execute(**kwargs):
        path = kwargs.get("path", "") or ""
        if _is_report_path(path):
            return (
                "错误：此文件是跳闸简报报告，不能用 edit_file 修改。"
                "请使用 trip_briefing_read 读取内容，修改后用 trip_briefing_write 写回。"
            )
        return await orig_execute(**kwargs)

    edit_tool.execute = _redirected_execute
    logger.debug("TripBriefingTool: edit_file redirect patched for agentplayground reports")


def _patch_resolve_path() -> None:
    """Patch _resolve_path to always allow agentplayground directory access."""
    from nanobot.agent.tools import filesystem

    orig_resolve = filesystem._resolve_path

    def _patched_resolve_path(
        path: str,
        workspace=None,
        allowed_dir=None,
        extra_allowed_dirs=None,
    ):
        # Inject agentplayground into extra_allowed_dirs
        extra = list(extra_allowed_dirs or [])
        if _AGENTPLAYGROUND_DIR not in extra:
            extra.append(_AGENTPLAYGROUND_DIR)
        return orig_resolve(path, workspace, allowed_dir, extra)

    filesystem._resolve_path = _patched_resolve_path
    logger.debug("TripBriefingTool: _resolve_path patched to allow agentplayground: {}", _AGENTPLAYGROUND_DIR)


def apply() -> None:
    from nanobot.agent.loop import AgentLoop

    # Patch _resolve_path first so file tools can access agentplayground
    try:
        _patch_resolve_path()
    except Exception as exc:
        logger.error("TripBriefingTool: failed to patch _resolve_path: {}", exc)

    _orig_init = AgentLoop.__init__
    _orig_register = AgentLoop._register_default_tools

    def _init_patched(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            from webui.services.trip_briefing.tool import TripBriefingReadTool, TripBriefingWriteTool, TripBriefingRerunTool
            self.tools.register(TripBriefingReadTool())
            self.tools.register(TripBriefingWriteTool())
            self.tools.register(TripBriefingRerunTool())
            _patch_edit_file_redirect(self.tools)
            logger.debug("TripBriefingTool: registered trip_briefing_read + trip_briefing_write + trip_briefing_rerun")
        except Exception as exc:
            logger.error("TripBriefingTool: failed to register in __init__: {}", exc)

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.trip_briefing.tool import TripBriefingReadTool, TripBriefingWriteTool, TripBriefingRerunTool
            self.tools.register(TripBriefingReadTool())
            self.tools.register(TripBriefingWriteTool())
            self.tools.register(TripBriefingRerunTool())
            _patch_edit_file_redirect(self.tools)
            logger.debug("TripBriefingTool: registered trip_briefing_read + trip_briefing_write + trip_briefing_rerun")
        except Exception as exc:
            logger.error("TripBriefingTool: failed to register in _register_default_tools: {}", exc)

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
