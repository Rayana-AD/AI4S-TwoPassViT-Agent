#!/usr/bin/env python3
"""Write {dirId}_AIA对象质检.csv — one row per PNG, nine defect columns + per-region JSON."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from roadshow_paths import RESULTS_DIR, dir_aia_primary, ensure_agent_path

ensure_agent_path()

from aia_object_qc import CSV_COLUMNS, qc_aia_object, row_for_csv  # noqa: E402
from audits import pixel_rings  # noqa: E402


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
                index[oid] = row
    return index


def _qc_one_worker(args: tuple[str, str, str, dict | None, str]) -> dict[str, str]:
    dir_id, image, label, agent_record, miss_mode = args
    payload = qc_aia_object(
        dir_id,
        image,
        label,
        agent_record=agent_record,
        miss_mode=miss_mode,
    )
    return row_for_csv(payload)


def iter_pairs(dir_path: str, *, boxed_only: bool = True) -> list[tuple[str, str]]:
    label_dir = os.path.join(dir_path, "label")
    data_dir = os.path.join(dir_path, "data")
    nested = os.path.isdir(label_dir) and os.path.isdir(data_dir)
    scan_dir = label_dir if nested else dir_path
    pairs: list[tuple[str, str]] = []
    try:
        names = sorted(os.listdir(scan_dir))
    except OSError:
        return pairs
    for name in names:
        if not name.endswith(".json") or name.endswith(".csv.json"):
            continue
        label = os.path.join(scan_dir, name)
        try:
            obj = json.load(open(label, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if boxed_only and not pixel_rings(obj):
            continue
        sample = str((obj.get("basic_annotation") or {}).get("fileName") or "")
        if not sample.endswith(".png"):
            sample = name.replace(".json", "")
            if not sample.endswith(".png"):
                sample = sample + ".png" if not name.endswith(".png.json") else name[:-5]
        image = os.path.join(data_dir if nested else dir_path, sample)
        if os.path.isfile(image):
            pairs.append((image, label))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="AIA per-object nine-defect QC CSV (one dir).")
    parser.add_argument("--dir", default=dir_aia_primary(), help="AIA directory with data/ and label/")
    parser.add_argument(
        "--physics-jsonl",
        default=os.path.join(RESULTS_DIR, "AIA_physics_informed.jsonl"),
        help="Optional pass1/2 results to merge (else 轮廓/漏标/虚标=待判定)",
    )
    parser.add_argument("--all-labels", action="store_true", help="Include labels without pixel boxes")
    parser.add_argument("--limit", type=int, default=0, help="Max objects (0=all)")
    parser.add_argument(
        "--miss-mode",
        choices=("fast", "full", "skip"),
        default="fast",
        help="漏标：fast=单次1024+按需gradient；full=2048全量；skip=仅机械/规则",
    )
    parser.add_argument("--out", default="", help="Output CSV path")
    parser.add_argument("--jobs", type=int, default=1, help="Parallel workers for object QC (CPU)")
    parser.add_argument(
        "--postprocess",
        action="store_true",
        help="After CSV: 目录审计包/评分卡/缺陷排序/更新路演结果行",
    )
    args = parser.parse_args()

    dir_id = os.path.basename(os.path.normpath(args.dir))
    out_path = args.out or os.path.join(RESULTS_DIR, f"{dir_id}_AIA对象质检.csv")
    agent_index = _load_physics_index(args.physics_jsonl)

    pairs = iter_pairs(args.dir, boxed_only=not args.all_labels)
    if args.limit > 0:
        pairs = pairs[: args.limit]

    tasks = [
        (dir_id, image, label, agent_index.get(os.path.basename(image)), args.miss_mode)
        for image, label in pairs
    ]

    t0 = time.perf_counter()
    rows: list[dict[str, str]] = []
    stats = {"通过": 0, "不通过": 0, "待判定": 0, "不适用": 0}
    if args.jobs <= 1:
        for task in tasks:
            row = _qc_one_worker(task)
            stats[row["objectOverall"]] = stats.get(row["objectOverall"], 0) + 1
            rows.append(row)
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(_qc_one_worker, task): task for task in tasks}
            for fut in as_completed(futures):
                row = fut.result()
                stats[row["objectOverall"]] = stats.get(row["objectOverall"], 0) + 1
                rows.append(row)
        rows.sort(key=lambda r: r.get("objectId") or "")

    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "dirId": dir_id,
        "n_rows": len(rows),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "objectOverall_counts": stats,
        "physics_jsonl_hits": sum(1 for image, _ in pairs if os.path.basename(image) in agent_index),
        "miss_mode": args.miss_mode,
        "jobs": args.jobs,
        "out_csv": out_path,
        "spec": "路演结果/AIA九类缺陷质检对照与CSV说明.md",
    }
    json.dump(summary, open(out_path.replace(".csv", ".json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.postprocess:
        from aia_z4_postprocess import main as postprocess_main

        postprocess_main()


if __name__ == "__main__":
    main()
