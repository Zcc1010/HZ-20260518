"""[FaultAnalysisTool] patch — register fault_analysis_rerun tool into the agent loop.

Adds ``fault_analysis_rerun`` tool for re-running fault analysis pipeline from
existing uploaded files.
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
            from webui.services.fault_analysis.tool import FaultAnalysisRerunTool
            self.tools.register(FaultAnalysisRerunTool())
            logger.debug("FaultAnalysisTool: registered fault_analysis_rerun")
        except Exception as exc:
            logger.error("FaultAnalysisTool: failed to register in __init__: {}", exc)

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.fault_analysis.tool import FaultAnalysisRerunTool
            self.tools.register(FaultAnalysisRerunTool())
            logger.debug("FaultAnalysisTool: registered fault_analysis_rerun")
        except Exception as exc:
            logger.error("FaultAnalysisTool: failed to register in _register_default_tools: {}", exc)

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
