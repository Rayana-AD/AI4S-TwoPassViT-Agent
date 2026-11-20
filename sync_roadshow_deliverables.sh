#!/usr/bin/env bash
# Sync authoritative roadshow outputs (2026-11-05 full orchestrator run) into Agent-Pipeline/交付/.
# Does NOT copy 路演交付/06-三目录全评测 中的 legacy AIA全目录模型.jsonl 等早期产物。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AP="$(cd "$(dirname "$0")" && pwd)"
RES="$ROOT/路演结果"
DEL="$AP/交付"
REQ="$ROOT/路演要求"

MANIFEST="$RES/roadshow_orchestrator_manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
  echo "Missing $MANIFEST — run roadshow_full_orchestrator first." >&2
  exit 1
fi

FINISHED="$(python3 -c "import json; print(json.load(open('$MANIFEST'))['finished'])")"
echo "Provenance: orchestrator finished $FINISHED"

mkdir -p "$DEL"/{01-运行记录,02-提交简表,03-对象质检,04-目录审计与评分,05-physics与证据,06-烟测对照,07-规范引用}

copy() {
  local src="$1" dest="$2"
  if [[ -f "$src" ]]; then
    cp -f "$src" "$dest"
    echo "  ok $(basename "$dest")"
  else
    echo "  skip missing $(basename "$src")" >&2
  fi
}

echo "== 01 运行记录 =="
copy "$MANIFEST" "$DEL/01-运行记录/roadshow_orchestrator_manifest.json"
copy "$RES/roadshow_preflight.json" "$DEL/01-运行记录/roadshow_preflight.json"
copy "$RES/系统运行日志.jsonl" "$DEL/01-运行记录/系统运行日志.jsonl"
copy "$RES/审计日志.jsonl" "$DEL/01-运行记录/审计日志.jsonl"
copy "$RES/运行记录.json" "$DEL/01-运行记录/运行记录.json"
if [[ -f "$RES/roadshow_three_modal_rerun.log" ]]; then
  tail -n 400 "$RES/roadshow_three_modal_rerun.log" > "$DEL/01-运行记录/roadshow_three_modal_rerun.log.tail"
fi
for tag in AIA_AR_sample_z4h764sf2d EPB_seg_sample_fbbqy66u2d ULF_sample_xfnogkdey9; do
  copy "$RES/${tag}_pipeline_summary.json" "$DEL/01-运行记录/${tag}_pipeline_summary.json"
  if [[ -f "$RES/${tag}_pipeline.log" ]]; then
    tail -n 200 "$RES/${tag}_pipeline.log" > "$DEL/01-运行记录/${tag}_pipeline.log.tail"
  fi
done

echo "== 02 提交简表（路演要求 §6） =="
copy "$RES/路演结果_待填队名.csv" "$DEL/02-提交简表/路演结果_待填队名.csv"
copy "$RES/证据表_待填队名.csv" "$DEL/02-提交简表/证据表_待填队名.csv"
if [[ -f "$RES/组内比较与排序说明.md" ]]; then
  copy "$RES/组内比较与排序说明.md" "$DEL/02-提交简表/组内比较与排序说明.md"
fi
python3 - <<'PY' "$RES" "$DEL/02-提交简表/三目录深测_路演结果行.csv"
import csv, os, sys
res, out = sys.argv[1], sys.argv[2]
ids = [
    "AIA_AR_sample_z4h764sf2d",
    "EPB_seg_sample_fbbqy66u2d",
    "ULF_sample_xfnogkdey9",
]
src = os.path.join(res, "路演结果_待填队名.csv")
rows_by_id = {}
fieldnames = None
with open(src, newline="", encoding="utf-8") as f:
    r = csv.DictReader(f)
    fieldnames = list(r.fieldnames or [])
    for row in r:
        if row.get("dirId") in ids:
            rows_by_id[row["dirId"]] = row
# 深测 ULF 可能尚未写回 12 行总表：从单目录路演结果行补一行（列对齐）
for did in ids:
    if did in rows_by_id:
        continue
    per = os.path.join(res, f"{did}_路演结果行.csv")
    if not os.path.isfile(per):
        continue
    with open(per, newline="", encoding="utf-8") as f:
        pr = csv.DictReader(f)
        prow = next(iter(pr), None)
    if not prow:
        continue
    ds = did.split("_sample_")[0] + "_sample" if "_sample_" in did else did
    rows_by_id[did] = {
        "datasetId": ds,
        "datasetVersion": prow.get("datasetVersion", ""),
        "dirId": did,
        "rankInDataset": prow.get("rankInDataset", ""),
        "rankGlobal": prow.get("rankGlobal", ""),
        "totalScore": prow.get("totalScore", ""),
        "mainDefectTypes": prow.get("defectKinds") or prow.get("mainDefectTypes", ""),
        "evidence": prow.get("note") or prow.get("evidence", ""),
    }
rows = [rows_by_id[i] for i in ids if i in rows_by_id]
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)
print(f"  ok 三目录深测_路演结果行.csv ({len(rows)} rows)")
if len(rows) < 3:
    print("  warn: 总表缺深测行，请重跑 evaluate_roadshow 刷新 路演结果_待填队名.csv", file=sys.stderr)
PY

echo "== 03 对象质检 =="
for f in \
  AIA_AR_sample_z4h764sf2d_AIA对象质检.csv \
  AIA_AR_sample_z4h764sf2d_AIA对象质检.json \
  EPB_seg_sample_fbbqy66u2d_EPB对象质检.csv \
  EPB_seg_sample_fbbqy66u2d_EPB对象质检.json \
  ULF_sample_xfnogkdey9_ULF对象质检.csv \
  ULF_sample_xfnogkdey9_ULF对象质检.json
do
  copy "$RES/$f" "$DEL/03-对象质检/$f"
done

echo "== 04 目录审计与评分 =="
for f in \
  AIA_AR_sample_z4h764sf2d_AIA目录审计包.json \
  AIA_AR_sample_z4h764sf2d_AIA审计指标.csv \
  AIA_AR_sample_z4h764sf2d_AIA证据汇总.csv \
  AIA_AR_sample_z4h764sf2d_路演结果行.csv \
  AIA_AR_sample_z4h764sf2d_缺陷严重程度排序.csv \
  AIA_AR_sample_z4h764sf2d_缺陷统计摘要.md \
  AIA_AR_sample_z4h764sf2d_HEK上下文_汇总.csv \
  评分卡_AIA_z4_aia_qc.json \
  EPB_seg_sample_fbbqy66u2d_EPB目录审计包.json \
  EPB_seg_sample_fbbqy66u2d_EPB审计指标.csv \
  EPB_seg_sample_fbbqy66u2d_EPB证据汇总.csv \
  EPB_seg_sample_fbbqy66u2d_路演结果行.csv \
  EPB_seg_sample_fbbqy66u2d_缺陷严重程度排序.csv \
  EPB_seg_sample_fbbqy66u2d_缺陷统计摘要.md \
  评分卡_EPB_fbbqy_epb_qc.json \
  ULF_sample_xfnogkdey9_ULF目录审计包.json \
  ULF_sample_xfnogkdey9_ULF审计指标.csv \
  ULF_sample_xfnogkdey9_ULF证据汇总.csv \
  ULF_sample_xfnogkdey9_路演结果行.csv \
  ULF_sample_xfnogkdey9_缺陷严重程度排序.csv \
  评分卡_ULF_xfnog_ulf_qc.json
do
  copy "$RES/$f" "$DEL/04-目录审计与评分/$f"
done

echo "== 05 physics 与证据 =="
for f in \
  AIA_physics_informed.jsonl \
  EPB_physics_informed.jsonl \
  ULF_physics_informed.jsonl \
  AIA_physics_informed_证据表.csv \
  EPB_physics_informed_证据表.csv \
  ULF_physics_informed_证据表.csv
do
  copy "$RES/$f" "$DEL/05-physics与证据/$f"
done

echo "== 06 烟测 =="
copy "$AP/smoke/last_run.json" "$DEL/06-烟测对照/smoke_last_run.json"
copy "$AP/smoke/review_cases_last.json" "$DEL/06-烟测对照/review_cases_last.json"

echo "== 07 规范引用 =="
for f in README.md 01_现场展示数据清单.md 02_选手展示和自测要求.md; do
  copy "$REQ/$f" "$DEL/07-规范引用/$f"
done
copy "$AP/experiments/Requirements_Notes_泛化与实测.md" "$DEL/07-规范引用/Requirements_Notes_泛化与实测.md"

echo "== Agent-Pipeline/results 轻量索引 =="
mkdir -p "$AP/results"
for f in roadshow_orchestrator_manifest.json speed_rules_check.json \
  AIA_AR_sample_z4h764sf2d_AIA目录审计包.json \
  EPB_seg_sample_fbbqy66u2d_EPB目录审计包.json \
  ULF_sample_xfnogkdey9_ULF目录审计包.json
do
  copy "$RES/$f" "$AP/results/$f"
done

python3 - <<PY
import json, os, hashlib
from datetime import datetime, timezone

ap = "$AP"
deliver = "$DEL"
res = "$RES"
finished = "$FINISHED"

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]

key_files = [
    f"{deliver}/01-运行记录/roadshow_orchestrator_manifest.json",
    f"{deliver}/05-physics与证据/AIA_physics_informed.jsonl",
    f"{deliver}/05-physics与证据/EPB_physics_informed.jsonl",
    f"{deliver}/05-physics与证据/ULF_physics_informed.jsonl",
    f"{deliver}/04-目录审计与评分/评分卡_AIA_z4_aia_qc.json",
]
meta = {
    "synced_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "orchestrator_finished": finished,
    "source_dir": res,
    "rule_track": {
        "C01-C05": "rules-roadshow-20261102",
        "physics_pass": "physics-informed-v1",
        "object_qc": {"AIA": "aia-qc-v2", "EPB": "epb-qc-v1", "ULF": "ulf-qc-v1"},
    },
    "excluded_on_purpose": [
        "路演交付/06-三目录全评测/AIA全目录模型.jsonl（早期非 physics-informed 轨）",
        "交付物/03-公开集实测/*",
        "colab_subset publish 30 版本评测",
    ],
    "key_file_sha256_prefix": {os.path.basename(p): sha256(p) for p in key_files if os.path.isfile(p)},
}
out = f"{deliver}/SYNC_MANIFEST.json"
json.dump(meta, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"  wrote {out}")
PY

echo "Done → $DEL (see 交付/README.md)"
