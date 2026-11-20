# Dataset Router（泛化目录识别 Subagent）

独立于 `modality_detect` 手写投票，用于：**少量采样 → 目录 schema + 视觉特征 → RAG 匹配标准流水线原型 → 推荐 QC 管线（AIA/EPB/ULF）**。

## 流程

```text
profile_directory()     # JSON 字段统计 + 布局拓扑 + 2–4 张图视觉探针
       ↓
match_profile()         # 与 corpus/pipeline_archetypes.json 打分（链接级 RAG）
       ↓
route_dataset_directory()  # 合并规则 override + 可选 legacy_detect 对照
```

## 语料

- `corpus/pipeline_archetypes.json`：SDO/AIA、HMI、LASCO CME、DMSP SSUSI、EPB 气辉、ULF 地磁等 **数据处理/格式** 参考链接（非主题论文堆砌）。
- `corpus/REFERENCE_LINKS.md`：人类可读的链接索引。

## 校验

**全量目录（已解压）：**

```bash
cd Agent-Pipeline/package/agent_modules
PYTHONPATH=. python -m dataset_router.validate --root /path/to/colab_subset/publish
```

**极小样本（模拟 12×2，json_cap=2）：**

```bash
PYTHONPATH=. python -m dataset_router.validate_subsample --root colab_subset/publish --json-cap 2
```

**OPC 路演 zip（流式读 tar，不落盘；默认跳过压缩体 >2GB 的 AIA tar）：**

```bash
PYTHONPATH=. python -m dataset_router.validate_zip \
  --zip /Volumes/KESU/OPC_路演测试数据.zip \
  --skip-gb 2 --json-sample 12
```

对大 AIA 单独抽检（耗时长，只扫 tar 头 + 少量 json/png）：

```bash
PYTHONPATH=. python -m dataset_router.validate_zip --zip ... --only AIA_AR_sample_z4h764sf2d --skip-gb 20
```

**V34 大 zip** 为多分片 `publish.tar.gz.part-*`，需先按包内说明合并后再挂载；router 只依赖目录内 schema，合并后可用 `validate` / `validate_subsample`。

通过标准：与目录名前缀约定（AIA/HMI/CME/DMSP→AIA，EPB→EPB，ULF→ULF）一致率 ≥ 设定阈值；并打印 `legacy_detect` 对照。

## 与星海舰队衔接（待办）

在 `run_pipeline.py` 增加可选 `--router v2`，用 `route_dataset_directory` 替代 `detect_modality_from_directory`；**不改动** physics_metrics / Pass1/Pass2。

## Scientific Debater（router 之后）

路由完成后可调用 **scientific_debater** 模拟「提问题 → 写辅助规则脚本 → 试跑 → 纠偏」，产物只在 `Agent-Pipeline/experiments/scientific_debater/`：

```bash
python ../scripts/run_scientific_debater.py --smoke-publish --offline
```

详见 `../scientific_debater/README.md`。