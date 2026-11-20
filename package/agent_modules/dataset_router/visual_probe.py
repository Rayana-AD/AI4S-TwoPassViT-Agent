"""Sample a few PNGs and extract coarse visual tags (no ML)."""

from __future__ import annotations

import os
import random
from typing import Any

from PIL import Image

from .schema import VisualSample


def _luma_stats(arr) -> tuple[float, float, float, float]:
    import numpy as np

    x = arr.astype("float32")
    if x.ndim == 3:
        x = 0.299 * x[..., 0] + 0.587 * x[..., 1] + 0.114 * x[..., 2]
    mean = float(x.mean())
    std = float(x.std())
    dark = float((x < mean - 0.5 * std).mean())
    bright = float((x > mean + 0.5 * std).mean())
    return mean, std, dark, bright


def _tags(mean: float, std: float, dark: float, bright: float, w: int, h: int) -> list[str]:
    tags: list[str] = []
    if max(w, h) >= 3000:
        tags.append("high_resolution")
    if w == h or abs(w - h) / max(w, h) < 0.05:
        tags.append("square_frame")
    if bright > 0.15 and mean > 80:
        tags.append("full_disk_bright")
    if dark > 0.08 and std > 25:
        tags.append("dark_streaks_on_bright_background")
    if std < 20:
        tags.append("low_contrast")
    if w > h * 1.2:
        tags.append("wide_aspect")
    return tags


def probe_image(path: str) -> VisualSample | None:
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            arr = __import__("numpy").array(im)
    except Exception:
        return None
    mean, std, dark, bright = _luma_stats(arr)
    return {
        "path": path,
        "width": w,
        "height": h,
        "mode": "RGB",
        "mean_luma": round(mean, 2),
        "std_luma": round(std, 2),
        "dark_fraction": round(dark, 4),
        "bright_fraction": round(bright, 4),
        "aspect": round(w / max(h, 1), 3),
        "tags": _tags(mean, std, dark, bright, w, h),
    }


def collect_png_paths(dir_path: str, limit: int = 4) -> list[str]:
    paths: list[str] = []
    data = os.path.join(dir_path, "data")
    if os.path.isdir(data):
        for name in sorted(os.listdir(data)):
            if name.endswith(".png"):
                paths.append(os.path.join(data, name))
    for name in sorted(os.listdir(dir_path)):
        if name.endswith(".png"):
            paths.append(os.path.join(dir_path, name))
    if len(paths) > limit:
        rng = random.Random(0)
        paths = rng.sample(paths, limit)
    return paths[:limit]


def probe_directory(dir_path: str, *, max_images: int = 4) -> dict[str, Any]:
    samples: list[VisualSample] = []
    for p in collect_png_paths(dir_path, limit=max_images):
        row = probe_image(p)
        if row:
            samples.append(row)
    tag_counts: dict[str, int] = {}
    for s in samples:
        for t in s.get("tags") or []:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    sizes = [(s["width"], s["height"]) for s in samples if s.get("width")]
    typical = f"{sizes[0][0]}x{sizes[0][1]}" if sizes else "n/a"
    return {
        "n_probed": len(samples),
        "samples": samples,
        "tag_counts": tag_counts,
        "typical_resolution": typical,
    }