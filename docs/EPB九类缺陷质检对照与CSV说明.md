# EPB 目录 · 九类缺陷质检对照与对象 CSV 说明

**依据**：`路演要求/01_现场展示数据清单.md`、`02_选手展示和自测要求.md` §6；`交付物/02-评价规范/数据集质量评价规范.md` 九类↔C01–C13。  
**范围**：`EPB_seg_sample_*` 四个目录（**扁平**：同目录 `{fileName}.png` + `{fileName}.json`）。  
**对照文档**：[AIA九类缺陷质检对照与CSV说明.md](./AIA九类缺陷质检对照与CSV说明.md)（HEK/日面框逻辑 **不照搬**）· [ULF九类缺陷质检对照与CSV说明.md](./ULF九类缺陷质检对照与CSV说明.md)（Pi2 时间窗，与 EPB 无关）。

---

## 0. EPB 与 AIA 质检哲学差异（必读）

| 维度 | AIA | EPB |
| --- | --- | --- |
| 几何 | HEK 五点框，偏小 | `mask.shapes` **任意多边形**，暗条 **大且不规则** |
| 物理对比 | 日面 EUV **亮**核 vs 外环 | flat-field **残差 depletion**（暗条） |
| Pass2 数值轨 | **0.5d–1d / 1d–2d 环带** + gradient | **多边形外固定环带 `band_audit`**（已标区 + 漏标候选 **共用**） |
| 漏标 | EUV 亮斑候选（诊断「可能未标亮区」） | **暗条连通 + 扩散轮廓**；列 **`九7_可能未标暗条`**；同图 **0–2** 候选 |
| 多区 | 多 HEK 框 | 本包常见 **1～2** 个 `EPB` mask / 图 |

实现版本：`epb-qc-v1`、`physics-informed-v1`、`EPB_MISS_METHOD=connectivity+diffusion+gradient_contour`。

---

## 1. 九类缺陷在 EPB 上的规则覆盖

| 九类 | checkId | EPB 是否适用 | 本仓库实现 | 判定层级 |
| --- | --- | --- | --- | --- |
| 1 数据文件缺失 | C01 | 是 | `json_consistency`：`basic_annotation.fileName` ↔ 同目录 PNG | **对象** |
| 2 孤儿标注/悬空引用 | C01 | 是 | 目录级 PNG/JSON 差集 + 对象 `fileName` | 目录 + 对象 |
| 3 边界与位置偏差 | C05 / C13 | 是 | C05：`像素越界`（1024 画面）；C13：Pass1/2 + **`band_audit`（非 AIA 环）** | **逐 mask** + 对象 |
| 4 类别非法词 | C04 | 是 | `science_annotation.mask.shapes[].label` 含 `__OOV__` 等 | 标注记录 |
| 5 事件时段超出文件 | C07 | **不适用** | ULF 专用 | 对象 **不适用** |
| 6 元数据尺寸与掩膜矛盾 | C06 | 是 | `basic_annotation.imgSize` vs PNG 头（如 `1024x1024`） | 对象 |
| 7 目标强信号漏标 | C09 | 是（**暗条轨**） | `missed_label_audit_epb` → **`九7_可能未标暗条`**；Agent 确认才 **`九7_漏标` fail** | 对象 + `missLabel` JSON |
| 8 虚标 | C09 | 是 | Pass2 单 mask **不合理**（无 depletion / 贴错结构） | **逐 mask** |
| 9 虚标与覆盖异常 | C09 | 是 | `mechanical_coverage_audit`（**多边形 bbox** IoU/IOS≥0.65、退化框） | **逐 mask 对** + 对象 |

**C08**、全目录 C13 审计轨：写法同 AIA，不计入九类分子时可写 `notes`。

结论：EPB **无 HEK/日面定标**；**#3、#7、#8** 一律按 **多边形 + 残差 band**，**禁止**用 AIA 小环带替代 EPB 暗条轮廓质检。

---

## 2. 目录汇总与脚本

| 产出 | 脚本 | 说明 |
| --- | --- | --- |
| `{dirId}_EPB对象质检.csv` | `epb_dir_object_qc_csv.py` | 每 PNG 一行，九类 + `regionsDetail` |
| `EPB_physics_informed.jsonl` | `physics_informed` + `prepare_epb` / `run_two_pass` | Pass1/2；可 `--physics-jsonl` 合并进对象 CSV |
| `EPB_fbbqy_sample_review/test_{objectId}.png` | `epb_physics_sample.py` | 全幅 **轮廓线**（无填充）+ 漏标候选多边形 |
| 目录路演行 / 证据 / 审计 | *待接* `epb_roadshow_aggregate.py`（可选） | 对齐 AIA bundle 时复用 `mechanical_coverage_audit` 已支持 EPB |

```bash
# 单目录对象 CSV（漏标 fast，Top-2 候选/图）
agent_modules/.venv/bin/python 路演结果/epb_dir_object_qc_csv.py \
  --dir 路演数据/EPB_seg_sample_fbbqy66u2d --miss-mode fast --jobs 4

# 抽样 Pass1+Pass2 + test_ 叠加图
agent_modules/.venv/bin/python 路演结果/epb_physics_sample.py \
  --secrets secrets.yaml --ids 某.png --no-api   # 仅规则+轮廓
```

**分母约定（EPB fbbqy 量级）**：有 mask 对象约 **770** / 目录；**mask 总数 ≈ 对象数 × (1～2)**。C13/虚标/轮廓用 **mask（region）** 分母；C01/C09 漏标用 **对象** 分母。

---

## 3. 对象 CSV 列定义（与 AIA 对齐处）

| 列名 | EPB 含义 |
| --- | --- |
| `dirId` | 如 `EPB_seg_sample_fbbqy66u2d` |
| `objectId` / `labelFile` | 同 basename：`xxx.png` / `xxx.json` |
| `ruleVersion` | `epb-qc-v1` |
| `objectOverall` / `objectOverallScored` | 合并九类；计分轨 **不含** 未确认漏标 |
| `九1_文件配对` … `九6_尺寸矛盾` | 同规范四字 verdict |
| **`九7_可能未标暗条`** | `无` / `有候选` / `不适用` |
| **`九7_漏标`** | Agent 确认 **likely_miss** 才 **不通过**；否则 **不适用** |
| `九3b_轮廓贴合` | Pass2 + **`band_audit`** |
| `九8_虚标` | Pass2 mask 不合理 |
| `九9_覆盖异常` | 机械 IoU/退化框 |
| `regionsDetail` | 逐 `region_id`：`fieldPath`=`science_annotation.mask.shapes[i].polygon` |
| `missLabel` | `candidates[]` 含 **`synthetic_polygon_full`**、`contour_method`、`preview_physics`（band） |
| `overlapNote` | `duplicate_label_groups`（同 label 多 mask） |

生成：`epb_object_qc.py` ← `missed_label_audit_epb`、`mechanical_coverage_audit`（已读 `pixel_rings`）。

---

## 4. 物理与漏标规则（EPB 专用）

### 4.1 已标 mask — `ring_audit_for_image(EPB)`

- **不用** 0.5d–1d 距离环（大暗条上 d 不稳定、环带常空）。  
- **改用** `_epb_miss_band_audit`：mask 内残差 vs **形态学外扩环带**；输出 `audit_band_depletion`、`area_ratio_to_median_label`、`boundary_gradient_mean`。  
- Pass2 提示字段仍名 `audit_0.5_1d`，语义为 **depletion 支持度**（兼容 JSON 模板）。

### 4.2 漏标 — `missed_label_candidates_epb`

1. ASI 有效区 + 残差 **P28** 暗阈  
2. 标注 union **轻膨胀** 外的 **暗连通域**  
3. 连通域内 **多暗点种子** → **有偏随机游走** 扩散  
4. **梯度收边** → **角序多边形**（非小矩形）  
5. 面积：**0.12～3×** 同图已标 mask 面积中位数（可至 **0.22× 全幅** 上限）  
6. **Top-2** 候选 / 图；Pass2 **`miss_ring_audit.band_audit`** 与已标区同一套 band 逻辑  

**汇总口径**：目录统计 **`九7_可能未标暗条`** = 有候选对象数（**诊断**）；**C09-miss-confirmed** = Agent/Pass2 确认漏标 k/n。

### 4.3 机械九类 #9

与 AIA **相同 IoU/IOS 阈值**，但 meta 来自 **mask 多边形 bbox**（`mechanical_coverage_audit` 已统一 `pixel_rings`）。

---

## 5. 单 mask `regionsDetail[]` 建议字段

```json
{
  "region_id": 0,
  "fieldPath": "science_annotation.mask.shapes[0].polygon",
  "caption": "EPB",
  "mechanical": "none|覆盖过多|覆盖不足",
  "pass1_confidence": 0.62,
  "pass2_verdict": "合理|不合理|不确定",
  "ring_audit_0.5_1d": "supports_depletion|weak_depletion|…",
  "band_audit": {
    "depletion_sigma": 1.2,
    "area_ratio_to_median_label": 1.05,
    "audit_miss_label": null
  },
  "scale_audit": { "area_ratio_to_median": 1.05, "scale_plausible": true }
}
```

对象级 **九3** = 全部 mask Pass2 合理 → 通过；任一不合理 → 不通过；未跑 VLM → 待判定。  
对象级 **九9** = 存在 severe_overlap 或退化 bbox → 不通过。

---

## 6. Pass1 / Pass2 分工（与 AIA 同构、EPB 不同参）

| 阶段 | EPB 内容 |
| --- | --- |
| **Pass1** | 逐 mask 结构猜测 + **`miss_candidates`**（目视 dark band） |
| **Pass2** | 已标：`band_audit` + `scale_audit`（面积）；漏标：`miss_verdicts` 引用 **band_audit** |
| **规则先行** | 机械 #9、C01/C04/C05/C06、漏标候选 **先进 CSV**，再 VLM 补 **九3/九8** |

---

## 7. 推荐流水线（对齐 AIA：`physics_informed` Pass1+2 → 对象 CSV → postprocess）

```bash
# 一键：API 双 pass + 九类对象 CSV + 路演行/证据/评分/排序/日志
agent_modules/.venv/bin/python 路演结果/epb_fbbqy_full_pipeline.py

# 分步
agent_modules/.venv/bin/python 路演结果/physics_informed_epb.py \
  --dir 路演数据/EPB_seg_sample_fbbqy66u2d --limit 0 --call --append
agent_modules/.venv/bin/python 路演结果/epb_dir_object_qc_csv.py \
  --dir 路演数据/EPB_seg_sample_fbbqy66u2d --miss-mode fast --jobs 8 --postprocess
```

产出与 AIA z4 同级：`EPB_physics_informed.jsonl`、`{dirId}_EPB对象质检.csv`、`*_EPB目录审计包.json`、`*_缺陷严重程度排序.csv`、`评分卡_EPB_fbbqy_epb_qc.json`。

---

## 8. 与 AIA 文档的字段对照

| AIA | EPB |
| --- | --- |
| `九7_可能未标亮区` | `九7_可能未标暗条` |
| HEK 上下文 CSV | **无**（可选残差/band 统计扩展） |
| `hek_event_annotation…` | `science_annotation.mask.shapes` |
| EUV `miss_ring` 亮核 | `band_audit` depletion |

---

**版本**：`epb-qc-v1` · 漏标 `connectivity+diffusion+gradient_contour` · 已标区 `epb_polygon_band`（2026-11 与代码同步）。
