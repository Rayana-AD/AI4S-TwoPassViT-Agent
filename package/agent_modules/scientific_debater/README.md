# Scientific Debater（科学辩题模块）

**目的**：在 `dataset_router` 识别 archetype 之后，用多轮「开发式提问」模拟你手工补 Pass1/2 前后脚本的过程：

1. **task_context** — 结合 RAG 链接，提议 GitHub/文档检索策略  
2. **defect_visual** — 固定视觉相关九类子集（3b/6/7/8/9）在本类图上可能长什么样（必要时送样图）  
3. **metric_proposals** — 亮度梯度、径向 profile 等可规则化指标  
4. **heuristic_geometry** / **heuristic_image_defects** — 几何算子；图像类逐项「可能情形」（固定 3b/6/7/8/9）  
5. **draft_script (v0)** — 生成 `auxiliary_metrics`（**不写入** `physics_metrics.py`）  
6. **calibrate + refine** — 沙箱试跑；v1/v2 教学与启发式修订  

## 边界

| 做 | 不做 |
|----|------|
| 产物写到 `Agent-Pipeline/experiments/scientific_debater/<dir_id>/` | 不改 `星海舰队/`、不改 `smoke_test` 指纹 |
| 辅助指标衔接 Pass1/2（实验 jsonl） | 不替代正式 `physics_informed_*.py` |
| 默认 `--offline` 可跑通 public 样例 | 不保证无 API 时脚本质量 |

## 模型

- 文本轮次：`vision.model_endpoint()` 的 **text** 角色（建议 `MODEL_TEXT_NAME=deepseek-v4-pro`）  
- 视觉轮次：**vision** 角色（如 `deepseek-flash`）  
- 环境变量覆盖见 `vision.py`。

## 命令

```bash
cd Agent-Pipeline/package/scripts

# 单目录离线（评委演示 / CI）
python run_scientific_debater.py --offline --dir ../../../colab_subset/publish/CME_C2_sample_g8x0hw7reo

# 四族 public 烟测
python run_scientific_debater.py --smoke-publish --offline

# 联调 API + 规则轨试跑 + 1 轮 refine
python run_scientific_debater.py \
  --dir ../../../colab_subset/publish/DMSP_SSUSI_aaue04ws6s \
  --secrets ../../../secrets.yaml \
  --pipeline-check --max-refine 1
```

产出：

- `debate_session.json` — 各轮问答  
- `auxiliary_metrics.py` — 可审查的辅助脚本  
- `auxiliary_metrics.jsonl` — 样本标量结果  

## 教学模型（三深测，不复制代码）

- 语料：`corpus/teaching_spine.json` · 拼装：`teaching_context.py`
- CLI：`--teaching-mode auto`（默认）| `meta_only` | `spine_full`
- 文档：`docs/Scientific_Debater_教学与主轨隔离.md`

## 后续（RL / 强化）

当前为 **显式辩题 phase** + 可选 refine。强化学习可把 `(profile, script) → calibration loss` 当奖励；接口预留为 `calibration` 列表与 `pipeline_dry_run` 摘要。