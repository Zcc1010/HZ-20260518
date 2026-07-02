"""[ImportantWarnTool] patch — register important_warn_query tool into the agent loop.

Adds an ``important_warn_query`` tool that queries alarm events and chart
statistics from the external dispatch platform API.
"""

from __future__ import annotations


def apply() -> None:
    from nanobot.agent.loop import AgentLoop

    _orig_init = AgentLoop.__init__
    _orig_register = AgentLoop._register_default_tools

    def _init_patched(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            from webui.services.important_warn.tool import ImportantWarnQueryTool
            self.tools.register(ImportantWarnQueryTool())
        except Exception:
            pass

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.important_warn.tool import ImportantWarnQueryTool
            self.tools.register(ImportantWarnQueryTool())
        except Exception:
            pass

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
