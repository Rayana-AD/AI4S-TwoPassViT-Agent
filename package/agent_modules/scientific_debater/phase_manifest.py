"""Canonical debater phase list (for docs + UI)."""

from __future__ import annotations

from typing import TypedDict


class DebatePhaseSpec(TypedDict):
    id: str
    role: str
    model: str
    user_question_zh: str
    model_deliverable: str
    feeds_next: str


DEBATE_PHASES: list[DebatePhaseSpec] = [
    {
        "id": "task_context",
        "role": "text",
        "model": "deepseek-v4-pro（MODEL_TEXT_NAME）",
        "user_question_zh": (
            "根据 dataset_router 的 archetype、RAG 参考链接与 profile 摘要："
            "应去 GitHub/官方文档检索哪些关键词？处理目标是什么？"
            "与现有 AIA/EPB/ULF Pass1-2 主轨差在哪？"
        ),
        "model_deliverable": "Markdown：## 检索策略 ## 处理目标 ## 与 Pass1-2 差距",
        "feeds_next": "defect_visual / metric_proposals",
    },
    {
        "id": "defect_visual",
        "role": "vision+text",
        "model": "deepseek-flash（样图）+ v4-pro 备选纯文本",
        "user_question_zh": (
            "九类缺陷在本类图像（伪彩极光/日冕遮挡盘/磁图网络/气辉暗条）上各可能呈现什么？"
            "Top5 可自动化图像线索？标注框错位时肉眼可见什么？"
            "哪 2 类硬伤必须 JSON 规则判、不要视觉越权？"
        ),
        "model_deliverable": "缺陷—图像征象对照 + 视觉/规则分工",
        "feeds_next": "metric_proposals",
    },
    {
        "id": "metric_proposals",
        "role": "text",
        "model": "deepseek-v4-pro",
        "user_question_zh": (
            "提议 3–5 个 numpy/PIL 可算的标量（亮度梯度、径向 profile、遮挡盘半径、"
            "盐胡椒噪声、条带对比等）：物理含义、缺陷敏感性、干净版标定法；"
            "指标表：进 Pass1 还是仅 Pass2 校验。"
        ),
        "model_deliverable": "指标表 + 阈值标定建议",
        "feeds_next": "draft_script",
    },
    {
        "id": "draft_script",
        "role": "text",
        "model": "deepseek-v4-pro",
        "user_question_zh": (
            "写出 auxiliary_metrics(image_path, label_obj) 辅助脚本（不接替 physics_metrics）；"
            "仅 numpy/PIL/math/json；输出 radial_gradient、local_contrast 等可序列化键。"
        ),
        "model_deliverable": "```python``` 代码块 → 沙箱 v0",
        "feeds_next": "calibrate_v0",
    },
    {
        "id": "calibrate_v0",
        "role": "local",
        "model": "（无 API）",
        "user_question_zh": "在目录抽样 2–4 张 PNG 上试跑 v0，记录标量或错误。",
        "model_deliverable": "auxiliary_metrics_v0.py + calibration_v0.json",
        "feeds_next": "refine_1",
    },
    {
        "id": "refine_n",
        "role": "text",
        "model": "deepseek-v4-pro",
        "user_question_zh": (
            "试跑结果（及可选 run_pipeline 规则轨摘要）是否爆炸/全零/与九类冲突？"
            "修订 auxiliary_metrics，保持函数签名；可多轮直到稳定。"
        ),
        "model_deliverable": "v1/v2/… 脚本 + 每轮 calibration_vN.json",
        "feeds_next": "calibrate_vN 或 done",
    },
    {
        "id": "linkage_review",
        "role": "text",
        "model": "可选 v4-pro",
        "user_question_zh": (
            "对照 router 的 pipeline/archetype 与各轮脚本差异："
            "辅助指标如何衔接 Pass1 上下文（仍不替代 Pass2 引数终裁）？"
        ),
        "model_deliverable": "联动检测报告（图文）",
        "feeds_next": "experiments 归档",
    },
]