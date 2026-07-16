"""[SettingDownloadTestTool] patch — register setting_download_test tool into the agent loop.

Adds a ``setting_download_test`` tool that tests setting sheet download without parsing.
"""

from __future__ import annotations

from loguru import logger


def apply() -> None:
    from nanobot.agent.loop import AgentLoop

    _orig_init = AgentLoop.__init__
    _orig_register = AgentLoop._register_default_tools

    def _init_patched(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            from webui.services.setting_parser.tool_download_test import SettingDownloadTestTool
            self.tools.register(SettingDownloadTestTool())
            logger.debug("SettingDownloadTestTool: registered setting_download_test")
        except Exception as exc:
            logger.error("SettingDownloadTestTool: failed to register in __init__: {}", exc)

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.setting_parser.tool_download_test import SettingDownloadTestTool
            self.tools.register(SettingDownloadTestTool())
            logger.debug("SettingDownloadTestTool: registered setting_download_test")
        except Exception as exc:
            logger.error("SettingDownloadTestTool: failed to register in _register_default_tools: {}", exc)

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
