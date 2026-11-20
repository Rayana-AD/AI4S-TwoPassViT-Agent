"""Aggregate per-object AIA QC CSV → 02 路演结果行 + 证据表行 + 可审计指标."""

from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any

EVIDENCE_VERBS = {"通过": "pass", "不通过": "fail", "待判定": "undetermined", "不适用": "not_applicable"}

NINE_TO_CHECK = {
    "九1_文件配对": "C01",
    "九2_孤儿标注": "C01",
    "九3a_像素越界": "C05",
    "九3b_轮廓贴合": "C13",
    "九4_类别非法": "C04",
    "九5_时段超限": "C07",
    "九6_尺寸矛盾": "C06",
    "九7_漏标": "C09",
    "九8_虚标": "C09",
    "九9_覆盖异常": "C09",
}

RULE_VERSIONS = {
    "C01": "rules-roadshow-20261102",
    "C04": "rules-roadshow-20261102",
    "C05": "rules-roadshow-20261102",
    "C09": "aia-qc-v1",
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


def _bright_unlabeled_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """EUV 启发式亮区：记为「可能未标亮区」，不计入九类漏标 fail（兼容旧 CSV 列 九7_漏标）。"""
    objects_with_candidates = 0
    total_candidates = 0
    objects_ring_signal = 0
    legacy_col_fail = 0
    for row in rows:
        miss = row.get("missLabel") or {}
        cands = miss.get("candidates") or []
        ring = miss.get("miss_ring_audit") or []
        if cands:
            objects_with_candidates += 1
            total_candidates += len(cands)
        if any(m.get("audit_miss_label") in {"likely_miss", "review"} for m in ring):
            objects_ring_signal += 1
        col = row.get("九7_可能未标亮区") or row.get("九7_漏标") or ""
        if col == "不通过":
            legacy_col_fail += 1
    n = len(rows) or 1
    k = objects_with_candidates
    p, se, re = _se_re(k, n)
    return {
        "objects_with_candidates": objects_with_candidates,
        "total_candidates": total_candidates,
        "objects_ring_heuristic_signal": objects_ring_signal,
        "legacy_csv_九7_不通过": legacy_col_fail,
        "rate_objects_with_candidates": round(p, 6),
        "se": round(se, 6),
        "relative_error": None if not math.isfinite(re) else round(re, 4),
        "policy": "诊断轨/非计分；不等同 HEK 漏标；旧列 九7_漏标 仅作历史字段",
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
                "ring_audit": reg.get("ring_audit_0.5_1d"),
            })
    return out


def compute_audit_metrics(rows: list[dict[str, Any]], *, n_labels_total: int | None = None) -> dict[str, Any]:
    """Numerators/denominators for Q4/Q7; region-level C13/C09."""
    n_objects = len(rows)
    regions = _region_verdicts(rows)
    n_regions = len(regions)

    obj_cols = [
        "九1_文件配对", "九3a_像素越界", "九9_覆盖异常", "objectOverall",
    ]
    obj_fail = {c: sum(1 for r in rows if r.get(c) == "不通过") for c in obj_cols if c != "objectOverall"}
    obj_und = {c: sum(1 for r in rows if r.get(c) == "待判定") for c in ["九3b_轮廓贴合", "九8_虚标"]}
    bright = _bright_unlabeled_stats(rows)

    reg_unreasonable = sum(1 for r in regions if r.get("pass2_verdict") == "不合理")
    reg_uncertain = sum(1 for r in regions if r.get("pass2_verdict") == "不确定")
    reg_reasonable = sum(1 for r in regions if r.get("pass2_verdict") == "合理")
    reg_mechanical = sum(1 for r in regions if r.get("mechanical") not in {"none", "", None})

    n_with_pass2 = sum(1 for r in rows if any((x.get("pass2_verdict") for x in (r.get("regionsDetail") or []))))

    metrics: list[dict[str, Any]] = []
    checks = [
        ("C01", "object", n_objects, obj_fail.get("九1_文件配对", 0), "有像素框对象 fileName 配对"),
        ("C05", "object", n_objects, obj_fail.get("九3a_像素越界", 0), "4096 画面内像素框"),
        (
            "C09-bright-unlabeled",
            "object",
            n_objects,
            bright["objects_with_candidates"],
            "可能未标亮区（EUV 诊断轨，非计分漏标）",
        ),
        ("C09-overlap", "object", n_objects, obj_fail.get("九9_覆盖异常", 0), "机械 IoU/IOS≥0.65 或退化框"),
        ("C09-miss-confirmed", "object", n_objects, 0, "Agent/Pass2 确认的漏标（当前无全目录确认）"),
        ("C13-region", "region", n_regions, reg_unreasonable, "Pass2 单框 verdict=不合理"),
        ("C13-region-und", "region", n_regions, reg_uncertain, "Pass2 单框 verdict=不确定"),
        ("C09-region-mech", "region", n_regions, reg_mechanical, "逐框 mechanical 标记"),
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
        "bright_unlabeled": bright,
        "ratio_metrics": metrics,
    }


def roadshow_result_row(
    dir_id: str,
    audit: dict[str, Any],
    *,
    dataset_version: str = "v34",
    rank_in_dataset: int = 0,
    rank_global: int = 0,
) -> dict[str, str]:
    """One row for 路演结果_{队名}.csv (6.1)."""
    fails = audit.get("object_fail_counts") or {}
    kinds: list[str] = []
    if fails.get("九1_文件配对"):
        kinds.append("文件配对")
    if fails.get("九3a_像素越界"):
        kinds.append("像素越界")
    if fails.get("九9_覆盖异常"):
        kinds.append("覆盖异常")
    bright = audit.get("bright_unlabeled") or {}
    if bright.get("objects_with_candidates"):
        kinds.append("可能未标亮区(诊断)")
    rp = audit.get("region_pass2_counts") or {}
    if rp.get("不合理"):
        kinds.append("轮廓虚标")
    if not kinds:
        kinds.append("未发现计分缺陷" if audit.get("n_objects_with_pass2") else "规则通过·语义待跑批")

    n_obj = int(audit.get("n_objects_boxed") or 1)
    n_reg = audit.get("n_regions_labeled") or 1
    pair_f = fails.get("九1_文件配对", 0)
    ann_obj = sum(fails.get(k, 0) for k in ("九3a_像素越界", "九9_覆盖异常"))
    ann_reg = rp.get("不合理", 0)
    density_obj = (pair_f + ann_obj) / (2 * max(n_obj, 1))
    density_reg = ann_reg / max(n_reg, 1)
    density = min(1.0, density_obj + 0.5 * density_reg)
    score = max(0.0, min(100.0, round(100 * (1 - density), 1)))

    evidence = (
        f"有框对象 {n_obj}；标注框 {n_reg}；配对失败 {pair_f}；"
        f"计分轨对象异常 {ann_obj}；框级不合理 {ann_reg}；"
        f"可能未标亮区(诊断) {bright.get('objects_with_candidates', 0)} 对象；"
        f"Pass2 覆盖 {audit.get('n_objects_with_pass2', 0)}/{n_obj}"
    )
    return {
        "datasetId": "AIA_AR_sample",
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
    """02 §6.2 evidence rows; returns (rows, next_seq)."""
    findings: list[dict[str, str]] = []
    seq = seq_start - 1
    family = "AIA"

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
            "ruleVersion": rule or RULE_VERSIONS.get(check.split("-")[0], "aia-qc-v1"),
            "dirId": dir_id,
            "objectId": object_id,
            "fieldPath": field,
            "locatorType": locator,
            "verdict": verdict,
            "detail": detail,
        })

    n_obj = len(rows)
    n_reg = sum(int(r.get("nRegions") or 0) for r in rows)

    # Directory-level summaries (four verdicts per check where applicable)
    bright = _bright_unlabeled_stats(rows)
    add(
        "C09",
        "not_applicable",
        f"九7 漏标计分轨不适用(AIA HEK 事件框)；可能未标亮区 {bright['objects_with_candidates']}/{n_obj} 对象、"
        f"候选 {bright['total_candidates']} 处（诊断轨，非 fail）",
        rule="aia-qc-v1",
    )

    for col, check in NINE_TO_CHECK.items():
        if col.startswith("九5") or col.startswith("九6"):
            add(check, "not_applicable", f"AIA 目录不适用 {col}", rule="aia-qc-v1")
            continue
        if col == "九7_漏标":
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
            rule="aia-qc-v1",
        )
        if und_k:
            add(check, "undetermined", f"{col} 待判定 {und_k} 个对象（缺 Pass2 或未跑漏标 full）", rule="aia-qc-v1")
        if pass_k:
            add(check, "pass", f"{col} 通过 {pass_k} 个对象", rule="aia-qc-v1")
        if na_k:
            add(check, "not_applicable", f"{col} 不适用 {na_k}", rule="aia-qc-v1")

    add(
        "C13",
        "undetermined" if audit_pass2_pending(rows) else ("fail" if any_region_unreasonable(rows) else "pass"),
        f"C13 框级 n={n_reg}；不合理 {count_region_verdict(rows, '不合理')}；"
        f"不确定 {count_region_verdict(rows, '不确定')}；合理 {count_region_verdict(rows, '合理')}",
        rule="physics-informed-v1",
    )

    # Sample object fails
    for row in rows:
        oid = row.get("objectId") or ""
        for col in ("九9_覆盖异常", "九3a_像素越界"):
            if row.get(col) != "不通过":
                continue
            check = NINE_TO_CHECK[col]
            add(check, "fail", row.get("notes") or col, oid, locator="sampleId")

    # Region-level C13 / C09 mechanical
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
                add("C13", "fail", f"region_id={rid} Pass2 不合理", oid, fp, "imageRegion")
                n_out += 1
            elif mech not in ("none", ""):
                add("C09", "fail", f"region_id={rid} 机械·{mech}", oid, fp, "imageRegion", rule="mechanical-coverage-v1")
                n_out += 1
    return findings, seq + 1


def audit_pass2_pending(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if row.get("九3b_轮廓贴合") == "待判定" or row.get("九8_虚标") == "待判定":
            return True
    return False


def any_region_unreasonable(rows: list[dict[str, Any]]) -> bool:
    return count_region_verdict(rows, "不合理") > 0


def count_region_verdict(rows: list[dict[str, Any]], verdict: str) -> int:
    n = 0
    for row in rows:
        for reg in row.get("regionsDetail") or []:
            if (reg.get("pass2_verdict") or "") == verdict:
                n += 1
    return n


def estimate_runtime_tokens(
    n_objects: int = 473,
    n_regions: int = 2042,
    *,
    miss_mode: str = "fast",
    api_workers: int = 8,
    rule_workers: int = 8,
) -> dict[str, Any]:
    """Wall-clock & token budget for full z4 directory (measured + extrapolated)."""
    # Measured: miss fast ~3.6s/obj; miss full ~19.5s/obj; VLM 2 samples
    rule_sec_per_obj = 3.6 if miss_mode == "fast" else (0.5 if miss_mode == "skip" else 19.5)
    rule_sec = n_objects * rule_sec_per_obj / max(rule_workers, 1)

    # Token fit from 0yML (19 reg) and 1GLxp (2 reg)
    def tokens_for_regions(nr: int) -> int:
        if nr <= 2:
            return 8634
        if nr >= 19:
            return 39917
        return int(8634 + (39917 - 8634) * (nr - 2) / (19 - 2))

    # approximate with mean regions per object
    mean_reg = n_regions / max(n_objects, 1)
    mean_tok = tokens_for_regions(max(1, round(mean_reg)))
    total_tokens = int(mean_tok * n_objects)
    # pass2 dominates wall time when API-bound
    sec_per_obj_api = 28.0 if mean_reg <= 3 else (45.0 if mean_reg <= 8 else 90.0)
    api_sec = n_objects * sec_per_obj_api / max(api_workers, 1)

    return {
        "assumptions": {
            "n_objects_boxed": n_objects,
            "n_regions": n_regions,
            "mean_regions_per_object": round(mean_reg, 3),
            "miss_mode": miss_mode,
            "api_workers": api_workers,
            "rule_workers": rule_workers,
            "vlm_samples": ["0yML 19reg ~40k tok ~90s", "1GLxp 2reg ~8.6k tok ~28s"],
        },
        "rule_pipeline_sec_est": round(rule_sec, 1),
        "rule_pipeline_under_3h": rule_sec < 10800,
        "vlm_api_sec_est_parallel": round(api_sec, 1),
        "vlm_api_under_3h_parallel": api_sec < 10800,
        "vlm_total_tokens_est": total_tokens,
        "vlm_tokens_millions": round(total_tokens / 1e6, 2),
        "recommended": (
            "全目录：规则+漏标 --miss-mode fast --jobs 8 先出对象 CSV 与证据；"
            "VLM Pass1+2 473 张 --jobs 4~8 视 API 限速；九3b/九8 未覆盖对象标待判定"
        ),
    }


def write_hek_context_for_dir(
    object_csv_path: str,
    out_dir: str,
    *,
    dir_id: str | None = None,
    data_dir: str,
) -> dict[str, str]:
    from aia_hek_context_analysis import write_hek_context_csvs

    rows = _parse_rows(object_csv_path)
    dir_id = dir_id or (rows[0].get("dirId") if rows else "unknown")
    return write_hek_context_csvs(
        rows,
        data_dir=data_dir,
        dir_id=dir_id,
        out_dir=out_dir,
    )


def write_directory_bundle(
    object_csv_path: str,
    out_dir: str,
    *,
    dir_id: str | None = None,
    n_labels_total: int | None = None,
    data_dir: str | None = None,
    hek_context: bool = True,
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

    stats_csv = os.path.join(out_dir, f"{dir_id}_AIA审计指标.csv")
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
    ev_csv = os.path.join(out_dir, f"{dir_id}_AIA证据汇总.csv")
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
            "object_qc": rows[0].get("ruleVersion") if rows else "aia-qc-v1",
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
    if hek_context and data_dir and os.path.isdir(data_dir):
        manifest["outputs"].update(
            write_hek_context_for_dir(
                object_csv_path,
                out_dir,
                dir_id=dir_id,
                data_dir=data_dir,
            )
        )
    manifest_path = os.path.join(out_dir, f"{dir_id}_AIA目录审计包.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest


def defect_severity_ranking(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sortable defect list: region-first, then object-level miss/overlap."""
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
            iou = pair.get("bbox_iou") or pair.get("ios") or 0
            push(
                90,
                "覆盖过多",
                oid,
                pair.get("region_a"),
                "hek_event_annotation.matched_events[].bbox_polygon_pixel",
                f"iou={iou}",
                str(pair.get("detail") or ""),
            )
        for issue in mech.get("region_issues") or []:
            push(
                85,
                issue.get("nine_defect_bucket") or "覆盖异常",
                oid,
                issue.get("region_id"),
                f"hek_event_annotation.matched_events[{issue.get('hek_event_index', issue.get('region_id'))}].bbox_polygon_pixel",
                "mechanical",
                str(issue.get("detail") or ""),
            )
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
            c = m.get("contrast_inside_vs_0.5_1d")
            push(
                70,
                "可能未标亮区",
                oid,
                None,
                "",
                f"contrast_0.5_1d={c}",
                str(m.get("centroid_full") or m.get("bbox_full") or ""),
            )

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
    """Update 评分卡 with object+region denominators from aia-qc-v1."""
    base: dict[str, Any] = {}
    if template_path and os.path.isfile(template_path):
        base = json.load(open(template_path, encoding="utf-8"))
    metrics = {m["checkId"]: m for m in audit.get("ratio_metrics") or []}
    n_obj = audit.get("n_objects_boxed") or 0
    n_reg = audit.get("n_regions_labeled") or 0
    card = {
        **base,
        "scorecard_id": f"SC-{dir_id}-aia-qc-v1",
        "dataset_name": dir_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": "aia-qc-v1+physics-informed-v1",
        "system_version": base.get("system_version") or "prototype-v1.0",
        "random_seed": 0,
        "total_labels_in_dir": audit.get("n_labels_in_dir") or base.get("total_labels_in_dir"),
        "boxed_objects_count": n_obj,
        "labeled_regions_count": n_reg,
        "overall_quality_score": float(result_row.get("totalScore") or 0),
        "roadshow_result_row": result_row,
        "object_qc_coverage": "100% boxed PNG pairs",
        "pass2_object_coverage": audit.get("pass2_coverage_objects"),
        "region_pass2_counts": audit.get("region_pass2_counts"),
        "ratio_metrics": audit.get("ratio_metrics"),
    }
    inv = list(base.get("nine_defect_inventory") or [])
    bright = audit.get("bright_unlabeled") or {}
    patch = {
        7: ("C13-region", n_reg, "框级 Pass2 不合理"),
        8: ("C09-bright-unlabeled", n_obj, "可能未标亮区(诊断轨)"),
        9: ("C09-overlap", n_obj, "对象级机械覆盖异常"),
    }
    for item in inv:
        idx = item.get("index")
        if idx in patch:
            key, denom, note = patch[idx]  # type: ignore
            if idx == 8:
                item["count"] = bright.get("objects_with_candidates")
                item["denominator"] = n_obj
                item["rate"] = bright.get("rate_objects_with_candidates")
                item["roadshow_scored"] = False
                item["track"] = "诊断轨(非漏标)"
            else:
                m = metrics.get(key) or {}
                item["count"] = m.get("numerator_k")
                item["denominator"] = m.get("denominator") or denom
                item["rate"] = m.get("rate_p")
            item["status"] = "已审计(aia-qc-v1)"
            item["audit_note"] = note
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
    card_path = os.path.join(out_dir, "评分卡_AIA_z4_aia_qc.json")
    with open(card_path, "w", encoding="utf-8") as handle:
        json.dump(card, handle, ensure_ascii=False, indent=2)

    stats_md = os.path.join(out_dir, f"{dir_id}_缺陷统计摘要.md")
    rp = audit.get("region_pass2_counts") or {}
    n_obj = int(audit.get("n_objects_boxed") or 0)
    with open(stats_md, "w", encoding="utf-8") as handle:
        handle.write(f"# {dir_id} 缺陷统计（aia-qc-v1 · 汇总口径 v3）\n\n")
        handle.write(f"- 有框对象：**{n_obj}**；标注框：**{audit.get('n_regions_labeled')}**\n")
        handle.write(f"- 对象 Pass2 覆盖：**{audit.get('n_objects_with_pass2')}**\n")
        handle.write(f"- 框级 Pass2：合理 {rp.get('合理',0)} / 不确定 {rp.get('不确定',0)} / 不合理 {rp.get('不合理',0)} / 未跑 {rp.get('未跑批',0)}\n")
        bu = audit.get("bright_unlabeled") or {}
        handle.write(
            f"- **可能未标亮区（诊断，非漏标）**：{bu.get('objects_with_candidates', 0)} 对象 / "
            f"{n_obj}，候选 {bu.get('total_candidates', 0)} 处；"
            f"旧 CSV 列「九7_漏标=不通过」{bu.get('legacy_csv_九7_不通过', 0)} 条已作历史字段不作计分\n\n"
        )
        handle.write("## 比例指标（计分轨不含 C09-bright-unlabeled）\n\n| checkId | 分母 | k | p | RE |\n|---|---:|---:|---:|---:|\n")
        for m in audit.get("ratio_metrics") or []:
            handle.write(
                f"| {m.get('checkId')} | {m.get('denominator')} | {m.get('numerator_k')} | "
                f"{m.get('rate_p')} | {m.get('relative_error_se_over_p')} |\n"
            )
        handle.write(f"\n排序表：`{os.path.basename(sev_path)}`（{len(sev)} 条）\n")

    return {
        "severity_csv": sev_path,
        "scorecard_json": card_path,
        "stats_md": stats_md,
    }


_ROADSHOW_RESULTS_FIELDS = (
    "datasetId",
    "datasetVersion",
    "dirId",
    "rankInDataset",
    "rankGlobal",
    "totalScore",
    "mainDefectTypes",
    "evidence",
)


def _normalize_roadshow_result_row(result_row: dict[str, str]) -> dict[str, str]:
    row = {k: str(v) for k, v in result_row.items() if v is not None}
    if "mainDefectTypes" not in row and row.get("defectKinds"):
        row["mainDefectTypes"] = row.pop("defectKinds", "")
    if "evidence" not in row and row.get("note"):
        row["evidence"] = row.pop("note", "")
    row.pop("note", None)
    row.pop("defectKinds", None)
    return row


def patch_roadshow_results_csv(
    results_csv: str,
    result_row: dict[str, str],
    *,
    dir_id: str,
) -> None:
    if not os.path.isfile(results_csv):
        return
    patch = _normalize_roadshow_result_row(result_row)
    out_rows: list[dict[str, str]] = []
    matched = False
    with open(results_csv, encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or _ROADSHOW_RESULTS_FIELDS)
        for name in _ROADSHOW_RESULTS_FIELDS:
            if name not in fields:
                fields.append(name)
        for row in reader:
            if row.get("dirId") == dir_id:
                matched = True
                for key in patch:
                    if key in fields:
                        row[key] = patch[key]
            out_rows.append({k: row.get(k, "") for k in fields})
    if not matched:
        new_row = {k: "" for k in fields}
        new_row.update({k: patch[k] for k in patch if k in fields})
        out_rows.append(new_row)
    with open(results_csv, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)


def append_audit_log(log_path: str, entry: dict[str, Any]) -> None:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
