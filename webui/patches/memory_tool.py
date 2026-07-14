"""[MemoryTool] patch — register memory read/write tools into the agent loop.

Adds ``memory_read`` and ``memory_write`` tools for reading and
writing tool-specific memory files.
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
            from webui.services.memory_tool import MemoryReadTool, MemoryWriteTool
            self.tools.register(MemoryReadTool())
            self.tools.register(MemoryWriteTool())
            logger.debug("MemoryTool: registered memory_read + memory_write")
        except Exception as exc:
            logger.error("MemoryTool: failed to register in __init__: {}", exc)

    def _register_default_tools_patched(self) -> None:
        _orig_register(self)
        try:
            from webui.services.memory_tool import MemoryReadTool, MemoryWriteTool
            self.tools.register(MemoryReadTool())
            self.tools.register(MemoryWriteTool())
            logger.debug("MemoryTool: registered memory_read + memory_write")
        except Exception as exc:
            logger.error("MemoryTool: failed to register in _register_default_tools: {}", exc)

    AgentLoop.__init__ = _init_patched  # type: ignore[method-assign]
    AgentLoop._register_default_tools = _register_default_tools_patched  # type: ignore[method-assign]
