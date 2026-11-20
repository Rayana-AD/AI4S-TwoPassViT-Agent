#!/usr/bin/env python3
"""Full AIA z4: object QC (473) → 目录审计包 → 评分卡/排序/日志 → 更新路演结果行."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from roadshow_paths import RESULTS_DIR, dir_aia_primary, ensure_agent_path

ensure_agent_path()

PY = sys.executable
DIR_ID = "AIA_AR_sample_z4h764sf2d"
LOG = os.path.join(RESULTS_DIR, f"{DIR_ID}_pipeline.log")


def _log(msg: str) -> None:
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _run(cmd: list[str], step: str) -> float:
    _log(f"START {step}: {' '.join(cmd)}")
    t0 = time.perf_counter()
    subprocess.run(cmd, check=True, cwd=os.path.dirname(os.path.abspath(__file__)))
    sec = round(time.perf_counter() - t0, 2)
    _log(f"DONE {step} in {sec}s")
    return sec


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-physics", action="store_true")
    parser.add_argument("--physics-only", action="store_true")
    parser.add_argument("--no-append", action="store_true", help="Re-run all physics (overwrite jsonl).")
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    open(LOG, "w").close()
    t_all = time.perf_counter()
    dir_path = dir_aia_primary()
    object_csv = os.path.join(RESULTS_DIR, f"{DIR_ID}_AIA对象质检.csv")
    physics_jsonl = os.path.join(RESULTS_DIR, "AIA_physics_informed.jsonl")

    timings: dict[str, float] = {}
    workers = int(os.environ.get("AIA_PHYSICS_WORKERS") or os.environ.get("PHYSICS_API_WORKERS", "2"))
    if not args.skip_physics:
        phys_cmd = [
            PY,
            os.path.join(RESULTS_DIR, "physics_informed_aia.py"),
            "--dir",
            dir_path,
            "--limit",
            "0",
            "--call",
            "--workers",
            str(workers),
        ]
        if not args.no_append:
            phys_cmd.append("--append")
        timings["physics_pass1_pass2"] = _run(phys_cmd, "physics_pass1_pass2")
    if args.physics_only:
        _log("physics-only done")
        return

    timings["object_qc+postprocess"] = _run(
        [
            PY,
            os.path.join(RESULTS_DIR, "aia_dir_object_qc_csv.py"),
            "--dir",
            dir_path,
            "--miss-mode",
            "fast",
            "--jobs",
            "8",
            "--physics-jsonl",
            physics_jsonl,
            "--postprocess",
        ],
        "object_qc+postprocess",
    )

    summary_path = os.path.join(RESULTS_DIR, f"{DIR_ID}_pipeline_summary.json")
    if os.path.isfile(summary_path):
        entry = json.load(open(summary_path, encoding="utf-8"))
        entry["pipeline_total_sec"] = round(time.perf_counter() - t_all, 2)
        entry["timings_sec"] = timings
        json.dump(entry, open(summary_path, "w"), ensure_ascii=False, indent=2)
    _log(f"ALL DONE → {object_csv}")


if __name__ == "__main__":
    main()
