"""Fixed nine-class subset that needs image/waveform context (debater prompts)."""

from __future__ import annotations

# 与路演九类 / C01–C13 对齐；1/2/4/5 以 JSON·配对·时间窗为主，辩题不展开
IMAGE_RELATED_DEFECTS: list[dict[str, str]] = [
    {"id": "3b", "name": "轮廓不贴结构", "rule_hint": "C03/C03b"},
    {"id": "6", "name": "行数/尺寸异常", "rule_hint": "C06 与图像尺寸/缩放"},
    {"id": "7", "name": "可能漏标亮区/强信号", "rule_hint": "C07/C09 诊断"},
    {"id": "8", "name": "待复核（噪声/伪影/难判）", "rule_hint": "C08/C13 旁证"},
    {"id": "9", "name": "虚标与覆盖异常", "rule_hint": "C09 重叠/过大框"},
]

MODALITY_IMAGE_SURFACE: dict[str, str] = {
    "AIA": "全日冕/EUV 磁图：日轮、活动区、穹顶/暗条、临边暗化、遮挡盘",
    "EPB": "鱼眼气辉：亮背景上的暗耗空条带、云缝、星迹、视场圆",
    "ULF": "地磁 Pi2 波形图/包络曲线：脉冲窗、安静段、边界截断（非像素掩膜）",
}


def format_image_defect_checklist(pipeline: str) -> str:
    lines = [
        "**固定清单**（视觉相关九类子集，禁止自创新的类别编号）：",
    ]
    for d in IMAGE_RELATED_DEFECTS:
        lines.append(f"- **{d['id']} {d['name']}**（{d['rule_hint']}）")
    surface = MODALITY_IMAGE_SURFACE.get(pipeline, "本 pipeline 图像/波形")
    lines.append(f"\n当前 pipeline={pipeline}，画面要素：{surface}")
    return "\n".join(lines)


def format_expected_answer_schema() -> str:
    return (
        "请对清单中 **每一项** 写：\n"
        "1. **图上可能情形**（本数据 1–2 条具体描述，可写「典型正常 vs 异常长什么样」）；\n"
        "2. **更像规则还是视觉**（JSON 机械 / Pass1 看图 / Pass2 裁决）；\n"
        "3. **v0 可辅助的一枚标量名**（若无则写「仅 Pass1/2」）。\n"
        "每项 ≤3 行；全文 ≤900 字；不要宽表格、不要重复九类全文定义。"
    )