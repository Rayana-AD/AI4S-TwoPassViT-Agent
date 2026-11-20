#!/usr/bin/env python3
"""dataset_router → scientific_debater (live API) → DEBATER_DEMO.md per dir."""

from __future__ import annotations

import argparse
import json
import os
import sys

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(PIPELINE_ROOT, "package")
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))

from dataset_router.router_agent import route_dataset_directory  # noqa: E402
from scientific_debater.debate_runner import run_debate_session  # noqa: E402
REPO_ROOT = os.environ.get("ROADSHOW_REPO_ROOT", os.path.dirname(PIPELINE_ROOT))
DEFAULT_PUBLISH = os.path.join(REPO_ROOT, "colab_subset", "publish")

DEFAULT_DIRS = [
    "DMSP_SSUSI_aaue04ws6s",
    "CME_C2_sample_g8x0hw7reo",
    "EPB_seg_sample_pb72bbq4bp",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", action="append", default=[], help="Dataset dir (repeatable)")
    parser.add_argument("--publish-demo", action="store_true", help="Run 3-type demo dirs")
    parser.add_argument("--secrets", default=os.path.join(REPO_ROOT, "secrets.yaml"))
    parser.add_argument("--max-refine", type=int, default=2)
    parser.add_argument("--image-sample", type=int, default=2)
    parser.add_argument("--pipeline-check", action="store_true")
    parser.add_argument("--teaching-mode", default="auto", choices=("auto", "meta_only", "spine_full"))
    args = parser.parse_args()

    dirs = list(args.dir)
    if args.publish_demo:
        dirs.extend(os.path.join(DEFAULT_PUBLISH, name) for name in DEFAULT_DIRS)
    if not dirs:
        raise SystemExit("Provide --dir or --publish-demo")

    os.environ.setdefault("MODEL_DISABLE_THINKING", "1")
    summary = []
    for dir_path in dirs:
        dir_path = os.path.abspath(dir_path)
        route = route_dataset_directory(dir_path, json_sample=12, image_sample=args.image_sample)
        session = run_debate_session(
            dir_path,
            secrets_path=args.secrets,
            offline=False,
            max_refine=args.max_refine,
            image_sample=args.image_sample,
            pipeline_check=args.pipeline_check,
            teaching_mode=args.teaching_mode,
        )
        summary.append(
            {
                "dir": os.path.basename(dir_path),
                "pipeline": route.get("pipeline"),
                "archetype": route.get("archetype_id"),
                "ok": session.get("ok"),
                "versions": session.get("script_versions"),
                "demo_report": session.get("demo_report"),
                "workspace": session.get("workspace"),
            }
        )

    index_dir = os.path.join(PIPELINE_ROOT, "experiments", "scientific_debater")
    os.makedirs(index_dir, exist_ok=True)
    index_path = os.path.join(index_dir, "LINKAGE_INDEX.json")
    json.dump({"runs": summary}, open(index_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    lines = ["# Router + Debater 联动索引\n", f"\n索引 JSON：`{index_path}`\n\n"]
    for row in summary:
        lines.append(
            f"- **{row['dir']}** · {row['pipeline']}/{row['archetype']} · "
            f"脚本版本 {row.get('versions')} · ok={row['ok']}\n"
            f"  - 报告：[DEBATER_DEMO.md]({row['demo_report']})\n"
        )
    index_md = os.path.join(index_dir, "LINKAGE_INDEX.md")
    with open(index_md, "w", encoding="utf-8") as handle:
        handle.write("".join(lines))

    print(json.dumps({"index_md": index_md, "runs": summary}, ensure_ascii=False, indent=2))
    if not all(r.get("ok") for r in summary):
        raise SystemExit(1)


if __name__ == "__main__":
    main()