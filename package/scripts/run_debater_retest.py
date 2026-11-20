#!/usr/bin/env python3
"""Full retest: router + debater (API) + evolution audit + Pass1 hook + index."""

from __future__ import annotations

import argparse
import json
import os
import sys

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(PIPELINE_ROOT, "package")
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))

from run_router_debater_linkage import DEFAULT_DIRS, DEFAULT_PUBLISH, main as _not_used  # noqa: F401
from dataset_router.router_agent import route_dataset_directory
from scientific_debater.debate_runner import run_debate_session

REPO_ROOT = os.environ.get("ROADSHOW_REPO_ROOT", os.path.dirname(PIPELINE_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Retest debater with teaching + Pass1 hook + evolution audit")
    parser.add_argument("--secrets", default=os.path.join(REPO_ROOT, "secrets.yaml"))
    parser.add_argument("--max-refine", type=int, default=2)
    parser.add_argument("--teaching-mode", default="auto")
    parser.add_argument("--dirs", nargs="*", default=DEFAULT_DIRS)
    args = parser.parse_args()
    os.environ.setdefault("MODEL_DISABLE_THINKING", "1")

    runs = []
    for name in args.dirs:
        path = os.path.join(DEFAULT_PUBLISH, name)
        if not os.path.isdir(path):
            runs.append({"dir": name, "skipped": True})
            continue
        route = route_dataset_directory(path, json_sample=12, image_sample=2)
        sess = run_debate_session(
            path,
            secrets_path=args.secrets,
            offline=False,
            max_refine=args.max_refine,
            image_sample=2,
            teaching_mode=args.teaching_mode,
        )
        runs.append(
            {
                "dir": name,
                "ok": sess.get("ok"),
                "best": sess.get("best_script_version"),
                "sane_evolution": (sess.get("evolution_audit") or {}).get("sane_evolution"),
                "pass1_hook": sess.get("pass1_hook_dry_run"),
                "demo": sess.get("demo_report"),
                "evolution_md": os.path.join(sess.get("workspace", ""), "EVOLUTION_AUDIT.md"),
            }
        )

    idx = os.path.join(PIPELINE_ROOT, "experiments", "scientific_debater", "RETEST_2026-11-19.json")
    json.dump({"runs": runs}, open(idx, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"index": idx, "runs": runs}, ensure_ascii=False, indent=2))
    if not all(r.get("ok") for r in runs if not r.get("skipped")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()