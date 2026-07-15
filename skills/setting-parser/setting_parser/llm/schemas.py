"""LLM 输出的中间结构（与顶层 models.py 区分，便于 schema 演进）."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class LLMDeviceMeta(BaseModel):
    station: str
    voltage_kv: int
    equipment_type: str
    equipment_name: str
    protection_set: str


class LLMProtectionDeviceMeta(BaseModel):
    vendor: str
    model_raw: str
    model_base: str
    firmware_version: str
    device_id: str


class LLMEquipmentParams(BaseModel):
    ct_ratio_primary: int
    ct_ratio_secondary: int
    pt_ratio_primary: int
    pt_ratio_secondary: int
    rated_current_a: float


class LLMSettingItem(BaseModel):
    item_no: str
    name_raw: str
    value: str
    value_numeric: Optional[float] = None
    unit: Optional[str] = None
    function: Optional[str] = None


class LLMControlWord(BaseModel):
    name_raw: str
    value: str
    meaning: Optional[str] = None


class LLMTripMatrixEntry(BaseModel):
    segment: str
    value: str
    decoded: list[str]


class LLMTripMatrix(BaseModel):
    format: str
    entries: list[LLMTripMatrixEntry]


class LLMSheetDraft(BaseModel):
    """LLM 抽取的中间结果（不含 knowledge_ref / name_alias，事后由后处理补全）."""
    device: LLMDeviceMeta
    protection_device: LLMProtectionDeviceMeta
    equipment_params: LLMEquipmentParams
    settings: list[LLMSettingItem] = Field(default_factory=list)
    control_words: list[LLMControlWord] = Field(default_factory=list)
    trip_matrix: Optional[LLMTripMatrix] = None
    parse_warnings: list[str] = Field(default_factory=list)