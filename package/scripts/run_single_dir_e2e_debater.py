#!/usr/bin/env python3
"""One dir: router → debater v0–v2 → Pass1/2 + QC + postprocess (with DEBATER_AUXILIARY_SCRIPT)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_ROOT = os.environ.get("ROADSHOW_REPO_ROOT", os.path.dirname(PIPELINE_ROOT))
PKG = os.path.join(PIPELINE_ROOT, "package")
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))

from dataset_router.router_agent import route_dataset_directory  # noqa: E402
from scientific_debater.debate_runner import run_debate_session  # noqa: E402


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dir",
        default=os.path.join(REPO_ROOT, "路演数据", "EPB_seg_sample_fbbqy66u2d"),
    )
    parser.add_argument("--max-refine", type=int, default=2)
    parser.add_argument("--physics-limit", type=int, default=2, help="Pass1/2 + QC object cap")
    parser.add_argument("--skip-debater", action="store_true")
    parser.add_argument("--skip-pipeline", action="store_true")
    parser.add_argument("--secrets", default=os.path.join(REPO_ROOT, "secrets.yaml"))
    args = parser.parse_args()

    dir_path = os.path.abspath(args.dir)
    dir_id = os.path.basename(os.path.normpath(dir_path))
    os.environ.setdefault("AGENT_PIPELINE_ROOT", PIPELINE_ROOT)
    os.environ.setdefault("ROADSHOW_REPO_ROOT", REPO_ROOT)
    os.environ.setdefault("MODEL_DISABLE_THINKING", "1")

    report: dict = {"dir_id": dir_id, "dir_path": dir_path, "steps": {}}
    t0 = time.perf_counter()

    route = route_dataset_directory(dir_path, json_sample=12, image_sample=2)
    report["router"] = {
        "pipeline": route.get("pipeline"),
        "archetype_id": route.get("archetype_id"),
        "confidence": route.get("confidence"),
        "layout": (route.get("profile") or {}).get("layout"),
    }

    workspace = os.path.join(PIPELINE_ROOT, "experiments", "scientific_debater", dir_id)
    script_path = os.path.join(workspace, "auxiliary_metrics.py")

    if not args.skip_debater:
        sess = run_debate_session(
            dir_path,
            secrets_path=args.secrets if os.path.isfile(args.secrets) else None,
            offline=not os.path.isfile(args.secrets),
            max_refine=args.max_refine,
            image_sample=3,
            pipeline_check=False,
            teaching_mode="spine_full",
        )
        report["debater"] = {
            "ok": sess.get("ok"),
            "v0_source": sess.get("v0_source"),
            "best_script_version": sess.get("best_script_version"),
            "script_versions": sess.get("script_versions"),
            "workspace": sess.get("workspace"),
            "pass1_hook": sess.get("pass1_hook_dry_run"),
            "evolution": sess.get("evolution_audit"),
        }
        script_path = os.path.join(sess["workspace"], "auxiliary_metrics.py")

    if not os.path.isfile(script_path):
        report["error"] = f"missing auxiliary script: {script_path}"
        _write(report, workspace, t0)
        raise SystemExit(2)

    if not args.skip_pipeline:
        env = os.environ.copy()
        env["DEBATER_AUXILIARY_SCRIPT"] = script_path
        cmd = [
            sys.executable,
            os.path.join(PIPELINE_ROOT, "agent", "run_pipeline.py"),
            "--dir",
            dir_path,
            "--limit",
            str(args.physics_limit),
            "--jobs",
            "2",
            "--physics",
            "call",
            "--physics-workers",
            "2",
            "--secrets",
            args.secrets,
        ]
        proc = subprocess.run(cmd, cwd=os.path.join(PKG, "scripts"), env=env, capture_output=True, text=True, timeout=3600)
        report["pipeline"] = {
            "ok": proc.returncode == 0,
            "auxiliary_script": script_path,
            "stdout_tail": (proc.stdout or "")[-3000:],
            "stderr_tail": (proc.stderr or "")[-1500:],
        }
        batch = os.path.join(PKG, "scripts", "路演结果", "run_pipeline_batch.json")
        if os.path.isfile(batch):
            report["pipeline"]["batch"] = json.load(open(batch, encoding="utf-8"))

    report["elapsed_sec"] = round(time.perf_counter() - t0, 2)
    _write(report, workspace, t0)
    print(json.dumps({"written": os.path.join(workspace, "SINGLE_DIR_E2E.json"), "ok": report.get("pipeline", {}).get("ok")}, ensure_ascii=False))


def _write(report: dict, workspace: str, t0: float) -> None:
    os.makedirs(workspace, exist_ok=True)
    path = os.path.join(workspace, "SINGLE_DIR_E2E.json")
    report["elapsed_sec"] = round(time.perf_counter() - t0, 2)
    json.dump(report, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()