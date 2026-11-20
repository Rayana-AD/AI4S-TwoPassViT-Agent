"""Lightweight RAG: score archetype corpus against a DirectoryProfile (no vectors DB)."""

from __future__ import annotations

import json
import os
import re
from typing import Any


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_/.]+", text.lower()))


def _load_corpus() -> list[dict[str, Any]]:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "corpus", "pipeline_archetypes.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _profile_tokens(profile: dict[str, Any]) -> set[str]:
    layout = str(profile.get("layout") or "")
    ann = profile.get("annotation") or {}
    vis = profile.get("visual") or {}
    topo = profile.get("topology") or {}
    bag = [
        layout,
        profile.get("summary_text") or "",
        " ".join(ann.get("keys_frequency") or {}),
        " ".join(vis.get("tag_counts") or {}),
        str(topo),
    ]
    if ann.get("has_ulf"):
        bag.append("ulf_event_annotation flat_csv_json time_series_waveform pi2")
    if ann.get("has_mask") and (ann.get("mask_epb_score_mean") or 0) >= 0.45:
        bag.append("science_annotation.mask epb fish_eye depletion")
    if ann.get("has_hek"):
        bag.append("hek_event_annotation hek sdo_aia ring")
    if ann.get("has_special_shapes"):
        bag.append("specialShapes ssusi auroral nadir")
    if layout == "data/label":
        bag.append("data/label sdo_aia_hek_ar hmi_sharp")
    if layout == "flat_csv_json":
        bag.append("ulf_magnetometer_pi2 imagenet csv")
    return _tokens(" ".join(bag))


def score_archetype(profile: dict[str, Any], entry: dict[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    ptoks = _profile_tokens(profile)
    ann = profile.get("annotation") or {}
    layout = profile.get("layout") or ""
    vis_tags = set((profile.get("visual") or {}).get("tag_counts") or {})

    for hint in entry.get("layout_hints") or []:
        if hint == layout or (hint in layout) or (layout in hint):
            score += 2.0
            reasons.append(f"layout≈{hint}")

    for marker in entry.get("annotation_markers") or []:
        key = marker.split(".")[-1] if "." in marker else marker
        freq = (ann.get("keys_frequency") or {}).get(marker) or (ann.get("keys_frequency") or {}).get(key)
        if marker == "ulf_event_annotation" and ann.get("has_ulf"):
            score += 4.0
            reasons.append("ulf_event present")
        elif marker == "science_annotation.mask" and ann.get("has_mask"):
            score += 3.0
            reasons.append("mask present")
        elif marker == "hek_event_annotation" and ann.get("has_hek"):
            score += 2.5
            reasons.append("hek present")
        elif marker == "science_annotation.specialShapes" and ann.get("has_special_shapes"):
            score += 2.5
            reasons.append("specialShapes present")
        elif freq:
            score += 1.5
            reasons.append(f"key {marker}")

    if entry.get("pipeline") == "EPB" and (ann.get("mask_epb_score_mean") or 0) >= 0.45:
        score += 2.0
        reasons.append("high mask_epb_score")
    if entry.get("pipeline") == "AIA" and ann.get("has_hek") and (ann.get("mask_epb_score_mean") or 0) < 0.45:
        score += 1.5

    for vhint in entry.get("visual_hints") or []:
        if vhint in vis_tags:
            score += 1.2
            reasons.append(f"visual {vhint}")

    corpus_text = json.dumps(entry, ensure_ascii=False)
    overlap = len(ptoks & _tokens(corpus_text))
    score += min(overlap * 0.15, 2.0)

    archetype = entry.get("archetype_id") or ""
    if layout == "flat_csv_json" and entry.get("pipeline") == "ULF":
        score += 3.0
        reasons.append("ULF csv+json layout")
    if layout == "flat_png_json" and archetype == "dmsp_ssusi_aurora" and ann.get("has_special_shapes"):
        score += 2.0

    return score, reasons


def match_profile(profile: dict[str, Any], *, top_k: int = 3) -> list[dict[str, Any]]:
    corpus = _load_corpus()
    ranked: list[tuple[float, dict[str, Any], list[str]]] = []
    for entry in corpus:
        sc, reasons = score_archetype(profile, entry)
        ranked.append((sc, entry, reasons))
    ranked.sort(key=lambda x: -x[0])
    hits: list[dict[str, Any]] = []
    for sc, entry, reasons in ranked[:top_k]:
        hits.append(
            {
                "score": round(sc, 3),
                "archetype_id": entry.get("archetype_id"),
                "title": entry.get("title"),
                "pipeline": entry.get("pipeline"),
                "physics_track": entry.get("physics_track"),
                "references": entry.get("references") or [],
                "reasons": reasons,
            }
        )
    return hits