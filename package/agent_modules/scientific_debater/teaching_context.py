"""Build gated teaching prompt from frozen deep-test spine (structure only)."""

from __future__ import annotations

import json
import os
from typing import Any

_CORPUS = os.path.join(os.path.dirname(__file__), "corpus", "teaching_spine.json")


def _load_corpus() -> dict[str, Any]:
    return json.load(open(_CORPUS, encoding="utf-8"))


def _pipeline_matches(case: dict[str, Any], pipeline: str) -> bool:
    return str(case.get("pipeline") or "").upper() == str(pipeline or "").upper()


def _archetype_far(case: dict[str, Any], archetype_id: str, do_not: list[str]) -> bool:
    """If any do_not_copy hint appears related to archetype, treat as 'far' → weaken teaching."""
    aid = (archetype_id or "").lower()
    text = " ".join(do_not).lower()
    if "dmsp" in aid or "ssusi" in aid:
        return "dmsp" in text or "specialshapes" in text
    if "cme" in aid or "lasco" in aid:
        return "cme" in text or "日冕" in text
    if "hmi" in aid:
        return "hek" in text and "special" in text
    return False


def build_teaching_block(
    *,
    pipeline: str,
    archetype_id: str,
    dir_id: str = "",
    mode: str = "auto",
) -> str:
    """
    mode:
      - auto: same pipeline + not far → layered deep case; else meta + one-liner analogy
      - meta_only: never inject deep case symbols (ablation / 纯新仪器)
      - spine_full: always inject layer diagram, still gated do_not_copy
    """
    corpus = _load_corpus()
    if mode == "meta_only":
        return _meta_only(corpus)

    cases = corpus.get("deep_cases") or []
    picked = [c for c in cases if _pipeline_matches(c, pipeline)]
    far = any(_archetype_far(c, archetype_id, c.get("do_not_copy_when") or []) for c in picked)

    lines = [
        "## 教学模式（三深测结构参考 — 非代码抄袭）",
        corpus.get("frozen_note", ""),
        "",
        "主链分层（所有数据共用思想）：",
    ]
    for layer in corpus.get("pipeline_layers") or []:
        lines.append(f"- **{layer.get('layer')}**：{layer.get('role')}")

    contract = corpus.get("debater_contract") or {}
    lines.extend(
        [
            "",
            "### debater 契约（与深测主库区分）",
            f"- 你只写：`{contract.get('single_entry')}`",
            f"- 不是 fork：`{', '.join(contract.get('not_a_fork_of') or [])}`",
            f"- 衔接方式：{contract.get('feeds')}",
            "",
        ]
    )

    if mode == "spine_full" or (picked and not far and mode == "auto"):
        for case in picked:
            lines.append(f"### 结构范例 `{case.get('id')}`（pipeline={case.get('pipeline')}）")
            lines.append("**当时为何加脚本：** " + "；".join(case.get("problem_that_triggered_scripts") or []))
            for block, title in [
                ("auxiliary_before_pass1", "Pass1 前（本地+叠加）"),
                ("between_pass1_pass2", "Pass1–2 之间（确定性审计）"),
                ("after_pass2", "Pass2 后（目录/CSV 政策）"),
            ]:
                items = case.get(block) or []
                if not items:
                    continue
                lines.append(f"**{title}：**")
                for it in items:
                    lines.append(
                        f"  - `{it.get('symbol')}` · {it.get('teach')} （契约：{it.get('contract')}）"
                    )
            dont = case.get("do_not_copy_when") or []
            if dont:
                lines.append("**当前 archetype 若属于以下情形 → 勿抄符号/常数，只抄分层：**")
                for d in dont:
                    lines.append(f"  - {d}")
    else:
        lines.append("### 当前数据与深测案例 **不同族** → 仅吸收分层与契约")
        analogies = []
        for case in cases:
            one = case.get("analogy_for_new_data_one_liner")
            if one:
                analogies.append(f"- ({case.get('id')}) {one}")
        lines.extend(analogies[:3])
        lines.append(
            "\n请根据 **本目录** archetype/RAG/视觉探针 自主命名指标；"
            "禁止从范例粘贴 `ring_audit`/`band_audit`/`window_audit` 实现。"
        )

    if dir_id:
        lines.append(f"\n（dir_id={dir_id} · archetype={archetype_id} · pipeline={pipeline} · far={far}）")
    return "\n".join(lines)


def _meta_only(corpus: dict[str, Any]) -> str:
    lines = ["## 教学模式（仅元结构，无深测符号）", ""]
    for layer in corpus.get("pipeline_layers") or []:
        if "debater" in str(layer.get("layer")).lower() or "L*" in str(layer.get("layer")):
            lines.append(f"- {layer.get('layer')}: {layer.get('role')}")
    lines.append("- 写一个 sandbox 内 `auxiliary_metrics`；Pass1/2 主轨保持不变。")
    return "\n".join(lines)