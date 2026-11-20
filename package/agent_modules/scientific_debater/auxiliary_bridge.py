"""Merge debater auxiliary_metrics into prepare_* item for Pass1/2 (experimental, env-gated)."""

from __future__ import annotations

import json
import os
from typing import Any

from .script_sandbox import run_auxiliary_metrics


def _load_label(item: dict[str, Any]) -> dict | None:
    label_path = item.get("label_path")
    if label_path and os.path.isfile(label_path):
        try:
            return json.load(open(label_path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _image_path(item: dict[str, Any]) -> str | None:
    path = item.get("image_path")
    if path and os.path.isfile(path):
        return path
    return None


def attach_auxiliary_to_item(item: dict[str, Any], script_path: str | None = None) -> dict[str, Any]:
    script_path = script_path or os.environ.get("DEBATER_AUXILIARY_SCRIPT") or ""
    if not script_path or not os.path.isfile(script_path):
        return item
    img = _image_path(item)
    if not img:
        return item
    code = open(script_path, encoding="utf-8").read()
    label = _load_label(item)
    raw = run_auxiliary_metrics(code, img, label)
    if raw.get("error"):
        item.setdefault("metrics", {})["debater_auxiliary_error"] = raw
        return item

    coverage = raw.get("pipeline_coverage")
    if not isinstance(coverage, list):
        coverage = _infer_coverage(raw)
        raw["pipeline_coverage"] = coverage

    metrics = item.setdefault("metrics", {})
    pre = raw.get("pre_pass1") if isinstance(raw.get("pre_pass1"), dict) else {}
    p1 = raw.get("pass1_context") if isinstance(raw.get("pass1_context"), dict) else {}
    p2h = raw.get("pass2_hint") if isinstance(raw.get("pass2_hint"), dict) else {}
    scalars = {k: v for k, v in raw.items() if k not in ("pre_pass1", "pass1_context", "pass2_hint", "pipeline_coverage")}

    metrics["debater_auxiliary"] = {
        "pipeline_coverage": coverage,
        "pre_pass1": pre or scalars,
        "pass1_context": p1,
        "pass2_hint": p2h,
        "scalars_flat": scalars,
        "script": os.path.basename(script_path),
    }
    return item


def _infer_coverage(raw: dict[str, Any]) -> list[str]:
    stages = []
    if raw.get("pre_pass1") or any(k in raw for k in ("radial_gradient", "local_contrast", "noise_fraction")):
        stages.append("L1_pre_pass1")
    if raw.get("pass1_context"):
        stages.append("L2_pass1_context")
    if raw.get("pass2_hint"):
        stages.append("L3_pass2_hint")
    if not stages:
        stages.append("L1_pre_pass1")
    return stages


def _find_label(dir_path: str, png: str) -> str | None:
    base = os.path.basename(png)
    candidates = [
        os.path.join(dir_path, "label", base + ".json"),
        os.path.join(dir_path, base + ".json"),
        png + ".json",
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def verify_pass1_hook(
    *,
    dir_path: str,
    script_path: str,
    modality: str = "AIA",
    limit: int = 1,
) -> dict[str, Any]:
    """Dry-run prepare_* + attach when label exists; else lightweight attach only."""
    from dataset_router.visual_probe import collect_png_paths

    from physics_inspect import prepare_aia, prepare_epb

    os.environ["DEBATER_AUXILIARY_SCRIPT"] = script_path
    dir_path = os.path.abspath(dir_path)
    pngs = collect_png_paths(dir_path, limit=max(limit, 3))
    if not pngs:
        return {"ok": False, "error": "no_png"}
    results = []
    for png in pngs:
        lab = _find_label(dir_path, png)
        used_prepare = False
        try:
            if lab and modality == "EPB":
                item = prepare_epb(png, lab)
                used_prepare = True
            elif lab and modality == "AIA":
                item = prepare_aia(png, lab)
                used_prepare = True
            else:
                item = {
                    "id": os.path.basename(png),
                    "modality": modality,
                    "image_path": png,
                    "label_path": lab,
                    "metrics": {},
                }
                item = attach_auxiliary_to_item(item, script_path)
        except ValueError:
            item = {
                "id": os.path.basename(png),
                "modality": modality,
                "image_path": png,
                "label_path": lab,
                "metrics": {},
            }
            item = attach_auxiliary_to_item(item, script_path)
        aux = (item.get("metrics") or {}).get("debater_auxiliary")
        results.append(
            {
                "object": os.path.basename(png),
                "used_prepare": used_prepare,
                "has_label": bool(lab),
                "has_auxiliary": bool(aux),
                "coverage": (aux or {}).get("pipeline_coverage"),
                "keys_pre": list(((aux or {}).get("pre_pass1") or {}).keys())[:12],
            }
        )
        if len(results) >= limit:
            break
    ok = all(r.get("has_auxiliary") for r in results)
    return {"ok": ok, "results": results, "script": script_path}