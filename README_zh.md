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

![两阶段管线](docs/gallery/architecture_two_pass_pipeline.jpg)

**扩展轨（非基准目录）：** `dataset_router` → 可选 `scientific_debater`（v0→v1→v2）→ 环境变量门控注入 Pass1。

![双轨分流](docs/gallery/dual_track_router_overview.png)

---

## 可视化 Gallery

### 三模态主轨（规则 + 两阶段）

| AIA 太阳 EUV | EPB 气辉 | ULF 脉动 |
|:---:|:---:|:---:|
| ![](docs/gallery/modality_aia_solar_euv.png) | ![](docs/gallery/modality_epb_airglow.png) | ![](docs/gallery/modality_ulf_magnetometer.png) |

### 扩展轨（单帧示意，非整目录）

| EPB 叠加质检 | DMSP 极光 UV | CME 日冕仪 | AIA 活动区（降采样） |
|:---:|:---:|:---:|:---:|
| ![](docs/gallery/sample_epb_overlay_qc.png) | ![](docs/gallery/sample_dmsp_aurora_uv.png) | ![](docs/gallery/sample_cme_coronagraph.png) | ![](docs/gallery/sample_aia_active_region.png) |

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