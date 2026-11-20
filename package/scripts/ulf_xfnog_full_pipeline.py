#!/usr/bin/env python3
"""Full ULF xfnog: object QC (+ optional physics jsonl) → postprocess bundle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from roadshow_paths import RESULTS_DIR, dir_ulf_primary, ensure_agent_path

ensure_agent_path()

PY = sys.executable
DIR_ID = "ULF_sample_xfnogkdey9"
LOG = os.path.join(RESULTS_DIR, f"{DIR_ID}_pipeline.log")


def _log(msg: str) -> None:
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-physics", action="store_true")
    parser.add_argument("--physics-only", action="store_true")
    parser.add_argument("--no-append", action="store_true")
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    open(LOG, "w").close()
    t_all = time.perf_counter()
    dir_path = dir_ulf_primary()
    physics = os.path.join(RESULTS_DIR, "ULF_physics_informed.jsonl")
    timings: dict[str, float] = {}
    workers = int(os.environ.get("PHYSICS_API_WORKERS", "8"))
    if not args.skip_physics:
        phys_cmd = [
            PY,
            os.path.join(RESULTS_DIR, "physics_informed_ulf.py"),
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
        t0 = time.perf_counter()
        _log(f"START physics: {' '.join(phys_cmd)}")
        subprocess.run(phys_cmd, check=True, cwd=os.path.dirname(__file__))
        timings["physics_pass1_pass2"] = round(time.perf_counter() - t0, 2)
        _log(f"DONE physics in {timings['physics_pass1_pass2']}s")
    if args.physics_only:
        _log("physics-only done")
        return

    cmd = [
        PY,
        os.path.join(RESULTS_DIR, "ulf_dir_object_qc_csv.py"),
        "--dir",
        dir_path,
        "--physics-jsonl",
        physics,
        "--jobs",
        "8",
        "--postprocess",
    ]
    t0 = time.perf_counter()
    _log(f"START {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=os.path.dirname(__file__))
    timings["object_qc+postprocess"] = round(time.perf_counter() - t0, 2)
    summary = os.path.join(RESULTS_DIR, f"{DIR_ID}_pipeline_summary.json")
    if os.path.isfile(summary):
        entry = json.load(open(summary, encoding="utf-8"))
        entry["pipeline_total_sec"] = round(time.perf_counter() - t_all, 2)
        entry["timings_sec"] = timings
        json.dump(entry, open(summary, "w"), ensure_ascii=False, indent=2)
    _log("ALL DONE")


if __name__ == "__main__":
    main()
