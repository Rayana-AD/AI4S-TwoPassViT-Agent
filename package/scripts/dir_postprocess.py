#!/usr/bin/env python3
"""Directory-level aggregate for ANY dirId (not locked to roadshow deep-test IDs)."""

from __future__ import annotations

import argparse
import json
import os
import shutil

from roadshow_paths import RESULTS_DIR, ensure_agent_path

ensure_agent_path()


def run_dir_postprocess(
    object_csv: str,
    *,
    dir_id: str,
    modality: str,
    out_dir: str | None = None,
    data_dir: str | None = None,
) -> dict:
    out_dir = out_dir or RESULTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    modality = (modality or "").upper()
    if not os.path.isfile(object_csv):
        raise SystemExit(f"Missing object CSV: {object_csv}")

    if modality == "AIA":
        from aia_roadshow_aggregate import write_directory_bundle, write_severity_and_scorecard

        manifest = write_directory_bundle(
            object_csv,
            out_dir,
            dir_id=dir_id,
            data_dir=data_dir,
        )
    elif modality == "EPB":
        from epb_roadshow_aggregate import write_directory_bundle, write_severity_and_scorecard

        manifest = write_directory_bundle(object_csv, out_dir, dir_id=dir_id)
    elif modality == "ULF":
        from ulf_roadshow_aggregate import write_directory_bundle, write_severity_and_scorecard

        manifest = write_directory_bundle(object_csv, out_dir, dir_id=dir_id)
    else:
        raise SystemExit(f"Unsupported modality for postprocess: {modality}")

    extras = write_severity_and_scorecard(object_csv, out_dir, manifest)
    card_src = extras.get("scorecard_json")
    card_dst = os.path.join(out_dir, f"{dir_id}_评分卡.json")
    if card_src and os.path.isfile(card_src) and os.path.abspath(card_src) != os.path.abspath(card_dst):
        shutil.copy2(card_src, card_dst)
        extras["scorecard_json_generic"] = card_dst
    outputs = dict(manifest.get("outputs") or {})
    outputs.update(extras)
    manifest["outputs"] = outputs
    summary_path = os.path.join(out_dir, f"{dir_id}_pipeline_summary.json")
    json.dump(manifest, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return {"dirId": dir_id, "modality": modality, "outputs": outputs, "summary": summary_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generic dir postprocess (any dirId).")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--dir-id", required=True)
    parser.add_argument("--modality", required=True, choices=("AIA", "EPB", "ULF"))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--data-dir", default="")
    args = parser.parse_args()
    result = run_dir_postprocess(
        args.csv,
        dir_id=args.dir_id,
        modality=args.modality,
        out_dir=args.out_dir or RESULTS_DIR,
        data_dir=args.data_dir or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
