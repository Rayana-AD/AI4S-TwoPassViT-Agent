"""HEK baselines from QC-passing boxes; compare cohorts using label JSON + object CSV (no PNG reads)."""

from __future__ import annotations

import csv
import json
import math
import os
import re
from statistics import median
from typing import Any

RULE_VERSION = "hek-context-v2"

HEK_NUMERIC_KEYS = (
    "area_atdiskcenter",
    "unsignedflux",
    "highsheararea",
    "meangradienttotal",
    "meangradienthorz",
    "meangradientvert",
    "meaninclinationgamma",
    "meantwistalpha",
    "meanshearangle",
    "meanvertcurrentdensity",
    "meancurrenthelicity",
    "unsignedcurrenthelicity",
)

_EVENT_IDX = re.compile(r"matched_events\[(\d+)\]")


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _shoelace_area(points: list) -> float:
    if len(points) < 3:
        return 0.0
    pts = points[:-1] if len(points) >= 2 and points[0] == points[-1] else points
    n = len(pts)
    area = 0.0
    for i in range(n):
        x0, y0 = float(pts[i][0]), float(pts[i][1])
        x1, y1 = float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1])
        area += x0 * y1 - x1 * y0
    return abs(area) * 0.5


def _long_diameter(points: list) -> float:
    if not points:
        return 0.0
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return max(max(xs) - min(xs), max(ys) - min(ys), 0.0)


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "median": None, "p10": None, "p90": None}
    xs = sorted(values)
    n = len(xs)

    def pct(q: float) -> float:
        if n == 1:
            return xs[0]
        idx = q * (n - 1)
        lo = int(math.floor(idx))
        hi = min(lo + 1, n - 1)
        w = idx - lo
        return xs[lo] * (1 - w) + xs[hi] * w

    return {
        "n": n,
        "median": round(median(xs), 6),
        "p10": round(pct(0.10), 6),
        "p90": round(pct(0.90), 6),
    }


def _hek_index(field_path: str) -> int | None:
    m = _EVENT_IDX.search(field_path or "")
    return int(m.group(1)) if m else None


def _label_cache_load(label_path: str, cache: dict[str, dict]) -> dict[str, Any]:
    if label_path in cache:
        return cache[label_path]
    if not os.path.isfile(label_path):
        cache[label_path] = {}
        return cache[label_path]
    cache[label_path] = json.load(open(label_path, encoding="utf-8"))
    return cache[label_path]


def _hek_event_from_obj(obj: dict[str, Any], hek_index: int | None) -> dict[str, Any]:
    if hek_index is None:
        return {}
    events = (obj.get("hek_event_annotation") or {}).get("matched_events") or []
    if hek_index < 0 or hek_index >= len(events):
        return {}
    ev = events[hek_index]
    return ev if isinstance(ev, dict) else {}


def _extract_hek_features(event: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "concept": event.get("concept") or "",
        "event_type": event.get("event_type") or "",
        "ar_noaanum": event.get("ar_noaanum") or "",
        "obs_channelid": event.get("obs_channelid") or "",
    }
    for key in HEK_NUMERIC_KEYS:
        out[key] = _safe_float(event.get(key))
    return out


def _region_qc_cohort(row: dict[str, Any], reg: dict[str, Any]) -> str:
    """Box-level cohorts; object 九7/整体 fail 不拖垮未机械标记的框（HEK 基线用）。"""
    if row.get("九1_文件配对") == "不通过":
        return "object_rule_fail"
    mech = reg.get("mechanical") or "none"
    if mech != "none":
        return "mech_issue"
    p2 = reg.get("pass2_verdict") or ""
    if p2 == "不合理":
        return "contour_fail"
    if p2 == "不确定":
        return "pending_review"
    if row.get("九3b_轮廓贴合") == "待判定" or row.get("九8_虚标") == "待判定":
        return "pending_review"
    if row.get("九3a_像素越界") == "不通过":
        return "object_rule_fail"
    return "reference"


def _ratio_to_ref(value: float | None, ref: dict[str, float | None]) -> float | None:
    med = ref.get("median")
    if value is None or med is None or med <= 0:
        return None
    return round(value / med, 4)


def _assist_hint(
    cohort: str,
    hek: dict[str, Any],
    euv: dict[str, Any],
    ref_hek: dict[str, dict[str, float | None]],
    ref_euv: dict[str, dict[str, float | None]],
) -> str:
    hints: list[str] = []
    if cohort == "reference":
        return "严格参照(轮廓已判通过)"
    if cohort == "pending_review":
        hints.append("对象/框语义待 Pass2，HEK 仍可与机械合格框基线对照")
    if cohort == "bright_unlabeled":
        fq = euv.get("flux_ratio_vs_quiet")
        p10 = (ref_euv.get("flux_ratio_vs_quiet") or {}).get("p10")
        p50 = (ref_euv.get("flux_ratio_vs_quiet") or {}).get("median")
        if fq is not None and p10 is not None and fq < p10:
            hints.append("EUV/宁静低于合格框P10，更似 plage/噪声或非独立 AR")
        elif fq is not None and p50 is not None and fq >= p50:
            hints.append("EUV达合格框中位以上，宜邻域/HEK复核是否扩展标注")
        audit = euv.get("_miss_audit") or ""
        if audit == "contradicts_brighter_core":
            hints.append("环带对比不支持独立亮核")
        return "；".join(hints) if hints else "可能未标亮区(无HEK)，仅诊断"

    uf = hek.get("unsignedflux")
    ref_u = ref_hek.get("unsignedflux") or {}
    if uf is not None and ref_u.get("median"):
        if uf < (ref_u.get("p10") or 0):
            hints.append("磁通低于合格框P10")
        elif uf > (ref_u.get("p90") or float("inf")):
            hints.append("磁通高于合格框P90")
    area = hek.get("area_atdiskcenter")
    ref_a = ref_hek.get("area_atdiskcenter") or {}
    if area is not None and ref_a.get("p10") and area < ref_a["p10"]:
        hints.append("HEK 日面面积偏小")
    fq = euv.get("flux_ratio_vs_quiet")
    ref_f = ref_euv.get("flux_ratio_vs_quiet") or {}
    if fq is not None and ref_f.get("median"):
        if fq < (ref_f.get("p10") or 0):
            hints.append("EUV/宁静偏低(对象CSV缓存)")
        elif fq > (ref_f.get("p90") or float("inf")):
            hints.append("EUV/宁静偏高(对象CSV缓存)")
    ring_c = euv.get("contrast_0.5_1d")
    if ring_c is not None and isinstance(ring_c, (int, float)) and ring_c < 0:
        hints.append("环带对比度为负，轮廓待复核")
    if cohort == "pending_review" and not hints:
        hints.append("待 Pass2/Agent，可先对照 HEK 基线")
    if cohort == "mech_issue":
        hints.append("机械覆盖异常，优先查 IoU/框几何")
    return "；".join(hints) if hints else "与合格框 HEK 分布接近"


def build_hek_context_rows(
    qc_rows: list[dict[str, Any]],
    *,
    data_dir: str,
    dir_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """JSON + object CSV only; EUV for candidates from missLabel.preview_physics (QC 阶段已算)."""
    detail: list[dict[str, Any]] = []
    label_cache: dict[str, dict] = {}
    label_dir = os.path.join(data_dir, "label")

    for row in qc_rows:
        object_id = row.get("objectId") or ""
        label_file = row.get("labelFile") or f"{object_id}.json"
        label_path = os.path.join(label_dir, label_file)
        obj = _label_cache_load(label_path, label_cache)
        wavelnth = (obj.get("science_annotation") or {}).get("wavelnth") or ""

        for reg in row.get("regionsDetail") or []:
            rid = reg.get("region_id")
            verts = reg.get("vertices_full") or []
            cohort = _region_qc_cohort(row, reg)
            hek_idx = _hek_index(reg.get("fieldPath") or "")
            hek = _extract_hek_features(_hek_event_from_obj(obj, hek_idx))
            area_px = _shoelace_area(verts) if verts else None
            area_hek = hek.get("area_atdiskcenter")
            area_ratio = ""
            if area_px and area_hek and area_px > 0:
                area_ratio = round(area_hek / area_px, 6)
            detail.append({
                "dirId": dir_id,
                "objectId": object_id,
                "recordKind": "labeled_region",
                "regionOrCandidateId": rid,
                "qcCohort": cohort,
                "aia_wavelnth": wavelnth,
                "fieldPath": reg.get("fieldPath") or "",
                "mechanical": reg.get("mechanical") or "",
                "pass2_verdict": reg.get("pass2_verdict") or "",
                "concept": hek.get("concept") or "",
                "ar_noaanum": hek.get("ar_noaanum") or "",
                "obs_channelid": hek.get("obs_channelid") or "",
                "bbox_area_px2": round(area_px, 1) if area_px else "",
                "long_d_px": round(_long_diameter(verts), 1) if verts else "",
                "hek_area_per_px2": area_ratio,
                **{k: hek.get(k) if hek.get(k) is not None else "" for k in HEK_NUMERIC_KEYS},
                "flux_ratio_vs_quiet": "",
                "flux_ratio_vs_ring": "",
                "cnr": "",
                "contrast_0.5_1d": reg.get("contrast_0.5_1d") if reg.get("contrast_0.5_1d") is not None else "",
                "ring_audit_0.5_1d": reg.get("ring_audit_0.5_1d") or "",
                "assistHint": "",
            })

        miss = row.get("missLabel") or {}
        ring_by_id = {m.get("candidate_id"): m for m in (miss.get("miss_ring_audit") or [])}
        for cand in miss.get("candidates") or []:
            cid = cand.get("candidate_id")
            poly = cand.get("synthetic_polygon_full") or []
            preview = cand.get("preview_physics") or {}
            ring = ring_by_id.get(cid) or {}
            detail.append({
                "dirId": dir_id,
                "objectId": object_id,
                "recordKind": "bright_unlabeled_candidate",
                "regionOrCandidateId": cid,
                "qcCohort": "bright_unlabeled",
                "aia_wavelnth": wavelnth,
                "fieldPath": "",
                "mechanical": "",
                "pass2_verdict": "",
                "concept": "",
                "ar_noaanum": "",
                "obs_channelid": "",
                "bbox_area_px2": round(_shoelace_area(poly), 1) if poly else "",
                "long_d_px": ring.get("d_long_px_full") or "",
                "hek_area_per_px2": "",
                **{k: "" for k in HEK_NUMERIC_KEYS},
                "flux_ratio_vs_quiet": preview.get("flux_ratio_vs_quiet", ""),
                "flux_ratio_vs_ring": preview.get("flux_ratio_vs_ring", ""),
                "cnr": preview.get("cnr", ""),
                "contrast_0.5_1d": ring.get("contrast_inside_vs_0.5_1d", ""),
                "ring_audit_0.5_1d": ring.get("audit_0.5_1d") or "",
                "miss_audit_0.5_1d": ring.get("audit_0.5_1d") or "",
                "audit_miss_label": ring.get("audit_miss_label") or "",
                "assistHint": "",
            })

    # HEK 基线：框级机械通过即可（不要求 Pass2；对象级九7 不参与）
    ref_rows = [
        d for d in detail
        if d["recordKind"] == "labeled_region"
        and d["qcCohort"] not in ("mech_issue", "contour_fail", "object_rule_fail", "bright_unlabeled")
    ]
    ref_hek: dict[str, dict[str, float | None]] = {}
    for key in HEK_NUMERIC_KEYS + ("hek_area_per_px2",):
        vals = [float(d[key]) for d in ref_rows if d.get(key) not in ("", None)]
        ref_hek[key] = _percentiles(vals)
    ref_euv: dict[str, dict[str, float | None]] = {}
    for key in ("flux_ratio_vs_quiet", "flux_ratio_vs_ring", "cnr", "contrast_0.5_1d"):
        vals = [float(d[key]) for d in ref_rows if d.get(key) not in ("", None)]
        ref_euv[key] = _percentiles(vals)
    cand_ref = [d for d in detail if d["recordKind"] == "bright_unlabeled_candidate"]
    for key in ("flux_ratio_vs_quiet", "flux_ratio_vs_ring", "cnr"):
        vals = [float(d[key]) for d in cand_ref if d.get(key) not in ("", None)]
        if vals and not ref_euv[key].get("n"):
            ref_euv[key] = _percentiles(vals)

    for d in detail:
        hek_feats = {k: _safe_float(d.get(k)) for k in HEK_NUMERIC_KEYS}
        hek_feats["area_atdiskcenter"] = _safe_float(d.get("area_atdiskcenter"))
        euv_feats = {
            k: _safe_float(d.get(k)) for k in ("flux_ratio_vs_quiet", "flux_ratio_vs_ring", "cnr")
        }
        c01 = _safe_float(d.get("contrast_0.5_1d"))
        if c01 is not None:
            euv_feats["contrast_0.5_1d"] = c01
        euv_feats["_miss_audit"] = d.get("miss_audit_0.5_1d") or d.get("ring_audit_0.5_1d") or ""
        d["unsignedflux_vs_ref_median"] = _ratio_to_ref(
            hek_feats.get("unsignedflux"), ref_hek.get("unsignedflux", {})
        ) or ""
        d["assistHint"] = _assist_hint(
            d["qcCohort"], hek_feats, euv_feats, ref_hek, ref_euv
        )

    summary: list[dict[str, Any]] = []
    cohorts = sorted({d["qcCohort"] for d in detail})
    metric_blocks: list[tuple[str, dict, str]] = []
    for key in HEK_NUMERIC_KEYS:
        if ref_hek.get(key, {}).get("n"):
            metric_blocks.append((key, ref_hek[key], f"HEK.{key}"))
    if ref_hek.get("hek_area_per_px2", {}).get("n"):
        metric_blocks.append(("hek_area_per_px2", ref_hek["hek_area_per_px2"], "derived.hek_area_per_px2"))
    for key in ref_euv:
        if ref_euv[key].get("n"):
            metric_blocks.append((key, ref_euv[key], f"EUV.{key}"))
    for metric_key, ref_block, label in metric_blocks:
        ref_n = int(ref_block["n"])
        for cohort in cohorts:
            if cohort == "reference":
                continue
            subset = [
                d for d in detail
                if d["qcCohort"] == cohort and d.get(metric_key) not in ("", None)
            ]
            vals = [float(d[metric_key]) for d in subset]
            if not vals:
                continue
            p10 = ref_block.get("p10")
            below = sum(1 for v in vals if p10 is not None and v < p10)
            summary.append({
                "dirId": dir_id,
                "metric": label,
                "reference_n": ref_n,
                "reference_median": ref_block.get("median"),
                "reference_p10": ref_block.get("p10"),
                "reference_p90": ref_block.get("p90"),
                "compare_cohort": cohort,
                "compare_n": len(vals),
                "compare_median": round(median(vals), 6),
                "compare_below_ref_p10": below,
                "compare_below_ref_p10_rate": round(below / len(vals), 4) if vals else "",
                "ruleVersion": RULE_VERSION,
                "data_source": "label_json+object_csv",
            })

    cohort_counts = {c: sum(1 for d in detail if d["qcCohort"] == c) for c in cohorts}
    hek_baseline_n = len(ref_rows)
    summary.insert(0, {
        "dirId": dir_id,
        "metric": "cohort_counts",
        "reference_n": hek_baseline_n,
        "reference_median": "",
        "reference_p10": "",
        "reference_p90": "",
        "compare_cohort": json.dumps(
            {**cohort_counts, "hek_baseline_labeled_regions": hek_baseline_n},
            ensure_ascii=False,
        ),
        "compare_n": len(detail),
        "compare_median": "",
        "compare_below_ref_p10": "",
        "compare_below_ref_p10_rate": "",
        "ruleVersion": RULE_VERSION,
        "data_source": "label_json+object_csv",
    })
    return detail, summary


DETAIL_COLUMNS = [
    "dirId",
    "objectId",
    "recordKind",
    "regionOrCandidateId",
    "qcCohort",
    "aia_wavelnth",
    "fieldPath",
    "mechanical",
    "pass2_verdict",
    "concept",
    "ar_noaanum",
    "obs_channelid",
    "bbox_area_px2",
    "long_d_px",
    "hek_area_per_px2",
    *HEK_NUMERIC_KEYS,
    "flux_ratio_vs_quiet",
    "flux_ratio_vs_ring",
    "cnr",
    "contrast_0.5_1d",
    "ring_audit_0.5_1d",
    "unsignedflux_vs_ref_median",
    "miss_audit_0.5_1d",
    "audit_miss_label",
    "assistHint",
]

SUMMARY_COLUMNS = [
    "dirId",
    "metric",
    "reference_n",
    "reference_median",
    "reference_p10",
    "reference_p90",
    "compare_cohort",
    "compare_n",
    "compare_median",
    "compare_below_ref_p10",
    "compare_below_ref_p10_rate",
    "ruleVersion",
    "data_source",
]


def write_hek_context_csvs(
    qc_rows: list[dict[str, Any]],
    *,
    data_dir: str,
    dir_id: str,
    out_dir: str,
) -> dict[str, str]:
    detail, summary = build_hek_context_rows(qc_rows, data_dir=data_dir, dir_id=dir_id)
    detail_path = os.path.join(out_dir, f"{dir_id}_HEK上下文_框明细.csv")
    summary_path = os.path.join(out_dir, f"{dir_id}_HEK上下文_汇总.csv")
    os.makedirs(out_dir, exist_ok=True)
    with open(detail_path, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=DETAIL_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(detail)
    with open(summary_path, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(summary)
    return {"hek_context_detail_csv": detail_path, "hek_context_summary_csv": summary_path}
