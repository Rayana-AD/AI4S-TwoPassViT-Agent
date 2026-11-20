"""Debate phase prompts (mimic human dev: GitHub → defects → metrics → script → refine)."""

from __future__ import annotations

import json
from typing import Any

from .nine_defect_visual import format_expected_answer_schema, format_image_defect_checklist


NINE_CLASS_HINT = """
赛题九类完整表：1 缺文件/配对 2 字段不一致 3a 坐标越界 3b 轮廓不贴 4 类别非法 5 时间窗
6 行数/尺寸 7 可能漏标 8 待复核 9 覆盖异常。
**本阶段只谈视觉相关固定子集**：3b、6、7、8、9（1/2/4/5 属 JSON/配对，不展开）。
"""


def phase_task_context(route: dict[str, Any]) -> str:
    hits = route.get("rag_hits") or []
    primary = hits[0] if hits else {}
    ref_lines: list[str] = []
    for ref in primary.get("references") or []:
        if isinstance(ref, dict):
            ref_lines.append(f"- {ref.get('label', 'ref')}: {ref.get('url', '')}")
    refs = "\n".join(ref_lines) or "(无稳定参考；仅写 2–3 个 GitHub **搜索关键词**，勿罗列仓库)"
    archetype = route.get("archetype_id") or "unknown"
    profile = route.get("profile") or {}
    summary = profile.get("summary_text") or ""
    pt = primary.get("physics_track") or route.get("physics_track") or "n/a"
    return (
        f"pipeline={route.get('pipeline')} archetype={archetype} physics_track={pt}。\n"
        f"profile 摘要（已截断）：{summary[:450]}\n\n"
        "**语料说明**：下列 ≤2 条为 corpus 长期有效链接；GitHub 仅需 **0–2 个搜索式**，"
        "不要展开大表格、不要编造 repo 全名。\n"
        f"{refs}\n\n"
        "输出要求（严格遵守字数）：\n"
        "- ## 检索策略：≤3 条 bullet（关键词 + 对应官方文档主题）\n"
        "- ## 处理目标：≤4 条 bullet\n"
        "- ## Pass1-2 差距：≤3 条 bullet（本 modality vs 另两轨）\n"
        "全文 ≤ 700 中文字；禁止 Markdown 宽表格。"
    )


def phase_defect_visual(archetype_id: str, visual: dict[str, Any]) -> str:
    tags = visual.get("tag_counts") or {}
    samples = visual.get("samples") or []
    thumb = json.dumps(
        [{"tags": s.get("tags"), "luma": s.get("mean_luma"), "std": s.get("std_luma")} for s in samples[:3]],
        ensure_ascii=False,
    )
    return (
        f"archetype={archetype_id}；视觉探针 tags={json.dumps(tags, ensure_ascii=False)}；样本统计={thumb}。\n"
        + NINE_CLASS_HINT
        + "\n对 **3b/6/7/8/9** 各用 1 句话描述：若出现在本类图上，**肉眼/波形上可能长什么样**。"
        "另列 ≤3 条可自动化线索，标明对应九类编号。全文 ≤600 字。"
    )


def phase_metric_proposals(
    prior_text: str,
    archetype_id: str,
    *,
    teaching_block: str = "",
) -> str:
    teach = f"\n\n{teaching_block}\n\n" if teaching_block else ""
    return (
        f"上文：\n{prior_text[:4000]}\n"
        f"{teach}"
        f"针对 {archetype_id}，提议 3–5 个**可 numpy/PIL/scipy 实现的审查标量**"
        "（梯度/分位数/带通包络、径向 profile、局部对比、掩膜外扩带等）。\n"
        "每个指标 2 行：名称+物理含义；缺陷敏感性+Pass1/Pass2。\n"
        "共 3–5 个指标；全文 ≤700 字，不要宽表格。"
    )


def phase_heuristic_geometry(pipeline: str, archetype_id: str, metric_text: str) -> str:
    return (
        f"pipeline={pipeline} archetype={archetype_id}。\n"
        "请回答（将写入 v0 脚本的算子设计，尤其 **C03b 轮廓不贴** 与掩膜面积/顶点）：\n"
        "1. 若标注是 **HEK 矩形** vs **EPB 不规则多边形掩膜** vs **specialShapes**，辅助指标应如何区分（勿把 AIA 环带参数套在 EPB 暗条上）？\n"
        "2. 需要从 `label_obj` 读取哪些字段（mask.shapes / matched_events / 顶点数 / 多边形面积比例）？\n"
        "3. 在 2–4 张样本上如何检验非幻觉常数？\n"
        f"上下文：{metric_text[:1200]}\n回答 ≤500 字。"
    )


def phase_heuristic_image_defects(pipeline: str, defect_text: str) -> str:
    checklist = format_image_defect_checklist(pipeline)
    schema = format_expected_answer_schema()
    return (
        f"{checklist}\n\n"
        f"{schema}\n\n"
        f"（参考，不必复述）defect_visual 摘要：\n{defect_text[:900]}"
    )


def phase_heuristic_pre_v1(
    pipeline: str,
    archetype_id: str,
    calibration: list[dict[str, Any]],
    teaching_block: str,
) -> str:
    cal = json.dumps(calibration, ensure_ascii=False, indent=2)[:3500]
    return (
        f"v0 已在样本上试跑。pipeline={pipeline} archetype={archetype_id}。\n"
        f"教学结构：\n{teaching_block[:2500]}\n\n"
        f"试跑：\n{cal}\n\n"
        "回答以下问题（答案将驱动 **v1** 修订，不是重写 unrelated 代码）：\n"
        "1. v0 是否仍在用「套用他轨」的指标（如 EPB 误用 AIA 环带思路）？如何改？\n"
        "2. `label_obj` 是否被实际使用？若未使用，哪些 C03b/C07 会漏检？\n"
        "3. `pipeline_coverage` 是否缺 L2_pass1_context？应补哪些键进 Pass1？\n"
        "4. 列出 **v1 应新增/应删除** 的具体标量名（该增的增、该减的减）。"
    )


def phase_heuristic_pre_v2(
    pipeline: str,
    calibration: list[dict[str, Any]],
    v1_code_excerpt: str,
    *,
    v1_reasoning_excerpt: str = "",
) -> str:
    cal = json.dumps(calibration, ensure_ascii=False, indent=2)[:3500]
    reason = f"\n### v1 模型推理摘录（找自相矛盾）\n{v1_reasoning_excerpt[:4500]}\n" if v1_reasoning_excerpt else ""
    return (
        f"v1 试跑完成。pipeline={pipeline}。\n"
        f"{reason}"
        f"v1 代码摘要：\n{v1_code_excerpt[:3500]}\n\n"
        f"v1 试跑：\n{cal}\n\n"
        "回答（驱动 **v2**：读 v1 推理是否落实、是否幻觉）：\n"
        "1. v1 文字承诺的指标是否在代码/试跑键中出现？列出不一致项。\n"
        "2. 多边形面积/顶点数、暗条窄带 vs 全图统计是否按 v1 推理实现？\n"
        "3. 与 v0 试跑横向：同目录样本是否同量级？异常常数是否应删？\n"
        "4. `pass2_hint` 能否与主轨 ring/band/window 数字类型对齐？不能则写明仅 L1。\n"
        "5. v2 改动 ≤30% 行；禁止删光 v1 已通过键；若无新增几何/审查量则声明「不必出 v2」。"
    )


def phase_draft_script(
    archetype_id: str,
    pipeline: str,
    metric_text: str,
    *,
    physics_track: str = "",
    teaching_block: str = "",
    synthesis_block: str = "",
    version_tag: str = "v0",
) -> str:
    is_v0 = version_tag == "v0"
    teach = "" if is_v0 else (f"\n\n{teaching_block}\n\n" if teaching_block else "")
    synth = f"\n\n【须综合的全部辩题回答】\n{synthesis_block}\n\n" if synthesis_block else ""
    structure = (
        "v0 返回 **扁平 dict**（4–8 个 JSON 标量 + `archetype` + `annotation_hint`），"
        "不要嵌套 `pipeline_coverage`；实现 **≤100 行**，最多 1–2 个小助手函数。\n"
        if is_v0
        else (
            "**返回结构（必须）**：\n"
            "```\n"
            "{\n"
            '  "pipeline_coverage": ["L1_pre_pass1", "L2_pass1_context"],\n'
            '  "pre_pass1": { ... },\n'
            '  "pass1_context": { ... },\n'
            '  "pass2_hint": { ... },\n'
            "}\n"
            "```\n"
        )
    )
    if is_v0:
        return (
            f"{synth}"
            f"你正在写 **v0**。请生成 **独立辅助脚本**（不接替 physics_metrics），Python 3.11。\n"
            f"**modality**：pipeline={pipeline} — ULF 时 `image_path` 常为 `.csv`；EPB/AIA 为 PNG。\n"
            "允许：numpy、PIL、math、json、scipy；禁止 cv2/os/subprocess/sys。\n"
            f"def auxiliary_metrics(image_path: str, label_obj: dict | None) -> dict:\n"
            f"    \"\"\"archetype {archetype_id} / pipeline {pipeline}.\"\"\"\n\n"
            f"physics_track={physics_track or 'n/a'}。\n"
            f"{structure}"
            f"依据指标讨论：\n{metric_text[:2500]}\n\n"
            "v0 标准：参数少、分 modality、有物理含义；teaching 对齐留给 v1。\n"
            "只输出一个 ```python ... ``` 代码块，不要其他文字。"
        )
    return (
        f"{teach}{synth}"
        f"你正在写 **{version_tag}**。独立辅助脚本，Python 3.11。pipeline={pipeline} archetype={archetype_id}。\n"
        f"{structure}"
        f"依据指标：\n{metric_text[:3500]}\n"
        "只输出一个 ```python ... ``` 代码块。"
    )


def phase_draft_script_v0_compact(
    archetype_id: str,
    pipeline: str,
    metric_text: str,
    *,
    physics_track: str = "",
) -> str:
    """Second-chance v0 when first draft truncated or failed AST."""
    return (
        f"写 **v0 极简** auxiliary_metrics，pipeline={pipeline} archetype={archetype_id} "
        f"physics_track={physics_track or 'n/a'}。\n"
        "≤70 行；仅 numpy/PIL/math/json/scipy；扁平 dict 4–6 键。\n"
        "ULF=读 CSV 列 H；EPB/AIA=Image.open PNG；有 label_obj 时读 mask.shapes 点数或面积之一。\n"
        f"指标摘要：{metric_text[:1200]}\n"
        "只输出 ```python ... ```，代码必须可 ast.parse。"
    )


def phase_refine_v1(
    script_excerpt: str,
    v0_calibration: list[dict[str, Any]],
    *,
    teaching_block: str,
    heuristic_answers: str,
    pipeline: str,
    archetype_id: str,
    physics_track: str = "",
    pipeline_result: dict[str, Any] | None = None,
) -> str:
    """v1 reads v0 results + teaching only (not full pre-v0 dialogue)."""
    cal = json.dumps(v0_calibration, ensure_ascii=False, indent=2)[:4000]
    pipe = json.dumps(pipeline_result or {}, ensure_ascii=False)[:1200]
    heur = heuristic_answers[:5000] if heuristic_answers else ""
    return (
        "修订为 **v1**（teaching 后版本，应接近主轨 prepare_* 辅助层，仍独立 `auxiliary_metrics`）。\n"
        "**禁止**重读 GitHub/九类长篇辩题；仅依据 v0 试跑 + 教学模式 + 下列启发式。\n"
        f"pipeline={pipeline} archetype={archetype_id} physics_track={physics_track or 'n/a'}\n\n"
        f"### 教学模式（全文，对齐主轨分层与键名习惯）\n{teaching_block[:12000]}\n\n"
        f"### v0 试跑结果（唯一事实来源）\n{cal}\n\n"
        f"### heuristic_pre_v1 回答\n{heur}\n\n"
        f"### v0 代码（在此基础上改）\n{script_excerpt[:6000]}\n\n"
        f"可选 run_pipeline 摘要：\n{pipe}\n\n"
        "要求：\n"
        "- 落实增删键；补齐 `pipeline_coverage` / `pass1_context`（若教学要求）；\n"
        "- 有 mask.shapes / 时间窗标注时必须读 `label_obj`；\n"
        "- 可用 scipy 做梯度/滤波/分位数；禁止 cv2/os。\n"
        "先写 3–6 行修订理由（Markdown），再输出 ```python ... ``` 代码块。"
    )


def phase_refine_v2(
    script_excerpt: str,
    v0_calibration: list[dict[str, Any]],
    v1_calibration: list[dict[str, Any]],
    *,
    v1_reasoning: str,
    teaching_block: str,
    heuristic_answers: str,
    pipeline: str,
    archetype_id: str,
    pipeline_result: dict[str, Any] | None = None,
) -> str:
    """v2 audits v1 reasoning vs metrics; heuristic + lateral compare vs v0."""
    c0 = json.dumps(v0_calibration, ensure_ascii=False, indent=2)[:2500]
    c1 = json.dumps(v1_calibration, ensure_ascii=False, indent=2)[:2500]
    pipe = json.dumps(pipeline_result or {}, ensure_ascii=False)[:1000]
    heur = heuristic_answers[:5000] if heuristic_answers else ""
    return (
        "修订为 **v2**（启发式反问 + 审查 v1 推理是否落实，防幻觉）。\n"
        "必须对照 **v1 完整上轮回复**（含代码块外文字）与试跑键是否一致；"
        "与 v0 横向对比同目录样本量级。\n"
        f"pipeline={pipeline} archetype={archetype_id}\n\n"
        f"### v1 推理过程（完整）\n{v1_reasoning[:14000]}\n\n"
        f"### v1 试跑\n{c1}\n\n"
        f"### v0 试跑（横向基线）\n{c0}\n\n"
        f"### 教学结构摘要（键名/主轨对齐参考，勿重抄 physics_metrics）\n{teaching_block[:4000]}\n\n"
        f"### heuristic_pre_v2 回答\n{heur}\n\n"
        f"### v1 代码\n{script_excerpt[:5000]}\n\n"
        f"可选 run_pipeline：\n{pipe}\n\n"
        "要求：修正 v1 推理与代码矛盾；落实掩膜几何/窄带统计；≤30% 行改动；"
        "若无实质增益可只微调并保留 v1 键。\n"
        "先列「v1 问题清单」3–5 条，再输出 ```python ... ```。"
    )


def phase_refine(
    script_excerpt: str,
    calibration: list[dict[str, Any]],
    pipeline_result: dict[str, Any] | None,
    *,
    synthesis_block: str = "",
    target_version: str = "v1",
    heuristic_answers: str = "",
) -> str:
    """Legacy fallback; prefer phase_refine_v1/v2."""
    if target_version == "v1":
        return phase_refine_v1(
            script_excerpt,
            calibration,
            teaching_block="(见 TEACHING_CONTEXT.md)",
            heuristic_answers=heuristic_answers,
            pipeline="",
            archetype_id="",
        )
    cal = json.dumps(calibration, ensure_ascii=False, indent=2)[:3000]
    return phase_refine_v2(
        script_excerpt,
        calibration,
        calibration,
        v1_reasoning=synthesis_block or heuristic_answers,
        teaching_block="",
        heuristic_answers=heuristic_answers,
        pipeline="",
        archetype_id="",
        pipeline_result=pipeline_result,
    )


def phase_vision_defect_check(archetype_id: str) -> str:
    return (
        f"数据类型：{archetype_id}。对照附件样图，"
        "用一句话描述：标注框/掩膜若错位，你会在图上看到什么？"
        "再列 2 个应交给规则 JSON 而非视觉判的硬伤。"
    )