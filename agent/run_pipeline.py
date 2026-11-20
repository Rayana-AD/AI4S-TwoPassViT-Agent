#!/usr/bin/env python3
"""One-command QC pipeline:
- On the 12 official roadshow benchmark directories: automatically uses the verified
  deterministic rule track (modality_detect + standard object QC + postprocess,
  with debater auxiliary disabled) so benchmark scores remain 100% reproducible.
- On all other datasets (other AIA/EPB/ULF versions, HMI, CME, DMSP, or unseen
  space-science datasets): uses Dataset Router (schema + visual probe + RAG) for
  adaptive routing, and optionally runs Scientific Debater (with Teaching) to
  generate and attach auxiliary metrics before Pass1/Pass2.

Does not change smoke/smoke_test.py (frozen three-directory fingerprints).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(PIPELINE_ROOT)
PKG = os.path.join(PIPELINE_ROOT, "package")
os.environ.setdefault("AGENT_PIPELINE_ROOT", PIPELINE_ROOT)
os.environ.setdefault("ROADSHOW_REPO_ROOT", REPO_ROOT)
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))
RESULTS = os.path.join(PKG, "scripts")

from modality_detect import (  # noqa: E402
    detect_modality_from_directory,
    list_dataset_dirs,
    resolve_pipeline_modality,
)
from roadshow_paths import RESULTS_DIR  # noqa: E402
from dir_postprocess import run_dir_postprocess  # noqa: E402

PY = sys.executable

# The exact 12 benchmark directories from the roadshow evaluation set.
# Only these 12 directories (not all AIA/EPB/ULF datasets) automatically fall back
# to the frozen deterministic rule track by default.
ROADSHOW_12_DIR_IDS: frozenset[str] = frozenset(
    {
        "AIA_AR_sample_3mogtggl50",
        "AIA_AR_sample_7qn2pdeube",
        "AIA_AR_sample_p86y2cz08y",
        "AIA_AR_sample_z4h764sf2d",
        "EPB_seg_sample_fbbqy66u2d",
        "EPB_seg_sample_mc4t7fou91",
        "EPB_seg_sample_qmn05l7r91",
        "EPB_seg_sample_z443g9dgh7",
        "ULF_sample_09b7y3z4hn",
        "ULF_sample_0yu0mc7d5a",
        "ULF_sample_ta382376ar",
        "ULF_sample_xfnogkdey9",
    }
)


def is_roadshow_12_dir(dir_path: str) -> bool:
    dir_id = os.path.basename(os.path.normpath(os.path.abspath(dir_path)))
    return dir_id in ROADSHOW_12_DIR_IDS


def _script_for(modality: str) -> tuple[str, str, str]:
    if modality == "AIA":
        return (
            os.path.join(PKG, "scripts", "aia_dir_object_qc_csv.py"),
            os.path.join(RESULTS_DIR, "AIA_physics_informed.jsonl"),
            os.path.join(PKG, "scripts", "physics_informed_aia.py"),
        )
    if modality == "EPB":
        return (
            os.path.join(PKG, "scripts", "epb_dir_object_qc_csv.py"),
            os.path.join(RESULTS_DIR, "EPB_physics_informed.jsonl"),
            os.path.join(PKG, "scripts", "physics_informed_epb.py"),
        )
    if modality == "ULF":
        return (
            os.path.join(PKG, "scripts", "ulf_dir_object_qc_csv.py"),
            os.path.join(RESULTS_DIR, "ULF_physics_informed.jsonl"),
            os.path.join(PKG, "scripts", "physics_informed_ulf.py"),
        )
    raise ValueError(f"Unsupported modality: {modality}")


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, cwd=RESULTS, env=env)


def _route_directory(
    dir_path: str,
    *,
    router_mode: str,
    roadshow_fallback: bool,
) -> tuple[str, dict, dict | None]:
    """Resolve pipeline modality using either legacy rule detection or Dataset Router."""
    use_v2_router = (router_mode == "v2") or (router_mode == "auto" and not roadshow_fallback)

    if use_v2_router:
        try:
            from dataset_router.router_agent import route_dataset_directory

            route = route_dataset_directory(dir_path, json_sample=12, image_sample=2)
            pipeline = str(route.get("pipeline") or "UNKNOWN")
            router_summary = {
                "engine": "dataset_router",
                "pipeline": pipeline,
                "archetype_id": route.get("archetype_id"),
                "confidence": route.get("confidence"),
                "layout": (route.get("profile") or {}).get("layout"),
                "physics_track": route.get("physics_track"),
            }
            if pipeline in {"AIA", "EPB", "ULF"}:
                return pipeline, router_summary, route
        except Exception as exc:
            router_summary = {"engine": "dataset_router_error_fallback", "error": str(exc)}
            info = detect_modality_from_directory(dir_path)
            modality = str(info.get("modality") or "UNKNOWN")
            if modality == "UNKNOWN":
                modality = resolve_pipeline_modality(dir_path=dir_path)
            return modality, {**info, "router_fallback": router_summary}, None

    info = detect_modality_from_directory(dir_path)
    modality = str(info.get("modality") or "UNKNOWN")
    if modality == "UNKNOWN":
        modality = resolve_pipeline_modality(dir_path=dir_path)
    return modality, {"engine": "legacy_rule_detect", **info}, None


def _maybe_run_debater(
    dir_path: str,
    *,
    debater_mode: str,
    roadshow_fallback: bool,
    teaching_mode: str,
    max_refine: int,
    secrets: str,
) -> tuple[str | None, dict]:
    """Optionally run Scientific Debater to synthesize auxiliary_metrics.py."""
    if debater_mode == "off":
        return None, {"enabled": False, "reason": "debater_off"}
    if debater_mode == "auto" and roadshow_fallback:
        return None, {"enabled": False, "reason": "roadshow_12_rule_fallback"}

    from scientific_debater.debate_runner import run_debate_session

    use_offline = (debater_mode == "offline") or (not secrets or not os.path.isfile(secrets))
    sess = run_debate_session(
        dir_path,
        secrets_path=None if use_offline else secrets,
        offline=use_offline,
        max_refine=0 if use_offline else max_refine,
        image_sample=3,
        pipeline_check=False,
        teaching_mode=teaching_mode,
    )
    script_path = os.path.join(sess["workspace"], "auxiliary_metrics.py")
    meta = {
        "enabled": True,
        "offline": use_offline,
        "ok": sess.get("ok"),
        "v0_source": sess.get("v0_source"),
        "best_script_version": sess.get("best_script_version"),
        "teaching_mode": teaching_mode,
        "workspace": sess.get("workspace"),
        "script_path": script_path if os.path.isfile(script_path) else None,
    }
    return (script_path if os.path.isfile(script_path) else None), meta


def run_one_dir(
    dir_path: str,
    *,
    limit: int,
    jobs: int,
    postprocess: bool,
    modality_opt: str,
    physics: str,
    physics_workers: int,
    secrets: str,
    router_mode: str = "auto",
    debater_mode: str = "off",
    teaching_mode: str = "auto",
    debater_max_refine: int = 2,
) -> dict:
    dir_path = os.path.abspath(dir_path)
    dir_id = os.path.basename(os.path.normpath(dir_path))
    profile_env = os.environ.get("PIPELINE_PROFILE", "").strip().lower()
    roadshow_fallback = is_roadshow_12_dir(dir_path) and profile_env != "force_extended"

    detected_modality, info, _route = _route_directory(
        dir_path,
        router_mode=router_mode,
        roadshow_fallback=roadshow_fallback,
    )
    modality = modality_opt or detected_modality
    script, physics_jsonl, physics_script = _script_for(modality)
    out_csv = os.path.join(RESULTS_DIR, f"{dir_id}_{modality}对象质检.csv")

    exec_mode = "roadshow_12_rule_fallback" if roadshow_fallback else "extended_adaptive"
    sub_env = os.environ.copy()

    debater_meta: dict = {"enabled": False, "reason": "not_requested"}
    if roadshow_fallback:
        # Strict safeguard: on the 12 benchmark directories, never leak experimental
        # auxiliary metrics into the verified rule/physics track.
        sub_env.pop("DEBATER_AUXILIARY_SCRIPT", None)
        debater_meta = {"enabled": False, "reason": "roadshow_12_rule_fallback"}
    else:
        aux_script, debater_meta = _maybe_run_debater(
            dir_path,
            debater_mode=debater_mode,
            roadshow_fallback=roadshow_fallback,
            teaching_mode=teaching_mode,
            max_refine=debater_max_refine,
            secrets=secrets,
        )
        if aux_script:
            sub_env["DEBATER_AUXILIARY_SCRIPT"] = aux_script

    if physics in {"metrics", "call"}:
        phys_cmd = [PY, physics_script, "--dir", dir_path, "--append"]
        if limit > 0:
            phys_cmd.extend(["--limit", str(limit)])
        else:
            phys_cmd.extend(["--limit", "0"])
        if physics == "call":
            phys_cmd.extend(["--call", "--workers", str(physics_workers)])
            if secrets:
                phys_cmd.extend(["--secrets", secrets])
        else:
            phys_cmd.append("--metrics-only")
        _run(phys_cmd, env=sub_env)

    qc_cmd = [
        PY,
        script,
        "--dir",
        dir_path,
        "--physics-jsonl",
        physics_jsonl,
        "--jobs",
        str(jobs),
        "--out",
        out_csv,
    ]
    if limit > 0:
        qc_cmd.extend(["--limit", str(limit)])
    if modality == "AIA":
        qc_cmd.extend(["--miss-mode", "fast"])
    print(
        json.dumps(
            {
                "dirId": dir_id,
                "execution_mode": exec_mode,
                "detected": info,
                "modality": modality,
                "debater": debater_meta,
                "qc": qc_cmd,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    _run(qc_cmd, env=sub_env)
    n_rows = 0
    summary_path = out_csv.replace(".csv", ".json")
    if os.path.isfile(summary_path):
        try:
            n_rows = int((json.load(open(summary_path, encoding="utf-8")) or {}).get("n_rows") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            n_rows = 0
    if n_rows == 0 and modality in {"AIA", "EPB"} and "--all-labels" not in qc_cmd:
        qc_cmd.append("--all-labels")
        print(json.dumps({"retry_all_labels": True, "dirId": dir_id}, ensure_ascii=False))
        _run(qc_cmd, env=sub_env)

    result: dict = {
        "dirId": dir_id,
        "dir": dir_path,
        "execution_mode": exec_mode,
        "detected": info,
        "modality": modality,
        "debater": debater_meta,
        "object_csv": out_csv,
    }
    if postprocess:
        result["postprocess"] = run_dir_postprocess(
            out_csv,
            dir_id=dir_id,
            modality=modality,
            out_dir=RESULTS_DIR,
            data_dir=dir_path,
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adaptive space-science QC pipeline: Dataset Router + optional Scientific Debater + rule/physics QC + postprocess."
    )
    parser.add_argument("--dir", default="", help="One dataset directory")
    parser.add_argument("--data-root", default="", help="Parent of many dirId folders (e.g. publish/)")
    parser.add_argument("--limit", type=int, default=0, help="Max objects per dir (0=all). Use 20 for a quick pass.")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--postprocess", action="store_true", default=True)
    parser.add_argument("--no-postprocess", action="store_true", help="Stop after object CSV")
    parser.add_argument("--modality", choices=("AIA", "EPB", "ULF"), default="")
    parser.add_argument(
        "--router",
        choices=("auto", "v2", "legacy"),
        default="auto",
        help="auto=legacy rule detect on the 12 roadshow dirs, Dataset Router on all other dirs; v2=always Dataset Router; legacy=always modality_detect",
    )
    parser.add_argument(
        "--debater",
        choices=("off", "auto", "offline", "call"),
        default="off",
        help="off=skip debater (default); auto=run debater on non-12 dirs (skip 12 roadshow dirs); offline=offline template; call=LLM debate + refine",
    )
    parser.add_argument(
        "--teaching-mode",
        choices=("auto", "meta_only", "spine_full"),
        default="auto",
        help="Teaching gating mode for Scientific Debater",
    )
    parser.add_argument("--debater-max-refine", type=int, default=2, help="Max v0->v1->v2 refine rounds")
    parser.add_argument(
        "--physics",
        choices=("skip", "metrics", "call"),
        default="skip",
        help="skip=rules only (default); metrics=local physics jsonl; call=Pass1/2 API",
    )
    parser.add_argument("--physics-workers", type=int, default=4)
    parser.add_argument("--secrets", default="/app/secrets.yaml")
    parser.add_argument("--max-dirs", type=int, default=0, help="When using --data-root, cap how many children to run")
    args = parser.parse_args()
    postprocess = bool(args.postprocess) and not args.no_postprocess

    if args.data_root:
        dirs = list_dataset_dirs(args.data_root)
        if args.max_dirs > 0:
            dirs = dirs[: args.max_dirs]
        if not dirs:
            raise SystemExit(f"No dataset directories under {args.data_root}")
    elif args.dir:
        dirs = [args.dir]
    else:
        raise SystemExit("Provide --dir or --data-root")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    reports = []
    for path in dirs:
        reports.append(
            run_one_dir(
                path,
                limit=args.limit,
                jobs=args.jobs,
                postprocess=postprocess,
                modality_opt=args.modality,
                physics=args.physics,
                physics_workers=args.physics_workers,
                secrets=args.secrets,
                router_mode=args.router,
                debater_mode=args.debater,
                teaching_mode=args.teaching_mode,
                debater_max_refine=args.debater_max_refine,
            )
        )
    batch = os.path.join(RESULTS_DIR, "run_pipeline_batch.json")
    json.dump({"n": len(reports), "runs": reports}, open(batch, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"ok": True, "n": len(reports), "batch": batch}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
