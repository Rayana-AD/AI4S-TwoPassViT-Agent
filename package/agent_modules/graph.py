"""JSON rules first, then one image-text branch, then a single record."""

from __future__ import annotations

import json
import os
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from audits import (
    FAIL,
    file_name_of,
    json_consistency,
    local_data_path,
    overall_status,
    pixel_rings,
    referenced_in_package,
    waveform_check_items,
    waveform_window,
)
from modality import classify_record
from spatial_precision import margin_status, near_threshold, score_annotation
from vision import (
    SPATIAL_STANDARD,
    WAVEFORM_STANDARD,
    explain_pending,
    judge_spatial,
    judge_waveform,
    load_secrets,
)

THRESHOLD_PATH = os.path.join(os.path.dirname(__file__), "spatial_threshold.json")


class CheckState(TypedDict, total=False):
    json_path: str
    record: dict
    kind: str
    data_exists: bool
    data_path: str
    time_count: int | None
    checks: list
    branch: str
    vision_standard: str
    vision_text: str
    text_note: str
    spatial: dict
    waveform: dict
    overall: str
    load_error: str
    score: dict
    use_vision: bool
    use_text: bool
    trace: list


def _trace(state: CheckState, step: str) -> list:
    return list(state.get("trace") or []) + [step]


def load_node(state: CheckState) -> dict:
    try:
        with open(state["json_path"], encoding="utf-8") as handle:
            record = json.load(handle)
    except json.JSONDecodeError as exc:
        return {"record": {}, "load_error": str(exc), "trace": _trace(state, "load")}
    return {"record": record, "load_error": "", "trace": _trace(state, "load")}


def classify_node(state: CheckState) -> dict:
    kind = classify_record(state["record"], state["json_path"])
    return {"kind": kind, "trace": _trace(state, "classify")}


def json_rules_node(state: CheckState) -> dict:
    record = state["record"]
    exists = referenced_in_package(record, state["json_path"])
    path = local_data_path(state["json_path"], file_name_of(record))
    checks = json_consistency(record, exists, state.get("time_count"))
    if state.get("load_error"):
        checks.insert(0, {
            "check": "文件损坏",
            "status": FAIL,
            "detail": "标注 JSON 无法解析：" + state["load_error"],
            "counts": True,
        })
    checks.append(data_readable(path or "", record))
    return {
        "data_exists": exists,
        "data_path": path or "",
        "checks": checks,
        "trace": _trace(state, "json_rules"),
    }


def data_readable(path: str, record: dict) -> dict:
    """Every sample is asked whether its data file can be opened. A missing local copy is not scored as corrupt."""
    if not path:
        named = file_name_of(record)
        detail = "本机没有数据副本，不能检查文件是否损坏" if named else "标注没有 fileName"
        return {"check": "数据可读", "status": "待复核", "detail": detail, "counts": False}
    try:
        if path.endswith(".csv"):
            with open(path, encoding="utf-8", errors="replace") as handle:
                header = handle.readline()
            if not header.strip():
                return {"check": "数据可读", "status": FAIL, "detail": "CSV 是空文件", "counts": True}
            return {"check": "数据可读", "status": "通过", "detail": "CSV 能打开", "counts": True}
        from PIL import Image
        with Image.open(path) as image:
            image.load()
            size = image.size
        return {"check": "数据可读", "status": "通过", "detail": f"图像能打开，尺寸 {size[0]}×{size[1]}", "counts": True}
    except Exception as exc:
        return {"check": "数据可读", "status": FAIL, "detail": f"文件打不开：{exc}", "counts": True}


def explain_node(state: CheckState) -> dict:
    note = ""
    if state.get("use_text"):
        pending = [item for item in state.get("checks") or [] if item.get("counts") and item["status"] == "待复核"]
        if pending:
            note = explain_pending(state["checks"], load_secrets())
    return {"text_note": note, "trace": _trace(state, "explain")}


def route(state: CheckState) -> str:
    kind = state.get("kind")
    if kind == "waveform":
        return "waveform"
    if kind in {"spatial_boxes", "segmentation"} and pixel_rings(state["record"]):
        return "spatial"
    return "none"


def _saved_threshold() -> float | None:
    if not os.path.exists(THRESHOLD_PATH):
        return None
    with open(THRESHOLD_PATH, encoding="utf-8") as handle:
        payload = json.load(handle)
    return float(payload["threshold"])


def waveform_node(state: CheckState) -> dict:
    checks = list(state.get("checks") or [])
    path = state.get("data_path") or ""
    vision_text = ""
    result = None
    if not path:
        result = {"rows": 0, "length_status": "不适用", "window_status": "不适用", "detail": "CSV 不在本机"}
        checks.extend(waveform_check_items(result))
        checks[-2]["counts"] = False
        checks[-1]["counts"] = False
    else:
        result = waveform_window(path, state["record"])
        checks.extend(waveform_check_items(result))
        want_vision = state.get("use_vision") and result["window_status"] != "不适用"
        if want_vision:
            vision_text = judge_waveform(path, state["record"], load_secrets())
            if result["length_status"] == FAIL:
                vision_text = "行数已不通过，下面的视觉结果只作补充，不能把这条序列判成标注准确。\n" + vision_text
    return {
        "checks": checks,
        "branch": "波形",
        "vision_standard": WAVEFORM_STANDARD if vision_text else "",
        "vision_text": vision_text,
        "waveform": result,
        "trace": _trace(state, "waveform"),
    }


def spatial_node(state: CheckState) -> dict:
    checks = list(state.get("checks") or [])
    rings = pixel_rings(state["record"])
    path = state.get("data_path") or ""
    score = None
    vision_text = ""
    if not rings:
        checks.append({
            "check": "轮廓贴结构",
            "status": "不适用",
            "detail": "没有像素轮廓",
            "counts": False,
        })
    elif not path:
        checks.append({
            "check": "轮廓贴结构",
            "status": "待复核",
            "detail": "轮廓在，图像未抽到本机",
            "counts": False,
        })
    else:
        polygons = [ring["points"] for ring in rings]
        score = score_annotation(path, polygons)
        threshold = _saved_threshold()
        if threshold is None:
            status = "待复核"
            detail = f"边缘占比 {score['edge_fraction']:.3f}，相对平移 {score['margin']:.3f}，阈值尚未标定"
            counts = False
        else:
            status = margin_status(score["margin"], threshold)
            detail = (
                f"边缘占比 {score['edge_fraction']:.3f}，平移后 {score['shifted_edge_fraction']:.3f}，"
                f"差值 {score['margin']:.3f}，阈值 {threshold:.3f}"
            )
            counts = True
        checks.append({"check": "轮廓贴结构", "status": status, "detail": detail, "counts": counts})
        close = threshold is not None and near_threshold(score["margin"], threshold)
        if state.get("use_vision") and close:
            labels = [ring["label"] for ring in rings]
            vision_text = judge_spatial(path, polygons, labels, load_secrets())
    return {
        "checks": checks,
        "branch": "明暗图",
        "vision_standard": SPATIAL_STANDARD if vision_text else "",
        "vision_text": vision_text,
        "spatial": score,
        "trace": _trace(state, "spatial"),
    }


def no_vision_node(state: CheckState) -> dict:
    return {
        "branch": "无",
        "vision_standard": "",
        "vision_text": "",
        "trace": _trace(state, "no_vision"),
    }


def vision_disagrees(text: str) -> bool:
    if not text or text.startswith("调用失败") or text.startswith("行数已不通过"):
        return False
    head = text.strip().lstrip("“\"'")
    return head.startswith("否") or head.upper().startswith("NO")


def merge_node(state: CheckState) -> dict:
    checks = state.get("checks") or []
    overall = overall_status(checks)
    if overall != FAIL and vision_disagrees(state.get("vision_text") or ""):
        overall = "待复核"
    return {"overall": overall, "trace": _trace(state, "merge")}


_DEFECTS = (
    ("文件缺失或损坏", ("引用文件", "文件损坏", "数据可读")),
    ("样本重复", ("时刻重复",)),
    ("标注引用错误", ("引用文件",)),
    ("类别错标", ("类别OOV", "类别错标", "CME数值")),
    ("目标漏标与虚标", ("目标漏标",)),
    ("边界或图像缺陷", ("像素越界", "声明尺寸", "轮廓贴结构", "事件时间范围", "波形行数", "时间窗峰谷")),
    ("划分泄漏", ("划分泄漏",)),
)
_RANK = {"不通过": 5, "待复核": 4, "待判定": 3, "不适用": 2, "通过": 1}


def _group_status(items: list[dict]) -> tuple[str, str]:
    """A confirmed pass or fail outranks an item that could not be scored."""
    if not items:
        return "不适用", ""
    failed = [item for item in items if item.get("counts") and item["status"] == "不通过"]
    passed = [item for item in items if item.get("counts") and item["status"] == "通过"]
    if failed:
        return "不通过", failed[0].get("detail", "")
    if passed:
        pending = [item for item in items if item["status"] == "待复核"]
        detail = passed[0].get("detail", "")
        if pending:
            detail += "；未进入分数：" + pending[0].get("detail", "")
        return "通过", detail
    ranked = max(items, key=lambda item: _RANK.get(item["status"], 0))
    return ranked["status"], ranked.get("detail", "")


def score_checks(checks: list[dict]) -> dict:
    """Pass count over applicable checks. 待判定, 不适用 and 待复核 do not become 0 or 100."""
    by_name = {}
    for item in checks:
        by_name.setdefault(item["check"], []).append(item)
    defects = []
    for name, keys in _DEFECTS:
        matched = [item for key in keys for item in by_name.get(key, [])]
        status, detail = _group_status(matched)
        defects.append({
            "defect": name,
            "status": status,
            "location": detail,
            "counts": status in {"通过", "不通过"},
        })
    counted = [item for item in checks if item.get("counts") and item["status"] in {"通过", "不通过"}]
    passes = sum(1 for item in counted if item["status"] == "通过")
    applicable = len(counted)
    quality = None if applicable == 0 else round(100 * passes / applicable, 2)
    return {
        "passes": passes,
        "applicable": applicable,
        "quality": quality,
        "defects": defects,
        "method": "质量 = 100 × 通过次数 / 适用次数。待判定、不适用、待复核不进入分母。单条样本没有五个版本，不算相关距离。",
    }


def score_node(state: CheckState) -> dict:
    return {"score": score_checks(state.get("checks") or []), "trace": _trace(state, "score")}


def build_graph():
    builder = StateGraph(CheckState)
    builder.add_node("load", load_node)
    builder.add_node("classify", classify_node)
    builder.add_node("json_rules", json_rules_node)
    builder.add_node("explain", explain_node)
    builder.add_node("waveform", waveform_node)
    builder.add_node("spatial", spatial_node)
    builder.add_node("no_vision", no_vision_node)
    builder.add_node("merge", merge_node)
    builder.add_node("score", score_node)
    builder.add_edge(START, "load")
    builder.add_edge("load", "classify")
    builder.add_edge("classify", "json_rules")
    builder.add_edge("json_rules", "explain")
    builder.add_conditional_edges("explain", route, {
        "waveform": "waveform",
        "spatial": "spatial",
        "none": "no_vision",
    })
    builder.add_edge("waveform", "merge")
    builder.add_edge("spatial", "merge")
    builder.add_edge("no_vision", "merge")
    builder.add_edge("merge", "score")
    builder.add_edge("score", END)
    return builder.compile()


_GRAPH = None


def invoke_one(
    json_path: str,
    *,
    use_vision: bool = False,
    use_text: bool = False,
    time_count: int | None = None,
) -> dict:
    """One sample. Vision and the text note stay off unless asked."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    state = _GRAPH.invoke({
        "json_path": json_path,
        "use_vision": use_vision,
        "use_text": use_text,
        "time_count": time_count,
        "trace": [],
    })
    return {
        "json_path": json_path,
        "kind": state.get("kind"),
        "checks": state.get("checks") or [],
        "branch": state.get("branch") or "无",
        "vision_standard": state.get("vision_standard") or "",
        "vision_text": state.get("vision_text") or "",
        "text_note": state.get("text_note") or "",
        "overall": state.get("overall") or overall_status(state.get("checks") or []),
        "score": state.get("score") or score_checks(state.get("checks") or []),
        "evidence_path": state.get("data_path") or "",
        "spatial": state.get("spatial"),
        "waveform": state.get("waveform"),
        "trace": state.get("trace") or [],
    }
