#!/usr/bin/env python3
"""Physics-informed two-pass inspection for AIA / EPB / ULF roadshow exemplars."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime

from roadshow_paths import RESULTS_DIR, dir_aia_primary, dir_epb_primary, dir_ulf_primary, ensure_agent_path

ensure_agent_path()
os.environ.setdefault("MODEL_DISABLE_THINKING", "1")

from physics_inspect import prepare_aia, prepare_epb, prepare_ulf, run_two_pass, physics_audit_label  # noqa: E402

RULE = "physics-informed-v1"
OUT_JSONL = os.path.join(RESULTS_DIR, "physics_informed_roadshow.jsonl")
OUT_SUMMARY = os.path.join(RESULTS_DIR, "physics_informed_roadshow.json")
INDEX = os.path.join(RESULTS_DIR, "代表样本索引.json")


def _resolve(modality: str, object_id: str) -> tuple[str, str | None]:
    if modality == "AIA":
        root = dir_aia_primary()
        image = os.path.join(root, "data", object_id)
        label = os.path.join(root, "label", object_id + ".json")
        return image, label if os.path.isfile(label) else None
    if modality == "EPB":
        root = dir_epb_primary()
        image = os.path.join(root, object_id)
        label = os.path.join(root, object_id.replace(".png", ".json"))
        if not os.path.isfile(label):
            label = os.path.join(root, object_id + ".json")
        return image, label if os.path.isfile(label) else None
    if modality == "ULF":
        root = dir_ulf_primary()
        csv_path = os.path.join(root, object_id)
        label = os.path.join(root, object_id + ".json")
        return csv_path, label if os.path.isfile(label) else None
    raise ValueError(modality)


def _prepare(modality: str, path: str, label: str | None) -> dict:
    if modality == "AIA":
        return prepare_aia(path, label)
    if modality == "EPB":
        return prepare_epb(path, label)
    return prepare_ulf(path, label)


def exemplars_from_index() -> list[tuple[str, str]]:
    data = json.load(open(INDEX, encoding="utf-8"))
    examples = data.get("examples") or {}
    pairs: list[tuple[str, str]] = []
    for object_id in examples.get("C13_contour") or []:
        if object_id.endswith(".png"):
            if os.path.isfile(os.path.join(dir_aia_primary(), "data", object_id)):
                pairs.append(("AIA", object_id))
            else:
                pairs.append(("EPB", object_id))
    for key in ("C09_false", "C09_miss"):
        for object_id in examples.get(key) or []:
            if object_id.endswith(".csv"):
                pairs.append(("ULF", object_id))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exemplars", action="store_true", help="Run C13/C09 items from 代表样本索引.json")
    parser.add_argument("--modality", choices=("AIA", "EPB", "ULF"))
    parser.add_argument("--ids", nargs="*", help="Object filenames")
    parser.add_argument("--call", action="store_true")
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()

    jobs: list[tuple[str, str]] = []
    if args.exemplars:
        jobs = exemplars_from_index()
    elif args.modality and args.ids:
        jobs = [(args.modality, oid) for oid in args.ids]
    else:
        jobs = [
            ("AIA", "Gb96QafrHF4ZNGdUa6Va.png"),
            ("EPB", "09u_N3cnKxe68a0ma7Bc.png"),
            ("ULF", "HjT4zNo2kbrkLPR2pq_s.csv"),
        ]

    mode = "a" if args.append else "w"
    t0 = time.perf_counter()
    rows = []
    with open(OUT_JSONL, mode, encoding="utf-8") as handle:
        for modality, object_id in jobs:
            path, label = _resolve(modality, object_id)
            if not os.path.isfile(path):
                print("skip missing", modality, object_id, flush=True)
                continue
            item = _prepare(modality, path, label)
            record = {
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "checkId": "C13-physics" if modality != "ULF" else "C09-physics",
                "ruleVersion": RULE,
                "modality": modality,
                "objectId": object_id,
                "metrics": item["metrics"],
                "physics_audit_offline": physics_audit_label(item),
            }
            if args.call:
                record.update(run_two_pass(item))
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            rows.append(record)
            print(modality, object_id, "ok", flush=True)

    summary = {
        "jobs": len(rows),
        "called_api": bool(args.call),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "out_jsonl": OUT_JSONL,
        "objects": [r["objectId"] for r in rows],
    }
    if args.call:
        summary["per_region_unreasonable"] = [
            {
                "objectId": r["objectId"],
                "n_unreasonable": (r.get("evaluation") or {}).get("n_unreasonable"),
                "pass2": (r.get("evaluation") or {}).get("pass2_verdict"),
            }
            for r in rows
        ]
    json.dump(summary, open(OUT_SUMMARY, "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
