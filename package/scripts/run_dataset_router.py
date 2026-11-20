#!/usr/bin/env python3
"""CLI: profile one dataset dir and print router JSON (+ optional legacy compare)."""

from __future__ import annotations

import argparse
import os
import sys

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(PIPELINE_ROOT, "agent_modules")
sys.path.insert(0, PKG)

from dataset_router import route_to_json  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--json-sample", type=int, default=20)
    parser.add_argument("--image-sample", type=int, default=4)
    parser.add_argument("--no-legacy", action="store_true")
    args = parser.parse_args()
    print(route_to_json(args.dir, json_sample=args.json_sample, image_sample=args.image_sample, compare_legacy=not args.no_legacy))


if __name__ == "__main__":
    main()