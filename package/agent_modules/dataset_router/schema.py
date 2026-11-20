"""Directory profile schema for dataset router (machine + human readable)."""

from __future__ import annotations

from typing import Any, TypedDict


class VisualSample(TypedDict, total=False):
    path: str
    width: int
    height: int
    mode: str
    mean_luma: float
    std_luma: float
    dark_fraction: float
    bright_fraction: float
    aspect: float
    tags: list[str]


class AnnotationStats(TypedDict, total=False):
    n_json_sampled: int
    keys_frequency: dict[str, int]
    has_hek: int
    has_mask: int
    has_special_shapes: int
    has_ulf: int
    has_pixel_rings: int
    mask_epb_score_mean: float
    avg_vertices_per_ring: float


class DirectoryProfile(TypedDict, total=False):
    dir_id: str
    dir_path: str
    layout: str
    topology: dict[str, Any]
    annotation: AnnotationStats
    visual: dict[str, Any]
    summary_text: str


class RouteDecision(TypedDict, total=False):
    pipeline: str
    archetype_id: str
    confidence: float
    layout: str
    rationale: list[str]
    rag_hits: list[dict[str, Any]]
    profile: DirectoryProfile
    legacy_detect: dict[str, Any]