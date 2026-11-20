"""Compact prepare_* snapshot for v1/v2 teaching (structure names, not fork physics_metrics)."""

from __future__ import annotations

import os
from typing import Any

from dataset_router.visual_probe import collect_png_paths


def _label_for_png(dir_path: str, png: str) -> str | None:
    base = os.path.basename(png)
    for cand in (
        os.path.join(dir_path, "label", base + ".json"),
        os.path.join(dir_path, base + ".json"),
    ):
        if os.path.isfile(cand):
            return cand
    return None


def build_standard_track_brief(dir_path: str, pipeline: str) -> str:
    """
    Keys/units from prepare_aia|epb|ulf for LLM v1 alignment.
    Does not dump full metrics JSON (avoid prompt bloat).
    """
    pipe = pipeline.upper()
    path, label_path = "", None
    if pipe == "ULF":
        for name in sorted(os.listdir(dir_path)):
            if name.endswith(".csv") and not name.endswith(".csv.json"):
                path = os.path.join(dir_path, name)
                lab = path + ".json"
                label_path = lab if os.path.isfile(lab) else None
                break
    else:
        pngs = collect_png_paths(dir_path, limit=1)
        if pngs:
            path = pngs[0]
            label_path = _label_for_png(dir_path, path)

    if not path:
        return f"(无样本路径 pipeline={pipeline})"

    try:
        if pipe == "AIA":
            from physics_inspect import prepare_aia
            from physics_metrics import aia_metrics_for_image

            if label_path and os.path.isfile(label_path):
                item = prepare_aia(path, label_path)
            else:
                item = {"metrics": aia_metrics_for_image(path, label_path), "modality": "AIA"}
        elif pipe == "EPB":
            from physics_inspect import prepare_epb
            from physics_metrics import epb_metrics_for_image

            if label_path and os.path.isfile(label_path):
                item = prepare_epb(path, label_path)
            else:
                item = {"metrics": epb_metrics_for_image(path, label_path), "modality": "EPB"}
        elif pipe == "ULF":
            from physics_inspect import prepare_ulf

            item = prepare_ulf(path, label_path)
        else:
            return f"(unsupported pipeline={pipeline})"
    except Exception as exc:  # noqa: BLE001
        return f"(prepare_* 快照失败: {exc})"

    metrics: dict[str, Any] = item.get("metrics") or {}
    top_keys = sorted(metrics.keys())
    lines = [
        f"## 标准轨参考（prepare_{pipeline.lower()}，单样本）",
        f"对象: {os.path.basename(path)}",
        f"顶层 metrics 键（v1 应在 pass1_context / pass2_hint **语义对齐**，勿整包抄袭）:",
        ", ".join(top_keys[:40]),
    ]
    if pipeline.upper() == "AIA":
        scene = metrics.get("scene") or {}
        lines.append(f"scene 示例键: {list(scene.keys())}")
        lines.append("主轨审计: overlap_audit, mechanical_coverage_audit, labeled_regions[].physics")
    elif pipeline.upper() == "EPB":
        lines.append(
            f"平场: flat_method={metrics.get('flat_method')}, grid={metrics.get('grid')}, "
            f"residual_unit={metrics.get('residual_unit')}"
        )
        lines.append("主轨: candidates (σ 带), 勿用 AIA 环带 CNR 替代")
    elif pipeline.upper() == "ULF":
        tc = metrics.get("threshold_calibration") or {}
        sw = metrics.get("sliding_window_scan") or {}
        lines.append(f"Pi2: band_label={metrics.get('band_label')}, unit={metrics.get('unit')}")
        if tc:
            lines.append(f"threshold_calibration 键: {list(tc.keys())[:12]}")
        if sw:
            lines.append(f"sliding_window_scan 键: {list(sw.keys())[:12]}")
        lines.append("路径为 .csv 非 PNG；勿 Image.open(csv)")
    lines.append(
        "**v1 目标**: auxiliary 输出 nested pipeline_coverage + pass1_context 键名/单位与上表一致或可映射。"
        "**v2 目标**: 在 v1 上补 label 几何/防幻觉，并向 pass2_hint 对齐 band_audit/window 可对齐数字。"
    )
    return "\n".join(lines)