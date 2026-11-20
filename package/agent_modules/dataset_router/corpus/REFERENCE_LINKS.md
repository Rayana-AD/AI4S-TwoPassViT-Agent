# 空间科学数据处理 / 标准化流水线 — 参考链接（Router RAG 语料）

用于数据集**格式与处理规范**检索，供 `pipeline_archetypes.json` 引用。更新时请同步 JSON 内 `references` 数组。

## 太阳 / SDO / HEK

| 说明 | URL |
| --- | --- |
| AIA 数据处理（Level 1.0→1.5、aia_prep） | https://lmsal.com/sdodocs/doc/dcur/SDOD0060.zip/zip/entry/sdoguidese7.html |
| SDO 数据分析导览（PDF） | https://aia.cfa.harvard.edu/trace/SSXG/ynsu/Ji/SDO_Data_Analysis_guide.pdf |
| HEK API / Annotator | https://lmsal.com/hek/api.html |
| HEK 综述论文 | https://doi.org/10.1007/s11207-010-9624-2 |
| HMI JSOC | https://jsoc.stanford.edu/ |
| LASCO CME 列表 | https://cdaw.gsfc.nasa.gov/CME_list/ |

## 电离层 / DMSP SSUSI

| 说明 | URL |
| --- | --- |
| CDAWeb SSUSI 骨架表 | https://cdaweb.gsfc.nasa.gov/pub/software/cdawlib/0SKELTABLES/dmspf18_r0_ssusi_00000000_v01.skt |
| pysatNASA `dmsp_ssusi` | https://pysatnasa.readthedocs.io/en/develop/_modules/pysatNASA/instruments/dmsp_ssusi.html |
| JHUAPL SSUSI 数据产品 | http://ssusi.jhuapl.edu/data_products |
| NOAA DMSP 传感器格式说明（PDF） | https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/dmsp/doc/AFRL%20ASCII%20and%20Binary%20File%20Format%20Descriptions.pdf |

## 地磁 / ULF（INTERMAGNET）

| 说明 | URL |
| --- | --- |
| INTERMAGNET 技术手册（数据格式附录） | https://tech-man.intermagnet.org/latest/appendices/dataformats.html |
| ImagCDF 技术说明 TN8 | https://intermagnet.org/docs/technical/im_tn_8_ImagCDF.pdf |
| 数据下载门户 | https://intermagnet.org/data_download.html |
| geomag-lib-python（含 CSV 写出） | https://github.com/INTERMAGNET/geomag-lib-python |

## OPC / 智能就绪数据集（赛题上下文）

赛题包内为 JSON 标注 + png/csv 成对结构；本模块以 **标注 schema 字段**（`hek_event_annotation`、`science_annotation.mask`、`ulf_event_annotation`）与 **目录拓扑** 对齐上表流水线，而非依赖 `dirId` 字符串。