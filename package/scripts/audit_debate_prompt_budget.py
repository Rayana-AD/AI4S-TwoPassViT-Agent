#!/usr/bin/env python3
"""Dry-run debater pre-v0 prompt sizes (no LLM)."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "package")
sys.path.insert(0, os.path.join(PKG, "agent_modules"))

from dataset_router.router_agent import route_dataset_directory  # noqa: E402
from scientific_debater.debate_phases import (  # noqa: E402
    phase_defect_visual,
    phase_draft_script,
    phase_heuristic_geometry,
    phase_heuristic_image_defects,
    phase_metric_proposals,
    phase_task_context,
)
from scientific_debater.dialogue_bundle import synthesis_for_script  # noqa: E402
from scientific_debater.rag_context import prepare_route_for_debate  # noqa: E402

DIRS = [
    ("AIA", os.path.join(os.path.dirname(ROOT), "colab_subset", "publish", "AIA_AR_sample_mugm2urshy")),
    ("EPB", os.path.join(os.path.dirname(ROOT), "路演数据", "EPB_seg_sample_fbbqy66u2d")),
    ("ULF", os.path.join(os.path.dirname(ROOT), "路演数据", "ULF_sample_xfnogkdey9")),
]


def main() -> None:
    rows = []
    for modality, path in DIRS:
        if not os.path.isdir(path):
            rows.append({"modality": modality, "skip": path})
            continue
        route = route_dataset_directory(path, json_sample=12, image_sample=2)
        rd = prepare_route_for_debate(json.loads(json.dumps(route, default=str)))
        visual = (route.get("profile") or {}).get("visual") or {}
        arch = route.get("archetype_id") or "?"
        p1 = phase_task_context(rd)
        p2 = phase_defect_visual(arch, visual)
        p3 = phase_metric_proposals("（dry-run）", arch)
        p4 = phase_heuristic_geometry(route.get("pipeline") or "?", arch, p3)
        p5 = phase_heuristic_image_defects(route.get("pipeline") or "?", p2)
        synth = synthesis_for_script(
            {
                "task_context": "X" * 1400,
                "defect_visual": "Y" * 1600,
                "metric_proposals": "Z" * 2000,
                "heuristic_geometry": "G" * 1400,
                "heuristic_image_defects": "H" * 1600,
            },
            stage="v0",
        )
        v0p = phase_draft_script(arch, route.get("pipeline") or "?", p3, synthesis_block=synth, version_tag="v0")
        rows.append(
            {
                "modality": modality,
                "archetype_id": arch,
                "rag_hits_in": len(route.get("rag_hits") or []),
                "rag_hits_debate": len(rd.get("rag_hits") or []),
                "refs_debate": len((rd.get("rag_hits") or [{}])[0].get("references") or []),
                "prompt_chars": {
                    "task_context": len(p1),
                    "defect_visual": len(p2),
                    "metric_proposals_stub": len(p3),
                    "heuristic_geometry_stub": len(p4),
                    "heuristic_image_defects_stub": len(p5),
                    "v0_draft_prompt": len(v0p),
                    "synthesis_worst_case": len(synth),
                },
            }
        )
    out = os.path.join(ROOT, "experiments", "scientific_debater", "PROMPT_BUDGET_AUDIT.json")
    json.dump({"dirs": rows}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"written": out, "dirs": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()