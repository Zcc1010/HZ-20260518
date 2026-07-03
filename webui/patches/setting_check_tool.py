"""[SettingCheckTool] patch — register setting check read/write tools into the agent loop.

Adds ``setting_check_read`` and ``setting_check_write`` tools for reading and
modifying setting check reports from the setting check service.
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
            from webui.services.setting_check.tool import SettingCheckReadTool, SettingCheckWriteTool, SettingCheckRerunTool
            self.tools.register(SettingCheckReadTool())
            self.tools.register(SettingCheckWriteTool())
            self.tools.register(SettingCheckRerunTool())
            logger.debug("SettingCheckTool: registered setting_check_read + setting_check_write + setting_check_rerun")
        except Exception as exc:
            logger.error("SettingCheckTool: failed to register in __init__: {}", exc)

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.setting_check.tool import SettingCheckReadTool, SettingCheckWriteTool, SettingCheckRerunTool
            self.tools.register(SettingCheckReadTool())
            self.tools.register(SettingCheckWriteTool())
            self.tools.register(SettingCheckRerunTool())
            logger.debug("SettingCheckTool: registered setting_check_read + setting_check_write + setting_check_rerun")
        except Exception as exc:
            logger.error("SettingCheckTool: failed to register in _register_default_tools: {}", exc)

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
