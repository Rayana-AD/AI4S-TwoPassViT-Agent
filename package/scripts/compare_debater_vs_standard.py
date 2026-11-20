#!/usr/bin/env python3
"""Side-by-side: 星海舰队/Agent-Pipeline prepare_* vs scientific_debater auxiliary_metrics."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(PIPELINE_ROOT, "package")
REPO_ROOT = os.environ.get("ROADSHOW_REPO_ROOT", os.path.dirname(PIPELINE_ROOT))
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))

from dataset_router.visual_probe import collect_png_paths  # noqa: E402
from scientific_debater.auxiliary_bridge import (  # noqa: E402
    _find_label,
    attach_auxiliary_to_item,
    verify_pass1_hook,
)
from scientific_debater.script_sandbox import run_auxiliary_metrics  # noqa: E402
from physics_inspect import prepare_aia, prepare_epb, prepare_ulf  # noqa: E402


def _standard_item(modality: str, data_path: str, label_path: str | None) -> dict:
    if modality == "AIA":
        if label_path and os.path.isfile(label_path):
            return prepare_aia(data_path, label_path, overlay=True)
        from physics_metrics import aia_metrics_for_image

        return {"metrics": aia_metrics_for_image(data_path, label_path), "modality": "AIA"}
    if modality == "EPB":
        if label_path and os.path.isfile(label_path):
            return prepare_epb(data_path, label_path, overlay=True)
        from physics_metrics import epb_metrics_for_image

        return {"metrics": epb_metrics_for_image(data_path, label_path), "modality": "EPB"}
    if modality == "ULF":
        return prepare_ulf(data_path, label_path)
    raise ValueError(modality)


def _summarize_metrics(metrics: dict, *, max_keys: int = 20) -> dict:
    if not metrics:
        return {}
    skip = {"overlay_path", "rings", "candidates", "envelope_plot"}
    out: dict = {}
    for k, v in metrics.items():
        if k in skip:
            out[k] = f"<{type(v).__name__}>"
            continue
        if isinstance(v, dict):
            out[k] = {sk: sv for sk, sv in list(v.items())[:max_keys]}
        elif isinstance(v, (list, tuple)) and len(v) > 5:
            out[k] = f"list[{len(v)}]"
        else:
            out[k] = v
        if len(out) >= max_keys:
            break
    return out


def _ulf_csv_paths(dir_path: str, limit: int) -> list[str]:
    csvs = []
    for name in sorted(os.listdir(dir_path)):
        if name.endswith(".csv") and not name.endswith(".csv.json"):
            csvs.append(os.path.join(dir_path, name))
        elif name.endswith(".csv.json"):
            pass
    # paired: prefer bare .csv if exists
    seen = set()
    out = []
    for p in csvs:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= limit:
            break
    if not out:
        for name in sorted(os.listdir(dir_path)):
            if name.endswith(".csv.json"):
                base = name[:-5]
                out.append(os.path.join(dir_path, base))
                if len(out) >= limit:
                    break
    return out


def compare_one(
    *,
    dir_path: str,
    modality: str,
    script_path: str,
    limit: int = 2,
) -> dict:
    dir_path = os.path.abspath(dir_path)
    rows = []
    if modality == "ULF":
        paths = _ulf_csv_paths(dir_path, limit)
        for csv_path in paths:
            lab = _find_label(dir_path, csv_path) or (csv_path + ".json" if os.path.isfile(csv_path + ".json") else None)
            std = _standard_item("ULF", csv_path, lab)
            label_obj = None
            if lab and os.path.isfile(lab):
                label_obj = json.load(open(lab, encoding="utf-8"))
            code = open(script_path, encoding="utf-8").read()
            aux_raw = run_auxiliary_metrics(code, csv_path, label_obj)
            item = {"image_path": csv_path, "label_path": lab, "metrics": {}}
            if not aux_raw.get("error"):
                item = attach_auxiliary_to_item(item, script_path)
            rows.append(
                {
                    "object": os.path.basename(csv_path),
                    "standard_metrics_keys": sorted((std.get("metrics") or {}).keys()),
                    "standard_snapshot": _summarize_metrics(std.get("metrics") or {}),
                    "debater_raw_error": aux_raw.get("error"),
                    "debater_snapshot": _summarize_metrics(aux_raw if not aux_raw.get("error") else aux_raw),
                    "debater_hook": (item.get("metrics") or {}).get("debater_auxiliary"),
                }
            )
        hook = verify_pass1_hook(dir_path=dir_path, script_path=script_path, modality=modality, limit=1)
        return {"modality": modality, "dir": dir_path, "samples": rows, "pass1_hook": hook}

    pngs = collect_png_paths(dir_path, limit=limit)
    for png in pngs:
        lab = _find_label(dir_path, png)
        std = _standard_item(modality, png, lab)
        code = open(script_path, encoding="utf-8").read()
        label_obj = None
        if lab and os.path.isfile(lab):
            label_obj = json.load(open(lab, encoding="utf-8"))
        aux_raw = run_auxiliary_metrics(code, png, label_obj)
        item_hook = attach_auxiliary_to_item(
            {
                "id": os.path.basename(png),
                "modality": modality,
                "image_path": png,
                "label_path": lab,
                "metrics": dict(std.get("metrics") or {}),
            },
            script_path,
        )
        rows.append(
            {
                "object": os.path.basename(png),
                "has_label": bool(lab),
                "standard_metrics_keys": sorted((std.get("metrics") or {}).keys()),
                "standard_snapshot": _summarize_metrics(std.get("metrics") or {}),
                "debater_raw_error": aux_raw.get("error"),
                "debater_snapshot": _summarize_metrics(aux_raw if not aux_raw.get("error") else aux_raw),
                "merged_has_debater": "debater_auxiliary" in (item_hook.get("metrics") or {}),
                "debater_coverage": ((item_hook.get("metrics") or {}).get("debater_auxiliary") or {}).get(
                    "pipeline_coverage"
                ),
            }
        )
    hook = verify_pass1_hook(dir_path=dir_path, script_path=script_path, modality=modality, limit=limit)
    return {"modality": modality, "dir": dir_path, "samples": rows, "pass1_hook": hook}


def run_pipeline_smoke(dir_path: str, *, with_aux: str | None) -> dict:
    env = os.environ.copy()
    env.pop("DEBATER_AUXILIARY_SCRIPT", None)
    if with_aux:
        env["DEBATER_AUXILIARY_SCRIPT"] = with_aux
    cmd = [sys.executable, os.path.join(PIPELINE_ROOT, "agent", "run_pipeline.py"), "--dir", dir_path, "--limit", "2"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=os.path.join(PKG, "scripts"),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return {
            "ok": proc.returncode == 0,
            "with_auxiliary": bool(with_aux),
            "tail_stdout": (proc.stdout or "")[-2000:],
            "tail_stderr": (proc.stderr or "")[-1500:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Dataset directory under colab_subset/publish")
    parser.add_argument("--modality", choices=("AIA", "EPB", "ULF"), required=True)
    parser.add_argument("--script", help="auxiliary_metrics.py path (default: debater workspace)")
    parser.add_argument("--workspace", help="experiments/scientific_debater/<dir_id>")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--pipeline", action="store_true", help="Also run run_pipeline --limit 2 twice")
    args = parser.parse_args()

    dir_path = args.dir
    if not os.path.isabs(dir_path):
        dir_path = os.path.join(REPO_ROOT, "colab_subset", "publish", os.path.basename(dir_path))

    script = args.script
    if not script and args.workspace:
        script = os.path.join(args.workspace, "auxiliary_metrics.py")
    if not script:
        dir_id = os.path.basename(dir_path.rstrip("/"))
        script = os.path.join(
            PIPELINE_ROOT, "experiments", "scientific_debater", dir_id, "auxiliary_metrics.py"
        )
    if not os.path.isfile(script):
        raise SystemExit(f"Missing script: {script}")

    report = compare_one(dir_path=dir_path, modality=args.modality, script_path=script, limit=args.limit)
    if args.pipeline:
        report["pipeline_baseline"] = run_pipeline_smoke(dir_path, with_aux=None)
        report["pipeline_with_debater"] = run_pipeline_smoke(dir_path, with_aux=script)

    out_dir = os.path.dirname(script)
    out_path = os.path.join(out_dir, "COMPARE_STANDARD.json")
    json.dump(report, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"written": out_path, "modality": args.modality, "samples": len(report["samples"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()