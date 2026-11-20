# OPC 交付清单 v2.3 对照自查 · 星海舰队

> 生成/刷新：`python3 Agent-Pipeline/build_pack.py`  
> 计分与 jsonl 权威源：**`Agent-Pipeline/交付/`**（非 `路演交付/06-三目录全评测`）。

## 1. 目录布局（DEL 第三节）

| 要求路径 | 状态 | 说明 |
| --- | --- | --- |
| `00_MANIFEST.yaml` + `SHA256SUMS.txt` | ✅ | 打包脚本维护 |
| `01`–`03`、`09`、`10` | ✅ | 正文在提交包根 |
| `04_评分卡/` ×12 json+html | ✅ | 来自 `交付/12目录批处理/` |
| `05_排序表/` | ⚠️ | `ranking_global.csv` 列与赛方模板 **部分一致**（见下） |
| `06_问题清单/` | ✅ | 536 条，源自 `证据表_星海舰队.csv` |
| `07_证据索引/` | ⚠️ | 索引 CSV 齐全；`evidence/` 为大对象指向母包 `交付/` |
| `08_运行日志/` | ⚠️ | `run.log.jsonl` 为编排审计日志，字段与 DEL-9 理想 schema **未逐列对齐** |
| `11_展示材料/` | ✅ | PPT + 路演结果/证据表 + 运行记录 |
| **`agent/`**（6×YAML） | ✅ | 仅此一处编排 YAML |
| **`image/`** | ✅ | `星海舰队_image.tar` + Dockerfile + compose + README |
| **`source/`** | ✅ | 源码快照；**不含 `docker/`** |

### 为何曾出现 image 与 source 都含 Docker？

早期 `build_pack` 把开发树 `Agent-Pipeline/docker/` 整目录 rsync 进 `source/`，又把 Dockerfile 复制进 `image/`，造成 **重复且命名混淆**（`image/` 被误当作“所有镜像相关文件的垃圾桶”）。现按 v2.3 拆分：

- **`image/`** = 评委加载运行的 **镜像产物 + 构建入口**  
- **`source/`** = **Python 源码**（package、smoke、docs、run_pipeline）  
- 开发机构建脚本仍在仓库 `Agent-Pipeline/docker/`，**不进入提交包 source/**

## 2. 分项符合度

| DEL | 符合 | 差距 / 处置 |
| --- | --- | --- |
| DEL-1 方案 | ✅ | 与 PPT、架构图一致 |
| DEL-2 可运行 | ✅ | 布局已按上表整理 |
| DEL-3 部署说明 | ✅ | 含烟测、回查、无 z4 跳过 AIA |
| DEL-4 评价规范 | ⚠️ | 正文偏长；机器可读 `03_评价规范.yaml` 为规则版本摘要，非全量 checkId 表 |
| DEL-5 评分卡 | ✅ | 12 目录 |
| DEL-6 排序表 | ⚠️ | 当前 CSV 为赛方 **§6.1 路演结果表** 列（`datasetId,dirId,rankGlobal,totalScore…`）；DEL-6 模板列 `rank,dimensionScores,groupId…` 见 `ranking_explanation.md` 文字说明 |
| DEL-7–8 | ✅/⚠️ | 见上 |
| DEL-9–10 | ⚠️ | 日志/schema 可后续映射脚本增强 |
| DEL-11 | ✅ | 含 Agent/泛化后续方案 |
| DEL-12 | ✅ | 三模态 demo 拼接 ≤5min |
| DEL-13 | ℹ️ | 现场答辩；`13_现场答辩记录.md` 为实录摘要（赛方树状图未单列） |

## 3. 声明

- 12 目录结果与 PPT 数字来自同一 `路演结果_星海舰队.csv`。  
- Docker 烟测：**EPB+ULF 可通过**即内部验收；缺 AIA 数据时跳过 AIA。  
- 对象级 Pass2 复现依赖挂载 `交付/05` 冻结 jsonl，不要求评委重跑全量 VLM。
