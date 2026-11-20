#!/usr/bin/env python3
"""Archive orchestrator deep-test dirs (z4/fbbqy/xfnog) into 交付/12目录批处理/<dirId>/.

The nine-dir queue skips DONE_DEEP; this fills the same layout from 路演结果/ (not batch_runs/).
Scorecards: only copies files whose JSON dataset_name matches dirId (avoids polluting from 路演结果/).
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES = os.path.join(ROOT, "路演结果")
DELIVER_ROOT = os.path.join(ROOT, "Agent-Pipeline", "交付", "12目录批处理")
DELIVER_FLAT = os.path.join(ROOT, "Agent-Pipeline", "交付")

DONE_DEEP = (
    "AIA_AR_sample_z4h764sf2d",
    "EPB_seg_sample_fbbqy66u2d",
    "ULF_sample_xfnogkdey9",
)


def _modality(dir_id: str) -> str:
    if dir_id.startswith("AIA_"):
        return "AIA"
    if dir_id.startswith("EPB_"):
        return "EPB"
    return "ULF"


def _scorecards_for_dir(results_dir: str, dir_id: str) -> list[str]:
    out: list[str] = []
    for name in os.listdir(results_dir):
        if not (name.startswith("评分卡_") and name.endswith(".json")):
            continue
        path = os.path.join(results_dir, name)
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("dataset_name") == dir_id or data.get("dirId") == dir_id:
            out.append(name)
    # fallback aliases used in deep test
    aliases = {
        "AIA_AR_sample_z4h764sf2d": ["评分卡_AIA_z4_aia_qc.json"],
        "EPB_seg_sample_fbbqy66u2d": ["评分卡_EPB_fbbqy_epb_qc.json"],
        "ULF_sample_xfnogkdey9": ["评分卡_ULF_xfnog_ulf_qc.json"],
    }
    for alt in aliases.get(dir_id, []):
        if alt not in out and os.path.isfile(os.path.join(results_dir, alt)):
            out.append(alt)
    return sorted(set(out))


def archive_one(dir_id: str, results_dir: str | None = None) -> str:
    results_dir = results_dir or RES
    mod = _modality(dir_id)
    out_root = os.path.join(DELIVER_ROOT, dir_id)
    for sub in ("01-运行记录", "03-对象质检", "04-目录审计与评分", "05-physics与证据"):
        os.makedirs(os.path.join(out_root, sub), exist_ok=True)

    def cp(src: str, rel: str) -> None:
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(out_root, rel))

    cp(os.path.join(results_dir, f"{dir_id}_pipeline.log"), "01-运行记录/pipeline.log")
    cp(os.path.join(results_dir, f"{dir_id}_pipeline_summary.json"), "01-运行记录/pipeline_summary.json")
    cp(os.path.join(results_dir, f"{dir_id}_{mod}对象质检.csv"), f"03-对象质检/{dir_id}_{mod}对象质检.csv")
    cp(os.path.join(results_dir, f"{dir_id}_{mod}对象质检.json"), f"03-对象质检/{dir_id}_{mod}对象质检.json")
    cp(os.path.join(results_dir, f"{dir_id}_{mod}目录审计包.json"), f"04-目录审计与评分/{dir_id}_{mod}目录审计包.json")
    cp(os.path.join(results_dir, f"{dir_id}_{mod}审计指标.csv"), f"04-目录审计与评分/{dir_id}_{mod}审计指标.csv")
    for pat in (
        f"{dir_id}_{mod}证据汇总.csv",
        f"{dir_id}_ULF证据汇总.csv",
        f"{dir_id}_AIA证据汇总.csv",
        f"{dir_id}_EPB证据汇总.csv",
    ):
        src = os.path.join(results_dir, pat)
        if os.path.isfile(src):
            cp(src, f"04-目录审计与评分/{pat}")
    cp(os.path.join(results_dir, f"{dir_id}_缺陷严重程度排序.csv"), f"04-目录审计与评分/{dir_id}_缺陷严重程度排序.csv")
    cp(os.path.join(results_dir, f"{dir_id}_路演结果行.csv"), f"04-目录审计与评分/{dir_id}_路演结果行.csv")
    for sc in _scorecards_for_dir(results_dir, dir_id):
        cp(os.path.join(results_dir, sc), f"04-目录审计与评分/{sc}")

    phys_jsonl = os.path.join(results_dir, f"{mod}_physics_informed.jsonl")
    phys_ev = os.path.join(results_dir, f"{mod}_physics_informed_证据表.csv")
    cp(phys_jsonl, f"05-physics与证据/{mod}_physics_informed.jsonl")
    cp(phys_ev, f"05-physics与证据/{mod}_physics_informed_证据表.csv")
    if os.path.isfile(phys_jsonl):
        shutil.copy2(phys_jsonl, os.path.join(out_root, "05-physics与证据", f"{dir_id}_{mod}_physics_informed.jsonl"))
    if os.path.isfile(phys_ev):
        shutil.copy2(
            phys_ev,
            os.path.join(out_root, "05-physics与证据", f"{dir_id}_{mod}_physics_informed_证据表.csv"),
        )

    meta = {
        "dirId": dir_id,
        "modality": mod,
        "archived_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "results_dir": results_dir,
        "source": "orchestrator_deep_test",
        "note": "Not from roadshow_nine_dir_queue; same layout as queue archives.",
    }
    json.dump(meta, open(os.path.join(out_root, "RUN_META.json"), "w"), ensure_ascii=False, indent=2)
    _mirror_to_flat(dir_id, out_root, mod)
    return out_root


def _mirror_to_flat(dir_id: str, batch_root: str, mod: str) -> None:
    files = [
        (f"03-对象质检/{dir_id}_{mod}对象质检.csv", f"03-对象质检/{dir_id}_{mod}对象质检.csv"),
        (f"03-对象质检/{dir_id}_{mod}对象质检.json", f"03-对象质检/{dir_id}_{mod}对象质检.json"),
        (f"04-目录审计与评分/{dir_id}_{mod}目录审计包.json", f"04-目录审计与评分/{dir_id}_{mod}目录审计包.json"),
        (f"04-目录审计与评分/{dir_id}_{mod}审计指标.csv", f"04-目录审计与评分/{dir_id}_{mod}审计指标.csv"),
        (f"04-目录审计与评分/{dir_id}_路演结果行.csv", f"04-目录审计与评分/{dir_id}_路演结果行.csv"),
        (f"04-目录审计与评分/{dir_id}_缺陷严重程度排序.csv", f"04-目录审计与评分/{dir_id}_缺陷严重程度排序.csv"),
        (f"05-physics与证据/{dir_id}_{mod}_physics_informed.jsonl", f"05-physics与证据/{dir_id}_{mod}_physics_informed.jsonl"),
        (f"05-physics与证据/{dir_id}_{mod}_physics_informed_证据表.csv", f"05-physics与证据/{dir_id}_{mod}_physics_informed_证据表.csv"),
    ]
    for src_rel, dest_rel in files:
        src = os.path.join(batch_root, src_rel)
        if not os.path.isfile(src):
            continue
        dest = os.path.join(DELIVER_FLAT, dest_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
    audit = os.path.join(batch_root, "04-目录审计与评分")
    if os.path.isdir(audit):
        for name in os.listdir(audit):
            if name.startswith(dir_id) and "证据汇总" in name:
                shutil.copy2(os.path.join(audit, name), os.path.join(DELIVER_FLAT, "04-目录审计与评分", name))
            if name.startswith("评分卡_") and name.endswith(".json"):
                shutil.copy2(os.path.join(audit, name), os.path.join(DELIVER_FLAT, "04-目录审计与评分", name))
    log_tail = os.path.join(batch_root, "01-运行记录", "pipeline.log")
    if os.path.isfile(log_tail):
        dest_log = os.path.join(DELIVER_FLAT, "01-运行记录", f"{dir_id}_pipeline.log.tail")
        with open(log_tail, encoding="utf-8", errors="replace") as handle:
            tail = handle.readlines()[-200:]
        open(dest_log, "w", encoding="utf-8").writelines(tail)
    summary = os.path.join(batch_root, "01-运行记录", "pipeline_summary.json")
    if os.path.isfile(summary):
        shutil.copy2(summary, os.path.join(DELIVER_FLAT, "01-运行记录", f"{dir_id}_pipeline_summary.json"))


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dir-id", action="append", dest="dir_ids", help="default: fbbqy + xfnog if missing bundle")
    p.add_argument("--all-deep", action="store_true", help="archive all three DONE_DEEP dirs")
    args = p.parse_args()
    targets = args.dir_ids or []
    if args.all_deep:
        targets = list(DONE_DEEP)
    if not targets:
        for did in ("EPB_seg_sample_fbbqy66u2d", "ULF_sample_xfnogkdey9"):
            if not os.path.isdir(os.path.join(DELIVER_ROOT, did)):
                targets.append(did)
    for did in targets:
        path = archive_one(did)
        print("archived", did, "->", path)


if __name__ == "__main__":
    main()
