#!/usr/bin/env python3
"""Rebuild 12 scorecards from 交付/12目录批处理 (object CSV + audit bundle only, no VLM/data re-run)."""

from __future__ import annotations

import csv
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AP = os.path.join(REPO, "Agent-Pipeline")
DEL = os.path.join(AP, "交付")
RES = os.path.join(REPO, "路演结果")
BATCH = os.path.join(DEL, "12目录批处理")
OUT = os.path.join(DEL, "04-提交评分卡")

sys.path.insert(0, os.path.join(AP, "package", "agent_modules"))
sys.path.insert(0, os.path.join(REPO, "agent_modules"))

TEMPLATES = {
    "AIA": os.path.join(RES, "评分卡_AIA_z4_aia_qc.json"),
    "EPB": os.path.join(RES, "评分卡_EPB_fbbqy_epb_qc.json"),
    "ULF": os.path.join(RES, "评分卡_ULF_xfnog_ulf_qc.json"),
}

SAMPLE_N = 50
SEED_ORDER = 0


def _mod(dir_id: str) -> str:
    if dir_id.startswith("AIA_"):
        return "AIA"
    if dir_id.startswith("EPB_"):
        return "EPB"
    return "ULF"


def _ok(val: str | None) -> bool:
    if val is None or val == "":
        return True
    if val in ("通过", "不适用", "待判定"):
        return val != "不通过"
    return val != "不通过"


def _dim_entry(passes: int, applicable: int, n_labels: int) -> dict:
    score = round(100.0 * passes / max(applicable, 1), 2)
    ratio = f"{round(100.0 * applicable / max(n_labels, 1), 1)}% ({applicable}/{n_labels})"
    status = "通过" if passes == applicable else ("不通过" if score < 80 else "待复核")
    return {
        "score": score,
        "passes": passes,
        "applicable": applicable,
        "check_coverage_ratio": ratio,
        "status": status,
        "source": "object_qc_sample50_v1",
    }


def dimension_scores_from_csv(rows: list[dict], n_labels: int, mod: str) -> dict:
    rows = sorted(rows, key=lambda r: (r.get("objectId") or "", r.get("dirId") or ""))
    sample = rows[:SAMPLE_N]
    app = len(sample)

    def pass_rows(cols: list[str]) -> int:
        n = 0
        for r in sample:
            if all(_ok(r.get(c)) for c in cols):
                n += 1
        return n

    if mod == "ULF":
        cols_quality = ["九4_类别非法", "九6_尺寸矛盾", "九5_时段超限"]
        cols_cov = ["九9_覆盖异常", "九5_时段超限"]
    elif mod == "EPB":
        cols_quality = ["九4_类别非法", "九6_尺寸矛盾", "九3a_像素越界"]
        cols_cov = ["九9_覆盖异常"]
    else:
        cols_quality = ["九4_类别非法", "九6_尺寸矛盾", "九3a_像素越界", "九3b_轮廓贴合"]
        cols_cov = ["九9_覆盖异常"]

    return {
        "完整性": _dim_entry(pass_rows(["九1_文件配对", "九2_孤儿标注"]), app, n_labels),
        "标注质量": _dim_entry(pass_rows(cols_quality), app, n_labels),
        "样本对应关系": _dim_entry(pass_rows(["九1_文件配对"]), app, n_labels),
        "覆盖与分布": _dim_entry(pass_rows(cols_cov), app, n_labels),
        "文档与来源追溯": _dim_entry(pass_rows(["九6_尺寸矛盾"]), app, n_labels),
        "使用条件": _dim_entry(
            sum(1 for r in sample if _ok(r.get("objectOverallScored") or r.get("objectOverall"))),
            app,
            n_labels,
        ),
    }


def rebuild_one(dir_id: str) -> dict:
    mod = _mod(dir_id)
    root = os.path.join(BATCH, dir_id)
    csv_path = os.path.join(root, "03-对象质检", f"{dir_id}_{mod}对象质检.csv")
    bundle_path = os.path.join(root, "04-目录审计与评分", f"{dir_id}_{mod}目录审计包.json")
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(csv_path)
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    audit: dict = {}
    if os.path.isfile(bundle_path):
        audit = json.load(open(bundle_path, encoding="utf-8")).get("audit") or {}

    sys.path.insert(0, os.path.join(AP, "package", "scripts"))
    from roadshow_paths import ensure_agent_path

    ensure_agent_path()

    if mod == "AIA":
        from aia_roadshow_aggregate import build_scorecard_from_audit, roadshow_result_row
    elif mod == "EPB":
        from epb_roadshow_aggregate import build_scorecard_from_audit, roadshow_result_row
    else:
        from ulf_roadshow_aggregate import roadshow_result_row

    if not audit:
        if mod == "EPB":
            from epb_roadshow_aggregate import compute_audit_metrics
        elif mod == "ULF":
            from ulf_roadshow_aggregate import compute_audit_metrics
        else:
            from aia_roadshow_aggregate import compute_audit_metrics
        audit = compute_audit_metrics(rows)

    n_labels = int(audit.get("n_labels_in_dir") or len(rows) or 1)
    result_csv = os.path.join(root, "04-目录审计与评分", f"{dir_id}_路演结果行.csv")
    if os.path.isfile(result_csv):
        with open(result_csv, encoding="utf-8") as f:
            rr = next(csv.DictReader(f))
    else:
        rr = roadshow_result_row(dir_id, audit)

    tmpl = TEMPLATES.get(mod)
    if mod == "ULF":
        base = json.load(open(tmpl, encoding="utf-8")) if tmpl and os.path.isfile(tmpl) else {}
        card = {
            **base,
            "scorecard_id": f"SC-{dir_id}-ulf-qc-v1",
            "dataset_name": dir_id,
            "tool_version": "ulf-qc-v1+physics-informed-v1",
            "ratio_metrics": audit.get("ratio_metrics"),
            "region_pass2_counts": audit.get("region_pass2_counts"),
            "pass2_object_coverage": audit.get("pass2_coverage_objects"),
        }
    else:
        card = build_scorecard_from_audit(audit, rr, dir_id=dir_id, template_path=tmpl)
    card["dataset_name"] = dir_id
    card["dirId"] = dir_id
    if rr.get("totalScore"):
        card["overall_quality_score"] = float(rr["totalScore"])
    card["dimension_scores"] = dimension_scores_from_csv(rows, n_labels, mod)
    card["audited_samples_count"] = min(SAMPLE_N, len(rows))
    card["dimension_scores_note"] = (
        "六维由冻结对象质检 CSV 前 50 条按列统计；目录总分 overall_quality_score 来自 postprocess 路演结果行。"
    )
    return card


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    dirs = sorted(d for d in os.listdir(BATCH) if d.startswith(("AIA_", "EPB_", "ULF_")))
    for dir_id in dirs:
        card = rebuild_one(dir_id)
        out_path = os.path.join(OUT, f"{dir_id}.json")
        json.dump(card, open(out_path, "w"), ensure_ascii=False, indent=2)
        dims = card.get("dimension_scores") or {}
        print(dir_id, "dims", len(dims), "total", card.get("overall_quality_score"))
        # mirror into batch audit folder (canonical name)
        sc_name = f"评分卡_{dir_id}.json"
        dest = os.path.join(BATCH, dir_id, "04-目录审计与评分", sc_name)
        json.dump(card, open(dest, "w"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
