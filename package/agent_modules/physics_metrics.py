"""Physics-informed metrics for AIA / EPB / ULF. Units are documented in each result dict."""

from __future__ import annotations

import json
import os
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.signal import butter, filtfilt, hilbert

from audits import pixel_rings


def _luminance_array(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float64)
    return 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]


def load_gray(path: str, max_side: int | None = 1024) -> tuple[np.ndarray, float]:
    """Return grayscale DN array and scale: multiply working pixel coords to get full-res coords."""
    full = Image.open(path)
    image = full
    scale = 1.0
    if max_side is not None and max(full.size) > max_side:
        ratio = max_side / max(full.size)
        new_size = (max(1, int(full.size[0] * ratio)), max(1, int(full.size[1] * ratio)))
        image = full.resize(new_size, Image.BILINEAR)
        scale = full.size[0] / image.size[0]
    gray = _luminance_array(image)
    return gray, scale


def _disk_mask(shape: tuple[int, int], margin: float = 0.04) -> np.ndarray:
    h, w = shape
    cy, cx = h / 2.0, w / 2.0
    radius = min(h, w) * (0.5 - margin)
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= radius ** 2


# 漏标候选：连通域面积须 ≥ 日面圆盘面积的一定比例（与 OPC viz_aia_ar.detect_disk 定标一致）
AIA_MISS_MIN_FRAC_OF_DISK = 0.001  # 0.10% 日面；小于此视为光晕/噪声，不算漏标
AIA_MISS_MAX_FRAC_OF_DISK = 0.025  # 连通域过大视为弥散冕/环带，非独立漏标 AR
_FALLBACK_DISK_R_FRAC = 0.46
EPB_MISS_MIN_FRAC_OF_FRAME = 0.0005
EPB_MISS_MAX_FRAC_OF_FRAME = 0.22
EPB_MISS_MIN_AREA_FRAC_MEDIAN = 0.12
EPB_MISS_MAX_AREA_FRAC_MEDIAN = 3.0
EPB_MISS_DEPLETION_SIGMA = 1.15
EPB_MISS_DARK_PERCENTILE = 28.0
EPB_MISS_TOP_K_DEFAULT = 2
EPB_MISS_DIFFUSION_WALKS = 48
EPB_MISS_DIFFUSION_STEPS = 140
EPB_MISS_METHOD = "connectivity+diffusion+gradient_contour"


def detect_disk_from_gray(gray: np.ndarray) -> tuple[float, float, float]:
    """Port of OPC viz_aia_ar.detect_disk — center (x,y) and radius in working pixels."""
    h, w = gray.shape
    cx = cy = (w - 1) / 2.0
    yy, xx = np.mgrid[:h, :w]
    r = np.hypot(xx - cx, yy - cy)
    nb = 256
    edges = np.linspace(0, 0.72 * w, nb + 1)
    idx = np.digitize(r.ravel(), edges) - 1
    prof = np.bincount(idx, weights=gray.ravel(), minlength=nb) / np.maximum(
        np.bincount(idx, minlength=nb), 1
    )
    centers = 0.5 * (edges[:-1] + edges[1:])
    lo_i = np.searchsorted(centers, 0.30 * w)
    hi_i = np.searchsorted(centers, 0.56 * w)
    seg = prof[lo_i:hi_i]
    fallback = _FALLBACK_DISK_R_FRAC * w
    if seg.size < 5:
        return cx, cy, fallback
    d = np.diff(prof)
    lo_i2 = max(lo_i, 1)
    thr = max(d[lo_i2:hi_i - 1].max() * 0.35, 1e-6)
    outer = [
        centers[i + 1]
        for i in range(lo_i2, hi_i - 1)
        if d[i] <= -thr
    ]
    radius = outer[-1] if outer else fallback
    return cx, cy, float(radius)


def aia_disk_area_full(gray: np.ndarray, scale: float) -> dict[str, float]:
    cx, cy, r_work = detect_disk_from_gray(gray)
    r_full = r_work * scale
    area_full = float(np.pi * r_full * r_full)
    return {
        "disk_cx_full": round(cx * scale, 1),
        "disk_cy_full": round(cy * scale, 1),
        "disk_r_full_px": round(r_full, 1),
        "disk_area_full_px2": round(area_full, 1),
        "miss_min_area_full_px2": round(AIA_MISS_MIN_FRAC_OF_DISK * area_full, 1),
        "miss_min_frac_of_disk": AIA_MISS_MIN_FRAC_OF_DISK,
    }


def _polygon_mask(shape: tuple[int, int], polygon: list[tuple[float, float]]) -> np.ndarray:
    mask = Image.new("L", (shape[1], shape[0]), 0)
    from PIL import ImageDraw

    draw = ImageDraw.Draw(mask)
    pts = [(float(x), float(y)) for x, y in polygon]
    if len(pts) >= 3:
        draw.polygon(pts, outline=1, fill=1)
    return np.asarray(mask, dtype=bool)


def _ring_outside_mask(
    shape: tuple[int, int],
    polygon: list[tuple[float, float]],
    inner: float = 4.0,
    outer: float = 36.0,
) -> np.ndarray:
    """Background annulus around polygon in pixel space."""
    filled = _polygon_mask(shape, polygon)
    dist_in = ndimage.distance_transform_edt(~filled)
    dist_out = ndimage.distance_transform_edt(filled)
    return (dist_out > inner) & (dist_out <= outer)


def bbox_of_polygon(polygon: list[tuple[float, float]]) -> dict[str, float]:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}


def _bbox_intersection_area(a: dict[str, float], b: dict[str, float]) -> float:
    ix0 = max(a["xmin"], b["xmin"])
    iy0 = max(a["ymin"], b["ymin"])
    ix1 = min(a["xmax"], b["xmax"])
    iy1 = min(a["ymax"], b["ymax"])
    return max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)


def bbox_iou(a: dict[str, float], b: dict[str, float]) -> float:
    inter = _bbox_intersection_area(a, b)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a["xmax"] - a["xmin"]) * max(0.0, a["ymax"] - a["ymin"])
    area_b = max(0.0, b["xmax"] - b["xmin"]) * max(0.0, b["ymax"] - b["ymin"])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def bbox_ios(a: dict[str, float], b: dict[str, float]) -> float:
    """Intersection over min(area) — catches nested boxes with low IoU."""
    inter = _bbox_intersection_area(a, b)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a["xmax"] - a["xmin"]) * max(0.0, a["ymax"] - a["ymin"])
    area_b = max(0.0, b["xmax"] - b["xmin"]) * max(0.0, b["ymax"] - b["ymin"])
    return inter / max(min(area_a, area_b), 1e-6)


def aia_quiet_sun(gray: np.ndarray) -> dict[str, Any]:
    disk = _disk_mask(gray.shape)
    values = gray[disk]
    quiet = float(np.percentile(values, 20))
    sigma = float(np.std(values[values <= np.percentile(values, 55)])) or 1.0
    return {
        "quiet_dn": round(quiet, 3),
        "sigma_dn": round(sigma, 4),
        "disk_median_dn": round(float(np.median(values)), 3),
        "unit": "DN (8-bit PNG luminance proxy)",
        "normalization": "contrast_vs_quiet_sun",
    }


def aia_contrast_in_polygon(gray: np.ndarray, polygon: list[tuple[float, float]]) -> dict[str, Any]:
    quiet = aia_quiet_sun(gray)
    inside = _polygon_mask(gray.shape, polygon)
    ring = _ring_outside_mask(gray.shape, polygon)
    if not inside.any() or not ring.any():
        return {"valid": False}
    mean_in = float(np.mean(gray[inside]))
    mean_bg = float(np.mean(gray[ring]))
    sigma_bg = float(np.std(gray[ring])) or quiet["sigma_dn"]
    cnr = (mean_in - mean_bg) / sigma_bg
    ratio_q = mean_in / max(quiet["quiet_dn"], 1e-3)
    return {
        "valid": True,
        "mean_in_dn": round(mean_in, 3),
        "mean_bg_dn": round(mean_bg, 3),
        "flux_ratio_vs_ring": round(mean_in / max(mean_bg, 1e-3), 4),
        "flux_ratio_vs_quiet": round(ratio_q, 4),
        "cnr": round(float(cnr), 4),
        **quiet,
    }


def aia_candidate_regions(gray: np.ndarray, top_k: int = 4, min_area: int = 40) -> list[dict[str, Any]]:
    """Bright regions on disk for blind VLM context (no label)."""
    disk = _disk_mask(gray.shape)
    qs = aia_quiet_sun(gray)
    enhanced = (gray - qs["quiet_dn"]) / max(qs["sigma_dn"], 1e-3)
    enhanced[~disk] = 0
    mask = enhanced > 4.0
    labeled, n = ndimage.label(mask)
    candidates: list[dict[str, Any]] = []
    for label_id in range(1, n + 1):
        region = labeled == label_id
        area = int(region.sum())
        if area < min_area:
            continue
        ys, xs = np.where(region)
        xmin, xmax = int(xs.min()), int(xs.max())
        ymin, ymax = int(ys.min()), int(ys.max())
        poly = [
            (xmin, ymin),
            (xmax, ymin),
            (xmax, ymax),
            (xmin, ymax),
            (xmin, ymin),
        ]
        metrics = aia_contrast_in_polygon(gray, poly)
        candidates.append({
            "bbox": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
            "area_px": area,
            "peak_enhancement_sigma": round(float(enhanced[region].max()), 3),
            "metrics": metrics,
        })
    candidates.sort(key=lambda row: row["peak_enhancement_sigma"], reverse=True)
    return candidates[:top_k]


def epb_flat_field(gray: np.ndarray, grid: int = 32) -> tuple[np.ndarray, dict[str, Any]]:
    """Coarse 2D median flat field; residual = observed - flat (negative = depletion)."""
    h, w = gray.shape
    coarse = np.zeros((grid, grid), dtype=np.float64)
    counts = np.zeros((grid, grid), dtype=np.float64)
    step_y = max(1, h // grid)
    step_x = max(1, w // grid)
    for gy in range(grid):
        for gx in range(grid):
            y0, y1 = gy * step_y, min(h, (gy + 1) * step_y)
            x0, x1 = gx * step_x, min(w, (gx + 1) * step_x)
            block = gray[y0:y1, x0:x1]
            coarse[gy, gx] = float(np.median(block))
            counts[gy, gx] = block.size
    flat = np.array(
        Image.fromarray(coarse.astype(np.float32)).resize((w, h), Image.BILINEAR),
        dtype=np.float64,
    )
    residual = gray - flat
    return residual, {
        "flat_method": "median_grid_bilinear",
        "grid": grid,
        "residual_unit": "DN (negative = darker than local flat field)",
    }


def epb_dark_candidates(gray: np.ndarray, top_k: int = 3, min_area: int = 80) -> list[dict[str, Any]]:
    residual, _meta = epb_flat_field(gray)
    sigma = float(np.std(residual)) or 1.0
    mask = residual < (-2.0 * sigma)
    labeled, n = ndimage.label(mask)
    found: list[dict[str, Any]] = []
    for label_id in range(1, n + 1):
        region = labeled == label_id
        area = int(region.sum())
        if area < min_area:
            continue
        ys, xs = np.where(region)
        bbox = {"xmin": int(xs.min()), "ymin": int(ys.min()), "xmax": int(xs.max()), "ymax": int(ys.max())}
        poly = [
            (bbox["xmin"], bbox["ymin"]),
            (bbox["xmax"], bbox["ymin"]),
            (bbox["xmax"], bbox["ymax"]),
            (bbox["xmin"], bbox["ymax"]),
            (bbox["xmin"], bbox["ymin"]),
        ]
        found.append({"bbox": bbox, "area_px": area, "metrics": epb_depletion_in_polygon(gray, poly)})
    found.sort(key=lambda row: row["metrics"].get("depletion_sigma") or 0, reverse=True)
    return found[:top_k]


def epb_depletion_in_polygon(gray: np.ndarray, polygon: list[tuple[float, float]]) -> dict[str, Any]:
    residual, meta = epb_flat_field(gray)
    inside = _polygon_mask(gray.shape, polygon)
    ring = _ring_outside_mask(gray.shape, polygon, inner=3, outer=28)
    if not inside.any() or not ring.any():
        return {"valid": False, **meta}
    mean_in = float(np.mean(residual[inside]))
    mean_bg = float(np.mean(residual[ring]))
    sigma_bg = float(np.std(residual[ring])) or 1.0
    depth = mean_bg - mean_in
    return {
        "valid": True,
        "mean_residual_in": round(mean_in, 4),
        "mean_residual_ring": round(mean_bg, 4),
        "depletion_depth_dn": round(depth, 4),
        "depletion_sigma": round(depth / sigma_bg, 4),
        **meta,
    }


def ulf_bandpass(h: np.ndarray, fs: float = 1.0, f_low: float = 1 / 150.0, f_high: float = 1 / 40.0) -> np.ndarray:
    h = np.asarray(h, dtype=np.float64)
    h = np.nan_to_num(h - np.nanmedian(h))
    nyq = fs / 2.0
    low = max(f_low / nyq, 1e-5)
    high = min(f_high / nyq, 0.999)
    if low >= high:
        return h * 0.0
    b, a = butter(3, [low, high], btype="band")
    if h.size < max(len(a), len(b)) * 3:
        return h * 0.0
    return filtfilt(b, a, h)


def ulf_pi2_metrics(h: np.ndarray, fs: float = 1.0) -> dict[str, Any]:
    filtered = ulf_bandpass(h, fs=fs)
    envelope = np.abs(hilbert(filtered))
    quiet = float(np.percentile(envelope, 30))
    peak = float(np.max(envelope))
    return {
        "band_hz": [round(1 / 150.0, 5), round(1 / 40.0, 5)],
        "band_label": "Pi2 6.7–25 mHz (40–150 s)",
        "envelope_quiet": round(quiet, 6),
        "envelope_peak": round(peak, 6),
        "peak_over_quiet": round(peak / max(quiet, 1e-9), 4),
        "unit": "nT proxy (CSV H column, median removed)",
    }


def ulf_window_metrics(h: np.ndarray, i0: int, i1: int, fs: float = 1.0) -> dict[str, Any]:
    segment = np.asarray(h[i0:i1], dtype=np.float64)
    if segment.size < 30:
        return {"valid": False}
    filtered = ulf_bandpass(segment, fs=fs)
    env = np.abs(hilbert(filtered))
    full = ulf_pi2_metrics(h, fs=fs)
    return {
        "valid": True,
        "window_energy": round(float(np.mean(env ** 2)), 8),
        "window_peak_envelope": round(float(np.max(env)), 6),
        "peak_over_quiet": full["peak_over_quiet"],
        **full,
    }


def load_ulf_h_csv(csv_path: str) -> np.ndarray:
    import csv

    vals: list[float] = []
    with open(csv_path, encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        if "H" not in (reader.fieldnames or []):
            return np.array([], dtype=np.float64)
        for row in reader:
            try:
                vals.append(float(row["H"]))
            except (TypeError, ValueError):
                vals.append(float("nan"))
    return np.asarray(vals, dtype=np.float64)


def ulf_envelope_series(h: np.ndarray, fs: float = 1.0) -> tuple[np.ndarray, dict[str, Any]]:
    h = np.asarray(h, dtype=np.float64)
    metrics = ulf_pi2_metrics(h, fs=fs)
    filtered = ulf_bandpass(h - np.nanmedian(h), fs=fs)
    envelope = np.abs(hilbert(filtered))
    return envelope, metrics


def _ulf_local_peak_indices(envelope: np.ndarray, *, min_distance: int = 40) -> list[int]:
    """Simple 1-D peak pick with minimum index spacing (Pi2 period lower bound ~40 s @ 1 Hz)."""
    x = np.asarray(envelope, dtype=np.float64)
    n = int(x.size)
    if n < 3:
        return []
    raw: list[tuple[float, int]] = []
    for i in range(1, n - 1):
        if x[i] >= x[i - 1] and x[i] > x[i + 1]:
            raw.append((float(x[i]), i))
    raw.sort(key=lambda t: -t[0])
    chosen: list[int] = []
    for _val, idx in raw:
        if all(abs(idx - c) >= min_distance for c in chosen):
            chosen.append(idx)
    chosen.sort()
    return chosen


def _ulf_sliding_starts(n: int, w: int, step: int) -> list[int]:
    """Grid starts plus trailing window so the hour tail is covered."""
    if n <= 0 or w <= 0:
        return []
    if n <= w:
        return [0]
    starts = list(range(0, n - w + 1, max(1, step)))
    last = n - w
    if not starts or starts[-1] != last:
        starts.append(last)
    return starts


def ulf_adaptive_scan_grid(envelope: np.ndarray, *, fs: float = 1.0) -> dict[str, Any]:
    """
    Data-driven window/stride from envelope peak spacing (not fixed 600/120).
    Pi2 40–150 s → min_distance 40 s; window ~ 2.5× median spacing, stride ~ 0.5× spacing.
    """
    peaks = _ulf_local_peak_indices(envelope, min_distance=max(30, int(40 * fs)))
    if len(peaks) >= 2:
        spacing = float(np.median(np.diff(peaks)))
        window_s = int(np.clip(round(spacing * 2.5 / fs), 120, 900))
        stride_s = int(np.clip(round(spacing * 0.5 / fs), 20, min(180, window_s // 2)))
        confidence = "peak_spacing"
    else:
        window_s, stride_s = 600, 120
        confidence = "low_no_clear_peaks"
    return {
        "window_s": window_s,
        "stride_s": stride_s,
        "n_envelope_peaks": len(peaks),
        "median_peak_spacing_s": round(float(np.median(np.diff(peaks))), 2) if len(peaks) >= 2 else None,
        "grid_confidence": confidence,
        "peak_indices_sample": peaks[:8],
    }


def ulf_sliding_window_scan(
    h: np.ndarray,
    *,
    fs: float = 1.0,
    window_s: int | None = None,
    stride_s: int | None = None,
    top_k: int = 12,
    adaptive: bool = True,
) -> dict[str, Any]:
    """
    Sliding Pi2 envelope scan for Pass1 calibration input.
    Handles hour boundaries (trailing window), peak localization inside each window, hour coverage.
    """
    h = np.asarray(h, dtype=np.float64)
    n = int(h.size)
    envelope, hour = ulf_envelope_series(h, fs=fs)
    quiet = float(hour["envelope_quiet"]) or 1e-9
    grid_meta: dict[str, Any] = {}
    if adaptive or window_s is None or stride_s is None:
        grid_meta = ulf_adaptive_scan_grid(envelope, fs=fs)
        window_s = int(grid_meta["window_s"])
        stride_s = int(grid_meta["stride_s"])
    w = max(30, int(window_s * fs))
    step = max(1, int(stride_s * fs))
    covered = np.zeros(n, dtype=bool)
    rows: list[dict[str, Any]] = []
    for i0 in _ulf_sliding_starts(n, w, step):
        i1 = min(i0 + w, n)
        seg = envelope[i0:i1]
        if seg.size < 30:
            continue
        covered[i0:i1] = True
        peak_rel = int(np.argmax(seg))
        peak_idx = i0 + peak_rel
        peak = float(seg[peak_rel])
        boundary = "interior"
        if i0 == 0:
            boundary = "start"
        if i1 >= n and i0 > 0:
            boundary = "end"
        if i0 == 0 and i1 >= n:
            boundary = "full_hour"
        rows.append({
            "i0": i0,
            "i1": i1,
            "duration_s": i1 - i0,
            "valid_fraction": round(seg.size / max(w, 1), 4),
            "boundary": boundary,
            "peak_t": peak_idx,
            "peak_over_quiet_p30": round(peak / quiet, 4),
            "window_max_envelope": round(peak, 6),
            "window_mean_envelope": round(float(np.mean(seg)), 6),
            "window_p90_envelope": round(float(np.percentile(seg, 90)), 6),
        })
    ratios = np.asarray([r["peak_over_quiet_p30"] for r in rows], dtype=np.float64)
    rows.sort(key=lambda r: -r["peak_over_quiet_p30"])
    return {
        "method": "sliding_max_pi2_envelope_v2",
        "window_s": window_s,
        "stride_s": stride_s,
        "adaptive_grid": grid_meta or None,
        "full_hour_envelope_quiet_p30": round(quiet, 6),
        "full_hour_peak_over_quiet": hour.get("peak_over_quiet"),
        "hour_coverage_fraction": round(float(covered.mean()), 4) if n else 0.0,
        "ratio_distribution": {
            "p10": round(float(np.percentile(ratios, 10)), 4) if ratios.size else None,
            "p50": round(float(np.percentile(ratios, 50)), 4) if ratios.size else None,
            "p90": round(float(np.percentile(ratios, 90)), 4) if ratios.size else None,
        },
        "n_positions": len(rows),
        "all_positions": rows,
        "top_peaks": rows[:top_k],
        "note": "Pass1 读 threshold_calibration（反估+CI）；勿仅抄固定 window_s/stride_s",
    }


def _param_ci(values: list[float] | np.ndarray, *, p_lo: float = 5.0, p_hi: float = 95.0) -> dict[str, float | None]:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"estimate": None, "ci_low": None, "ci_high": None}
    return {
        "estimate": round(float(np.median(arr)), 4),
        "ci_low": round(float(np.percentile(arr, p_lo)), 4),
        "ci_high": round(float(np.percentile(arr, p_hi)), 4),
    }


def ulf_burst_run_stats(
    envelope: np.ndarray,
    quiet: float,
    *,
    fs: float = 1.0,
    ratio_grid: tuple[float, ...] = (1.6, 2.0, 2.4, 2.8, 3.2),
) -> dict[str, Any]:
    """Connected runs above quiet×ratio; used to back-estimate duration / merge_gap."""
    env = np.asarray(envelope, dtype=np.float64)
    out: list[dict[str, Any]] = []
    for ratio in ratio_grid:
        thr = quiet * ratio
        active = env > thr
        labeled, n_feat = ndimage.label(active)
        lengths: list[float] = []
        peaks: list[float] = []
        for lab in range(1, n_feat + 1):
            idx = np.where(labeled == lab)[0]
            if idx.size < 5:
                continue
            lengths.append(float(idx.size) / fs)
            peaks.append(float(np.max(env[idx])) / quiet)
        out.append({
            "ratio_over_quiet": ratio,
            "n_runs": len(lengths),
            "run_duration_s": _param_ci(lengths),
            "run_peak_over_quiet": _param_ci(peaks),
        })
    return {"by_ratio_threshold": out}


def ulf_threshold_calibration(
    h: np.ndarray,
    *,
    label_path: str | None = None,
    fs: float = 1.0,
) -> dict[str, Any]:
    """
    Back-estimate Pass1 thresholds from sliding scan + envelope runs (point + percentile CI).
    Model Pass1 confirms/adjusts → threshold_proposal; Pass2 re-applies that proposal.
    """
    h = np.asarray(h, dtype=np.float64)
    n = int(h.size)
    if n < 100:
        return {"valid": False, "reason": "H too short"}
    scan = ulf_sliding_window_scan(h, fs=fs, adaptive=True)
    envelope, hour = ulf_envelope_series(h, fs=fs)
    quiet = float(hour["envelope_quiet"]) or 1e-9
    ratios = np.asarray([r["peak_over_quiet_p30"] for r in scan.get("all_positions") or []], dtype=np.float64)
    if ratios.size == 0:
        return {"valid": False, "reason": "empty sliding scan"}

    quiet_windows = ratios[ratios <= np.percentile(ratios, 40)]
    loud_windows = ratios[ratios >= np.percentile(ratios, 85)]
    gap = float(np.median(loud_windows) - np.percentile(quiet_windows, 90)) if quiet_windows.size and loud_windows.size else 0.5
    peak_est = max(
        float(np.percentile(quiet_windows, 95)) + max(0.25, 0.35 * gap),
        1.5,
    )
    peak_ci_lo = float(np.percentile(quiet_windows, 90)) + 0.15 if quiet_windows.size else peak_est * 0.75
    peak_ci_hi = float(np.percentile(loud_windows, 10)) if loud_windows.size else peak_est * 1.35

    run_stats = ulf_burst_run_stats(envelope, quiet, fs=fs)
    best_ratio_row = max(
        (r for r in run_stats["by_ratio_threshold"] if r["n_runs"] >= 1),
        key=lambda r: r["n_runs"],
        default=None,
    )
    if best_ratio_row and best_ratio_row["run_duration_s"]["estimate"] is not None:
        dur_est = best_ratio_row["run_duration_s"]
        run_ratio = float(best_ratio_row["ratio_over_quiet"])
        peak_est = max(peak_est, run_ratio)
        peak_ci_lo = min(peak_ci_lo, run_ratio * 0.85)
        peak_ci_hi = max(peak_ci_hi, run_ratio * 1.25)
    else:
        dur_est = {"estimate": 60.0, "ci_low": 40.0, "ci_high": 150.0}

    peaks = _ulf_local_peak_indices(envelope, min_distance=max(30, int(40 * fs)))
    gaps: list[float] = []
    if len(peaks) >= 2:
        gaps = [float(b - a) for a, b in zip(peaks[:-1], peaks[1:])]
    merge_est = _param_ci(gaps) if gaps else {"estimate": 30.0, "ci_low": 15.0, "ci_high": 60.0}
    if merge_est.get("estimate") is not None:
        merge_est["estimate"] = round(min(120.0, max(10.0, float(merge_est["estimate"]) * 0.35)), 2)

    in_win_est: dict[str, Any] = {"estimate": 1.5, "ci_low": 1.25, "ci_high": 2.0, "source": "default_literature_gap"}
    labeled_split: dict[str, Any] | None = None
    if label_path and os.path.isfile(label_path):
        from audits import window_spans

        obj = json.load(open(label_path, encoding="utf-8"))
        spans = window_spans(obj, n)
        lmask = np.zeros(n, dtype=bool)
        for span in spans:
            if span.get("i0") is None:
                continue
            lmask[int(span["i0"]) : int(span["i1"])] = True
        in_ratios: list[float] = []
        out_ratios: list[float] = []
        for row in scan.get("all_positions") or []:
            i0, i1 = int(row["i0"]), int(row["i1"])
            frac = float(lmask[i0:i1].mean()) if lmask.any() else 0.0
            r = float(row["peak_over_quiet_p30"])
            if frac >= 0.5:
                in_ratios.append(r)
            elif frac <= 0.05:
                out_ratios.append(r)
        if in_ratios and out_ratios:
            mid = (float(np.median(in_ratios)) + float(np.median(out_ratios))) / 2.0
            in_win_est = {
                "estimate": round(max(1.2, mid * 0.92), 4),
                "ci_low": round(max(1.0, float(np.percentile(out_ratios, 75))), 4),
                "ci_high": round(float(np.percentile(in_ratios, 25)), 4),
                "source": "labeled_overlap_split",
            }
            labeled_split = {
                "n_windows_over_label": len(in_ratios),
                "n_windows_outside_label": len(out_ratios),
                "median_ratio_in": round(float(np.median(in_ratios)), 4),
                "median_ratio_out": round(float(np.median(out_ratios)), 4),
            }

    max_burst_est = {
        "estimate": min(900.0, max(300.0, float(dur_est.get("ci_high") or 900) * 3)),
        "ci_low": 600.0,
        "ci_high": 900.0,
    }

    ratio_p90 = (scan.get("ratio_distribution") or {}).get("p90")
    if ratio_p90 is not None:
        cap = float(ratio_p90) * 1.55
        if peak_est > cap:
            peak_est = cap
            peak_ci_hi = min(float(peak_ci_hi), cap * 1.15)

    vlm_scan = {k: v for k, v in scan.items() if k != "all_positions"}
    return {
        "valid": True,
        "method": "sliding_back_estimate_v1",
        "sliding_window_scan": vlm_scan,
        "scan_summary": {
            "window_s": scan["window_s"],
            "stride_s": scan["stride_s"],
            "grid_confidence": (scan.get("adaptive_grid") or {}).get("grid_confidence"),
            "hour_coverage_fraction": scan.get("hour_coverage_fraction"),
            "ratio_distribution": scan.get("ratio_distribution"),
            "n_positions": scan.get("n_positions"),
        },
        "peak_over_quiet_min": {
            "estimate": round(peak_est, 4),
            "ci_low": round(peak_ci_lo, 4),
            "ci_high": round(peak_ci_hi, 4),
            "unit": "ratio_vs_p30_quiet",
        },
        "in_window_ratio_min": in_win_est,
        "min_burst_duration_s": {
            "estimate": round(float(dur_est.get("estimate") or 60), 2),
            "ci_low": round(float(dur_est.get("ci_low") or 40), 2),
            "ci_high": round(float(dur_est.get("ci_high") or 150), 2),
            "unit": "seconds",
        },
        "max_burst_duration_s": max_burst_est,
        "merge_gap_s": {
            "estimate": merge_est.get("estimate"),
            "ci_low": merge_est.get("ci_low"),
            "ci_high": merge_est.get("ci_high"),
            "unit": "seconds",
        },
        "miss_overlap_max": {"estimate": 0.15, "ci_low": 0.08, "ci_high": 0.25, "unit": "fraction"},
        "burst_run_stats": run_stats,
        "labeled_window_split": labeled_split,
        "pass1_instruction": (
            "以各 estimate 为初值、ci_low~ci_high 为合理区间；结合波形图输出 threshold_proposal，"
            "并说明与 calibration 一致或偏离原因（calibration_agreement）。"
        ),
    }


def ulf_merge_threshold_proposal(
    pass1_parsed: dict[str, Any] | None,
    calibration: dict[str, Any] | None,
) -> dict[str, Any]:
    """Pass2 数值轨：优先 Pass1 终估，缺项用 calibration estimate 补齐。"""
    tp = dict((pass1_parsed or {}).get("threshold_proposal") or {})
    cal = calibration or {}
    provenance: dict[str, str] = {}

    def _fill(key: str, cal_key: str, cast):
        if tp.get(key) is not None:
            provenance[key] = "pass1"
            return cast(tp[key])
        block = cal.get(cal_key) or {}
        est = block.get("estimate")
        if est is not None:
            provenance[key] = "calibration_estimate"
            return cast(est)
        provenance[key] = "fallback"
        return cast(None)

    merged = {
        "peak_over_quiet_min": _fill("peak_over_quiet_min", "peak_over_quiet_min", float),
        "in_window_ratio_min": _fill(
            "in_window_ratio_min",
            "in_window_ratio_min",
            float,
        ),
        "min_burst_duration_s": _fill("min_burst_duration_s", "min_burst_duration_s", int),
        "max_burst_duration_s": _fill("max_burst_duration_s", "max_burst_duration_s", int),
        "merge_gap_s": _fill("merge_gap_s", "merge_gap_s", int),
        "miss_overlap_max": _fill("miss_overlap_max", "miss_overlap_max", float),
        "rationale": tp.get("rationale") or cal.get("pass1_instruction"),
        "calibration_agreement": tp.get("calibration_agreement"),
        "provenance": provenance,
    }
    defaults = {
        "peak_over_quiet_min": 2.0,
        "in_window_ratio_min": 1.5,
        "min_burst_duration_s": 60,
        "max_burst_duration_s": 900,
        "merge_gap_s": 30,
        "miss_overlap_max": 0.15,
    }
    for k, v in defaults.items():
        if merged[k] is None:
            merged[k] = v
            provenance[k] = "physics_thresholds_fallback"
    merged["provenance"] = provenance
    return merged


def ulf_miss_interval_candidates(
    csv_path: str,
    label_path: str,
    *,
    fs: float = 1.0,
    top_k: int = 8,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pass1 漏标初筛：包络峰 + 滑动窗外段，重叠标注掩膜（无 verdict）。"""
    from audits import window_spans

    h = load_ulf_h_csv(csv_path)
    n = int(h.size)
    if n < 100 or not os.path.isfile(label_path):
        return {"method": "envelope_peaks_and_sliding", "candidates": []}
    obj = json.load(open(label_path, encoding="utf-8"))
    spans = window_spans(obj, n)
    lmask = np.zeros(n, dtype=bool)
    for span in spans:
        if span.get("i0") is None:
            continue
        lmask[int(span["i0"]) : int(span["i1"])] = True
    envelope, hour = ulf_envelope_series(h, fs=fs)
    quiet = float(hour["envelope_quiet"]) or 1e-9
    cal = calibration or ulf_threshold_calibration(h, label_path=label_path, fs=fs)
    peak_min = float((cal.get("peak_over_quiet_min") or {}).get("estimate") or 2.0)
    half_win = max(30, int(((cal.get("scan_summary") or {}).get("window_s") or 600) * fs * 0.5))

    cands: list[dict[str, Any]] = []
    for peak_t in _ulf_local_peak_indices(envelope, min_distance=max(30, int(40 * fs))):
        por = float(envelope[peak_t]) / quiet
        if por < peak_min * 0.9:
            continue
        i0 = max(0, peak_t - half_win)
        i1 = min(n, peak_t + half_win)
        overlap = float(lmask[i0:i1].mean()) if lmask.any() else 0.0
        cands.append({
            "candidate_id": len(cands),
            "kind": "envelope_peak",
            "peak_t": peak_t,
            "i0": i0,
            "i1": i1,
            "duration_s": i1 - i0,
            "peak_over_quiet_p30": round(por, 4),
            "overlap_labeled_fraction": round(overlap, 4),
        })
    scan = ulf_sliding_window_scan(h, fs=fs, adaptive=True)
    for row in scan.get("top_peaks") or []:
        i0, i1 = int(row["i0"]), int(row["i1"])
        overlap = float(lmask[i0:i1].mean()) if lmask.any() else 0.0
        if overlap > 0.35:
            continue
        cands.append({
            "candidate_id": len(cands),
            "kind": "sliding_window",
            "peak_t": row.get("peak_t"),
            "i0": i0,
            "i1": i1,
            "duration_s": i1 - i0,
            "peak_over_quiet_p30": row.get("peak_over_quiet_p30"),
            "overlap_labeled_fraction": round(overlap, 4),
            "boundary": row.get("boundary"),
        })
    cands.sort(key=lambda r: (r["overlap_labeled_fraction"], -float(r.get("peak_over_quiet_p30") or 0)))
    for cid, row in enumerate(cands[:top_k]):
        row["candidate_id"] = cid
    return {"method": "envelope_peaks_and_sliding", "peak_min_used": peak_min, "candidates": cands[:top_k]}


def ulf_pass2_audit_from_thresholds(
    csv_path: str,
    label_path: str,
    threshold_proposal: dict[str, Any] | None,
    *,
    fs: float = 1.0,
) -> dict[str, Any]:
    """
    Pass2 数值轨：应用 Pass1 给出的 threshold_proposal（缺失时用 physics_thresholds 作 hint）。
    返回 labeled_window_audit + miss_burst_audit，供 VLM 引用。
    """
    from audits import window_spans

    thresholds = load_thresholds()
    ulf_hint = thresholds.get("ULF") or {}
    tp = threshold_proposal or {}
    peak_min = float(tp.get("peak_over_quiet_min") or ulf_hint.get("peak_over_quiet_min") or 2.0)
    in_win_min = float(tp.get("in_window_ratio_min") or tp.get("in_window_envelope_ratio_min") or 1.5)
    min_burst = int(float(tp.get("min_burst_duration_s") or 60))
    max_burst = int(float(tp.get("max_burst_duration_s") or 900))
    merge_gap = int(float(tp.get("merge_gap_s") or 30))
    miss_overlap_max = float(tp.get("miss_overlap_max") or 0.15)

    h = load_ulf_h_csv(csv_path)
    obj = json.load(open(label_path, encoding="utf-8"))
    n = h.size
    if n < 100:
        return {"valid": False, "reason": "H too short"}

    envelope, hour = ulf_envelope_series(h, fs=fs)
    quiet = float(hour["envelope_quiet"]) or 1e-9
    spans = window_spans(obj, n)
    lmask = np.zeros(n, dtype=bool)
    events = (obj.get("ulf_event_annotation") or {}).get("matched_events") or []

    labeled_audit: list[dict[str, Any]] = []
    for rid, span in enumerate(spans):
        if span.get("i0") is None:
            labeled_audit.append({"region_id": rid, "valid": False, "note": span.get("note")})
            continue
        i0, i1 = int(span["i0"]), int(span["i1"])
        lmask[i0:i1] = True
        seg = envelope[i0:i1]
        w_max = float(np.max(seg)) if seg.size else 0.0
        ratio = w_max / quiet
        outside = envelope.copy()
        outside[lmask] = np.nan
        out_p90 = float(np.nanpercentile(outside[~np.isnan(outside)], 90)) if (~np.isnan(outside)).any() else quiet
        ev = events[rid] if rid < len(events) else {}
        if ratio >= in_win_min and w_max >= out_p90 * 0.8:
            audit = "supports_pi2"
        elif ratio >= in_win_min * 0.85:
            audit = "weak_pi2"
        else:
            audit = "contradicts_pi2"
        labeled_audit.append({
            "region_id": rid,
            "valid": True,
            "start_dt": ev.get("start_dt"),
            "end_dt": ev.get("end_dt"),
            "i0": i0,
            "i1": i1,
            "duration_s": i1 - i0,
            "window_max_envelope": round(w_max, 6),
            "peak_over_quiet_p30": round(ratio, 4),
            "outside_envelope_p90": round(out_p90, 6),
            "audit_labeled_window": audit,
            "thresholds_used": {"in_window_ratio_min": in_win_min},
        })

    thr = quiet * peak_min
    active = envelope > thr
    if merge_gap > 0:
        active = ndimage.binary_closing(active, structure=np.ones(merge_gap + 1))
    labeled_cc, n_feat = ndimage.label(active)
    miss_audit: list[dict[str, Any]] = []
    for lab in range(1, n_feat + 1):
        idx = np.where(labeled_cc == lab)[0]
        if idx.size < min_burst or idx.size > max_burst:
            continue
        i0, i1 = int(idx[0]), int(idx[-1]) + 1
        overlap = float(lmask[i0:i1].mean()) if lmask.any() else 0.0
        peak = float(np.max(envelope[i0:i1]))
        por = peak / quiet
        if overlap <= miss_overlap_max:
            miss_audit.append({
                "kind": "pi2_envelope_burst",
                "i0": i0,
                "i1": i1,
                "duration_s": i1 - i0,
                "peak_over_quiet_p30": round(por, 4),
                "overlap_labeled_fraction": round(overlap, 4),
                "audit_miss_label": "likely_miss" if por >= peak_min * 1.05 else "review",
            })
    miss_audit.sort(key=lambda r: -r["peak_over_quiet_p30"])

    uea = obj.get("ulf_event_annotation") or {}
    meta_flags: list[str] = []
    if uea.get("has_events") and not events:
        meta_flags.append("has_events_true_but_empty_matched_events")
    if uea.get("event_count") not in (None, len(events)) and events is not None:
        if uea.get("event_count") != len(events):
            meta_flags.append("event_count_mismatch")

    return {
        "valid": True,
        "thresholds_applied": {
            "peak_over_quiet_min": peak_min,
            "in_window_ratio_min": in_win_min,
            "min_burst_duration_s": min_burst,
            "max_burst_duration_s": max_burst,
            "merge_gap_s": merge_gap,
            "miss_overlap_max": miss_overlap_max,
            "from_pass1": bool(threshold_proposal),
            "provenance": (threshold_proposal or {}).get("provenance"),
        },
        "full_hour": hour,
        "labeled_window_audit": labeled_audit,
        "miss_burst_audit": miss_audit[:8],
        "metadata_flags": meta_flags,
    }


def rings_from_label(label_path: str) -> list[dict]:
    obj = json.load(open(label_path, encoding="utf-8"))
    return pixel_rings(obj)


def _polygon_area_pts(pts: list[tuple[float, float]]) -> float:
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for j, (x0, y0) in enumerate(pts):
        x1, y1 = pts[(j + 1) % len(pts)]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def mechanical_coverage_audit(
    label_path: str,
    *,
    iou_severe: float = 0.65,
    min_bbox_span_px: float = 0.0,
) -> dict[str, Any]:
    """
    Pre-Agent rules: degenerate bbox (w/h<=0) → 覆盖不足；
    bbox IoU >= iou_severe 或 intersection/min(area) >= iou_severe → 覆盖过多。
    AIA（HEK 框）与 EPB（mask 多边形）共用。
    """
    obj = json.load(open(label_path, encoding="utf-8"))
    modality = "EPB" if "hek_event_annotation" not in obj else "AIA"
    meta: list[dict[str, Any]] = []
    for ring in pixel_rings(obj):
        raw = ring.get("points") or []
        pts = [(float(p[0]), float(p[1])) for p in raw if isinstance(p, list) and len(p) >= 2]
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        bb = bbox_of_polygon(pts)
        w = bb["xmax"] - bb["xmin"]
        h = bb["ymax"] - bb["ymin"]
        meta.append({
            "region_id": len(meta),
            "shape_label": ring.get("label"),
            "bbox_full": bb,
            "width_px_full": round(w, 4),
            "height_px_full": round(h, 4),
            "area_px_full": _polygon_area_pts(pts),
        })

    region_issues: list[dict[str, Any]] = []
    for row in meta:
        w, h = row["width_px_full"], row["height_px_full"]
        if w <= min_bbox_span_px or h <= min_bbox_span_px:
            region_issues.append({
                "region_id": row["region_id"],
                "issue": "degenerate_bbox",
                "width_px_full": w,
                "height_px_full": h,
                "nine_defect_bucket": "覆盖不足",
                "verdict": "fail",
                "detail": f"bbox 宽={w}px 高={h}px，宽或高≤{min_bbox_span_px}，无法表达有效覆盖。",
            })
        elif row["area_px_full"] < 1.0:
            region_issues.append({
                "region_id": row["region_id"],
                "issue": "zero_area_polygon",
                "nine_defect_bucket": "覆盖不足",
                "verdict": "fail",
                "detail": "多边形面积≈0，覆盖不足/无效标注。",
            })

    severe_overlap_pairs: list[dict[str, Any]] = []
    for a in range(len(meta)):
        for b in range(a + 1, len(meta)):
            bb_a, bb_b = meta[a]["bbox_full"], meta[b]["bbox_full"]
            iou = bbox_iou(bb_a, bb_b)
            ios = bbox_ios(bb_a, bb_b)
            if iou < iou_severe and ios < iou_severe:
                continue
            trigger = "bbox_iou" if iou >= iou_severe else "intersection_over_smaller"
            severe_overlap_pairs.append({
                "region_a": meta[a]["region_id"],
                "region_b": meta[b]["region_id"],
                "label_a": meta[a].get("shape_label"),
                "label_b": meta[b].get("shape_label"),
                "ar_a": meta[a].get("shape_label"),
                "ar_b": meta[b].get("shape_label"),
                "bbox_iou": round(iou, 4),
                "intersection_over_smaller": round(ios, 4),
                "trigger": trigger,
                "issue": "severe_overlap",
                "nine_defect_bucket": "覆盖过多",
                "verdict": "fail",
                "detail": (
                    f"重叠严重：IoU={iou:.3f}，较小框被覆盖比例={ios:.3f}，"
                    f"阈值≥{iou_severe}（{trigger}），属覆盖过多/重复标注。"
                ),
            })

    mechanical_fail = bool(region_issues or severe_overlap_pairs)
    return {
        "modality": modality,
        "iou_severe_threshold": iou_severe,
        "n_regions": len(meta),
        "region_issues": region_issues,
        "severe_overlap_pairs": severe_overlap_pairs,
        "mechanical_fail": mechanical_fail,
        "nine_defect_index": 9,
        "nine_defect_name": "虚标与覆盖异常",
        "agent_note": "以上项送 Agent 前已机械判定；Pass1/2 不必推翻 fail，可仅对未命中机械规则的 region 做视觉/物理复核。",
    }


def annotation_overlap_audit(
    label_path: str,
    *,
    iou_min: float = 0.12,
    area_ratio_nested: float = 4.0,
    iou_severe: float = 0.65,
) -> dict[str, Any]:
    """Detect nested masks / duplicate labels (AIA HEK or EPB mask)."""
    obj = json.load(open(label_path, encoding="utf-8"))
    meta: list[dict[str, Any]] = []
    for ring in pixel_rings(obj):
        raw = ring.get("points") or []
        pts = [(float(p[0]), float(p[1])) for p in raw if isinstance(p, list) and len(p) >= 2]
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        meta.append({
            "region_id": len(meta),
            "shape_label": ring.get("label"),
            "ar_noaanum": ring.get("label"),
            "bbox_full": bbox_of_polygon(pts),
            "area_px_full": _polygon_area_pts(pts),
        })

    overlap_pairs: list[dict[str, Any]] = []
    for a in range(len(meta)):
        for b in range(a + 1, len(meta)):
            ia, ib = meta[a]["bbox_full"], meta[b]["bbox_full"]
            iou = bbox_iou(ia, ib)
            area_a, area_b = meta[a]["area_px_full"], meta[b]["area_px_full"]
            small, large = (a, b) if area_a <= area_b else (b, a)
            sb, lb = meta[small]["bbox_full"], meta[large]["bbox_full"]
            nested = (
                sb["xmin"] >= lb["xmin"] - 0.5
                and sb["ymin"] >= lb["ymin"] - 0.5
                and sb["xmax"] <= lb["xmax"] + 0.5
                and sb["ymax"] <= lb["ymax"] + 0.5
                and meta[large]["area_px_full"] >= meta[small]["area_px_full"] * area_ratio_nested
            )
            if iou >= iou_min or nested:
                overlap_pairs.append({
                    "region_a": meta[a]["region_id"],
                    "region_b": meta[b]["region_id"],
                    "ar_a": meta[a].get("ar_noaanum"),
                    "ar_b": meta[b].get("ar_noaanum"),
                    "bbox_iou": round(iou, 4),
                    "nested": nested,
                    "area_ratio": round(max(area_a, area_b) / max(min(area_a, area_b), 1.0), 2),
                })

    from collections import defaultdict

    by_ar: dict[str, list[int]] = defaultdict(list)
    for row in meta:
        key = str(row.get("ar_noaanum") or "_no_ar_num")
        by_ar[key].append(row["region_id"])
    duplicate_groups = [
        {"ar_noaanum": k if k != "_no_ar_num" else None, "region_ids": ids}
        for k, ids in by_ar.items()
        if len(ids) > 1
    ]

    suspect = [p for p in overlap_pairs if p["nested"] or p["bbox_iou"] >= 0.35]
    severe = [p for p in overlap_pairs if p["bbox_iou"] >= iou_severe]
    redundant_flags: list[dict[str, Any]] = []
    for p in suspect:
        kind = "nested_redundant"
        if p.get("ar_a") and p.get("ar_a") == p.get("ar_b"):
            kind = "duplicate_same_ar_id"
        bucket = "覆盖过多" if p["bbox_iou"] >= iou_severe else "冗余标注"
        redundant_flags.append({**p, "quality_class": kind, "roadshow_bucket": bucket})
    return {
        "n_regions": len(meta),
        "overlap_pairs": overlap_pairs,
        "duplicate_ar_groups": duplicate_groups,
        "suspect_redundant_pairs": suspect,
        "severe_overlap_pairs": severe,
        "iou_severe_threshold": iou_severe,
        "redundant_label_flags": redundant_flags,
        "note": (
            f"IoU≥{iou_severe} 见 mechanical_coverage_audit.severe_overlap_pairs；嵌套见 redundant_label_flags。"
        ),
    }


def scale_polygon(polygon: list[tuple[float, float]], scale: float) -> list[tuple[float, float]]:
    if scale == 1.0:
        return polygon
    inv = 1.0 / scale
    return [(x * inv, y * inv) for x, y in polygon]


def aia_metrics_for_image(image_path: str, label_path: str | None = None) -> dict[str, Any]:
    gray, scale = load_gray(image_path, max_side=1024)
    scene = aia_quiet_sun(gray)
    candidates = aia_candidate_regions(gray)
    full = Image.open(image_path)
    candidates_full = []
    for row in candidates:
        bb = row.get("bbox") or {}
        candidates_full.append({
            **row,
            "bbox_full": {
                "xmin": round(bb.get("xmin", 0) * scale, 1),
                "ymin": round(bb.get("ymin", 0) * scale, 1),
                "xmax": round(bb.get("xmax", 0) * scale, 1),
                "ymax": round(bb.get("ymax", 0) * scale, 1),
            },
        })
    out: dict[str, Any] = {
        "modality": "AIA",
        "image": os.path.basename(image_path),
        "working_scale_to_full": round(scale, 6),
        "full_width": full.size[0],
        "full_height": full.size[1],
        "scene": scene,
        "candidates": candidates_full,
    }
    if label_path and os.path.isfile(label_path):
        label_metrics = []
        for ring in rings_from_label(label_path):
            poly = [(float(x), float(y)) for x, y in ring["points"]]
            poly_work = [(x / scale, y / scale) for x, y in poly]
            label_metrics.append({
                "label": ring.get("label"),
                "polygon_full": poly,
                "bbox_full": bbox_of_polygon(poly),
                "metrics": aia_contrast_in_polygon(gray, poly_work),
            })
        out["label_reference"] = label_metrics
    return out


def epb_metrics_for_image(image_path: str, label_path: str | None = None) -> dict[str, Any]:
    gray, scale = load_gray(image_path, max_side=1024)
    residual, meta = epb_flat_field(gray)
    candidates = epb_dark_candidates(gray)
    out: dict[str, Any] = {
        "modality": "EPB",
        "image": os.path.basename(image_path),
        "working_scale_to_full": round(scale, 6),
        "residual_min": round(float(residual.min()), 4),
        "residual_max": round(float(residual.max()), 4),
        "candidates": candidates,
        **meta,
    }
    if label_path and os.path.isfile(label_path):
        shapes = []
        for ring in rings_from_label(label_path):
            poly = [(float(x), float(y)) for x, y in ring["points"]]
            poly_work = [(x / scale, y / scale) for x, y in poly]
            shapes.append({
                "label": ring.get("label"),
                "bbox_full": bbox_of_polygon(poly),
                "metrics": epb_depletion_in_polygon(gray, poly_work),
            })
        out["label_reference"] = shapes
        out["missed_label_candidates"] = missed_label_candidates_epb(
            image_path, label_path, top_k=4, gray=gray, scale=scale
        )
    return out


def default_thresholds_path() -> str:
    here = os.path.dirname(__file__)
    return os.path.join(here, "physics_thresholds.json")


def load_thresholds(path: str | None = None) -> dict[str, Any]:
    chosen = path or default_thresholds_path()
    if not os.path.isfile(chosen):
        return {}
    with open(chosen, encoding="utf-8") as handle:
        return json.load(handle)


def _polygon_area(verts: list[tuple[float, float]]) -> float:
    if len(verts) < 3:
        return 0.0
    area = 0.0
    for i, (x0, y0) in enumerate(verts):
        x1, y1 = verts[(i + 1) % len(verts)]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _long_diameter_full(polygon_full: list[tuple[float, float]]) -> float:
    bb = bbox_of_polygon(polygon_full)
    return max(bb["xmax"] - bb["xmin"], bb["ymax"] - bb["ymin"], 1.0)


def _annulus_outside(
    inside: np.ndarray,
    d_px: float,
    inner_factor: float,
    outer_factor: float,
) -> np.ndarray:
    """Pixels outside polygon with distance to inside in [inner_factor*d, outer_factor*d]."""
    dist = ndimage.distance_transform_edt(~inside)
    return (~inside) & (dist >= inner_factor * d_px) & (dist <= outer_factor * d_px)


def _region_means(gray: np.ndarray, inside: np.ndarray, rings: list[np.ndarray]) -> dict[str, float | None]:
    out: dict[str, float | None] = {"mean_inside": None}
    if inside.any():
        out["mean_inside"] = float(np.mean(gray[inside]))
    for i, ring in enumerate(rings):
        key = f"mean_ring_{i}"
        out[key] = float(np.mean(gray[ring])) if ring.any() else None
    return out


def _aia_support(mean_in: float | None, mean_ring: float | None, sigma: float) -> str:
    if mean_in is None or mean_ring is None:
        return "insufficient_samples"
    delta = mean_in - mean_ring
    if delta > max(0.5 * sigma, 1.0):
        return "supports_brighter_core"
    if delta < -max(0.5 * sigma, 1.0):
        return "contradicts_brighter_core"
    return "weak_contrast"


AIA_DISPLAY_CLIP_DN = 252.0


def _aia_saturation_audit(
    mean_inside: float | None,
    inside: np.ndarray,
    gray: np.ndarray,
) -> dict[str, Any]:
    if mean_inside is None or not inside.any():
        return {"valid": False}
    hi = float(np.percentile(gray, 99.5)) if gray.size else 255.0
    clip_dn = max(AIA_DISPLAY_CLIP_DN, hi - 2.0)
    frac_at_clip = float(np.mean(gray[inside] >= clip_dn))
    saturated_core = mean_inside >= clip_dn - 1.0 or frac_at_clip >= 0.85
    return {
        "valid": True,
        "clip_dn_assumed": round(clip_dn, 2),
        "bright_at_clip_fraction": round(frac_at_clip, 4),
        "saturated_core_likely": saturated_core,
    }


def _aia_composite_hint(
    audit_05: str,
    gradient: dict[str, Any] | None,
    *,
    mean_inside: float | None,
    saturation: dict[str, Any] | None,
) -> str:
    """Synthesize ring vs gradient; ring support alone must not imply boundary consistency."""
    ga = gradient or {}
    bound = ga.get("audit_boundary_gradient") or ""
    bound_ok = bound in {
        "supports_boundary_step",
        "weak_boundary_step",
        "supports_radial_envelope",
    }
    ring_weak = audit_05 == "weak_contrast"
    ring_supports = audit_05 == "supports_brighter_core"
    saturated = bool((saturation or {}).get("saturated_core_likely"))

    if ring_weak and bound_ok:
        return "weak_far_ring_but_local_boundary_supported"
    if ring_supports and bound_ok:
        return "ring_and_boundary_consistent"
    if ring_supports and bound in {"flat_boundary", "contradicts_brighter_inside"}:
        if saturated or (mean_inside is not None and mean_inside >= AIA_DISPLAY_CLIP_DN - 1.0):
            return "ring_bright_but_saturation_no_boundary"
        return "ring_bright_but_flat_boundary"
    if ring_supports:
        return "ring_bright_boundary_mismatch"
    return bound or "unknown"


def _gradient_audit_aia(
    gray: np.ndarray,
    inside: np.ndarray,
    d_px: float,
    sigma: float,
) -> dict[str, Any]:
    """Fine pass-2 check: boundary band DN step, Sobel gradient, radial shells (fractions of d)."""
    if not inside.any() or d_px <= 0:
        return {"valid": False}
    dist_in = ndimage.distance_transform_edt(inside)
    dist_out = ndimage.distance_transform_edt(~inside)
    band = float(max(1.0, min(4.0, 0.05 * d_px)))

    core = inside & (dist_in > band)
    rim_inside = inside & (dist_in <= band)
    rim_outside = (~inside) & (dist_out <= band)

    gx = ndimage.sobel(gray, axis=1)
    gy = ndimage.sobel(gray, axis=0)
    grad = np.hypot(gx, gy)

    mean_core = float(np.mean(gray[core])) if core.any() else None
    mean_rim_in = float(np.mean(gray[rim_inside])) if rim_inside.any() else None
    mean_rim_out = float(np.mean(gray[rim_outside])) if rim_outside.any() else None
    step = None if mean_rim_in is None or mean_rim_out is None else mean_rim_in - mean_rim_out

    boundary_mask = rim_inside | rim_outside
    mean_grad_boundary = float(np.mean(grad[boundary_mask])) if boundary_mask.any() else None
    mean_grad_core = float(np.mean(grad[core])) if core.any() else None

    radial: list[dict[str, Any]] = []
    for name, lo_f, hi_f in (
        ("0_0.25d_out", 0.0, 0.25),
        ("0.25_0.5d_out", 0.25, 0.5),
        ("0.5_1d_out", 0.5, 1.0),
        ("1_2d_out", 1.0, 2.0),
    ):
        lo, hi = lo_f * d_px, hi_f * d_px
        shell = (~inside) & (dist_out >= lo) & (dist_out < hi)
        radial.append({
            "shell": name,
            "mean_dn": round(float(np.mean(gray[shell])), 4) if shell.any() else None,
            "n_px": int(shell.sum()),
        })

    shell_05_1 = next((s for s in radial if s["shell"] == "0.5_1d_out"), None)
    core_minus_shell = None
    if mean_core is not None and shell_05_1 and shell_05_1.get("mean_dn") is not None:
        core_minus_shell = mean_core - float(shell_05_1["mean_dn"])

    radial_means = [s["mean_dn"] for s in radial if s.get("mean_dn") is not None]
    radial_monotonic = (
        len(radial_means) >= 2
        and all(radial_means[i] >= radial_means[i + 1] - 1.0 for i in range(len(radial_means) - 1))
    )

    audit = "insufficient_samples"
    grad_thr = max(0.6 * sigma, 1.5)
    step_strong = max(0.35 * sigma, 2.0)
    step_weak = max(0.12 * sigma, 0.5)
    if step is not None and mean_grad_boundary is not None:
        if step > step_strong and mean_grad_boundary >= grad_thr:
            audit = "supports_boundary_step"
        elif step > step_weak:
            audit = "weak_boundary_step"
        elif step < -step_strong:
            audit = "contradicts_brighter_inside"
        else:
            audit = "flat_boundary"

    envelope_thr = max(0.25 * sigma, 3.0)
    if (
        audit in {"flat_boundary", "weak_boundary_step", "insufficient_samples"}
        and core_minus_shell is not None
        and core_minus_shell >= envelope_thr
        and radial_monotonic
        and mean_grad_boundary is not None
        and mean_grad_boundary >= grad_thr
    ):
        audit = "supports_radial_envelope"

    return {
        "valid": True,
        "boundary_band_px": round(band, 3),
        "mean_core_dn": None if mean_core is None else round(mean_core, 4),
        "mean_rim_inside_dn": None if mean_rim_in is None else round(mean_rim_in, 4),
        "mean_rim_outside_dn": None if mean_rim_out is None else round(mean_rim_out, 4),
        "boundary_dn_step_inside_minus_outside": None if step is None else round(step, 4),
        "mean_grad_at_boundary": None if mean_grad_boundary is None else round(mean_grad_boundary, 4),
        "mean_grad_in_core": None if mean_grad_core is None else round(mean_grad_core, 4),
        "radial_profile_outside": radial,
        "core_minus_0.5_1d_shell_dn": None if core_minus_shell is None else round(core_minus_shell, 4),
        "radial_monotonic_outside": radial_monotonic,
        "audit_boundary_gradient": audit,
        "note": "五点 JSON 常为旋转矩形；weak_contrast 时看 boundary 台阶、径向壳层单调性、core_minus_0.5_1d_shell_dn。",
    }


def _scale_audit_aia(
    area_full: float,
    d_full: float,
    median_area: float,
    median_d: float,
    inside: np.ndarray,
    gray: np.ndarray,
    quiet_dn: float,
    sigma_dn: float,
    contrast_05_1: float | None,
) -> dict[str, Any]:
    area_ratio = area_full / max(median_area, 1.0)
    d_ratio = d_full / max(median_d, 1.0)
    bright_frac = float(np.mean(gray[inside] > quiet_dn + sigma_dn)) if inside.any() else 0.0
    audit = "appropriate"
    if area_ratio > 6.0 or (area_ratio > 3.0 and bright_frac < 0.35):
        audit = "oversized"
    elif area_ratio < 0.08 or d_ratio < 0.15:
        audit = "undersized_fragment"
    elif area_ratio > 2.5 or d_ratio > 2.5:
        audit = "large_vs_median"
    elif area_ratio < 0.35 and d_ratio < 0.6:
        audit = "small_vs_median"
    contrast_ok = contrast_05_1 is not None and contrast_05_1 > max(0.25 * sigma_dn, 2.0)
    scale_plausible = audit in {"appropriate", "small_vs_median", "large_vs_median"} or (
        audit == "oversized" and contrast_ok and bright_frac >= 0.45
    )
    return {
        "median_area_px_full": round(median_area, 2),
        "median_d_long_px_full": round(median_d, 2),
        "area_ratio_to_median": round(area_ratio, 3),
        "d_ratio_to_median": round(d_ratio, 3),
        "bright_pixel_fraction_inside": round(bright_frac, 4),
        "audit_scale": audit,
        "scale_plausible": scale_plausible,
    }


def missed_label_candidates_aia(
    image_path: str,
    label_path: str,
    *,
    top_k: int = 6,
    enhancement_sigma: float = 3.5,
    max_side: int = 2048,
    gray: np.ndarray | None = None,
    scale: float | None = None,
) -> dict[str, Any]:
    """Bright regions outside labeled union, size anchored to median label area on this image."""
    if gray is None or scale is None:
        gray, scale = load_gray(image_path, max_side=max_side)
    qs = aia_quiet_sun(gray)
    rings = rings_from_label(label_path)
    areas_full: list[float] = []
    d_longs: list[float] = []
    union = np.zeros(gray.shape, dtype=bool)
    for ring in rings:
        poly_full = [(float(x), float(y)) for x, y in ring["points"]]
        if len(poly_full) >= 2 and poly_full[0] == poly_full[-1]:
            poly_full = poly_full[:-1]
        areas_full.append(_polygon_area(poly_full))
        d_longs.append(_long_diameter_full(poly_full))
        poly_work = [(x / scale, y / scale) for x, y in poly_full]
        union |= _polygon_mask(gray.shape, poly_work)

    median_area = float(np.median(areas_full)) if areas_full else 10000.0
    median_d = float(np.median(d_longs)) if d_longs else 128.0
    disk_geo = aia_disk_area_full(gray, scale)
    disk_area_full = disk_geo["disk_area_full_px2"]
    min_area_full = disk_geo["miss_min_area_full_px2"]
    max_area_full = AIA_MISS_MAX_FRAC_OF_DISK * disk_area_full
    min_area = min_area_full / (scale**2)
    max_area = max_area_full / (scale**2)
    side_work = max(4.0, (min_area_full ** 0.5) / scale)
    margin = max(2, int(round(side_work * 0.25)))
    union_dilated = ndimage.binary_dilation(union, iterations=margin)

    cx_w, cy_w, r_work = detect_disk_from_gray(gray)
    yy, xx = np.ogrid[: gray.shape[0], : gray.shape[1]]
    disk = (xx - cx_w) ** 2 + (yy - cy_w) ** 2 <= r_work**2
    enhanced = (gray - qs["quiet_dn"]) / max(qs["sigma_dn"], 1e-3)
    enhanced[~disk] = 0
    mask = (enhanced > enhancement_sigma) & (~union_dilated) & disk
    labeled, n = ndimage.label(mask)

    candidates: list[dict[str, Any]] = []
    for label_id in range(1, n + 1):
        region = labeled == label_id
        area = int(region.sum())
        area_full_px = area * (scale**2)
        if area < min_area or area > max_area:
            continue
        if area_full_px < min_area_full * 0.85:
            continue
        ys, xs = np.where(region)
        bbox_area_full = float((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)) * (scale**2)
        if bbox_area_full > max_area_full:
            continue
        if area_full_px > max_area_full:
            continue
        cx_w, cy_w = float(xs.mean()), float(ys.mean())
        half = side_work / 2.0
        x0 = max(0.0, cx_w - half)
        y0 = max(0.0, cy_w - half)
        x1 = min(gray.shape[1] - 1.0, cx_w + half)
        y1 = min(gray.shape[0] - 1.0, cy_w + half)
        poly_work = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        metrics = aia_contrast_in_polygon(gray, poly_work)
        if not metrics.get("valid"):
            continue
        bbox_full = {
            "xmin": round(x0 * scale, 1),
            "ymin": round(y0 * scale, 1),
            "xmax": round(x1 * scale, 1),
            "ymax": round(y1 * scale, 1),
        }
        candidates.append({
            "candidate_id": len(candidates),
            "bbox_full": bbox_full,
            "centroid_full": [round(cx_w * scale, 1), round(cy_w * scale, 1)],
            "synthetic_polygon_full": [
                [bbox_full["xmin"], bbox_full["ymin"]],
                [bbox_full["xmax"], bbox_full["ymin"]],
                [bbox_full["xmax"], bbox_full["ymax"]],
                [bbox_full["xmin"], bbox_full["ymax"]],
            ],
            "reference_median_area_px_full": round(median_area, 2),
            "reference_median_d_px_full": round(median_d, 2),
            "component_area_px_full": round(area_full_px, 1),
            "disk_area_frac": round(area_full_px / max(disk_area_full, 1.0), 6),
            "peak_enhancement_sigma": round(float(enhanced[region].max()), 3),
            "preview_physics": metrics,
        })
    candidates.sort(key=lambda row: row["peak_enhancement_sigma"], reverse=True)
    candidates = candidates[:top_k]
    for idx, row in enumerate(candidates):
        row["candidate_id"] = idx
    return {
        "reference_median_area_px_full": round(median_area, 2),
        "reference_median_d_long_px_full": round(median_d, 2),
        "disk_geometry": disk_geo,
        "size_gate": {
            "min_area_work_px": round(min_area, 1),
            "max_area_work_px": round(max_area, 1),
            "min_area_full_px2": round(min_area_full, 1),
            "min_frac_of_disk": AIA_MISS_MIN_FRAC_OF_DISK,
            "method": "OPC viz_aia_ar.detect_disk + area >= frac*πR²",
        },
        "candidates": candidates,
        "note": "漏标候选须达日面面积比例阈值；HEK 事件框非全盘 AR 普查。",
    }


def _epb_valid_sky_mask(gray: np.ndarray, *, min_dn: float = 8.0) -> np.ndarray:
    """Mask ASI disk (exclude black padding); coarse brightness gate."""
    h, w = gray.shape
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    yy, xx = np.mgrid[:h, :w]
    disk = (xx - cx) ** 2 + (yy - cy) ** 2 <= (0.48 * min(h, w)) ** 2
    return disk & (gray >= min_dn)


def _epb_seeds_in_component(region: np.ndarray, residual: np.ndarray, *, max_seeds: int = 10) -> list[tuple[int, int]]:
    ys, xs = np.where(region)
    if ys.size == 0:
        return []
    order = np.argsort(residual[ys, xs])
    seeds: list[tuple[int, int]] = []
    min_sep = max(6, int(round(min(region.shape) * 0.02)))
    for idx in order[: max(30, max_seeds * 4)]:
        y, x = int(ys[idx]), int(xs[idx])
        if all((y - sy) ** 2 + (x - sx) ** 2 >= min_sep**2 for sy, sx in seeds):
            seeds.append((y, x))
        if len(seeds) >= max_seeds:
            break
    if not seeds:
        seeds.append((int(ys[order[0]]), int(xs[order[0]])))
    return seeds


def _epb_diffusion_grow(
    dark_mask: np.ndarray,
    residual: np.ndarray,
    seeds: list[tuple[int, int]],
    *,
    n_walks: int = EPB_MISS_DIFFUSION_WALKS,
    n_steps: int = EPB_MISS_DIFFUSION_STEPS,
    seed: int = 0,
) -> np.ndarray:
    """Biased random walks from dark seeds → visit heatmap → region (Brownian 近似)."""
    h, w = dark_mask.shape
    heat = np.zeros((h, w), dtype=np.float32)
    rng = np.random.default_rng(seed)
    for sy, sx in seeds:
        for _ in range(n_walks):
            y, x = sy, sx
            for _ in range(n_steps):
                if not (0 <= y < h and 0 <= x < w) or not dark_mask[y, x]:
                    break
                heat[y, x] += 1.0
                nbrs: list[tuple[int, int, float]] = []
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and dark_mask[ny, nx]:
                        nbrs.append((ny, nx, float(residual[ny, nx])))
                if not nbrs:
                    break
                nbrs.sort(key=lambda t: t[2])
                pick = nbrs[0] if rng.random() < 0.72 else nbrs[rng.integers(0, len(nbrs))]
                y, x = pick[0], pick[1]
    if heat.max() <= 0:
        region = np.zeros_like(dark_mask)
        for sy, sx in seeds:
            region[sy, sx] = True
        return region
    thr = max(2.0, float(np.percentile(heat[heat > 0], 55)))
    grown = heat >= thr
    grown &= dark_mask
    grown = ndimage.binary_closing(grown, iterations=2)
    return grown


def _epb_gradient_refine_region(region: np.ndarray, gray: np.ndarray, residual: np.ndarray) -> np.ndarray:
    """Snap boundary: keep pixels inside where residual below local band median."""
    if not region.any():
        return region
    m_in = float(np.median(residual[region]))
    gy, gx = np.gradient(gray)
    gmag = np.hypot(gx, gy)
    dil = ndimage.binary_dilation(region, iterations=2)
    shell = dil & ~region
    if shell.any():
        shell_med = float(np.median(residual[shell]))
        cutoff = m_in + 0.35 * (shell_med - m_in)
    else:
        cutoff = m_in + 0.5
    refined = region & (residual <= cutoff)
    edge = ndimage.binary_dilation(refined, iterations=1) & ~refined
    if edge.any() and float(gmag[edge].mean()) > float(gmag[refined].mean()) * 0.85:
        return refined
    return region


def _polygon_from_region(region: np.ndarray, scale: float, *, max_vertices: int = 72) -> list[list[float]]:
    eroded = ndimage.binary_erosion(region)
    boundary = region & ~eroded
    ys, xs = np.where(boundary)
    if xs.size < 3:
        ys, xs = np.where(region)
    if xs.size < 3:
        return []
    cx, cy = float(xs.mean()), float(ys.mean())
    angles = np.arctan2(ys - cy, xs - cx)
    order = np.argsort(angles)
    step = max(1, len(order) // max_vertices)
    poly = [[round(float(xs[i]) * scale, 1), round(float(ys[i]) * scale, 1)] for i in order[::step]]
    if poly and poly[0] != poly[-1]:
        poly.append(poly[0])
    return poly


def _epb_miss_band_audit(
    gray: np.ndarray,
    residual: np.ndarray,
    poly_work: list[tuple[float, float]],
    *,
    scale: float,
    median_area: float,
    sigma_bg: float,
) -> dict[str, Any]:
    inside = _polygon_mask(residual.shape, poly_work)
    if not inside.any():
        return {"valid": False}
    dil = ndimage.binary_dilation(inside, iterations=max(3, int(10 / max(scale, 1e-6))))
    outer = dil & ~inside
    m_in = float(np.mean(residual[inside]))
    m_out = float(np.mean(residual[outer])) if outer.any() else m_in
    dep = m_out - m_in
    area_full = float(inside.sum()) * (scale**2)
    area_ratio = area_full / max(median_area, 1.0)
    gy, gx = np.gradient(gray)
    gmag = np.hypot(gx, gy)
    er = ndimage.binary_erosion(inside)
    edge = inside & ~er
    g_edge = float(np.mean(gmag[edge])) if edge.any() else 0.0
    audit = _epb_support(m_in, m_out, sigma_bg)
    plausible_area = EPB_MISS_MIN_AREA_FRAC_MEDIAN <= area_ratio <= EPB_MISS_MAX_AREA_FRAC_MEDIAN
    if audit == "supports_depletion" and plausible_area:
        miss = "likely_miss"
    elif audit in {"supports_depletion", "weak_depletion"} and area_ratio >= EPB_MISS_MIN_AREA_FRAC_MEDIAN * 0.7:
        miss = "review"
    else:
        miss = "unlikely"
    return {
        "valid": True,
        "mean_inside": round(m_in, 4),
        "mean_outer_band": round(m_out, 4),
        "depletion_depth_dn": round(dep, 4),
        "depletion_sigma": round(dep / max(sigma_bg, 1e-6), 4),
        "area_px_full": round(area_full, 1),
        "area_ratio_to_median_label": round(area_ratio, 3),
        "boundary_gradient_mean": round(g_edge, 4),
        "audit_band_depletion": audit,
        "audit_miss_label": miss,
    }


def missed_label_candidates_epb(
    image_path: str,
    label_path: str,
    *,
    top_k: int = EPB_MISS_TOP_K_DEFAULT,
    depletion_sigma: float = EPB_MISS_DEPLETION_SIGMA,
    max_side: int = 2048,
    gray: np.ndarray | None = None,
    scale: float | None = None,
    fast: bool = False,
) -> dict[str, Any]:
    """EPB 漏标：普适暗区 → 连通域 → 多种子扩散 → 梯度轮廓（不用 AIA 环带）。"""
    if gray is None or scale is None:
        gray, scale = load_gray(image_path, max_side=max_side)
    residual, flat_meta = epb_flat_field(gray)
    sigma_r = float(np.std(residual)) or 1.0
    sky = _epb_valid_sky_mask(gray)
    sky_vals = residual[sky]
    dark_level = float(np.percentile(sky_vals, EPB_MISS_DARK_PERCENTILE)) if sky_vals.size else 0.0

    rings = rings_from_label(label_path)
    areas_full: list[float] = []
    d_longs: list[float] = []
    union = np.zeros(gray.shape, dtype=bool)
    for ring in rings:
        pts = [(float(x), float(y)) for x, y in ring["points"]]
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        areas_full.append(_polygon_area(pts))
        d_longs.append(_long_diameter_full(pts))
        poly_work = [(x / scale, y / scale) for x, y in pts]
        union |= _polygon_mask(gray.shape, poly_work)

    frame_area_full = float(gray.shape[0] * gray.shape[1]) * (scale**2)
    median_area = float(np.median(areas_full)) if areas_full else 12000.0
    median_d = float(np.median(d_longs)) if d_longs else 120.0
    min_area_full = max(
        EPB_MISS_MIN_FRAC_OF_FRAME * frame_area_full,
        EPB_MISS_MIN_AREA_FRAC_MEDIAN * median_area,
    )
    max_area_full = min(
        EPB_MISS_MAX_FRAC_OF_FRAME * frame_area_full,
        EPB_MISS_MAX_AREA_FRAC_MEDIAN * median_area,
    )
    min_area = min_area_full / (scale**2)
    max_area = max_area_full / (scale**2)
    margin = max(2, int(round((median_d / scale) * 0.08)))
    union_dilated = ndimage.binary_dilation(union, iterations=margin)

    dark_seed = (residual <= dark_level) | (residual < (-depletion_sigma * 0.65 * sigma_r))
    dark_mask = dark_seed & sky & (~union_dilated)
    labeled, n = ndimage.label(dark_mask)

    n_walks = max(16, EPB_MISS_DIFFUSION_WALKS // (2 if fast else 1))
    n_steps = max(60, EPB_MISS_DIFFUSION_STEPS // (2 if fast else 1))

    raw_candidates: list[dict[str, Any]] = []
    for label_id in range(1, n + 1):
        comp = labeled == label_id
        area_px = int(comp.sum())
        area_full_px = area_px * (scale**2)
        if area_px < min_area or area_px > max_area:
            continue
        seeds = _epb_seeds_in_component(comp, residual, max_seeds=8 if fast else 12)
        grown = _epb_diffusion_grow(dark_mask, residual, seeds, n_walks=n_walks, n_steps=n_steps)
        grown |= comp
        grown = _epb_gradient_refine_region(grown, gray, residual)
        if int(grown.sum()) < min_area:
            continue
        poly_full = _polygon_from_region(grown, scale, max_vertices=56 if fast else 72)
        if len(poly_full) < 4:
            continue
        poly_work = [(x / scale, y / scale) for x, y in poly_full[:-1]]
        band = _epb_miss_band_audit(
            gray, residual, poly_work, scale=scale, median_area=median_area, sigma_bg=sigma_r
        )
        if not band.get("valid"):
            continue
        if band.get("audit_miss_label") == "unlikely" and (band.get("depletion_sigma") or 0) < depletion_sigma * 0.5:
            continue
        bb = bbox_of_polygon([(p[0], p[1]) for p in poly_full[:-1]])
        ys, xs = np.where(grown)
        raw_candidates.append({
            "bbox_full": {k: round(v, 1) for k, v in bb.items()},
            "centroid_full": [round(float(xs.mean()) * scale, 1), round(float(ys.mean()) * scale, 1)],
            "synthetic_polygon_full": poly_full,
            "component_area_px_full": round(float(grown.sum()) * (scale**2), 1),
            "n_seeds": len(seeds),
            "peak_depletion_sigma": band.get("depletion_sigma"),
            "area_ratio_to_median": band.get("area_ratio_to_median_label"),
            "preview_physics": band,
            "contour_method": EPB_MISS_METHOD,
        })

    raw_candidates.sort(
        key=lambda r: (
            {"likely_miss": 2, "review": 1, "unlikely": 0}.get(
                (r.get("preview_physics") or {}).get("audit_miss_label", ""), 0
            ),
            r.get("peak_depletion_sigma") or 0,
        ),
        reverse=True,
    )
    candidates: list[dict[str, Any]] = []
    for row in raw_candidates[:top_k]:
        row = dict(row)
        row["candidate_id"] = len(candidates)
        row["reference_median_area_px_full"] = round(median_area, 2)
        row["reference_median_d_px_full"] = round(median_d, 2)
        candidates.append(row)

    return {
        "modality": "EPB",
        "method": EPB_MISS_METHOD,
        "reference_median_area_px_full": round(median_area, 2),
        "reference_median_d_long_px_full": round(median_d, 2),
        "frame_area_full_px2": round(frame_area_full, 1),
        "dark_level_residual_dn": round(dark_level, 4),
        "size_gate": {
            "min_frac_of_frame": EPB_MISS_MIN_FRAC_OF_FRAME,
            "max_frac_of_frame": EPB_MISS_MAX_FRAC_OF_FRAME,
            "min_area_frac_of_median_label": EPB_MISS_MIN_AREA_FRAC_MEDIAN,
            "max_area_frac_of_median_label": EPB_MISS_MAX_AREA_FRAC_MEDIAN,
            "depletion_sigma_threshold": depletion_sigma,
        },
        "flat_field_meta": flat_meta,
        "candidates": candidates,
        "note": "暗条连通+扩散轮廓；Pass1 目视；Pass2 band_audit 复核。预期同图 0–2 条漏标候选。",
    }


def missed_label_audit_epb(
    image_path: str,
    label_path: str,
    *,
    mode: str = "full",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if mode == "skip":
        return {}, []
    fast = mode == "fast"
    max_side = 1024 if fast else 2048
    top_k = EPB_MISS_TOP_K_DEFAULT
    gray, scale = load_gray(image_path, max_side=max_side)
    miss_payload = missed_label_candidates_epb(
        image_path,
        label_path,
        top_k=top_k,
        max_side=max_side,
        gray=gray,
        scale=scale,
        fast=fast,
    )
    miss_ring = ring_audit_for_miss_candidates(
        image_path,
        miss_payload,
        gray=gray,
        scale=scale,
        max_side=max_side,
        lazy_gradient=fast,
        modality="EPB",
    )
    if fast:
        miss_payload["miss_audit_mode"] = "fast"
    return miss_payload, miss_ring


def ring_audit_for_miss_candidates(
    image_path: str,
    miss_payload: dict[str, Any],
    *,
    gray: np.ndarray | None = None,
    scale: float | None = None,
    max_side: int = 2048,
    lazy_gradient: bool = False,
    modality: str = "AIA",
) -> list[dict[str, Any]]:
    """Ring audit on synthetic boxes outside labels (AIA bright / EPB dark)."""
    cands = (miss_payload or {}).get("candidates") or []
    if not cands:
        return []
    modality = (modality or miss_payload.get("modality") or "AIA").upper()
    if gray is None or scale is None:
        gray, scale = load_gray(image_path, max_side=max_side)
    residual = None
    if modality == "EPB":
        residual, _ = epb_flat_field(gray)
        data = residual
        sigma_bg = float(np.std(residual)) or 1.0
    else:
        data = gray
        qs = aia_quiet_sun(gray)
        sigma_bg = qs["sigma_dn"]
    median_area = float(miss_payload.get("reference_median_area_px_full") or 10000)
    median_d = float(miss_payload.get("reference_median_d_long_px_full") or 128)
    rows: list[dict[str, Any]] = []
    for cand in cands:
        poly_full = [(float(x), float(y)) for x, y in cand.get("synthetic_polygon_full") or []]
        if len(poly_full) < 3:
            bb = cand.get("bbox_full") or {}
            poly_full = [
                (bb["xmin"], bb["ymin"]),
                (bb["xmax"], bb["ymin"]),
                (bb["xmax"], bb["ymax"]),
                (bb["xmin"], bb["ymax"]),
            ]
        d_full = _long_diameter_full(poly_full)
        d = d_full / scale
        poly_work = [(x / scale, y / scale) for x, y in poly_full[:-1] if len(poly_full) >= 3]
        if len(poly_work) < 3:
            poly_work = [(x / scale, y / scale) for x, y in poly_full]
        inside = _polygon_mask(data.shape, poly_work)
        if modality == "EPB":
            if residual is None:
                residual, _ = epb_flat_field(gray)
            band = _epb_miss_band_audit(
                gray, residual, poly_work, scale=scale, median_area=median_area, sigma_bg=sigma_bg
            )
            audit_ring = band.get("audit_band_depletion") or "insufficient_samples"
            contrast = band.get("depletion_depth_dn")
            m_in = band.get("mean_inside")
            m1 = band.get("mean_outer_band")
            gradient = {"boundary_gradient_mean": band.get("boundary_gradient_mean")}
            ar = band.get("area_ratio_to_median_label") or 0
            scale_audit = {
                "median_area_px_full": round(median_area, 2),
                "median_d_long_px_full": round(median_d, 2),
                "area_ratio_to_median": ar,
                "audit_scale": "appropriate" if EPB_MISS_MIN_AREA_FRAC_MEDIAN <= ar <= EPB_MISS_MAX_AREA_FRAC_MEDIAN else "atypical_vs_median",
                "scale_plausible": EPB_MISS_MIN_AREA_FRAC_MEDIAN <= ar <= EPB_MISS_MAX_AREA_FRAC_MEDIAN,
            }
        else:
            ring_05_1 = _annulus_outside(inside, d, 0.5, 1.0)
            ring_1_2 = _annulus_outside(inside, d, 1.0, 2.0)
            means = _region_means(data, inside, [ring_05_1, ring_1_2])
            m_in, m1, m2 = means["mean_inside"], means["mean_ring_0"], means["mean_ring_1"]
            audit_ring = _aia_support(m_in, m1, sigma_bg)
            contrast = None if m_in is None or m1 is None else m_in - m1
            qs = aia_quiet_sun(gray)
            need_gradient = not lazy_gradient or audit_ring == "weak_contrast"
            gradient = _gradient_audit_aia(gray, inside, d, sigma_bg) if need_gradient else None
            scale_audit = _scale_audit_aia(
                _polygon_area(poly_full),
                d_full,
                median_area,
                median_d,
                inside,
                gray,
                qs["quiet_dn"],
                sigma_bg,
                contrast,
            )
        row = {
            "candidate_id": cand.get("candidate_id"),
            "kind": "miss_label_candidate",
            "modality": modality,
            "centroid_full": cand.get("centroid_full"),
            "bbox_full": cand.get("bbox_full"),
            "d_long_px_full": round(d_full, 2),
            "mean_inside": None if m_in is None else round(m_in, 4),
            "mean_ring_0.5_1d": None if m1 is None else round(m1, 4),
            "contrast_inside_vs_0.5_1d": None if contrast is None else round(contrast, 4),
            "audit_0.5_1d": audit_ring,
            "gradient_audit": gradient if modality == "AIA" else None,
            "scale_audit": scale_audit,
        }
        if modality == "EPB":
            row["audit_miss_label"] = band.get("audit_miss_label") or "unlikely"
            row["band_audit"] = band
            row["audit_0.5_1d"] = audit_ring
            row["contrast_inside_vs_outer_band"] = contrast
        else:
            ga = row["gradient_audit"] or {}
            if row["audit_0.5_1d"] == "supports_brighter_core" or ga.get("audit_boundary_gradient") in {
                "supports_boundary_step",
                "supports_radial_envelope",
            }:
                row["audit_miss_label"] = "likely_miss"
            elif row["audit_0.5_1d"] == "weak_contrast":
                row["audit_miss_label"] = "review"
            else:
                row["audit_miss_label"] = "unlikely"
        rows.append(row)
    return rows


def missed_label_audit_aia(
    image_path: str,
    label_path: str,
    *,
    mode: str = "full",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One PNG load; mode full|fast|skip. fast ≈ 1024 + top3 + lazy gradient (batch CSV)."""
    if mode == "skip":
        return {}, []
    fast = mode == "fast"
    max_side = 1024 if fast else 2048
    top_k = 3 if fast else 6
    gray, scale = load_gray(image_path, max_side=max_side)
    miss_payload = missed_label_candidates_aia(
        image_path,
        label_path,
        top_k=top_k,
        max_side=max_side,
        gray=gray,
        scale=scale,
    )
    miss_ring = ring_audit_for_miss_candidates(
        image_path,
        miss_payload,
        gray=gray,
        scale=scale,
        max_side=max_side,
        lazy_gradient=fast,
    )
    if fast:
        miss_payload["miss_audit_mode"] = "fast"
    return miss_payload, miss_ring


def _epb_support(mean_in: float | None, mean_ring: float | None, sigma: float) -> str:
    """Residual: more negative inside => depletion supports EPB box."""
    if mean_in is None or mean_ring is None:
        return "insufficient_samples"
    delta = mean_ring - mean_in
    if delta > max(0.5 * sigma, 0.5):
        return "supports_depletion"
    if delta < -max(0.5 * sigma, 0.5):
        return "contradicts_depletion"
    return "weak_depletion"


def ring_audit_for_image(image_path: str, label_path: str, modality: str) -> list[dict[str, Any]]:
    """Pass-2 numeric audit: compare inside box vs rings at 0.5d–1d and 1d–2d (d = long diameter, full px)."""
    gray, scale = load_gray(image_path, max_side=2048)
    modality = modality.upper()
    residual = None
    sigma_bg = float(np.std(gray)) or 1.0
    if modality == "EPB":
        residual, _ = epb_flat_field(gray)
        sigma_bg = float(np.std(residual)) or 1.0
        data = residual
    else:
        data = gray
        sigma_bg = float(aia_quiet_sun(gray)["sigma_dn"])

    label_rings = rings_from_label(label_path)
    specs: list[tuple[float, float]] = []
    for ring in label_rings:
        poly_full = [(float(x), float(y)) for x, y in ring["points"]]
        if len(poly_full) >= 2 and poly_full[0] == poly_full[-1]:
            poly_full = poly_full[:-1]
        specs.append((_polygon_area(poly_full), _long_diameter_full(poly_full)))
    median_area = float(np.median([s[0] for s in specs])) if specs else 1.0
    median_d = float(np.median([s[1] for s in specs])) if specs else 1.0
    quiet_aia = aia_quiet_sun(gray) if modality == "AIA" else {}

    rows: list[dict[str, Any]] = []
    for region_id, ring in enumerate(label_rings):
        poly_full = [(float(x), float(y)) for x, y in ring["points"]]
        if len(poly_full) >= 2 and poly_full[0] == poly_full[-1]:
            poly_full = poly_full[:-1]
        area_full = _polygon_area(poly_full)
        d_full = _long_diameter_full(poly_full)
        d = d_full / scale
        poly_work = [(x / scale, y / scale) for x, y in poly_full]
        inside = _polygon_mask(data.shape, poly_work)
        if modality == "EPB":
            band = _epb_miss_band_audit(
                gray, residual, poly_work, scale=scale, median_area=median_area, sigma_bg=sigma_bg
            )
            ar = band.get("area_ratio_to_median_label") or (area_full / max(median_area, 1))
            row = {
                "region_id": region_id,
                "caption": ring.get("label"),
                "d_long_px_full": round(d_full, 2),
                "polygon_area_px_full": round(area_full, 2),
                "audit_method": "epb_polygon_band",
                "ring_definition": "fixed-px outer band around mask (not AIA 0.5d ring)",
                "mean_inside": band.get("mean_inside"),
                "mean_outer_band": band.get("mean_outer_band"),
                "contrast_inside_vs_outer_band": band.get("depletion_depth_dn"),
                "audit_0.5_1d": band.get("audit_band_depletion"),
                "band_audit": band,
                "boundary_gradient_mean": band.get("boundary_gradient_mean"),
                "unit": "DN_residual",
                "scale_audit": {
                    "median_area_px_full": round(median_area, 2),
                    "area_ratio_to_median": round(ar, 3),
                    "audit_scale": "appropriate" if 0.15 <= ar <= 4.0 else "atypical_vs_median",
                    "scale_plausible": 0.12 <= ar <= 5.0,
                },
            }
            rows.append(row)
            continue
        ring_05_1 = _annulus_outside(inside, d, 0.5, 1.0)
        ring_1_2 = _annulus_outside(inside, d, 1.0, 2.0)
        means = _region_means(data, inside, [ring_05_1, ring_1_2])
        m_in = means["mean_inside"]
        m1 = means["mean_ring_0"]
        m2 = means["mean_ring_1"]
        row = {
            "region_id": region_id,
            "caption": ring.get("label"),
            "d_long_px_full": round(d_full, 2),
            "polygon_area_px_full": round(area_full, 2),
            "ring_definition": "outside polygon, geodesic px distance to inside in [0.5d,1d] and [1d,2d]",
            "mean_inside": None if m_in is None else round(m_in, 4),
            "mean_ring_0.5_1d": None if m1 is None else round(m1, 4),
            "mean_ring_1_2d": None if m2 is None else round(m2, 4),
            "contrast_inside_vs_0.5_1d": None if m_in is None or m1 is None else round(m_in - m1, 4),
            "contrast_inside_vs_1_2d": None if m_in is None or m2 is None else round(m_in - m2, 4),
            "ring_0.5_1d_px_count": int(ring_05_1.sum()),
            "ring_1_2d_px_count": int(ring_1_2.sum()),
            "audit_0.5_1d": _aia_support(m_in, m1, sigma_bg),
            "audit_1_2d": _aia_support(m_in, m2, sigma_bg),
            "unit": "DN_luminance",
        }
        if modality == "AIA" and m_in is not None and m1 is not None:
            row["flux_ratio_inside_over_0.5_1d"] = round(m_in / max(m1, 1e-6), 4)
        if modality == "AIA":
            row["gradient_audit"] = _gradient_audit_aia(gray, inside, d, sigma_bg)
            row["scale_audit"] = _scale_audit_aia(
                area_full,
                d_full,
                median_area,
                median_d,
                inside,
                gray,
                quiet_aia["quiet_dn"],
                quiet_aia["sigma_dn"],
                row.get("contrast_inside_vs_0.5_1d"),
            )
            row["saturation_audit"] = _aia_saturation_audit(m_in, inside, gray)
            row["audit_composite_hint"] = _aia_composite_hint(
                row.get("audit_0.5_1d") or "",
                row["gradient_audit"],
                mean_inside=m_in,
                saturation=row["saturation_audit"],
            )
        rows.append(row)
    return rows
