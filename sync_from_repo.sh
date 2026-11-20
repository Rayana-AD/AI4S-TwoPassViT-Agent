#!/usr/bin/env bash
# Refresh package/ from 空间科学 repo (run after code changes).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$REPO/Agent-Pipeline/package"
rsync -a --exclude '.venv' --exclude '__pycache__' \
  "$REPO/agent_modules/"*.py "$REPO/agent_modules/"*.json "$PKG/agent_modules/"
for f in roadshow_paths.py aia_dir_object_qc_csv.py epb_dir_object_qc_csv.py ulf_dir_object_qc_csv.py \
  physics_informed_aia.py physics_informed_epb.py physics_informed_ulf.py physics_informed_roadshow.py \
  aia_z4_full_pipeline.py aia_z4_postprocess.py epb_fbbqy_full_pipeline.py epb_fbbqy_postprocess.py \
  ulf_xfnog_full_pipeline.py ulf_xfnog_postprocess.py epb_physics_sample.py ulf_pi2_rule_viz.py; do
  cp "$REPO/路演结果/$f" "$PKG/scripts/"
done
cp "$PKG/roadshow_paths.py" "$PKG/scripts/roadshow_paths.py"
echo "Synced to $PKG"
