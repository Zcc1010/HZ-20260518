"""[SettingParserTool] patch — register setting_parse_device tool into the agent loop.

Adds a ``setting_parse_device`` tool that automatically downloads setting sheets
from the secondary equipment ledger and parses them.
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
            from webui.services.setting_parser.tool import SettingParseDeviceTool
            self.tools.register(SettingParseDeviceTool())
            logger.debug("SettingParserTool: registered setting_parse_device")
        except Exception as exc:
            logger.error("SettingParserTool: failed to register in __init__: {}", exc)

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.setting_parser.tool import SettingParseDeviceTool
            self.tools.register(SettingParseDeviceTool())
            logger.debug("SettingParserTool: registered setting_parse_device")
        except Exception as exc:
            logger.error("SettingParserTool: failed to register in _register_default_tools: {}", exc)

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
