"""Offline auxiliary_metrics templates when no LLM (smoke / CI)."""

from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "lasco_cme_catalog": '''"""Auxiliary: coronagraph occult disk + corona gradient (offline template)."""
import json
import math
import numpy as np
from PIL import Image


def auxiliary_metrics(image_path: str, label_obj: dict | None) -> dict:
    im = Image.open(image_path).convert("L")
    arr = np.array(im, dtype=np.float32)
    h, w = arr.shape
    cy, cx = h / 2.0, w / 2.0
    yy, xx = np.ogrid[:h, :w]
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r_norm = r / (0.5 * min(h, w))
    inner = arr[r_norm < 0.22]
    corona = arr[(r_norm >= 0.28) & (r_norm < 0.85)]
    background = arr[r_norm >= 0.9]
    occult_mean = float(inner.mean()) if inner.size else 0.0
    corona_std = float(corona.std()) if corona.size else 0.0
    noise_frac = float((arr > arr.mean() + 4 * arr.std()).mean())
    radial_gradient = float(np.gradient(arr.mean(axis=1)).std())
    hint = "limb_corona" if corona_std > 15 else "low_corona_signal"
    return {
        "occult_mean_luma": round(occult_mean, 3),
        "corona_std": round(corona_std, 3),
        "noise_hot_fraction": round(noise_frac, 5),
        "radial_gradient": round(radial_gradient, 4),
        "annotation_hint": hint,
        "archetype": "lasco_cme_catalog",
    }
''',
    "hmi_sharp_ar": '''"""Auxiliary: full-disk limb darkening + network contrast (offline template)."""
import numpy as np
from PIL import Image


def auxiliary_metrics(image_path: str, label_obj: dict | None) -> dict:
    im = Image.open(image_path).convert("L")
    arr = np.array(im, dtype=np.float32)
    h, w = arr.shape
    cy, cx = h / 2.0, w / 2.0
    yy, xx = np.ogrid[:h, :w]
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (0.5 * min(h, w))
    center = arr[r < 0.35]
    limb = arr[(r > 0.75) & (r < 0.95)]
    limb_contrast = float(center.mean() - limb.mean()) if center.size and limb.size else 0.0
    gx = np.abs(np.diff(arr, axis=1)).mean()
    gy = np.abs(np.diff(arr, axis=0)).mean()
    local_contrast = float((gx + gy) / 2.0)
    bright_net = float((arr > np.percentile(arr, 92)).mean())
    return {
        "limb_contrast": round(limb_contrast, 3),
        "local_contrast": round(local_contrast, 3),
        "bright_network_fraction": round(bright_net, 5),
        "radial_gradient": round(float(np.gradient(arr.mean(axis=1)).std()), 4),
        "annotation_hint": "magnetogram_network" if bright_net > 0.02 else "quiet_disk",
        "archetype": "hmi_sharp_ar",
    }
''',
    "dmsp_ssusi_aurora": '''"""Auxiliary: auroral oval / pseudo-color streaks (offline template)."""
import numpy as np
from PIL import Image


def auxiliary_metrics(image_path: str, label_obj: dict | None) -> dict:
    im = Image.open(image_path).convert("RGB")
    arr = np.array(im, dtype=np.float32)
    luma = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    h, w = luma.shape
    col_profile = luma.mean(axis=0)
    row_profile = luma.mean(axis=1)
    streak_score = float(col_profile.std() / (col_profile.mean() + 1e-6))
    chroma = float(arr.std())
    bright_oval = float((luma > np.percentile(luma, 88)).mean())
    return {
        "along_col_contrast": round(streak_score, 4),
        "chroma_std": round(chroma, 3),
        "bright_oval_fraction": round(bright_oval, 5),
        "radial_gradient": round(float(np.gradient(row_profile).std()), 4),
        "annotation_hint": "auroral_arc" if streak_score > 0.15 else "weak_emission",
        "archetype": "dmsp_ssusi_aurora",
    }
''',
    "epb_allsky_airglow_mask": '''"""Auxiliary: fish-eye dark streak on bright airglow (offline template)."""
import numpy as np
from PIL import Image


def auxiliary_metrics(image_path: str, label_obj: dict | None) -> dict:
    im = Image.open(image_path).convert("L")
    arr = np.array(im, dtype=np.float32)
    dark = arr < np.percentile(arr, 25)
    bright = arr > np.percentile(arr, 75)
    dark_frac = float(dark.mean())
    band_contrast = float(arr[bright].mean() - arr[dark].mean()) if bright.any() and dark.any() else 0.0
    gx = np.abs(np.diff(arr, axis=1)).mean()
    return {
        "dark_streak_fraction": round(dark_frac, 5),
        "band_contrast": round(band_contrast, 3),
        "local_contrast": round(float(gx), 3),
        "noise_fraction": round(float((arr > arr.mean() + 5 * arr.std()).mean()), 5),
        "annotation_hint": "epb_depletion_band" if band_contrast > 20 else "uniform_background",
        "archetype": "epb_allsky_airglow_mask",
    }
''',
    "ulf_magnetometer_pi2": '''"""Auxiliary: ULF Pi2 band envelope from CSV (offline; path may be .csv not image)."""
import json
import math
import numpy as np


def _read_h_column(csv_path: str) -> np.ndarray:
    vals: list[float] = []
    with open(csv_path, encoding="utf-8", errors="replace") as handle:
        header = [name.strip() for name in handle.readline().split(",")]
        if "H" not in header:
            return np.asarray([], dtype=np.float64)
        idx = header.index("H")
        for line in handle:
            parts = line.split(",")
            try:
                vals.append(float(parts[idx]))
            except (ValueError, IndexError):
                vals.append(float("nan"))
    return np.asarray(vals, dtype=np.float64)


def auxiliary_metrics(image_path: str, label_obj: dict | None) -> dict:
    h = _read_h_column(image_path)
    if h.size < 60:
        return {"error": "too_few_samples", "n_samples": int(h.size), "archetype": "ulf_magnetometer_pi2"}
    h = h - float(np.nanmedian(h))
    h = np.nan_to_num(h, nan=0.0)
    # 1 s cadence proxy band 6.7-25 mHz -> ~40-150 s smoothing
    win = 60
    if h.size >= win:
        kernel = np.ones(win, dtype=np.float64) / win
        env = np.convolve(np.abs(h), kernel, mode="same")
    else:
        env = np.abs(h)
    quiet = float(np.percentile(env, 30))
    peak = float(np.max(env))
    ratio = peak / (quiet + 1e-9)
    n_windows = 0
    if label_obj:
        spans = (label_obj.get("ulf_event_annotation") or {}).get("matched_events") or []
        n_windows = len(spans)
    hint = "pi2_burst" if ratio > 3.0 else "quiet_band"
    return {
        "n_samples": int(h.size),
        "envelope_quiet_p30": round(quiet, 6),
        "envelope_peak": round(peak, 6),
        "peak_over_quiet": round(ratio, 4),
        "band_label": "Pi2 6.7-25 mHz proxy",
        "n_labeled_events": n_windows,
        "annotation_hint": hint,
        "archetype": "ulf_magnetometer_pi2",
    }
''',
    "sdo_aia_hek_ar": '''"""Fallback AIA-like ring cues (offline)."""
import numpy as np
from PIL import Image


def auxiliary_metrics(image_path: str, label_obj: dict | None) -> dict:
    im = Image.open(image_path).convert("L")
    arr = np.array(im, dtype=np.float32)
    return {
        "local_contrast": round(float(np.abs(np.diff(arr, axis=1)).mean()), 3),
        "bright_fraction": round(float((arr > np.percentile(arr, 90)).mean()), 5),
        "radial_gradient": round(float(np.gradient(arr.mean(axis=1)).std()), 4),
        "annotation_hint": "euv_active_region",
        "archetype": "sdo_aia_hek_ar",
    }
''',
}


def offline_script_for(archetype_id: str, pipeline: str) -> str:
    if archetype_id in TEMPLATES:
        return TEMPLATES[archetype_id]
    if pipeline == "EPB":
        return TEMPLATES["epb_allsky_airglow_mask"]
    if pipeline == "ULF":
        return TEMPLATES["ulf_magnetometer_pi2"]
    return TEMPLATES.get("sdo_aia_hek_ar", "")