#!/usr/bin/env python3
"""Physics-informed Pass1+Pass2 VLM on flat EPB directory (json overlay, band_audit metrics)."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime

from roadshow_paths import RESULTS_DIR, dir_epb_primary, ensure_agent_path

ensure_agent_path()
os.environ.setdefault("MODEL_DISABLE_THINKING", "1")

from audits import pixel_rings  # noqa: E402
from physics_inspect import prepare_epb, run_two_pass  # noqa: E402
from roadshow_physics_export import append_evidence_csv, findings_from_physics_record  # noqa: E402
from physics_informed_runner import done_ids as _done_ids, run_parallel_jsonl  # noqa: E402
from vision import load_secrets  # noqa: E402

RULE = "physics-informed-v1"
DEFAULT_WORKERS = int(os.environ.get("PHYSICS_API_WORKERS", "4"))
OUT_JSONL = os.path.join(RESULTS_DIR, "EPB_physics_informed.jsonl")
OUT_SUMMARY = os.path.join(RESULTS_DIR, "EPB_physics_informed.json")
OUT_EVIDENCE = os.path.join(RESULTS_DIR, "EPB_physics_informed_证据表.csv")


def locate(
    dir_path: str,
    limit: int | None,
    ids: list[str] | None = None,
) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for name in sorted(os.listdir(dir_path)):
        if not name.endswith(".json"):
            continue
        label = os.path.join(dir_path, name)
        obj = json.load(open(label, encoding="utf-8"))
        if not pixel_rings(obj):
            continue
        sample = str((obj.get("basic_annotation") or {}).get("fileName") or "")
        if not sample.endswith(".png"):
            sample = name.replace(".json", ".png")
        image = os.path.join(dir_path, sample)
        if not os.path.isfile(image):
            continue
        if ids and os.path.basename(image) not in ids:
            continue
        found.append((image, label))
        if limit and len(found) >= limit:
            break
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=dir_epb_primary())
    parser.add_argument("--limit", type=int, default=0, help="Max images; 0 = all masked pairs.")
    parser.add_argument("--call", action="store_true", help="Call vision API for pass1+pass2.")
    parser.add_argument("--metrics-only", action="store_true", help="prepare_epb metrics only, no API.")
    parser.add_argument("--ids", nargs="*", help="Only these PNG basenames")
    parser.add_argument("--append", action="store_true", help="Skip objectIds already in jsonl.")
    parser.add_argument("--secrets", default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets.yaml"))
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Parallel API workers when --call (default PHYSICS_API_WORKERS or 4).",
    )
    args = parser.parse_args()

    pairs = locate(args.dir, args.limit if args.limit > 0 else None, args.ids)
    if args.append:
        done = _done_ids(OUT_JSONL)
        pairs = [(img, lbl) for img, lbl in pairs if os.path.basename(img) not in done]
    secrets = load_secrets(args.secrets) if args.call else None
    t0 = time.perf_counter()
    rows: list[dict] = []
    evidence_rows: list[dict] = []

    def _process(pair: tuple[str, str]) -> dict:
        image, label = pair
        oid = os.path.basename(image)
        item = prepare_epb(image, label)
        record: dict = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "checkId": "C13-physics",
            "ruleVersion": RULE,
            "dirId": os.path.basename(args.dir),
            "objectId": oid,
            "modality": "EPB",
            "label_path": label,
            "image_path": image,
            "metrics": item["metrics"],
        }
        try:
            if args.call:
                record.update(run_two_pass(item, secrets))
            else:
                record["note"] = "metrics_only"
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        return record

    def _progress(record: dict) -> None:
        n_reg = len((record.get("metrics") or {}).get("labeled_regions") or [])
        ev = record.get("evaluation") or {}
        print(
            record.get("objectId"),
            "regions",
            n_reg,
            "pass2",
            ev.get("pass2_verdict"),
            record.get("error") or "",
            flush=True,
        )

    if args.call and args.workers > 1:
        rows, usage_meta = run_parallel_jsonl(
            pairs,
            out_jsonl=OUT_JSONL,
            append=args.append,
            workers=args.workers,
            process_one=_process,
            on_progress=_progress,
        )
        total_usage = {k: usage_meta.get(k, 0) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
        if args.call:
            for r in rows:
                if not r.get("error"):
                    evidence_rows.extend(
                        findings_from_physics_record(r, label_path=r.get("label_path") or "")
                    )
    else:
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        mode = "a" if args.append else "w"
        with open(OUT_JSONL, mode, encoding="utf-8") as handle:
            for image, label in pairs:
                record = _process((image, label))
                if args.call and not record.get("error"):
                    for stage in ("pass1", "pass2"):
                        usage = (record.get(stage) or {}).get("usage") or {}
                        for key in total_usage:
                            total_usage[key] += int(usage.get(key) or 0)
                    evidence_rows.extend(
                        findings_from_physics_record(record, label_path=label)
                    )
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                rows.append(record)
                _progress(record)

    if args.call and evidence_rows:
        if args.append and os.path.isfile(OUT_JSONL):
            evidence_rows = []
            for line in open(OUT_JSONL, encoding="utf-8"):
                rec = json.loads(line)
                if rec.get("error"):
                    continue
                lp = rec.get("label_path") or ""
                evidence_rows.extend(findings_from_physics_record(rec, label_path=lp))
        open(OUT_EVIDENCE, "w").close()
        append_evidence_csv(evidence_rows, OUT_EVIDENCE)

    summary = {
        "dir": args.dir,
        "n": len(rows),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "called_api": bool(args.call),
        "usage_total": total_usage if args.call else None,
        "out_jsonl": OUT_JSONL,
        "out_evidence_csv": OUT_EVIDENCE if args.call else None,
    }
    if args.call and rows:
        summary["final_judgments"] = [
            {
                "objectId": r["objectId"],
                "pass2_verdict": (r.get("evaluation") or {}).get("pass2_verdict"),
                "n_regions": (r.get("evaluation") or {}).get("n_label_regions"),
                "n_unreasonable": (r.get("evaluation") or {}).get("n_unreasonable"),
                "error": r.get("error"),
            }
            for r in rows
        ]
    json.dump(summary, open(OUT_SUMMARY, "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
