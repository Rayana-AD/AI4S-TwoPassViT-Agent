#!/usr/bin/env python3
"""Scientific debater CLI: dataset_router → debate → auxiliary_metrics (experiments/ only)."""

from __future__ import annotations

import argparse
import json
import os
import sys

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(PIPELINE_ROOT, "package")
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))

from scientific_debater.debate_runner import run_debate_session  # noqa: E402

REPO_ROOT = os.environ.get("ROADSHOW_REPO_ROOT", os.path.dirname(PIPELINE_ROOT))
DEFAULT_PUBLISH = os.path.join(REPO_ROOT, "colab_subset", "publish")

SMOKE_DIRS = [
    ("CME", "CME_C2_sample_g8x0hw7reo"),
    ("DMSP", "DMSP_SSUSI_aaue04ws6s"),
    ("EPB", "EPB_seg_sample_pb72bbq4bp"),
    ("HMI", "HMI_AR_sample_6yaatkycjv"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Scientific debater (does not modify 星海舰队).")
    parser.add_argument("--dir", default="", help="One dataset directory")
    parser.add_argument("--secrets", default="", help="secrets.yaml for DeepSeek v4-pro / flash")
    parser.add_argument("--offline", action="store_true", help="No API; use archetype templates")
    parser.add_argument("--max-refine", type=int, default=1, help="LLM refine loops after calibration")
    parser.add_argument("--image-sample", type=int, default=3)
    parser.add_argument("--pipeline-check", action="store_true", help="Run run_pipeline --limit 2 --physics skip")
    parser.add_argument(
        "--teaching-mode",
        choices=("auto", "meta_only", "spine_full"),
        default="auto",
        help="auto=gated deep-test spine; meta_only=no z4/fbbqy symbols; spine_full=always show layers",
    )
    parser.add_argument(
        "--smoke-publish",
        action="store_true",
        help="Offline smoke on CME/DMSP/EPB/HMI (if present under colab_subset/publish)",
    )
    args = parser.parse_args()

    if args.smoke_publish:
        reports = []
        for label, name in SMOKE_DIRS:
            path = os.path.join(DEFAULT_PUBLISH, name)
            if not os.path.isdir(path):
                reports.append({"family": label, "dir": name, "skipped": "missing"})
                continue
            session = run_debate_session(
                path,
                secrets_path=args.secrets or None,
                offline=True,
                max_refine=0,
                image_sample=min(args.image_sample, 2),
                pipeline_check=False,
                teaching_mode=args.teaching_mode,
            )
            reports.append(
                {
                    "family": label,
                    "dir": name,
                    "pipeline": session.get("route", {}).get("pipeline"),
                    "archetype": session.get("route", {}).get("archetype_id"),
                    "ok": session.get("ok"),
                    "workspace": session.get("workspace"),
                }
            )
        out = os.path.join(PIPELINE_ROOT, "experiments", "scientific_debater", "smoke_publish_report.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump({"reports": reports}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(json.dumps({"smoke_publish": reports, "report": out}, ensure_ascii=False, indent=2))
        if not all(r.get("ok") for r in reports if not r.get("skipped")):
            raise SystemExit(1)
        return

    if not args.dir:
        raise SystemExit("Provide --dir or --smoke-publish")

    session = run_debate_session(
        args.dir,
        secrets_path=args.secrets or None,
        offline=args.offline,
        max_refine=args.max_refine,
        image_sample=args.image_sample,
        pipeline_check=args.pipeline_check,
        teaching_mode=args.teaching_mode,
    )
    print(json.dumps({"ok": session.get("ok"), "workspace": session.get("workspace"), "dir_id": session.get("dir_id")}, ensure_ascii=False, indent=2))
    if not session.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()