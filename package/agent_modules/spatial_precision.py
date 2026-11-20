"""How much of a contour sits on a brightness gradient, versus the same contour shifted aside.

Thresholds come only from unshifted annotations on clean versions.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

MAX_SIDE = 1024


def load_luminance(image_path: str) -> tuple[np.ndarray, float]:
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    scale = 1.0
    if max(width, height) > MAX_SIDE:
        scale = MAX_SIDE / max(width, height)
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.BILINEAR)
    array = np.asarray(image, dtype=np.float32)
    luminance = 0.2126 * array[:, :, 0] + 0.7152 * array[:, :, 1] + 0.0722 * array[:, :, 2]
    return luminance, scale


def _scale_rings(rings: list[list[tuple[float, float]]], scale: float) -> list[list[tuple[float, float]]]:
    return [[(x * scale, y * scale) for x, y in ring] for ring in rings]


def _bounds(rings: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [point[0] for ring in rings for point in ring]
    ys = [point[1] for ring in rings for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def shift_vector(rings: list[list[tuple[float, float]]], width: int, height: int) -> tuple[float, float]:
    """Move the contour by a little more than its own width, staying inside the frame."""
    min_x, min_y, max_x, max_y = _bounds(rings)
    dx = max(12.0, (max_x - min_x) * 1.1)
    dy = max(8.0, (max_y - min_y) * 0.15)
    if max_x + dx >= width - 1:
        dx = -dx
    if max_y + dy >= height - 1:
        dy = -dy
    if min_x + dx < 0:
        dx = abs(dx)
    if min_y + dy < 0:
        dy = abs(dy)
    return dx, dy


def shift_rings(
    rings: list[list[tuple[float, float]]],
    dx: float,
    dy: float,
) -> list[list[tuple[float, float]]]:
    return [[(x + dx, y + dy) for x, y in ring] for ring in rings]


def _perimeter(ring: list[tuple[float, float]], step: float = 2.0, limit: int = 800) -> list[tuple[float, float]]:
    if len(ring) < 2:
        return list(ring)
    sequence = list(ring)
    if sequence[0] == sequence[-1]:
        sequence = sequence[:-1]
    if len(sequence) < 2:
        return sequence
    closed = sequence + [sequence[0]]
    points: list[tuple[float, float]] = []
    for start, end in zip(closed, closed[1:]):
        distance = math.hypot(end[0] - start[0], end[1] - start[1])
        steps = max(1, int(distance / step))
        for index in range(steps):
            weight = index / steps
            points.append((
                start[0] + (end[0] - start[0]) * weight,
                start[1] + (end[1] - start[1]) * weight,
            ))
            if len(points) >= limit:
                return points
    return points


def _edge_threshold(magnitude: np.ndarray) -> float:
    high = float(np.percentile(magnitude, 90))
    if high <= 0:
        high = float(magnitude.max()) * 0.2
    return high or 1.0


def edge_fraction(
    magnitude: np.ndarray,
    rings: list[list[tuple[float, float]]],
    threshold: float,
) -> float:
    height, width = magnitude.shape
    hits = 0
    total = 0
    for ring in rings:
        for x, y in _perimeter(ring):
            ix = int(round(x))
            iy = int(round(y))
            if ix < 0 or iy < 0 or ix >= width or iy >= height:
                continue
            total += 1
            if magnitude[iy, ix] >= threshold:
                hits += 1
    if total == 0:
        return 0.0
    return hits / total


def score_annotation(image_path: str, rings: list[list[tuple[float, float]]]) -> dict:
    """Margin is contour-on-gradient minus the same contour after a shift."""
    if not rings:
        return {
            "edge_fraction": 0.0,
            "shifted_edge_fraction": 0.0,
            "margin": 0.0,
            "shift": (0.0, 0.0),
            "applicable": False,
        }
    luminance, scale = load_luminance(image_path)
    scaled = _scale_rings(rings, scale)
    magnitude = np.hypot(*np.gradient(luminance))
    threshold = _edge_threshold(magnitude)
    height, width = luminance.shape
    dx, dy = shift_vector(scaled, width, height)
    base = edge_fraction(magnitude, scaled, threshold)
    shifted = edge_fraction(magnitude, shift_rings(scaled, dx, dy), threshold)
    return {
        "edge_fraction": float(base),
        "shifted_edge_fraction": float(shifted),
        "margin": float(base - shifted),
        "shift": (float(dx), float(dy)),
        "applicable": True,
    }


def calibrate_threshold(margins: list[float]) -> float:
    """10th percentile of positive-sample margins. Negatives are not used."""
    if not margins:
        return 0.0
    ordered = np.sort(np.asarray(margins, dtype=np.float64))
    index = int(0.10 * (len(ordered) - 1))
    return float(ordered[index])


def margin_status(margin: float, threshold: float) -> str:
    if margin + 1e-9 >= threshold:
        return "通过"
    return "待复核"


def near_threshold(margin: float, threshold: float) -> bool:
    span = max(0.05, abs(threshold))
    return abs(margin - threshold) <= span
