#!/usr/bin/env python3
"""Deep-test debater on AIA/EPB/ULF dirs + compare vs prepare_* (星海舰队标准轨)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(PIPELINE_ROOT, "package")
REPO_ROOT = os.environ.get("ROADSHOW_REPO_ROOT", os.path.dirname(PIPELINE_ROOT))
sys.path.insert(0, os.path.join(PKG, "agent_modules"))
sys.path.insert(0, os.path.join(PKG, "scripts"))

from scientific_debater.debate_runner import run_debate_session  # noqa: E402

# z4 全量若不在本机，用同 schema 的 colab AIA；EPB/ULF 用路演深测目录
DEEP = [
    ("AIA", "AIA_AR_sample_mugm2urshy", os.path.join(REPO_ROOT, "colab_subset", "publish", "AIA_AR_sample_mugm2urshy"), "AIA 深测代理"),
    ("EPB", "EPB_seg_sample_fbbqy66u2d", os.path.join(REPO_ROOT, "路演数据", "EPB_seg_sample_fbbqy66u2d"), "fbbqy 深测"),
    ("ULF", "ULF_sample_xfnogkdey9", os.path.join(REPO_ROOT, "路演数据", "ULF_sample_xfnogkdey9"), "xfnog 深测"),
]


def main() -> None:
    secrets = os.path.join(REPO_ROOT, "secrets.yaml")
    os.environ.setdefault("MODEL_DISABLE_THINKING", "1")
    PY = sys.executable
    results = []
    for modality, dir_id, path, label in DEEP:
        if not os.path.isdir(path):
            results.append({"modality": modality, "dir_id": dir_id, "skipped": path})
            continue
        sess = run_debate_session(
            path,
            secrets_path=secrets,
            offline=False,
            max_refine=2,
            image_sample=3,
            pipeline_check=True,
            teaching_mode="spine_full",
            json_sample=16,
        )
        script = os.path.join(sess["workspace"], "auxiliary_metrics.py")
        cmp_cmd = [
            PY,
            os.path.join(PKG, "scripts", "compare_debater_vs_standard.py"),
            "--dir",
            path,
            "--modality",
            modality,
            "--script",
            script,
            "--limit",
            "2",
            "--pipeline",
        ]
        subprocess.run(cmp_cmd, check=False)
        results.append(
            {
                "modality": modality,
                "dir_id": dir_id,
                "note": label,
                "ok": sess.get("ok"),
                "best": sess.get("best_script_version"),
                "sane_evolution": (sess.get("evolution_audit") or {}).get("sane_evolution"),
                "workspace": sess.get("workspace"),
                "demo": sess.get("demo_report"),
                "dialogue": os.path.join(sess["workspace"], "DIALOGUE_BUNDLE.md"),
                "compare": os.path.join(sess["workspace"], "COMPARE_STANDARD.json"),
            }
        )

    out = os.path.join(PIPELINE_ROOT, "experiments", "scientific_debater", "DEEP_THREE_COMPARE.json")
    json.dump({"runs": results}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    md_lines = ["# 深测三模态 Debater vs 标准 prepare_*\n"]
    for r in results:
        md_lines.append(
            f"- **{r.get('modality')}** `{r.get('dir_id')}` ({r.get('note')}) ok={r.get('ok')} best={r.get('best')}\n"
            f"  - 辩题全集：`{r.get('dialogue')}`\n"
            f"  - 对比：`{r.get('compare')}`\n"
        )
    md_path = os.path.join(PIPELINE_ROOT, "experiments", "scientific_debater", "DEEP_THREE_COMPARE.md")
    open(md_path, "w", encoding="utf-8").write("".join(md_lines))
    print(json.dumps({"index": out, "markdown": md_path, "runs": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()