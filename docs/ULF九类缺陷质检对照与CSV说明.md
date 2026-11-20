# ULF 目录 · 九类缺陷质检对照与物理检验说明

**依据**：`交付物/02-评价规范/数据集质量评价规范.md`、`OPC-code/code_for_ULF_sample/README.md`；路演数据 `ULF_sample_xfnogkdey9`（扁平 `{id}.csv` + `{id}.csv.json`）。  
**对照**：[AIA九类缺陷质检对照与CSV说明.md](./AIA九类缺陷质检对照与CSV说明.md) · [EPB九类缺陷质检对照与CSV说明.md](./EPB九类缺陷质检对照与CSV说明.md)（**无像素框/掩膜**，任务为 **Pi2 时间窗**）。

---

## 0. 先回答：列含义、要不要四分量一起看、T 是什么

### 0.1 CSV 各列（`t,H,D,Z,T`，3600 行）

| 列 | 含义 | 单位（OPC 示例 / 可视化脚本） | 质检是否用 |
| --- | --- | --- | --- |
| `t` | 相对该小时 **0 秒起的采样序号**（0…3599），不是 Unix 时间 | s（索引） | 映射 `matched_events` → `i0,i1` |
| `H` | 水平分量（子午 FGM 习惯下的 H） | **nT** | **Pi2 主通道**（带通、包络、规则窗检验） |
| `D` | 磁偏角 / declination | **deg** | 辅助（`ulf_good_bad` 等边缘对齐）；**不**作为当前 Pi2 带通输入 |
| `Z` | 垂直分量 | **nT** | 同上，辅助 |
| `T` | 第四路标量（schema 写 nT；部分台站文件中数值近乎常数） | 标注为 nT | **当前管道不参与 Pi2 滤波**；勿与 EPB「温度」混淆 |

**不需要四分量同时出现相同形态的 Pi2 才判「有事件」。**  
文献与工程上 Pi2 阻尼振荡 **以 H（或水平磁场）为主**；D/Z 可能同相或弱耦合，**不是「四路齐涨齐跌」的硬条件**。本仓库 `physics_metrics.ulf_pi2_metrics` / `prepare_ulf` **只对 H 做 6.7–25 mHz 带通 + Hilbert 包络**；`audits.waveform_window` 的粗规则也是 **H 偏离中位数**。

### 0.2 标注在检什么（一条样本 = 1 小时）

- **正样本**：`ulf_event_annotation.has_events=true`，`matched_events[]` 里每条为 `{start_dt, end_dt, kind, source}`，常见 `kind=Pi2`。
- **负样本**：`has_events=false`，`matched_events=[]`（安静小时）。
- **时间轴**：`basic_annotation.startTime` / `endTime` 定义该 CSV 覆盖的 UTC 小时；事件窗必须落在此区间内（**结束比 `endTime` 晚 ≤1 s 容差**，见 C07）。

可视化参考：`OPC-code/code_for_ULF_sample/plot_ulf_annotations.py`（四分量 + 事件窗）；**Pi2 规则诊断图**（H / 带通 / 包络 / 阈值线）：`路演结果/ulf_pi2_rule_viz.py` → `ULF_pi2_rule_review/`（**不走** `ulf_good_bad` 好数据路线）。

### 0.3 Pi2 物理判据（文献）↔ 本仓库实现

| 文献 / 你整理的要点 | 本仓库对应 | 说明 |
| --- | --- | --- |
| 周期 **40–150 s**（**6.7–25 mHz**） | `ulf_bandpass(..., f_low=1/150, f_high=1/40)` | 全 **3600 s** H 序列，`fs=1 Hz`（见下采样 caveat） |
| 带通或 CWT + **Hilbert 包络** | `ulf_pi2_metrics`：`envelope_quiet`（P30）、`envelope_peak`、`peak_over_quiet` | 去中位数后滤波 |
| 能量 **> 底噪 ~3×**、持续 **1–15 min** | 文献建议；**具体倍数/时长/合并规则不在代码里写死** | **阈值由模型或标定集确定**；当前只输出描述量 + 窗图 |
| 漏标 / 虚标 | 需 **窗 vs 全小时 Pi2 包络** 对比 | 先 `ulf_pi2_rule_viz.py --mode windows` 画窗；**Pass1 提议阈值，Pass2 用 `window_audit` 计分** |
| 历史 `ulf_good_bad` 好数据轨 | 自参照 + 16 张 VLM | **不作为默认**；见讨论，仅可选参照 |

**采样率 caveat**：JSON 里偶有 `sampling_rate_hz: 0.25` 但 **`n_points=3600`、文件仍 3600 行** — 质检按 **3600 行 × 1 Hz 索引** 处理（与 C08 一致）；若物理上非 1 Hz，需在对象 `notes` 标数据元数据矛盾（扩展 C06）。

**`window_audit`（Pass2 数值轨）**：`physics_metrics.ulf_pass2_audit_from_thresholds` — 用 Pass1 的 `threshold_proposal` 生成 `labeled_window_audit`（每窗 `audit_labeled_window`）与 `miss_burst_audit`（标注外 Pi2 包络段）。Pass1 输入含 `sliding_window_scan`（600 s / 120 s 步长）与 `missed_label_candidates`（滑动高峰 vs 标注重叠）。

---

## 1. 九类缺陷在 ULF 上的规则覆盖

| 九类 | checkId | ULF 是否适用 | 本仓库实现 | 判定层级 |
| --- | --- | --- | --- | --- |
| 1 数据文件缺失 | C01 | 是 | `json_consistency`：`fileName` ↔ 同目录 `.csv` | **对象**（1 小时文件） |
| 2 孤儿标注/悬空引用 | C01 | 是 | 目录差集 + `fileName` | 目录 + 对象 |
| 3 边界与位置偏差 | C05 / C13 | **时间语义** | C07/C05 不适用像素；C13：**时间窗是否对准 H 上 Pi2/脉动**（Pass2 + `时间窗峰谷` 粗规则） | **逐事件窗** + 对象 |
| 4 类别非法词 | C04 | 弱 | 无 EPB式 `__OOV__`；可查 `kind` / `event_types` 异常 | 多为 NA |
| 5 事件时段超出文件 | C07 | **是（ULF 主战场）** | `_ulf_time_check`：事件超出 `startTime`–`endTime` **>1 s** → fail | 对象 |
| 6 元数据尺寸与掩膜矛盾 | C06 | **不适用** | 无 PNG/imgSize；**C08** 管 CSV **3600 行** | 对象 **不适用**；见 **C08/6b** |
| 7 目标强信号漏标 | C09 | 是 | 全小时 H：**Pi2 带通包络峰** 高、**无 `matched_events`** → 诊断/参照轨；Pass2 `miss_verdicts` | 对象 + 参照脚本 |
| 8 虚标 | C09 | 是 | 有窗但 **窗内 Pi2 能量弱** / Pass2 **不合理** | **逐窗** |
| 9 虚标与覆盖异常 | C09 | 部分 | **多事件窗重叠**、**零长度窗**、`event_count`≠列表长；非 IoU 像素 | 对象 / 事件列表 |

**C08**：`波形行数` — CSV 行数与 `science_annotation.n_points` 均为 **3600**（计分/完整性轨，见评价规范「抽出 CSV 行数」）。

**与 AIA/EPB 差异**：无 HEK/掩膜；**九5 在 ULF 上启用**；**九6（imgSize）不适用**；**九3** 是 **时间窗 vs 波形**，不是像素越界（像素越界对 ULF 为 NA）。

---

## 2. 物理检验量（可直接算，不必全库画图）

对象级 / 窗级进入 `prepare_ulf` → `metrics`（供 Pass1/Pass2）：

| 字段 | 含义 |
| --- | --- |
| `band_label` | `Pi2 6.7–25 mHz (40–150 s)` |
| `envelope_quiet` | 全小时 H，Pi2 带通后包络的 **P30**（底噪代理） |
| `envelope_peak` | 全小时包络 **最大值** |
| `peak_over_quiet` | 峰值 / 底噪；**>2（或校准 3）** 表示小时内有强 Pi2 能量 |
| `windows_labeled[]` | 每个 `matched_events` 映射的 `i0,i1` + `window_peak_envelope`、`window_energy` 等 |

规则层（`audits.waveform_window`）：

| 检查项 | 逻辑 |
| --- | --- |
| `波形行数` | `rows==3600` 且 `n_points==3600` |
| `时间窗峰谷` | 窗内 H 相对中位数 **最大偏离** 是否 **> 窗外 95% 分位**（粗对齐，非 Pi2 带通） |

参照轨（已跑全目录好数据分离）：

| 脚本 / 产出 | 作用 |
| --- | --- |
| `路演结果/ulf_good_bad.py` | 模型标定「好窗」→ **虚标**（峰离窗缘过远）、**漏标**（未标块像好窗） |
| `ULF虚标漏标.jsonl` / `ULF好坏分离.json` | 3534 参照样本上的 C09 统计（规范文档引用） |

VLM 轨（与 AIA/EPB 同构）：

| 阶段 | 内容 |
| --- | --- |
| **预处理** | `prepare_ulf`：波形图 + **`threshold_calibration`**（自适应 window/stride、尾窗覆盖、峰定位、反估 estimate+CI）+ `sliding_window_scan` 摘要 |
| **Pass1** | 以 calibration 为初值，模型结合图输出 **`threshold_proposal` 终估**（`calibration_agreement`）、`sliding_assessment`、`regions`、`miss_candidates` |
| **Pass2** | `ulf_merge_threshold_proposal` 合并 Pass1 与 calibration → **同参复算** `window_audit`；VLM 终判 |

入口：`physics_inspect.prepare_ulf` + `run_two_pass`；全目录 **`physics_informed_ulf.py`**（镜像 EPB）；抽样 **`physics_informed_roadshow.py --modality ULF`**。

---

## 3. 任务一句话（路演 / Agent）

**任务**：在 **1 Hz、3600 点** 的地磁小时文件上，检验 **`ulf_event_annotation.matched_events` 标出的 Pi2（ULF）时间窗** 是否与 **H 分量 Pi2 频段（6.7–25 mHz）能量** 一致；负样本应无事件窗且全小时无显著 Pi2 包络峰；正样本窗应覆盖脉动主段而非随意截取安静段。

---

## 4. 对象 CSV / 目录交付（规划，与 AIA/EPB 对齐）

| 产出 | 脚本（现状） |
| --- | --- |
| `{dirId}_ULF对象质检.csv` | **待** `ulf_dir_object_qc_csv.py`（可复用 `json_consistency` + `waveform_check_items` + physics jsonl） |
| `{dirId}_ULF目录审计包.json` 等 | **待** `ulf_roadshow_aggregate.py` |
| `ULF_physics_informed.jsonl` | `physics_informed_ulf.py` |

当前可直接跑：

```bash
# 仅 metrics（滑动窗 + 漏标候选，无 API）
agent_modules/.venv/bin/python 路演结果/physics_informed_ulf.py --limit 20 --metrics-only

# 全目录 Pass1+Pass2（需 secrets；Pass1 提议阈值 → Pass2 window_audit）
agent_modules/.venv/bin/python 路演结果/physics_informed_ulf.py --call --append

# 规则窗图（阈值未写死，仅画 JSON 窗）
agent_modules/.venv/bin/python 路演结果/ulf_pi2_rule_viz.py --mode windows

# 可选参照轨 C09（好数据分离；非默认 verdict）
agent_modules/.venv/bin/python 路演结果/ulf_good_bad.py

# 代表样本 Pass1+Pass2
agent_modules/.venv/bin/python 路演结果/physics_informed_roadshow.py --modality ULF --ids HjT4zNo2kbrkLPR2pq_s.csv --call
```

**分母约定（xfnogkdey9）**：目录标注约 **6120** 对；抽出/质检常用 **3534** 条「好数据」参照；**有事件窗对象** 以 `has_events` + 非空 `matched_events` 计数；**窗级** C13 分母 = **事件窗条数**（非 6120）。

---

## 5. 九类 ↔ 路演现象（本数据集常见）

| 九类 | ULF 典型现象 |
| --- | --- |
| 1 | 缺 `.csv` 或 `.csv.json` |
| 2 | 仅 json 无 csv |
| 3 | 窗偏到安静段、峰在窗外（C13）；或 `event_count` 与列表不一致 |
| 5 | 事件结束比 `endTime` 晚 **>1 s**（五版本约 **374–433** 条量级，规范称不单独作排序键） |
| 6 | （imgSize NA） |
| 6b/C08 | CSV **≠3600** 行（与 `n_points` 矛盾） |
| 7 | 全小时 `peak_over_quiet` 高但 `matched_events=[]` |
| 8 | 有 Pi2 窗但窗内带通能量≈基线 |
| 9 | 多窗重叠、重复事件、零长度窗 |

---

## 6. 与 EPB/AIA 的字段对照

| AIA/EPB | ULF |
| --- | --- |
| `objectId` = PNG | `objectId` = **`xxx.csv`** |
| `regionsDetail` / 框 | **`windows_labeled`** / `matched_events` 时间窗 |
| `九7_可能未标亮区/暗条` | **Pi2 包络峰 + 无事件窗**（诊断/参照） |
| `ring_audit` / `band_audit` | **`window_audit.labeled_window_audit`** + **`miss_burst_audit`** |
| HEK / mask | **`ulf_event_annotation` only** |

---

**版本**：规则 `rules-roadshow-20261102` · Pi2 指标 `physics_metrics.ulf_*` · VLM `physics-informed-v1`（2026-11 与代码同步）。  
**扩展**：对象 CSV / `ulf_roadshow_aggregate.py` 仍待接；physics jsonl 已可用 `physics_informed_ulf.py`。
