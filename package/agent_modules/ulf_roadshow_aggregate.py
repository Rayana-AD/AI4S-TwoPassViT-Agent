"""ULF object QC CSV → 路演结果行 / 审计包 / 证据 / 评分卡（对齐 AIA/EPB bundle）."""

from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone
from typing import Any

from aia_roadshow_aggregate import append_audit_log, estimate_runtime_tokens, patch_roadshow_results_csv

RULE_VERSIONS = {
    "C01": "rules-roadshow-20261102",
    "C07": "rules-roadshow-20261102",
    "C08": "rules-roadshow-20261102",
    "C09": "ulf-qc-v1",
    "C13": "physics-informed-v1",
}


def _parse_rows(csv_path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(csv_path, encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row = dict(raw)
            for key in ("regionsDetail", "waveformAudit", "windowAudit", "missLabel", "metadataFlags"):
                if key in row and isinstance(row[key], str):
                    try:
                        row[key] = json.loads(row[key])
                    except json.JSONDecodeError:
                        row[key] = [] if key == "regionsDetail" else {}
            rows.append(row)
    return rows


def _se_re(k: int, n: int) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = k / n
    se = math.sqrt(p * (1 - p) / n)
    re = (se / p) if p > 1e-12 else (0.0 if k == 0 else float("inf"))
    return p, se, re


def _pi2_unlabeled_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    objects_with_candidates = 0
    total_candidates = 0
    confirmed_fail = 0
    for row in rows:
        miss = row.get("missLabel") or {}
        ring = miss.get("miss_burst_audit") or []
        if row.get("九7_可能未标Pi2") == "有候选":
            objects_with_candidates += 1
        total_candidates += len(ring)
        if row.get("九7_漏标") == "不通过":
            confirmed_fail += 1
    n = len(rows) or 1
    k = objects_with_candidates
    p, se, re = _se_re(k, n)
    return {
        "objects_with_candidates": objects_with_candidates,
        "total_candidates": total_candidates,
        "confirmed_miss_fail_objects": confirmed_fail,
        "rate_objects_with_candidates": round(p, 6),
        "se": round(se, 6),
        "relative_error": None if not math.isfinite(re) else round(re, 4),
        "policy": "九7_可能未标Pi2=诊断轨；九7_漏标=Pass2 确认才计分 fail",
    }


def compute_audit_metrics(rows: list[dict[str, Any]], *, n_labels_total: int | None = None) -> dict[str, Any]:
    n_objects = len(rows)
    regions: list[dict[str, Any]] = []
    for row in rows:
        oid = row.get("objectId") or ""
        for reg in row.get("regionsDetail") or []:
            regions.append({
                "objectId": oid,
                "region_id": reg.get("region_id"),
                "pass2_verdict": reg.get("pass2_verdict") or "",
                "audit_labeled_window": reg.get("audit_labeled_window"),
            })
    n_regions = len(regions)

    obj_cols = ["九1_文件配对", "九5_时段超限", "九6_尺寸矛盾", "九9_覆盖异常"]
    obj_fail = {c: sum(1 for r in rows if r.get(c) == "不通过") for c in obj_cols}
    obj_und = {c: sum(1 for r in rows if r.get(c) == "待判定") for c in ["九3b_轮廓贴合", "九8_虚标"]}
    pi2 = _pi2_unlabeled_stats(rows)

    reg_unreasonable = sum(1 for r in regions if r.get("pass2_verdict") == "不合理")
    reg_uncertain = sum(1 for r in regions if r.get("pass2_verdict") == "不确定")
    reg_reasonable = sum(1 for r in regions if r.get("pass2_verdict") == "合理")
    n_with_pass2 = sum(
        1 for r in rows if any((x.get("pass2_verdict") for x in (r.get("regionsDetail") or [])))
    )

    metrics: list[dict[str, Any]] = []
    checks = [
        ("C01", "object", n_objects, obj_fail.get("九1_文件配对", 0), "CSV+json 配对"),
        ("C07", "object", n_objects, obj_fail.get("九5_时段超限", 0), "事件超出文件时段>1s"),
        ("C08", "object", n_objects, obj_fail.get("九6_尺寸矛盾", 0), "波形 3600 行"),
        ("C09-pi2-unlabeled", "object", n_objects, pi2["objects_with_candidates"], "可能未标 Pi2（诊断）"),
        ("C09-overlap", "object", n_objects, obj_fail.get("九9_覆盖异常", 0), "事件窗重叠/零长度/event_count"),
        ("C09-miss-confirmed", "object", n_objects, pi2["confirmed_miss_fail_objects"], "九7_漏标确认"),
        ("C13-window", "region", n_regions, reg_unreasonable, "Pass2 单窗不合理"),
        ("C13-window-und", "region", n_regions, reg_uncertain, "Pass2 单窗不确定"),
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
        "object_undetermined_counts": obj_und,
        "pi2_unlabeled": pi2,
        "ratio_metrics": metrics,
    }


def roadshow_result_row(dir_id: str, audit: dict[str, Any], **kwargs: Any) -> dict[str, str]:
    fails = audit.get("object_fail_counts") or {}
    kinds: list[str] = []
    if fails.get("九1_文件配对"):
        kinds.append("文件配对")
    if fails.get("九5_时段超限"):
        kinds.append("时段超限")
    if fails.get("九6_尺寸矛盾"):
        kinds.append("波形行数")
    if fails.get("九9_覆盖异常"):
        kinds.append("事件窗异常")
    pi2 = audit.get("pi2_unlabeled") or {}
    if pi2.get("objects_with_candidates"):
        kinds.append("可能未标Pi2(诊断)")
    if pi2.get("confirmed_miss_fail_objects"):
        kinds.append("漏标确认")
    rp = audit.get("region_pass2_counts") or {}
    if rp.get("不合理"):
        kinds.append("时间窗虚标")
    if not kinds:
        kinds.append("未发现计分缺陷" if audit.get("n_objects_with_pass2") else "规则通过·语义待跑批")

    n_obj = int(audit.get("n_objects_boxed") or 1)
    n_reg = audit.get("n_regions_labeled") or 1
    pair_f = fails.get("九1_文件配对", 0)
    ann_obj = sum(fails.get(k, 0) for k in ("九5_时段超限", "九6_尺寸矛盾", "九9_覆盖异常"))
    ann_reg = rp.get("不合理", 0)
    density_obj = (pair_f + ann_obj) / (2 * max(n_obj, 1))
    density_reg = ann_reg / max(n_reg, 1)
    total_score = max(0.0, 100.0 - 40.0 * density_obj - 60.0 * density_reg)
    suffix = dir_id.rsplit("_", 1)[-1] if "_" in dir_id else dir_id
    evidence = (
        f"对象 {n_obj}；事件窗 {n_reg}；配对失败 {pair_f}；"
        f"计分轨对象异常 {ann_obj}；窗级不合理 {ann_reg}；"
        f"可能未标Pi2(诊断) {pi2.get('objects_with_candidates', 0)} 对象；"
        f"Pass2 覆盖 {audit.get('n_objects_with_pass2', 0)}/{n_obj}"
    )
    return {
        "datasetId": "ULF_sample",
        "datasetVersion": str(kwargs.get("dataset_version", suffix)),
        "dirId": dir_id,
        "rankInDataset": str(kwargs.get("rank_in_dataset") or ""),
        "rankGlobal": str(kwargs.get("rank_global") or ""),
        "totalScore": f"{total_score:.2f}",
        "mainDefectTypes": "；".join(kinds),
        "evidence": evidence,
    }


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
    est = estimate_runtime_tokens(n_objects=audit["n_objects_boxed"], n_regions=audit["n_regions_labeled"])

    result_row = roadshow_result_row(dir_id, audit)
    result_csv = os.path.join(out_dir, f"{dir_id}_路演结果行.csv")
    with open(result_csv, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=list(result_row.keys()))
        w.writeheader()
        w.writerow(result_row)

    stats_csv = os.path.join(out_dir, f"{dir_id}_ULF审计指标.csv")
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

    ev_csv = os.path.join(out_dir, f"{dir_id}_ULF证据汇总.csv")
    evidence: list[dict[str, str]] = []
    for row in rows:
        oid = row.get("objectId") or ""
        for reg in row.get("regionsDetail") or []:
            if reg.get("pass2_verdict") == "不合理":
                evidence.append({
                    "findingId": f"{oid}#w{reg.get('region_id')}",
                    "checkId": "C13-window",
                    "ruleVersion": "physics-informed-v1",
                    "dirId": dir_id,
                    "objectId": oid,
                    "fieldPath": reg.get("fieldPath") or "",
                    "locatorType": "time_window",
                    "verdict": "fail",
                    "detail": str(reg.get("audit_labeled_window") or reg.get("pass2_verdict")),
                })
    with open(ev_csv, "w", encoding="utf-8", newline="") as handle:
        if evidence:
            w = csv.DictWriter(handle, fieldnames=list(evidence[0].keys()))
            w.writeheader()
            w.writerows(evidence)
        else:
            handle.write("findingId,checkId,ruleVersion,dirId,objectId,fieldPath,locatorType,verdict,detail\n")

    manifest = {
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "dirId": dir_id,
        "objectCsv": object_csv_path,
        "ruleVersions": {"object_qc": rows[0].get("ruleVersion") if rows else "ulf-qc-v1", "roadshow_rules": RULE_VERSIONS},
        "randomSeed": 0,
        "audit": audit,
        "runtime_estimate": est,
        "outputs": {
            "roadshow_result_row": result_csv,
            "audit_metrics_csv": stats_csv,
            "evidence_aggregate_csv": ev_csv,
        },
    }
    manifest_path = os.path.join(out_dir, f"{dir_id}_ULF目录审计包.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest


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
    ranked: list[dict[str, Any]] = []
    for row in rows:
        oid = row.get("objectId") or ""
        sev = 0
        if row.get("九5_时段超限") == "不通过":
            sev = max(sev, 90)
        if row.get("九7_漏标") == "不通过":
            sev = max(sev, 85)
        for reg in row.get("regionsDetail") or []:
            if reg.get("pass2_verdict") == "不合理":
                sev = max(sev, 80)
        if sev:
            ranked.append({"severity_rank": sev, "objectId": oid, "note": row.get("notes") or ""})
    ranked.sort(key=lambda r: -r["severity_rank"])
    sev_path = os.path.join(out_dir, f"{dir_id}_缺陷严重程度排序.csv")
    if ranked:
        with open(sev_path, "w", encoding="utf-8", newline="") as handle:
            w = csv.DictWriter(handle, fieldnames=list(ranked[0].keys()))
            w.writeheader()
            w.writerows(ranked)

    base: dict[str, Any] = {}
    if scorecard_template and os.path.isfile(scorecard_template):
        base = json.load(open(scorecard_template, encoding="utf-8"))
    card = {
        **base,
        "scorecard_id": f"SC-{dir_id}-ulf-qc-v1",
        "dataset_name": dir_id,
        "tool_version": "ulf-qc-v1+physics-informed-v1",
        "overall_quality_score": float(roadshow_result_row(dir_id, audit).get("totalScore") or 0),
        "ratio_metrics": audit.get("ratio_metrics"),
    }
    card_path = os.path.join(out_dir, "评分卡_ULF_xfnog_ulf_qc.json")
    json.dump(card, open(card_path, "w"), ensure_ascii=False, indent=2)
    return {"severity_csv": sev_path, "scorecard_json": card_path}
