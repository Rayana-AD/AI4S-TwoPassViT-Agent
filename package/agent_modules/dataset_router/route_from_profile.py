"""Route pipeline from a DirectoryProfile (filesystem or streamed tar)."""

from __future__ import annotations

from modality_detect import detect_modality_from_directory, infer_modality_from_profile

from .rag_match import match_profile
from .schema import DirectoryProfile, RouteDecision


def decide_pipeline(profile: DirectoryProfile, *, compare_legacy_path: str | None = None) -> RouteDecision:
    hits = match_profile(profile, top_k=3)
    best = hits[0] if hits else {}
    second = hits[1] if len(hits) > 1 else {}
    conf = 0.35
    if best:
        margin = (best.get("score") or 0) - (second.get("score") or 0)
        conf = min(0.98, 0.45 + 0.08 * (best.get("score") or 0) + 0.05 * margin)
    pipeline = str(best.get("pipeline") or "UNKNOWN")
    rationale = list(best.get("reasons") or [])
    if profile.get("summary_text"):
        rationale.insert(0, profile["summary_text"])

    ann = profile.get("annotation") or {}
    layout = profile.get("layout") or ""
    topo = profile.get("topology") or {}
    if layout in {"flat_csv_json", "flat_csv"} and (topo.get("n_csv") or 0) >= 1 and (topo.get("n_csv_json") or 0) >= 1:
        pipeline = "ULF"
        rationale.append("override: csv+.csv.json pair → ULF")
        conf = max(conf, 0.85)
        best = {**best, "archetype_id": "ulf_magnetometer_pi2", "pipeline": "ULF"}
    elif ann.get("has_mask") and (ann.get("mask_epb_score_mean") or 0) >= 0.45 and not ann.get("has_hek"):
        pipeline = "EPB"
        rationale.append("override: large mask polygons → EPB")
        conf = max(conf, 0.8)
    elif ann.get("has_hek") or ann.get("has_special_shapes") or layout == "data/label":
        pipeline = "AIA"
        conf = max(conf, 0.75)

    decision: RouteDecision = {
        "pipeline": pipeline,
        "archetype_id": str(best.get("archetype_id") or ""),
        "confidence": round(conf, 3),
        "layout": layout,
        "rationale": rationale,
        "rag_hits": hits,
        "profile": profile,
    }
    if str(profile.get("dir_path") or "").startswith("zip:"):
        decision["legacy_detect"] = infer_modality_from_profile(profile)
    elif compare_legacy_path:
        decision["legacy_detect"] = detect_modality_from_directory(compare_legacy_path)
    return decision