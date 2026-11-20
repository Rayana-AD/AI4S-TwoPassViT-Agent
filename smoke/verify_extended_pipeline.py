#!/usr/bin/env python3
"""Self-check for Docker / local runtime:
1. All required third-party and internal packages import cleanly.
2. Dataset Router identifies multiple space-science dataset families (beyond AIA/EPB/ULF).
3. Scientific Debater + Teaching + Sandbox runs offline end-to-end.
4. agent/run_pipeline.py automatically falls back to deterministic rules on the 12
   roadshow benchmark directories, and activates Dataset Router (+ optional Debater)
   on other datasets.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.environ.get("ROADSHOW_REPO_ROOT", os.path.dirname(PIPELINE_ROOT))
PKG = os.path.join(PIPELINE_ROOT, "package")
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))


def check_imports() -> dict:
    required = [
        "numpy",
        "PIL",
        "yaml",
        "scipy",
        "audits",
        "modality_detect",
        "physics_metrics",
        "dataset_router.router_agent",
        "scientific_debater.debate_runner",
        "scientific_debater.teaching_context",
        "scientific_debater.script_sandbox",
        "scientific_debater.auxiliary_bridge",
        "scientific_debater.evolution_audit",
    ]
    optional = ["matplotlib", "langgraph"]
    missing = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            missing.append({"module": mod, "error": str(exc)})
    optional_status = {}
    for mod in optional:
        try:
            importlib.import_module(mod)
            optional_status[mod] = "installed"
        except Exception:
            optional_status[mod] = "not_installed_locally_installed_in_docker"
    return {
        "ok": not missing,
        "checked_core": len(required),
        "missing": missing,
        "optional": optional_status,
    }


def check_router_multi_family() -> dict:
    from dataset_router.router_agent import route_dataset_directory

    publish_root = os.path.join(REPO_ROOT, "colab_subset", "publish")
    if not os.path.isdir(publish_root):
        return {"ok": True, "skipped": True, "reason": "colab_subset/publish not mounted"}

    samples = [
        ("DMSP_SSUSI_aaue04ws6s", "AIA"),
        ("CME_C2_sample_g8x0hw7reo", "AIA"),
        ("HMI_AR_sample_6yaatkycjv", "AIA"),
        ("EPB_seg_sample_pb72bbq4bp", "EPB"),
        ("ULF_sample_lj7rg82ela", "ULF"),
        ("AIA_AR_sample_mugm2urshy", "AIA"),
    ]
    results = []
    all_ok = True
    for name, expected_pipeline in samples:
        p = os.path.join(publish_root, name)
        if not os.path.isdir(p):
            continue
        r = route_dataset_directory(p, json_sample=8, image_sample=2)
        got = r.get("pipeline")
        ok = got == expected_pipeline
        if not ok:
            all_ok = False
        results.append(
            {
                "dir": name,
                "expected_pipeline": expected_pipeline,
                "got_pipeline": got,
                "archetype_id": r.get("archetype_id"),
                "ok": ok,
            }
        )
    return {"ok": all_ok and bool(results), "cases": results}


def check_pipeline_routing_and_fallback() -> dict:
    roadshow_epb = os.path.join(REPO_ROOT, "路演数据", "EPB_seg_sample_fbbqy66u2d")
    non_12_dmsp = os.path.join(REPO_ROOT, "colab_subset", "publish", "DMSP_SSUSI_aaue04ws6s")
    non_12_epb = os.path.join(REPO_ROOT, "colab_subset", "publish", "EPB_seg_sample_pb72bbq4bp")

    results = []
    all_ok = True
    with tempfile.TemporaryDirectory(prefix="verify_ext_pipeline_") as tmp_res:
        env = os.environ.copy()
        env["ROADSHOW_RESULTS"] = tmp_res
        env["DEBATER_EXPERIMENTS_ROOT"] = os.path.join(tmp_res, "debater_runs")
        env["AGENT_PIPELINE_ROOT"] = PIPELINE_ROOT
        env["ROADSHOW_REPO_ROOT"] = REPO_ROOT

        # Case 1: One of the 12 roadshow benchmark directories -> must fall back to rules
        if os.path.isdir(roadshow_epb):
            cmd = [
                sys.executable,
                os.path.join(PIPELINE_ROOT, "agent", "run_pipeline.py"),
                "--dir",
                roadshow_epb,
                "--limit",
                "2",
                "--jobs",
                "1",
                "--no-postprocess",
                "--router",
                "auto",
                "--debater",
                "auto",
            ]
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
            batch = json.load(open(os.path.join(tmp_res, "run_pipeline_batch.json"), encoding="utf-8"))
            run0 = (batch.get("runs") or [{}])[0]
            ok = (
                proc.returncode == 0
                and run0.get("execution_mode") == "roadshow_12_rule_fallback"
                and (run0.get("detected") or {}).get("engine") == "legacy_rule_detect"
                and not (run0.get("debater") or {}).get("enabled")
            )
            if not ok:
                all_ok = False
            results.append(
                {
                    "case": "roadshow_12_dir_fallback",
                    "dir": os.path.basename(roadshow_epb),
                    "execution_mode": run0.get("execution_mode"),
                    "router_engine": (run0.get("detected") or {}).get("engine"),
                    "debater_enabled": (run0.get("debater") or {}).get("enabled"),
                    "ok": ok,
                }
            )

        # Case 2: Non-12 EPB directory (same modality, NOT in the 12 benchmark list) -> must use Dataset Router
        if os.path.isdir(non_12_epb):
            cmd = [
                sys.executable,
                os.path.join(PIPELINE_ROOT, "agent", "run_pipeline.py"),
                "--dir",
                non_12_epb,
                "--limit",
                "2",
                "--jobs",
                "1",
                "--no-postprocess",
                "--router",
                "auto",
                "--debater",
                "off",
            ]
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
            batch = json.load(open(os.path.join(tmp_res, "run_pipeline_batch.json"), encoding="utf-8"))
            run0 = (batch.get("runs") or [{}])[0]
            ok = (
                proc.returncode == 0
                and run0.get("execution_mode") == "extended_adaptive"
                and (run0.get("detected") or {}).get("engine") == "dataset_router"
                and run0.get("modality") == "EPB"
            )
            if not ok:
                all_ok = False
            results.append(
                {
                    "case": "non_12_epb_adaptive_router",
                    "dir": os.path.basename(non_12_epb),
                    "execution_mode": run0.get("execution_mode"),
                    "router_engine": (run0.get("detected") or {}).get("engine"),
                    "archetype_id": (run0.get("detected") or {}).get("archetype_id"),
                    "ok": ok,
                }
            )

        # Case 3: Non-12 new instrument family (DMSP SSUSI) with offline Debater + Teaching
        if os.path.isdir(non_12_dmsp):
            cmd = [
                sys.executable,
                os.path.join(PIPELINE_ROOT, "agent", "run_pipeline.py"),
                "--dir",
                non_12_dmsp,
                "--limit",
                "2",
                "--jobs",
                "1",
                "--no-postprocess",
                "--router",
                "auto",
                "--debater",
                "offline",
            ]
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
            batch = json.load(open(os.path.join(tmp_res, "run_pipeline_batch.json"), encoding="utf-8"))
            run0 = (batch.get("runs") or [{}])[0]
            deb = run0.get("debater") or {}
            ok = (
                proc.returncode == 0
                and run0.get("execution_mode") == "extended_adaptive"
                and (run0.get("detected") or {}).get("engine") == "dataset_router"
                and bool(deb.get("enabled"))
                and bool(deb.get("ok"))
            )
            if not ok:
                all_ok = False
            results.append(
                {
                    "case": "non_12_dmsp_router_plus_debater_offline",
                    "dir": os.path.basename(non_12_dmsp),
                    "execution_mode": run0.get("execution_mode"),
                    "router_engine": (run0.get("detected") or {}).get("engine"),
                    "archetype_id": (run0.get("detected") or {}).get("archetype_id"),
                    "debater_ok": deb.get("ok"),
                    "ok": ok,
                }
            )

    return {"ok": all_ok, "cases": results}


def check_unit_logic() -> dict:
    """Data-independent unit check (works inside bare Docker container without mounted datasets)."""
    import numpy as np
    from PIL import Image
    from scientific_debater.teaching_context import build_teaching_block
    from scientific_debater.script_sandbox import lint_auxiliary_code, run_auxiliary_metrics

    sys.path.insert(0, os.path.join(PIPELINE_ROOT, "agent"))
    import run_pipeline as rp

    # 1. Exact 12-dir fallback boundary (must distinguish 12 roadshow dirs vs other same-modality dirs)
    assert len(rp.ROADSHOW_12_DIR_IDS) == 12
    assert rp.is_roadshow_12_dir("/data/EPB_seg_sample_fbbqy66u2d") is True
    assert rp.is_roadshow_12_dir("/data/EPB_seg_sample_pb72bbq4bp") is False
    assert rp.is_roadshow_12_dir("/data/AIA_AR_sample_z4h764sf2d") is True
    assert rp.is_roadshow_12_dir("/data/AIA_AR_sample_mugm2urshy") is False
    assert rp.is_roadshow_12_dir("/data/DMSP_SSUSI_aaue04ws6s") is False

    # 2. Teaching gating: far archetype (DMSP) should downgrade vs near archetype (EPB)
    t_epb = build_teaching_block(pipeline="EPB", archetype_id="epb_allsky_airglow_mask", mode="auto")
    t_dmsp = build_teaching_block(pipeline="AIA", archetype_id="dmsp_ssusi_aurora", mode="auto")
    t_meta = build_teaching_block(pipeline="AIA", archetype_id="unknown", mode="meta_only")
    assert "EPB_fbbqy" in t_epb
    assert "不同族" in t_dmsp
    assert "仅元结构" in t_meta

    # 3. Sandbox AST lint + execution on a synthetic PNG
    sample_code = (
        "import numpy as np\n"
        "from PIL import Image\n"
        "def auxiliary_metrics(image_path: str, label_obj: dict | None) -> dict:\n"
        "    arr = np.asarray(Image.open(image_path).convert('L'), dtype=np.float32)\n"
        "    return {'mean_luma': round(float(arr.mean()), 4), 'has_label': int(bool(label_obj))}\n"
    )
    lint_errs = lint_auxiliary_code(sample_code)
    assert not lint_errs, f"unexpected lint errors: {lint_errs}"
    with tempfile.TemporaryDirectory(prefix="verify_sandbox_") as td:
        png_path = os.path.join(td, "synthetic.png")
        Image.fromarray(np.full((64, 64), 120, dtype=np.uint8)).save(png_path)
        res = run_auxiliary_metrics(sample_code, png_path, {"mask": {}})
        assert res.get("error") is None
        assert res.get("mean_luma") == 120.0
        assert res.get("has_label") == 1

    return {
        "ok": True,
        "roadshow_12_count": len(rp.ROADSHOW_12_DIR_IDS),
        "teaching_gating_ok": True,
        "sandbox_exec_ok": True,
    }


def _progress(msg: str) -> None:
    print(f"[verify] {msg}", file=sys.stderr, flush=True)


def main() -> None:
    quick = os.environ.get("VERIFY_QUICK", "").strip() in ("1", "true", "yes")
    _progress("imports …")
    imports = check_imports()
    _progress("unit_logic …")
    unit_logic = check_unit_logic()
    if quick:
        _progress("VERIFY_QUICK=1 — skip router/pipeline e2e (use mounted data + full run for judges)")
        router_multi_family = {"ok": True, "skipped": True, "reason": "VERIFY_QUICK"}
        pipeline_dual_track = {"ok": True, "skipped": True, "reason": "VERIFY_QUICK"}
    else:
        _progress("router_multi_family …")
        router_multi_family = check_router_multi_family()
        _progress("pipeline_dual_track … (may take several minutes on amd64 emulation)")
        pipeline_dual_track = check_pipeline_routing_and_fallback()
    report = {
        "imports": imports,
        "unit_logic": unit_logic,
        "router_multi_family": router_multi_family,
        "pipeline_dual_track": pipeline_dual_track,
    }
    report["ok"] = all(section.get("ok") for section in report.values())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
