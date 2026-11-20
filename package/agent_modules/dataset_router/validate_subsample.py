#!/usr/bin/env python3
"""Stress-test router/legacy with tiny JSON samples (simulates 2-object subsets)."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

from dataset_router.profiler import annotation_stats_from_objects, profile_from_parts, probe_directory
from dataset_router.profiler import _layout_topology  # noqa: E402
from dataset_router.router_agent import route_dataset_profile
from modality_detect import detect_modality_from_directory, infer_modality_from_profile


def expected_pipeline(dir_name: str) -> str:
    if dir_name.startswith("ULF_"):
        return "ULF"
    if dir_name.startswith("EPB_"):
        return "EPB"
    if dir_name.startswith(("AIA_", "HMI_", "CME_", "DMSP_")):
        return "AIA"
    return "UNKNOWN"


def _collect_json_objects(dir_path: str, limit: int) -> list[dict]:
    import json as js

    objects = []
    label = os.path.join(dir_path, "label")
    roots = [label] if os.path.isdir(label) else [dir_path]
    names: list[str] = []
    for root in roots:
        try:
            names.extend(os.path.join(root, n) for n in sorted(os.listdir(root)) if n.endswith(".json"))
        except OSError:
            pass
    names.sort(key=lambda p: (p.endswith(".csv.json"), p))
    rng = random.Random(0)
    if len(names) > limit:
        names = sorted(rng.sample(names, limit))
    for path in names:
        try:
            objects.append(js.load(open(path, encoding="utf-8")))
        except (OSError, js.JSONDecodeError):
            pass
    return objects


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--json-cap", type=int, default=2)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    rows = []
    ok_r = ok_l = 0
    for name in sorted(os.listdir(args.root)):
        path = os.path.join(args.root, name)
        if not os.path.isdir(path):
            continue
        exp = expected_pipeline(name)
        if exp == "UNKNOWN":
            continue
        layout, topo = _layout_topology(path)
        ann = annotation_stats_from_objects(_collect_json_objects(path, args.json_cap))
        visual = probe_directory(path, max_images=min(2, args.json_cap))
        profile = profile_from_parts(
            dir_id=name,
            dir_path=path,
            layout=layout,
            topo=topo,
            annotation=ann,
            visual=visual,
        )
        dec = route_dataset_profile(profile, compare_legacy_path=path)
        legacy_dir = detect_modality_from_directory(path, sample=args.json_cap)
        legacy_prof = infer_modality_from_profile(profile)
        got = dec.get("pipeline")
        match_r = got == exp
        match_l = legacy_dir.get("modality") == exp and legacy_prof.get("modality") == exp
        ok_r += int(match_r)
        ok_l += int(match_l)
        rows.append(
            {
                "dirId": name,
                "expected": exp,
                "router": got,
                "legacy_dir": legacy_dir.get("modality"),
                "legacy_profile": legacy_prof.get("modality"),
                "json_cap": args.json_cap,
                "match_router": match_r,
                "match_legacy": match_l,
            }
        )
    n = len(rows)
    report = {
        "root": args.root,
        "json_cap": args.json_cap,
        "router_accuracy": round(ok_r / n, 3) if n else 0,
        "legacy_accuracy": round(ok_l / n, 3) if n else 0,
        "rows": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, indent=2))
    if n and (ok_r < n or ok_l < n):
        raise SystemExit(1)


if __name__ == "__main__":
    main()