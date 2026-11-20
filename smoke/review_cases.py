#!/usr/bin/env python3
"""Optional dev check: a few fixed PNGs (AIA/EPB) for offline physics-prep metrics — not the main smoke gate (see smoke_test.py)."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "package")
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))
os.environ.setdefault("AGENT_PIPELINE_ROOT", ROOT)
os.environ.setdefault("ROADSHOW_REPO_ROOT", os.path.dirname(ROOT))

from roadshow_paths import dir_aia_primary, dir_epb_primary, ensure_agent_path  # noqa: E402

ensure_agent_path()

from physics_inspect import prepare_aia, prepare_epb  # noqa: E402
from epb_object_qc import qc_epb_object  # noqa: E402
from aia_object_qc import qc_aia_object  # noqa: E402


def _check_epb_09u() -> dict:
    oid = "09u_N3cnKxe68a0ma7Bc.png"
    d = dir_epb_primary()
    img = os.path.join(d, oid)
    lab = os.path.join(d, oid.replace(".png", ".json"))
    item = prepare_epb(img, lab)
    row = qc_epb_object(os.path.basename(d), img, lab, miss_mode="fast")
    rings = (item.get("metrics") or {}).get("labeled_regions") or []
    band = None
    for r in (item.get("metrics") or {}).get("ring_audit") or []:
        band = (r.get("band_audit") or {}).get("depletion_sigma")
    review_png = os.path.join(
        os.path.dirname(ROOT),
        "路演结果",
        "EPB_fbbqy_sample_review",
        "test_09u_N3cnKxe68a0ma7Bc.png",
    )
    return {
        "objectId": oid,
        "review_png_exists": os.path.isfile(review_png),
        "review_png": review_png,
        "n_regions": len(rings),
        "objectOverall": row.get("objectOverall"),
        "九3b_轮廓贴合": row.get("九3b_轮廓贴合"),
        "depletion_sigma_sample": band,
        "expect": "offline: 九3b 待判定 unless physics jsonl; band depletion_sigma>0 for dark band",
        "pass": row.get("九1_文件配对") == "通过" and len(rings) >= 1,
    }


def _check_aia_gb96() -> dict:
    oid = "Gb96QafrHF4ZNGdUa6Va.png"
    d = dir_aia_primary()
    img = os.path.join(d, "data", oid)
    lab = os.path.join(d, "label", oid + ".json")
    if not os.path.isfile(img):
        return {
            "objectId": oid,
            "skipped": True,
            "skip_reason": "missing_aia_z4_data",
            "pass": True,
        }
    item = prepare_aia(img, lab)
    row = qc_aia_object(os.path.basename(d), img, lab, miss_mode="fast")
    n_reg = len((item.get("metrics") or {}).get("labeled_regions") or [])
    miss = (item.get("metrics") or {}).get("missed_label_candidates") or {}
    return {
        "objectId": oid,
        "n_regions": n_reg,
        "objectOverall": row.get("objectOverall"),
        "九9_覆盖异常": row.get("九9_覆盖异常"),
        "miss_candidates": len(miss.get("candidates") or []),
        "expect": "2 HEK boxes; bright_unlabeled candidates likely (HEK≠漏标终判); 九9 often 不通过(IoU)",
        "pass": n_reg == 2 and row.get("九1_文件配对") == "通过",
    }


def main() -> None:
    out = {"cases": [_check_epb_09u(), _check_aia_gb96()]}
    out_path = os.path.join(ROOT, "smoke", "review_cases_last.json")
    json.dump(out, open(out_path, "w"), ensure_ascii=False, indent=2)
    ok = all(c.get("pass") for c in out["cases"] if not c.get("skipped"))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
