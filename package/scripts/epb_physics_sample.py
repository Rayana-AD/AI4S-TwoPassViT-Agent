#!/usr/bin/env python3
"""Sample EPB: two-pass VLM + full-res mask overlay for manual review."""

from __future__ import annotations

import argparse
import json
import os
import textwrap
import time
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from roadshow_paths import RESULTS_DIR, ensure_agent_path

ensure_agent_path()
os.environ.setdefault("MODEL_DISABLE_THINKING", "1")

from audits import pixel_rings  # noqa: E402
from physics_inspect import prepare_epb, run_two_pass  # noqa: E402
from physics_metrics import missed_label_audit_epb  # noqa: E402
from vision import load_secrets  # noqa: E402

DEFAULT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "路演数据",
    "EPB_seg_sample_fbbqy66u2d",
)
OVERLAY_COLORS = ((255, 48, 48), (48, 180, 255), (255, 200, 48), (180, 80, 255))
MISS_COLOR = (0, 255, 200)


def locate_flat(dir_path: str, limit: int, ids: list[str] | None) -> list[tuple[str, str]]:
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


def _vertices(points: list) -> list[tuple[float, float]]:
    pts = [
        (float(p[0]), float(p[1]))
        for p in points
        if isinstance(p, (list, tuple)) and len(p) >= 2 and not isinstance(p[0], (list, tuple))
    ]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        return pts[:-1]
    return pts


def render_full_review_png(
    image_path: str,
    label_path: str,
    *,
    miss_payload: dict | None = None,
    miss_ring: list | None = None,
) -> Image.Image:
    """Draw dataset masks + dark-band miss candidates on full-resolution image."""
    base = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    draw = ImageDraw.Draw(base)
    obj = json.load(open(label_path, encoding="utf-8"))
    rings = pixel_rings(obj)
    for idx, ring in enumerate(rings):
        color = OVERLAY_COLORS[idx % len(OVERLAY_COLORS)]
        verts = _vertices(ring.get("points") or [])
        if len(verts) < 3:
            continue
        outline_rgba = (*color, 255)
        closed = list(verts) + [verts[0]]
        for a, b in zip(closed, closed[1:]):
            odraw.line([a, b], fill=outline_rgba, width=4)
        cx = sum(v[0] for v in verts) / len(verts)
        cy = sum(v[1] for v in verts) / len(verts)
        tag = f"#{idx} {ring.get('label') or 'EPB'}"
        odraw.text((cx + 4, cy), tag, fill=outline_rgba)
    img = Image.alpha_composite(base, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    ring_by = {m.get("candidate_id"): m for m in (miss_ring or [])}
    for cand in (miss_payload or {}).get("candidates") or []:
        cid = cand.get("candidate_id")
        audit = (ring_by.get(cid) or {}).get("audit_miss_label") or (
            (cand.get("preview_physics") or {}).get("audit_miss_label")
        ) or "?"
        poly = _vertices(cand.get("synthetic_polygon_full") or [])
        if len(poly) >= 3:
            closed = list(poly) + [poly[0]]
            for a, b in zip(closed, closed[1:]):
                draw.line([a, b], fill=MISS_COLOR, width=3)
            tx, ty = poly[0]
        else:
            bb = cand.get("bbox_full") or {}
            if not bb:
                continue
            x0, y0, x1, y1 = bb["xmin"], bb["ymin"], bb["xmax"], bb["ymax"]
            draw.rectangle([x0, y0, x1, y1], outline=MISS_COLOR, width=2)
            tx, ty = x0, y0
        dep = (cand.get("preview_physics") or {}).get("depletion_sigma", "")
        draw.text((tx + 2, max(0, ty - 14)), f"miss#{cid} {audit} σ={dep}", fill=MISS_COLOR)
    return img


def _summary_text(record: dict) -> str:
    ev = record.get("evaluation") or {}
    p2 = record.get("pass2") or {}
    parsed = p2.get("parsed") or {}
    lines = [
        f"objectId: {record.get('objectId')}",
        f"pass2_verdict: {ev.get('pass2_verdict') or parsed.get('pass2_verdict')}",
        f"n_unreasonable: {ev.get('n_unreasonable')}",
        "",
        "per_region:",
    ]
    for row in ev.get("per_region") or []:
        lines.append(f"  #{row.get('region_id')}: {row.get('verdict')} — {row.get('reason', '')[:120]}")
    lines.append("")
    lines.append("miss_ring_audit:")
    for m in record.get("miss_ring_audit") or p2.get("miss_ring_audit") or []:
        lines.append(
            f"  cand#{m.get('candidate_id')}: {m.get('audit_miss_label')} "
            f"audit={m.get('audit_0.5_1d')} contrast={m.get('contrast_inside_vs_0.5_1d')}"
        )
    mv = (parsed.get("miss_verdicts") or [])
    if mv:
        lines.append("")
        lines.append("model miss_verdicts:")
        for m in mv:
            lines.append(f"  cand#{m.get('candidate_id')}: {m.get('verdict')} — {m.get('reason', '')[:100]}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=DEFAULT_DIR)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument(
        "--ids",
        nargs="*",
        default=[
            "0Pbz0Z5kBnTOgs_ruTTP.png",
            "09u_N3cnKxe68a0ma7Bc.png",
            "0F3cmX_Fcvg7rn_TvZ5A.png",
        ],
        help="PNG basenames to run (default: 3 samples incl. 0Pbz…)",
    )
    parser.add_argument("--secrets", default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets.yaml"))
    parser.add_argument("--out-dir", default=os.path.join(RESULTS_DIR, "EPB_fbbqy_sample_review"))
    parser.add_argument("--miss-mode", choices=("fast", "full"), default="fast")
    parser.add_argument("--no-api", action="store_true", help="Metrics + overlays only")
    args = parser.parse_args()

    secrets = load_secrets(args.secrets)
    pairs = locate_flat(args.dir, 0, args.ids)
    if not pairs:
        pairs = locate_flat(args.dir, args.limit, None)
    if not pairs:
        raise SystemExit("No masked png+json pairs found")

    os.makedirs(args.out_dir, exist_ok=True)
    out_jsonl = os.path.join(args.out_dir, "run.jsonl")
    t0 = time.perf_counter()
    records: list[dict] = []

    with open(out_jsonl, "w", encoding="utf-8") as handle:
        for image, label in pairs:
            oid = os.path.basename(image)
            print("processing", oid, flush=True)
            miss_payload, miss_ring = missed_label_audit_epb(image, label, mode=args.miss_mode)
            review_img = render_full_review_png(image, label, miss_payload=miss_payload, miss_ring=miss_ring)
            overlay_path = os.path.join(args.out_dir, f"test_{oid}")
            review_img.save(overlay_path, format="PNG")

            item = prepare_epb(image, label)
            record: dict = {
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "dirId": os.path.basename(args.dir),
                "objectId": oid,
                "modality": "EPB",
                "label_path": label,
                "image_path": image,
                "overlay_review_png": overlay_path,
                "miss_candidates_n": len(miss_payload.get("candidates") or []),
                "miss_heuristic_likely": sum(
                    1 for m in miss_ring if m.get("audit_miss_label") == "likely_miss"
                ),
            }
            if not args.no_api:
                record.update(run_two_pass(item, secrets))
                summary_path = os.path.join(args.out_dir, f"{oid}_model_summary.txt")
                open(summary_path, "w", encoding="utf-8").write(_summary_text(record))
                record["model_summary_txt"] = summary_path
            else:
                record["note"] = "no_api"
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            records.append(record)
            print(
                "  overlay", overlay_path,
                "miss_cand", record["miss_candidates_n"],
                "likely", record["miss_heuristic_likely"],
                flush=True,
            )

    summary = {
        "dir": args.dir,
        "n": len(records),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "called_api": not args.no_api,
        "out_dir": args.out_dir,
        "jsonl": out_jsonl,
        "objects": [
            {
                "objectId": r["objectId"],
                "overlay": r.get("overlay_review_png"),
                "pass2": ((r.get("evaluation") or {}).get("pass2_verdict")),
                "miss_likely": r.get("miss_heuristic_likely"),
            }
            for r in records
        ],
    }
    json.dump(summary, open(os.path.join(args.out_dir, "run_summary.json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
