"""webui.patches — monkey-patches applied to nanobot at startup.
 
Each sub-module targets one concern and exposes a single ``apply()`` function.
Call ``apply_all()`` once at process start (done by ``webui.__main__``).
 
Patch inventory
───────────────
channels    [Channel]     Relax access-control managed by the WebUI.
network     [Network]     Allow RFC1918 intranet ranges through shared guards.
mcp_dynamic [MCPDynamic]  Per-server MCP stacks for dynamic load/unload.
prompt      [Prompt]      Brand and constrain the internal system prompt.
session     [Session]     Add SessionManager.delete for UI-initiated deletion.
provider    [Provider]    Auto-fall-back to OpenAI /v1/responses when needed.
skills      [Skills]      Honour .disabled_skills.json from the WebUI toggle.
subagent    [SubAgent]    Push tool-call progress to WebUI / external channels.
token_estimation [TokenEstimation] Fail fast on offline tiktoken misses.
ledger_tool [LedgerTool]  Register ledger_query tool for equipment queries.
status_tool [StatusTool]  Register status_query tool for running status queries.
important_warn_tool [ImportantWarnTool] Register important_warn_query tool for alarm queries.
trip_briefing_tool [TripBriefingTool] Register trip_briefing_read/write tools for briefing reports.
setting_check_tool [SettingCheckTool] Register setting_check_read/write tools for check reports.
memory_tool [MemoryTool]  Register memory_read/write tools for tool-specific memory.
risk_assessment_tool [RiskAssessmentTool] Register risk_assessment_collect tool for 6-source data orchestration.
setting_parser_tool [SettingParserTool] Register setting_parse_device tool for auto download + parse setting sheets.
setting_download_test_tool [SettingDownloadTestTool] Register setting_download_test tool for testing setting sheet download only.
safety_ticket_tool [SafetyTicketTool] Register safety_ticket_review tools for safety ticket review.
"""
 
from __future__ import annotations
 
from webui.patches import channels, config, important_warn_tool, ledger_tool, memory_tool, mcp_dynamic, network, prompt, provider, risk_assessment_tool, safety_ticket_tool, session, setting_check_tool, setting_download_test_tool, setting_parser_tool, skills, status_tool, subagent, token_estimation, trip_briefing_tool


def apply_all() -> None:
    """Apply every patch in dependency order."""
    config.apply()       # must run early to intercept Config methods
    network.apply()
    mcp_dynamic.apply()  # must run before agent is created
    prompt.apply()
    channels.apply()
    session.apply()
    token_estimation.apply()
    provider.apply()
    skills.apply()
    subagent.apply()
    ledger_tool.apply()
    status_tool.apply()
    important_warn_tool.apply()
    trip_briefing_tool.apply()
    setting_check_tool.apply()
    memory_tool.apply()
    risk_assessment_tool.apply()
    setting_parser_tool.apply()
    setting_download_test_tool.apply()
    safety_ticket_tool.apply()
