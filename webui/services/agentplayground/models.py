from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


APP_ID_WAVE_RECORD_PARSER = "wave-record-parser"
APP_ID_SETTING_CHECK = "setting-check"
JobStatus = Literal["queued", "processing", "completed", "failed"]


@dataclass(frozen=True)
class AgentPlaygroundApp:
    id: str
    name: str
    description: str
    kind: str = "workspace"
    enabled: bool = True

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)
