"""Map physics-informed two-pass runs to 路演要求 6.2 证据表 rows (C13)."""

from __future__ import annotations

import json
import os
from typing import Any

from audits import aia_hek_field_paths, epb_mask_field_paths


def _verdict_to_roadshow(verdict: str) -> str:
    v = (verdict or "").strip()
    if v == "合理":
        return "pass"
    if v == "不合理":
        return "fail"
    if v in {"不确定", "undetermined", ""}:
        return "undetermined"
    if v in {"是", "pass"}:
        return "pass"
    if v in {"否", "fail"}:
        return "fail"
    return "undetermined"


def _ring_by_id(ring_audit: list[dict] | None) -> dict[Any, dict]:
    return {row.get("region_id"): row for row in (ring_audit or []) if row.get("region_id") is not None}


def _pass1_by_id(record: dict) -> dict[Any, dict]:
    norm = ((record.get("pass1") or {}).get("normalized") or {}).get("per_region") or []
    if norm:
        return {row.get("region_id"): row for row in norm}
    try:
        from physics_inspect import normalize_pass1

        stub = {"metrics": record.get("metrics") or {}}
        norm = normalize_pass1((record.get("pass1") or {}).get("parsed") or {}, stub).get("per_region") or []
        if norm:
            return {row.get("region_id"): row for row in norm}
    except Exception:
        pass
    parsed = ((record.get("pass1") or {}).get("parsed") or {}).get("regions") or []
    return {row.get("region_id"): row for row in parsed}


def _vertices_summary(verts: list | None) -> str:
    if not verts:
        return ""
    pts = verts[:4]
    if len(verts) > 4:
        return f"polygon5 first4={pts}…"
    return f"polygon={verts}"


def mechanical_evidence_rows(record: dict, *, label_path: str | None = None) -> list[dict[str, str]]:
    """Pre-Agent geometry: IoU≥65% → 覆盖过多；bbox w/h≤0 → 覆盖不足（九类 #9）。"""
    dir_id = record.get("dirId") or ""
    object_id = record.get("objectId") or record.get("id") or ""
    mech = (record.get("metrics") or {}).get("mechanical_coverage_audit")
    if mech is None and label_path and os.path.isfile(label_path):
        from physics_metrics import mechanical_coverage_audit

        mech = mechanical_coverage_audit(label_path)
    if not mech:
        return []
    rule = "mechanical-coverage-v1"
    check = "C09"
    rows: list[dict[str, str]] = []
    for issue in mech.get("region_issues") or []:
        rid = issue.get("region_id")
        rows.append({
            "findingId": f"{check}-{dir_id}-{object_id}-mech-r{rid}",
            "checkId": check,
            "ruleVersion": rule,
            "dirId": dir_id,
            "objectId": object_id,
            "fieldPath": f"hek_event_annotation.matched_events[{issue.get('hek_event_index', rid)}].bbox_polygon_pixel",
            "locatorType": "imageRegion",
            "verdict": "fail",
            "detail": f"【机械·{issue.get('nine_defect_bucket')}】{issue.get('detail')}（送 Agent 前判定，九类#9）",
        })
    for pair in mech.get("severe_overlap_pairs") or []:
        ra, rb = pair.get("region_a"), pair.get("region_b")
        rows.append({
            "findingId": f"{check}-{dir_id}-{object_id}-overlap-{ra}-{rb}",
            "checkId": check,
            "ruleVersion": rule,
            "dirId": dir_id,
            "objectId": object_id,
            "fieldPath": "hek_event_annotation.matched_events[].bbox_polygon_pixel",
            "locatorType": "imageRegion",
            "verdict": "fail",
            "detail": (
                f"【机械·覆盖过多】region {ra}↔{rb} bbox_iou={pair.get('bbox_iou')}≥"
                f"{mech.get('iou_severe_threshold')}。{pair.get('detail','')}"
            ),
        })
    return rows


def findings_from_physics_record(record: dict, *, label_path: str | None = None) -> list[dict[str, str]]:
    """
    One evidence row per labeled region (annotation target), 02 §6.2 columns.
    """
    dir_id = record.get("dirId") or ""
    object_id = record.get("objectId") or record.get("id") or ""
    rule = record.get("ruleVersion") or "physics-informed-v1"
    check = record.get("checkId") or "C13"
    if check.endswith("-physics"):
        check = check.replace("-physics", "")

    modality = record.get("modality") or (record.get("metrics") or {}).get("modality") or "AIA"
    p2 = ((record.get("pass2") or {}).get("parsed") or {})
    by_verdict = {
        r.get("region_id"): r
        for r in (p2.get("regions") or [])
        if r.get("region_id") is not None
    }
    labeled = (record.get("metrics") or {}).get("labeled_regions") or []
    ring_audit = record.get("ring_audit") or ((record.get("pass2") or {}).get("ring_audit"))
    rings_map = _ring_by_id(ring_audit)
    pass1_map = _pass1_by_id(record)

    field_paths: list[str] = []
    if label_path and os.path.isfile(label_path):
        obj = json.load(open(label_path, encoding="utf-8"))
        if modality == "AIA" or "hek_event_annotation" in obj:
            field_paths = aia_hek_field_paths(obj)
        else:
            field_paths = epb_mask_field_paths(obj)
    default_field = (
        "hek_event_annotation.matched_events[].bbox_polygon_pixel"
        if modality == "AIA"
        else "science_annotation.mask.shapes[].polygon"
    )

    rows: list[dict[str, str]] = mechanical_evidence_rows(record, label_path=label_path)
    for row in labeled:
        rid = row.get("region_id")
        p2_row = by_verdict.get(rid) or {}
        verdict_cn = p2_row.get("verdict") or p2.get("pass2_verdict") or ""
        road_verdict = _verdict_to_roadshow(str(verdict_cn))
        p1 = pass1_map.get(rid) or {}
        ring = rings_map.get(rid) or {}
        conf = p1.get("confidence_plausible")
        conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
        field = field_paths[rid] if isinstance(rid, int) and rid < len(field_paths) else default_field
        verts = row.get("vertices_full")
        loc = _vertices_summary(verts)
        detail_parts = [
            f"physics-informed pass2：{verdict_cn or '—'}。",
            f"pass1 confidence_plausible={conf_s}。",
        ]
        if ring:
            detail_parts.append(
                "ring_audit "
                f"contrast_0.5_1d={ring.get('contrast_inside_vs_0.5_1d')} "
                f"audit={ring.get('audit_0.5_1d')}/{ring.get('audit_1_2d')}。"
            )
            ga = ring.get("gradient_audit") or {}
            if ga.get("valid"):
                detail_parts.append(
                    "gradient "
                    f"step={ga.get('boundary_dn_step_inside_minus_outside')} "
                    f"grad={ga.get('mean_grad_at_boundary')} "
                    f"audit_boundary={ga.get('audit_boundary_gradient')} "
                    f"hint={ring.get('audit_composite_hint')}。"
                )
        if p2_row.get("reason"):
            detail_parts.append(str(p2_row.get("reason")))
        if loc:
            detail_parts.append(loc)
        detail = " ".join(detail_parts).replace("\n", " ")[:2000]
        finding_id = f"{check}-{dir_id}-{object_id}-r{rid}"
        rows.append({
            "findingId": finding_id,
            "checkId": check,
            "ruleVersion": rule,
            "dirId": dir_id,
            "objectId": object_id,
            "fieldPath": field,
            "locatorType": "imageRegion",
            "verdict": road_verdict,
            "detail": detail,
        })
    return rows


def append_evidence_csv(rows: list[dict[str, str]], csv_path: str) -> None:
    import csv

    header = ["findingId", "checkId", "ruleVersion", "dirId", "objectId", "fieldPath", "locatorType", "verdict", "detail"]
    write_header = not os.path.isfile(csv_path) or os.path.getsize(csv_path) == 0
    with open(csv_path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
