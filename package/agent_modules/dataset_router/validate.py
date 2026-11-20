#!/usr/bin/env python3
"""Validate dataset router on a folder of OPC-like dataset dirs."""

from __future__ import annotations

import argparse
import json
import os
import sys

# package/agent_modules on path when run as -m dataset_router.validate from agent_modules
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

from dataset_router.router_agent import route_dataset_directory  # noqa: E402


def expected_pipeline(dir_name: str) -> str:
    if dir_name.startswith("ULF_"):
        return "ULF"
    if dir_name.startswith("EPB_"):
        return "EPB"
    if dir_name.startswith(("AIA_", "HMI_", "CME_", "DMSP_")):
        return "AIA"
    return "UNKNOWN"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate dataset router against dir-name ground truth.")
    parser.add_argument("--root", required=True, help="Parent with many dataset dirs (e.g. colab_subset/publish)")
    parser.add_argument("--limit", type=int, default=0, help="Max dirs (0=all)")
    parser.add_argument("--json-sample", type=int, default=20)
    parser.add_argument("--image-sample", type=int, default=3)
    parser.add_argument("--out", default="", help="Write JSON report path")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    names = sorted(n for n in os.listdir(root) if not n.startswith("."))
    dirs = [os.path.join(root, n) for n in names if os.path.isdir(os.path.join(root, n))]
    if args.limit > 0:
        dirs = dirs[: args.limit]

    rows = []
    ok_router = ok_legacy = 0
    for path in dirs:
        name = os.path.basename(path)
        exp = expected_pipeline(name)
        if exp == "UNKNOWN":
            continue
        dec = route_dataset_directory(
            path,
            json_sample=args.json_sample,
            image_sample=args.image_sample,
            compare_legacy=True,
        )
        got = dec.get("pipeline") or "UNKNOWN"
        legacy = (dec.get("legacy_detect") or {}).get("modality") or "UNKNOWN"
        match_r = got == exp
        match_l = legacy == exp
        ok_router += int(match_r)
        ok_legacy += int(match_l)
        rows.append(
            {
                "dirId": name,
                "expected": exp,
                "router": got,
                "legacy": legacy,
                "confidence": dec.get("confidence"),
                "archetype_id": dec.get("archetype_id"),
                "layout": dec.get("layout"),
                "match_router": match_r,
                "match_legacy": match_l,
                "rationale": dec.get("rationale"),
            }
        )

    n = len(rows)
    report = {
        "root": root,
        "n_dirs": n,
        "router_accuracy": round(ok_router / n, 3) if n else 0.0,
        "legacy_accuracy": round(ok_legacy / n, 3) if n else 0.0,
        "rows": rows,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    if n and ok_router < n:
        raise SystemExit(1)


if __name__ == "__main__":
    main()