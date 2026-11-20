#!/usr/bin/env python3
"""Validate router on OPC roadshow zip (stream tar members, no full extract)."""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

from dataset_router.archive_stream import list_opc_tar_members, stream_tar_member  # noqa: E402
from dataset_router.router_agent import route_dataset_profile  # noqa: E402


def expected_pipeline(dir_name: str) -> str:
    if dir_name.startswith("ULF_"):
        return "ULF"
    if dir_name.startswith("EPB_"):
        return "EPB"
    if dir_name.startswith(("AIA_", "HMI_", "CME_", "DMSP_")):
        return "AIA"
    return "UNKNOWN"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", default="/Volumes/KESU/OPC_路演测试数据.zip")
    parser.add_argument("--only", nargs="*", help="dirId list; default all tars in zip")
    parser.add_argument("--json-sample", type=int, default=12)
    parser.add_argument("--image-sample", type=int, default=2)
    parser.add_argument("--skip-gb", type=float, default=2.0, help="Skip tar compressed size above this GB")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    members = list_opc_tar_members(args.zip)
    rows = []
    ok_r = ok_l = 0
    for row in members:
        dir_id = row["dir_id"]
        if args.only and dir_id not in args.only:
            continue
        if row["compress_size"] > args.skip_gb * 1e9:
            rows.append(
                {
                    "dirId": dir_id,
                    "skipped": True,
                    "reason": f"tar>{args.skip_gb}GB compressed; use --only or raise --skip-gb",
                    "compress_gb": round(row["compress_size"] / 1e9, 2),
                }
            )
            continue
        print(f"streaming {dir_id} …", flush=True)
        profile = stream_tar_member(
            args.zip,
            row["zip_member"],
            dir_id=dir_id,
            json_sample=args.json_sample,
            image_sample=args.image_sample,
        )
        dec = route_dataset_profile(profile)
        exp = expected_pipeline(dir_id)
        got = dec.get("pipeline")
        legacy = (dec.get("legacy_detect") or {}).get("modality")
        match_r = got == exp
        match_l = legacy == exp
        ok_r += int(match_r)
        ok_l += int(match_l)
        rows.append(
            {
                "dirId": dir_id,
                "expected": exp,
                "router": got,
                "legacy": legacy,
                "confidence": dec.get("confidence"),
                "layout": dec.get("layout"),
                "tar_members": profile.get("topology", {}).get("tar_member_count"),
                "match_router": match_r,
                "match_legacy": match_l,
            }
        )

    tested = [r for r in rows if not r.get("skipped")]
    n = len(tested)
    report = {
        "zip": args.zip,
        "n_tested": n,
        "n_skipped": len(rows) - n,
        "router_accuracy": round(ok_r / n, 3) if n else 0.0,
        "legacy_accuracy": round(ok_l / n, 3) if n else 0.0,
        "rows": rows,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    if n and ok_r < n:
        raise SystemExit(1)


if __name__ == "__main__":
    main()