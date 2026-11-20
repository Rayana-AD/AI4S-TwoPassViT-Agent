"""Two-pass physics-informed VLM inspection (dataset JSON overlay + metrics)."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from physics_metrics import (
    aia_metrics_for_image,
    annotation_overlap_audit,
    epb_metrics_for_image,
    load_thresholds,
    mechanical_coverage_audit,
    missed_label_candidates_aia,
    missed_label_candidates_epb,
    ring_audit_for_image,
    ring_audit_for_miss_candidates,
    ulf_merge_threshold_proposal,
    ulf_miss_interval_candidates,
    ulf_pi2_metrics,
    ulf_pass2_audit_from_thresholds,
    ulf_sliding_window_scan,
    ulf_threshold_calibration,
    ulf_window_metrics,
)
from label_overlay import render_json_overlay
from physics_prompts import (
    AIA_TASK,
    EPB_TASK,
    PASS1_FORMAT,
    PASS1_TASK,
    PASS2_FORMAT,
    PASS2_TASK,
    ULF_PASS1_FORMAT,
    ULF_PASS1_TASK,
    ULF_PASS2_FORMAT,
    ULF_PASS2_TASK,
    ULF_TASK,
)
from vision import chat_with_usage, load_secrets


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}


def _labeled_region_count(item: dict[str, Any]) -> int:
    return len((item.get("metrics") or {}).get("labeled_regions") or [])


def _pass1_max_tokens(n_regions: int) -> int:
    """Enough JSON for many regions (e.g. 19 polygons) without truncating."""
    return min(4096, max(1200, 200 + n_regions * 90))


def _pass2_max_tokens(n_regions: int) -> int:
    """Pass2 reasons cite ring + gradient numbers — needs more tokens than pass1."""
    return min(8192, max(2000, 350 + n_regions * 130))


def normalize_pass1(parsed: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Align pass1 regions with labeled_regions; surface missing/extra ids."""
    labeled = (item.get("metrics") or {}).get("labeled_regions") or []
    expected_ids = [row.get("region_id") for row in labeled]
    by_id = {
        r.get("region_id"): r
        for r in (parsed.get("regions") or [])
        if r.get("region_id") is not None
    }
    per_region: list[dict[str, Any]] = []
    missing: list[Any] = []
    for row in labeled:
        rid = row.get("region_id")
        got = by_id.get(rid) or {}
        conf = got.get("confidence_plausible")
        if conf is None and got.get("preliminary_verdict"):
            v = str(got.get("preliminary_verdict", ""))
            conf = {"合理": 0.75, "不确定": 0.5, "不合理": 0.2}.get(v, 0.5)
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        if conf_f is not None:
            conf_f = max(0.0, min(1.0, conf_f))
        entry = {
            "region_id": rid,
            "caption": row.get("caption") or got.get("caption"),
            "structure_guess": got.get("structure_guess", ""),
            "confidence_plausible": conf_f,
            "reason": got.get("reason", ""),
        }
        if rid not in by_id:
            missing.append(rid)
            entry["missing_in_model_output"] = True
        per_region.append(entry)
    extra_ids = [rid for rid in by_id if rid not in expected_ids]
    return {
        "n_regions_expected": len(labeled),
        "n_regions_returned": len(parsed.get("regions") or []),
        "missing_region_ids": missing,
        "extra_region_ids": extra_ids,
        "complete": not missing and not extra_ids,
        "per_region": per_region,
        "mean_confidence_plausible": (
            sum(r["confidence_plausible"] for r in per_region if r["confidence_plausible"] is not None)
            / max(1, sum(1 for r in per_region if r["confidence_plausible"] is not None))
            if per_region
            else None
        ),
    }


def _maybe_attach_debater_auxiliary(item: dict[str, Any]) -> dict[str, Any]:
    if not os.environ.get("DEBATER_AUXILIARY_SCRIPT"):
        return item
    try:
        from scientific_debater.auxiliary_bridge import attach_auxiliary_to_item

        return attach_auxiliary_to_item(item)
    except Exception:
        return item


def _metrics_for_vlm(metrics: dict[str, Any], overlay_meta: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in metrics.items() if k != "label_reference"}
    out["overlay"] = {
        "mode": overlay_meta.get("overlay_mode"),
        "note": overlay_meta.get("note"),
    }
    out["crop_origin"] = overlay_meta.get("crop_origin")
    out["display_width"] = overlay_meta.get("display_width")
    out["display_height"] = overlay_meta.get("display_height")
    labeled = []
    refs = metrics.get("label_reference") or []
    for row in overlay_meta.get("labeled_regions") or []:
        entry = dict(row)
        idx = entry.get("region_id")
        if isinstance(idx, int) and idx < len(refs):
            entry["physics"] = refs[idx].get("metrics")
            entry["bbox_full"] = refs[idx].get("bbox_full")
        labeled.append(entry)
    out["labeled_regions"] = labeled
    return out


def prepare_aia(image_path: str, label_path: str | None = None, *, overlay: bool = True) -> dict[str, Any]:
    metrics = aia_metrics_for_image(image_path, label_path)
    if overlay and label_path and os.path.isfile(label_path):
        png, overlay_meta = render_json_overlay(image_path, label_path, max_side=512)
    else:
        raise ValueError("AIA 检验需要 label JSON 以绘制 dataset 轮廓")
    metrics_vlm = _metrics_for_vlm(metrics, overlay_meta)
    if label_path and os.path.isfile(label_path):
        mech = mechanical_coverage_audit(label_path)
        metrics_vlm["mechanical_coverage_audit"] = mech
        metrics_vlm["missed_label_candidates"] = missed_label_candidates_aia(image_path, label_path)
        ov = annotation_overlap_audit(label_path)
        ov["mechanical_coverage"] = mech
        metrics_vlm["overlap_audit"] = ov
    item = {
        "id": os.path.basename(image_path),
        "modality": "AIA",
        "png": png,
        "metrics": metrics_vlm,
        "metrics_full": metrics,
        "task": AIA_TASK,
        "inspection_mode": "json_overlay",
        "image_path": image_path,
        "label_path": label_path,
    }
    return _maybe_attach_debater_auxiliary(item)


def prepare_epb(image_path: str, label_path: str | None = None, *, overlay: bool = True) -> dict[str, Any]:
    metrics = epb_metrics_for_image(image_path, label_path)
    if overlay and label_path and os.path.isfile(label_path):
        png, overlay_meta = render_json_overlay(image_path, label_path, max_side=512)
    else:
        raise ValueError("EPB 检验需要 label JSON 以绘制 dataset 轮廓")
    metrics_vlm = _metrics_for_vlm(metrics, overlay_meta)
    if label_path and os.path.isfile(label_path):
        mech = mechanical_coverage_audit(label_path)
        metrics_vlm["mechanical_coverage_audit"] = mech
        metrics_vlm["missed_label_candidates"] = metrics.get("missed_label_candidates") or missed_label_candidates_epb(
            image_path, label_path
        )
        ov = annotation_overlap_audit(label_path)
        ov["mechanical_coverage"] = mech
        metrics_vlm["overlap_audit"] = ov
    item = {
        "id": os.path.basename(image_path),
        "modality": "EPB",
        "png": png,
        "metrics": metrics_vlm,
        "metrics_full": metrics,
        "task": EPB_TASK,
        "inspection_mode": "json_overlay",
        "image_path": image_path,
        "label_path": label_path,
    }
    return _maybe_attach_debater_auxiliary(item)


def prepare_ulf(csv_path: str, label_path: str | None = None) -> dict[str, Any]:
    import numpy as np

    from vision import render_waveform

    obj = json.load(open(label_path, encoding="utf-8")) if label_path else {}
    png = render_waveform(csv_path, obj, draw_windows=True)
    h_vals: list[float] = []
    with open(csv_path, encoding="utf-8", errors="replace") as handle:
        header = [name.strip() for name in handle.readline().split(",")]
        if "H" in header:
            idx = header.index("H")
            for line in handle:
                parts = line.split(",")
                try:
                    h_vals.append(float(parts[idx]))
                except (ValueError, IndexError):
                    h_vals.append(float("nan"))
    h = np.asarray(h_vals, dtype=np.float64)
    pi2_hour = ulf_pi2_metrics(h)
    metrics_full: dict[str, Any] = {
        "modality": "ULF",
        "file": os.path.basename(csv_path),
        "n_samples": int(h.size),
        **pi2_hour,
    }
    calibration: dict[str, Any] = {}
    if h.size >= 100:
        calibration = ulf_threshold_calibration(h, label_path=label_path)
        metrics_full["threshold_calibration"] = calibration
        metrics_full["sliding_window_scan"] = ulf_sliding_window_scan(h, adaptive=True)
    if label_path:
        from audits import window_spans

        spans = window_spans(obj, len(h))
        metrics_full["windows_labeled"] = []
        for rid, span in enumerate(spans):
            if span.get("i0") is None:
                continue
            i0, i1 = int(span["i0"]), int(span["i1"])
            metrics_full["windows_labeled"].append({
                "region_id": rid,
                "caption": f"window_{i0}_{i1}",
                "i0": i0,
                "i1": i1,
                **ulf_window_metrics(h, i0, i1),
            })
        uea = obj.get("ulf_event_annotation") or {}
        events = uea.get("matched_events") or []
        metrics_full["annotation_snippet"] = {
            "has_events": uea.get("has_events"),
            "event_count": uea.get("event_count"),
            "matched_events": [
                {
                    "start_dt": ev.get("start_dt"),
                    "end_dt": ev.get("end_dt"),
                    "label": ev.get("label"),
                }
                for ev in events[:12]
            ],
        }
    metrics_vlm = {
        k: v
        for k, v in metrics_full.items()
        if k not in ("windows_labeled", "sliding_window_scan")
    }
    if calibration.get("valid"):
        metrics_vlm["threshold_calibration"] = calibration
        metrics_vlm["sliding_window_scan"] = calibration.get("sliding_window_scan") or {}
    metrics_vlm["labeled_regions"] = metrics_full.get("windows_labeled") or []
    metrics_vlm["pi2_full_hour"] = {
        "band_hz": pi2_hour.get("band_hz"),
        "envelope_quiet_p30": pi2_hour.get("envelope_quiet"),
        "peak_over_quiet": pi2_hour.get("peak_over_quiet"),
    }
    metrics_vlm["overlay"] = {"mode": "ulf_red_windows", "note": "红色竖线为 dataset 时间窗"}
    if label_path and os.path.isfile(label_path):
        metrics_vlm["missed_label_candidates"] = ulf_miss_interval_candidates(
            csv_path,
            label_path,
            calibration=calibration if calibration.get("valid") else None,
        )
    return {
        "id": os.path.basename(csv_path),
        "modality": "ULF",
        "png": png,
        "metrics": metrics_vlm,
        "metrics_full": metrics_full,
        "task": ULF_TASK,
        "inspection_mode": "json_overlay",
        "csv_path": csv_path,
        "label_path": label_path,
    }


def _pass_format(modality: str | None, pass_tag: str) -> str:
    if pass_tag == "pass1":
        base = PASS1_FORMAT
        return base + ("\n" + ULF_PASS1_FORMAT if modality == "ULF" else "")
    base = PASS2_FORMAT
    return base + ("\n" + ULF_PASS2_FORMAT if modality == "ULF" else "")


def _pass_prompt_text(task: str, item: dict[str, Any], pass_tag: str, extra: str = "") -> str:
    metrics_json = json.dumps(item["metrics"], ensure_ascii=False)
    thresholds = load_thresholds()
    modality = item.get("modality")
    if modality == "ULF":
        stage_task = (
            (ULF_PASS1_TASK + "\n" + PASS1_TASK)
            if pass_tag == "pass1"
            else (ULF_PASS2_TASK + "\n" + PASS2_TASK)
        )
    else:
        stage_task = PASS1_TASK if pass_tag == "pass1" else PASS2_TASK
    n_reg = len((item.get("metrics") or {}).get("labeled_regions") or [])
    pass1_hint = (
        f"本图 labeled_regions 共 {n_reg} 条，Pass1 的 regions 必须输出 {n_reg} 条且 region_id 对齐。\n"
        if pass_tag == "pass1" and n_reg
        else ""
    )
    return (
        f"{task}\n{stage_task}\n阶段：{pass_tag}\n"
        f"{pass1_hint}"
        f"{extra}\n"
        f"metrics：\n{metrics_json}\n"
        f"参考阈值：{json.dumps(thresholds.get(item['modality'], {}), ensure_ascii=False)}\n"
        f"{_pass_format(modality, pass_tag)}"
    )


def _image_message(task: str, item: dict[str, Any], pass_tag: str, extra: str = "") -> list:
    text = _pass_prompt_text(task, item, pass_tag, extra=extra)
    encoded = base64.b64encode(item["png"]).decode()
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}},
    ]


def inspect_pass1(item: dict[str, Any], secrets: dict | None = None) -> dict[str, Any]:
    secrets = load_secrets() if secrets is None else secrets
    n_reg = _labeled_region_count(item)
    content = _image_message(item["task"], item, "pass1")
    result = chat_with_usage(
        content,
        "vision",
        secrets,
        timeout=180,
        max_tokens=_pass1_max_tokens(n_reg),
    )
    parsed = _parse_json_object(result.get("text") or "")
    if parsed and not parsed.get("id"):
        parsed["id"] = item["id"]
    normalized = normalize_pass1(parsed, item) if parsed else normalize_pass1({}, item)
    return {
        "raw": result.get("text"),
        "parsed": parsed,
        "normalized": normalized,
        "usage": result.get("usage"),
        "model": result.get("model"),
        "api_role": "vision",
    }


def inspect_pass2(
    item: dict[str, Any],
    pass1: dict[str, Any],
    secrets: dict | None = None,
    *,
    label_path: str | None = None,
    image_path: str | None = None,
) -> dict[str, Any]:
    secrets = load_secrets() if secrets is None else secrets
    ring_audit: list[dict] = []
    overlap_audit: dict[str, Any] = {}
    miss_ring_audit: list[dict] = []
    window_audit: dict[str, Any] = {}
    if item["modality"] == "ULF" and label_path:
        csv_path = item.get("csv_path") or (image_path if (image_path or "").endswith(".csv") else None)
        if csv_path and os.path.isfile(csv_path):
            cal = (item.get("metrics") or {}).get("threshold_calibration") or {}
            merged = ulf_merge_threshold_proposal(pass1.get("parsed"), cal if cal.get("valid") else None)
            window_audit = ulf_pass2_audit_from_thresholds(csv_path, label_path, merged)
            window_audit["threshold_proposal_merged"] = merged
            item["metrics"]["window_audit"] = window_audit
    if label_path and image_path and item["modality"] in ("AIA", "EPB"):
        ring_audit = ring_audit_for_image(image_path, label_path, item["modality"])
        item["metrics"]["ring_audit"] = ring_audit
        overlap_audit = annotation_overlap_audit(label_path)
        item["metrics"]["overlap_audit"] = overlap_audit
        miss_payload = item["metrics"].get("missed_label_candidates") or {}
        miss_ring_audit = ring_audit_for_miss_candidates(
            image_path,
            miss_payload,
            modality=item["modality"],
        )
        item["metrics"]["miss_ring_audit"] = miss_ring_audit

    api_role = "vision"
    if item["modality"] == "ULF":
        extra = (
            f"Pass1 JSON（含 threshold_proposal）：{json.dumps(pass1.get('parsed') or {}, ensure_ascii=False)}\n"
            f"window_audit（Pass2 数值轨，必须引用）：\n{json.dumps(window_audit, ensure_ascii=False)}\n"
            "【Pass2 输入说明】本阶段不再附带波形图；请仅依据上述 metrics、Pass1 与 window_audit 终判。\n"
        )
        prompt = _pass_prompt_text(item["task"], item, "pass2", extra=extra)
        api_role = "text"
        content: str | list = prompt
    else:
        extra = (
            f"Pass1 JSON：{json.dumps(pass1.get('parsed') or {}, ensure_ascii=False)}\n"
            f"ring_audit（脚本计算，Pass2 必须引用）：\n{json.dumps(ring_audit, ensure_ascii=False)}\n"
            f"overlap_audit（同区多框/嵌套，与单框物理检验分开）：\n{json.dumps(overlap_audit, ensure_ascii=False)}\n"
            f"miss_ring_audit（标注区外、中位尺度候选，audit_miss_label=likely_miss 为漏标）：\n"
            f"{json.dumps(miss_ring_audit, ensure_ascii=False)}"
        )
        content = _image_message(item["task"], item, "pass2", extra=extra)
    n_reg = _labeled_region_count(item)
    result = chat_with_usage(
        content,
        api_role,
        secrets,
        timeout=max(180, 60 + n_reg * 8),
        max_tokens=_pass2_max_tokens(n_reg),
    )
    parsed = _parse_json_object(result.get("text") or "")
    if parsed and not parsed.get("id"):
        parsed["id"] = item["id"]
    return {
        "raw": result.get("text"),
        "parsed": parsed,
        "usage": result.get("usage"),
        "model": result.get("model"),
        "api_role": api_role,
        "ring_audit": ring_audit,
        "miss_ring_audit": miss_ring_audit,
        "overlap_audit": overlap_audit,
        "window_audit": window_audit,
    }


def physics_audit_label(item: dict[str, Any]) -> dict[str, Any]:
    """Rule layer on JSON geometry using computed metrics (evaluation only)."""
    thresholds = load_thresholds()
    modality = item.get("modality")
    refs = (item.get("metrics_full") or {}).get("label_reference") or []
    if modality == "AIA" and refs:
        t = thresholds.get("AIA") or {}
        cnr_min = float(t.get("cnr_min_plausible") or -999)
        flags = []
        for ref in refs:
            cnr = (ref.get("metrics") or {}).get("cnr")
            if cnr is not None and cnr < cnr_min:
                flags.append({"bbox_full": ref.get("bbox_full"), "cnr": cnr, "issue": "low_cnr_vs_calibrated"})
        return {"modality": "AIA", "cnr_min_plausible": cnr_min, "flags": flags, "suspect": bool(flags)}
    if modality == "EPB" and refs:
        t = thresholds.get("EPB") or {}
        sig_min = float(t.get("depletion_sigma_p10") or -999)
        flags = []
        for ref in refs:
            sig = (ref.get("metrics") or {}).get("depletion_sigma")
            if sig is not None and sig < sig_min:
                flags.append({"bbox_full": ref.get("bbox_full"), "depletion_sigma": sig, "issue": "weak_depletion"})
        return {"modality": "EPB", "depletion_sigma_p10": sig_min, "flags": flags, "suspect": bool(flags)}
    if modality == "ULF":
        wins = (item.get("metrics_full") or {}).get("windows_labeled") or []
        peak_min = float((thresholds.get("ULF") or {}).get("peak_over_quiet_min") or 2.0)
        flags = []
        for win in wins:
            if win.get("window_peak_envelope") is not None:
                ratio = win.get("peak_over_quiet")
                if ratio is not None and ratio < peak_min:
                    flags.append({"i0": win.get("i0"), "i1": win.get("i1"), "peak_over_quiet": ratio, "issue": "weak_pi2"})
        return {"modality": "ULF", "peak_over_quiet_min": peak_min, "flags": flags, "suspect": bool(flags)}
    return {"modality": modality, "suspect": False}


def score_against_label(item: dict[str, Any], pass2: dict[str, Any]) -> dict[str, Any]:
    """Summarize per-region verdicts (overlay mode) plus physics audit."""
    parsed = pass2.get("parsed") or {}
    audit = physics_audit_label(item)
    labeled = (item.get("metrics") or {}).get("labeled_regions") or []
    by_id = {
        r.get("region_id"): r
        for r in (parsed.get("regions") or [])
        if r.get("region_id") is not None
    }
    per_region = []
    for row in labeled:
        rid = row.get("region_id")
        verdict = (by_id.get(rid) or {}).get("verdict") or ""
        per_region.append({
            "region_id": rid,
            "caption": row.get("caption"),
            "verdict": verdict,
            "reason": (by_id.get(rid) or {}).get("reason", ""),
        })
    n_bad = sum(1 for row in per_region if row.get("verdict") == "不合理")
    return {
        "scored": bool(labeled),
        "mode": item.get("inspection_mode") or "json_overlay",
        "n_label_regions": len(labeled),
        "n_unreasonable": n_bad,
        "per_region": per_region,
        "pass2_verdict": parsed.get("pass2_verdict") or parsed.get("overall"),
        "physics_audit": audit,
    }


def score_pass1(item: dict[str, Any], pass1: dict[str, Any]) -> dict[str, Any]:
    return normalize_pass1(pass1.get("parsed") or {}, item)


def run_two_pass(item: dict[str, Any], secrets: dict | None = None) -> dict[str, Any]:
    p1 = inspect_pass1(item, secrets)
    ulf_csv = item.get("csv_path") if item["modality"] == "ULF" else None
    p2 = inspect_pass2(
        item,
        p1,
        secrets,
        label_path=item.get("label_path"),
        image_path=item.get("image_path") or ulf_csv,
    )
    pass1_score = score_pass1(item, p1)
    evaluation = score_against_label(item, p2) if item["modality"] in {"AIA", "EPB", "ULF"} else {
        "scored": False,
        "physics_audit": physics_audit_label(item),
        "pass2_verdict": (p2.get("parsed") or {}).get("pass2_verdict") or (p2.get("parsed") or {}).get("overall"),
    }
    evaluation["pass1"] = pass1_score
    return {
        "id": item["id"],
        "modality": item["modality"],
        "metrics": item["metrics"],
        "pass1": p1,
        "pass2": p2,
        "ring_audit": p2.get("ring_audit"),
        "evaluation": evaluation,
    }
