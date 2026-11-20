"""Unified scientific task prompts for physics-informed VLM inspection."""

AIA_TASK = """\
任务：SDO/AIA 活动区（AR）dataset 标注质量检验。图上彩色线为 JSON **五点闭合**多边形（常为旋转矩形），不是 EPB 掩膜。
"""

PASS1_TASK = """\
【Pass1 — 理解与逐条初判（必须覆盖全部 region_id）】
1. 先写 task_understood：一句话说明本图要检验什么（AR/EPB/ULF 窗等）。
2. metrics.labeled_regions 有几条，regions 数组就必须有几条，且 region_id 一一对应；多标注图禁止只给整图一个结论。
3. 对每条 region_id 仅基于**当前叠加图上的该条轮廓**给出：
   - structure_guess、confidence_plausible（0~1）、reason。
4. **漏标初筛**：阅读 metrics.missed_label_candidates.candidates（AIA：标注区外增亮候选；EPB：标注区外**暗条带/残差凹陷**候选，尺度锚定本图 mask 面积中位数）。
   - 在图像上核对：该处是否有应标 AR/亮斑或 EPB 暗条却未画 JSON 框/掩膜；
   - 输出 miss_candidates[]：每条 candidate_id、confidence_missed（0~1，高=像漏标）、一句 reason。
   - 无可靠候选时 miss_candidates 可为空数组。
5. Pass1 不做 ring 计算；不确定时 confidence 应偏低。
6. metrics.mechanical_coverage_audit：IoU≥0.65 或 bbox 宽高≤0 已机械 fail（覆盖过多/不足），**勿推翻**；image_summary 可汇总冗余框。
"""

PASS2_TASK = """\
【Pass2 — ring_audit + gradient_audit + scale_audit + 漏标】
AIA：ring_audit 为 0.5d–1d、1d–2d 外环；gradient_audit；scale_audit 含 d_ratio；saturation_audit 标显示饱和。
EPB（已标 mask）：ring_audit 实为 **band_audit**（多边形外固定像素环带 depletion，**不用 0.5d 小环**）；scale_audit 以 **area_ratio_to_median** 为主。
你必须：
1. 逐条 region_id 引用 ring 的 contrast、audit_0.5_1d；weak 时引用 gradient；**并引用 scale_audit**（过大框 oversized 可仍贴合但 scale_plausible=false）。
2. overlap_audit.redundant_label_flags：嵌套/同 AR 重复框 → 在 reason 或 summary 标注「冗余标注」，**不等同于单框不合理**；是否算虚标见 image_summary.redundant_label_note。
3. miss_ring_audit：AIA 用 ring/gradient；**EPB 用 band_audit（depletion + area_ratio_to_median）**。likely_miss 且 pass1 confidence_missed≥0.55 → miss_verdicts「漏标」。
4. audit_composite_hint 规则（**勿单凭 audit_0.5_1d=supports_brighter_core 判合理**）：
   - weak_far_ring_but_local_boundary_supported 且 pass1≥0.55 → 可判合理（须 gradient/径向数值）。
   - ring_and_boundary_consistent → ring 与 gradient 均支持，可倾向合理。
   - ring_bright_but_flat_boundary / ring_bright_but_saturation_no_boundary → 环对比支持但**无边界台阶或饱和顶格**；须结合 scale_audit：small_vs_median/undersized_fragment 且 saturated_core_likely=true → 倾向**不合理**（饱和碎片/虚标/应扩框）；若 gradient 为 supports_radial_envelope 且 scale 合理可改不确定。
5. reason 须含至少两个具体数值。
"""

EPB_TASK = """\
任务：630nm EPB 掩膜检验。Pass2 对已标 region 仍可用 ring_audit(depletion)；**漏标候选不用 AIA 环带**。
漏标：metrics.missed_label_candidates 为规则轨 **暗条连通+扩散轮廓**（band_audit：depletion_sigma、area_ratio_to_median_label、boundary_gradient）；Pass1 目视；Pass2 读 miss_ring_audit.band_audit 定 miss_verdicts。同图预期 0–2 条候选。
"""

ULF_TASK = """\
任务：ULF 水平分量 H 上 Pi2（约 6.7–25 mHz，周期 40–150 s）时间窗检验。叠加图为 H、Pi2 带通与包络；红色竖线为 JSON 标注时间窗。
科学要点：检验「窗内是否有 Pi2 式脉冲/振荡增强」，不要求 D/Z 同相；T 列通常不参与本流水线。
"""

ULF_PASS1_TASK = """\
【ULF Pass1 — 滑动反估 + 置信区间 + 模型终估（不写 pass2_verdict）】
1. **先读** metrics.threshold_calibration：脚本已由自适应滑动窗（峰间距定 window/stride、含小时尾窗覆盖）反估各阈值 estimate 与 ci_low~ci_high；并含 hour_coverage_fraction、peak_t 定位、labeled_window_split（若有标注）。
2. 读 metrics.sliding_window_scan.top_peaks（window_s/stride_s 见 scan_summary，**非固定常数**）。
3. 结合波形图与 Pi2 文献（40–150 s），输出 **threshold_proposal**（Pass1 终估，供 Pass2 复算）：
   各字段应落在 calibration 的 CI 内或 **explicit 偏离**；附 calibration_agreement（ agree|adjust|reject 之一 + 一句理由）。
4. sliding_assessment：引用 peak_t / boundary（start|end|interior）标注 pi2_burst_candidate|quiet|uncertain。
5. missed_label_candidates（包络峰 + 滑动窗）：candidate_id 对齐；confidence_missed + reason；**不**写「漏标」终判。
6. regions[] 覆盖全部 region_id。
"""

ULF_PASS2_TASK = """\
【ULF Pass2 — 代入 Pass1 终估阈值复算 + 判断】
脚本已将 Pass1 threshold_proposal 与 calibration 缺项合并为 threshold_proposal_merged，并据此计算 window_audit（与 Pass1 同参复检一遍）。
你必须：
1. 逐 region_id 引用 labeled_window_audit；对照 Pass1 regions 与 calibration CI。
2. miss_verdicts 引用 miss_burst_audit；与 Pass1 miss_candidates 一致或说明变更。
3. 若 window_audit.thresholds_applied.provenance 含 calibration_estimate，在 reason 中注明 Pass1 是否未覆盖该字段。
4. reason 须含 ≥2 个 window_audit 数值；禁止引入 Pass1 未出现且未在 calibration 中的新常数。
"""

ULF_PASS1_FORMAT = (
    'ULF 额外字段：'
    '"threshold_proposal":{"peak_over_quiet_min":浮点,"in_window_ratio_min":浮点,'
    '"min_burst_duration_s":整数,"max_burst_duration_s":整数,"merge_gap_s":整数,'
    '"miss_overlap_max":0~1,"rationale":"…","calibration_agreement":"agree|adjust|reject + 理由"},'
    '"sliding_assessment":[{"i0":秒,"i1":秒,"peak_t":可选,"role":"…","note":""}]'
)

ULF_PASS2_FORMAT = (
    'ULF regions.reason 须引用 labeled_window_audit；miss_verdicts 须引用 miss_burst_audit。'
)

PASS1_FORMAT = (
    "只输出 JSON："
    '{"id":"文件名","task_understood":"…","n_regions_expected":整数,'
    '"regions":[{"region_id":0,"caption":"…","structure_guess":"…",'
    '"confidence_plausible":0.0到1.0,"reason":"一句"}],'
    '"miss_candidates":[{"candidate_id":0,"confidence_missed":0.0到1.0,"reason":"一句"}],'
    '"image_summary":"…"}'
)

PASS2_FORMAT = (
    "只输出 JSON："
    '{"id":"文件名","pass2_verdict":"合理|不合理|不确定","changed":true|false,'
    '"regions":[{"region_id":0,"verdict":"合理|不合理|不确定","reason":"含 ring/gradient/scale 数值"}],'
    '"miss_verdicts":[{"candidate_id":0,"verdict":"漏标|待复核|非漏标","reason":"引用 miss_ring_audit"}],'
    '"redundant_label_note":"嵌套/重复框是否构成冗余或虚标（一句）","reason":"总结"}'
)
