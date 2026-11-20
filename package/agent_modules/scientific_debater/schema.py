from __future__ import annotations

from typing import Any, TypedDict


class DebateTurn(TypedDict, total=False):
    phase: str
    prompt_summary: str
    response: str
    usage: dict[str, int]
    model: str
    offline: bool


class SampleCalibration(TypedDict, total=False):
    image_path: str
    metrics: dict[str, Any]
    error: str


class DebateSession(TypedDict, total=False):
    dir_id: str
    dir_path: str
    route: dict[str, Any]
    workspace: str
    turns: list[DebateTurn]
    draft_script_path: str
    calibration: list[SampleCalibration]
    pipeline_dry_run: dict[str, Any]
    ok: bool
    notes: list[str]