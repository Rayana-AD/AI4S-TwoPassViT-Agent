#!/usr/bin/env python3
"""Static + light checks: extended source is a superset of 星海舰队 baseline pipeline."""

from __future__ import annotations

import ast
import json
import os
import sys

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(PIPELINE_ROOT, "package")
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))
sys.path.insert(0, os.path.join(PIPELINE_ROOT, "agent"))

# 初版 DEL source/ 必须存在的路径（相对 PIPELINE_ROOT）；扩展包只能增不能删。
BASELINE_PATHS = [
    "package/roadshow_paths.py",
    "package/scripts/aia_dir_object_qc_csv.py",
    "package/scripts/epb_dir_object_qc_csv.py",
    "package/scripts/ulf_dir_object_qc_csv.py",
    "package/scripts/physics_informed_aia.py",
    "package/scripts/physics_informed_epb.py",
    "package/scripts/physics_informed_ulf.py",
    "package/scripts/dir_postprocess.py",
    "package/scripts/aia_z4_full_pipeline.py",
    "package/scripts/epb_fbbqy_full_pipeline.py",
    "package/scripts/ulf_xfnog_full_pipeline.py",
    "package/agent_modules/modality_detect.py",
    "package/agent_modules/physics_informed_runner.py",
    "package/agent_modules/physics_inspect.py",
    "package/agent_modules/aia_object_qc.py",
    "package/agent_modules/epb_object_qc.py",
    "package/agent_modules/ulf_object_qc.py",
    "smoke/smoke_test.py",
    "smoke/expected_baseline.json",
    "agent/run_pipeline.py",
]

EXTENSION_PATHS = [
    "package/agent_modules/dataset_router/router_agent.py",
    "package/agent_modules/scientific_debater/debate_runner.py",
    "package/agent_modules/scientific_debater/auxiliary_bridge.py",
    "smoke/verify_extended_pipeline.py",
]

OPTIONAL_ENTRY = "entry/run_pipeline.py"


def check_files() -> dict:
    missing_baseline = []
    missing_ext = []
    for rel in BASELINE_PATHS:
        if not os.path.isfile(os.path.join(PIPELINE_ROOT, rel)):
            missing_baseline.append(rel)
    for rel in EXTENSION_PATHS:
        if not os.path.isfile(os.path.join(PIPELINE_ROOT, rel)):
            missing_ext.append(rel)
    entry = os.path.join(PIPELINE_ROOT, OPTIONAL_ENTRY)
    entry_ok = os.path.isfile(entry)
    need_entry = os.environ.get("REQUIRE_ENTRY", "").strip() in ("1", "true", "yes")
    entry_issue = not entry_ok and need_entry
    return {
        "ok": not missing_baseline and not missing_ext and not entry_issue,
        "missing_baseline": missing_baseline,
        "missing_extension": missing_ext,
        "entry_run_pipeline": entry_ok,
    }


def check_run_pipeline_contract() -> dict:
    import run_pipeline as rp  # noqa: WPS433

    errors = []
    if len(getattr(rp, "ROADSHOW_12_DIR_IDS", ())) != 12:
        errors.append("ROADSHOW_12_DIR_IDS must have 12 entries")
    for mod in ("AIA", "EPB", "ULF"):
        try:
            rp._script_for(mod)
        except Exception as exc:
            errors.append(f"_script_for({mod}): {exc}")
    if not callable(getattr(rp, "run_one_dir", None)):
        errors.append("run_one_dir missing")
    if not callable(getattr(rp, "is_roadshow_12_dir", None)):
        errors.append("is_roadshow_12_dir missing")
    return {"ok": not errors, "errors": errors, "roadshow_12_count": len(rp.ROADSHOW_12_DIR_IDS)}


def check_dockerfile_copy_set(supplement_root: str | None) -> dict:
    """If run inside supplement package, Dockerfile must COPY same tree as 初版 + source/."""
    if not supplement_root:
        return {"ok": True, "skipped": True}
    dockerfile = os.path.join(supplement_root, "image", "Dockerfile")
    if not os.path.isfile(dockerfile):
        return {"ok": True, "skipped": True, "reason": "image/Dockerfile not visible in this runtime"}
    text = open(dockerfile, encoding="utf-8").read()
    need = ["source/package/agent_modules", "source/agent", "source/smoke", "source/docs"]
    missing = [n for n in need if n not in text]
    return {"ok": not missing, "dockerfile": dockerfile, "missing_copy_directives": missing}


def main() -> None:
    files = check_files()
    contract = check_run_pipeline_contract()
    supplement = os.environ.get("SUPPLEMENT_ROOT")
    docker = check_dockerfile_copy_set(supplement)
    report = {
        "pipeline_root": PIPELINE_ROOT,
        "files": files,
        "run_pipeline_contract": contract,
        "dockerfile": docker,
    }
    report["ok"] = all(section.get("ok") for section in (files, contract, docker) if "ok" in section)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()