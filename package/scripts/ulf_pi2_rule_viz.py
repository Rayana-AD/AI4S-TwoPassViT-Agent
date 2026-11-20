#!/usr/bin/env python3
"""ULF Pi2 physics panels + dataset time windows (visual-first).

Default: draw H / Pi2 bandpass / Hilbert envelope and **JSON 标注窗** only.
Descriptive scalars (P30 envelope, peak_over_quiet, per-window max envelope) are
exported for later **model/threshold calibration** — no fixed 3× / 1.5× verdicts.

Optional `--mode diagnostic` keeps exploratory burst-merge heuristics (explicitly provisional).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import ndimage
from scipy.signal import hilbert

from roadshow_paths import RESULTS_DIR, dir_ulf_primary, ensure_agent_path

ensure_agent_path()
from audits import window_spans  # noqa: E402
from physics_metrics import ulf_bandpass, ulf_pi2_metrics  # noqa: E402

CURVE = "#1f3b73"
EVENT_PI2 = "#E69F00"
WIN_COLORS = ("#E69F00", "#0072B2", "#009E73", "#CC79A7")

DEFAULT_DIR = dir_ulf_primary()
OUT_DIR = os.path.join(RESULTS_DIR, "ULF_pi2_rule_review")


def load_h(csv_path: str) -> np.ndarray:
    vals: list[float] = []
    with open(csv_path, encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        if "H" not in (reader.fieldnames or []):
            return np.array([], dtype=np.float64)
        for row in reader:
            try:
                vals.append(float(row["H"]))
            except (TypeError, ValueError):
                vals.append(float("nan"))
    return np.asarray(vals, dtype=np.float64)


def pi2_envelope(h: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    h = np.asarray(h, dtype=np.float64)
    metrics = ulf_pi2_metrics(h, fs=1.0)
    filtered = ulf_bandpass(h - np.nanmedian(h), fs=1.0)
    envelope = np.abs(hilbert(filtered))
    return filtered, envelope, metrics


def describe_windows(obj: dict, n: int, envelope: np.ndarray) -> list[dict[str, Any]]:
    """Annotation windows only — no pass/fail."""
    spans = window_spans(obj, n)
    uea = obj.get("ulf_event_annotation") or {}
    events = uea.get("matched_events") or []
    out: list[dict[str, Any]] = []
    for rid, span in enumerate(spans):
        if span.get("i0") is None:
            out.append({
                "region_id": rid,
                "parse_ok": False,
                "note": span.get("note") or "time parse failed",
            })
            continue
        i0, i1 = int(span["i0"]), int(span["i1"])
        ev = events[rid] if rid < len(events) else {}
        seg = envelope[i0:i1] if envelope.size else np.array([])
        out.append({
            "region_id": rid,
            "parse_ok": True,
            "kind": span.get("kind") or ev.get("kind"),
            "start_dt": ev.get("start_dt"),
            "end_dt": ev.get("end_dt"),
            "i0": i0,
            "i1": i1,
            "duration_s": i1 - i0,
            "window_max_envelope": round(float(np.max(seg)), 6) if seg.size else None,
            "window_mean_envelope": round(float(np.mean(seg)), 6) if seg.size else None,
        })
    return out


def build_record(csv_path: str, json_path: str, *, mode: str, **diag_kw) -> dict[str, Any]:
    obj = json.load(open(json_path, encoding="utf-8"))
    h = load_h(csv_path)
    oid = os.path.basename(csv_path)
    uea = obj.get("ulf_event_annotation") or {}
    base: dict[str, Any] = {
        "objectId": oid,
        "n_samples": int(h.size),
        "rows_ok": h.size == 3600,
        "has_events": bool(uea.get("has_events")),
        "event_count_json": uea.get("event_count"),
        "n_matched_events": len(uea.get("matched_events") or []),
        "mode": mode,
    }
    if h.size < 100:
        base["skip"] = True
        return base

    filtered, envelope, metrics = pi2_envelope(h)
    windows = describe_windows(obj, h.size, envelope)
    base["pi2_metrics_descriptive"] = {
        "band_label": metrics.get("band_label"),
        "envelope_quiet_p30_full_hour": metrics.get("envelope_quiet"),
        "envelope_peak_full_hour": metrics.get("envelope_peak"),
        "peak_over_quiet_full_hour": metrics.get("peak_over_quiet"),
        "note": "比值仅供标定；阈值应由模型/专家定，非计分 verdict",
    }
    base["windows"] = windows
    base["_h"] = h
    base["filtered"] = filtered
    base["envelope"] = envelope
    base["spans"] = window_spans(obj, h.size)

    if mode == "diagnostic":
        base["provisional_diagnostic"] = _provisional_diagnostic(
            h.size, envelope, metrics, base["spans"], **diag_kw
        )
    return base


def _provisional_diagnostic(
    n: int,
    envelope: np.ndarray,
    metrics: dict,
    spans: list[dict],
    *,
    peak_ratio: float,
    in_window_ratio: float,
    miss_overlap_max: float,
    min_duration_s: int,
    max_duration_s: int,
) -> dict[str, Any]:
    """Exploratory only — parameters not validated."""
    quiet = float(metrics["envelope_quiet"])
    lmask = np.zeros(n, dtype=bool)
    for span in spans:
        if span.get("i0") is None:
            continue
        lmask[int(span["i0"]) : int(span["i1"])] = True
    thr = quiet * peak_ratio
    active = envelope > thr
    active = ndimage.binary_closing(active, structure=np.ones(31))
    labeled, n_feat = ndimage.label(active)
    bursts = []
    for lab in range(1, n_feat + 1):
        idx = np.where(labeled == lab)[0]
        if idx.size < min_duration_s or idx.size > max_duration_s:
            continue
        i0, i1 = int(idx[0]), int(idx[-1]) + 1
        bursts.append({"i0": i0, "i1": i1, "peak": float(np.max(envelope[i0:i1]))})
    return {
        "warning": "provisional heuristic; do not use as roadshow verdict",
        "params": {
            "peak_ratio": peak_ratio,
            "in_window_ratio": in_window_ratio,
            "miss_overlap_max": miss_overlap_max,
            "min_duration_s": min_duration_s,
            "max_duration_s": max_duration_s,
        },
        "bursts_above_peak_ratio": bursts[:10],
    }


def plot_windows(record: dict, out_png: str, *, show_p30: bool = True, dpi: int = 150) -> None:
    h = record.get("_h")
    if h is None or record.get("skip"):
        return
    n = h.size
    t_min = np.arange(n) / 60.0
    filtered = record["filtered"]
    envelope = record["envelope"]
    desc = record.get("pi2_metrics_descriptive") or {}
    quiet = desc.get("envelope_quiet_p30_full_hour")
    windows = record.get("windows") or []

    fig, axes = plt.subplots(4, 1, figsize=(9.2, 8.0), sharex=True)
    title = (
        f"{record['objectId']} | has_events={record.get('has_events')} "
        f"n_win={len([w for w in windows if w.get('parse_ok')])} | "
        f"peak/quiet(hour)={desc.get('peak_over_quiet_full_hour')}"
    )
    axes[0].set_title(title, fontsize=9)

    for ax, y, ylab in zip(
        axes[:3],
        (h, filtered, envelope),
        ("H (nT)", "H Pi2 band (6.7–25 mHz)", "Hilbert envelope"),
    ):
        ax.plot(t_min, y, lw=0.35, color=CURVE)
        for w in windows:
            if not w.get("parse_ok"):
                continue
            c = WIN_COLORS[w["region_id"] % len(WIN_COLORS)]
            ax.axvspan(w["i0"] / 60, w["i1"] / 60, color=c, alpha=0.28, lw=0)
            ax.axvline(w["i0"] / 60, color=c, lw=0.6, alpha=0.7)
            ax.axvline(w["i1"] / 60, color=c, lw=0.6, alpha=0.7)
        ax.set_ylabel(ylab, fontsize=8)
        ax.grid(alpha=0.25, lw=0.4)

    if show_p30 and quiet is not None:
        axes[2].axhline(
            float(quiet),
            color="gray",
            ls="--",
            lw=0.8,
            label=f"full-hour env P30={quiet:.4g} (ref only)",
        )
        axes[2].legend(fontsize=7, loc="upper right")

    axm = axes[3]
    mask = np.zeros(n)
    for w in windows:
        if w.get("parse_ok"):
            mask[w["i0"] : w["i1"]] = 1.0
    axm.fill_between(t_min, mask, step="mid", alpha=0.55, color=EVENT_PI2)
    axm.set_ylim(-0.1, 1.2)
    axm.set_ylabel("label mask")
    axm.set_xlabel("minutes from hour start (3600 s @ 1 Hz index)")
    axm.grid(alpha=0.25, lw=0.4)

    # annotate windows under title area via text box
    lines = []
    for w in windows:
        if not w.get("parse_ok"):
            lines.append(f"win{w.get('region_id')}: parse fail")
            continue
        lines.append(
            f"win{w['region_id']} {w.get('kind')} {w.get('start_dt')}–{w.get('end_dt')} "
            f"({w['duration_s']}s) max_env={w.get('window_max_envelope')}"
        )
    if lines:
        fig.text(0.01, 0.01, "\n".join(lines[:6]), fontsize=6, family="monospace", va="bottom")

    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(out_png, dpi=dpi)
    plt.close(fig)


def pick_structural_examples(records: list[dict], limit: int = 8) -> list[dict]:
    """Pick varied **annotation shapes**, not rule tags."""
    buckets: dict[str, list[dict]] = {
        "no_events": [],
        "events_empty_list": [],
        "single_long_win": [],
        "single_short_win": [],
        "multi_win": [],
        "parse_fail": [],
    }
    for r in records:
        if r.get("skip") or not r.get("rows_ok"):
            continue
        wins = [w for w in (r.get("windows") or []) if w.get("parse_ok")]
        if not r.get("has_events") and not wins:
            buckets["no_events"].append(r)
        elif r.get("has_events") and not wins:
            buckets["events_empty_list"].append(r)
        elif any(not w.get("parse_ok") for w in (r.get("windows") or [])):
            buckets["parse_fail"].append(r)
        elif len(wins) >= 2:
            buckets["multi_win"].append(r)
        elif wins and wins[0]["duration_s"] >= 120:
            buckets["single_long_win"].append(r)
        elif wins and wins[0]["duration_s"] < 120:
            buckets["single_short_win"].append(r)
    chosen: list[dict] = []
    seen: set[str] = set()
    for key in buckets:
        for r in buckets[key]:
            if r["objectId"] in seen:
                continue
            chosen.append(r)
            seen.add(r["objectId"])
            if len(chosen) >= limit:
                return chosen
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=DEFAULT_DIR)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--scan-limit", type=int, default=800)
    parser.add_argument("--ids", nargs="*", help="Only these CSV basenames")
    parser.add_argument(
        "--mode",
        choices=("windows", "diagnostic"),
        default="windows",
        help="windows=只画标注窗+描述量；diagnostic=附加 provisional burst 启发（非 verdict）",
    )
    parser.add_argument("--peak-ratio", type=float, default=3.0, help="diagnostic only")
    parser.add_argument("--in-window-ratio", type=float, default=1.5, help="diagnostic only")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    names = sorted(n for n in os.listdir(args.dir) if n.endswith(".csv"))
    if args.ids:
        names = [n for n in names if n in args.ids]
    else:
        names = names[: args.scan_limit]

    records: list[dict] = []
    for name in names:
        csv_path = os.path.join(args.dir, name)
        json_path = csv_path + ".json"
        if not os.path.isfile(json_path):
            continue
        records.append(
            build_record(
                csv_path,
                json_path,
                mode=args.mode,
                peak_ratio=args.peak_ratio,
                in_window_ratio=args.in_window_ratio,
                miss_overlap_max=0.15,
                min_duration_s=60,
                max_duration_s=900,
            )
        )

    showcase = records if args.ids else pick_structural_examples(records)
    manifest: list[dict] = []
    for r in showcase:
        png = os.path.join(args.out_dir, r["objectId"].replace(".csv", "_pi2_windows.png"))
        plot_windows(r, png)
        slim = {
            k: v
            for k, v in r.items()
            if k not in ("_h", "filtered", "envelope", "spans")
        }
        slim["figure"] = png
        manifest.append(slim)
        print(r["objectId"], "->", os.path.basename(png))

    summary = {
        "dir": args.dir,
        "mode": args.mode,
        "scanned": len(records),
        "showcase_n": len(manifest),
        "policy": "阈值未固定；图仅展示 JSON 时间窗与 Pi2 包络；计分阈值留待模型/标定",
        "cases": manifest,
    }
    json_path = os.path.join(args.out_dir, "pi2_window_cases.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    md_path = os.path.join(args.out_dir, "pi2_window_cases.md")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("# ULF Pi2 — 标注时间窗可视化（无固定阈值 verdict）\n\n")
        handle.write(
            "全小时：H 去中位数 → Pi2 带通 → Hilbert 包络。"
            "图中 **竖线/色带 = `matched_events` 映射窗**；灰色虚线仅为 **P30 参考**，不是 3× 计分线。\n\n"
        )
        for c in manifest:
            handle.write(f"## `{c['objectId']}`\n\n")
            handle.write(f"- figure: `{os.path.basename(c.get('figure', ''))}`\n")
            handle.write(f"- descriptive: `{c.get('pi2_metrics_descriptive')}`\n")
            for w in c.get("windows") or []:
                handle.write(f"- window: `{w}`\n")
            if c.get("provisional_diagnostic"):
                handle.write(f"- provisional (ignore for scoring): `{c['provisional_diagnostic']}`\n")
            handle.write("\n")

    print(json.dumps({"out": args.out_dir, "json": json_path, "n": len(manifest)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
