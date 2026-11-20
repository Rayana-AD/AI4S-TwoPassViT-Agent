#!/usr/bin/env python3
"""After EPB object CSV: bundle + 评分卡 + 排序 + 路演结果行 + 审计日志."""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from datetime import datetime, timezone

from roadshow_paths import RESULTS_DIR, ensure_agent_path

ensure_agent_path()

from epb_roadshow_aggregate import (  # noqa: E402
    append_audit_log,
    patch_roadshow_results_csv,
    roadshow_result_row,
    write_directory_bundle,
    write_severity_and_scorecard,
)

DIR_ID = "EPB_seg_sample_fbbqy66u2d"


def main() -> None:
    object_csv = os.path.join(RESULTS_DIR, f"{DIR_ID}_EPB对象质检.csv")
    if not os.path.isfile(object_csv):
        raise SystemExit(f"Missing {object_csv}")
    t0 = time.perf_counter()
    manifest = write_directory_bundle(object_csv, RESULTS_DIR, dir_id=DIR_ID, n_labels_total=788)
    extras = write_severity_and_scorecard(
        object_csv,
        RESULTS_DIR,
        manifest,
        scorecard_template=os.path.join(RESULTS_DIR, "评分卡_EPB_fbbqy.json"),
    )
    manifest["outputs"].update(extras)
    rr = roadshow_result_row(DIR_ID, manifest["audit"])
    patch_roadshow_results_csv(
        os.path.join(RESULTS_DIR, "路演结果_待填队名.csv"),
        rr,
        dir_id=DIR_ID,
    )
    entry = {
        "time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "pipeline": "epb_fbbqy_postprocess",
        "dirId": DIR_ID,
        "ruleVersions": manifest.get("ruleVersions"),
        "randomSeed": 0,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "total_sec": round(time.perf_counter() - t0, 2),
        "outputs": manifest.get("outputs"),
    }
    append_audit_log(os.path.join(RESULTS_DIR, "审计日志.jsonl"), entry)
    append_audit_log(os.path.join(RESULTS_DIR, "系统运行日志.jsonl"), entry)
    out = os.path.join(RESULTS_DIR, f"{DIR_ID}_pipeline_summary.json")
    json.dump(entry, open(out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps(entry, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
