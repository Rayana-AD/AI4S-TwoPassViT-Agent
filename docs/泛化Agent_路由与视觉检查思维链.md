# 泛化 Agent：路由、视觉检查与三深测思维链（细粒度版）

> 来源：`空间科学/cursor_data_extraction_from_zip_file.md`、会话记录  
> `e7077cc1-a2fe-4d37-892a-7db3a2c3d66a`、本机脚本 **修改时间**（仓库无 git，**不能**用 `git log` 复现，见 §0）。  
> 目的：每条**具体改动**对应**具体问题**；区分 **交付主路径** vs **讨论过但未落地** 的比喻/算法。

---

## 0. 如何读本文 & 时间线依据

| 依据 | 用途 | 局限 |
|------|------|------|
| 聊天导出中的 `<timestamp>` | 决策先后、路演口径变更 | 长文需检索，不全在一条时间线上 |
| `ls -lt` 对 `Agent-Pipeline/package/**.py` | 脚本 **最后集中修改日**（如 2026-11-04 路演链、2026-11-19 路由） | 只反映末次写入，不含中间删改 |
| `smoke_test.py` 冻结指纹 | 判「是否动了深测交付锚点」 | 不等于全仓库历史 |
| transcript jsonl | `run_pipeline`、Docker、router 等 **工程节点** | 不含每次 StrReplace 的全文 |

**交付主路径（评委 / 星海舰队镜像）一句话**：

```text
docker load → smoke_test（z4 / fbbqy / xfnog 各 3 条）→ run_pipeline（默认 --physics skip）
    → modality_detect → *_dir_object_qc_csv → dir_postprocess → 评分卡/审计包
```

**不是主路径**：单次样本 `graph.py` LangGraph、`hex_score.py` 路演排序、`ulf_good_bad` 进 12 目录统一 `evaluate_roadshow`、塑料膜「可训练模块」、Christaller 六边形合成路演名次。

---

## 1. 结论（答辩用，仍保留）

| 问题 | 答案 |
|------|------|
| `publish` 上 router 检对了吗？ | 是：30/30；六类代表目录与 `run_pipeline` 三条 QC 链一致。 |
| 新数据能自动跑**规则九类**吗？ | **能**：`modality_detect`（现网）或 `dataset_router`（验证/泛化）→ AIA/EPB/ULF → 既有 `*_dir_object_qc_csv.py`。 |
| 仅靠 RAG 能长出全新 Pass1/2？ | **不能**；RAG 选 **已有** archetype + `physics_track`；新仪器要人加 `physics_metrics` + prompt。 |
| 与三深测同等的全目录视觉？ | **可选**：`--physics call` + secrets；默认 skip 时 Pass2 类列为待判定——与交付说明一致。 |

---

## 2. 未进入交付主路径的想法（避免与最终实现混读）

以下为聊天或原型中出现、**但当前镜像默认链路不依赖** 或 **仅作对照实验** 的内容。

| 想法 / 比喻 | 当时要解决的问题 | 实际落点 | 主路径？ |
|-------------|------------------|----------|----------|
| **塑料膜凸起**（先训一批好数据再按洞） | 明暗图批量判「框是否落在亮结构上」 | 部分吸收为 `spatial_precision` 平移 margin + 干净版标定 0.038；**无**单独可训练模块 | 部分（规则几何），非端到端训练 |
| **LangGraph 统筹全量生产** | 单条样本 JSON→视觉分支合成 | `graph.py` + `run_module_tests.py` 模块测 | **否**；生产用 `run_pipeline` + 目录脚本 |
| **Christaller 六边形密嵌合成路演名次** | 六维冗余、版本间相关 | `hex_score.py`、`六边形综合.json`（公开集 30 版探索） | **否**；路演排序用 **缺陷密度严格升序** |
| **文本模型重算缺文件/event_count** | Agent 感 | `audits` 硬规则；`explain_pending` 只解释**待复核** | 否（不推翻机械结果） |
| **全图每张送 flash 计主分** | 任务书要视觉 | z4 批量关 thinking；**主分仍规则九类**；轮廓进 C13/physics 轨 | 部分（深测/API 跑批），非默认交付 |
| **`ulf_good_bad` 写入 12 目录统一评价卡** | ULF C09 无真值 | 仅 xfnog 深测链 + 单独脚本；`evaluate_roadshow` 曾占位待判定 | 深测有，12 目录卡**未全对齐**（见聊天 §「三套口径」） |
| **六维等权 + 六边形做数据集全局排序** | 赛题六维 | 官方六维规范 + 缺陷密度；六边形仅在文档中标注为**探索算法** | 否 |
| **plastic / 可泛化标准一次性写死** | 30 公开版对照 | 收敛为 **modality + 九类 schema + 三 spine** | 是（规则侧） |
| **Research subagent 自动写 physics_metrics** | 新仪器 | `09_未完成事项说明` / archetype 表 | **未实现** |
| **`run_pipeline --router v2` 默认** | 新数据路由 | `dataset_router` 已可独立验证；**未**接入默认 CLI | 待接 |

---

## 3. 按时间顺序：问题 → 改动（脚本级）

时间粒度：**聊天时间戳** + **文件末次修改日**。同一日内多项按逻辑依赖排序。

### 3.1 公开集摸清形态（≈ 2026-10 下旬）

| 序号 | 具体问题 | 决策 | 改动（文件 / 行为） | 主路径 |
|------|----------|------|---------------------|--------|
| P01 | 245GB 包不能整包解压统计 | 子集 + manifest | `check_annotations.py`、`colab_subset/manifest.tsv` | 数据准备 |
| P02 | 六类 schema 不一（HEK / mask / specialShapes / csv.json） | 不能共用单一 bbox 规则 | 扫描结论写入聊天表；后入 `modality.py` → `modality_detect.py` | 是 |
| P03 | 缺文件要六类可比 | 以 manifest 配对计缺失阶梯 | `audits.referenced_in_package`、`locate_problems.py` | 是 |
| P04 | CME 无像素框却被当空间框检 | 单独 `event_catalog` 分支 | `modality.classify_record`；CME 规则偏目录/事件字段 | 是 |
| P05 | EPB 声明 1024×512 与真图 1024×1024 | 尺寸一致性独立 C02 | `audits.json_consistency`、对象 QC 尺寸列 | 是 |
| P06 | 无参考答案的漏标/虚标/覆盖 | 不伪造 0/100；记待判定 | 四态 `待判定`、路演分母政策 | 是 |

### 3.2 原型 Agent + 空间轮廓实验（2026-10-27 前后，文件 ~10-27）

| 序号 | 具体问题 | 决策 | 改动 | 主路径 |
|------|----------|------|------|--------|
| P07 | 图文：框是否贴亮结构 | 平移负样本 + margin | `spatial_precision.score_annotation`；`spatial_threshold.json`（10% 分位 ~0.038） | 辅助；深测以 physics ring/band 为主 |
| P08 | 单条要走通 JSON→视觉 | LangGraph 状态机 | `graph.py`（`classify_record` → audits → spatial/vision） | **原型 only** |
| P09 | 六类 JSON 标准要可单测 | canvas 标准落四态 | `audits.py` 大规模扩展、`run_module_tests.py` | 是（规则核心） |
| P10 | 波形先硬后软 | 行数 + 时间窗再 VLM | `waveform_window`、`waveform_check_items` | 是 |

### 3.3 公开集 30 版定量 & 六边形探索（~10-31，非路演最终排序）

| 序号 | 具体问题 | 决策 | 改动 | 主路径 |
|------|----------|------|------|--------|
| P11 | 30 版要可复算台账 | 确定性扫描 + 智能体补 4 条定位 | `locate_problems.py`、`智能体补洞.json` | 交付物/对照 |
| P12 | 六维相关不应简单加权和 | Christaller 式合成 | `hex_score.py`、`六边形综合.json` | **探索；路演不用** |
| P13 | 路演必须缺陷越多分越低 | 放弃六边形做最终名次 | 文稿改为 **缺陷密度升序** | **是（路演口径）** |

### 3.4 路演 12 目录 + z4 批量视觉（2026-11-02 前后，~11-02）

| 序号 | 具体问题 | 决策 | 改动 | 主路径 |
|------|----------|------|------|--------|
| P14 | thinking 拖慢 z4 且可能空正文 | 批量关思考 | 运行配置 `thinking: false`（日志字段） | API 跑批配置 |
| P15 | 规则 100 分但 473 张轮廓不贴 | 规则分与 C13 分流 | `aia_object_qc` 九类 + 后续 physics 轨证据 | 是 |
| P16 | xfnog 规则密度 0.0387 vs 参照 0.072「漏标」 | 名次仍以规则密度；xfnog 不单独前移 | 聊天「名次冻结」说明 | 路演叙事 |
| P17 | flash 不应每张都送 | JSON 全扫；读图分批 | 批量脚本 limit/workers 设计 | 是 |

### 3.5 Physics-informed 深测三线（2026-11-04～11-09，文件簇 11-04～11-09）

| 序号 | 具体问题 | 决策 | 改动 | 主路径 |
|------|----------|------|------|--------|
| P18 | Pass2 幻觉数字 | 算子先行；Pass2 强制引 metrics | `physics_metrics.py`、`physics_prompts.py`、`physics_inspect.run_two_pass` | 深测 + `--physics call` |
| P19 | AIA 环带 Δ 在日冕/暗区翻车 | 自适应 0.5d–1.0d；`miss_ring` 启发式 | `ring_audit`、`_refine_miss_ring_heuristic`、`missed_label_candidates_aia` | 是（AIA 轨） |
| P20 | HEK 框 ≠ 全盘亮区普查 | 「可能未标亮区」诊断 **不计分漏标** | `aia_roadshow_aggregate` 九7 政策 | 是 |
| P21 | EPB 不能套 AIA 小环 | band σ + 平场残差 | `_epb_miss_band_audit`、`ring_audit_for_image(EPB)` | 是（EPB 轨） |
| P22 | EPB 1024×512 声明矛盾 | 与 P05 联动对象 QC | `epb_object_qc.py`、`epb_roadshow_aggregate` | 是 |
| P23 | ULF Pass2 传图幻觉/token | Pass2 **文本-only** 引 `window_audit` | `physics_inspect` ULF 分支、`physics_prompts` ULF_PASS2 | 是（ULF 轨） |
| P24 | 无真值 ULF 漏标/虚标 | 好波形参考轨实验 | `ulf_good_bad.py`、`ulf_sliding_window_scan`（**实验**） | 深测部分对象；非 12 目录统一卡 |
| P25 | VLM 要看 dataset 红框而非乱画 | 512 侧轮廓叠加 | `label_overlay.py` | call 路径 |
| P26 | 三模态目录级产出对齐 | 对象 CSV + 审计包 + postprocess | `*_dir_object_qc_csv.py`、`*_roadshow_aggregate.py`、`dir_postprocess.py` | 是 |
| P27 | Agent-Pipeline 可交付、与旧散落脚本分离 | 独立 `package/` + Docker | `Agent-Pipeline/`、`roadshow_paths.py`、`smoke/smoke_test.py`（**冻结三目录**） | **是（镜像源）** |
| P28 | 一键新目录不改 smoke | 检测→QC→后处理 | `agent/run_pipeline.py`；`--physics` 默认 `skip` | **是** |
| P29 | CME/colab 无 matched_events → QC 0 行 | `boxed_only` 漏检 | `run_pipeline`：`n_rows==0` 时追加 `--all-labels` 重跑 | 是 |
| P30 | Gb96 等 review 图与 jsonl 对齐 | 烟测锚点 | `smoke/review_cases.py` | 交付回归 |

### 3.6 泛化 / 路由 / 大 zip（2026-11-19，文件 11-19）

| 序号 | 具体问题 | 决策 | 改动 | 主路径 |
|------|----------|------|------|--------|
| P31 | colab 六类含 HMI/CME/DMSP，不能硬编码目录名 | archetype + 轻量 RAG | `dataset_router/`：`profiler`、`rag_match`、`pipeline_archetypes.json` | 验证 / 待接 v2 |
| P32 | 极小样本 ULF 误判（曾要求 n_csv≥3） | csv + csv.json 成对即可 | `modality_detect`：`n_csv>=1 && n_csv_json>=1` 早退 ULF | **是（现网 detect）** |
| P33 | EPB/AIA 平铺目录投票平局 | mask 面积/顶点启发式 + `epb_score_bias` | `_mask_epb_likelihood`、`_score()` tie-break | **是** |
| P34 | `data/label` 太阳布局误投 EPB | layout 优先 AIA | `has_data_label` → 直接 AIA | **是** |
| P35 | 200GB+ zip 不能落地解压 | tar-in-zip 流式抽样 | `archive_stream.py`、`validate_zip.py`（`--skip-gb` 跳 AIA 大 tar） | 泛化验证 |
| P36 | 流式 profile 与目录 detect 不一致 | 同一规则函数 | `infer_modality_from_profile()` | router 与 detect 对齐 |
| P37 | DMSP `specialShapes` 路由 | schema 覆盖 + archetype | `profiler` annotation 信号、`router_agent.decide_pipeline` | router |
| P38 | AutoDL 无 docker in docker | proot 跑 rootfs | 运维笔记（非代码）；本地 amd64 镜像导出 | 交付环境 |

---

## 4. 三深测：逐项问题登记（比 §3 更贴目录）

### 4.1 AIA `z4h764sf2d`

| 问题 ID | 现象 | 改动要点 | 文件 / 入口 |
|---------|------|----------|-------------|
| A-z4-01 | 规则 0 硬伤 → 100 分，与轮廓问题矛盾 | C13/physics 与 C01–06 分列；证据表分 checkId | `aia_object_qc.py`、aggregate |
| A-z4-02 | 环带 Δ 在日冕误杀 | 自适应环宽、d–环带搜索 | `physics_metrics.ring_audit` |
| A-z4-03 | 亮斑/非 HEK 漏标候选爆炸 | 面积比例限制；诊断九7 | `missed_label_candidates_aia`、aggregate 政策 |
| A-z4-04 | 部分 label 无框被 skipped | 目录 QC 0 行 | `run_pipeline` → `--all-labels` |
| A-z4-05 | API 成本 | Pass1 不终判；limit/workers；关 thinking | `physics_informed_aia.py` |

### 4.2 EPB `fbbqy66u2d`

| 问题 ID | 现象 | 改动要点 | 文件 |
|---------|------|----------|------|
| E-fbb-01 | 1024×512 声明 vs 1024 图/mask | C02/C06 fail | `audits`、`epb_object_qc` |
| E-fbb-02 | 气辉细长暗条非 AR 环 | band_audit | `physics_metrics._epb_miss_band_audit` |
| E-fbb-03 | 模型 batch 只问轮廓 | 不推翻缺文件/__OOV__ | Pass2 prompt + 规则优先 |
| E-fbb-04 | 缺标暗区 | 连通域 + band 指标进 Pass2 | `missed_label_candidates_epb` |

### 4.3 ULF `xfnogkdey9`

| 问题 ID | 现象 | 改动要点 | 文件 |
|---------|------|----------|------|
| U-xf-01 | 窗超出 CSV 末尾 | 波形硬伤 | `waveform_window`、`ulf_object_qc` |
| U-xf-02 | 行数 ≠3600 | 九6 | `audits` + object QC |
| U-xf-03 | Pass2 看图胡说 | Pass2 无图 | `physics_inspect`、`physics_prompts` |
| U-xf-04 | 无金标 C09 | good-bad 实验轨 | `ulf_good_bad.py`（**非**统一 12 目录卡） |
| U-xf-05 | 烟测 offline window | 无 jsonl 也填 windowAudit | `ulf_dir_object_qc_csv` / object qc 校准路径 |

---

## 5. 脚本栈层级（与谁在主路径上）

```text
[L0 路由]  modality_detect（生产） ‖ dataset_router（验证/未来 v2）
[L1 规则]  audits + *_object_qc → 九类 CSV
[L2 物理]  physics_metrics → ring / band / pi2 / miss（本地）
[L3 Pass1] physics_inspect.inspect_pass1
[L4 Pass2] inspect_pass2（ULF 可无图）
[L5 目录]  dir_postprocess / *_roadshow_aggregate

[旁路]     graph.py（单条 LangGraph）
[旁路]     spatial_precision + vision.py（早期轮廓分数 + 单次判决）
[旁路]     hex_score / 六边形综合（30 版探索）
```

| 模块 | 末次修改约 | 为何存在 | 默认镜像用？ |
|------|------------|----------|--------------|
| `modality.py` | 10-27 | 早期单条分类 | 被 `modality_detect` 取代（detect 仍 import audits） |
| `graph.py` | 11-02 | 验证 route + 视觉分支 | 否 |
| `spatial_precision.py` | 10-27 | margin 标定 | 间接（思想进 metrics）；非目录主分 |
| `physics_*.py` | 11-04～11-09 | 深测 Pass1/2 | 仅 `--physics metrics/call` |
| `run_pipeline.py` | 11 月 | 泛化一键 | **是** |
| `dataset_router/*` | 11-19 | 新数据路由 QC | 独立 CLI；未默认写入 run_pipeline |

---

## 6. colab `publish` 六类：规则 vs 视觉

| 数据族 | 典型问题（路由） | 规则默认 | 视觉（call） | 备注 |
|--------|------------------|----------|--------------|------|
| SDO/AIA | data/label | HEK/九类 | prepare_aia | 主路径 |
| HMI | 同 AIA spine | 同左 | 同左 | 无 HMI 专用 prompt |
| CME | 常无框、has_events false | all-labels、完整性 | 有 png+框时同 AIA | 偏事件目录规则 |
| DMSP | specialShapes 平铺 | 当 AIA 框轨 | 同 AIA | RAG：`dmsp_ssusi_aurora` |
| EPB | mask 大 polygon | 九类+尺寸 | prepare_epb | tie-break 见 P33 |
| ULF | flat csv+json | 行数/窗 | Pass1 图 + Pass2 文本 | 小样本见 P32 |

---

## 7. Scientific Debater（新模块，实验路径）

| 阶段 | 作用 | 与主路径关系 |
|------|------|----------------|
| `dataset_router` | 识别 archetype / pipeline | 与生产 detect 并列验证 |
| **scientific_debater** | 多轮辩题 → `auxiliary_metrics.py` → 沙箱标定 → 可选 refine | **仅** `experiments/scientific_debater/`；**不改** 星海舰队 |
| Pass1/2 | 主视觉轨 | 辅助 jsonl **衔接**主库，不替代 `physics_metrics` |

### 7.1 Debater 完整辩题清单（与代码 `phase_manifest.py` 一致）

| 阶段 ID | 模型 | 向模型提出的核心问题（摘要） | 交付物 |
|---------|------|------------------------------|--------|
| `task_context` | **v4-pro** 文本 | RAG 链路上应检索哪些 GitHub/文档关键词？处理目标？与 Pass1/2 主轨差距？ | `## 检索策略 / 处理目标 / 差距` |
| `defect_visual` | **flash** 视觉 + 文本 | 九类在本类图（极光/日冕/磁图/气辉）上的征象？Top5 图像线索？框错位长什么样？何者必须 JSON 规则？ | 缺陷—图像对照 |
| `metric_proposals` | **v4-pro** | 3–5 个 numpy/PIL 标量（梯度、径向 profile、噪声…）+ 标定法 + Pass1/Pass2 分工表 | 指标表 |
| `draft_script` | **v4-pro** | 生成 `auxiliary_metrics(image_path, label_obj)`（不接替 `physics_metrics`） | `auxiliary_metrics_v0.py` |
| `calibrate_v0` | 本地沙箱 | 抽样 PNG 试跑 v0 | `calibration_v0.json` |
| `refine_1…N` | **v4-pro** | 据试跑（+ 可选 `run_pipeline` 规则摘要）修订脚本，直到标量合理 | `v1/v2…` + `calibration_vN.json` |
| `linkage_review` | 报告 | router 结论 + 各轮脚本 diff + 样图标量表 | `DEBATER_DEMO.md` |

**联动实调（DeepSeek，已配置 `secrets.yaml` 的 `model_text_name` / `model_vision_name`）：**

```bash
cd Agent-Pipeline/package/scripts
export MODEL_DISABLE_THINKING=1   # 与 z4 批量一致，缩短首 token 延迟
python3 run_router_debater_linkage.py --publish-demo \
  --secrets ../../../secrets.yaml --max-refine 2 --image-sample 2
```

产出索引：[`experiments/scientific_debater/LINKAGE_INDEX.md`](../experiments/scientific_debater/LINKAGE_INDEX.md)（**2026-11-19 已实调**）；每目录含 **`DEBATER_DEMO.md`**（辩题回答、样图、`v0→v1→v2` diff、标量表）。完整阶段定义另见 `package/agent_modules/scientific_debater/phase_manifest.py`。

离线烟测（无 API）：

```bash
python3 run_scientific_debater.py --smoke-publish --offline
```

对应你举例的三类图：**CME 日冕仪**、**HMI 磁图**、**DMSP 极光伪彩**（演示含 **EPB 气辉**）。

### 7.2 深测辅助脚本作「教学模型」、不压制新数据（详见专文）

[`docs/Scientific_Debater_教学与主轨隔离.md`](Scientific_Debater_教学与主轨隔离.md)

要点：

- **教结构**（Pass 前/中/后 + `prepare_*` vs `ring|band|window_audit`），**不教** `physics_metrics` 全文。
- Debater 多文件 **v0/v1/v2 = refine**，不是多条生产链；终版 `auxiliary_metrics.py` 为试跑 **择优**。
- `teaching_spine.json` + `--teaching-mode auto|meta_only|spine_full` 门控：DMSP/CME 等 **far** 时只给类比句，禁止抄环带/band 符号。
- 会话内可审计：`experiments/.../TEACHING_CONTEXT.md`。

---

## 8. dataset_router + RAG（能力边界）

| 能力 | 实现 | 自动生成新 Python track？ |
|------|------|---------------------------|
| layout / schema | `profiler.py` | 否 |
| 少量图像 tags | `visual_probe.py` | 否 |
| 文档链 RAG | `rag_match.py` + `REFERENCE_LINKS.md` | 否 |
| `physics_track` 名 | `pipeline_archetypes.json` | 需人加 metrics |
| 大 zip | `archive_stream.py` | — |

---

## 9. 复现命令

```bash
# colab 全目录 router 验证
cd Agent-Pipeline/package/agent_modules
PYTHONPATH=. python -m dataset_router.validate --root colab_subset/publish

# 极小 json 抽样
PYTHONPATH=. python -m dataset_router.validate_subsample --root colab_subset/publish --json-cap 2

# OPC zip 流式（默认跳过 >2GB tar）
PYTHONPATH=. python -m dataset_router.validate_zip \
  --zip /Volumes/KESU/OPC_路演测试数据.zip --skip-gb 2

# 生产式一键（仍用 modality_detect）
python Agent-Pipeline/agent/run_pipeline.py --dir <dirId路径>
```

---

## 10. 与聊天导出的关系

- **全量叙事、token、面板、Docker 体积辩论**：`空间科学/cursor_data_extraction_from_zip_file.md`（文首有 2026-11-19 导航）。  
- **本文**：**问题—改动—是否在主路径** 登记 + 时间序；答辩/泛化接 `run_pipeline --router v2` 时以 §3.6、§7 为 backlog。

**文档版本**：2026-11-19 · 细粒度修订（无 git 时间线，已标注 mtime 局限）· 与 `modality_detect`、`dataset_router` 同步。