#!/usr/bin/env python3
"""Smoke: AIA/EPB/ULF object QC (limit 3) — compare to baseline fingerprints."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(PIPELINE_ROOT)
PKG = os.path.join(PIPELINE_ROOT, "package")
AGENT = os.path.join(REPO_ROOT, "agent_modules")
PY = os.path.join(AGENT, ".venv", "bin", "python3")
if not os.path.isfile(PY):
    PY = sys.executable

os.environ.setdefault("AGENT_PIPELINE_ROOT", PIPELINE_ROOT)
os.environ.setdefault("ROADSHOW_REPO_ROOT", REPO_ROOT)
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))

from roadshow_paths import dir_aia_primary, dir_epb_primary, dir_ulf_primary, RESULTS_DIR, ensure_agent_path  # noqa: E402

ensure_agent_path()

SMOKE_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(SMOKE_DIR, "expected_baseline.json")
LAST = os.path.join(SMOKE_DIR, "last_run.json")
LIMIT = 3


def _data_ready(modality: str, dir_path: str) -> str | None:
    """Return skip reason if data missing; None if OK to run."""
    if not os.path.isdir(dir_path):
        return "missing_data_dir"
    if modality == "AIA":
        if not os.path.isdir(os.path.join(dir_path, "label")):
            return "missing_aia_label_dir"
    if modality in ("EPB", "ULF"):
        ext = ".json" if modality == "EPB" else ".csv"
        found = False
        with os.scandir(dir_path) as it:
            for i, ent in enumerate(it):
                if i > 200:
                    break
                if ent.name.endswith(ext):
                    found = True
                    break
        if not found:
            return f"missing_{modality.lower()}_labels"
    return None


def _fingerprint(csv_path: str) -> dict:
    if not os.path.isfile(csv_path):
        return {"error": "missing", "path": csv_path}
    with open(csv_path, encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        cols = reader.fieldnames or []
        rows = list(reader)
    sample = rows[0] if rows else {}
    keys = (
        "objectId",
        "objectOverall",
        "九1_文件配对",
        "九3b_轮廓贴合",
        "nRegions",
    )
    return {
        "path": csv_path,
        "n_rows": len(rows),
        "columns_head": cols[:8],
        "n_columns": len(cols),
        "sample": {k: sample.get(k) for k in keys if k in sample},
    }


def _run(modality: str, script: str, dir_path: str, extra: list[str] | None = None) -> dict:
    skip = _data_ready(modality, dir_path)
    if skip:
        return {
            "modality": modality,
            "skipped": True,
            "skip_reason": skip,
            "dir": dir_path,
            "fingerprint": {},
        }
    dir_id = os.path.basename(os.path.normpath(dir_path))
    out = os.path.join(RESULTS_DIR, f"_smoke_{dir_id}_{modality}对象质检.csv")
    cmd = [
        PY,
        os.path.join(PKG, "scripts", script),
        "--dir",
        dir_path,
        "--limit",
        str(LIMIT),
        "--out",
        out,
        "--jobs",
        "1",
    ]
    if extra:
        cmd.extend(extra)
    t0 = time.perf_counter()
    subprocess.run(cmd, check=True, cwd=os.path.join(PKG, "scripts"))
    return {"modality": modality, "sec": round(time.perf_counter() - t0, 2), "fingerprint": _fingerprint(out)}


def main() -> None:
    runs = [
        _run(
            "AIA",
            "aia_dir_object_qc_csv.py",
            dir_aia_primary(),
            ["--miss-mode", "fast", "--physics-jsonl", os.path.join(RESULTS_DIR, "AIA_physics_informed.jsonl")],
        ),
        _run(
            "EPB",
            "epb_dir_object_qc_csv.py",
            dir_epb_primary(),
            ["--physics-jsonl", os.path.join(RESULTS_DIR, "EPB_physics_informed.jsonl")],
        ),
        _run(
            "ULF",
            "ulf_dir_object_qc_csv.py",
            dir_ulf_primary(),
            ["--physics-jsonl", os.path.join(RESULTS_DIR, "ULF_physics_informed.jsonl")],
        ),
    ]
    executed = [r for r in runs if not r.get("skipped")]
    skipped = [r for r in runs if r.get("skipped")]
    report = {"runs": runs, "limit": LIMIT, "executed": len(executed), "skipped": len(skipped)}
    json.dump(report, open(LAST, "w"), ensure_ascii=False, indent=2)

    ok = bool(executed)
    if os.path.isfile(BASELINE):
        base = json.load(open(BASELINE, encoding="utf-8"))
        ref_by_mod = {r.get("modality"): r for r in (base.get("runs") or [])}
        for run in executed:
            ref = ref_by_mod.get(run.get("modality")) or {}
            fp = run.get("fingerprint") or {}
            rf = ref.get("fingerprint") or {}
            if fp.get("n_rows") != rf.get("n_rows"):
                ok = False
            if fp.get("n_columns") != rf.get("n_columns"):
                ok = False
    else:
        json.dump(report, open(BASELINE, "w"), ensure_ascii=False, indent=2)
        print("Wrote new baseline:", BASELINE)

    summary = {
        "ok": ok,
        "last": LAST,
        "executed_modalities": [r["modality"] for r in executed],
        "skipped_modalities": [{r["modality"]: r.get("skip_reason")} for r in skipped],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
