"""Stream-read OPC roadshow zip → per-dir .tar without full disk extract."""

from __future__ import annotations

import io
import json
import os
import tarfile
import zipfile
from typing import Any, Callable, Iterator

from .profiler import profile_from_parts
from .schema import DirectoryProfile

_MAX_JSON = 2_000_000
_MAX_PNG = 12_000_000


def list_opc_tar_members(zip_path: str) -> list[dict[str, Any]]:
    """List dataset tars inside OPC_路演测试数据.zip style layout."""
    out: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.endswith(".tar"):
                continue
            info = zf.getinfo(name)
            base = os.path.basename(name).replace(".tar", "")
            out.append(
                {
                    "dir_id": base,
                    "zip_member": name,
                    "compress_size": info.compress_size,
                    "file_size": info.file_size,
                }
            )
    return sorted(out, key=lambda r: r["dir_id"])


def _basename_in_tar(path: str) -> str:
    return path.rstrip("/").split("/")[-1]


def _parent_layout(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    if len(parts) >= 2:
        return parts[-2]
    return ""


def stream_tar_member(
    zip_path: str,
    tar_member: str,
    *,
    dir_id: str,
    json_sample: int = 20,
    image_sample: int = 3,
    on_progress: Callable[[str], None] | None = None,
) -> DirectoryProfile:
    """
    One linear pass over tar inside zip (``r|``); count topology + read small json/png only.
    Does not write to disk; suitable for multi-GB AIA tars (header scan + few bodies).
    """
    topo: dict[str, Any] = {
        "n_csv": 0,
        "n_csv_json": 0,
        "n_png_top": 0,
        "n_json_top": 0,
        "n_png_data": 0,
        "n_json_label": 0,
        "has_data_label": False,
        "source": "zip_tar_stream",
        "zip_path": zip_path,
        "tar_member": tar_member,
    }
    has_data = has_label = False
    json_blobs: list[tuple[str, dict]] = []
    png_blobs: list[tuple[str, bytes]] = []
    n_members = 0

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(tar_member) as raw:
            with tarfile.open(fileobj=raw, mode="r|") as tf:
                for info in tf:
                    n_members += 1
                    if not info.isfile():
                        continue
                    name = info.name.replace("\\", "/")
                    base = _basename_in_tar(name)
                    parent = _parent_layout(name)
                    if parent == "data" and base.endswith(".png"):
                        topo["n_png_data"] += 1
                        has_data = True
                    if parent == "label" and base.endswith(".json") and not base.endswith(".csv.json"):
                        topo["n_json_label"] += 1
                        has_label = True
                    if base.endswith(".csv") and not base.endswith(".csv.json"):
                        topo["n_csv"] += 1
                    elif base.endswith(".csv.json"):
                        topo["n_csv_json"] += 1
                    elif base.endswith(".png") and parent != "data":
                        topo["n_png_top"] += 1
                    elif base.endswith(".json") and not base.endswith(".csv.json") and parent != "label":
                        topo["n_json_top"] += 1

                    want_json = (
                        len(json_blobs) < json_sample
                        and base.endswith(".json")
                        and info.size <= _MAX_JSON
                    )
                    want_png = (
                        len(png_blobs) < image_sample
                        and base.endswith(".png")
                        and info.size <= _MAX_PNG
                    )
                    if not (want_json or want_png):
                        continue
                    f = tf.extractfile(info)
                    if not f:
                        continue
                    data = f.read()
                    if want_json and base.endswith(".json"):
                        try:
                            obj = json.loads(data.decode("utf-8"))
                            json_blobs.append((name, obj))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            pass
                    elif want_png:
                        png_blobs.append((name, data))
                    if on_progress and n_members % 5000 == 0:
                        on_progress(f"tar scan {n_members} members, json={len(json_blobs)} png={len(png_blobs)}")

    topo["has_data_label"] = has_data and has_label
    topo["tar_member_count"] = n_members
    layout = "unknown"
    if topo["has_data_label"]:
        layout = "data/label"
    elif topo["n_csv"] and topo["n_csv_json"]:
        layout = "flat_csv_json"
    elif topo["n_png_top"] or topo["n_json_top"] or topo["n_png_data"]:
        layout = "flat_png_json"

    from .profiler import annotation_stats_from_objects

    ann = annotation_stats_from_objects([o for _, o in json_blobs])
    vis_samples = []
    for path, blob in png_blobs:
        import tempfile

        # probe_image needs path — use BytesIO via temp not needed if we extend probe
        try:
            from PIL import Image

            with Image.open(io.BytesIO(blob)) as im:
                im = im.convert("RGB")
                w, h = im.size
                arr = __import__("numpy").array(im)
            from .visual_probe import _luma_stats, _tags

            mean, std, dark, bright = _luma_stats(arr)
            vis_samples.append(
                {
                    "path": f"tar:{path}",
                    "width": w,
                    "height": h,
                    "mean_luma": round(mean, 2),
                    "std_luma": round(std, 2),
                    "dark_fraction": round(dark, 4),
                    "bright_fraction": round(bright, 4),
                    "tags": _tags(mean, std, dark, bright, w, h),
                }
            )
        except Exception:
            continue
    tag_counts: dict[str, int] = {}
    for s in vis_samples:
        for t in s.get("tags") or []:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    visual = {
        "n_probed": len(vis_samples),
        "samples": vis_samples,
        "tag_counts": tag_counts,
        "typical_resolution": f"{vis_samples[0]['width']}x{vis_samples[0]['height']}" if vis_samples else "n/a",
    }
    return profile_from_parts(
        dir_id=dir_id,
        dir_path=f"zip:{zip_path}!{tar_member}",
        layout=layout,
        topo=topo,
        annotation=ann,
        visual=visual,
    )


def iter_opc_profiles(
    zip_path: str,
    *,
    json_sample: int = 20,
    image_sample: int = 3,
    only_dir_ids: list[str] | None = None,
) -> Iterator[DirectoryProfile]:
    for row in list_opc_tar_members(zip_path):
        if only_dir_ids and row["dir_id"] not in only_dir_ids:
            continue
        yield stream_tar_member(
            zip_path,
            row["zip_member"],
            dir_id=row["dir_id"],
            json_sample=json_sample,
            image_sample=image_sample,
        )