"""Build markdown demo: router + debater turns + script diffs + images."""

from __future__ import annotations

import difflib
import json
import os
import shutil
from typing import Any


def _rel(workspace: str, path: str) -> str:
    if path.startswith(workspace):
        return os.path.relpath(path, workspace)
    return path


def _load_cal(workspace: str, name: str) -> list[dict]:
    p = os.path.join(workspace, name)
    if not os.path.isfile(p):
        return []
    return json.load(open(p, encoding="utf-8"))


def _copy_assets(workspace: str, calibration: list[dict], *, limit: int = 3) -> list[str]:
    assets = os.path.join(workspace, "report_images")
    os.makedirs(assets, exist_ok=True)
    out: list[str] = []
    for i, row in enumerate(calibration[:limit]):
        src = row.get("image_path") or ""
        if not src or not os.path.isfile(src):
            continue
        dst = os.path.join(assets, f"sample_{i + 1}_{os.path.basename(src)}")
        if not os.path.isfile(dst):
            shutil.copy2(src, dst)
        out.append(dst)
    return out


def _script_diff(workspace: str, v0: str, v1: str) -> str:
    a = open(v0, encoding="utf-8").read().splitlines() if os.path.isfile(v0) else []
    b = open(v1, encoding="utf-8").read().splitlines() if os.path.isfile(v1) else []
    lines = difflib.unified_diff(a, b, fromfile=os.path.basename(v0), tofile=os.path.basename(v1), lineterm="")
    text = "\n".join(lines)
    if len(text) > 12000:
        return text[:12000] + "\n…(diff truncated)…"
    return text or "(无差异或缺少版本文件)"


def _metrics_table(cal: list[dict]) -> str:
    if not cal:
        return "_无标定样本_\n"
    keys: set[str] = set()
    for row in cal:
        m = row.get("metrics") or {}
        if not m.get("error"):
            keys.update(k for k in m if k != "error")
    keys = sorted(keys)
    lines = ["| 图 | " + " | ".join(keys) + " |", "|---|" + "|".join(["---"] * len(keys)) + "|"]
    for row in cal:
        m = row.get("metrics") or {}
        base = os.path.basename(row.get("image_path") or "")
        if m.get("error"):
            lines.append(f"| {base} | _error: {m.get('error')}_ |")
            continue
        vals = [str(m.get(k, "")) for k in keys]
        lines.append("| " + base + " | " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def build_demo_report(
    *,
    workspace: str,
    route: dict[str, Any],
    session: dict[str, Any],
    title: str = "",
) -> str:
    dir_id = session.get("dir_id") or "unknown"
    title = title or f"Router + Debater 联动：{dir_id}"
    cal_final = session.get("calibration") or _load_cal(workspace, "calibration_final.json")
    assets = _copy_assets(workspace, cal_final)

    turns = session.get("turns") or []
    turn_md = []
    for t in turns:
        ph = t.get("phase") or ""
        if ph in ("meta", "done"):
            continue
        resp = (t.get("response") or "").strip()
        cap = 12000 if ph in ("task_context", "defect_visual", "metric_proposals", "heuristic_geometry", "heuristic_image_defects", "heuristic_pre_v1", "heuristic_pre_v2") else 2500
        if len(resp) > cap:
            resp = resp[:cap] + "\n\n…(截断)…"
        usage = t.get("usage") or {}
        tok = usage.get("total_tokens", 0)
        turn_md.append(
            f"### 阶段 `{ph}`\n\n"
            f"- API tokens（本轮）: {tok} · offline={t.get('offline')}\n\n"
            f"**模型回答摘要：**\n\n{resp}\n"
        )

    v0 = os.path.join(workspace, "auxiliary_metrics_v0.py")
    v1 = os.path.join(workspace, "auxiliary_metrics_v1.py")
    v2 = os.path.join(workspace, "auxiliary_metrics_v2.py")
    final = os.path.join(workspace, "auxiliary_metrics.py")

    diff01 = _script_diff(workspace, v0, v1 if os.path.isfile(v1) else final)
    diff12 = ""
    if os.path.isfile(v1) and os.path.isfile(v2):
        diff12 = _script_diff(workspace, v1, v2)
    elif os.path.isfile(v1):
        diff12 = _script_diff(workspace, v1, final)

    img_md = ""
    for p in assets:
        img_md += f"\n![{os.path.basename(p)}]({_rel(workspace, p)})\n"

    cal_v0 = _load_cal(workspace, "calibration_v0.json")
    cal_v1 = _load_cal(workspace, "calibration_v1.json")
    cal_v2 = _load_cal(workspace, "calibration_v2.json")

    best = session.get("best_script_version") or "v0"
    bundle_path = os.path.join(workspace, "DIALOGUE_BUNDLE.md")
    bundle_note = ""
    if os.path.isfile(bundle_path):
        bundle_note = (
            "\n## 0. 辩题与分阶段输入\n\n"
            f"前置辩题全集：**[DIALOGUE_BUNDLE.md]({_rel(workspace, bundle_path)})**。\n"
            "- **v0**：综合前置辩题写首版；\n"
            "- **v1**：只读 v0 试跑 + `TEACHING_CONTEXT` + `heuristic_pre_v1`（见 `V1_REASONING.md` 为 v1 修订推理）；\n"
            "- **v2**：读 v1 完整推理 + v0/v1 试跑对比 + `heuristic_pre_v2`。\n"
        )
    md = f"""# {title}

> **最终采用脚本版本**：`{best}`（若 refine 引入 cv2/os 等被沙箱拒绝，会自动回退到试跑通过的最高分版本）
{bundle_note}
## 1. dataset_router 结论

| 字段 | 值 |
|------|-----|
| pipeline | {route.get('pipeline')} |
| archetype_id | {route.get('archetype_id')} |
| confidence | {route.get('confidence')} |
| layout | {route.get('layout')} |

**rationale：** {'; '.join(route.get('rationale') or [])}

**RAG 首条：** {(route.get('rag_hits') or [{}])[0].get('title', 'n/a')}

## 2. 辩题轮次（DeepSeek 实调）

{chr(10).join(turn_md)}

## 3. 样图与最终标量

{img_md}

### 最终试跑表

{_metrics_table(cal_final)}

## 4. 脚本迭代差异

### v0 → v1

```diff
{diff01}
```

### v1 → v2（若有）

```diff
{diff12 or '(单轮 refine 或无 v2)'}
```

### 各轮标量对比（键级）

| 版本 | 样本数 | 有 error 的条数 |
|------|--------|----------------|
| v0 | {len(cal_v0)} | {sum(1 for r in cal_v0 if (r.get('metrics') or {}).get('error'))} |
| v1 | {len(cal_v1)} | {sum(1 for r in cal_v1 if (r.get('metrics') or {}).get('error'))} |
| v2 | {len(cal_v2)} | {sum(1 for r in cal_v2 if (r.get('metrics') or {}).get('error'))} |

## 5. Pass1 衔接试跑（`DEBATER_AUXILIARY_SCRIPT` + prepare_*，无 API）

```json
{json.dumps(session.get("pass1_hook_dry_run") or {}, ensure_ascii=False, indent=2)[:2000]}
```

## 6. 脚本演进审计（v0–vN 该增增、该减减）

详见 [`EVOLUTION_AUDIT.md`](EVOLUTION_AUDIT.md) · sane={session.get("evolution_audit", {}).get("sane_evolution")}

## 7. 如何衔接 Pass1/2（不替代）

- `auxiliary_metrics.jsonl` 可作为 Pass1 附加上下文；Pass2 仍以 `physics_metrics` 数字为准。
- 产物目录：`{workspace}`

---
生成自 `scientific_debater.demo_report` · session ok={session.get('ok')}
"""
    out_path = os.path.join(workspace, "DEBATER_DEMO.md")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(md)
    return out_path