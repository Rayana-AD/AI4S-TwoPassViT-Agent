"""Paths for Agent-Pipeline (self-contained). Data defaults to sibling 路演数据 under repo root."""

from __future__ import annotations

import os
import sys

_PIPELINE_ROOT = os.environ.get(
    "AGENT_PIPELINE_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
_REPO_ROOT = os.environ.get("ROADSHOW_REPO_ROOT", os.path.dirname(_PIPELINE_ROOT))

ROADSHOW_DATA = os.environ.get("ROADSHOW_DATA", os.path.join(_REPO_ROOT, "路演数据"))
AGENT_MODULES = os.environ.get("AGENT_MODULES", os.path.join(_PIPELINE_ROOT, "package", "agent_modules"))
SCRIPTS_DIR = os.environ.get("AGENT_PIPELINE_SCRIPTS", os.path.join(_PIPELINE_ROOT, "package", "scripts"))
RESULTS_DIR = os.environ.get("ROADSHOW_RESULTS", os.path.join(_PIPELINE_ROOT, "results"))


def ensure_agent_path() -> None:
    for p in (AGENT_MODULES, SCRIPTS_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)


def dir_aia_primary() -> str:
    return os.environ.get("ROADSHOW_DIR_AIA", os.path.join(ROADSHOW_DATA, "AIA_AR_sample_z4h764sf2d"))


def dir_epb_primary() -> str:
    return os.environ.get("ROADSHOW_DIR_EPB", os.path.join(ROADSHOW_DATA, "EPB_seg_sample_fbbqy66u2d"))


def dir_ulf_primary() -> str:
    return os.environ.get("ROADSHOW_DIR_ULF", os.path.join(ROADSHOW_DATA, "ULF_sample_xfnogkdey9"))
