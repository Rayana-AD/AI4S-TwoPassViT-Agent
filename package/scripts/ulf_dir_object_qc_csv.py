#!/usr/bin/env python3
"""Write {dirId}_ULF对象质检.csv — flat ULF dir ({id}.csv + {id}.csv.json)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from roadshow_paths import RESULTS_DIR, dir_ulf_primary, ensure_agent_path

ensure_agent_path()

from ulf_object_qc import CSV_COLUMNS, qc_ulf_object, row_for_csv  # noqa: E402


def _physics_agent_record(row: dict) -> dict:
    agent = dict(row)
    p2 = agent.get("pass2") or {}
    if p2.get("window_audit") and not agent.get("window_audit"):
        agent["window_audit"] = p2["window_audit"]
    return agent


def _load_physics_index(jsonl_path: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    if not os.path.isfile(jsonl_path):
        return index
    with open(jsonl_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            oid = row.get("objectId") or row.get("id")
            if oid:
                index[oid] = _physics_agent_record(row)
    return index


def iter_pairs(dir_path: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for name in sorted(os.listdir(dir_path)):
        if not name.endswith(".csv") or name.endswith(".csv.json"):
            continue
        csv_path = os.path.join(dir_path, name)
        label = csv_path + ".json"
        if os.path.isfile(label):
            pairs.append((csv_path, label))
    return pairs


def _qc_one(args: tuple[str, str, str, dict | None]) -> dict[str, str]:
    dir_id, csv_path, label, agent = args
    return row_for_csv(qc_ulf_object(dir_id, csv_path, label, agent_record=agent))


def main() -> None:
    parser = argparse.ArgumentParser(description="ULF per-object QC CSV.")
    parser.add_argument("--dir", default=dir_ulf_primary())
    parser.add_argument(
        "--physics-jsonl",
        default=os.path.join(RESULTS_DIR, "ULF_physics_informed.jsonl"),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--postprocess", action="store_true")
    args = parser.parse_args()

    dir_id = os.path.basename(os.path.normpath(args.dir))
    out_path = args.out or os.path.join(RESULTS_DIR, f"{dir_id}_ULF对象质检.csv")
    agent_index = _load_physics_index(args.physics_jsonl)
    pairs = iter_pairs(args.dir)
    if args.limit > 0:
        pairs = pairs[: args.limit]

    t0 = time.perf_counter()
    rows: list[dict[str, str]] = []
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            futs = [
                pool.submit(
                    _qc_one,
                    (dir_id, csv_path, lab, agent_index.get(os.path.basename(csv_path))),
                )
                for csv_path, lab in pairs
            ]
            for fut in as_completed(futs):
                rows.append(fut.result())
    else:
        for csv_path, lab in pairs:
            rows.append(
                row_for_csv(
                    qc_ulf_object(
                        dir_id,
                        csv_path,
                        lab,
                        agent_record=agent_index.get(os.path.basename(csv_path)),
                    )
                )
            )
    rows.sort(key=lambda r: r.get("objectId") or "")

    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    sidecar = {
        "dirId": dir_id,
        "n_rows": len(rows),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "physics_jsonl": args.physics_jsonl,
        "n_physics_index": len(agent_index),
        "out_csv": out_path,
    }
    json.dump(sidecar, open(out_path.replace(".csv", ".json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(sidecar, ensure_ascii=False, indent=2))

    if args.postprocess:
        import subprocess
        import sys

        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "ulf_xfnog_postprocess.py")],
            check=True,
        )


if __name__ == "__main__":
    main()
