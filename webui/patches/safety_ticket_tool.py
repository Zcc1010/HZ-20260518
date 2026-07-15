"""[SafetyTicketTool] patch — register safety_ticket_review tools into the agent loop.

Adds two tools:
  - safety_ticket_review_extract: extract docx text + read knowledge base
  - safety_ticket_review_generate_report: generate review report docx from JSON
"""

from __future__ import annotations

from loguru import logger


def apply() -> None:
    from nanobot.agent.loop import AgentLoop

    _orig_init = AgentLoop.__init__
    _orig_register = AgentLoop._register_default_tools

    def _register_tools(self):
        try:
            from webui.services.safety_ticket.tool import (
                SafetyTicketReviewExtractTool,
                SafetyTicketReviewGenerateReportTool,
            )
            self.tools.register(SafetyTicketReviewExtractTool())
            self.tools.register(SafetyTicketReviewGenerateReportTool())
            logger.debug("SafetyTicketTool: registered safety_ticket_review_extract + safety_ticket_review_generate_report")
        except Exception as exc:
            logger.error("SafetyTicketTool: failed to register: {}", exc)

    def _init_patched(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        _register_tools(self)

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        _register_tools(self)

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
