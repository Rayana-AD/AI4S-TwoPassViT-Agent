"""Build DirectoryProfile from layout + JSON schema sampling (no hardcoded dir names)."""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

from audits import pixel_rings

from modality_detect import _mask_epb_likelihood

from .schema import AnnotationStats, DirectoryProfile
from .visual_probe import probe_directory


def _iter_json_paths(dir_path: str, sample: int) -> list[str]:
    out: list[str] = []
    label = os.path.join(dir_path, "label")
    scan_roots = [label] if os.path.isdir(label) else [dir_path]
    for root in scan_roots:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            if not name.endswith(".json"):
                continue
            if name.endswith(".csv.json"):
                out.append(os.path.join(root, name))
                continue
            if name.endswith(".json"):
                out.append(os.path.join(root, name))
            if len(out) >= sample:
                return out
    return out[:sample]


def _layout_topology(dir_path: str) -> tuple[str, dict[str, Any]]:
    names = os.listdir(dir_path)
    data_dir = os.path.join(dir_path, "data")
    label_dir = os.path.join(dir_path, "label")
    n_csv = sum(1 for n in names if n.endswith(".csv") and not n.endswith(".csv.json"))
    n_csv_json = sum(1 for n in names if n.endswith(".csv.json"))
    n_png_top = sum(1 for n in names if n.endswith(".png"))
    n_json_top = sum(1 for n in names if n.endswith(".json") and not n.endswith(".csv.json"))
    topo: dict[str, Any] = {
        "n_csv": n_csv,
        "n_csv_json": n_csv_json,
        "n_png_top": n_png_top,
        "n_json_top": n_json_top,
        "has_data_label": os.path.isdir(data_dir) and os.path.isdir(label_dir),
    }
    if topo["has_data_label"]:
        topo["n_png_data"] = sum(1 for n in os.listdir(data_dir) if n.endswith(".png")) if os.path.isdir(data_dir) else 0
        topo["n_json_label"] = sum(1 for n in os.listdir(label_dir) if n.endswith(".json")) if os.path.isdir(label_dir) else 0
        return "data/label", topo
    if n_csv and n_csv_json:
        layout = "flat_csv_json"
        topo["csv_pair_ratio"] = round(min(n_csv, n_csv_json) / max(n_csv, 1), 3)
        return layout, topo
    if n_png_top or n_json_top:
        return "flat_png_json", topo
    return "unknown", topo


def annotation_stats_from_objects(objects: list[dict]) -> AnnotationStats:
    keys_counter: Counter[str] = Counter()
    has_hek = has_mask = has_special = has_ulf = has_rings = 0
    epb_scores: list[float] = []
    verts: list[int] = []
    for obj in objects:
        if isinstance(obj.get("ulf_event_annotation"), dict):
            has_ulf += 1
            keys_counter["ulf_event_annotation"] += 1
        if "hek_event_annotation" in obj:
            has_hek += 1
            keys_counter["hek_event_annotation"] += 1
        sci = obj.get("science_annotation") or {}
        if isinstance(sci, dict):
            if sci.get("specialShapes"):
                has_special += 1
                keys_counter["science_annotation.specialShapes"] += 1
            mask = sci.get("mask")
            if isinstance(mask, dict) and (mask.get("shapes") or []):
                has_mask += 1
                keys_counter["science_annotation.mask"] += 1
        rings = pixel_rings(obj)
        if rings:
            has_rings += 1
            epb_scores.append(_mask_epb_likelihood(obj, rings))
            for r in rings:
                pts = r.get("points") or []
                verts.append(len(pts))
    checked = len(objects)
    return {
        "n_json_sampled": checked,
        "keys_frequency": dict(keys_counter.most_common(12)),
        "has_hek": has_hek,
        "has_mask": has_mask,
        "has_special_shapes": has_special,
        "has_ulf": has_ulf,
        "has_pixel_rings": has_rings,
        "mask_epb_score_mean": round(sum(epb_scores) / len(epb_scores), 3) if epb_scores else 0.0,
        "avg_vertices_per_ring": round(sum(verts) / len(verts), 2) if verts else 0.0,
    }


def _annotate_sample(dir_path: str, *, sample: int) -> AnnotationStats:
    objects: list[dict] = []
    for path in _iter_json_paths(dir_path, sample):
        try:
            objects.append(json.load(open(path, encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return annotation_stats_from_objects(objects)


def profile_from_parts(
    *,
    dir_id: str,
    dir_path: str,
    layout: str,
    topo: dict[str, Any],
    annotation: AnnotationStats,
    visual: dict[str, Any],
) -> DirectoryProfile:
    return {
        "dir_id": dir_id,
        "dir_path": dir_path,
        "layout": layout,
        "topology": topo,
        "annotation": annotation,
        "visual": visual,
        "summary_text": _summary(layout, topo, annotation, visual),
    }


def _summary(layout: str, topo: dict, ann: AnnotationStats, visual: dict) -> str:
    parts = [f"layout={layout}"]
    if ann.get("has_ulf"):
        parts.append("annotation=ulf_event")
    elif ann.get("has_mask") and (ann.get("mask_epb_score_mean") or 0) >= 0.45:
        parts.append("annotation=epb_mask")
    elif ann.get("has_hek") or ann.get("has_special_shapes"):
        parts.append("annotation=hek_or_special_shapes")
    tags = list((visual.get("tag_counts") or {}).keys())[:4]
    if tags:
        parts.append("visual=" + ",".join(tags))
    if topo.get("has_data_label"):
        parts.append(f"data/label png={topo.get('n_png_data', 0)} json={topo.get('n_json_label', 0)}")
    return "; ".join(parts)


def profile_directory(dir_path: str, *, json_sample: int = 20, image_sample: int = 4) -> DirectoryProfile:
    dir_path = os.path.abspath(dir_path)
    layout, topo = _layout_topology(dir_path)
    ann = _annotate_sample(dir_path, sample=json_sample)
    visual = probe_directory(dir_path, max_images=image_sample)
    profile: DirectoryProfile = {
        "dir_id": os.path.basename(os.path.normpath(dir_path)),
        "dir_path": dir_path,
        "layout": layout,
        "topology": topo,
        "annotation": ann,
        "visual": visual,
        "summary_text": _summary(layout, topo, ann, visual),
    }
    return profile