"""Pydantic 数据模型 — spec §4 JSON Schema 的强类型映射."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator


class SourceMeta(BaseModel):
    file_path: str
    file_sha256: str = Field(min_length=64, max_length=64)
    parsed_at: str  # ISO 8601


class DeviceMeta(BaseModel):
    station: str
    voltage_kv: int
    equipment_type: str
    equipment_name: str
    protection_set: str


class ProtectionDeviceMeta(BaseModel):
    vendor: str
    model_raw: str
    model_base: str
    firmware_version: str
    device_id: str
    knowledge_base_ref: Optional[str] = None


class EquipmentParams(BaseModel):
    ct_ratio_primary: int
    ct_ratio_secondary: int
    pt_ratio_primary: int
    pt_ratio_secondary: int
    rated_current_a: float


class KnowledgeRef(BaseModel):
    """settings 用的知识库引用（含范围，便于异常检测）."""
    manual: str
    section: str
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    range_unit: Optional[str] = None


class SettingItem(BaseModel):
    item_no: str
    name_raw: str
    name_alias: Optional[str] = None
    value: str  # 字符串保留原值（"0xABCD" / "0.50"）
    value_numeric: Optional[float] = None
    unit: Optional[str] = None
    function: Optional[str] = None
    knowledge_ref: Optional[KnowledgeRef] = None


class ControlWord(BaseModel):
    name_raw: str
    name_alias: Optional[str] = None
    value: str
    meaning: Optional[str] = None
    knowledge_ref: Optional[str] = None  # 字符串（仅文件位置）


class TripMatrixEntry(BaseModel):
    segment: str
    value: str
    decoded: list[str]


class TripMatrix(BaseModel):
    format: str  # "hex" | "binary"
    entries: list[TripMatrixEntry]


class SettingSheet(BaseModel):
    schema_version: str = "1.0"
    source: SourceMeta
    device: DeviceMeta
    protection_device: ProtectionDeviceMeta
    equipment_params: EquipmentParams
    settings: list[SettingItem] = Field(default_factory=list)
    control_words: list[ControlWord] = Field(default_factory=list)
    trip_matrix: Optional[TripMatrix] = None
    parse_warnings: list[str] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def check_version(cls, v: str) -> str:
        if not v.startswith("1."):
            raise ValueError(f"unsupported schema_version: {v}")
        return v
