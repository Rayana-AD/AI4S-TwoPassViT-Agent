#!/usr/bin/env python3
"""Write {dirId}_EPB对象质检.csv — flat EPB dir (png+json same folder)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from roadshow_paths import RESULTS_DIR, dir_epb_primary, ensure_agent_path

ensure_agent_path()

from epb_object_qc import CSV_COLUMNS, qc_epb_object, row_for_csv  # noqa: E402
from audits import pixel_rings  # noqa: E402


def _physics_agent_record(row: dict) -> dict:
    """Normalize physics-informed jsonl row for epb_object_qc."""
    if row.get("evaluation") or (row.get("pass2") or {}).get("parsed"):
        agent = dict(row)
        p2 = agent.get("pass2") or {}
        if p2.get("miss_ring_audit") and not agent.get("miss_ring_audit"):
            agent["miss_ring_audit"] = p2["miss_ring_audit"]
        if p2.get("ring_audit") and not agent.get("ring_audit"):
            agent["ring_audit"] = p2["ring_audit"]
        return agent
    return _legacy_epb_vlm_to_agent(row)


def _legacy_epb_vlm_to_agent(row: dict) -> dict:
    """Map EPB全目录模型.jsonl (是/否 crop C13) → epb_object_qc pass2 shape."""
    if row.get("evaluation") or (row.get("pass2") or {}).get("parsed"):
        return row
    raw = str(row.get("verdict") or "")
    if raw.startswith("是"):
        verdict = "合理"
    elif raw.startswith("否"):
        verdict = "不合理"
    else:
        return row
    per = [{"region_id": 0, "verdict": verdict, "reason": row.get("reason") or ""}]
    return {
        **row,
        "evaluation": {"per_region": per},
        "pass2": {"parsed": {"pass2_verdict": verdict, "per_region": per}},
    }


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


def _qc_one_worker(args: tuple[str, str, str, dict | None, str]) -> dict[str, str]:
    dir_id, image, label, agent_record, miss_mode = args
    return row_for_csv(
        qc_epb_object(dir_id, image, label, agent_record=agent_record, miss_mode=miss_mode)
    )


def iter_pairs(dir_path: str, *, masked_only: bool = True) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for name in sorted(os.listdir(dir_path)):
        if not name.endswith(".json"):
            continue
        label = os.path.join(dir_path, name)
        obj = json.load(open(label, encoding="utf-8"))
        if masked_only and not pixel_rings(obj):
            continue
        sample = str((obj.get("basic_annotation") or {}).get("fileName") or "")
        if not sample.endswith(".png"):
            sample = name.replace(".json", ".png")
        image = os.path.join(dir_path, sample)
        if os.path.isfile(image):
            pairs.append((image, label))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="EPB per-object QC CSV (one flat directory).")
    parser.add_argument("--dir", default=dir_epb_primary())
    parser.add_argument(
        "--physics-jsonl",
        default=os.path.join(RESULTS_DIR, "EPB_physics_informed.jsonl"),
        help="Merge Pass1+2: EPB_physics_informed.jsonl (preferred) or legacy EPB全目录模型.jsonl",
    )
    parser.add_argument("--all-labels", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--miss-mode", choices=("fast", "full", "skip"), default="fast")
    parser.add_argument("--out", default="")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument(
        "--postprocess",
        action="store_true",
        help="Run epb_fbbqy_postprocess (bundle/scorecard/ranking/logs)",
    )
    args = parser.parse_args()

    dir_id = os.path.basename(os.path.normpath(args.dir))
    out_path = args.out or os.path.join(RESULTS_DIR, f"{dir_id}_EPB对象质检.csv")
    agent_index = _load_physics_index(args.physics_jsonl)

    pairs = iter_pairs(args.dir, masked_only=not args.all_labels)
    if args.limit > 0:
        pairs = pairs[: args.limit]

    tasks = [
        (dir_id, img, lbl, agent_index.get(os.path.basename(img)), args.miss_mode)
        for img, lbl in pairs
    ]
    t0 = time.perf_counter()
    rows: list[dict[str, str]] = []
    stats: dict[str, int] = {"通过": 0, "不通过": 0, "待判定": 0, "不适用": 0}
    if args.jobs <= 1:
        for task in tasks:
            row = _qc_one_worker(task)
            stats[row["objectOverall"]] = stats.get(row["objectOverall"], 0) + 1
            rows.append(row)
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(_qc_one_worker, t) for t in tasks]
            for fut in as_completed(futures):
                row = fut.result()
                stats[row["objectOverall"]] = stats.get(row["objectOverall"], 0) + 1
                rows.append(row)
    rows.sort(key=lambda r: r.get("objectId") or "")

    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    summary = {
        "dirId": dir_id,
        "n_rows": len(rows),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "objectOverall_counts": stats,
        "physics_jsonl_hits": sum(1 for image, _ in pairs if os.path.basename(image) in agent_index),
        "miss_mode": args.miss_mode,
        "jobs": args.jobs,
        "out_csv": out_path,
        "spec": "路演结果/EPB九类缺陷质检对照与CSV说明.md",
    }
    json.dump(summary, open(out_path.replace(".csv", ".json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.postprocess:
        from epb_fbbqy_postprocess import main as postprocess_main

        postprocess_main()


if __name__ == "__main__":
    main()
