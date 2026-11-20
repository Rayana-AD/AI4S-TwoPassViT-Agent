"""Debate-only RAG narrowing: few stable refs, small prompts for v0."""

from __future__ import annotations

import copy
from typing import Any

# v0 脚本合成时各阶段回答最长字符（完整辩题仍写入 DIALOGUE_BUNDLE 时可另存）
PHASE_ANSWER_CAPS: dict[str, int] = {
    "task_context": 1400,
    "defect_visual": 1600,
    "metric_proposals": 2000,
    "heuristic_geometry": 1400,
    "heuristic_image_defects": 1000,
    "heuristic_pre_v1": 2000,
    "heuristic_pre_v2": 2000,
}

SYNTHESIS_SLICE = 1600  # per section in synthesis_for_script(v0)


def cap_phase_answer(text: str, phase: str) -> str:
    lim = PHASE_ANSWER_CAPS.get(phase, 1800)
    text = (text or "").strip()
    if len(text) <= lim:
        return text
    return text[: lim - 1].rstrip() + "…"


def prepare_route_for_debate(route: dict[str, Any]) -> dict[str, Any]:
    """Keep 1 best-matching archetype hit + ≤2 reference URLs for debater prompts."""
    out = copy.deepcopy(route)
    hits = list(route.get("rag_hits") or [])
    archetype_id = route.get("archetype_id") or ""
    pipeline = route.get("pipeline") or ""

    best: dict[str, Any] | None = None
    for h in hits:
        if h.get("archetype_id") == archetype_id:
            best = h
            break
    if best is None and hits:
        best = hits[0]

    if best:
        refs = list(best.get("references") or [])[:2]
        slim = {
            "score": best.get("score"),
            "archetype_id": best.get("archetype_id"),
            "title": best.get("title"),
            "pipeline": best.get("pipeline"),
            "physics_track": best.get("physics_track"),
            "references": refs,
            "reasons": (best.get("reasons") or [])[:3],
        }
        out["rag_hits"] = [slim]
        out["rag_debate_note"] = "debater uses top-1 archetype + max 2 stable refs; dynamic GitHub search is prose-only."
    else:
        out["rag_hits"] = []
        out["rag_debate_note"] = f"no corpus hit; infer from pipeline={pipeline}"

    profile = out.get("profile") or {}
    summary = profile.get("summary_text") or ""
    if isinstance(summary, str) and len(summary) > 500:
        profile = {**profile, "summary_text": summary[:500] + "…"}
        out["profile"] = profile
    return out


def estimate_v0_prompt_chars(dialogue: dict[str, str]) -> dict[str, Any]:
    keys = [
        "task_context",
        "defect_visual",
        "metric_proposals",
        "heuristic_geometry",
        "heuristic_image_defects",
    ]
    per = {k: len((dialogue.get(k) or "")[:SYNTHESIS_SLICE]) for k in keys}
    return {"per_phase_capped": per, "synthesis_total": sum(per.values())}