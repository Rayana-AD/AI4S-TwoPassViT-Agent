"""Decide which checker a sample should go to. Rules only, no model call."""

from __future__ import annotations


def _modality_name(basic: dict) -> str:
    value = basic.get("modality")
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").lower()


def classify_record(obj: dict, source: str = "") -> str:
    """Return waveform, event_catalog, segmentation, spatial_boxes, or spatial_image.

    Quiet HMI/AIA and quiet CME both have an empty event list and anonymous
    instrument fields. The dataset directory name is what separates them.
    """
    basic = obj.get("basic_annotation") or {}
    fmt = str(basic.get("fileFormat") or "").lower()
    if "ulf_event_annotation" in obj or fmt == "csv" or _modality_name(basic) == "timeseries":
        return "waveform"

    science = obj.get("science_annotation") or {}
    if isinstance(science.get("mask"), dict):
        return "segmentation"
    if "specialShapes" in science:
        shapes = science.get("specialShapes") or []
        return "spatial_boxes" if shapes else "spatial_image"

    events = (obj.get("hek_event_annotation") or {}).get("matched_events") or []
    has_pixel = any(isinstance(event, dict) and event.get("bbox_polygon_pixel") for event in events)
    if has_pixel:
        return "spatial_boxes"
    if events and any(isinstance(event, dict) and ("width" in event or "central_pa" in event) for event in events):
        return "event_catalog"

    text = source.replace("\\", "/")
    if "hek_event_annotation" in obj:
        if "CME_C2" in text:
            return "event_catalog"
        if "HMI_AR" in text or "AIA_AR" in text:
            return "spatial_boxes"
    if fmt in {"png", "jpg", "jpeg"} or _modality_name(basic) == "image":
        return "spatial_image"
    return "unknown"
