"""Per-object AIA QC row: nine defect buckets + per-region JSON (roadshow 02 aligned)."""

from __future__ import annotations

import json
import os
from typing import Any

from audits import FAIL, NA, PASS, UNDECIDED, json_consistency, pixel_rings
from physics_metrics import (
    annotation_overlap_audit,
    mechanical_coverage_audit,
    missed_label_audit_aia,
    rings_from_label,
)

# 02 §6.2 evidence verbs ↔ object CSV (Chinese)
EVIDENCE_TO_OBJECT = {
    "pass": "通过",
    "fail": "不通过",
    "undetermined": "待判定",
    "not_applicable": "不适用",
}

RULE_VERSION = "aia-qc-v2"


def _status_from_audit_item(item: dict | None) -> str:
    if not item:
        return NA
    return item.get("status") or UNDECIDED


def _worst(statuses: list[str]) -> str:
    if any(s == FAIL for s in statuses):
        return FAIL
    if any(s in {UNDECIDED, "待复核"} for s in statuses):
        return UNDECIDED
    if statuses and all(s == NA for s in statuses):
        return NA
    return PASS


def _region_mechanical_flags(region_id: int, mech: dict) -> str:
    for issue in mech.get("region_issues") or []:
        if issue.get("region_id") == region_id:
            return issue.get("nine_defect_bucket") or "覆盖不足"
    for pair in mech.get("severe_overlap_pairs") or []:
        if region_id in (pair.get("region_a"), pair.get("region_b")):
            return "覆盖过多"
    return "none"


def _long_diameter(points: list) -> float:
    if not points:
        return 128.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return max(max(xs) - min(xs), max(ys) - min(ys), 1.0)


def _centroid(points: list) -> tuple[float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _refine_miss_ring_heuristic(miss_ring: list[dict], label_path: str) -> list[dict]:
    """AIA HEK boxes are event targets, not full-disk AR census — demote nearby bright blobs."""
    rings = rings_from_label(label_path)
    if not rings or not miss_ring:
        return miss_ring
    refs: list[tuple[tuple[float, float], float]] = []
    for ring in rings:
        pts = ring.get("points") or []
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        refs.append((_centroid(pts), _long_diameter(pts)))
    out: list[dict] = []
    for row in list(miss_ring):
        row = dict(row)
        c = row.get("centroid_full") or [0, 0]
        cx, cy = float(c[0]), float(c[1])
        nearest_d = min(
            ((cx - rc[0]) ** 2 + (cy - rc[1]) ** 2) ** 0.5 for rc, _ in refs
        )
        ref_d = max(r[1] for r in refs)
        if row.get("audit_miss_label") == "likely_miss" and nearest_d < 3.5 * ref_d:
            row["audit_miss_label"] = "review"
            row["audit_miss_note"] = "距已标框 <3.5d，视为同活动区/邻域光晕，不计入对象级漏标 fail"
        out.append(row)
    return out


def _agent_confirms_miss(agent_record: dict | None) -> bool:
    if not agent_record:
        return False
    for key in ("miss_ring_audit",):
        for m in agent_record.get(key) or []:
            if m.get("audit_miss_label") == "likely_miss":
                return True
    ev = agent_record.get("evaluation") or {}
    for m in ev.get("miss_ring_audit") or []:
        if m.get("audit_miss_label") == "likely_miss":
            return True
    return bool((agent_record.get("pass2") or {}).get("parsed", {}).get("missed_label_confirmed"))


def _build_regions_detail(
    label_path: str,
    image_path: str,
    mech: dict,
    agent: dict | None,
) -> list[dict[str, Any]]:
    from audits import aia_hek_field_paths

    obj = json.load(open(label_path, encoding="utf-8"))
    paths = aia_hek_field_paths(obj)
    ring_rows = (agent or {}).get("ring_audit") or []
    ring_by_id = {r.get("region_id"): r for r in ring_rows}
    eval_regions = ((agent or {}).get("evaluation") or {}).get("per_region") or []
    p2_by_id = {r.get("region_id"): r for r in eval_regions}
    p1_norm = (((agent or {}).get("pass1") or {}).get("normalized") or {}).get("per_region") or []
    p1_by_id = {r.get("region_id"): r for r in p1_norm}

    labeled = ((agent or {}).get("metrics") or {}).get("labeled_regions") or []
    if not labeled and ring_rows:
        labeled = [{"region_id": r.get("region_id")} for r in ring_rows]
    if not labeled:
        rings = pixel_rings(obj)
        labeled = [{"region_id": i, "vertices_full": r.get("points")} for i, r in enumerate(rings)]

    details: list[dict[str, Any]] = []
    for row in labeled:
        rid = row.get("region_id")
        if rid is None:
            continue
        ring = ring_by_id.get(rid) or {}
        p2 = p2_by_id.get(rid) or {}
        p1 = p1_by_id.get(rid) or {}
        scale = ring.get("scale_audit") or {}
        fpath = paths[rid] if isinstance(rid, int) and rid < len(paths) else ""
        entry = {
            "region_id": rid,
            "caption": row.get("caption"),
            "fieldPath": fpath,
            "vertices_full": row.get("vertices_full"),
            "mechanical": _region_mechanical_flags(rid, mech),
            "pass1_confidence": p1.get("confidence_plausible"),
            "pass2_verdict": p2.get("verdict") or "",
            "scale_audit": scale.get("audit_scale"),
            "scale_plausible": scale.get("scale_plausible"),
            "ring_audit_0.5_1d": ring.get("audit_0.5_1d"),
            "contrast_0.5_1d": ring.get("contrast_inside_vs_0.5_1d"),
        }
        details.append(entry)
    return details


def qc_aia_object(
    dir_id: str,
    image_path: str,
    label_path: str,
    *,
    agent_record: dict | None = None,
    miss_mode: str = "fast",
) -> dict[str, Any]:
    """One CSV row payload for a paired PNG + label."""
    obj = json.load(open(label_path, encoding="utf-8"))
    object_id = os.path.basename(image_path)
    data_exists = os.path.isfile(image_path)
    rule_findings = json_consistency(obj, data_exists)
    by_check = {f["check"]: f for f in rule_findings}

    d1 = _status_from_audit_item(by_check.get("引用文件"))
    d2 = PASS if d1 == PASS else FAIL if d1 == FAIL else UNDECIDED
    d3a = _status_from_audit_item(by_check.get("像素越界"))
    d4 = _status_from_audit_item(by_check.get("类别OOV"))
    d5 = NA
    d6 = NA

    mech = mechanical_coverage_audit(label_path)
    ov = annotation_overlap_audit(label_path)
    mech_fail = mech.get("mechanical_fail", False)

    d9 = FAIL if mech_fail else PASS if mech.get("n_regions") else NA

    if data_exists:
        miss_payload, miss_ring = missed_label_audit_aia(image_path, label_path, mode=miss_mode)
        miss_ring = _refine_miss_ring_heuristic(miss_ring, label_path)
    else:
        miss_payload, miss_ring = {}, []
    likely_miss = [m for m in miss_ring if m.get("audit_miss_label") == "likely_miss"]
    confirmed_miss = _agent_confirms_miss(agent_record)
    # 九7：统计上为「可能未标亮区」，不作 HEK 漏标 fail（见 aia-qc-v2 汇总口径）
    n_cand = len(miss_payload.get("candidates") or [])
    if not data_exists:
        d7 = NA
    elif confirmed_miss and likely_miss:
        d7 = FAIL
    elif n_cand > 0 or likely_miss:
        d7 = "有候选"
    else:
        d7 = "无"
    regions = _build_regions_detail(label_path, image_path, mech, agent_record)
    n_regions = len(regions) or mech.get("n_regions") or 0

    d3b = NA
    d8 = NA
    if n_regions == 0:
        d3b = NA
    elif agent_record and ((agent_record.get("pass2") or {}).get("parsed")):
        per = ((agent_record.get("evaluation") or {}).get("per_region") or [])
        verbs = [r.get("verdict") for r in per]
        if any(v == "不合理" for v in verbs):
            d3b = FAIL
            d8 = FAIL
        elif any(v == "不确定" for v in verbs):
            d3b = UNDECIDED
        elif verbs:
            d3b = PASS
        else:
            d3b = UNDECIDED
    else:
        d3b = UNDECIDED
        d8 = UNDECIDED

    d7_miss_scored = NA
    if confirmed_miss and likely_miss:
        d7_miss_scored = FAIL

    applicable = [s for s in (d1, d2, d3a, d3b, d4, d8, d9, d7_miss_scored) if s != NA]
    object_overall = _worst(applicable) if applicable else NA

    scored_applicable = [s for s in (d1, d2, d3a, d4, d9, d7_miss_scored) if s != NA]
    if d3b == FAIL:
        scored_applicable.append(d3b)
    if d8 == FAIL:
        scored_applicable.append(d8)
    object_overall_scored = _worst(scored_applicable) if scored_applicable else NA
    return {
        "dirId": dir_id,
        "objectId": object_id,
        "labelFile": os.path.basename(label_path),
        "ruleVersion": RULE_VERSION,
        "objectOverall": object_overall,
        "九1_文件配对": d1,
        "objectOverallScored": object_overall_scored,
        "missHeuristicLikely": len(likely_miss),
        "missConfirmed": confirmed_miss,
        "九2_孤儿标注": d2,
        "九3a_像素越界": d3a,
        "九3b_轮廓贴合": d3b,
        "九4_类别非法": d4,
        "九5_时段超限": d5,
        "九6_尺寸矛盾": d6,
        "九7_可能未标亮区": d7,
        "九7_漏标": d7_miss_scored,
        "九8_虚标": d8,
        "九9_覆盖异常": d9,
        "nRegions": n_regions,
        "regionsDetail": regions,
        "mechanicalCoverage": {
            "severe_overlap_pairs": mech.get("severe_overlap_pairs"),
            "region_issues": mech.get("region_issues"),
            "iou_severe_threshold": mech.get("iou_severe_threshold"),
        },
        "missLabel": {
            "candidates": miss_payload.get("candidates"),
            "miss_ring_audit": miss_ring,
            "policy": "可能未标亮区=诊断；九7_漏标计分轨不适用(HEK事件框)",
        },
        "overlapNote": {
            "duplicate_ar_groups": ov.get("duplicate_ar_groups"),
            "n_suspect_pairs": len(ov.get("suspect_redundant_pairs") or []),
        },
        "notes": _notes_summary(d1, d3b, d7, d8, d9, mech, n_cand),
    }


def _notes_summary(d1, d3b, d7, d8, d9, mech, n_cand) -> str:
    parts = []
    if d1 == FAIL:
        parts.append("配对失败")
    if d9 == FAIL:
        parts.append(f"机械覆盖异常 {len(mech.get('severe_overlap_pairs') or [])} 对")
    if d7 == "有候选" and n_cand:
        parts.append(f"可能未标亮区 {n_cand} 处(非漏标)")
    if d8 == FAIL:
        parts.append("存在虚标/不合理框")
    if d3b == UNDECIDED:
        parts.append("轮廓待 Agent/Pass2")
    return "；".join(parts) if parts else "规则+机械项通过或待跑批"


def row_for_csv(payload: dict[str, Any]) -> dict[str, str]:
    """Flatten JSON columns for CSV output."""
    out = {k: v for k, v in payload.items() if k not in {
        "regionsDetail", "mechanicalCoverage", "missLabel", "overlapNote",
    }}
    out["regionsDetail"] = json.dumps(payload.get("regionsDetail") or [], ensure_ascii=False)
    out["mechanicalCoverage"] = json.dumps(payload.get("mechanicalCoverage") or {}, ensure_ascii=False)
    out["missLabel"] = json.dumps(payload.get("missLabel") or {}, ensure_ascii=False)
    out["overlapNote"] = json.dumps(payload.get("overlapNote") or {}, ensure_ascii=False)
    return out


CSV_COLUMNS = [
    "dirId",
    "objectId",
    "labelFile",
    "ruleVersion",
    "objectOverall",
    "九1_文件配对",
    "objectOverallScored",
    "missHeuristicLikely",
    "missConfirmed",
    "九2_孤儿标注",
    "九3a_像素越界",
    "九3b_轮廓贴合",
    "九4_类别非法",
    "九5_时段超限",
    "九6_尺寸矛盾",
    "九7_可能未标亮区",
    "九7_漏标",
    "九8_虚标",
    "九9_覆盖异常",
    "nRegions",
    "regionsDetail",
    "mechanicalCoverage",
    "missLabel",
    "overlapNote",
    "notes",
]
