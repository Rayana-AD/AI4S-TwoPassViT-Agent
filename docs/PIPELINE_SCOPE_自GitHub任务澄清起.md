# 新管线范围（自「查 GitHub 理解 AIA/EPB/ULF 任务」起）

**起点**（对话锚点）：主办方未充分公开图像科学细节 → 查阅 OPC/GitHub 样例与 HEK/EPB/ULF schema，对齐 **Pi2 / EPB 暗条 / AIA AR 框** 与九类 C01–C13。

**终点**（当前）：Pass1/Pass2 physics-informed + 三模态对象 CSV / 目录审计包 + `Agent-Pipeline` 可复现包。

## 里程碑

1. **任务理解**：`OPC-code/code_for_*`、`colab_subset/publish` JSON 字段；路演数据 z4 / fbbqy / xfnog 与任务书六类目录对应表（见导出 transcript / zip 说明 md）。
2. **AIA**：`aia-qc-v2` 对象 CSV；z4 全目录 473 对象；`AIA_physics_informed.jsonl`；HEK 上下文 CSV（**非** HEK=漏标终判）。
3. **EPB**：`band_audit` 替代 AIA 0.5d 环；fbbqy 全目录 pipeline；样例 **`test_09u_N3cnKxe68a0ma7Bc.png`**（`epb_physics_sample.py`）。
4. **ULF**：Pi2 6.7–25 mHz；**滑动反估阈值 + Pass1 终估 + Pass2 window_audit**；`ulf-qc-v1` 对象 CSV；弃用 `ulf_good_bad` 作默认 verdict。
5. **Agent-Pipeline**：打包 `physics_prompts`、`physics_metrics`、`physics_inspect`、QC/aggregate、脚本；Docker 重建；烟测 + Gb96/09u review cases。

## 与早期产物区分

| 早期 | 现行 |
| --- | --- |
| 纯 VLM 是/否 jsonl | `*_physics_informed.jsonl` Pass1+2 |
| `ulf_good_bad` 好数据轨 | 诊断参照；主链 Pass1/2 |
| 固定 Pi2 3× 阈值 | `threshold_calibration` + 模型 `threshold_proposal` |
| 路演交付旧 Docker | `Agent-Pipeline/docker/Dockerfile` |

## 烟测对齐

- `smoke/smoke_test.py`：AIA/EPB/ULF 各 3 行 CSV 指纹。
- `smoke/review_cases.py`：`Gb96QafrHF4ZNGdUa6Va.png`（2 框 + miss 候选）、`09u_N3cnKxe68a0ma7Bc.png`（EPB 暗条 metrics）。
