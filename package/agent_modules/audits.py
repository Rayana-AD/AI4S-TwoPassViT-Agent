"""Deterministic checks. Pixel-box tasks and waveforms do not share a metric."""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timezone

PASS = "通过"
FAIL = "不通过"
REVIEW = "待复核"
UNDECIDED = "待判定"
NA = "不适用"

_COUNTED = {PASS, FAIL, REVIEW}
_IMG_SIZE = re.compile(r"(\d+)\s*[xX×]\s*(\d+)")
_MANIFEST = "/Users/rayana/Desktop/空间科学/colab_subset/manifest.tsv"
_INDEX: set[tuple[str, str]] | None = None


def _item(check: str, status: str, detail: str, counts: bool | None = None) -> dict:
    if counts is None:
        counts = status in _COUNTED
    return {"check": check, "status": status, "detail": detail, "counts": counts}


def overall_status(checks: list[dict]) -> str:
    """不适用 and non-counted composition notes do not fail a sample."""
    counted = [item for item in checks if item.get("counts")]
    if any(item["status"] == FAIL for item in counted):
        return FAIL
    if any(item["status"] in {REVIEW, UNDECIDED} for item in counted):
        return REVIEW
    return PASS


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def file_name_of(obj: dict) -> str:
    header = obj.get("label_header") or {}
    basic = obj.get("basic_annotation") or {}
    return str(header.get("fileName") or basic.get("fileName") or "")


def dataset_name_of(json_path: str) -> str:
    parts = json_path.replace("\\", "/").split("/")
    if "publish" in parts:
        index = parts.index("publish")
        if index + 1 < len(parts):
            return parts[index + 1]
    parent = os.path.basename(os.path.dirname(json_path))
    if parent == "label":
        return os.path.basename(os.path.dirname(os.path.dirname(json_path)))
    return parent


def dataset_dir_of(json_path: str) -> str:
    parent = os.path.dirname(json_path)
    if os.path.basename(parent) == "label":
        return os.path.dirname(parent)
    return parent


def load_package_index(manifest_path: str = _MANIFEST) -> set[tuple[str, str]]:
    """(dataset, data basename) for every non-JSON file named in the local manifest."""
    global _INDEX
    if _INDEX is not None and manifest_path == _MANIFEST:
        return _INDEX
    found: set[tuple[str, str]] = set()
    with open(manifest_path, encoding="utf-8") as handle:
        next(handle, None)
        for line in handle:
            rel = line.split("\t", 1)[0]
            if rel.endswith(".json"):
                continue
            parts = rel.split("/")
            if len(parts) < 3:
                continue
            found.add((parts[1], parts[-1]))
    if manifest_path == _MANIFEST:
        _INDEX = found
    return found


def referenced_in_package(obj: dict, json_path: str, index: set[tuple[str, str]] | None = None) -> bool:
    name = file_name_of(obj)
    if not name:
        return False
    if index is None:
        try:
            index = load_package_index()
        except OSError:
            index = set()
    ds = dataset_name_of(json_path)
    if index and any(item[0] == ds for item in index):
        return (ds, name) in index
    # Standalone dataset directory or roadshow directory: check if file is present on disk
    return local_data_path(json_path, name) is not None


def local_data_path(json_path: str, file_name: str | None = None) -> str | None:
    if not file_name:
        return None
    root = dataset_dir_of(json_path)
    # Fast paths before os.walk
    cand1 = os.path.join(os.path.dirname(json_path), file_name)
    if os.path.isfile(cand1):
        return cand1
    cand2 = os.path.join(root, file_name)
    if os.path.isfile(cand2):
        return cand2
    cand3 = os.path.join(root, "data", file_name)
    if os.path.isfile(cand3):
        return cand3
    for dirpath, _, names in os.walk(root):
        if file_name in names:
            return os.path.join(dirpath, file_name)
    return None


def observation_time(obj: dict) -> str:
    basic = obj.get("basic_annotation") or {}
    science = obj.get("science_annotation") or {}
    return str(basic.get("startTime") or basic.get("timestamp") or science.get("dateObs") or "")


def _as_points(raw) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not isinstance(raw, list):
        return points
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and not isinstance(item[0], (list, tuple)):
            points.append((float(item[0]), float(item[1])))
    return points


def _rectangle(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) != 2:
        return points
    (x0, y0), (x1, y1) = points
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _hek_pixel_rings(obj: dict) -> list[dict]:
    rings: list[dict] = []
    hek = obj.get("hek_event_annotation") or {}
    for event in hek.get("matched_events") or []:
        if not isinstance(event, dict) or not event.get("bbox_polygon_pixel"):
            continue
        points = _as_points(event.get("bbox_polygon_pixel"))
        if len(points) >= 3:
            rings.append({
                "label": str(event.get("event_type") or event.get("eventtype") or ""),
                "points": points,
                "shape_type": "polygon",
            })
    return rings


def _science_mask_rings(obj: dict) -> list[dict]:
    rings: list[dict] = []
    science = obj.get("science_annotation") or {}
    mask = science.get("mask")
    if isinstance(mask, dict):
        for shape in mask.get("shapes") or []:
            points = _as_points(shape.get("points"))
            if len(points) >= 3:
                rings.append({
                    "label": str(shape.get("label") or ""),
                    "points": points,
                    "shape_type": str(shape.get("shape_type") or "polygon"),
                })
    for shape in science.get("specialShapes") or []:
        points = _as_points(shape.get("points"))
        if len(points) >= 2:
            kind = str(shape.get("shape_type") or "rectangle")
            ring = _rectangle(points) if kind == "rectangle" else points
            rings.append({"label": str(shape.get("label") or ""), "points": ring, "shape_type": kind})
    return rings


def pixel_rings(obj: dict) -> list[dict]:
    """Pixel polygons and rectangles. CME catalog fields are not included."""
    # AIA (路演 01): hek_event_annotation.matched_events[].bbox_polygon_pixel only.
    if "hek_event_annotation" in obj:
        return _hek_pixel_rings(obj)
    return _science_mask_rings(obj)


def epb_mask_field_paths(obj: dict) -> list[str]:
    """fieldPath for each drawable mask shape, aligned with pixel_rings() order."""
    paths: list[str] = []
    mask = (obj.get("science_annotation") or {}).get("mask") or {}
    for idx, shape in enumerate(mask.get("shapes") or []):
        points = _as_points(shape.get("points"))
        if len(points) >= 3:
            paths.append(f"science_annotation.mask.shapes[{idx}].polygon")
    return paths


def aia_hek_field_paths(obj: dict) -> list[str]:
    """fieldPath for each drawable ring, aligned with pixel_rings() order."""
    paths: list[str] = []
    for idx, event in enumerate((obj.get("hek_event_annotation") or {}).get("matched_events") or []):
        if not isinstance(event, dict) or not event.get("bbox_polygon_pixel"):
            continue
        points = _as_points(event.get("bbox_polygon_pixel"))
        if len(points) >= 3:
            paths.append(f"hek_event_annotation.matched_events[{idx}].bbox_polygon_pixel")
    return paths


def _all_points(rings: list[dict]) -> list[tuple[float, float]]:
    return [point for ring in rings for point in ring["points"]]


def real_frame(obj: dict) -> tuple[int, int] | None:
    basic = obj.get("basic_annotation") or {}
    if basic.get("imageWidth") and basic.get("imageHeight"):
        return int(float(basic["imageWidth"])), int(float(basic["imageHeight"]))
    science = obj.get("science_annotation") or {}
    mask = science.get("mask")
    if isinstance(mask, dict) and mask.get("imageWidth") and mask.get("imageHeight"):
        return int(mask["imageWidth"]), int(mask["imageHeight"])
    if "hek_event_annotation" in obj:
        return 4096, 4096
    return None


def _outside(points: list[tuple[float, float]], width: int, height: int) -> int:
    count = 0
    for x, y in points:
        if x < -0.5 or y < -0.5 or x > width + 0.5 or y > height + 0.5:
            count += 1
    return count


def _declared_size(obj: dict) -> tuple[int, int] | None:
    basic = obj.get("basic_annotation") or {}
    match = _IMG_SIZE.search(str(basic.get("imgSize") or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def json_consistency(
    obj: dict,
    data_name_exists: bool,
    time_count: int | None = None,
) -> list[dict]:
    """Text and JSON rules. Missing fields are 不适用 and are not scored."""
    findings: list[dict] = []
    name = file_name_of(obj)
    findings.append(_item(
        "引用文件",
        FAIL if not name or not data_name_exists else PASS,
        name or "标注没有 fileName",
    ))

    counted_events = False
    for key in ("hek_event_annotation", "ulf_event_annotation"):
        block = obj.get(key)
        if not isinstance(block, dict) or "event_count" not in block:
            continue
        counted_events = True
        matched = block.get("matched_events") or []
        count = block.get("event_count")
        ok = isinstance(count, int) and count == len(matched)
        findings.append(_item(
            "event_count",
            PASS if ok else FAIL,
            f"event_count={count}，列表 {len(matched)} 条",
        ))
    if not counted_events:
        findings.append(_item("event_count", NA, "没有 event_count", counts=False))

    if isinstance(obj.get("ulf_event_annotation"), dict):
        findings.append(_ulf_has_events_consistency(obj))

    findings.append(_cme_value_check(obj))
    findings.append(_ulf_time_check(obj))

    if "hek_event_annotation" in obj:
        has_pixel = any(
            isinstance(event, dict) and event.get("bbox_polygon_pixel")
            for event in (obj.get("hek_event_annotation") or {}).get("matched_events") or []
        )
        findings.append(_item(
            "像素框",
            PASS if has_pixel else NA,
            "事件带像素框" if has_pixel else "没有像素框。目录型事件这样是格式，不是缺陷",
            counts=False,
        ))
    else:
        findings.append(_item("像素框", NA, "没有事件像素框字段", counts=False))

    rings = pixel_rings(obj)
    points = _all_points(rings)
    frame = real_frame(obj)
    if not points or frame is None:
        findings.append(_item("像素越界", NA, "没有可核对的像素坐标", counts=False))
    else:
        width, height = frame
        bad = _outside(points, width, height)
        findings.append(_item(
            "像素越界",
            FAIL if bad else PASS,
            f"真实画面 {width}×{height}，越界点 {bad}",
        ))

    declared = _declared_size(obj)
    if declared is None:
        findings.append(_item("声明尺寸", NA, "没有 imgSize", counts=False))
    else:
        real = frame
        outside_declared = _outside(points, declared[0], declared[1]) if points else 0
        mismatch = real is not None and declared != real
        if mismatch or outside_declared:
            real_text = f"{real[0]}×{real[1]}" if real else "未知"
            findings.append(_item(
                "声明尺寸",
                FAIL,
                f"声明 {declared[0]}×{declared[1]}，真实画面 {real_text}，超出声明的点 {outside_declared}",
            ))
        else:
            findings.append(_item(
                "声明尺寸",
                PASS,
                f"声明 {declared[0]}×{declared[1]} 与画面一致",
            ))

    science = obj.get("science_annotation") or {}
    shape_labels = _shape_labels(science)
    if shape_labels is None:
        findings.append(_item("类别OOV", NA, "没有分割或矩形类别", counts=False))
    elif not shape_labels:
        findings.append(_item("类别OOV", NA, "没有类别可检查", counts=False))
    elif any(label == "__OOV__" for label in shape_labels):
        findings.append(_item("类别OOV", FAIL, "类别写成 __OOV__"))
    else:
        findings.append(_item("类别OOV", PASS, f"{len(shape_labels)} 个类别都不是 __OOV__"))

    if isinstance(science.get("mask"), dict):
        empty = not (science["mask"].get("shapes") or [])
        findings.append(_item(
            "空掩膜",
            NA,
            "空掩膜，记为数据构成，不参与排序" if empty else "不是空掩膜",
            counts=False,
        ))
    else:
        findings.append(_item("空掩膜", NA, "没有掩膜", counts=False))

    if "specialShapes" in science:
        shapes = science.get("specialShapes") or []
        findings.append(_item(
            "无矩形",
            NA,
            f"{len(shapes)} 个矩形" if shapes else "无矩形，记为数据构成，不参与排序",
            counts=False,
        ))
    else:
        findings.append(_item("无矩形", NA, "没有矩形字段", counts=False))

    if "qualityLevel" in science:
        findings.append(_item(
            "qualityLevel",
            NA,
            f"qualityLevel={science.get('qualityLevel')}，不能当作高/中/低",
            counts=False,
        ))
    else:
        findings.append(_item("qualityLevel", NA, "没有 qualityLevel", counts=False))

    if "hek_event_annotation" in obj or "ulf_event_annotation" in obj:
        block = obj.get("hek_event_annotation") or obj.get("ulf_event_annotation") or {}
        present = bool(block.get("matched_events"))
        findings.append(_item(
            "有无事件",
            NA,
            "数据构成：有事件" if present else "数据构成：无事件",
            counts=False,
        ))
    else:
        findings.append(_item("有无事件", NA, "没有事件列表", counts=False))

    if time_count is None:
        findings.append(_item("时刻重复", NA, "单条调用未做全数据集时刻统计", counts=False))
    elif time_count > 1:
        findings.append(_item(
            "时刻重复",
            REVIEW,
            f"该观测时刻还出现在其他样本中，共 {time_count} 条，先待复核",
        ))
    else:
        findings.append(_item("时刻重复", PASS, "该观测时刻在已统计范围内唯一"))

    for check, detail in (
        ("类别错标", "没有参考答案，不能判类别对错"),
        ("目标漏标", "没有参考答案，不能判漏标或误标"),
        ("划分泄漏", "没有划分清单，不能判训练测试泄漏"),
    ):
        findings.append(_item(check, UNDECIDED, detail, counts=False))
    return findings


def _cme_value_check(obj: dict) -> dict:
    events = (obj.get("hek_event_annotation") or {}).get("matched_events") or []
    catalog = [event for event in events if isinstance(event, dict) and ("width" in event or "central_pa" in event)]
    if not catalog:
        return _item("CME数值", NA, "不是日冕抛射目录事件", counts=False)
    illegal = []
    for event in catalog:
        width = event.get("width")
        angle = event.get("central_pa")
        speed = event.get("linear_speed")
        if width is not None:
            try:
                if not 0 <= float(width) <= 360:
                    illegal.append(f"width={width}")
            except (TypeError, ValueError):
                illegal.append(f"width={width}")
        if angle is not None:
            try:
                if not 0 <= float(angle) <= 360:
                    illegal.append(f"central_pa={angle}")
            except (TypeError, ValueError):
                illegal.append(f"central_pa={angle}")
        if speed is not None:
            try:
                value = float(speed)
                if value != value or value in (float("inf"), float("-inf")):
                    illegal.append("linear_speed 不是有限数")
            except (TypeError, ValueError):
                illegal.append("linear_speed 不是有限数")
    if illegal:
        return _item("CME数值", FAIL, "角宽或位置角超出 0–360°：" + "，".join(illegal[:4]))
    return _item("CME数值", PASS, "位置角、角宽在 0–360°，速度是有限数")


def _ulf_has_events_consistency(obj: dict) -> dict:
    """ULF: has_events must agree with matched_events list (九9 / 元数据)."""
    block = obj.get("ulf_event_annotation") or {}
    if "has_events" not in block:
        return _item("has_events一致", NA, "无 has_events 字段", counts=False)
    matched = block.get("matched_events") or []
    has_ev = bool(block.get("has_events"))
    n = len(matched)
    if has_ev and n == 0:
        return _item(
            "has_events一致",
            FAIL,
            "has_events=true 但 matched_events 为空",
        )
    if not has_ev and n > 0:
        return _item(
            "has_events一致",
            FAIL,
            f"has_events=false 但 matched_events 有 {n} 条",
        )
    return _item("has_events一致", PASS, f"has_events={has_ev}，列表 {n} 条")


def _ulf_time_check(obj: dict) -> dict:
    block = obj.get("ulf_event_annotation")
    if not isinstance(block, dict):
        return _item("事件时间范围", NA, "没有波形事件", counts=False)
    events = [event for event in block.get("matched_events") or [] if isinstance(event, dict)]
    if not events:
        return _item("事件时间范围", NA, "这条波形没有事件窗", counts=False)
    basic = obj.get("basic_annotation") or {}
    start = _parse_time(str(basic.get("startTime") or ""))
    end = _parse_time(str(basic.get("endTime") or ""))
    if start is None or end is None:
        return _item("事件时间范围", REVIEW, "读不到文件起止时间", counts=False)
    late = []
    for event in events:
        t0 = _parse_time(str(event.get("start_dt") or ""))
        t1 = _parse_time(str(event.get("end_dt") or ""))
        if t0 is None or t1 is None:
            continue
        if t0 < start or (t1 - end).total_seconds() > 1:
            late.append(f"{event.get('start_dt')}–{event.get('end_dt')}")
    if late:
        return _item(
            "事件时间范围",
            FAIL,
            "事件超出文件时段超过 1 秒：" + "；".join(late[:3]),
        )
    return _item("事件时间范围", PASS, "事件窗落在文件时段内，允许比 endTime 晚 1 秒")


def _shape_labels(science: dict) -> list[str] | None:
    if isinstance(science.get("mask"), dict):
        return [str(shape.get("label") or "") for shape in science["mask"].get("shapes") or []]
    if "specialShapes" in science:
        return [str(shape.get("label") or "") for shape in science.get("specialShapes") or []]
    return None


def timestamp_review(times: list[str]) -> dict:
    """Dataset-level clock collision. Shared times are 待复核, not confirmed duplicates."""
    usable = [item for item in times if item]
    counts: dict[str, int] = {}
    for item in usable:
        counts[item] = counts.get(item, 0) + 1
    shared_samples = sum(count for count in counts.values() if count > 1)
    if not usable:
        return _item("时刻重复", NA, "没有观测时刻", counts=False)
    if shared_samples == 0:
        return _item("时刻重复", PASS, f"{len(usable)} 条时刻互不重复")
    return _item(
        "时刻重复",
        REVIEW,
        f"{len(usable)} 条对 {len(counts)} 个时刻，{shared_samples} 条与其他样本共用时刻",
    )


def window_spans(obj: dict, n_rows: int) -> list[dict]:
    basic = obj.get("basic_annotation") or {}
    science = obj.get("science_annotation") or {}
    block = obj.get("ulf_event_annotation") or {}
    start = _parse_time(str(basic.get("startTime") or science.get("dateObs") or ""))
    spans = []
    for event in block.get("matched_events") or []:
        if not isinstance(event, dict):
            continue
        t0 = _parse_time(str(event.get("start_dt") or ""))
        t1 = _parse_time(str(event.get("end_dt") or ""))
        if start is None or t0 is None or t1 is None:
            spans.append({"kind": event.get("kind"), "i0": None, "i1": None, "note": "时间无法解析"})
            continue
        i0 = int((t0 - start).total_seconds())
        i1 = int((t1 - start).total_seconds())
        i0 = max(0, min(max(n_rows - 1, 0), i0))
        i1 = max(i0 + 1, min(n_rows, i1)) if n_rows else i0
        spans.append({"kind": event.get("kind"), "i0": i0, "i1": i1, "note": "", "event": event})
    return spans


def waveform_window(csv_path: str, obj: dict) -> dict:
    """Row count, then whether the labeled window holds a larger H excursion than the rest of the hour."""
    science = obj.get("science_annotation") or {}
    with open(csv_path, newline="") as handle:
        rows = list(csv.DictReader(handle))
    n_rows = len(rows)
    n_points = science.get("n_points")
    try:
        n_points_num = int(n_points)
    except (TypeError, ValueError):
        n_points_num = None
    length_ok = n_rows == 3600 and n_points_num == 3600
    length_status = PASS if length_ok else FAIL
    events = (obj.get("ulf_event_annotation") or {}).get("matched_events") or []
    if not events:
        return {
            "rows": n_rows,
            "n_points": n_points,
            "length_status": length_status,
            "window_status": NA,
            "detail": "没有时间窗事件",
            "spans": [],
        }
    try:
        h_values = [float(row["H"]) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "rows": n_rows,
            "n_points": n_points,
            "length_status": length_status,
            "window_status": REVIEW,
            "detail": f"读不到 H 列：{exc}",
            "spans": [],
        }
    median = sorted(h_values)[len(h_values) // 2]
    deviation = [abs(value - median) for value in h_values]
    spans = window_spans(obj, n_rows)
    reports = []
    hits = []
    for span in spans:
        event = span.get("event") or {}
        if span["i0"] is None:
            reports.append(span["note"])
            hits.append(False)
            continue
        i0, i1 = span["i0"], span["i1"]
        inside = deviation[i0:i1]
        outside = deviation[:i0] + deviation[i1:]
        if not inside or not outside:
            reports.append(f"{span.get('kind')} 窗口落在序列外")
            hits.append(False)
            continue
        outside_sorted = sorted(outside)
        outside_p95 = outside_sorted[int(0.95 * (len(outside_sorted) - 1))]
        peak = max(inside)
        hit = peak > outside_p95
        hits.append(hit)
        reports.append(
            f"{event.get('kind')} {event.get('start_dt')}–{event.get('end_dt')} "
            f"窗内最大偏离 {peak:.2f}，窗外 95% 为 {outside_p95:.2f}，"
            f"{'窗内有更强的峰或谷' if hit else '窗内没有超过窗外的峰或谷'}"
        )
    window_status = PASS if hits and all(hits) else REVIEW
    return {
        "rows": n_rows,
        "n_points": n_points,
        "length_status": length_status,
        "window_status": window_status,
        "detail": "；".join(reports),
        "spans": spans,
    }


def waveform_check_items(result: dict) -> list[dict]:
    items = [_item(
        "波形行数",
        result["length_status"],
        f"{result['rows']} 行，n_points={result.get('n_points')}，期望都是 3600",
    )]
    counts = result["window_status"] != NA
    items.append(_item("时间窗峰谷", result["window_status"], result["detail"], counts=counts))
    return items
