#!/usr/bin/env python3
"""Compare one D5000 G file and one 新一代 G file."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

IGNORED_TAGS = {
    "G",
    "Layer",
    "Theme",
    "Color",
    "Font",
    "Item",
    "Text",
    "DText",
    "ConnectLine",
    "poke",
}
COORD_ATTRS = ("x", "y", "x1", "y1", "x2", "y2", "w", "h")
UNORDERED_ATTRS = {"link", "node_area"}
GLOBAL_COMPARABLE_ATTRS = {
    "app",
    "fc",
    "fm",
    "fs",
    "LevelEnd",
    "LevelStart",
    "link",
    "ls",
    "lw",
    "node_area",
    "p_AssFlag",
    "p_FatherObjId",
    "p_ShowModeMask",
    "state",
    "switchapp",
    "tfr",
}
REQUIRED_FIELDS_BY_TAG = {
    "ACLineEnd": {"id", "keyid", "key_name", "d", "link", "state"},
    "Arrester": {"id", "keyid", "x", "y", "devref"},
    "Bus": {"id", "keyid", "key_name", "d", "x1", "y1", "x2", "y2", "state"},
    "CBreaker": {"id", "keyid", "key_name", "x", "y", "devref", "state"},
    "ConnectLine": {"id", "d", "link"},
    "Disconnector": {"id", "keyid", "key_name", "x", "y", "devref", "state"},
    "DText": {"id", "keyid", "key_name", "x", "y"},
    "EnergyConsumer": {"id", "d", "link"},
    "GroundDisconnector": {"id", "keyid", "key_name", "x", "y", "devref", "state"},
    "PT": {"id", "keyid", "key_name", "x", "y", "devref", "state"},
    "Status": {"id", "x", "y", "devref"},
    "Table": {"id", "x", "y", "devref"},
    "Terminal": {"id", "keyid", "x", "y", "devref"},
    "Text": {"id", "ts", "x", "y"},
    "Transformer2": {"id", "keyid1", "keyid2", "key_name1", "key_name2", "x", "y", "devref", "state1", "state2"},
    "Transformer3": {
        "id",
        "keyid1",
        "keyid2",
        "keyid3",
        "key_name1",
        "key_name2",
        "key_name3",
        "x",
        "y",
        "devref",
        "state1",
        "state2",
        "state3",
    },
    "Zxddd": {"id", "keyid", "x", "y", "devref"},
    "poke": {"id", "x", "y", "ahref"},
}
ONLY_NEW_GEN_ATTRS = {
    "bold",
    "calendar",
    "composeType",
    "datalength",
    "deltaX",
    "deltaY",
    "devref",
    "end_time",
    "endArrowSize",
    "endArrowType",
    "fcc",
    "h",
    "interval",
    "italic",
    "menu_type",
    "node_area",
    "p_DataFrom",
    "p_FatherObjId",
    "p_IsAbs",
    "p_ReportType",
    "p_ReverseDisplayT",
    "p_SignDisplayT",
    "p_jDisplayT",
    "sta_mode",
    "sta_policy",
    "sta_type",
    "start_time",
    "startArrowSize",
    "startArrowType",
    "w",
    "wmT",
    "x",
    "y",
}
ROOT_COMPARABLE_ATTRS = (
    "w",
    "h",
    "bgi",
    "bgf",
    "bgc",
    "bgiw",
    "VerNo",
    "InitAppID",
    "InitAppAvailable",
)
ROOT_NEW_GEN_ONLY_ATTRS = (
    "graphType",
    "facID",
    "facName",
    "requestPara",
    "requestDest",
    "scaleType",
    "workCondtionFileType",
    "Refresh",
    "animModel",
    "animNum",
    "color",
    "x",
    "y",
)
WEAK_SCORE_MIN = 140
EVIDENCE_LABELS = {
    "same_keyid": "同keyid",
    "same_key_name": "同key_name",
    "same_label": "同设备名称",
    "same_devref": "同图元引用",
    "same_object_id": "同对象ID",
    "same_position": "坐标一致",
    "near_position": "坐标接近",
    "rough_position": "坐标大致接近",
}
RTKEYID_PREFIX_LABELS = {
    "1210": "线路量测",
    "1301": "母线量测",
    "1312": "主变量测",
    "1321": "断路器量测",
    "1322": "刀闸量测",
    "1323": "接地刀闸量测",
    "103054": "其他遥测",
    "103055": "其他遥信",
    "1101": "发电机量测",
    "1108": "发电机量测",
    "223621": "光伏量测",
}
FIELD_RULE_ROWS = [
    ["P0-必须比对", "标识字段", "id、keyid、key_name", "精确比较"],
    ["P0-必须比对", "位置字段", "x、y、d、x1/y1/x2/y2", "坐标按容差比较，d按路径坐标比较"],
    ["P1-建议比对", "关联字段", "node_area、link、p_FatherObjId", "分号分隔项先排序再比较"],
    ["P1-建议比对", "状态字段", "state、app、switchapp", "精确比较"],
    ["P1-建议比对", "样式字段", "fc、fm、ls、lw、fs、tfr", "精确比较"],
    ["P2-可选比对", "显示控制", "p_ShowModeMask、LevelStart/End、p_AssFlag", "精确比较"],
    ["P3-跳过", "颜色映射", "lc", "两套系统颜色映射不同，不直接作为异常"],
    ["P3-跳过", "编码差异", "voltype", "两套系统编码体系不同，不直接作为异常"],
    ["P3-跳过", "新一代独有", "rtkeyid、composeType、h、w等", "D5000通常不存在，报告中仅提示"],
]
SYSTEM_DIFF_ROWS = [
    ["lc颜色映射", "ACLineEnd、Bus、CBreaker、ConnectLine、Disconnector、GroundDisconnector", "两套颜色映射体系", "通常不需要关注"],
    ["voltype编码", "ACLineEnd、Bus、CBreaker、DText、Disconnector、GroundDisconnector、Transformer", "两套编码体系", "需要业务映射时再确认"],
    ["坐标浮点精度", "Text、GroundDisconnector等", "小数精度不同", "容差内不算异常"],
    ["link顺序", "ConnectLine", "分号分隔项顺序不同", "排序后一致则不算异常"],
    ["node_area顺序", "Bus、ConnectLine等", "分号分隔项顺序不同", "排序后一致则不算异常"],
    ["新一代独有属性", "多数设备类型", "新系统补充元数据", "不直接作为设备不对应依据"],
]


def normalize_text(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    return value.lower()


def normalize_signature(parts: Iterable[str]) -> str:
    cleaned = sorted({normalize_text(part) for part in parts if normalize_text(part)})
    return "|".join(cleaned)


def parse_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_point_stream(raw: str | None) -> list[tuple[float, float]]:
    if not raw:
        return []
    points = []
    for chunk in raw.split():
        if "," not in chunk:
            continue
        left, right = chunk.split(",", 1)
        x_val = parse_float(left)
        y_val = parse_float(right)
        if x_val is None or y_val is None:
            continue
        points.append((x_val, y_val))
    return points


def basename_devref(devref: str) -> str:
    value = normalize_text(devref)
    if not value:
        return ""
    return value.split(":")[-1]


def label_from_parts(tag: str, key_names: list[str], text_value: str, devref: str, object_id: str) -> str:
    if key_names:
        tail = key_names[0].split("/")[-1].strip()
        if tail:
            return tail
    if text_value.strip():
        return text_value.strip()
    if devref.strip():
        return devref.split(":")[-1].strip()
    return f"{tag}:{object_id}"


def parse_xml_root(path: Path) -> ET.Element:
    text = path.read_bytes().decode("gbk", errors="replace")
    return ET.fromstring(text)


def collect_all_objects(root: ET.Element) -> list[dict[str, object]]:
    objects = []
    for elem in root.iter():
        object_id = elem.attrib.get("id")
        if not object_id or elem.tag in {"G", "Layer", "Theme", "Color", "Font", "Item"}:
            continue
        objects.append({"tag": elem.tag, "id": object_id, "attrs": dict(elem.attrib)})
    return objects


def root_compare_rows(d5000_attrs: dict[str, str], xyd_attrs: dict[str, str]) -> list[list[str]]:
    rows = []
    for attr in ROOT_COMPARABLE_ATTRS:
        d5000_value = d5000_attrs.get(attr, "-")
        xyd_value = xyd_attrs.get(attr, "-")
        rows.append(
            [
                attr,
                d5000_value,
                xyd_value,
                "一致" if d5000_value == xyd_value else "不一致",
                "G根元素共有属性，按规则直接比较",
            ]
        )
    return rows


def new_gen_only_root_rows(xyd_attrs: dict[str, str]) -> list[list[str]]:
    rows = []
    for attr in ROOT_NEW_GEN_ONLY_ATTRS:
        if attr in xyd_attrs:
            rows.append([attr, xyd_attrs.get(attr, ""), "新一代文件级元数据，D5000中通常不存在，不参与异常判断"])
    return rows


def object_type_overview_rows(d5000_objects: list[dict[str, object]], xyd_objects: list[dict[str, object]]) -> list[list[str]]:
    d5000_by_tag = Counter(str(item["tag"]) for item in d5000_objects)
    xyd_by_tag = Counter(str(item["tag"]) for item in xyd_objects)
    d5000_ids_by_tag: dict[str, set[str]] = defaultdict(set)
    xyd_ids_by_tag: dict[str, set[str]] = defaultdict(set)
    field_presence: dict[tuple[str, str, str], bool] = defaultdict(bool)

    for source, objects, ids_by_tag in (
        ("d5000", d5000_objects, d5000_ids_by_tag),
        ("xyd", xyd_objects, xyd_ids_by_tag),
    ):
        for item in objects:
            tag = str(item["tag"])
            attrs = item["attrs"]
            ids_by_tag[tag].add(str(item["id"]))
            if any(key.startswith("keyid") and attrs.get(key) not in (None, "", "0") for key in attrs):
                field_presence[(source, tag, "keyid")] = True
            if any(key.startswith("key_name") and attrs.get(key) for key in attrs):
                field_presence[(source, tag, "key_name")] = True
            if any(key.startswith("rtkeyid") and attrs.get(key) for key in attrs):
                field_presence[(source, tag, "rtkeyid")] = True

    rows = []
    for tag in sorted(set(d5000_by_tag) | set(xyd_by_tag)):
        d5000_count = d5000_by_tag.get(tag, 0)
        xyd_count = xyd_by_tag.get(tag, 0)
        common_ids = len(d5000_ids_by_tag[tag] & xyd_ids_by_tag[tag])
        expected = max(d5000_count, xyd_count)
        rows.append(
            [
                tag,
                str(d5000_count),
                str(xyd_count),
                "一致" if d5000_count == xyd_count else "不一致",
                f"{common_ids}/{expected}" if expected else "0/0",
                "是" if field_presence[("d5000", tag, "keyid")] or field_presence[("xyd", tag, "keyid")] else "否",
                "是" if field_presence[("d5000", tag, "key_name")] or field_presence[("xyd", tag, "key_name")] else "否",
                "是" if field_presence[("xyd", tag, "rtkeyid")] else "否",
            ]
        )
    return rows


def id_match_summary(d5000_objects: list[dict[str, object]], xyd_objects: list[dict[str, object]]) -> dict[str, int]:
    d5000_ids = {str(item["id"]) for item in d5000_objects}
    xyd_ids = {str(item["id"]) for item in xyd_objects}
    common_ids = d5000_ids & xyd_ids
    return {
        "d5000_object_count": len(d5000_objects),
        "xyd_object_count": len(xyd_objects),
        "d5000_id_count": len(d5000_ids),
        "xyd_id_count": len(xyd_ids),
        "common_id_count": len(common_ids),
        "d5000_only_id_count": len(d5000_ids - xyd_ids),
        "xyd_only_id_count": len(xyd_ids - d5000_ids),
    }


def object_label(tag: str, attrs: dict[str, str], object_id: str) -> str:
    key_names = collect_signature_values(attrs, "key_name")
    text_value = attrs.get("ts", "")
    devref = attrs.get("devref", "")
    return label_from_parts(tag, key_names, text_value, devref, object_id)


def display_attr_value(value: object) -> str:
    if value is None:
        return "不存在"
    text = str(value)
    return text if text else "空"


def normalize_unordered_value(value: str | None) -> tuple[str, ...]:
    if not value:
        return tuple()
    return tuple(sorted(item.strip() for item in value.split(";") if item.strip()))


def is_new_gen_only_attr(attr: str) -> bool:
    return attr in ONLY_NEW_GEN_ATTRS or attr.startswith("rtkeyid")


def is_rule_comparable_attr(tag: str, attr: str) -> bool:
    if attr in REQUIRED_FIELDS_BY_TAG.get(tag, set()):
        return True
    if attr in GLOBAL_COMPARABLE_ATTRS:
        return True
    return False


def classify_field_difference(tag: str, attr: str, d5000_value: str | None, xyd_value: str | None, tolerance: float) -> tuple[str, str] | None:
    if attr == "id" or d5000_value == xyd_value:
        return None

    if d5000_value is not None and xyd_value is not None:
        if attr == "lc":
            return "规则内差异", "lc颜色映射：两套系统颜色映射不同，不直接作为异常"

        if attr.startswith("voltype"):
            return "需确认", "voltype编码：两侧编码体系不同，需要按业务映射关系确认"

        if not is_rule_comparable_attr(tag, attr):
            return None

        if attr in UNORDERED_ATTRS and normalize_unordered_value(d5000_value) == normalize_unordered_value(xyd_value):
            return "规则内差异", f"{attr} 字段顺序不同，但拆分排序后内容一致"

        d5000_number = parse_float(d5000_value)
        xyd_number = parse_float(xyd_value)
        if d5000_number is not None and xyd_number is not None and abs(d5000_number - xyd_number) <= tolerance:
            return "规则内差异", f"{attr} 字段为浮点精度差异，差值在容差内"

        return "需关注", "规则要求比对的字段值不一致"

    if d5000_value is None and xyd_value is not None:
        if is_new_gen_only_attr(attr):
            return "6.0独有", "6.0新增属性，D5000 通常不存在，不参与直接比对"
        if is_rule_comparable_attr(tag, attr):
            return "需关注", "规则要求比对的字段仅 6.0 存在，D5000 缺失"
        return None

    if d5000_value is not None and xyd_value is None:
        if is_rule_comparable_attr(tag, attr):
            return "需关注", "规则要求比对的字段仅 D5000 存在，6.0 缺失"
        return None

    return None


def build_field_diff_analysis(d5000_path: Path, xyd_path: Path, tolerance: float) -> dict[str, object]:
    d5000_objects = collect_all_objects(parse_xml_root(d5000_path))
    xyd_objects = collect_all_objects(parse_xml_root(xyd_path))
    d5000_by_key = {(str(item["tag"]), str(item["id"])): item for item in d5000_objects}
    xyd_by_key = {(str(item["tag"]), str(item["id"])): item for item in xyd_objects}

    differences = []
    for tag, object_id in sorted(set(d5000_by_key) & set(xyd_by_key)):
        d5000_attrs = d5000_by_key[(tag, object_id)]["attrs"]
        xyd_attrs = xyd_by_key[(tag, object_id)]["attrs"]
        if not isinstance(d5000_attrs, dict) or not isinstance(xyd_attrs, dict):
            continue

        label = object_label(tag, d5000_attrs, object_id)
        for attr in sorted(set(d5000_attrs) | set(xyd_attrs)):
            category_reason = classify_field_difference(
                tag,
                attr,
                d5000_attrs.get(attr),
                xyd_attrs.get(attr),
                tolerance,
            )
            if category_reason is None:
                continue
            category, reason = category_reason
            differences.append(
                {
                    "category": category,
                    "tag": tag,
                    "object_id": object_id,
                    "label": label,
                    "attribute": attr,
                    "d5000_value": display_attr_value(d5000_attrs.get(attr)),
                    "xyd_value": display_attr_value(xyd_attrs.get(attr)),
                    "reason": reason,
                }
            )

    category_counts = Counter(str(item["category"]) for item in differences)
    return {
        "differences": differences,
        "summary": {
            "total": len(differences),
            "attention": category_counts.get("需关注", 0),
            "confirm": category_counts.get("需确认", 0),
            "explained": category_counts.get("规则内差异", 0),
            "new_gen_only": category_counts.get("6.0独有", 0),
        },
    }


def build_rule_analysis(d5000_path: Path, xyd_path: Path, tolerance: float) -> dict[str, object]:
    d5000_root = parse_xml_root(d5000_path)
    xyd_root = parse_xml_root(xyd_path)
    d5000_objects = collect_all_objects(d5000_root)
    xyd_objects = collect_all_objects(xyd_root)
    return {
        "root_compare_rows": root_compare_rows(d5000_root.attrib, xyd_root.attrib),
        "new_gen_only_root_rows": new_gen_only_root_rows(xyd_root.attrib),
        "object_type_rows": object_type_overview_rows(d5000_objects, xyd_objects),
        "id_match_summary": id_match_summary(d5000_objects, xyd_objects),
        "field_diff_analysis": build_field_diff_analysis(d5000_path, xyd_path, tolerance),
    }


@dataclass(frozen=True)
class Device:
    source: str
    path: str
    station_name: str
    tag: str
    object_id: str
    key_names: tuple[str, ...]
    key_ids: tuple[str, ...]
    rt_key_ids: tuple[str, ...]
    text_value: str
    devref: str
    devref_base: str
    label: str
    coords: dict[str, float]
    center: tuple[float, float] | None

    @property
    def key_name_signature(self) -> str:
        return normalize_signature(self.key_names)

    @property
    def key_id_signature(self) -> str:
        return normalize_signature(self.key_ids)

    @property
    def label_signature(self) -> str:
        return normalize_text(self.label)

    def compact(self) -> dict[str, object]:
        return {
            "source": self.source,
            "path": self.path,
            "station_name": self.station_name,
            "tag": self.tag,
            "object_id": self.object_id,
            "key_names": list(self.key_names),
            "key_ids": list(self.key_ids),
            "rt_key_ids": list(self.rt_key_ids),
            "text_value": self.text_value,
            "devref": self.devref,
            "label": self.label,
            "coords": self.coords,
            "center": list(self.center) if self.center else None,
        }


def compute_center(tag: str, attrs: dict[str, str], coords: dict[str, float]) -> tuple[float, float] | None:
    x1 = coords.get("x1")
    x2 = coords.get("x2")
    y1 = coords.get("y1")
    y2 = coords.get("y2")
    if None not in (x1, x2, y1, y2):
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    points = parse_point_stream(attrs.get("d"))
    if points:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)

    x_val = coords.get("x")
    y_val = coords.get("y")
    if x_val is not None and y_val is not None:
        return (x_val, y_val)

    return None


def collect_signature_values(attrs: dict[str, str], prefix: str) -> list[str]:
    values = []
    direct = attrs.get(prefix)
    if direct not in (None, "", "0"):
        values.append(direct)
    index = 1
    while True:
        key = f"{prefix}{index}"
        if key not in attrs:
            break
        value = attrs.get(key)
        if value not in (None, "", "0"):
            values.append(value)
        index += 1
    return values


def parse_objects(path: Path, source: str, *, include_tags: set[str] | None = None, ignored_tags: set[str] | None = None) -> tuple[str, list[Device]]:
    root = parse_xml_root(path)
    station_name = root.attrib.get("facName", "").strip()
    devices: list[Device] = []

    for elem in root.iter():
        if include_tags is not None and elem.tag not in include_tags:
            continue
        if ignored_tags is not None and elem.tag in ignored_tags:
            continue
        object_id = elem.attrib.get("id")
        if not object_id:
            continue

        coords = {
            attr: value
            for attr, raw in ((name, parse_float(elem.attrib.get(name))) for name in COORD_ATTRS)
            if raw is not None
            for value in (raw,)
        }
        key_names = tuple(collect_signature_values(elem.attrib, "key_name"))
        key_ids = tuple(collect_signature_values(elem.attrib, "keyid"))
        rt_key_ids = tuple(collect_signature_values(elem.attrib, "rtkeyid"))
        text_value = elem.attrib.get("ts", "")
        devref = elem.attrib.get("devref", "")
        label = label_from_parts(elem.tag, list(key_names), text_value, devref, object_id)
        devices.append(
            Device(
                source=source,
                path=str(path),
                station_name=station_name,
                tag=elem.tag,
                object_id=object_id,
                key_names=key_names,
                key_ids=key_ids,
                rt_key_ids=rt_key_ids,
                text_value=text_value,
                devref=devref,
                devref_base=basename_devref(devref),
                label=label,
                coords=coords,
                center=compute_center(elem.tag, elem.attrib, coords),
            )
        )

    return station_name, devices


def parse_devices(path: Path, source: str) -> tuple[str, list[Device]]:
    return parse_objects(path, source, ignored_tags=IGNORED_TAGS)


def parse_dtexts(path: Path, source: str) -> tuple[str, list[Device]]:
    return parse_objects(path, source, include_tags={"DText"})


def center_distance(left: Device, right: Device) -> float | None:
    if left.center is None or right.center is None:
        return None
    dx = left.center[0] - right.center[0]
    dy = left.center[1] - right.center[1]
    return math.sqrt(dx * dx + dy * dy)


def coordinate_deltas(left: Device, right: Device, tolerance: float) -> tuple[dict[str, float], bool]:
    deltas = {}
    for attr in COORD_ATTRS:
        if attr in left.coords and attr in right.coords:
            deltas[attr] = abs(left.coords[attr] - right.coords[attr])
    distance = center_distance(left, right)
    if distance is not None:
        deltas["center_distance"] = distance
    coordinate_ok = all(value <= tolerance for value in deltas.values())
    return deltas, coordinate_ok


def build_exact_index(devices: Iterable[Device], signature_name: str) -> dict[tuple[str, str], list[Device]]:
    index: dict[tuple[str, str], list[Device]] = defaultdict(list)
    for device in devices:
        signature = getattr(device, signature_name)
        if signature:
            index[(device.tag, signature)].append(device)
    return index


def candidate_score(left: Device, right: Device) -> tuple[int, list[str]]:
    if left.tag != right.tag:
        return -1, []

    score = 0
    evidence: list[str] = []

    if left.key_id_signature and left.key_id_signature == right.key_id_signature:
        score += 950
        evidence.append("same_keyid")
    if left.key_name_signature and left.key_name_signature == right.key_name_signature:
        score += 900
        evidence.append("same_key_name")
    if left.label_signature and left.label_signature == right.label_signature:
        score += 240
        evidence.append("same_label")
    if left.devref_base and left.devref_base == right.devref_base:
        score += 120
        evidence.append("same_devref")
    if left.object_id == right.object_id:
        score += 30
        evidence.append("same_object_id")

    distance = center_distance(left, right)
    if distance is not None:
        if distance <= 0.001:
            score += 60
            evidence.append("same_position")
        elif distance <= 5:
            score += 30
            evidence.append("near_position")
        elif distance <= 50:
            score += 10
            evidence.append("rough_position")

    return score, evidence


def make_match_record(level: str, left: Device, right: Device, tolerance: float, evidence: list[str], score: int) -> dict[str, object]:
    deltas, coordinate_ok = coordinate_deltas(left, right, tolerance)
    return {
        "match_level": level,
        "tag": left.tag,
        "score": score,
        "evidence": evidence,
        "coordinate_ok": coordinate_ok,
        "coordinate_deltas": deltas,
        "d5000": left.compact(),
        "xyd": right.compact(),
    }


def compare_devices(d5000_devices: list[Device], xyd_devices: list[Device], tolerance: float) -> dict[str, object]:
    unmatched_left = {(device.tag, device.object_id): device for device in d5000_devices}
    unmatched_right = {(device.tag, device.object_id): device for device in xyd_devices}
    strong_matches: list[dict[str, object]] = []
    weak_matches: list[dict[str, object]] = []

    for object_key in sorted(set(unmatched_left) & set(unmatched_right)):
        left = unmatched_left[object_key]
        right = unmatched_right[object_key]
        score, evidence = candidate_score(left, right)
        strong_matches.append(make_match_record("strong", left, right, tolerance, evidence or ["same_object_id"], max(score, 1000)))
        unmatched_left.pop(object_key, None)
        unmatched_right.pop(object_key, None)

    coordinate_anomalies = [match for match in strong_matches + weak_matches if not match["coordinate_ok"]]

    return {
        "strong_match": sorted(strong_matches, key=lambda item: (item["tag"], item["d5000"]["label"])),
        "weak_match": sorted(weak_matches, key=lambda item: (item["tag"], item["d5000"]["label"])),
        "unmatched_d5000": [device.compact() for device in sorted(unmatched_left.values(), key=lambda item: (item.tag, item.label))],
        "unmatched_xyd": [device.compact() for device in sorted(unmatched_right.values(), key=lambda item: (item.tag, item.label))],
        "coordinate_anomaly": sorted(coordinate_anomalies, key=lambda item: (item["tag"], item["d5000"]["label"])),
    }


def render_match_line(match: dict[str, object]) -> str:
    left = match["d5000"]
    right = match["xyd"]
    evidence = ",".join(match["evidence"]) or "none"
    deltas = match["coordinate_deltas"]
    center_distance = deltas.get("center_distance")
    center_text = f"{center_distance:.6f}" if center_distance is not None else "n/a"
    return (
        f"- [{match['tag']}] {left['label']} | D5000 id={left['object_id']} "
        f"<-> 新一代 id={right['object_id']} | score={match['score']} | "
        f"evidence={evidence} | coordinate_ok={match['coordinate_ok']} | center_distance={center_text}"
    )


def render_device_line(device: dict[str, object], source_name: str) -> str:
    key_name = ", ".join(device["key_names"]) if device["key_names"] else "-"
    key_id = ", ".join(device["key_ids"]) if device["key_ids"] else "-"
    return (
        f"- [{device['tag']}] {device['label']} | {source_name} id={device['object_id']} | "
        f"key_name={key_name} | key_id={key_id}"
    )


def markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    def cell(value: object) -> str:
        text = str(value).replace("\n", "<br>")
        return text.replace("|", "\\|")

    lines = [
        "| " + " | ".join(cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell(item) for item in row) + " |")
    return lines


def evidence_text(evidence: list[str]) -> str:
    if not evidence:
        return "-"
    return "、".join(EVIDENCE_LABELS.get(item, item) for item in evidence)


def device_cell(device: dict[str, object]) -> str:
    return f"{device['label']}（id={device['object_id']}）"


def list_text(values: object) -> str:
    if not values:
        return "-"
    if isinstance(values, list):
        return "；".join(str(item) for item in values) or "-"
    return str(values)


def center_text(device: dict[str, object]) -> str:
    center = device.get("center")
    if not center:
        return "-"
    return f"({float(center[0]):.6f}, {float(center[1]):.6f})"


def coords_text(device: dict[str, object]) -> str:
    coords = device.get("coords") or {}
    if not isinstance(coords, dict) or not coords:
        return "-"
    display_coords = {key: value for key, value in coords.items() if key not in {"w", "h"}}
    if not display_coords:
        display_coords = coords
    return "；".join(f"{key}={float(value):.6f}" for key, value in sorted(display_coords.items()))


def delta_text(match: dict[str, object]) -> str:
    deltas = match.get("coordinate_deltas") or {}
    if not isinstance(deltas, dict) or not deltas:
        return "-"
    return "；".join(f"{key}={float(value):.6f}" for key, value in sorted(deltas.items()))


def device_detail_rows(devices: list[dict[str, object]], source_name: str) -> list[list[str]]:
    return [
        [
            str(device["tag"]),
            str(device["label"]),
            str(device["object_id"]),
            list_text(device.get("key_names")),
            list_text(device.get("key_ids")),
            str(device.get("devref") or "-"),
            center_text(device),
            coords_text(device),
        ]
        for device in devices
    ]


def match_detail_rows(matches: list[dict[str, object]]) -> list[list[str]]:
    rows = []
    for match in matches:
        left = match["d5000"]
        right = match["xyd"]
        rows.append(
            [
                str(match["tag"]),
                device_cell(left),
                list_text(left.get("key_names")),
                list_text(left.get("key_ids")),
                center_text(left),
                device_cell(right),
                list_text(right.get("key_names")),
                list_text(right.get("key_ids")),
                center_text(right),
                str(match["score"]),
                evidence_text(match["evidence"]),
                "正常" if match["coordinate_ok"] else "异常",
                delta_text(match),
            ]
        )
    return rows


def coordinate_check_text(match: dict[str, object]) -> str:
    if match["coordinate_ok"]:
        return "正常"
    deltas = match["coordinate_deltas"]
    center_distance = deltas.get("center_distance")
    if center_distance is not None:
        return f"异常，中心点差值 {center_distance:.6f}"
    return "异常"


def issue_rows(result: dict[str, object]) -> list[list[str]]:
    rows: list[list[str]] = []

    for match in result["weak_match"]:
        rows.append(
            [
                "疑似对应",
                str(match["tag"]),
                device_cell(match["d5000"]),
                device_cell(match["xyd"]),
                coordinate_check_text(match),
                evidence_text(match["evidence"]),
                "匹配依据不足，建议人工确认",
            ]
        )

    for match in result["coordinate_anomaly"]:
        rows.append(
            [
                "坐标异常",
                str(match["tag"]),
                device_cell(match["d5000"]),
                device_cell(match["xyd"]),
                coordinate_check_text(match),
                evidence_text(match["evidence"]),
                "设备已匹配，但坐标超出阈值",
            ]
        )

    for device in result["unmatched_d5000"]:
        rows.append(
            [
                "D5000有设备，新一代未找到对应项",
                str(device["tag"]),
                device_cell(device),
                "-",
                "-",
                "未找到可接受的新一代候选设备",
                "建议检查设备命名、类型或图元缺失",
            ]
        )

    for device in result["unmatched_xyd"]:
        rows.append(
            [
                "新一代有设备，D5000未找到对应项",
                str(device["tag"]),
                "-",
                device_cell(device),
                "-",
                "未找到可接受的D5000候选设备",
                "建议检查设备命名、类型或图元新增",
            ]
        )

    return rows


def append_match_detail(lines: list[str], match: dict[str, object], index: int) -> None:
    left = match["d5000"]
    right = match["xyd"]
    lines.append(f"{index}. {match['tag']}：{device_cell(left)}  <->  {device_cell(right)}")
    lines.append(f"   坐标检查：{coordinate_check_text(match)}")
    lines.append(f"   坐标差值：{delta_text(match)}")
    lines.append(f"   判断依据：{evidence_text(match['evidence'])}")
    if left.get("key_names") or right.get("key_names"):
        lines.append(f"   key_name：D5000={list_text(left.get('key_names'))}；新一代={list_text(right.get('key_names'))}")
    if left.get("key_ids") or right.get("key_ids"):
        lines.append(f"   keyid：D5000={list_text(left.get('key_ids'))}；新一代={list_text(right.get('key_ids'))}")


def append_difference_records(lines: list[str], records: list[dict[str, object]], limit: int | None = None) -> None:
    selected = records if limit is None else records[:limit]
    for index, item in enumerate(selected, start=1):
        lines.append(
            f"{index}. {item['tag']}：{item['label']}（id={item['object_id']}）"
        )
        lines.append(f"   字段：{item['attribute']}")
        lines.append(f"   D5000：{item['d5000_value']}")
        lines.append(f"   6.0：{item['xyd_value']}")
        lines.append(f"   说明：{item['reason']}")
    if limit is not None and len(records) > limit:
        lines.append(f"其余 {len(records) - limit} 条未在报告正文展开，完整明细见 result.json 的 rule_analysis.field_diff_analysis.differences。")


def append_grouped_difference_summary(lines: list[str], records: list[dict[str, object]], limit_per_group: int = 5) -> None:
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for item in records:
        groups[(str(item["tag"]), str(item["attribute"]), str(item["reason"]))].append(item)

    for group_index, ((tag, attr, reason), items) in enumerate(sorted(groups.items()), start=1):
        if attr == "lc":
            title = f"{tag} 的 lc颜色映射"
        elif attr.startswith("voltype"):
            title = f"{tag} 的 {attr}编码"
        else:
            title = f"{tag} 的 {attr}"
        lines.append(f"{group_index}. {title}：{len(items)} 项")
        lines.append(f"   说明：{reason}")
        for item in items[:limit_per_group]:
            lines.append(
                f"   - {item['label']}（id={item['object_id']}）：D5000={item['d5000_value']}；6.0={item['xyd_value']}"
            )
        if len(items) > limit_per_group:
            lines.append(f"   - 其余 {len(items) - limit_per_group} 项见 result.json。")


def append_new_gen_only_summary(lines: list[str], records: list[dict[str, object]]) -> None:
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for item in records:
        groups[str(item["tag"])][str(item["attribute"])] += 1

    for tag in sorted(groups):
        attr_parts = [f"{attr}({count})" for attr, count in sorted(groups[tag].items())]
        lines.append(f"- {tag}：{'; '.join(attr_parts)}")


def mapped_matches_from(comparison: dict[str, object]) -> list[dict[str, object]]:
    matches = list(comparison["strong_match"]) + list(comparison["weak_match"])
    return sorted(matches, key=lambda item: (str(item["tag"]), str(item["d5000"]["label"])))


def mapped_matches(result: dict[str, object]) -> list[dict[str, object]]:
    return mapped_matches_from(result)


def comparison_name(device: dict[str, object]) -> str:
    key_names = device.get("key_names")
    if isinstance(key_names, list) and key_names:
        return "；".join(str(item) for item in key_names)
    return str(device.get("label") or "")


def names_equal(left: dict[str, object], right: dict[str, object]) -> bool:
    left_names = left.get("key_names")
    right_names = right.get("key_names")
    if isinstance(left_names, list) and isinstance(right_names, list) and (left_names or right_names):
        return normalize_signature(str(item) for item in left_names) == normalize_signature(str(item) for item in right_names)
    return normalize_text(str(left.get("label") or "")) == normalize_text(str(right.get("label") or ""))


def name_anomaly_matches(result: dict[str, object]) -> list[dict[str, object]]:
    return [match for match in mapped_matches(result) if not names_equal(match["d5000"], match["xyd"])]


def key_ids_signature(device: dict[str, object]) -> str:
    values = device.get("key_ids")
    if not isinstance(values, list):
        return ""
    return normalize_signature(str(item) for item in values)


def has_key_ids(device: dict[str, object]) -> bool:
    return bool(key_ids_signature(device))


def rt_key_ids_text(device: dict[str, object]) -> str:
    return list_text(device.get("rt_key_ids"))


def keyid_issue_matches(matches: list[dict[str, object]]) -> list[dict[str, object]]:
    issues = []
    for match in matches:
        left = match["d5000"]
        right = match["xyd"]
        if not has_key_ids(left):
            continue
        if not has_key_ids(right) or key_ids_signature(left) != key_ids_signature(right):
            issues.append(match)
    return issues


def rtkeyid_missing_matches(matches: list[dict[str, object]]) -> list[dict[str, object]]:
    issues = []
    for match in matches:
        left = match["d5000"]
        right = match["xyd"]
        if has_key_ids(left) and not right.get("rt_key_ids"):
            issues.append(match)
    return issues


def count_d5000_keyed(matches: list[dict[str, object]]) -> int:
    return sum(1 for match in matches if has_key_ids(match["d5000"]))


def append_object_list(
    lines: list[str],
    devices: list[dict[str, object]],
    source_name: str,
    object_name: str,
    limit: int | None = None,
) -> None:
    if not devices:
        lines.append(f"{source_name}独有{object_name}：无")
        return
    lines.append(f"{source_name}独有{object_name}：{len(devices)} 项")
    selected = devices if limit is None else devices[:limit]
    for index, device in enumerate(selected, start=1):
        lines.append(f"{index}. {device['tag']}：{device_cell(device)}")
        lines.append(f"   名称：{comparison_name(device) or '-'}")
        lines.append(f"   keyid：{list_text(device.get('key_ids'))}")
        if device.get("rt_key_ids"):
            lines.append(f"   rtkeyid：{rt_key_ids_text(device)}")
        lines.append(f"   坐标：{coords_text(device)}")
    if limit is not None and len(devices) > limit:
        lines.append(f"其余 {len(devices) - limit} 项见 result.json。")


def append_device_list(lines: list[str], devices: list[dict[str, object]], source_name: str, limit: int | None = None) -> None:
    append_object_list(lines, devices, source_name, "设备", limit)


def append_name_anomalies(lines: list[str], matches: list[dict[str, object]], *, show_heading: bool = True) -> None:
    if not matches:
        if show_heading:
            lines.append("名称不一致：0")
        return
    if show_heading:
        lines.append(f"名称不一致：{len(matches)} 项")
    for index, match in enumerate(matches, start=1):
        left = match["d5000"]
        right = match["xyd"]
        lines.append(f"{index}. {match['tag']}：id={left['object_id']}")
        lines.append(f"   D5000名称：{comparison_name(left) or '-'}")
        lines.append(f"   6.0名称：{comparison_name(right) or '-'}")


def append_keyid_anomalies(lines: list[str], matches: list[dict[str, object]], object_name: str) -> None:
    label = "DText keyid" if object_name == "DText" else f"{object_name}keyid"
    if not matches:
        lines.append(f"{label}缺失或不一致：0")
        return
    lines.append(f"{label}缺失或不一致：{len(matches)} 项")
    for index, match in enumerate(matches, start=1):
        left = match["d5000"]
        right = match["xyd"]
        lines.append(f"{index}. {match['tag']}：id={left['object_id']}")
        lines.append(f"   名称：{comparison_name(left) or comparison_name(right) or '-'}")
        lines.append(f"   D5000 keyid：{list_text(left.get('key_ids'))}")
        lines.append(f"   6.0 keyid：{list_text(right.get('key_ids'))}")
        if not has_key_ids(right):
            lines.append(f"   问题说明：D5000已关联keyid，但6.0未关联keyid。")
        else:
            lines.append(f"   问题说明：D5000和6.0都有关联keyid，但值不一致。")


def append_rtkeyid_missing(lines: list[str], matches: list[dict[str, object]], limit: int | None = 50) -> None:
    if not matches:
        lines.append("DText缺少rtkeyid：0")
        return
    lines.append(f"DText缺少rtkeyid：{len(matches)} 项")
    selected = matches if limit is None else matches[:limit]
    for index, match in enumerate(selected, start=1):
        left = match["d5000"]
        right = match["xyd"]
        lines.append(f"{index}. DText：id={left['object_id']}")
        lines.append(f"   D5000名称：{comparison_name(left) or '-'}")
        lines.append(f"   6.0名称：{comparison_name(right) or '-'}")
        lines.append(f"   D5000 keyid：{list_text(left.get('key_ids'))}")
        lines.append(f"   6.0 keyid：{list_text(right.get('key_ids'))}")
        lines.append(f"   6.0 rtkeyid：{rt_key_ids_text(right)}")
        lines.append(f"   D5000坐标：{coords_text(left)}")
        lines.append(f"   6.0坐标：{coords_text(right)}")
        if has_key_ids(right) and key_ids_signature(left) == key_ids_signature(right):
            lines.append("   问题说明：D5000已关联keyid，6.0也保留了相同keyid，但6.0缺少rtkeyid；需确认该量测显示点是否应补充实时库标识。")
        elif not has_key_ids(right):
            lines.append("   问题说明：D5000已关联keyid，但6.0缺少keyid和rtkeyid；需确认迁移是否漏绑。")
        else:
            lines.append("   问题说明：D5000与6.0 keyid不一致，且6.0缺少rtkeyid；需优先确认量测绑定关系。")
    if limit is not None and len(matches) > limit:
        lines.append(f"其余 {len(matches) - limit} 项见 result.json。")


def append_coordinate_anomalies(lines: list[str], matches: list[dict[str, object]]) -> None:
    if not matches:
        lines.append("坐标不一致：0")
        return
    lines.append(f"坐标不一致：{len(matches)} 项")
    for index, match in enumerate(matches, start=1):
        left = match["d5000"]
        right = match["xyd"]
        lines.append(f"{index}. {match['tag']}：{device_cell(left)}")
        lines.append(f"   D5000坐标：{coords_text(left)}")
        lines.append(f"   6.0坐标：{coords_text(right)}")
        lines.append(f"   差值：{delta_text(match)}")


def text_width(value: object) -> int:
    width = 0
    for char in str(value):
        if unicodedata.combining(char):
            continue
        east_asian_width = unicodedata.east_asian_width(char)
        width += 2 if east_asian_width in {"F", "W"} else 1
    return width


def truncate_width(value: object, max_width: int) -> str:
    text = str(value)
    if text_width(text) <= max_width:
        return text
    result = []
    width = 0
    for char in text:
        char_width = 2 if ord(char) >= 0x1100 else 1
        if width + char_width > max_width - 2:
            break
        result.append(char)
        width += char_width
    return "".join(result) + ".."


def pad_width(value: object, width: int) -> str:
    text = str(value)
    return text + " " * max(width - text_width(text), 0)


def wrap_width(value: object, max_width: int) -> list[str]:
    text = str(value)
    if not text:
        return [""]
    lines: list[str] = []
    current: list[str] = []
    current_width = 0
    for char in text:
        char_width = 2 if ord(char) >= 0x1100 else 1
        if current and current_width + char_width > max_width:
            lines.append("".join(current))
            current = [char]
            current_width = char_width
        else:
            current.append(char)
            current_width += char_width
    if current:
        lines.append("".join(current))
    return lines or [""]


def plain_table(headers: list[str], rows: list[list[object]], max_widths: list[int] | None = None) -> list[str]:
    prepared_rows = [[str(cell) for cell in row] for row in rows]
    column_count = len(headers)
    if max_widths is None:
        max_widths = [0] * column_count
    normalized_rows = [
        [row[index] if index < len(row) else "" for index in range(column_count)]
        for row in prepared_rows
    ]
    widths = []
    for index in range(column_count):
        values = [str(headers[index])] + [row[index] for row in normalized_rows]
        widths.append(max([max_widths[index], *(text_width(value) for value in values)]))

    gap = "      "
    lines = [gap.join(pad_width(str(headers[index]), widths[index]) for index in range(column_count))]
    lines.append(gap.join("-" * widths[index] for index in range(column_count)))
    for row in normalized_rows:
        lines.append(gap.join(pad_width(row[index], widths[index]) for index in range(column_count)))
    return lines


def first_key_name(device: dict[str, object]) -> str:
    return comparison_name(device) or str(device.get("label") or "-")


def short_file_name(path_value: object) -> str:
    return Path(str(path_value)).name


def short_detail(value: object, max_width: int = 90) -> str:
    return truncate_width(value, max_width)


def related_type_for_device(device: dict[str, object] | None) -> str:
    if not isinstance(device, dict):
        return "-"
    tag = str(device.get("tag") or "")
    if tag != "DText":
        return tag or "-"

    name = first_key_name(device)
    if "母线" in name:
        return "母线量测"
    if "主变" in name or "变压器" in name:
        return "主变量测"
    if "开关" in name or "断路器" in name:
        return "断路器量测"
    if "接地" in name and ("刀闸" in name or "闸刀" in name):
        return "接地刀闸量测"
    if "刀闸" in name or "闸刀" in name:
        return "刀闸量测"
    if "集电线" in name or "线路" in name or re.search(r"\d+[A-Z]?\d*线", name):
        return "线路量测"
    if "储能" in name or "SOC" in name:
        return "储能遥测"
    if "光伏" in name or "逆变器" in name:
        return "光伏量测"
    if "发电机" in name:
        return "发电机量测"

    rt_values = device.get("rt_key_ids")
    if isinstance(rt_values, list):
        for value in rt_values:
            prefix = str(value).split(":", 1)[0]
            if prefix in RTKEYID_PREFIX_LABELS:
                return RTKEYID_PREFIX_LABELS[prefix]

    return "量测显示"


def issue_related_type(issue: dict[str, object]) -> str:
    d5000 = issue.get("d5000")
    xyd = issue.get("xyd")
    if isinstance(xyd, dict):
        value = related_type_for_device(xyd)
        if value != "量测显示":
            return value
    if isinstance(d5000, dict):
        return related_type_for_device(d5000)
    return "-"


def issue_object_name(match_or_device: dict[str, object], source: str = "d5000") -> str:
    if "d5000" in match_or_device:
        device = match_or_device[source]
    else:
        device = match_or_device
    return first_key_name(device)


def movement_text(match: dict[str, object], tolerance: float) -> str:
    left = match["d5000"]
    right = match["xyd"]
    left_coords = left.get("coords") or {}
    right_coords = right.get("coords") or {}
    parts = []
    left_x = left_coords.get("x")
    right_x = right_coords.get("x")
    if left_x is not None and right_x is not None:
        delta_x = float(right_x) - float(left_x)
        if abs(delta_x) > tolerance:
            parts.append(f"6.0显示位置{'右移' if delta_x > 0 else '左移'}{abs(delta_x):.6f}")
    left_y = left_coords.get("y")
    right_y = right_coords.get("y")
    if left_y is not None and right_y is not None:
        delta_y = float(right_y) - float(left_y)
        if abs(delta_y) > tolerance:
            parts.append(f"6.0显示位置{'下移' if delta_y > 0 else '上移'}{abs(delta_y):.6f}")
    if parts:
        return "；".join(parts)
    return f"坐标差值：{delta_text(match)}"


def make_issue(
    object_type: str,
    object_id: str,
    problem_type: str,
    detail: str,
    d5000: dict[str, object] | None = None,
    xyd: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "object_type": object_type,
        "object_id": object_id,
        "problem_type": problem_type,
        "detail": detail,
        "d5000": d5000,
        "xyd": xyd,
    }


def build_report_issues(
    result: dict[str, object],
    mapped: list[dict[str, object]],
    dtext_mapped: list[dict[str, object]],
    name_anomalies: list[dict[str, object]],
    coordinate_anomalies: list[dict[str, object]],
    device_keyid_issues: list[dict[str, object]],
    dtext_name_anomalies: list[dict[str, object]],
    dtext_coordinate_anomalies: list[dict[str, object]],
    dtext_keyid_issues: list[dict[str, object]],
    dtext_rtkeyid_missing: list[dict[str, object]],
) -> list[dict[str, object]]:
    tolerance = float(result["metadata"]["coordinate_tolerance"])
    issues: list[dict[str, object]] = []

    for device in result["unmatched_d5000"]:
        detail = f"D5000有，6.0没有；名称={first_key_name(device)}；keyid={list_text(device.get('key_ids'))}；坐标={coords_text(device)}"
        issues.append(make_issue(str(device["tag"]), str(device["object_id"]), "6.0缺少设备", detail, d5000=device))
    for device in result["unmatched_xyd"]:
        detail = f"6.0有，D5000没有；名称={first_key_name(device)}；keyid={list_text(device.get('key_ids'))}；坐标={coords_text(device)}"
        issues.append(make_issue(str(device["tag"]), str(device["object_id"]), "D5000缺少设备", detail, xyd=device))

    for match in device_keyid_issues:
        left = match["d5000"]
        right = match["xyd"]
        if not has_key_ids(right):
            detail = "D5000有keyid，6.0 keyid为空"
        else:
            detail = f"D5000 keyid={list_text(left.get('key_ids'))}；6.0 keyid={list_text(right.get('key_ids'))}"
        issues.append(make_issue(str(match["tag"]), str(left["object_id"]), "设备keyid不对", detail, left, right))

    for match in name_anomalies:
        left = match["d5000"]
        right = match["xyd"]
        detail = f"D5000名称={comparison_name(left) or '-'}；6.0名称={comparison_name(right) or '-'}"
        issues.append(make_issue(str(match["tag"]), str(left["object_id"]), "设备名称不一致", detail, left, right))

    for match in coordinate_anomalies:
        left = match["d5000"]
        right = match["xyd"]
        detail = f"{movement_text(match, tolerance)}；D5000坐标={coords_text(left)}；6.0坐标={coords_text(right)}"
        issues.append(make_issue(str(match["tag"]), str(left["object_id"]), "设备坐标不一致", detail, left, right))

    dtext_comparison = result["dtext_comparison"]
    for device in dtext_comparison["unmatched_d5000"]:
        detail = f"D5000有，6.0没有；名称={first_key_name(device)}；keyid={list_text(device.get('key_ids'))}；坐标={coords_text(device)}"
        issues.append(make_issue("DText", str(device["object_id"]), "6.0缺少DText", detail, d5000=device))
    for device in dtext_comparison["unmatched_xyd"]:
        detail = f"6.0有，D5000没有；名称={first_key_name(device)}；keyid={list_text(device.get('key_ids'))}；坐标={coords_text(device)}"
        issues.append(make_issue("DText", str(device["object_id"]), "D5000缺少DText", detail, xyd=device))

    for match in dtext_keyid_issues:
        left = match["d5000"]
        right = match["xyd"]
        if not has_key_ids(right):
            detail = "D5000有keyid，6.0 keyid为空"
        else:
            detail = f"D5000 keyid={list_text(left.get('key_ids'))}；6.0 keyid={list_text(right.get('key_ids'))}"
        issues.append(make_issue("DText", str(left["object_id"]), "DText keyid不对", detail, left, right))

    for match in dtext_rtkeyid_missing:
        left = match["d5000"]
        right = match["xyd"]
        detail = f"D5000和6.0 keyid一致；keyid={list_text(left.get('key_ids'))}；6.0实时库ID为空"
        issues.append(make_issue("DText", str(left["object_id"]), "DText缺少实时库ID", detail, left, right))

    for match in dtext_name_anomalies:
        left = match["d5000"]
        right = match["xyd"]
        detail = f"D5000名称={comparison_name(left) or '-'}；6.0名称={comparison_name(right) or '-'}"
        issues.append(make_issue("DText", str(left["object_id"]), "DText名称不一致", detail, left, right))

    for match in dtext_coordinate_anomalies:
        left = match["d5000"]
        right = match["xyd"]
        detail = f"{movement_text(match, tolerance)}；D5000坐标={coords_text(left)}；6.0坐标={coords_text(right)}"
        issues.append(make_issue("DText", str(left["object_id"]), "DText坐标不一致", detail, left, right))

    return issues


def append_issue_details(lines: list[str], issues: list[dict[str, object]]) -> None:
    if not issues:
        lines.append("无需要展开的问题。")
        return
    for index, issue in enumerate(issues, start=1):
        lines.append(f"问题 {index}：{issue['problem_type']}")
        lines.append(f"对象类型：{issue['object_type']}")
        lines.append(f"对象id：{issue['object_id']}")
        lines.append(f"明细：{issue['detail']}")
        d5000 = issue.get("d5000")
        xyd = issue.get("xyd")
        if isinstance(d5000, dict):
            lines.append("D5000：")
            lines.append(f"  名称：{first_key_name(d5000)}")
            lines.append(f"  keyid：{list_text(d5000.get('key_ids'))}")
            lines.append(f"  坐标：{coords_text(d5000)}")
        if isinstance(xyd, dict):
            lines.append("6.0：")
            lines.append(f"  名称：{first_key_name(xyd)}")
            lines.append(f"  keyid：{list_text(xyd.get('key_ids'))}")
            if xyd.get("rt_key_ids"):
                lines.append(f"  rtkeyid：{rt_key_ids_text(xyd)}")
            elif issue["object_type"] == "DText" or "rtkeyid" in str(issue["problem_type"]):
                lines.append("  rtkeyid：-")
            lines.append(f"  坐标：{coords_text(xyd)}")
        lines.append("")


def render_text_report(result: dict[str, object]) -> str:
    lines = []
    meta = result["metadata"]
    counts = result["summary_counts"]
    mapped = mapped_matches(result)
    dtext_comparison = result["dtext_comparison"]
    dtext_mapped = mapped_matches_from(dtext_comparison)
    name_anomalies = name_anomaly_matches(result)
    device_keyid_issues = keyid_issue_matches(mapped)
    dtext_name_anomalies = [match for match in dtext_mapped if not names_equal(match["d5000"], match["xyd"])]
    dtext_keyid_issues = keyid_issue_matches(dtext_mapped)
    dtext_rtkeyid_missing = rtkeyid_missing_matches(dtext_mapped)
    coordinate_anomalies = result["coordinate_anomaly"]
    dtext_coordinate_anomalies = dtext_comparison["coordinate_anomaly"]
    issues = build_report_issues(
        result,
        mapped,
        dtext_mapped,
        name_anomalies,
        coordinate_anomalies,
        device_keyid_issues,
        dtext_name_anomalies,
        dtext_coordinate_anomalies,
        dtext_keyid_issues,
        dtext_rtkeyid_missing,
    )

    lines.append("G文件对比结果")
    lines.append("=" * 28)
    lines.append("")
    lines.append("一、对比结果")
    lines.append(f"D5000文件：{short_file_name(meta['d5000_file'])}")
    lines.append(f"6.0文件：{short_file_name(meta['xyd_file'])}")
    lines.append(f"D5000厂站：{meta['d5000_station_name'] or '未识别'}")
    lines.append(f"6.0厂站：{meta['xyd_station_name'] or '未识别'}")
    lines.append(f"坐标容差：{meta['coordinate_tolerance']}")
    lines.append(f"设备ID映射：已映射 {len(mapped)} 项；D5000独有 {counts['unmatched_d5000']} 项；6.0独有 {counts['unmatched_xyd']} 项。")
    lines.append(f"DText映射：已映射 {len(dtext_mapped)} 项；D5000独有 {len(dtext_comparison['unmatched_d5000'])} 项；6.0独有 {len(dtext_comparison['unmatched_xyd'])} 项。")
    lines.append("")
    summary_rows = [
        ["设备是否缺失", "异常" if counts["unmatched_d5000"] or counts["unmatched_xyd"] else "正常", counts["unmatched_d5000"] + counts["unmatched_xyd"], f"两边都有的设备{len(mapped)}项"],
        ["设备是否关联keyid", "异常" if device_keyid_issues else "正常", len(device_keyid_issues), f"D5000有关联keyid的设备{count_d5000_keyed(mapped)}项"],
        ["设备名称", "异常" if name_anomalies else "正常", len(name_anomalies), "名称不一致"],
        ["设备坐标", "异常" if coordinate_anomalies else "正常", len(coordinate_anomalies), "设备显示位置偏移"],
        ["DText是否缺失", "异常" if dtext_comparison["unmatched_d5000"] or dtext_comparison["unmatched_xyd"] else "正常", len(dtext_comparison["unmatched_d5000"]) + len(dtext_comparison["unmatched_xyd"]), f"两边都有的DText{len(dtext_mapped)}项"],
        ["DText是否关联keyid", "异常" if dtext_keyid_issues else "正常", len(dtext_keyid_issues), f"D5000有关联keyid的DText{count_d5000_keyed(dtext_mapped)}项"],
        ["DText实时库ID", "异常" if dtext_rtkeyid_missing else "正常", len(dtext_rtkeyid_missing), f"缺少{len(dtext_rtkeyid_missing)}项"],
        ["DText名称", "提醒" if dtext_name_anomalies else "正常", len(dtext_name_anomalies), "多为6.0增加表名、厂站名或值"],
        ["DText坐标", "异常" if dtext_coordinate_anomalies else "正常", len(dtext_coordinate_anomalies), "量测显示位置偏移"],
    ]
    lines.extend(plain_table(["检查项", "结果", "数量", "明细"], summary_rows, [22, 8, 6, 42]))

    lines.append("")
    lines.append("二、检查范围")
    scope_rows = [
        ["设备对象", counts["d5000_devices"], counts["xyd_devices"], len(mapped), "参与ID、名称、坐标、keyid检查"],
        ["DText量测显示点", counts["d5000_dtexts"], counts["xyd_dtexts"], len(dtext_mapped), "参与ID、名称、坐标、keyid、rtkeyid检查"],
        ["其他图形对象", "-", "-", "-", "Text、ConnectLine、poke、Layer等不参与业务问题判断"],
    ]
    lines.extend(plain_table(["范围", "D5000", "6.0", "已映射", "明细"], scope_rows, [18, 8, 8, 8, 54]))

    lines.append("")
    lines.append("三、问题明细")
    if issues:
        issue_rows_for_table = [
            [index, issue["object_type"], issue_related_type(issue), issue["object_id"], issue["problem_type"], issue["detail"]]
            for index, issue in enumerate(issues, start=1)
        ]
        lines.extend(plain_table(["序号", "对象类型", "关联类型", "对象id", "问题类型", "明细"], issue_rows_for_table, [4, 10, 12, 12, 18, 96]))
    else:
        lines.append("无需要关注的问题。")

    return "\n".join(lines)


def html_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def html_table(headers: list[str], rows: list[list[object]], class_name: str = "") -> str:
    class_attr = f' class="{html_escape(class_name)}"' if class_name else ""
    parts = [f"<table{class_attr}>", "<thead><tr>"]
    for header in headers:
        parts.append(f"<th>{html_escape(header)}</th>")
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{html_escape(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def render_html_report(result: dict[str, object]) -> str:
    meta = result["metadata"]
    counts = result["summary_counts"]
    mapped = mapped_matches(result)
    dtext_comparison = result["dtext_comparison"]
    dtext_mapped = mapped_matches_from(dtext_comparison)
    name_anomalies = name_anomaly_matches(result)
    device_keyid_issues = keyid_issue_matches(mapped)
    dtext_name_anomalies = [match for match in dtext_mapped if not names_equal(match["d5000"], match["xyd"])]
    dtext_keyid_issues = keyid_issue_matches(dtext_mapped)
    dtext_rtkeyid_missing = rtkeyid_missing_matches(dtext_mapped)
    coordinate_anomalies = result["coordinate_anomaly"]
    dtext_coordinate_anomalies = dtext_comparison["coordinate_anomaly"]
    issues = build_report_issues(
        result,
        mapped,
        dtext_mapped,
        name_anomalies,
        coordinate_anomalies,
        device_keyid_issues,
        dtext_name_anomalies,
        dtext_coordinate_anomalies,
        dtext_keyid_issues,
        dtext_rtkeyid_missing,
    )
    summary_rows = [
        ["设备是否缺失", "异常" if counts["unmatched_d5000"] or counts["unmatched_xyd"] else "正常", counts["unmatched_d5000"] + counts["unmatched_xyd"], f"两边都有的设备{len(mapped)}项"],
        ["设备是否关联keyid", "异常" if device_keyid_issues else "正常", len(device_keyid_issues), f"D5000有关联keyid的设备{count_d5000_keyed(mapped)}项"],
        ["设备名称", "异常" if name_anomalies else "正常", len(name_anomalies), "名称不一致"],
        ["设备坐标", "异常" if coordinate_anomalies else "正常", len(coordinate_anomalies), "设备显示位置偏移"],
        ["DText是否缺失", "异常" if dtext_comparison["unmatched_d5000"] or dtext_comparison["unmatched_xyd"] else "正常", len(dtext_comparison["unmatched_d5000"]) + len(dtext_comparison["unmatched_xyd"]), f"两边都有的DText{len(dtext_mapped)}项"],
        ["DText是否关联keyid", "异常" if dtext_keyid_issues else "正常", len(dtext_keyid_issues), f"D5000有关联keyid的DText{count_d5000_keyed(dtext_mapped)}项"],
        ["DText实时库ID", "异常" if dtext_rtkeyid_missing else "正常", len(dtext_rtkeyid_missing), f"缺少{len(dtext_rtkeyid_missing)}项"],
        ["DText名称", "提醒" if dtext_name_anomalies else "正常", len(dtext_name_anomalies), "多为6.0增加表名、厂站名或值"],
        ["DText坐标", "异常" if dtext_coordinate_anomalies else "正常", len(dtext_coordinate_anomalies), "量测显示位置偏移"],
    ]
    scope_rows = [
        ["设备对象", counts["d5000_devices"], counts["xyd_devices"], len(mapped), "参与ID、名称、坐标、keyid检查"],
        ["DText量测显示点", counts["d5000_dtexts"], counts["xyd_dtexts"], len(dtext_mapped), "参与ID、名称、坐标、keyid、rtkeyid检查"],
        ["其他图形对象", "-", "-", "-", "Text、ConnectLine、poke、Layer等不参与业务问题判断"],
    ]
    issue_rows = [
        [index, issue["object_type"], issue_related_type(issue), issue["object_id"], issue["problem_type"], issue["detail"]]
        for index, issue in enumerate(issues, start=1)
    ]

    file_cards = [
        ("D5000文件", short_file_name(meta["d5000_file"])),
        ("6.0文件", short_file_name(meta["xyd_file"])),
        ("D5000厂站", meta["d5000_station_name"] or "未识别"),
        ("6.0厂站", meta["xyd_station_name"] or "未识别"),
        ("坐标容差", meta["coordinate_tolerance"]),
    ]
    file_card_html = "".join(
        f"<div class=\"meta-item\"><span>{html_escape(label)}</span><strong>{html_escape(value)}</strong></div>"
        for label, value in file_cards
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>G文件对比结果</title>
  <style>
    :root {{
      --bg: #f4f0e8;
      --ink: #1c1b18;
      --muted: #6d675c;
      --line: #d8cfbf;
      --panel: #fffaf0;
      --accent: #0f5f5c;
      --bad: #b42318;
      --warn: #9a5b00;
      --ok: #247145;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top left, #fff7df 0, transparent 34rem), var(--bg);
      color: var(--ink);
      font-family: "Microsoft YaHei", "Noto Sans CJK SC", "PingFang SC", sans-serif;
      line-height: 1.55;
    }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 32px; }}
    h1 {{ margin: 0 0 18px; font-size: 30px; letter-spacing: 0.04em; }}
    h2 {{ margin: 30px 0 12px; font-size: 20px; }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }}
    .meta-item {{
      background: rgba(255, 250, 240, 0.82);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
    }}
    .meta-item span {{ display: block; color: var(--muted); font-size: 12px; }}
    .meta-item strong {{ display: block; margin-top: 3px; font-size: 15px; }}
    .table-wrap {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 10px 28px rgba(50, 41, 24, 0.08);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 860px;
      font-size: 14px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      vertical-align: top;
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #efe5d1;
      color: #3b3428;
      font-weight: 700;
      z-index: 1;
    }}
    td:last-child, th:last-child {{
      white-space: normal;
      min-width: 460px;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    .summary td:nth-child(2) {{ font-weight: 700; }}
    .note {{ color: var(--muted); margin: 8px 0 0; font-size: 13px; }}
  </style>
</head>
<body>
<main>
  <h1>G文件对比结果</h1>
  <section>
    <h2>一、对比结果</h2>
    <div class="meta">{file_card_html}</div>
    <p class="note">设备ID映射：已映射 {len(mapped)} 项；D5000独有 {counts['unmatched_d5000']} 项；6.0独有 {counts['unmatched_xyd']} 项。DText映射：已映射 {len(dtext_mapped)} 项；D5000独有 {len(dtext_comparison['unmatched_d5000'])} 项；6.0独有 {len(dtext_comparison['unmatched_xyd'])} 项。</p>
    <div class="table-wrap">{html_table(["检查项", "结果", "数量", "明细"], summary_rows, "summary")}</div>
  </section>
  <section>
    <h2>二、检查范围</h2>
    <div class="table-wrap">{html_table(["范围", "D5000", "6.0", "已映射", "明细"], scope_rows)}</div>
  </section>
  <section>
    <h2>三、问题明细</h2>
    <div class="table-wrap">{html_table(["序号", "对象类型", "关联类型", "对象id", "问题类型", "明细"], issue_rows)}</div>
  </section>
</main>
</body>
</html>
"""


def build_result(d5000_path: Path, xyd_path: Path, tolerance: float) -> dict[str, object]:
    d5000_station, d5000_devices = parse_devices(d5000_path, "d5000")
    xyd_station, xyd_devices = parse_devices(xyd_path, "xyd")
    _, d5000_dtexts = parse_dtexts(d5000_path, "d5000")
    _, xyd_dtexts = parse_dtexts(xyd_path, "xyd")
    comparison = compare_devices(d5000_devices, xyd_devices, tolerance)
    dtext_comparison = compare_devices(d5000_dtexts, xyd_dtexts, tolerance)
    rule_analysis = build_rule_analysis(d5000_path, xyd_path, tolerance)
    result = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "d5000_file": str(d5000_path),
            "xyd_file": str(xyd_path),
            "d5000_station_name": d5000_station,
            "xyd_station_name": xyd_station,
            "coordinate_tolerance": tolerance,
        },
        "rule_analysis": rule_analysis,
        "summary_counts": {
            "d5000_devices": len(d5000_devices),
            "xyd_devices": len(xyd_devices),
            "d5000_dtexts": len(d5000_dtexts),
            "xyd_dtexts": len(xyd_dtexts),
            "strong_match": len(comparison["strong_match"]),
            "weak_match": len(comparison["weak_match"]),
            "unmatched_d5000": len(comparison["unmatched_d5000"]),
            "unmatched_xyd": len(comparison["unmatched_xyd"]),
            "coordinate_anomaly": len(comparison["coordinate_anomaly"]),
        },
        "dtext_comparison": dtext_comparison,
    }
    result.update(comparison)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare one D5000 G file and one 新一代 G file.")
    parser.add_argument("d5000_file", type=Path)
    parser.add_argument("xyd_file", type=Path)
    parser.add_argument("--coord-tolerance", type=float, default=0.001)
    parser.add_argument("--format", choices=("html", "text", "json", "both"), default="html")
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_result(args.d5000_file, args.xyd_file, args.coord_tolerance)
    text_report = render_text_report(result)
    html_report = render_html_report(result)
    json_text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.json_out:
        args.json_out.write_text(json_text, encoding="utf-8")

    if args.format in ("html", "both"):
        print(html_report)
    if args.format == "text":
        print(text_report)
    if args.format in ("json", "both"):
        if args.format == "both":
            print()
            print("JSON_RESULT")
        print(json_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
