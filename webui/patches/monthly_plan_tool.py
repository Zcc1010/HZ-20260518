"""[MonthlyPlanTool] patch — register monthly_plan_process tool into the agent loop.

Adds a ``monthly_plan_process`` tool that processes monthly power outage plan
Excel files, searches for keywords in the "工作内容" column, marks matching
rows yellow, and generates a summary.
"""

from __future__ import annotations


def apply() -> None:
    from nanobot.agent.loop import AgentLoop

    _orig_init = AgentLoop.__init__
    _orig_register = AgentLoop._register_default_tools

    def _init_patched(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            from webui.services.monthly_plan.tool import MonthlyPlanProcessTool
            self.tools.register(MonthlyPlanProcessTool())
        except Exception:
            pass

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.monthly_plan.tool import MonthlyPlanProcessTool
            self.tools.register(MonthlyPlanProcessTool())
        except Exception:
            pass

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
