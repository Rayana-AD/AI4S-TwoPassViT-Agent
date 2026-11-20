# AI4S Two-Pass ViT Agent

**简体中文** · [English](README.md)

面向空间科学多模态数据（太阳极紫外成像、电离层气辉掩膜、地磁脉动时序及扩展仪器族）的**物理约束 + 两阶段大模型**质量评价智能体，并可选接入 **Dataset Router** 与 **Scientific Debater** 扩展轨。

> **保密说明：** 本仓库仅公开**源码、文档与少量降采样示意样本**，不含完整竞赛数据集、合作方标识材料或 API 密钥。

---

## 速览

| | |
|---|---|
| **背景** | 官方评测类 OPC 数据质检：AIA / EPB / ULF 等；纯端到端 VLM 在弥散背景与时序波形上易产生幻觉、缺乏可复核数值链。 |
| **方法** | 本地**确定性物理 / 几何算子** → **Pass1** 感知初判 → 脚本审计指标 → **Pass2** 终审（强制引用标量）；新目录经 **Router** 画像分派；**Debater** 在沙箱中迭代 `auxiliary_metrics.py` 衔接主轨。 |
| **创新点** | 12 个基准目录**双轨回退**（规则专用、关闭 Debater）；**门控 Teaching**；**分级 Memory**；模型生成代码 **AST 沙箱**；Docker + 烟测 / 扩展自检门禁。 |
| **结果** | 完成基准目录对象级 QC 与六维评分交付；公开子集路由回归 **6 族 30 目录 100% 命中**；EPB / DMSP / CME 等扩展族离线 Debater 链路可审计；提供 `linux/amd64` 容器镜像构建。 |

---

## 架构示意

### 1）统一入口 `run_pipeline.py`（基准集 vs 扩展轨）

```mermaid
flowchart TD
  IN([待检目录]) --> GATE{dirId 属于冻结的<br/>12 个基准目录?}
  GATE -->|是| RULE[规则轨 modality_detect]
  GATE -->|否| ROUTER[Dataset Router<br/>画像 + 视觉探针 + RAG]
  RULE --> MOD{AIA / EPB / ULF}
  ROUTER --> MOD
  MOD --> DEB{Debater?}
  DEB -->|12 目录: 强制关闭| QC
  DEB -->|扩展目录: 可选| DEBATER[Scientific Debater<br/>v0→v1→v2 沙箱]
  DEBATER -->|DEBATER_AUXILIARY_SCRIPT| QC
  DEB -->|off| QC[对象级 QC 脚本]
  QC --> PHYS[physics_informed_*<br/>Pass1 + Pass2]
  PHYS --> CSV[对象 CSV + jsonl]
  CSV --> PP{后处理?}
  PP -->|是| POST[dir_postprocess 评分卡]
  PP -->|否| OUT([ROADSHOW_RESULTS])
  POST --> OUT
```

### 2）单样本两阶段（先算后判，Pass2 必须引用数值）

```mermaid
flowchart LR
  subgraph prep [本地 prepare_*]
    R0[规则预检<br/>配对/越界]
    R1[物理算子<br/>环带/窄带/滤波]
    R2[叠加图或波形图]
  end
  subgraph p1 [Pass1]
    V1[视觉或文本模型<br/>结构理解 + 候选]
  end
  subgraph mid [脚本审计]
    M1[环带/带通/窗口审计]
    M2[漏标候选合并]
  end
  subgraph p2 [Pass2]
    V2[视觉 AIA EPB 或<br/>纯文本 ULF]
    V2rule[理由须含算子数值]
  end
  R0 --> R1 --> R2 --> V1 --> M1 --> M2 --> V2
  V2 --> V2rule --> JOUT([objectOverall])
```

| 模态 | Pass1 | 典型算子 | Pass2 |
|------|-------|----------|-------|
| **AIA** | 日冕 EUV + 标注叠加 | 外向环带对比度 Δ、漏标亮斑候选 | 视觉终审 |
| **EPB** | 气辉 + 掩膜叠加 | 外扩窄带耗空 σ、面积比 | 视觉终审 |
| **ULF** | 滤波波形图（Pass2 **不传图**） | 带通包络、峰噪比、能量窗 | **纯文本**终审 |

### 3）ULF 专用链路（与赛题流程图一致）

```mermaid
flowchart TB
  U0[ULF 规则<br/>csv/json 配对 时段窗] --> U1[prepare_ulf<br/>6.7–25 mHz 滤波 + 包络]
  U1 --> U2[Pass1 波形理解<br/>threshold_proposal window_audit]
  U2 --> U3[中间脚本<br/>合并阈值 重叠 PI2 分类]
  U3 --> U4[Pass2 文本模型<br/>miss_burst_audit 数值终裁]
  U4 --> U5[写入 ULF 对象质检 CSV]
```

### 4）扩展轨：Debater 衔接主轨（环境变量门控）

```mermaid
flowchart LR
  RT[Router 原型] --> TCH[Teaching 门控<br/>同族/远族分级]
  TCH --> PH[辩题阶段<br/>任务→视觉→指标→草案]
  PH --> V0[v0 脚本]
  V0 --> SB[AST 沙箱 lint + 试跑]
  SB --> V1[v1 样本校准]
  V1 --> V2[v2 自审 refine]
  V2 --> BR[auxiliary_bridge 可选]
  BR --> P1[注入 Pass1 上下文]
```

图例：**实线框** = 本地 Python 确定性步骤；**12 基准目录**不走 Debater 注入评分路径。

---

## 方法亮点

### 与传统 Agent 架构：联系与区别

| 常见范式（ReAct / 多 Agent 协作 / Tool Calling） | 本项目 |
|-----------------------------------------------|--------|
| 模型循环规划并调工具，数值常在文本里「猜」 | **先本地物理脚本算指标**，Pass2 **必须引用**算子输出 |
| 长期向量记忆、跨任务共享 | **分级记忆**：评测 run 隔离；辩题 **按 v0/v1/v2 切片** 防膨胀 |
| 多角色开放式协商 | **单编排器 + 固定辩题 DAG**，交付物是可执行 `auxiliary_metrics.py` |
| 通用文档 RAG | **Router 原型 RAG** + **门控 Teaching**（只教结构，远族降级） |
| 模型即评分器 | **模型做终审**；九类缺陷与 CSV 由 **规则轨 + 接地 Pass2** 产出 |
| 任意 Python 执行 | 仅 Debater 草稿进 **AST 沙箱**；主轨逻辑不变 |

仍采用现代栈常见组件：**LangGraph**（规则图）、结构化 Prompt、可选 API、**smoke / verify** 回归门禁。

### 安全性与可信

| 层级 | 做法 |
|------|------|
| **抗幻觉** | Pass2 强制引用环带/窄带/时间窗数值；ULF Pass2 **纯文本**读预计算序列，不传波形图 |
| **权限分离** | 12 个基准 `dirId` **仅规则轨**，强制关闭 Debater 桥接，成绩零漂移 |
| **不可信代码** | `script_sandbox`：AST 白名单 import、禁止写文件、`eval` 封禁、返回值 JSON 可序列化 |
| **可选注入** | 仅当设置 `DEBATER_AUXILIARY_SCRIPT`；默认主轨与初版一致 |
| **供应链** | 仓库无密钥；`secrets.yaml` 运行时挂载；Docker + 固定依赖 |
| **可审计** | Teaching / 演进 / 对话落盘；烟测指纹 `last_run.json` |

---

## Gallery（方法示意，非封面）

三模态九类缺陷质检对照总览：

![九类缺陷对照总览](docs/gallery/method/nine_defect_taxonomy_overview.png)

### AIA — 多边形叠加 → 环带算子 → Pass2

| Pass1：JSON 轮廓叠加在日冕 EUV 上 |
|:---:|
| ![](docs/gallery/method/aia_pass1_polygon_overlay.png) |

### EPB — 掩膜叠加 → 外扩窄带耗空审计

| Pass1 掩膜叠加 | Pass2 带域 / 残差审计示意 |
|:---:|:---:|
| ![](docs/gallery/method/epb_pass1_label_overlay.png) | ![](docs/gallery/method/epb_pass2_band_audit.png) |

### ULF — 带通/包络管线（演示片三连帧）

| 帧 1 | 帧 2 | 帧 3 |
|:---:|:---:|:---:|
| ![](docs/gallery/method/ulf_pipeline_frame_01.png) | ![](docs/gallery/method/ulf_pipeline_frame_02.png) | ![](docs/gallery/method/ulf_pipeline_frame_03.png) |

配套短视频：[ulf_signal_pipeline_demo.mp4](docs/media/ulf_signal_pipeline_demo.mp4)

### 扩展仪器族（单帧脱敏）

| DMSP 极光 UV | CME 日冕仪 |
|:---:|:---:|
| ![](docs/gallery/sample_dmsp_aurora_uv.png) | ![](docs/gallery/sample_cme_coronagraph.png) |

三模态概要海报（仅作导读）：[AIA](docs/gallery/modality_aia_solar_euv.png) · [EPB](docs/gallery/modality_epb_airglow.png) · [ULF](docs/gallery/modality_ulf_magnetometer.png)

详见 [docs/gallery/README.md](docs/gallery/README.md)。

---

## 短视频示意

| 文件 | 内容 |
|------|------|
| [agent_workflow_demo.mp4](docs/media/agent_workflow_demo.mp4) | 智能体端到端工作流概览 |
| [ulf_signal_pipeline_demo.mp4](docs/media/ulf_signal_pipeline_demo.mp4) | ULF 带通 / 包络与文本终审轨 |

---

## 快速开始

```bash
docker build --platform linux/amd64 -f docker/Dockerfile -t space-science-agent:latest .
docker run --rm -v /path/to/data:/data:ro -e ROADSHOW_DATA=/data \
  space-science-agent:latest smoke/smoke_test.py
```

```bash
python3 smoke/check_pipeline_completeness.py
python3 smoke/verify_extended_pipeline.py
python3 agent/run_pipeline.py --dir /path/to/dataset --limit 5 --router auto --debater offline
```

环境变量：`ROADSHOW_DATA`、`ROADSHOW_RESULTS`、`AGENT_PIPELINE_ROOT`；Pass1/Pass2 在线重跑需自备 `secrets.yaml`。

---

## 目录结构

| 路径 | 说明 |
|------|------|
| `package/agent_modules/` | 物理指标、QC、Router、Debater |
| `package/scripts/` | 目录 / 对象 CSV 流水线 |
| `agent/` | `run_pipeline.py` 与智能体声明 |
| `smoke/` | 烟测与扩展自检 |
| `docker/` | amd64 镜像 |
| `docs/` | 九类缺陷说明、Gallery、演示媒体 |

---

## 数据与引用

完整路演数据请通过赛方 / 数据提供方正规渠道获取，**禁止**通过本仓库传播原始数据包。使用代码请注明本仓库地址。

问题反馈：[GitHub Issues](https://github.com/Rayana-AD/AI4S-TwoPassViT-Agent/issues)。