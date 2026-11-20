"""Accumulated Q&A passed into v0 / v1 / v2 script generations."""

from __future__ import annotations

from typing import Any

from .rag_context import SYNTHESIS_SLICE


def bundle_dict(parts: dict[str, str]) -> dict[str, str]:
    return {k: (v or "").strip() for k, v in parts.items() if v}


def bundle_markdown(parts: dict[str, str], *, title: str = "累积辩题与回答") -> str:
    lines = [f"# {title}", ""]
    order = [
        ("task_context", "① GitHub/文档检索与处理目标"),
        ("defect_visual", "② 九类缺陷在图像上的征象"),
        ("metric_proposals", "③ 科学处理参数提议"),
        ("heuristic_geometry", "④ 掩膜/多边形/框几何启发式"),
        ("heuristic_image_defects", "⑤ 视觉相关九类（固定 3b/6/7/8/9）· 图上可能情形"),
        ("heuristic_pre_v1", "⑥ v0 试跑后 → v1 前追加问题"),
        ("heuristic_pre_v2", "⑦ v1 试跑后 → v2 前追加问题"),
    ]
    for key, label in order:
        body = parts.get(key) or ""
        if not body:
            continue
        lines.append(f"## {label}")
        lines.append("")
        lines.append(body)
        lines.append("")
    lines.extend(["## ⑧ 各阶段脚本输入策略", "", STAGE_INPUT_POLICY.strip(), ""])
    return "\n".join(lines)


def synthesis_for_script(parts: dict[str, str], *, stage: str) -> str:
    """v0 only: cumulative pre-draft Q&A. v1/v2 refine use context_for_refine_* (not full辩题)."""
    if stage != "v0":
        return ""
    keys_v0 = [
        "task_context",
        "defect_visual",
        "metric_proposals",
        "heuristic_geometry",
        "heuristic_image_defects",
    ]
    chunks: list[str] = [
        "### 阶段 v0：综合前置辩题写首版脚本",
        "目标：按 pipeline 区分处理（ULF=CSV 时间序，EPB=气辉 PNG+掩膜，AIA=日冕/磁图等）；",
        "参数可少，但须有 2–5 个可审查的 numpy/PIL（可选用 scipy）标量，并声明 Pass1→Pass2 衔接。",
    ]
    for k in keys_v0:
        if parts.get(k):
            chunks.append(f"--- {k} ---\n{parts[k][:SYNTHESIS_SLICE]}")
    return "\n\n".join(chunks)


STAGE_INPUT_POLICY = """
| 阶段 | 模型应读入 | 不应重读 |
|------|------------|----------|
| v0 | 全部前置辩题（GitHub→九类→参数→几何） | — |
| v1 | v0 试跑 JSON + v0 代码 + **教学模式全文** + heuristic_pre_v1 | 长篇 task_context/defect_visual 原文 |
| v2 | **v1 完整推理回复** + v1/v0 试跑对比 + heuristic_pre_v2 + 教学结构摘要 | v0 辩题全集 |
"""