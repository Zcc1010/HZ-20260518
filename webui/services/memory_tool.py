"""Memory tools — read and write tool-specific memory files.

Each tool has its own memory namespace stored at:
    ~/.nanobot/workspace/memory/tools/{tool_name}/MEMORY.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


class ToolMemoryStore:
    """Standalone file-based memory store for tool-specific namespaces."""

    def __init__(self, workspace: Path, tool_name: str):
        self.tool_name = tool_name
        self.memory_dir = workspace / "memory" / "tools" / tool_name
        self.memory_file = self.memory_dir / "MEMORY.md"

    def read_memory(self) -> str:
        try:
            return self.memory_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def write_memory(self, content: str) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file.write_text(content, encoding="utf-8")

    @staticmethod
    def list_tool_namespaces(workspace: Path) -> list[str]:
        tools_dir = workspace / "memory" / "tools"
        if not tools_dir.exists():
            return []
        return sorted(
            d.name for d in tools_dir.iterdir()
            if d.is_dir() and (d / "MEMORY.md").exists()
        )


@tool_parameters(
    tool_parameters_schema(
        tool_name=StringSchema("工具名称，如 wave-record、setting-check"),
    )
)
class MemoryReadTool(Tool):
    """Read tool-specific memory content."""

    name = "memory_read"
    description = "读取指定工具的长期记忆内容。记忆用于存储工具专属的知识和用户偏好。"

    async def execute(self, tool_name: str = "", **kwargs: Any) -> str:
        if not tool_name:
            return "错误：请指定工具名称（tool_name）"

        workspace = Path.home() / ".nanobot" / "workspace"
        store = ToolMemoryStore(workspace, tool_name)
        content = store.read_memory()

        if not content:
            return f"工具 '{tool_name}' 暂无记忆内容。"

        return f"## 工具 '{tool_name}' 的记忆\n\n{content}"


@tool_parameters(
    tool_parameters_schema(
        tool_name=StringSchema("工具名称，如 wave-record、setting-check"),
        content=StringSchema("要写入的记忆内容（Markdown格式）"),
    )
)
class MemoryWriteTool(Tool):
    """Write tool-specific memory content."""

    name = "memory_write"
    description = "写入或更新指定工具的长期记忆。记忆用于存储工具专属的知识和用户偏好。"

    async def execute(self, tool_name: str = "", content: str = "", **kwargs: Any) -> str:
        if not tool_name:
            return "错误：请指定工具名称（tool_name）"

        if not content:
            return "错误：请提供要写入的记忆内容（content）"

        workspace = Path.home() / ".nanobot" / "workspace"
        store = ToolMemoryStore(workspace, tool_name)
        store.write_memory(content)

        logger.info("MemoryWriteTool: wrote memory for tool '{}'", tool_name)
        return f"已成功更新工具 '{tool_name}' 的记忆。"
