# Scientific Debater：深测脚本作「教学模型」、又不压制新数据理解

## 问题

- 三深测（z4 / fbbqy / xfnog）在 Pass1/2 **前·中·后** 写过多段辅助逻辑（`prepare_*`、`ring_audit`、`band_audit`、`window_audit`、aggregate 政策等）。
- Debater 对新数据会产出 **多版** `auxiliary_metrics_v0/v1/v2`（ refine 迭代，不是多条生产管线）。
- 目标：让模型 **学会分层与契约**，又不要在 DMSP/CME 等新族上 **照抄环带 Δ / band / Pi2**。

## 原则（三层隔离）

| 层 | 教什么 | 不教什么 |
|----|--------|----------|
| **结构** | L-1…L5 + L* 分工；Pass2 必须引数；辅助在沙箱 | 不把 `physics_metrics.py` 正文塞进 prompt |
| **契约** | 符号名 + 输入输出 +「当时为何加」 | 不贴 200 行实现 |
| **门控** | `do_not_copy_when` + archetype 距离 | 同 pipeline 但不同仪器时不注入深测符号 |

冻结的 **星海舰队 / smoke_test** 不参与 debater 写入路径；教学语料只在 `scientific_debater/corpus/teaching_spine.json`。

## 三深测在主线里的「前·中·后」（教学用）

| 时机 | AIA z4 | EPB fbbqy | ULF xfnog |
|------|--------|-----------|-----------|
| **Pass1 前** | `label_overlay` + `aia_metrics_for_image` | `epb_metrics` + 暗条几何 | `render_waveform` + `threshold_calibration` |
| **Pass1–2 间** | `ring_audit_for_image` | `_epb_miss_band_audit` | `ulf_pass2_audit_from_thresholds` |
| **Pass2 后** | 九7 诊断不进 C09 | 尺寸/规则优先 | `windowAudit` 列对齐 jsonl |

Debater **只模仿 L* 一层**：单个 `auxiliary_metrics()`，衔接 Pass1 上下文，**不 fork** 上表函数。

## 实现：门控教学注入

1. **语料**：[teaching_spine.json](../package/agent_modules/scientific_debater/corpus/teaching_spine.json)  
2. **拼装**：`teaching_context.build_teaching_block(pipeline, archetype_id, mode=…)`  
3. **注入点**：仅 `metric_proposals`、`draft_script`（不在 `task_context` 灌 GitHub 前置里混大量深测符号，避免 anchor bias）  
4. **模式**  
   - `auto`（默认）：同 pipeline 且 archetype 未命中 `do_not_copy_when` → 展开对应深测 **结构范例**；否则 **meta + 一句类比**  
   - `meta_only`：仅 L* 分层，无 z4/fbbqy/xfnog 符号（纯新仪器）  
   - `spine_full`：总展示分层表 + 范例 + `do_not_copy`（答辩演示用）

每次会话写入：`experiments/.../TEACHING_CONTEXT.md`（可审计「当时模型看到了什么教学」）。

```bash
python package/scripts/run_scientific_debater.py \
  --dir colab_subset/publish/DMSP_SSUSI_aaue04ws6s \
  --secrets secrets.yaml --teaching-mode auto
```

## DeepSeek 为何给出「几份脚本」

| 文件 | 含义 |
|------|------|
| `auxiliary_metrics_v0.py` | 首轮草稿 |
| `auxiliary_metrics_v1/v2.py` | refine 修订 |
| `auxiliary_metrics.py` | **试跑得分最高** 的版本（非最后一轮） |

**不是**要求模型平行写三套生产脚本；而是 **同一函数迭代**。主轨仍只有一份 `prepare_*` + `run_two_pass`（深测冻结）。

## 与 dataset_router 联动

```
router（archetype/pipeline）
    → teaching_context 门控
    → debater 针对 **本 archetype** 写 auxiliary_metrics
    → 沙箱试跑 → refine
    → 可选：把 jsonl 标量并进 Pass1（实验，未进星海舰队）
```

Router 决定 **pipeline**；teaching 决定 **注入多深的范例**；二者叠加避免「认成 AIA 就 ring_audit」的过度泛化。

## 重测（全流程 + Pass1 衔接 + 演进审计）

```bash
export DEBATER_AUXILIARY_SCRIPT=experiments/.../auxiliary_metrics.py  # 可选，physics 自动读
cd Agent-Pipeline/package/scripts
export MODEL_DISABLE_THINKING=1
python3 run_debater_retest.py --secrets ../../../secrets.yaml --teaching-mode auto --max-refine 2
```

产出：

- `EVOLUTION_AUDIT.md`：v0/v1/v2 指标增减与行数 Δ（`regressed` / `good_add` / `bloat`）
- `pass1_hook_dry_run`：`prepare_*` 后 `metrics.debater_auxiliary` 是否写入
- 索引：`experiments/scientific_debater/RETEST_2026-11-19.json`

**2026-11-19 实调**：DMSP/CME/EPB 均 `ok`；择优 **v1**（v2 常因 cv2/签名退化被拒）；`sane_evolution=true`。

Pass1 实参（无 API）：

```bash
export DEBATER_AUXILIARY_SCRIPT=/path/to/auxiliary_metrics.py
# 再跑 physics_informed_* --metrics-only 或 prepare_aia 单条
```

## 后续

- 从 `physics_inspect.prepare_*` 自动 **抽取签名** 刷新语料（仍不注入正文）  
- 强制 `pipeline_coverage` 含 `L2_pass1_context`（当前模型常仅 L1）  
- RL 奖励：标量稳定性 + 与九类规则一致性（非与 z4 数值相等）