"""Score v0→v1→v2 script evolution: not blind growth/shrink."""

from __future__ import annotations

import ast
import difflib
import json
import os
from typing import Any


def _read(path: str) -> str:
    return open(path, encoding="utf-8").read() if os.path.isfile(path) else ""


def _metric_keys(calibration: list[dict]) -> set[str]:
    keys: set[str] = set()
    for row in calibration or []:
        m = row.get("metrics") or {}
        if m.get("error"):
            continue
        for k in m:
            if not k.startswith("_"):
                keys.add(k)
    return keys


def _line_count(code: str) -> int:
    try:
        return len(ast.parse(code).body)
    except SyntaxError:
        return len(code.splitlines())


def _has_signature(code: str) -> bool:
    return "def auxiliary_metrics" in code and "image_path" in code


def audit_versions(workspace: str) -> dict[str, Any]:
    tags = []
    for name in sorted(os.listdir(workspace)):
        if name.startswith("auxiliary_metrics_v") and name.endswith(".py"):
            tags.append(name.replace("auxiliary_metrics_", "").replace(".py", ""))
    if not tags:
        tags = ["v0"] if os.path.isfile(os.path.join(workspace, "auxiliary_metrics_v0.py")) else []

    rows = []
    prev_keys: set[str] | None = None
    prev_lines = 0
    prev_ok = False
    for tag in sorted(tags, key=lambda t: (len(t), t)):
        code_path = os.path.join(workspace, f"auxiliary_metrics_{tag}.py")
        cal_path = os.path.join(workspace, f"calibration_{tag}.json")
        code = _read(code_path)
        cal = json.load(open(cal_path, encoding="utf-8")) if os.path.isfile(cal_path) else []
        keys = _metric_keys(cal)
        errs = sum(1 for r in cal if (r.get("metrics") or {}).get("error"))
        ok = bool(cal) and errs == 0
        lines = _line_count(code)
        sig_ok = _has_signature(code)

        added = sorted(keys - prev_keys) if prev_keys is not None else sorted(keys)
        removed = sorted(prev_keys - keys) if prev_keys is not None else []
        line_delta = lines - prev_lines if prev_lines else 0

        verdict = "ok"
        notes: list[str] = []
        if not ok:
            verdict = "regressed"
            notes.append("试跑 error")
        elif prev_ok and not added and removed and line_delta > 30:
            verdict = "bloat"
            notes.append("无 metric 增益但代码膨胀")
        elif prev_ok and removed and len(removed) > len(added) + 2:
            verdict = "over_pruned"
            notes.append("删除指标过多")
        elif prev_ok and added and not removed and line_delta < 0:
            verdict = "good_trim"
            notes.append("增指标同时精简")
        elif prev_ok and added:
            verdict = "good_add"
            notes.append("合理增补")
        if (
            tag == "v2"
            and prev_ok
            and ok
            and not added
            and not removed
            and "label_obj" not in code
            and "shapes" not in code
        ):
            verdict = "stale_v2"
            notes.append("v1 已 ok 且 v2 无新增键/未用 label 几何，应拒收或重跑启发式")
        if not sig_ok:
            verdict = "bad_sig"
            notes.append("签名丢失 label_obj")

        rows.append(
            {
                "version": tag,
                "cal_ok": ok,
                "n_errors": errs,
                "metric_keys": sorted(keys),
                "added_keys": added,
                "removed_keys": removed,
                "line_body_nodes": lines,
                "line_delta": line_delta,
                "verdict": verdict,
                "notes": notes,
            }
        )
        prev_keys = keys
        prev_lines = lines
        prev_ok = ok

    v0 = os.path.join(workspace, "auxiliary_metrics_v0.py")
    vf = os.path.join(workspace, "auxiliary_metrics.py")
    diff = ""
    if os.path.isfile(v0) and os.path.isfile(vf):
        diff = "\n".join(
            difflib.unified_diff(
                _read(v0).splitlines(),
                _read(vf).splitlines(),
                fromfile="v0",
                tofile="final",
                lineterm="",
            )
        )[:8000]

    summary = {
        "versions": rows,
        "best_verdict": next((r["verdict"] for r in reversed(rows) if r["cal_ok"]), "none"),
        "sane_evolution": all(
            r["verdict"] in ("ok", "good_add", "good_trim", "regressed")
            for r in rows[1:]
            if rows[0].get("cal_ok")
        ),
        "v0_to_final_diff_head": diff,
    }
    out = os.path.join(workspace, "EVOLUTION_AUDIT.json")
    json.dump(summary, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    md = _markdown(summary)
    open(os.path.join(workspace, "EVOLUTION_AUDIT.md"), "w", encoding="utf-8").write(md)
    return summary


def _markdown(summary: dict[str, Any]) -> str:
    lines = ["# 脚本演进审计 v0→vN", "", "| 版本 | 试跑 | 指标增 | 指标减 | 行节点Δ | 判定 |", "|---|---|---|---|---|---|"]
    for r in summary.get("versions") or []:
        lines.append(
            f"| {r['version']} | {r['cal_ok']} | {', '.join(r['added_keys'][:5]) or '—'} | "
            f"{', '.join(r['removed_keys'][:5]) or '—'} | {r['line_delta']:+d} | {r['verdict']} |"
        )
    lines.extend(["", f"**sane_evolution**: {summary.get('sane_evolution')}", ""])
    return "\n".join(lines)