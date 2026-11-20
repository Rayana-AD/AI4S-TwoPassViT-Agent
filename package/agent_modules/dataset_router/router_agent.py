"""Dataset router subagent: profile → RAG match → pipeline recommendation."""

from __future__ import annotations

import json
from typing import Any

from .profiler import profile_directory
from .route_from_profile import decide_pipeline
from .schema import DirectoryProfile, RouteDecision


def route_dataset_directory(
    dir_path: str,
    *,
    json_sample: int = 20,
    image_sample: int = 4,
    compare_legacy: bool = True,
) -> RouteDecision:
    profile = profile_directory(dir_path, json_sample=json_sample, image_sample=image_sample)
    return decide_pipeline(profile, compare_legacy_path=dir_path if compare_legacy else None)


def route_dataset_profile(profile: DirectoryProfile, *, compare_legacy_path: str | None = None) -> RouteDecision:
    return decide_pipeline(profile, compare_legacy_path=compare_legacy_path)


def route_to_json(dir_path: str, **kwargs: Any) -> str:
    return json.dumps(route_dataset_directory(dir_path, **kwargs), ensure_ascii=False, indent=2)