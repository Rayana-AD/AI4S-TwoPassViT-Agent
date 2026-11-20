"""Draw dataset JSON polygons on images for VLM (draw first, then resize once)."""

from __future__ import annotations

import io
import json
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from audits import pixel_rings

OVERLAY_COLORS = (
    (255, 48, 48),
    (48, 180, 255),
    (255, 200, 48),
    (180, 80, 255),
)


def _vertices(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) >= 2 and points[0] == points[-1]:
        return list(points[:-1])
    return list(points)


def _union_bbox(rings: list[dict], pad: float) -> tuple[int, int, int, int]:
    xs = [x for ring in rings for x, _ in ring["points"]]
    ys = [y for ring in rings for _, y in ring["points"]]
    if not xs:
        return 0, 0, 0, 0
    return (
        int(min(xs) - pad),
        int(min(ys) - pad),
        int(max(xs) + pad),
        int(max(ys) + pad),
    )


def render_json_overlay(
    image_path: str,
    label_path: str,
    *,
    max_side: int = 512,
    pad: float = 64.0,
    use_full_disk: bool | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Return PNG bytes and metadata. Polygons are JSON-accurate; image scaled uniformly after drawing."""
    full = Image.open(image_path).convert("RGB")
    fw, fh = full.size
    obj = json.load(open(label_path, encoding="utf-8"))
    rings = pixel_rings(obj)
    if not rings:
        return _resize_only(full, max_side, fw, fh, 0, 0)

    left, top, right, bottom = _union_bbox(rings, pad)
    left = max(0, left)
    top = max(0, top)
    right = min(fw, right)
    bottom = min(fh, bottom)
    union_area = max(0, right - left) * max(0, bottom - top)
    if use_full_disk is None:
        use_full_disk = len(rings) >= 2 or union_area > 0.35 * fw * fh

    if use_full_disk:
        canvas = full.copy()
        ox, oy = 0, 0
    else:
        canvas = full.crop((left, top, right, bottom))
        ox, oy = left, top

    draw = ImageDraw.Draw(canvas)
    cw, ch = canvas.size
    labeled: list[dict[str, Any]] = []

    for idx, ring in enumerate(rings):
        color = OVERLAY_COLORS[idx % len(OVERLAY_COLORS)]
        full_pts = [(float(x), float(y)) for x, y in ring["points"]]
        verts = _vertices(full_pts)
        local = [(x - ox, y - oy) for x, y in verts]
        if len(local) >= 3:
            draw.polygon(local, fill=None, outline=color, width=2)
        cap = _caption_for_ring(obj, ring, verts, idx)
        if local:
            draw.text((local[0][0] + 3, local[0][1] + 3), cap, fill=color)
        labeled.append({
            "region_id": idx,
            "caption": cap,
            "vertices_full": [[x, y] for x, y in verts],
        })

    out = _resize_canvas(canvas, max_side)
    scale = min(max_side / max(cw, ch), 1.0) if max(cw, ch) > max_side else 1.0
    meta = {
        "overlay_mode": "full_disk" if use_full_disk else "crop_union",
        "full_width": fw,
        "full_height": fh,
        "crop_origin": {"x0": ox, "y0": oy, "width": cw, "height": ch},
        "display_width": out.size[0],
        "display_height": out.size[1],
        "uniform_scale_after_draw": scale,
        "labeled_regions": labeled,
        "note": "彩色轮廓为 dataset JSON 多边形，不是模型生成。请判断轮廓是否贴住物理结构。",
    }
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue(), meta


def _caption_for_ring(obj: dict, ring: dict, verts: list[tuple[float, float]], idx: int) -> str:
    for event in (obj.get("hek_event_annotation") or {}).get("matched_events") or []:
        raw = _vertices([(float(p[0]), float(p[1])) for p in event.get("bbox_polygon_pixel") or [] if isinstance(p, list)])
        if len(raw) == len(verts) and all(abs(a[0] - b[0]) < 0.05 and abs(a[1] - b[1]) < 0.05 for a, b in zip(raw, verts)):
            num = event.get("ar_noaanum")
            return f"AR {num}" if num else f"AR#{idx}"
    return str(ring.get("label") or f"region_{idx}")


def _resize_canvas(canvas: Image.Image, max_side: int) -> Image.Image:
    longest = max(canvas.size)
    if longest <= max_side:
        return canvas
    ratio = max_side / longest
    return canvas.resize(
        (max(1, int(canvas.size[0] * ratio)), max(1, int(canvas.size[1] * ratio))),
        Image.Resampling.BILINEAR,
    )


def _resize_only(full: Image.Image, max_side: int, fw: int, fh: int, ox: int, oy: int) -> tuple[bytes, dict]:
    out = _resize_canvas(full, max_side)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue(), {
        "overlay_mode": "none",
        "full_width": fw,
        "full_height": fh,
        "crop_origin": {"x0": ox, "y0": oy, "width": fw, "height": fh},
        "display_width": out.size[0],
        "display_height": out.size[1],
        "labeled_regions": [],
    }
