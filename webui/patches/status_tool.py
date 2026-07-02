"""[StatusTool] patch — register status_query tool into the agent loop.

Adds a ``status_query`` tool that queries protection device running status
from the external dispatch platform API.
"""

from __future__ import annotations


def apply() -> None:
    from nanobot.agent.loop import AgentLoop

    _orig_init = AgentLoop.__init__
    _orig_register = AgentLoop._register_default_tools

    def _init_patched(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            from webui.services.status_query.tool import StatusQueryTool
            self.tools.register(StatusQueryTool())
        except Exception:
            pass

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.status_query.tool import StatusQueryTool
            self.tools.register(StatusQueryTool())
        except Exception:
            pass

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
