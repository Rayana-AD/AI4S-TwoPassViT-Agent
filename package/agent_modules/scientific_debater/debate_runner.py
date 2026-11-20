"""Orchestrate scientific debater turns: router → Q&A → draft script → calibrate → refine."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from dataset_router.router_agent import route_dataset_directory
from dataset_router.visual_probe import collect_png_paths

from vision import chat_with_usage, load_secrets, model_endpoint

from .teaching_context import build_teaching_block
from .debate_phases import (
    phase_defect_visual,
    phase_draft_script,
    phase_heuristic_geometry,
    phase_heuristic_image_defects,
    phase_heuristic_pre_v1,
    phase_heuristic_pre_v2,
    phase_metric_proposals,
    phase_draft_script_v0_compact,
    phase_refine_v1,
    phase_refine_v2,
    phase_task_context,
    phase_vision_defect_check,
)
from .dialogue_bundle import bundle_markdown, synthesis_for_script
from .rag_context import cap_phase_answer, estimate_v0_prompt_chars, prepare_route_for_debate
from .offline_draft import offline_script_for
from .schema import DebateSession, DebateTurn, SampleCalibration
from .auxiliary_bridge import verify_pass1_hook
from .demo_report import build_demo_report
from .evolution_audit import audit_versions
from .script_sandbox import extract_python_block, lint_auxiliary_code, run_auxiliary_metrics


def _pipeline_root() -> str:
    here = os.path.abspath(__file__)
    default = os.path.dirname(os.path.dirname(os.path.dirname(here)))  # Agent-Pipeline/
    return os.environ.get("AGENT_PIPELINE_ROOT", default)


def _offline_script_choice(dir_id: str, archetype_id: str, pipeline: str, visual: dict[str, Any]) -> str:
    tags = visual.get("tag_counts") or {}
    if archetype_id == "generic_spatial_boxes" or dir_id.startswith("HMI_"):
        if tags.get("low_contrast") or dir_id.startswith("HMI_"):
            return offline_script_for("hmi_sharp_ar", pipeline)
    if dir_id.startswith("CME_") or tags.get("full_disk_bright"):
        return offline_script_for("lasco_cme_catalog", pipeline)
    return offline_script_for(archetype_id, pipeline)


def _workspace(dir_id: str) -> str:
    base = os.environ.get("DEBATER_EXPERIMENTS_ROOT") or os.path.join(
        _pipeline_root(), "experiments", "scientific_debater"
    )
    root = os.path.join(base, dir_id)
    os.makedirs(root, exist_ok=True)
    return root


def _write_turn(workspace: str, session: DebateSession, turn: DebateTurn) -> None:
    session.setdefault("turns", []).append(turn)
    path = os.path.join(workspace, "debate_session.json")
    json.dump(session, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def _llm_text(prompt: str, secrets: dict | None, *, max_tokens: int = 1200) -> dict[str, Any]:
    return chat_with_usage(prompt, "text", secrets, timeout=180, max_tokens=max_tokens)


def _llm_vision(text: str, png_path: str, secrets: dict | None) -> dict[str, Any]:
    import base64

    with open(png_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode()
    content = [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}},
    ]
    return chat_with_usage(content, "vision", secrets, timeout=180, max_tokens=600)


def _load_label_for_image(dir_path: str, png_path: str) -> dict | None:
    base = os.path.basename(png_path)
    label_dir = os.path.join(dir_path, "label")
    if os.path.isdir(label_dir):
        cand = os.path.join(label_dir, base + ".json")
        if os.path.isfile(cand):
            try:
                return json.load(open(cand, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    flat = os.path.join(dir_path, base + ".json")
    if os.path.isfile(flat):
        try:
            return json.load(open(flat, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _clean_code(code: str) -> str:
    code = extract_python_block(code) or code
    return extract_python_block(code) or code


def _code_from_llm_response(raw: str) -> str:
    code = _clean_code(raw)
    if "def auxiliary_metrics" not in code:
        return ""
    return code


def _likely_truncated(usage: dict[str, Any], max_tokens: int) -> bool:
    comp = int(usage.get("completion_tokens") or 0)
    return comp >= max(500, max_tokens - 80)


def _ensure_v0_code(
    *,
    first_code: str,
    first_usage: dict[str, Any],
    dir_id: str,
    archetype_id: str,
    pipeline: str,
    visual: dict[str, Any],
    secrets: dict[str, Any],
    metric_text: str,
    physics_track: str,
    max_tokens: int,
) -> tuple[str, str, str]:
    """Returns (code, source_tag, raw_snippet_for_log)."""
    source = "llm_v0"
    code = first_code
    if lint_auxiliary_code(code):
        if _likely_truncated(first_usage, max_tokens):
            source = "llm_v0_truncated"
        p_compact = phase_draft_script_v0_compact(
            archetype_id, pipeline, metric_text, physics_track=physics_track
        )
        r2 = _llm_text(p_compact, secrets, max_tokens=2200)
        code2 = _code_from_llm_response(r2.get("text") or "")
        if code2 and not lint_auxiliary_code(code2, max_lines=100):
            return code2, "llm_v0_compact_retry", (r2.get("text") or "")[:4000]
        source = "offline_after_lint_fail"
        code = _offline_script_choice(dir_id, archetype_id, pipeline, visual)
    return code, source, ""


def _save_script_version(workspace: str, code: str, tag: str) -> str:
    path = os.path.join(workspace, f"auxiliary_metrics_{tag}.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(_clean_code(code))
    return path


def _save_calibration(workspace: str, tag: str, rows: list[SampleCalibration]) -> None:
    json.dump(rows, open(os.path.join(workspace, f"calibration_{tag}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def _calibration_score(rows: list[SampleCalibration]) -> float:
    if not rows:
        return -1.0
    good = 0
    keys = 0
    for row in rows:
        m = row.get("metrics") or {}
        if m.get("error"):
            continue
        good += 1
        keys += len([k for k in m if k != "error"])
    if good == 0:
        return 0.0
    return good * 1000.0 + keys


def _pick_best_script_version(workspace: str, tags: list[str]) -> tuple[str, list[SampleCalibration]]:
    audit_path = os.path.join(workspace, "EVOLUTION_AUDIT.json")
    stale: set[str] = set()
    if os.path.isfile(audit_path):
        for row in json.load(open(audit_path, encoding="utf-8")).get("versions") or []:
            if row.get("verdict") == "stale_v2":
                stale.add(str(row.get("version")))
    best_tag = tags[0] if tags else "v0"
    best_cal: list[SampleCalibration] = []
    best_score = -1.0
    for tag in tags:
        if tag in stale:
            continue
        path = os.path.join(workspace, f"calibration_{tag}.json")
        if not os.path.isfile(path):
            continue
        cal = json.load(open(path, encoding="utf-8"))
        score = _calibration_score(cal)
        if score > best_score:
            best_score = score
            best_tag = tag
            best_cal = cal
    script_src = os.path.join(workspace, f"auxiliary_metrics_{best_tag}.py")
    script_dst = os.path.join(workspace, "auxiliary_metrics.py")
    if os.path.isfile(script_src):
        with open(script_src, encoding="utf-8") as handle:
            code = handle.read()
        with open(script_dst, "w", encoding="utf-8") as handle:
            handle.write(_clean_code(code))
    return best_tag, best_cal


def calibrate_script(
    code: str,
    dir_path: str,
    *,
    max_images: int = 3,
    pipeline: str = "AIA",
) -> list[SampleCalibration]:
    rows: list[SampleCalibration] = []
    if pipeline == "ULF":
        n = 0
        for name in sorted(os.listdir(dir_path)):
            if not name.endswith(".csv") or name.endswith(".csv.json"):
                continue
            csv_path = os.path.join(dir_path, name)
            lab = csv_path + ".json" if os.path.isfile(csv_path + ".json") else None
            metrics = run_auxiliary_metrics(code, csv_path, json.load(open(lab, encoding="utf-8")) if lab else None)
            row: SampleCalibration = {"image_path": csv_path, "metrics": metrics}
            if metrics.get("error"):
                row["error"] = str(metrics.get("error"))
            rows.append(row)
            n += 1
            if n >= max_images:
                break
        return rows
    for png in collect_png_paths(dir_path, limit=max_images):
        label = _load_label_for_image(dir_path, png)
        metrics = run_auxiliary_metrics(code, png, label)
        row = {"image_path": png, "metrics": metrics}
        if metrics.get("error"):
            row["error"] = str(metrics.get("error"))
        rows.append(row)
    return rows


def _optional_pipeline_check(dir_path: str, *, limit: int = 2) -> dict[str, Any]:
    """Dry-run run_pipeline (rules only). Does not touch 星海舰队."""
    py = sys.executable
    pipeline_script = os.path.join(_pipeline_root(), "agent", "run_pipeline.py")
    if not os.path.isfile(pipeline_script):
        return {"skipped": "run_pipeline.py missing"}
    cmd = [py, pipeline_script, "--dir", dir_path, "--limit", str(limit), "--physics", "skip", "--no-postprocess"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=_pipeline_root())
        summary = {"exit_code": proc.returncode, "stdout_tail": proc.stdout[-1500:], "stderr_tail": proc.stderr[-800:]}
        return summary
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except OSError as exc:
        return {"error": str(exc)}


def run_debate_session(
    dir_path: str,
    *,
    secrets_path: str | None = None,
    offline: bool = False,
    max_refine: int = 1,
    image_sample: int = 3,
    pipeline_check: bool = False,
    json_sample: int = 12,
    teaching_mode: str = "auto",
) -> DebateSession:
    dir_path = os.path.abspath(dir_path)
    dir_id = os.path.basename(os.path.normpath(dir_path))
    workspace = _workspace(dir_id)
    secrets = load_secrets(secrets_path) if secrets_path else load_secrets()
    endpoint = model_endpoint(secrets)
    has_llm = bool(endpoint.get("key")) and bool(endpoint.get("text")) and not offline

    route = route_dataset_directory(dir_path, json_sample=json_sample, image_sample=max(image_sample, 2))
    route_serial = json.loads(json.dumps(route, default=str))
    route_debate = prepare_route_for_debate(route_serial)
    session: DebateSession = {
        "dir_id": dir_id,
        "dir_path": dir_path,
        "route": route_serial,
        "workspace": workspace,
        "turns": [],
        "notes": [
            "星海舰队交付包未被修改；产物仅写在 experiments/scientific_debater/",
            f"llm={'yes' if has_llm else 'offline'}",
        ],
        "ok": False,
    }
    _write_turn(workspace, session, {"phase": "meta", "prompt_summary": "session_start", "response": dir_id, "offline": not has_llm})

    profile = route.get("profile") or {}
    visual = profile.get("visual") or {}
    archetype_id = route.get("archetype_id") or "unknown"
    pipeline = route.get("pipeline") or "UNKNOWN"
    physics_track = ""
    for hit in route_debate.get("rag_hits") or []:
        if hit.get("physics_track"):
            physics_track = hit["physics_track"]
            break

    # --- Phase 1 task context ---
    p1 = phase_task_context(route_debate)
    if has_llm:
        r1 = _llm_text(p1, secrets, max_tokens=750)
        t1 = cap_phase_answer(r1.get("text") or "", "task_context")
        u1 = r1.get("usage") or {}
    else:
        t1 = (
            f"## 检索策略（offline）\n搜索：{archetype_id} + OPC 标注字段 + instrument handbook。\n"
            f"## 处理目标\n对齐 pipeline={pipeline}，Gap：主库 physics_track 未为 {archetype_id} 单独分叉。\n"
        )
        u1 = {}
    _write_turn(
        workspace,
        session,
        {
            "phase": "task_context",
            "prompt_summary": p1[:200],
            "response": t1,
            "usage": u1,
            "offline": not has_llm,
        },
    )

    # --- Phase 2 defect visual (vision on first png if available) ---
    p2 = phase_defect_visual(archetype_id, visual)
    pngs = collect_png_paths(dir_path, limit=1)
    if has_llm and pngs:
        r2 = _llm_vision(phase_vision_defect_check(archetype_id) + "\n" + p2[:1200], pngs[0], secrets)
        t2 = cap_phase_answer(r2.get("text") or "", "defect_visual")
        u2 = r2.get("usage") or {}
    elif has_llm:
        r2 = _llm_text(p2, secrets, max_tokens=900)
        t2 = cap_phase_answer(r2.get("text") or "", "defect_visual")
        u2 = r2.get("usage") or {}
    else:
        t2 = p2 + "\n\n(offline) 九类图像侧：C03b 轮廓、C07 漏标亮区、噪声伪影→待复核。"
        u2 = {}
    _write_turn(workspace, session, {"phase": "defect_visual", "prompt_summary": p2[:200], "response": t2, "usage": u2, "offline": not has_llm})

    teaching_block = build_teaching_block(
        pipeline=pipeline,
        archetype_id=archetype_id,
        dir_id=dir_id,
        mode=teaching_mode,
    )
    session["teaching_mode"] = teaching_mode
    with open(os.path.join(workspace, "TEACHING_CONTEXT.md"), "w", encoding="utf-8") as handle:
        handle.write(teaching_block)

    # --- Phase 3 metrics ---
    p3 = phase_metric_proposals((t1 + "\n" + t2)[:2800], archetype_id, teaching_block="")
    if has_llm:
        r3 = _llm_text(p3, secrets, max_tokens=1000)
        t3 = cap_phase_answer(r3.get("text") or "", "metric_proposals")
        u3 = r3.get("usage") or {}
    else:
        t3 = "径向梯度、局部对比度、遮挡盘均值、盐胡椒占比 → 供 auxiliary_metrics 输出。"
        u3 = {}
    _write_turn(workspace, session, {"phase": "metric_proposals", "prompt_summary": p3[:200], "response": t3, "usage": u3, "offline": not has_llm})

    dialogue: dict[str, str] = {
        "task_context": t1,
        "defect_visual": t2,
        "metric_proposals": t3,
    }

    p_hgeo = phase_heuristic_geometry(pipeline, archetype_id, t3)
    if has_llm:
        r_hg = _llm_text(p_hgeo, secrets, max_tokens=1200)
        t_hg = cap_phase_answer(r_hg.get("text") or "", "heuristic_geometry")
        _write_turn(workspace, session, {"phase": "heuristic_geometry", "prompt_summary": p_hgeo[:200], "response": t_hg, "usage": r_hg.get("usage") or {}, "offline": False})
    else:
        t_hg = "（offline）按 pipeline 区分环带 vs band vs 时间窗。"
    dialogue["heuristic_geometry"] = t_hg

    p_himg = phase_heuristic_image_defects(pipeline, t2)
    if has_llm:
        r_hi = _llm_text(p_himg, secrets, max_tokens=850)
        t_hi = cap_phase_answer(r_hi.get("text") or "", "heuristic_image_defects")
        _write_turn(workspace, session, {"phase": "heuristic_image_defects", "prompt_summary": p_himg[:200], "response": t_hi, "usage": r_hi.get("usage") or {}, "offline": False})
    else:
        t_hi = ""
    dialogue["heuristic_image_defects"] = t_hi

    session["dialogue_bundle"] = dialogue
    with open(os.path.join(workspace, "DIALOGUE_BUNDLE.md"), "w", encoding="utf-8") as handle:
        handle.write(bundle_markdown(dialogue))
    json.dump(
        {"route_debate": route_debate, "prompt_budget": estimate_v0_prompt_chars(dialogue)},
        open(os.path.join(workspace, "rag_debate_context.json"), "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )

    synth_v0 = synthesis_for_script(dialogue, stage="v0")
    p4 = phase_draft_script(
        archetype_id,
        pipeline,
        t3,
        physics_track=physics_track,
        teaching_block="",
        synthesis_block=synth_v0,
        version_tag="v0",
    )
    v0_source = "offline"
    if has_llm:
        v0_max_tok = 2400
        r4 = _llm_text(p4, secrets, max_tokens=v0_max_tok)
        raw4 = r4.get("text") or ""
        u4 = r4.get("usage") or {}
        draft = _code_from_llm_response(raw4)
        if not draft:
            code = _offline_script_choice(dir_id, archetype_id, pipeline, visual)
            v0_source = "offline_no_function"
            session["notes"].append("v0_llm_missing auxiliary_metrics -> offline")
        else:
            code, v0_source, _ = _ensure_v0_code(
                first_code=draft,
                first_usage=u4,
                dir_id=dir_id,
                archetype_id=archetype_id,
                pipeline=pipeline,
                visual=visual,
                secrets=secrets,
                metric_text=t3,
                physics_track=physics_track,
                max_tokens=v0_max_tok,
            )
            if v0_source.startswith("offline"):
                session["notes"].append(f"v0_{v0_source}")
            elif v0_source == "llm_v0_truncated":
                session["notes"].append("v0_llm_likely_truncated -> compact retry or offline")
    else:
        raw4 = "(offline template)"
        code = _offline_script_choice(dir_id, archetype_id, pipeline, visual)
        u4 = {}
    script_path = os.path.join(workspace, "auxiliary_metrics.py")
    _save_script_version(workspace, code, "v0")
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write(code)
    session["draft_script_path"] = script_path
    session["script_versions"] = ["v0"]
    session["v0_source"] = v0_source if has_llm else "offline"
    _write_turn(
        workspace,
        session,
        {"phase": "draft_script_v0", "prompt_summary": p4[:200], "response": raw4[:8000], "usage": u4, "offline": not has_llm},
    )

    calibration = calibrate_script(code, dir_path, max_images=image_sample, pipeline=pipeline)
    if calibration and all((r.get("metrics") or {}).get("error") for r in calibration):
        session["notes"].append("v0_cal_failed -> offline template fallback")
        code = _offline_script_choice(dir_id, archetype_id, pipeline, visual)
        _save_script_version(workspace, code, "v0")
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(_clean_code(code))
        calibration = calibrate_script(code, dir_path, max_images=image_sample, pipeline=pipeline)
    session["calibration"] = calibration
    _save_calibration(workspace, "v0", calibration)
    v0_calibration = json.loads(json.dumps(calibration))

    pipe_summary = _optional_pipeline_check(dir_path) if pipeline_check else {"skipped": True}
    session["pipeline_dry_run"] = pipe_summary

    v1_reasoning = ""

    def _heur_v2(cal: list[dict], c: str) -> str:
        return phase_heuristic_pre_v2(
            pipeline,
            cal,
            c[:8000],
            v1_reasoning_excerpt=v1_reasoning,
        )

    refine_plan = [
        ("v1", "heuristic_pre_v1", lambda cal, c: phase_heuristic_pre_v1(pipeline, archetype_id, cal, teaching_block)),
        ("v2", "heuristic_pre_v2", _heur_v2),
    ]
    for idx in range(max_refine):
        if not has_llm:
            break
        ver, heur_key, heur_fn = refine_plan[idx] if idx < len(refine_plan) else (f"v{idx+1}", f"heuristic_pre_v{idx+1}", None)
        if heur_fn:
            p_h = heur_fn(calibration, code)
            r_h = _llm_text(p_h, secrets, max_tokens=1400)
            t_h = r_h.get("text") or ""
            dialogue[heur_key] = t_h
            session["dialogue_bundle"] = dialogue
            with open(os.path.join(workspace, "DIALOGUE_BUNDLE.md"), "w", encoding="utf-8") as handle:
                handle.write(bundle_markdown(dialogue))
            _write_turn(
                workspace,
                session,
                {
                    "phase": heur_key,
                    "prompt_summary": p_h[:200],
                    "response": t_h[:8000],
                    "usage": r_h.get("usage") or {},
                    "offline": False,
                },
            )
        heur_ans = dialogue.get(heur_key, "")
        if ver == "v1":
            p5 = phase_refine_v1(
                code,
                v0_calibration,
                teaching_block=teaching_block,
                heuristic_answers=heur_ans,
                pipeline=pipeline,
                archetype_id=archetype_id,
                physics_track=physics_track,
                pipeline_result=pipe_summary if pipeline_check else None,
            )
        else:
            p5 = phase_refine_v2(
                code,
                v0_calibration,
                calibration,
                v1_reasoning=v1_reasoning,
                teaching_block=teaching_block,
                heuristic_answers=heur_ans,
                pipeline=pipeline,
                archetype_id=archetype_id,
                pipeline_result=pipe_summary if pipeline_check else None,
            )
        r5 = _llm_text(p5, secrets, max_tokens=3200)
        full_reply = r5.get("text") or ""
        new_code = extract_python_block(full_reply) or ""
        new_code = extract_python_block(new_code) or new_code
        if not new_code or "def auxiliary_metrics" not in new_code:
            break
        if ver == "v1":
            v1_reasoning = full_reply
            session["v1_reasoning_trace"] = full_reply[:20000]
            with open(os.path.join(workspace, "V1_REASONING.md"), "w", encoding="utf-8") as handle:
                handle.write(full_reply)
        code = new_code
        _save_script_version(workspace, code, ver)
        session.setdefault("script_versions", []).append(ver)
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(code)
        calibration = calibrate_script(code, dir_path, max_images=image_sample, pipeline=pipeline)
        if calibration and all((r.get("metrics") or {}).get("error") for r in calibration):
            session["notes"].append(f"{ver}_cal_all_failed")
            if ver == "v2" and os.path.isfile(os.path.join(workspace, "auxiliary_metrics_v1.py")):
                with open(os.path.join(workspace, "auxiliary_metrics_v1.py"), encoding="utf-8") as handle:
                    code = handle.read()
                with open(script_path, "w", encoding="utf-8") as handle:
                    handle.write(_clean_code(code))
                calibration = calibrate_script(code, dir_path, max_images=image_sample, pipeline=pipeline)
                session["notes"].append("v2_reverted_to_v1_after_cal_fail")
                break
        session["calibration"] = calibration
        _save_calibration(workspace, ver, calibration)
        _write_turn(
            workspace,
            session,
            {
                "phase": f"draft_script_{ver}",
                "prompt_summary": p5[:200],
                "response": (r5.get("text") or "")[:8000],
                "usage": r5.get("usage") or {},
                "offline": False,
            },
        )

    versions = session.get("script_versions") or ["v0"]
    evolution = audit_versions(workspace)
    session["evolution_audit"] = evolution
    best_tag, calibration = _pick_best_script_version(workspace, versions)
    session["calibration"] = calibration
    session["best_script_version"] = best_tag
    session["notes"].append(f"best_script={best_tag} (auto-pick after refine)")
    if not calibration:
        pngs_exist = bool(collect_png_paths(dir_path, limit=1))
        cal_ok = pipeline == "ULF" and not pngs_exist
    else:
        cal_ok = all(not (c.get("metrics") or {}).get("error") for c in calibration)
    session["ok"] = bool(code) and cal_ok
    session["notes"].append(f"finished_utc={datetime.now(timezone.utc).isoformat()}")
    _write_turn(workspace, session, {"phase": "done", "prompt_summary": "ok", "response": json.dumps({"ok": session["ok"]})})

    # auxiliary jsonl for downstream Pass1 hook (experimental)
    jsonl_path = os.path.join(workspace, "auxiliary_metrics.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for row in calibration:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    session["auxiliary_jsonl"] = jsonl_path
    _save_calibration(workspace, "final", calibration)
    modality = pipeline if pipeline in ("AIA", "EPB", "ULF") else "AIA"
    hook = verify_pass1_hook(
        dir_path=dir_path,
        script_path=os.path.join(workspace, "auxiliary_metrics.py"),
        modality=modality,
        limit=1,
    )
    session["pass1_hook_dry_run"] = hook
    session["ok"] = bool(session.get("ok")) and bool(hook.get("ok"))
    report_path = build_demo_report(workspace=workspace, route=route_serial, session=session)
    session["demo_report"] = report_path
    json.dump(session, open(os.path.join(workspace, "debate_session.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return session