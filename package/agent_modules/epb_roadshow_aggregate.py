"""Aggregate per-object EPB QC CSV → 路演结果行 + 证据 + 审计指标 + 排序/评分卡."""

from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from aia_roadshow_aggregate import (
    NINE_TO_CHECK,
    append_audit_log,
    audit_pass2_pending,
    count_region_verdict,
    estimate_runtime_tokens,
    patch_roadshow_results_csv,
)

RULE_VERSIONS = {
    "C01": "rules-roadshow-20261102",
    "C04": "rules-roadshow-20261102",
    "C05": "rules-roadshow-20261102",
    "C06": "rules-roadshow-20261102",
    "C09": "epb-qc-v1",
    "C13": "physics-informed-v1",
}


def _parse_rows(csv_path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(csv_path, encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row = dict(raw)
            for key in ("regionsDetail", "mechanicalCoverage", "missLabel", "overlapNote"):
                if key in row and isinstance(row[key], str):
                    try:
                        row[key] = json.loads(row[key])
                    except json.JSONDecodeError:
                        row[key] = []
            rows.append(row)
    return rows


def _se_re(k: int, n: int, p: float | None = None) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = k / n if p is None else p
    se = math.sqrt(p * (1 - p) / n) if n else 0.0
    re = (se / p) if p > 1e-12 else (0.0 if k == 0 else float("inf"))
    return p, se, re


def _dark_unlabeled_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    objects_with_candidates = 0
    total_candidates = 0
    objects_band_signal = 0
    confirmed_fail = 0
    for row in rows:
        miss = row.get("missLabel") or {}
        cands = miss.get("candidates") or []
        ring = miss.get("miss_ring_audit") or []
        if cands:
            objects_with_candidates += 1
            total_candidates += len(cands)
        if any(m.get("audit_miss_label") in {"likely_miss", "review"} for m in ring):
            objects_band_signal += 1
        if row.get("九7_漏标") == "不通过":
            confirmed_fail += 1
    n = len(rows) or 1
    k = objects_with_candidates
    p, se, re = _se_re(k, n)
    return {
        "objects_with_candidates": objects_with_candidates,
        "total_candidates": total_candidates,
        "objects_band_heuristic_signal": objects_band_signal,
        "confirmed_miss_fail_objects": confirmed_fail,
        "rate_objects_with_candidates": round(p, 6),
        "se": round(se, 6),
        "relative_error": None if not math.isfinite(re) else round(re, 4),
        "policy": "九7_可能未标暗条=诊断轨；九7_漏标=Pass2/Agent 确认才计分 fail",
    }


def _region_verdicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        oid = row.get("objectId") or ""
        for reg in row.get("regionsDetail") or []:
            out.append({
                "objectId": oid,
                "region_id": reg.get("region_id"),
                "fieldPath": reg.get("fieldPath") or "",
                "mechanical": reg.get("mechanical") or "none",
                "pass2_verdict": reg.get("pass2_verdict") or "",
                "pass1_confidence": reg.get("pass1_confidence"),
                "band_audit": reg.get("ring_audit_0.5_1d"),
            })
    return out


def compute_audit_metrics(rows: list[dict[str, Any]], *, n_labels_total: int | None = None) -> dict[str, Any]:
    n_objects = len(rows)
    regions = _region_verdicts(rows)
    n_regions = len(regions)

    obj_cols = ["九1_文件配对", "九3a_像素越界", "九4_类别非法", "九6_尺寸矛盾", "九9_覆盖异常"]
    obj_fail = {c: sum(1 for r in rows if r.get(c) == "不通过") for c in obj_cols}
    obj_und = {c: sum(1 for r in rows if r.get(c) == "待判定") for c in ["九3b_轮廓贴合", "九8_虚标"]}
    dark = _dark_unlabeled_stats(rows)

    reg_unreasonable = sum(1 for r in regions if r.get("pass2_verdict") == "不合理")
    reg_uncertain = sum(1 for r in regions if r.get("pass2_verdict") == "不确定")
    reg_reasonable = sum(1 for r in regions if r.get("pass2_verdict") == "合理")
    reg_mechanical = sum(1 for r in regions if r.get("mechanical") not in {"none", "", None})

    n_with_pass2 = sum(
        1 for r in rows if any((x.get("pass2_verdict") for x in (r.get("regionsDetail") or [])))
    )
    miss_confirmed = dark["confirmed_miss_fail_objects"]

    metrics: list[dict[str, Any]] = []
    checks = [
        ("C01", "object", n_objects, obj_fail.get("九1_文件配对", 0), "有 mask 对象 fileName 配对"),
        ("C04", "object", n_objects, obj_fail.get("九4_类别非法", 0), "mask label 含 __OOV__"),
        ("C05", "object", n_objects, obj_fail.get("九3a_像素越界", 0), "1024 画面内 mask 顶点"),
        ("C06", "object", n_objects, obj_fail.get("九6_尺寸矛盾", 0), "imgSize 与画面/顶点一致"),
        (
            "C09-dark-unlabeled",
            "object",
            n_objects,
            dark["objects_with_candidates"],
            "可能未标暗条（诊断轨，非计分漏标）",
        ),
        ("C09-overlap", "object", n_objects, obj_fail.get("九9_覆盖异常", 0), "机械 IoU/IOS≥0.65 或退化框"),
        ("C09-miss-confirmed", "object", n_objects, miss_confirmed, "九7_漏标=不通过（Agent/Pass2 确认）"),
        ("C13-region", "region", n_regions, reg_unreasonable, "Pass2 单 mask verdict=不合理"),
        ("C13-region-und", "region", n_regions, reg_uncertain, "Pass2 单 mask verdict=不确定"),
        ("C09-region-mech", "region", n_regions, reg_mechanical, "逐 mask mechanical 标记"),
    ]
    for check_id, denom_type, denom, k, note in checks:
        p, se, re = _se_re(k, denom)
        metrics.append({
            "checkId": check_id,
            "denomType": denom_type,
            "denominator": denom,
            "numerator_k": k,
            "rate_p": round(p, 6),
            "se": round(se, 6),
            "relative_error_se_over_p": None if not math.isfinite(re) else round(re, 4),
            "note": note,
        })

    return {
        "n_objects_boxed": n_objects,
        "n_regions_labeled": n_regions,
        "n_labels_in_dir": n_labels_total,
        "n_objects_with_pass2": n_with_pass2,
        "pass2_coverage_objects": round(n_with_pass2 / max(n_objects, 1), 4),
        "region_pass2_counts": {
            "合理": reg_reasonable,
            "不确定": reg_uncertain,
            "不合理": reg_unreasonable,
            "未跑批": n_regions - reg_reasonable - reg_uncertain - reg_unreasonable,
        },
        "object_fail_counts": obj_fail,
        "object_fail_counts_scored": obj_fail,
        "object_undetermined_counts": obj_und,
        "dark_unlabeled": dark,
        "ratio_metrics": metrics,
    }


def roadshow_result_row(
    dir_id: str,
    audit: dict[str, Any],
    *,
    dataset_version: str = "fbbqy",
    rank_in_dataset: int = 0,
    rank_global: int = 0,
) -> dict[str, str]:
    fails = audit.get("object_fail_counts") or {}
    kinds: list[str] = []
    if fails.get("九1_文件配对"):
        kinds.append("文件配对")
    if fails.get("九3a_像素越界"):
        kinds.append("像素越界")
    if fails.get("九4_类别非法"):
        kinds.append("类别非法")
    if fails.get("九6_尺寸矛盾"):
        kinds.append("尺寸矛盾")
    if fails.get("九9_覆盖异常"):
        kinds.append("覆盖异常")
    dark = audit.get("dark_unlabeled") or {}
    if dark.get("objects_with_candidates"):
        kinds.append("可能未标暗条(诊断)")
    if dark.get("confirmed_miss_fail_objects"):
        kinds.append("漏标确认")
    rp = audit.get("region_pass2_counts") or {}
    if rp.get("不合理"):
        kinds.append("轮廓虚标")
    if not kinds:
        kinds.append("未发现计分缺陷" if audit.get("n_objects_with_pass2") else "规则通过·语义待跑批")

    n_obj = int(audit.get("n_objects_boxed") or 1)
    n_reg = audit.get("n_regions_labeled") or 1
    pair_f = fails.get("九1_文件配对", 0)
    ann_obj = sum(
        fails.get(k, 0)
        for k in ("九3a_像素越界", "九4_类别非法", "九6_尺寸矛盾", "九9_覆盖异常")
    )
    ann_reg = rp.get("不合理", 0)
    density_obj = (pair_f + ann_obj) / (2 * max(n_obj, 1))
    density_reg = ann_reg / max(n_reg, 1)
    density = min(1.0, density_obj + 0.5 * density_reg)
    score = max(0.0, min(100.0, round(100 * (1 - density), 1)))

    evidence = (
        f"有 mask 对象 {n_obj}；标注 mask {n_reg}；配对失败 {pair_f}；"
        f"计分轨对象异常 {ann_obj}；mask 级不合理 {ann_reg}；"
        f"可能未标暗条(诊断) {dark.get('objects_with_candidates', 0)} 对象；"
        f"Pass2/legacy 覆盖 {audit.get('n_objects_with_pass2', 0)}/{n_obj}"
    )
    return {
        "datasetId": "EPB_seg_sample",
        "datasetVersion": dataset_version,
        "dirId": dir_id,
        "rankInDataset": str(rank_in_dataset or ""),
        "rankGlobal": str(rank_global or ""),
        "totalScore": str(score),
        "mainDefectTypes": "；".join(kinds),
        "evidence": evidence,
    }


def evidence_rows_from_object_csv(
    rows: list[dict[str, Any]],
    *,
    dir_id: str,
    seq_start: int = 1,
    max_region_fails: int = 200,
) -> tuple[list[dict[str, str]], int]:
    findings: list[dict[str, str]] = []
    seq = seq_start - 1
    family = "EPB"

    def add(
        check: str,
        verdict: str,
        detail: str,
        object_id: str = "",
        field: str = "",
        locator: str = "file",
        rule: str | None = None,
    ) -> None:
        nonlocal seq
        seq += 1
        findings.append({
            "findingId": f"{check}-{family}-{seq:06d}",
            "checkId": check.split("-")[0],
            "ruleVersion": rule or RULE_VERSIONS.get(check.split("-")[0], "epb-qc-v1"),
            "dirId": dir_id,
            "objectId": object_id,
            "fieldPath": field,
            "locatorType": locator,
            "verdict": verdict,
            "detail": detail,
        })

    n_obj = len(rows)
    n_reg = sum(int(r.get("nRegions") or 0) for r in rows)
    dark = _dark_unlabeled_stats(rows)
    add(
        "C09",
        "not_applicable",
        f"九7 可能未标暗条 {dark['objects_with_candidates']}/{n_obj} 对象、"
        f"候选 {dark['total_candidates']} 处（诊断轨）；确认漏标 fail {dark['confirmed_miss_fail_objects']}",
        rule="epb-qc-v1",
    )

    epb_nine_cols = [
        "九1_文件配对", "九2_孤儿标注", "九3a_像素越界", "九3b_轮廓贴合", "九4_类别非法",
        "九5_时段超限", "九6_尺寸矛盾", "九7_可能未标暗条", "九7_漏标", "九8_虚标", "九9_覆盖异常",
    ]
    for col in epb_nine_cols:
        check = NINE_TO_CHECK.get(col, "C09")
        if col == "九5_时段超限":
            add(check, "not_applicable", "EPB 目录不适用 C07/九5", rule="epb-qc-v1")
            continue
        if col == "九7_可能未标暗条":
            k = sum(1 for r in rows if (r.get(col) or "") not in ("无", "不适用", ""))
            add(check, "pass" if k == 0 else "undetermined", f"{col} 有候选/信号 {k}/{n_obj}（诊断）", rule="epb-qc-v1")
            continue
        counts = Counter(r.get(col) or "" for r in rows)
        fail_k = counts.get("不通过", 0)
        und_k = counts.get("待判定", 0)
        pass_k = counts.get("通过", 0)
        na_k = counts.get("不适用", 0)
        add(
            check,
            "fail" if fail_k else "pass",
            f"{col} 对象级：通过 {pass_k}、不通过 {fail_k}、待判定 {und_k}、不适用 {na_k} / n={n_obj}",
            rule="epb-qc-v1",
        )

    add(
        "C13",
        "undetermined" if audit_pass2_pending(rows) else ("fail" if reg_unreasonable(rows) else "pass"),
        f"C13 mask 级 n={n_reg}；不合理 {count_region_verdict(rows, '不合理')}；"
        f"不确定 {count_region_verdict(rows, '不确定')}；合理 {count_region_verdict(rows, '合理')}",
        rule="physics-informed-v1",
    )

    for row in rows:
        oid = row.get("objectId") or ""
        for col in ("九9_覆盖异常", "九3a_像素越界", "九4_类别非法", "九6_尺寸矛盾"):
            if row.get(col) != "不通过":
                continue
            check = NINE_TO_CHECK.get(col, "C09")
            add(check, "fail", row.get("notes") or col, oid, locator="sampleId")

    n_out = 0
    for row in rows:
        oid = row.get("objectId") or ""
        for reg in row.get("regionsDetail") or []:
            if n_out >= max_region_fails:
                break
            rid = reg.get("region_id")
            fp = reg.get("fieldPath") or ""
            v2 = reg.get("pass2_verdict") or ""
            mech = reg.get("mechanical") or "none"
            if v2 == "不合理":
                add("C13", "fail", f"region_id={rid} Pass2/legacy 不合理", oid, fp, "imageRegion")
                n_out += 1
            elif mech not in ("none", ""):
                add("C09", "fail", f"region_id={rid} 机械·{mech}", oid, fp, "imageRegion", rule="mechanical-coverage-v1")
                n_out += 1
    return findings, seq + 1


def reg_unreasonable(rows: list[dict[str, Any]]) -> bool:
    return count_region_verdict(rows, "不合理") > 0


def defect_severity_ranking(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []

    def push(
        severity: int,
        kind: str,
        object_id: str,
        region_id: int | None,
        field_path: str,
        metric: str,
        detail: str,
    ) -> None:
        ranked.append({
            "severity_rank": severity,
            "defect_kind": kind,
            "objectId": object_id,
            "region_id": "" if region_id is None else region_id,
            "fieldPath": field_path,
            "metric": metric,
            "detail": detail,
        })

    for row in rows:
        oid = row.get("objectId") or ""
        mech = row.get("mechanicalCoverage") or {}
        for pair in mech.get("severe_overlap_pairs") or []:
            iou = pair.get("bbox_iou") or pair.get("intersection_over_smaller") or 0
            ra, rb = pair.get("region_a"), pair.get("region_b")
            fp = f"science_annotation.mask.shapes[{ra}].polygon" if ra is not None else ""
            push(90, "覆盖过多", oid, ra, fp, f"iou={iou}", str(pair.get("detail") or ""))
        for issue in mech.get("region_issues") or []:
            rid = issue.get("region_id")
            push(
                85,
                issue.get("nine_defect_bucket") or "覆盖异常",
                oid,
                rid,
                f"science_annotation.mask.shapes[{rid}].polygon",
                "mechanical",
                str(issue.get("detail") or ""),
            )
        for col, kind in (
            ("九4_类别非法", "类别非法"),
            ("九6_尺寸矛盾", "尺寸矛盾"),
            ("九3a_像素越界", "像素越界"),
        ):
            if row.get(col) == "不通过":
                push(75, kind, oid, None, "basic_annotation", col, row.get("notes") or "")
        for reg in row.get("regionsDetail") or []:
            rid = reg.get("region_id")
            fp = reg.get("fieldPath") or ""
            v2 = reg.get("pass2_verdict") or ""
            if v2 == "不合理":
                push(80, "轮廓虚标", oid, rid, fp, "pass2=不合理", "")
            elif v2 == "不确定":
                push(50, "轮廓待复核", oid, rid, fp, "pass2=不确定", reg.get("ring_audit_0.5_1d") or "")
        miss = row.get("missLabel") or {}
        for m in miss.get("miss_ring_audit") or []:
            if m.get("audit_miss_label") != "likely_miss":
                continue
            dep = m.get("depletion_depth_dn") or m.get("contrast_inside_vs_outer_band")
            push(70, "可能未标暗条", oid, None, "", f"depletion={dep}", str(m.get("centroid_full") or ""))

    ranked.sort(key=lambda r: (-int(r["severity_rank"]), r.get("objectId") or "", str(r.get("region_id"))))
    for i, row in enumerate(ranked, start=1):
        row["order"] = i
    return ranked


def build_scorecard_from_audit(
    audit: dict[str, Any],
    result_row: dict[str, str],
    *,
    dir_id: str,
    template_path: str | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {}
    if template_path and os.path.isfile(template_path):
        base = json.load(open(template_path, encoding="utf-8"))
    metrics = {m["checkId"]: m for m in audit.get("ratio_metrics") or []}
    n_obj = audit.get("n_objects_boxed") or 0
    n_reg = audit.get("n_regions_labeled") or 0
    card = {
        **base,
        "scorecard_id": f"SC-{dir_id}-epb-qc-v1",
        "dataset_name": dir_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": "epb-qc-v1+physics-informed-v1",
        "system_version": base.get("system_version") or "prototype-v1.0",
        "random_seed": 0,
        "total_labels_in_dir": audit.get("n_labels_in_dir") or base.get("total_labels_in_dir"),
        "boxed_objects_count": n_obj,
        "labeled_regions_count": n_reg,
        "overall_quality_score": float(result_row.get("totalScore") or 0),
        "roadshow_result_row": result_row,
        "object_qc_coverage": "100% masked PNG+json pairs",
        "pass2_object_coverage": audit.get("pass2_coverage_objects"),
        "region_pass2_counts": audit.get("region_pass2_counts"),
        "ratio_metrics": audit.get("ratio_metrics"),
    }
    inv = list(base.get("nine_defect_inventory") or [])
    dark = audit.get("dark_unlabeled") or {}
    fails = audit.get("object_fail_counts") or {}
    static_patch = {
        1: fails.get("九1_文件配对", 0),
        3: fails.get("九3a_像素越界", 0),
        4: fails.get("九4_类别非法", 0),
        6: fails.get("九6_尺寸矛盾", 0),
    }
    for item in inv:
        idx = item.get("index")
        if idx in static_patch:
            item["count"] = static_patch[idx]
            item["denominator"] = n_obj
            item["rate"] = round(static_patch[idx] / max(n_obj, 1), 6)
            item["status"] = "已审计(epb-qc-v1)"
        if idx == 7:
            m = metrics.get("C13-region") or {}
            item["count"] = m.get("numerator_k")
            item["denominator"] = m.get("denominator") or n_reg
            item["rate"] = m.get("rate_p")
            item["status"] = "已审计(epb-qc-v1)"
            item["audit_note"] = "mask 级 Pass2/legacy 不合理"
        if idx == 8:
            item["count"] = dark.get("objects_with_candidates")
            item["denominator"] = n_obj
            item["rate"] = dark.get("rate_objects_with_candidates")
            item["roadshow_scored"] = False
            item["track"] = "诊断轨(可能未标暗条)"
            item["status"] = "已审计(epb-qc-v1)"
        if idx == 9:
            m = metrics.get("C09-overlap") or {}
            item["count"] = m.get("numerator_k")
            item["denominator"] = m.get("denominator") or n_obj
            item["rate"] = m.get("rate_p")
            item["roadshow_scored"] = True
            item["status"] = "已审计(epb-qc-v1)"
    card["nine_defect_inventory"] = inv
    return card


def write_severity_and_scorecard(
    object_csv_path: str,
    out_dir: str,
    manifest: dict[str, Any],
    *,
    scorecard_template: str | None = None,
) -> dict[str, str]:
    rows = _parse_rows(object_csv_path)
    dir_id = manifest.get("dirId") or "unknown"
    audit = manifest.get("audit") or {}
    result_row = roadshow_result_row(dir_id, audit)

    sev = defect_severity_ranking(rows)
    sev_path = os.path.join(out_dir, f"{dir_id}_缺陷严重程度排序.csv")
    if sev:
        with open(sev_path, "w", encoding="utf-8", newline="") as handle:
            w = csv.DictWriter(handle, fieldnames=list(sev[0].keys()))
            w.writeheader()
            w.writerows(sev)

    card = build_scorecard_from_audit(
        audit,
        result_row,
        dir_id=dir_id,
        template_path=scorecard_template,
    )
    card_path = os.path.join(out_dir, "评分卡_EPB_fbbqy_epb_qc.json")
    with open(card_path, "w", encoding="utf-8") as handle:
        json.dump(card, handle, ensure_ascii=False, indent=2)

    stats_md = os.path.join(out_dir, f"{dir_id}_缺陷统计摘要.md")
    rp = audit.get("region_pass2_counts") or {}
    n_obj = int(audit.get("n_objects_boxed") or 0)
    with open(stats_md, "w", encoding="utf-8") as handle:
        handle.write(f"# {dir_id} 缺陷统计（epb-qc-v1 · 汇总口径 v1）\n\n")
        handle.write(f"- 有 mask 对象：**{n_obj}**；标注 mask：**{audit.get('n_regions_labeled')}**\n")
        handle.write(f"- 对象 Pass2/legacy 覆盖：**{audit.get('n_objects_with_pass2')}**\n")
        handle.write(
            f"- mask 级 Pass2：合理 {rp.get('合理',0)} / 不确定 {rp.get('不确定',0)} / "
            f"不合理 {rp.get('不合理',0)} / 未跑 {rp.get('未跑批',0)}\n"
        )
        du = audit.get("dark_unlabeled") or {}
        handle.write(
            f"- **可能未标暗条（诊断）**：{du.get('objects_with_candidates', 0)} 对象 / "
            f"{n_obj}，候选 {du.get('total_candidates', 0)} 处；"
            f"确认漏标 fail {du.get('confirmed_miss_fail_objects', 0)}\n\n"
        )
        handle.write("## 比例指标\n\n| checkId | 分母 | k | p | RE |\n|---|---:|---:|---:|---:|\n")
        for m in audit.get("ratio_metrics") or []:
            handle.write(
                f"| {m.get('checkId')} | {m.get('denominator')} | {m.get('numerator_k')} | "
                f"{m.get('rate_p')} | {m.get('relative_error_se_over_p')} |\n"
            )
        handle.write(f"\n排序表：`{os.path.basename(sev_path)}`（{len(sev)} 条）\n")

    return {"severity_csv": sev_path, "scorecard_json": card_path, "stats_md": stats_md}


def write_directory_bundle(
    object_csv_path: str,
    out_dir: str,
    *,
    dir_id: str | None = None,
    n_labels_total: int | None = None,
) -> dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    rows = _parse_rows(object_csv_path)
    dir_id = dir_id or (rows[0].get("dirId") if rows else "unknown")
    audit = compute_audit_metrics(rows, n_labels_total=n_labels_total)
    est = estimate_runtime_tokens(
        n_objects=audit["n_objects_boxed"],
        n_regions=audit["n_regions_labeled"],
    )

    result_row = roadshow_result_row(dir_id, audit)
    result_csv = os.path.join(out_dir, f"{dir_id}_路演结果行.csv")
    with open(result_csv, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=list(result_row.keys()))
        w.writeheader()
        w.writerow(result_row)

    stats_csv = os.path.join(out_dir, f"{dir_id}_EPB审计指标.csv")
    with open(stats_csv, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(
            handle,
            fieldnames=[
                "checkId", "denomType", "denominator", "numerator_k",
                "rate_p", "se", "relative_error_se_over_p", "note",
            ],
        )
        w.writeheader()
        for m in audit["ratio_metrics"]:
            w.writerow(m)

    evidence, _ = evidence_rows_from_object_csv(rows, dir_id=dir_id)
    ev_csv = os.path.join(out_dir, f"{dir_id}_EPB证据汇总.csv")
    ev_header = [
        "findingId", "checkId", "ruleVersion", "dirId", "objectId",
        "fieldPath", "locatorType", "verdict", "detail",
    ]
    with open(ev_csv, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=ev_header)
        w.writeheader()
        w.writerows(evidence)

    manifest = {
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "dirId": dir_id,
        "objectCsv": object_csv_path,
        "ruleVersions": {
            "object_qc": rows[0].get("ruleVersion") if rows else "epb-qc-v1",
            "roadshow_rules": RULE_VERSIONS,
        },
        "randomSeed": 0,
        "audit": audit,
        "runtime_estimate": est,
        "outputs": {
            "roadshow_result_row": result_csv,
            "audit_metrics_csv": stats_csv,
            "evidence_aggregate_csv": ev_csv,
        },
    }
    manifest_path = os.path.join(out_dir, f"{dir_id}_EPB目录审计包.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest
