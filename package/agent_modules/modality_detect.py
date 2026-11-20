"""Detect roadshow modality (AIA / EPB / ULF) for a path, JSON, or directory."""

from __future__ import annotations

import json
import os
from typing import Any

from audits import pixel_rings, real_frame


def _polygon_area(points: list) -> float:
    if len(points) < 3:
        return 0.0
    pts = [(float(p[0]), float(p[1])) for p in points if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _mask_epb_likelihood(obj: dict, rings: list[dict]) -> float:
    """Higher → more EPB-like (large / irregular masks)."""
    if not rings:
        return 0.0
    frame = real_frame(obj) or (4096, 4096)
    frame_area = max(float(frame[0] * frame[1]), 1.0)
    scores: list[float] = []
    for ring in rings:
        pts = ring.get("points") or []
        area = _polygon_area(pts)
        frac = area / frame_area
        n_vert = len(pts)
        compact = (n_vert >= 8) or (frac > 0.015)
        large = frac > 0.008
        scores.append(0.6 * min(1.0, frac / 0.05) + 0.4 * (1.0 if compact else 0.2))
    return max(scores) if scores else 0.0


def detect_modality_from_json(obj: dict) -> str:
    if isinstance(obj.get("ulf_event_annotation"), dict):
        return "ULF"
    science = obj.get("science_annotation") or {}
    mask = science.get("mask") if isinstance(science, dict) else None
    if isinstance(mask, dict) and (mask.get("shapes") or []):
        rings = pixel_rings(obj)
        return "EPB" if _mask_epb_likelihood(obj, rings) >= 0.45 else "AIA"
    if "hek_event_annotation" in obj:
        return "AIA"
    if isinstance(science, dict) and (science.get("specialShapes") or []):
        return "AIA"
    rings = pixel_rings(obj)
    if rings:
        return "EPB" if _mask_epb_likelihood(obj, rings) >= 0.45 else "AIA"
    basic = obj.get("basic_annotation") or {}
    fn = str(basic.get("fileName") or "")
    if fn.endswith(".csv"):
        return "ULF"
    if fn.endswith(".png"):
        return "EPB"
    return "UNKNOWN"


def detect_modality_from_path(path: str) -> str:
    low = path.lower()
    if low.endswith(".csv"):
        return "ULF"
    if low.endswith(".csv.json"):
        return "ULF"
    if low.endswith(".json"):
        try:
            obj = json.load(open(path, encoding="utf-8"))
            return detect_modality_from_json(obj)
        except (OSError, json.JSONDecodeError):
            return "UNKNOWN"
    if low.endswith(".png"):
        return "IMAGE"
    return "UNKNOWN"


def detect_modality_from_directory(dir_path: str, *, sample: int = 40) -> dict[str, Any]:
    """Scan directory layout + sample JSON to infer primary modality."""
    if not os.path.isdir(dir_path):
        return {"modality": "UNKNOWN", "reason": "not a directory"}
    names = os.listdir(dir_path)
    n_csv = sum(1 for n in names if n.endswith(".csv") and not n.endswith(".csv.json"))
    n_png_top = sum(1 for n in names if n.endswith(".png"))
    data_dir = os.path.join(dir_path, "data")
    label_dir = os.path.join(dir_path, "label")
    has_data_label = os.path.isdir(data_dir) and os.path.isdir(label_dir)
    if has_data_label:
        n_png = sum(1 for n in os.listdir(data_dir) if n.endswith(".png")) if os.path.isdir(data_dir) else 0
        n_label = sum(1 for n in os.listdir(label_dir) if n.endswith(".json")) if os.path.isdir(label_dir) else 0
        if n_png or n_label:
            return {
                "modality": "AIA",
                "layout": "data/label",
                "n_png": n_png,
                "n_label_json": n_label,
            }
    n_png = n_png_top
    n_csv_json = sum(1 for n in names if n.endswith(".csv.json"))
    # ULF: paired time-series + sidecar labels (robust for tiny subsamples)
    if n_csv >= 1 and n_csv_json >= 1 and n_png_top == 0 and not has_data_label:
        ulf_hits = 0
        scanned = 0
        for name in sorted(names):
            if not name.endswith(".csv.json"):
                continue
            if scanned >= min(sample, 8):
                break
            scanned += 1
            try:
                obj = json.load(open(os.path.join(dir_path, name), encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(obj.get("ulf_event_annotation"), dict) or detect_modality_from_json(obj) == "ULF":
                ulf_hits += 1
        if ulf_hits > 0 or n_csv_json >= n_csv:
            return {
                "modality": "ULF",
                "layout": "flat_csv_json",
                "n_csv": n_csv,
                "n_csv_json": n_csv_json,
                "ulf_sample_hits": ulf_hits,
            }
    votes: dict[str, int] = {"AIA": 0, "EPB": 0, "ULF": 0}
    epb_scores: list[float] = []
    checked = 0
    json_names = sorted(
        n
        for n in names
        if n.endswith(".json")
    )
    # Prefer plain .json before .csv.json when sampling mixed flat dirs
    json_names.sort(key=lambda x: (x.endswith(".csv.json"), x))
    for name in json_names:
        if checked >= sample:
            break
        try:
            obj = json.load(open(os.path.join(dir_path, name), encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        m = detect_modality_from_json(obj)
        if m in votes:
            votes[m] += 1
        rings = pixel_rings(obj)
        if rings:
            epb_scores.append(_mask_epb_likelihood(obj, rings))
        checked += 1
    if checked == 0 and n_png:
        return {"modality": "EPB", "layout": "flat_png", "n_png": n_png, "note": "no json sampled"}
    if not checked:
        return {"modality": "UNKNOWN", "layout": "flat_mixed", "n_png": n_png, "n_csv": n_csv}

    def _score(k: str) -> float:
        base = float(votes.get(k) or 0)
        if k == "EPB" and epb_scores:
            base += 0.35 * (sum(epb_scores) / len(epb_scores))
        if k == "AIA":
            base += 0.15 * votes.get("AIA", 0)
        if k == "ULF":
            base += 0.2 * votes.get("ULF", 0)
        return base

    ranked = sorted(votes.keys(), key=lambda k: (-_score(k), k))
    winner = ranked[0] if _score(ranked[0]) > 0 else "UNKNOWN"
    if winner == "UNKNOWN":
        winner = "EPB" if n_png and not n_csv else ("ULF" if n_csv and n_csv_json else "UNKNOWN")
    return {
        "modality": winner,
        "layout": "flat_mixed",
        "votes": votes,
        "n_json_sampled": checked,
        "n_png": n_png,
        "n_csv": n_csv,
        "n_csv_json": n_csv_json,
        "tie_break": "epb_score_bias" if epb_scores else "vote_only",
        "mask_epb_score_mean": round(sum(epb_scores) / len(epb_scores), 3) if epb_scores else 0.0,
    }


def infer_modality_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Same rules as directory detect, using streamed/small-sample profile (no listdir)."""
    layout = str(profile.get("layout") or "")
    topo = profile.get("topology") or {}
    ann = profile.get("annotation") or {}
    n_csv = int(topo.get("n_csv") or 0)
    n_csv_json = int(topo.get("n_csv_json") or 0)
    n_png = int(topo.get("n_png_top") or 0) + int(topo.get("n_png_data") or 0)
    if layout == "data/label" or topo.get("has_data_label"):
        return {"modality": "AIA", "layout": "data/label", **{k: topo.get(k) for k in ("n_png_data", "n_json_label")}}
    if layout == "flat_csv_json" and n_csv >= 1 and n_csv_json >= 1:
        return {
            "modality": "ULF",
            "layout": "flat_csv_json",
            "n_csv": n_csv,
            "n_csv_json": n_csv_json,
            "ulf_hits": ann.get("has_ulf") or 0,
        }
    if ann.get("has_ulf"):
        return {"modality": "ULF", "layout": layout, "source": "profile_annotation"}
    if ann.get("has_mask") and (ann.get("mask_epb_score_mean") or 0) >= 0.45 and not ann.get("has_hek"):
        return {"modality": "EPB", "layout": layout, "mask_epb_score_mean": ann.get("mask_epb_score_mean")}
    if ann.get("has_hek") or ann.get("has_special_shapes"):
        return {"modality": "AIA", "layout": layout}
    if n_png and not n_csv:
        return {"modality": "EPB", "layout": layout, "note": "png_only_fallback"}
    return {"modality": "UNKNOWN", "layout": layout}


def resolve_pipeline_modality(
    dir_path: str | None = None,
    label_path: str | None = None,
    data_path: str | None = None,
) -> str:
    """
    Entry for agent: known types use standard pipelines; unknown mask → AIA/EPB heuristic; series → ULF.
    """
    if label_path and os.path.isfile(label_path):
        try:
            obj = json.load(open(label_path, encoding="utf-8"))
            m = detect_modality_from_json(obj)
            if m != "UNKNOWN":
                return m
        except (OSError, json.JSONDecodeError):
            pass
    if data_path:
        m = detect_modality_from_path(data_path)
        if m in {"ULF", "AIA", "EPB"}:
            return m
    if dir_path:
        return str(detect_modality_from_directory(dir_path).get("modality") or "UNKNOWN")
    return "UNKNOWN"


def looks_like_dataset_dir(dir_path: str) -> bool:
    """True if dir looks like one OPC sample folder (not a parent of many)."""
    if not os.path.isdir(dir_path):
        return False
    if os.path.isdir(os.path.join(dir_path, "data")) and os.path.isdir(os.path.join(dir_path, "label")):
        return True
    try:
        names = os.listdir(dir_path)
    except OSError:
        return False
    n_csv = sum(1 for n in names if n.endswith(".csv") and not n.endswith(".csv.json"))
    n_csv_json = sum(1 for n in names if n.endswith(".csv.json"))
    n_json = sum(1 for n in names if n.endswith(".json") and not n.endswith(".csv.json"))
    n_png = sum(1 for n in names if n.endswith(".png"))
    if n_csv and n_csv_json:
        return True
    if n_png and n_json:
        return True
    return False


def list_dataset_dirs(root: str) -> list[str]:
    """If root is a dataset, return [root]; if it contains dataset children, return those."""
    if not os.path.isdir(root):
        return []
    children: list[str] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(root, name)
        if os.path.isdir(path) and looks_like_dataset_dir(path):
            children.append(os.path.abspath(path))
    if children:
        return children
    if looks_like_dataset_dir(root):
        return [os.path.abspath(root)]
    return []
