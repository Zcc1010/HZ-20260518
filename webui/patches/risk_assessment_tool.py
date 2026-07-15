"""[RiskAssessmentTool] patch — register risk_assessment_collect tool into the agent loop.

Adds a ``risk_assessment_collect`` tool that orchestrates full 6-source
data collection for protection risk assessment in a single call.
"""

from __future__ import annotations


def apply() -> None:
    from nanobot.agent.loop import AgentLoop

    _orig_init = AgentLoop.__init__
    _orig_register = AgentLoop._register_default_tools

    def _init_patched(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            from webui.services.risk_assessment.tool import RiskAssessmentCollectTool
            self.tools.register(RiskAssessmentCollectTool())
        except Exception:
            pass

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.risk_assessment.tool import RiskAssessmentCollectTool
            self.tools.register(RiskAssessmentCollectTool())
        except Exception:
            pass

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
