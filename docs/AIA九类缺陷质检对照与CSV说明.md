# AIA 目录 · 九类缺陷质检对照与对象 CSV 说明

**依据**：`路演要求/01_现场展示数据清单.md`、`02_选手展示和自测要求.md` §6；`交付物/02-评价规范/数据集质量评价规范.md` 九类↔C01–C13 表。  
**范围**：AIA_AR_sample 四个目录（两级 `data/` + `label/*.png.json`）。  
**EPB 同级说明**：[EPB九类缺陷质检对照与CSV说明.md](./EPB九类缺陷质检对照与CSV说明.md)（mask 多边形 + 暗条 band，**勿用本文 AIA 环带逻辑**）。  
**ULF 同级说明**：[ULF九类缺陷质检对照与CSV说明.md](./ULF九类缺陷质检对照与CSV说明.md)（Pi2 时间窗 + H 带通，**无像素框**）。

---

## 1. 九类缺陷在 AIA 上的规则覆盖

| 九类 | checkId | AIA 是否适用 | 本仓库质检实现 | 判定层级 |
| --- | --- | --- | --- | --- |
| 1 数据文件缺失 | C01 | 是 | `audits.json_consistency` 引用文件 + 配对扫描 | 对象：PNG 是否存在 |
| 2 孤儿标注/悬空引用 | C01 | 是 | 目录级差集 + 对象 `fileName` 一致 | 目录 + 对象 |
| 3 边界与位置偏差 | C05 / C13 | 是 | C05：`像素越界`；C13：两 pass 物理 + ring/gradient/scale | **逐框** + 对象汇总 |
| 4 类别非法词 | C04 | 部分 | AIA 无 EPB `mask.label`；HEK `concept` 含 `__OOV__` 等 → fail | 标注记录 |
| 5 事件时段超出文件 | C07 | **不适用** | ULF 专用 | 对象填 **不适用** |
| 6 元数据尺寸与掩膜矛盾 | C06 | **不适用** | AIA 无 `imgSize`，尺寸读 PNG 头 | 对象填 **不适用** |
| 7 目标强信号漏标 | C09 | **AIA 计分轨不适用** | HEK 为事件框；EUV 亮区记 **可能未标亮区**（诊断轨），**不按漏标 fail** | `missLabel` JSON |
| 8 虚标 | C09 | 是 | Pass2 单框 **不合理**（非机械重复）；背景框/无结构 | **逐框** |
| 9 虚标与覆盖异常 | C09 | 是 | **送 Agent 前** `mechanical_coverage_audit`（IoU/IOS≥0.65→覆盖过多；w/h≤0→覆盖不足）；`scale_audit` 过大框 | **逐框对** + 对象 |

**C08**（CSV 3600 行）与 **C13 全目录审计轨** 不计入九类分子，但可写在 `notes` 或目录级 `nine_defect_inventory`。

结论：**AIA 九类在工程上均有对应规则**；#5、#6 在对象 CSV 中固定为「不适用」，不是未检查。

---

## 2. 目录汇总（在对象 CSV 之上）

| 产出 | 脚本 | 对应 02 |
| --- | --- | --- |
| `{dirId}_AIA对象质检.csv` | `aia_dir_object_qc_csv.py` | 内部明细（非提交表） |
| `{dirId}_路演结果行.csv` | `aia_dir_roadshow_bundle.py` | **6.1** 一行/目录，合并进 `路演结果_{队名}.csv` |
| `{dirId}_AIA证据汇总.csv` | 同上 | **6.2** 检查项四类 verdict + 抽样 `imageRegion` |
| `{dirId}_AIA审计指标.csv` | 同上 | Q4 比例/SE/RE（对象分母 vs **框分母 2042**） |
| `{dirId}_AIA目录审计包.json` | 同上 | Q7/Q8：ruleVersion、seed=0、耗时/token 估算 |
| `{dirId}_HEK上下文_框明细.csv` | 汇总（**只读**对象 CSV + `label/*.json`，**不读 PNG**） | 合格框 HEK 基线；候选 EUV 用 QC 阶段 `missLabel.preview_physics` |
| `{dirId}_HEK上下文_汇总.csv` | 同上 | 各 `qcCohort` 相对参照的 median/P10 偏离率 |

```bash
# 473 张并行规则+漏标 fast（约 8 核 ~4 min）
agent_modules/.venv/bin/python 路演结果/aia_dir_object_qc_csv.py --miss-mode fast --jobs 8

# 目录汇总（可仅估算）
agent_modules/.venv/bin/python 路演结果/aia_dir_roadshow_bundle.py
agent_modules/.venv/bin/python 路演结果/aia_dir_roadshow_bundle.py --estimate-only
```

**分母约定（AIA z4）**：C01 全目录 **1838** 条标注；有像素框对象 **473**；标注框 **2042**（`region_id`）。C13/虚标/轮廓用 **框** 作分母；配对/覆盖异常用 **对象**；**可能未标亮区**（C09-bright-unlabeled）单独诊断指标，**不计入漏标 k/n**。

---

## 3. 与 `02` 两份 CSV 的关系

| 文件 | 粒度 | 本 AIA 对象 CSV |
| --- | --- | --- |
| `路演结果_{队名}.csv` | **12 行 / 目录** | 不替代；目录汇总仍由 `evaluate_roadshow.py` 出分 |
| `证据表_{队名}.csv` | **每条 finding** | 对象 CSV 的 fail 应能回查为证据行（`findingId`+`checkId`） |
| **`{dirId}_AIA对象质检.csv`**（本规范） | **每 PNG 一行** | 九类列 + `regionsDetail` 内 **逐 region_id 框** |

对象表 verdict 与证据表对齐：

| 对象表 | 证据表 §6.2 |
| --- | --- |
| 通过 | pass |
| 不通过 | fail |
| 待判定 | undetermined |
| 不适用 | not_applicable |

---

## 4. `{dirId}_AIA对象质检.csv` 列定义

UTF-8，**一行 = 一个对象**（`objectId` = `basic_annotation.fileName`）。

| 列名 | 含义 |
| --- | --- |
| `dirId` | 目录名 |
| `objectId` | 数据 PNG 文件名 |
| `labelFile` | `label/{objectId}.json` |
| `ruleVersion` | 如 `aia-qc-v1` |
| `objectOverall` | 九类合并：任一适用项 **不通过**→不通过；仅 **待判定**→待判定；否则 **通过** |
| `九1_文件配对` … `九9_覆盖异常` | 四类等级之一 |
| `nRegions` | 有像素框的 region 数 |
| `regionsDetail` | JSON 字符串：**逐框** `region_id, verdict, pass1_conf, pass2_verdict, scale, ring_audit, …` |
| `mechanicalCoverage` | JSON：严重重叠对、退化框 |
| `missLabel` | JSON：漏标候选与 `audit_miss_label` |
| `overlapNote` | 同 AR 多框组摘要 |
| `notes` | 人工可读一句 |

生成脚本：`路演结果/aia_dir_object_qc_csv.py`（可 `--physics-jsonl` 合并 Agent 结果）。

**九7 / 可能未标亮区（汇总口径 v3，无需重跑对象 CSV）**  
- 对象 CSV 保留历史列 `九7_漏标`；**目录汇总**改读 `missLabel` 候选数，记 **可能未标亮区**，**不计入漏标 k/n**。  
- 计分列：`九7_可能未标亮区` = `无` / `有候选`；`九7_漏标` = **不适用**（除非 Agent 确认漏标）。  
- 候选仍用 OPC `detect_disk` + ≥0.1% 日面等启发式，仅作诊断。  
- `objectOverallScored`、路演分数、C09-bright-unlabeled 与 C09-miss-confirmed 分开。

**漏标性能（473 张对象 CSV）**  
默认 `--miss-mode fast`：每张图 **只解码一次**、工作分辨率 **1024**、最多 **3** 个候选、**仅 weak_contrast 时** 才算 gradient（`supports_brighter_core` 可直接判 likely_miss）。全量复核用 `--miss-mode full`；只出机械/规则列用 `--miss-mode skip`（九7/九8 多为待判定）。

---

## 5. 单框 `regionsDetail[]` 建议字段

```json
{
  "region_id": 0,
  "fieldPath": "hek_event_annotation.matched_events[0].bbox_polygon_pixel",
  "ar_noaanum": "12731",
  "mechanical": "none|覆盖过多|覆盖不足",
  "pass1_confidence": 0.55,
  "pass2_verdict": "合理|不合理|不确定",
  "scale_audit": "appropriate|oversized|…",
  "ring_audit_0.5_1d": "supports_brighter_core|weak_contrast|…",
  "bbox_full": {"xmin": 0, "ymin": 0, "xmax": 0, "ymax": 0}
}
```

对象级 **九3** = 所有框 C13 均通过→通过；任一不合理→不通过；未跑 Agent→待判定。  
对象级 **九9** = 存在机械 severe_overlap 或退化框→不通过。

---

## 6. 推荐流水线（AIA z4 目录）

```text
1. evaluate_roadshow / 规则扫描 → 目录分 + 证据表 C01/C04/C05
2. aia_dir_object_qc_csv.py --dir … [--physics-jsonl AIA_physics_informed.jsonl]
3. physics_informed_aia.py --limit 0 --call（473 张，补 C13/漏标/虚标）
4. 证据表 append：C09 机械 + C13 physics + mechanical_evidence_rows
```

---

**版本**：`aia-qc-v1`（与 `physics-informed-v1`、`mechanical-coverage-v1` 并存时写在 `ruleVersion` / finding 中）。
