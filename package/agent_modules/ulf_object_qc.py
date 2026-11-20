"""Per-object ULF QC: nine defect buckets + windowsDetail (Pass1/Pass2 physics-informed)."""

from __future__ import annotations

import json
import os
from typing import Any

from audits import FAIL, NA, PASS, REVIEW, UNDECIDED, json_consistency, waveform_check_items, waveform_window
from physics_metrics import (
    load_ulf_h_csv,
    ulf_merge_threshold_proposal,
    ulf_pass2_audit_from_thresholds,
    ulf_pi2_metrics,
    ulf_threshold_calibration,
)

RULE_VERSION = "ulf-qc-v2"

# 九7 诊断：全小时包络 heuristic（脚本轨；计分 fail 仍须 Pass2 miss_verdicts「漏标」）
_POR_MISS_CANDIDATE = 2.8
_POR_MISS_HEURISTIC = 3.0


def _status_from_audit_item(item: dict | None) -> str:
    if not item:
        return NA
    return item.get("status") or UNDECIDED


def _worst(statuses: list[str]) -> str:
    if any(s == FAIL for s in statuses):
        return FAIL
    if any(s in {UNDECIDED, "待复核", REVIEW} for s in statuses):
        return UNDECIDED
    if statuses and all(s == NA for s in statuses):
        return NA
    return PASS


def _find_check(findings: list[dict], name: str) -> dict | None:
    for f in findings:
        if f.get("check") == name:
            return f
    return None


def _ulf_window_overlap_fail(spans: list[dict]) -> tuple[str, str]:
    valid = [s for s in spans if s.get("i0") is not None]
    if not valid:
        return NA, "无时间窗"
    notes: list[str] = []
    fail = False
    for s in valid:
        if (int(s["i1"]) - int(s["i0"])) <= 1:
            fail = True
            notes.append(f"零/近零长度窗 i={s['i0']}-{s['i1']}")
    for i, a in enumerate(valid):
        for b in valid[i + 1 :]:
            i0a, i1a = int(a["i0"]), int(a["i1"])
            i0b, i1b = int(b["i0"]), int(b["i1"])
            if i0a < i1b and i0b < i1a:
                fail = True
                notes.append(f"窗重叠 {i0a}-{i1a} vs {i0b}-{i1b}")
    if fail:
        return FAIL, "；".join(notes[:4])
    return PASS, "事件窗无重叠且长度>1s"


def _physics_agent_record(row: dict) -> dict:
    agent = dict(row)
    p2 = agent.get("pass2") or {}
    if p2.get("window_audit") and not agent.get("window_audit"):
        agent["window_audit"] = p2["window_audit"]
    return agent


def _agent_confirms_miss(agent: dict | None) -> bool:
    """Pass2 miss_verdicts「漏标」才计九7 漏标 fail；脚本 likely_miss 仅作候选。"""
    if not agent:
        return False
    p2 = (agent.get("pass2") or {}).get("parsed") or {}
    for m in p2.get("miss_verdicts") or []:
        if m.get("verdict") == "漏标":
            return True
    return False


def _annotation_metadata_flags(uea: dict) -> list[str]:
    events = uea.get("matched_events") or []
    flags: list[str] = []
    if uea.get("has_events") and not events:
        flags.append("has_events_true_but_empty_matched_events")
    if uea.get("has_events") is False and events:
        flags.append("has_events_false_but_nonempty_matched_events")
    return flags


def _resolve_window_audit(
    csv_path: str,
    label_path: str,
    *,
    agent: dict | None,
    agent_record: dict | None,
    data_exists: bool,
    run_offline_window_audit: bool,
) -> dict[str, Any]:
    window_audit: dict[str, Any] = {}
    if agent:
        window_audit = dict(agent.get("window_audit") or {})
        if not window_audit and (agent.get("pass2") or {}).get("window_audit"):
            window_audit = dict((agent.get("pass2") or {}).get("window_audit") or {})
    has_miss = bool(window_audit.get("miss_burst_audit"))
    has_labeled = bool(window_audit.get("labeled_window_audit"))
    if (has_miss or has_labeled) or not run_offline_window_audit or not data_exists:
        return window_audit

    source = agent or agent_record or {}
    cal = ((source.get("metrics") or {}).get("threshold_calibration"))
    if not (isinstance(cal, dict) and cal.get("valid")):
        h = load_ulf_h_csv(csv_path)
        if h.size >= 100:
            cal = ulf_threshold_calibration(h, label_path=label_path)
    tp = None
    pass1_parsed = ((source.get("pass1") or {}).get("parsed")) if source else None
    if pass1_parsed:
        tp = ulf_merge_threshold_proposal(
            pass1_parsed,
            cal if isinstance(cal, dict) and cal.get("valid") else None,
        )
    elif isinstance(cal, dict) and cal.get("valid"):
        tp = ulf_merge_threshold_proposal(None, cal)
    if tp:
        computed = ulf_pass2_audit_from_thresholds(csv_path, label_path, tp)
        window_audit = {**computed, **window_audit}
    return window_audit


def _peak_over_quiet(
    csv_path: str,
    agent: dict | None,
    agent_record: dict | None,
    data_exists: bool,
) -> float | None:
    for source in (agent, agent_record):
        if not source:
            continue
        por = (source.get("metrics") or {}).get("peak_over_quiet")
        if por is not None:
            try:
                return float(por)
            except (TypeError, ValueError):
                pass
    if not data_exists:
        return None
    h = load_ulf_h_csv(csv_path)
    if h.size < 100:
        return None
    por = ulf_pi2_metrics(h).get("peak_over_quiet")
    return float(por) if por is not None else None


def _build_regions_detail(
    label_path: str,
    agent: dict | None,
    window_audit: dict | None,
) -> list[dict[str, Any]]:
    obj = json.load(open(label_path, encoding="utf-8"))
    events = (obj.get("ulf_event_annotation") or {}).get("matched_events") or []
    wa_rows = {r.get("region_id"): r for r in (window_audit or {}).get("labeled_window_audit") or []}
    eval_regions = ((agent or {}).get("evaluation") or {}).get("per_region") or []
    p2_by_id = {r.get("region_id"): r for r in eval_regions}
    p2parsed = ((agent or {}).get("pass2") or {}).get("parsed") or {}
    for r in p2parsed.get("regions") or []:
        rid = r.get("region_id")
        if rid is not None and rid not in p2_by_id:
            p2_by_id[rid] = r
    p1_norm = (((agent or {}).get("pass1") or {}).get("normalized") or {}).get("per_region") or []
    p1_by_id = {r.get("region_id"): r for r in p1_norm}
    labeled = ((agent or {}).get("metrics") or {}).get("labeled_regions") or []
    if not labeled:
        from audits import window_spans

        n = 3600
        spans = window_spans(obj, n)
        labeled = [
            {"region_id": i, "i0": s.get("i0"), "i1": s.get("i1")}
            for i, s in enumerate(spans)
            if s.get("i0") is not None
        ]

    details: list[dict[str, Any]] = []
    for row in labeled:
        rid = row.get("region_id")
        if rid is None:
            continue
        ev = events[rid] if isinstance(rid, int) and rid < len(events) else {}
        wa = wa_rows.get(rid) or {}
        p2 = p2_by_id.get(rid) or {}
        p1 = p1_by_id.get(rid) or {}
        details.append({
            "region_id": rid,
            "caption": row.get("caption") or f"window_{row.get('i0')}_{row.get('i1')}",
            "fieldPath": f"ulf_event_annotation.matched_events[{rid}]",
            "i0": wa.get("i0") or row.get("i0"),
            "i1": wa.get("i1") or row.get("i1"),
            "start_dt": ev.get("start_dt") or wa.get("start_dt"),
            "end_dt": ev.get("end_dt") or wa.get("end_dt"),
            "duration_s": wa.get("duration_s"),
            "mechanical": "none",
            "pass1_confidence": p1.get("confidence_plausible"),
            "pass2_verdict": p2.get("verdict") or "",
            "audit_labeled_window": wa.get("audit_labeled_window"),
            "peak_over_quiet_p30": wa.get("peak_over_quiet_p30"),
            "window_audit": wa if wa else None,
        })
    return details


def qc_ulf_object(
    dir_id: str,
    csv_path: str,
    label_path: str,
    *,
    agent_record: dict | None = None,
    run_offline_window_audit: bool = True,
) -> dict[str, Any]:
    object_id = os.path.basename(csv_path)
    obj = json.load(open(label_path, encoding="utf-8"))
    data_exists = os.path.isfile(csv_path)
    rule_findings = json_consistency(obj, data_exists)
    by_check = {f["check"]: f for f in rule_findings}

    d1 = _status_from_audit_item(by_check.get("引用文件"))
    d2 = PASS if d1 == PASS else FAIL if d1 == FAIL else UNDECIDED
    d3a = NA
    d4 = NA

    d5 = _status_from_audit_item(by_check.get("事件时间范围"))

    wf = waveform_window(csv_path, obj) if data_exists else {"length_status": NA, "window_status": NA, "spans": []}
    wf_items = {i["check"]: i for i in waveform_check_items(wf)} if data_exists else {}
    d6 = _status_from_audit_item(wf_items.get("波形行数"))

    agent = _physics_agent_record(agent_record) if agent_record else None
    uea = obj.get("ulf_event_annotation") or {}
    window_audit = _resolve_window_audit(
        csv_path,
        label_path,
        agent=agent,
        agent_record=agent_record,
        data_exists=data_exists,
        run_offline_window_audit=run_offline_window_audit,
    )

    spans = wf.get("spans") or []
    d9, d9_note = _ulf_window_overlap_fail(spans)
    ec = by_check.get("event_count")
    if ec and ec.get("status") == FAIL:
        d9 = FAIL
    he = by_check.get("has_events一致")
    if he and he.get("status") == FAIL:
        d9 = FAIL
        detail = he.get("detail") or "has_events 与 matched_events 不一致"
        d9_note = detail if d9_note in {NA, "无时间窗"} else f"{d9_note}；{detail}"

    miss_audit = window_audit.get("miss_burst_audit") or []
    likely_miss = [m for m in miss_audit if m.get("audit_miss_label") == "likely_miss"]
    has_ev = bool(uea.get("has_events")) and (uea.get("matched_events") or [])
    por = _peak_over_quiet(csv_path, agent, agent_record, data_exists)
    por_heuristic = bool(not has_ev and por is not None and por > _POR_MISS_CANDIDATE)
    confirmed_miss = _agent_confirms_miss(agent)
    if not data_exists:
        d7 = NA
    elif confirmed_miss:
        d7 = FAIL
    elif likely_miss or por_heuristic:
        d7 = "有候选"
    else:
        d7 = "无"
    d7_miss_scored = FAIL if confirmed_miss else NA

    regions = _build_regions_detail(label_path, agent, window_audit)
    n_regions = len(regions)

    d3b = NA
    d8 = NA
    coarse = wf_items.get("时间窗峰谷")
    if n_regions == 0 and not uea.get("has_events"):
        d3b = NA
        d8 = NA
    elif agent and ((agent.get("pass2") or {}).get("parsed")):
        per = ((agent.get("evaluation") or {}).get("per_region") or [])
        verbs = [r.get("verdict") for r in per]
        if any(v == "不合理" for v in verbs):
            d3b = FAIL
            d8 = FAIL
        elif any(v == "不确定" for v in verbs):
            d3b = UNDECIDED
        elif verbs:
            d3b = PASS
        else:
            d3b = UNDECIDED
    elif coarse and coarse.get("status") == FAIL:
        d3b = REVIEW
    else:
        d3b = UNDECIDED

    if not has_ev and por and por > 3.5 and not likely_miss:
        d8 = UNDECIDED

    meta = list(dict.fromkeys(
        _annotation_metadata_flags(uea)
        + list(window_audit.get("metadata_flags") or [])
    ))
    applicable = [s for s in (d1, d2, d5, d6, d8, d9, d7_miss_scored) if s != NA]
    if d3b in (FAIL, UNDECIDED, REVIEW):
        applicable.append(d3b if d3b != REVIEW else UNDECIDED)
    object_overall = _worst(applicable) if applicable else NA

    scored = [s for s in (d1, d2, d5, d6, d9, d7_miss_scored) if s != NA]
    if d3b == FAIL:
        scored.append(d3b)
    if d8 == FAIL:
        scored.append(d8)
    object_overall_scored = _worst(scored) if scored else NA

    return {
        "dirId": dir_id,
        "objectId": object_id,
        "labelFile": os.path.basename(label_path),
        "ruleVersion": RULE_VERSION,
        "objectOverall": object_overall,
        "objectOverallScored": object_overall_scored,
        "九1_文件配对": d1,
        "九2_孤儿标注": d2,
        "九3a_像素越界": d3a,
        "九3b_轮廓贴合": d3b,
        "九4_类别非法": d4 if d4 != NA else NA,
        "九5_时段超限": d5,
        "九6_尺寸矛盾": d6,
        "九7_可能未标Pi2": d7,
        "九7_漏标": d7_miss_scored,
        "九8_虚标": d8,
        "九9_覆盖异常": d9,
        "missHeuristicLikely": len(likely_miss),
        "missConfirmed": confirmed_miss,
        "nRegions": n_regions,
        "regionsDetail": regions,
        "waveformAudit": {
            "rows": wf.get("rows"),
            "length_status": wf.get("length_status"),
            "window_status": wf.get("window_status"),
            "detail": wf.get("detail"),
            "d9_note": d9_note,
        },
        "windowAudit": window_audit,
        "missLabel": {
            "miss_burst_audit": miss_audit,
            "policy": "可能未标Pi2=诊断轨；须 Pass2 miss_verdicts 确认才计漏标 fail",
            "screen": {
                "peak_over_quiet": round(por, 4) if por is not None else None,
                "por_heuristic_candidate": por_heuristic,
                "n_likely_miss_bursts": len(likely_miss),
                "por_threshold_candidate": _POR_MISS_CANDIDATE,
            },
        },
        "metadataFlags": meta,
        "notes": _notes_summary(d1, d5, d6, d3b, d7, d8, d9, meta),
    }


def _notes_summary(d1, d5, d6, d3b, d7, d8, d9, meta) -> str:
    parts: list[str] = []
    if d1 == FAIL:
        parts.append("CSV/JSON 配对失败")
    if d5 == FAIL:
        parts.append("事件超出文件时段")
    if d6 == FAIL:
        parts.append("波形行数≠3600")
    if d9 == FAIL:
        if any("has_events" in f for f in meta):
            parts.append("has_events与事件列表不一致")
        else:
            parts.append("事件窗重叠或零长度/event_count")
    if d7 == "有候选":
        parts.append("可能未标 Pi2(诊断)")
    if d8 == FAIL:
        parts.append("虚标/窗内 Pi2 弱")
    if d3b == UNDECIDED:
        parts.append("时间窗待 Pass1/Pass2")
    if meta:
        parts.append("元数据:" + ",".join(meta[:2]))
    return "；".join(parts) if parts else "规则项通过或待跑批"


def row_for_csv(payload: dict[str, Any]) -> dict[str, str]:
    json_keys = ("regionsDetail", "waveformAudit", "windowAudit", "missLabel", "metadataFlags")
    out = {k: v for k, v in payload.items() if k not in json_keys}
    for key in json_keys:
        out[key] = json.dumps(payload.get(key) or ([] if key == "regionsDetail" else {}), ensure_ascii=False)
    return out


CSV_COLUMNS = [
    "dirId", "objectId", "labelFile", "ruleVersion", "objectOverall", "objectOverallScored",
    "九1_文件配对", "九2_孤儿标注", "九3a_像素越界", "九3b_轮廓贴合", "九4_类别非法",
    "九5_时段超限", "九6_尺寸矛盾", "九7_可能未标Pi2", "九7_漏标", "九8_虚标", "九9_覆盖异常",
    "missHeuristicLikely", "missConfirmed", "nRegions", "regionsDetail", "waveformAudit",
    "windowAudit", "missLabel", "metadataFlags", "notes",
]
