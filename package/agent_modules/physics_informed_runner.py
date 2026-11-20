"""Parallel Pass1+Pass2 physics-informed jsonl writer (thread-safe append)."""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable


def done_ids(jsonl_path: str) -> set[str]:
    done: set[str] = set()
    if not os.path.isfile(jsonl_path):
        return done
    for line in open(jsonl_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        oid = row.get("objectId") or row.get("id")
        if oid and not row.get("error"):
            done.add(str(oid))
    return done


def run_parallel_jsonl(
    pairs: list[tuple[Any, ...]],
    *,
    out_jsonl: str,
    append: bool,
    workers: int,
    process_one: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    process_one(*pair) -> record dict (must include objectId).
    Writes each line under a lock; flush per record.
    """
    mode = "a" if append else "w"
    lock = threading.Lock()
    rows: list[dict[str, Any]] = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    t0 = time.perf_counter()

    with open(out_jsonl, mode, encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(process_one, pair): pair for pair in pairs}
            for fut in as_completed(futures):
                record = fut.result()
                with lock:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                rows.append(record)
                for stage in ("pass1", "pass2"):
                    u = (record.get(stage) or {}).get("usage") or {}
                    for key in usage_total:
                        usage_total[key] += int(u.get(key) or 0)
                if on_progress:
                    on_progress(record)

    elapsed = round(time.perf_counter() - t0, 2)
    return rows, {**usage_total, "elapsed_sec": int(elapsed)}
