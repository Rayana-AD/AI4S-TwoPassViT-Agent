#!/usr/bin/env python3
"""Module tests on the local colab_subset. JSON rules do not open images or call a model."""

from __future__ import annotations

import json
import os
import sys

from audits import (
    FAIL,
    NA,
    PASS,
    REVIEW,
    UNDECIDED,
    file_name_of,
    json_consistency,
    load_package_index,
    observation_time,
    overall_status,
    pixel_rings,
    referenced_in_package,
    timestamp_review,
    waveform_window,
)
from graph import FAIL as GRAPH_FAIL
from graph import THRESHOLD_PATH, invoke_one, merge_node
from modality import classify_record
from spatial_precision import MAX_SIDE, calibrate_threshold, score_annotation, shift_rings
from vision import judge_spatial, load_secrets, render_waveform

ROOT = "/Users/rayana/Desktop/空间科学/colab_subset/publish"
OUT = os.path.join(os.path.dirname(__file__), "module_test_out")


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _status(checks: list[dict], name: str) -> dict:
    for item in checks:
        if item["check"] == name:
            return item
    raise AssertionError(f"missing check {name}")


def _jsons(dataset: str):
    root = os.path.join(ROOT, dataset)
    for dirpath, _, names in os.walk(root):
        for name in names:
            if name.endswith(".json"):
                yield os.path.join(dirpath, name)


def _find(dataset: str, predicate, limit: int = 8000) -> str | None:
    for index, path in enumerate(_jsons(dataset)):
        if index >= limit:
            break
        if predicate(_load(path), path):
            return path
    return None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_router() -> dict[str, str]:
    print("== type router ==")
    found = {
        "HMI": _find("HMI_AR_sample_6yaatkycjv", lambda obj, path: any(
            isinstance(event, dict) and event.get("bbox_polygon_pixel")
            for event in (obj.get("hek_event_annotation") or {}).get("matched_events") or []
        )),
        "AIA": _find("AIA_AR_sample_mugm2urshy", lambda obj, path: any(
            isinstance(event, dict) and event.get("bbox_polygon_pixel")
            for event in (obj.get("hek_event_annotation") or {}).get("matched_events") or []
        )),
        "CME": _find("CME_C2_sample_g8x0hw7reo", lambda obj, path: any(
            isinstance(event, dict) and ("width" in event or "central_pa" in event)
            for event in (obj.get("hek_event_annotation") or {}).get("matched_events") or []
        )),
        "DMSP_box": _find("DMSP_SSUSI_aaue04ws6s", lambda obj, path: bool(
            (obj.get("science_annotation") or {}).get("specialShapes")
        )),
        "DMSP_plain": _find("DMSP_SSUSI_aaue04ws6s", lambda obj, path: not (
            (obj.get("science_annotation") or {}).get("specialShapes")
        )),
        "EPB": _find("EPB_seg_sample_84baza8n1b", lambda obj, path: bool(
            ((obj.get("science_annotation") or {}).get("mask") or {}).get("shapes")
        )),
        "ULF": _find("ULF_sample_lj7rg82ela", lambda obj, path: True),
    }
    expected = {
        "HMI": "spatial_boxes",
        "AIA": "spatial_boxes",
        "CME": "event_catalog",
        "DMSP_box": "spatial_boxes",
        "DMSP_plain": "spatial_image",
        "EPB": "segmentation",
        "ULF": "waveform",
    }
    for name, kind in expected.items():
        path = found[name]
        _require(path is not None, f"{name} sample not found")
        got = classify_record(_load(path), path)
        _require(got == kind, f"{name} classified {got}, expected {kind}")
        print(f"{name}: {kind} | {os.path.basename(path)}")
    quiet_cme = _find("CME_C2_sample_g8x0hw7reo", lambda obj, path: not (
        (obj.get("hek_event_annotation") or {}).get("matched_events")
    ))
    _require(classify_record(_load(quiet_cme), quiet_cme) == "event_catalog", "quiet CME left the catalog route")
    return found


def test_json_rules(samples: dict[str, str]) -> None:
    print("\n== json rules ==")
    index = load_package_index()
    for name, path in samples.items():
        obj = _load(path)
        checks = json_consistency(obj, referenced_in_package(obj, path, index))
        brief = ", ".join(f"{item['check']}={item['status']}" for item in checks if item["counts"])
        print(f"{name}: counted [{brief}] overall={overall_status(checks)}")
        _require(_status(checks, "类别错标")["status"] == UNDECIDED, "missing-answer checks must stay 待判定")
        _require(_status(checks, "类别错标")["counts"] is False, "待判定 must not be scored")
        _require(_status(checks, "像素框")["counts"] is False, "absent pixel boxes are not a scored defect")

    epb = _load(samples["EPB"])
    epb_checks = json_consistency(epb, True)
    _require(_status(epb_checks, "event_count")["status"] == NA, "EPB has no event_count")
    dmsp_plain = _load(samples["DMSP_plain"])
    plain_checks = json_consistency(dmsp_plain, True)
    _require(_status(plain_checks, "无矩形")["counts"] is False, "missing rectangles are composition")
    _require("数据构成" in _status(plain_checks, "无矩形")["detail"], "plain DMSP should be marked composition")
    _require(_status(plain_checks, "qualityLevel")["status"] == NA, "qualityLevel is not a grade")

    declared_bad = _find("EPB_seg_sample_pb72bbq4bp", lambda obj, path: "512" in str(
        (obj.get("basic_annotation") or {}).get("imgSize") or ""
    ))
    _require(declared_bad is not None, "no EPB record declares 512")
    bad_checks = json_consistency(_load(declared_bad), True)
    _require(_status(bad_checks, "声明尺寸")["status"] == FAIL, "1024x512 declaration should fail")
    _require(_status(bad_checks, "像素越界")["status"] in {PASS, NA}, "declared-512 points still sit in the real frame")

    oov = _find("EPB_seg_sample_pb72bbq4bp", lambda obj, path: any(
        shape.get("label") == "__OOV__"
        for shape in ((obj.get("science_annotation") or {}).get("mask") or {}).get("shapes") or []
    ))
    _require(_status(json_consistency(_load(oov), True), "类别OOV")["status"] == FAIL, "OOV should fail")
    clean_oov = json_consistency(_load(samples["EPB"]), True)
    _require(_status(clean_oov, "类别OOV")["status"] == PASS, "clean EPB label should not be OOV")

    mismatch = _find("CME_C2_sample_di7yj9fvs2", lambda obj, path: (
        (obj.get("hek_event_annotation") or {}).get("event_count")
        != len((obj.get("hek_event_annotation") or {}).get("matched_events") or [])
    ))
    _require(mismatch is not None, "CME count mismatch not found")
    _require(_status(json_consistency(_load(mismatch), True), "event_count")["status"] == FAIL, "CME count mismatch")
    _require(_status(json_consistency(_load(samples["CME"]), True), "像素框")["status"] == NA, "CME boxes stay 不适用")
    print("declared size, OOV, CME count mismatch: ok")

    missing = _find("HMI_AR_sample_6toksh7wns", lambda obj, path: (
        file_name_of(obj) and (dataset_pair(path, obj) not in index)
    ))
    _require(missing is not None, "no missing HMI file in the degraded version")
    _require(_status(json_consistency(_load(missing), False), "引用文件")["status"] == FAIL, "missing file should fail")
    present = json_consistency(_load(samples["HMI"]), True)
    _require(_status(present, "引用文件")["status"] == PASS, "clean HMI file should be present in the manifest")
    print("file list: ok")


def dataset_pair(path: str, obj: dict) -> tuple[str, str]:
    from audits import dataset_name_of
    return dataset_name_of(path), file_name_of(obj)


def test_timestamps() -> None:
    print("\n== timestamps ==")
    for dataset, expected in (
        ("HMI_AR_sample_6yaatkycjv", PASS),
        ("AIA_AR_sample_mugm2urshy", REVIEW),
        ("DMSP_SSUSI_aaue04ws6s", REVIEW),
    ):
        times = [observation_time(_load(path)) for path in _jsons(dataset)]
        item = timestamp_review(times)
        _require(item["status"] == expected, f"{dataset} timestamp {item}")
        print(f"{dataset}: {item['status']} | {item['detail']}")


def test_waveform_numeric() -> dict[str, list[str]]:
    print("\n== waveform numeric ==")
    chosen = {"clean": [], "bad": []}
    for label, dataset, want_bad in (
        ("clean", "ULF_sample_lj7rg82ela", False),
        ("bad", "ULF_sample_pmsjn7a72e", True),
    ):
        for path in _jsons(dataset):
            obj = _load(path)
            events = (obj.get("ulf_event_annotation") or {}).get("matched_events") or []
            csv_path = os.path.join(ROOT, dataset, file_name_of(obj))
            if not events or not os.path.exists(csv_path):
                continue
            result = waveform_window(csv_path, obj)
            is_bad = result["rows"] != 3600
            if is_bad != want_bad:
                continue
            if not want_bad:
                _require(result["length_status"] == PASS, result)
            chosen[label].append(csv_path)
            print(
                f"{label}: rows={result['rows']} length={result['length_status']} "
                f"window={result['window_status']} | {os.path.basename(csv_path)}"
            )
            if len(chosen[label]) >= 2:
                break
        _require(len(chosen[label]) == 2, f"need 2 {label} waveform files, got {len(chosen[label])}")
    return chosen


def _paired_rings(dataset: str, limit: int) -> list[tuple[str, list]]:
    pairs = []
    root = os.path.join(ROOT, dataset)
    for dirpath, _, names in os.walk(root):
        for name in names:
            if not name.endswith(".png"):
                continue
            image_path = os.path.join(dirpath, name)
            json_path = _json_for_image(root, name)
            if json_path is None:
                continue
            rings = [ring["points"] for ring in pixel_rings(_load(json_path))]
            if not rings:
                continue
            pairs.append((image_path, rings, json_path))
            if len(pairs) >= limit:
                return pairs
    return pairs


def _json_for_image(dataset_dir: str, image_name: str) -> str | None:
    stem = image_name[:-4] if image_name.endswith(".png") else image_name
    for candidate in (
        os.path.join(dataset_dir, "label", image_name + ".json"),
        os.path.join(dataset_dir, image_name + ".json"),
        os.path.join(dataset_dir, stem + ".json"),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def test_spatial() -> dict[str, list[dict]]:
    print("\n== spatial precision ==")
    families = {
        "HMI": "HMI_AR_sample_6yaatkycjv",
        "AIA": "AIA_AR_sample_mugm2urshy",
        "DMSP": "DMSP_SSUSI_aaue04ws6s",
        "EPB": "EPB_seg_sample_84baza8n1b",
    }
    report = {}
    margins = []
    for name, dataset in families.items():
        pairs = _paired_rings(dataset, 4)
        _require(len(pairs) >= 2, f"{name} needs local images with contours, got {len(pairs)}")
        family = []
        for image_path, rings, json_path in pairs:
            positive = score_annotation(image_path, rings)
            longest = max(ImageSize(image_path))
            scale = 1.0 if longest <= MAX_SIDE else MAX_SIDE / longest
            dx, dy = positive["shift"]
            negative = score_annotation(image_path, shift_rings(rings, dx / scale, dy / scale))
            family.append({
                "image": image_path,
                "json": json_path,
                "rings": rings,
                "positive": positive,
                "negative_edge": negative["edge_fraction"],
            })
            margins.append(positive["margin"])
            print(
                f"{name} {os.path.basename(image_path)}: "
                f"edge {positive['edge_fraction']:.3f} shifted {positive['shifted_edge_fraction']:.3f} "
                f"margin {positive['margin']:.3f} negative_edge {negative['edge_fraction']:.3f}"
            )
        pos_mid = _median([item["positive"]["edge_fraction"] for item in family])
        neg_mid = _median([item["negative_edge"] for item in family])
        _require(pos_mid > neg_mid, f"{name} contour does not beat a shifted contour ({pos_mid:.3f} vs {neg_mid:.3f})")
        report[name] = family
    threshold = calibrate_threshold(margins)
    with open(THRESHOLD_PATH, "w", encoding="utf-8") as handle:
        json.dump({"threshold": threshold, "n": len(margins)}, handle)
    print(f"threshold from positive margins only: {threshold:.3f} on {len(margins)} samples")
    return report


def ImageSize(path: str) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as image:
        return image.size


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def test_graph(samples: dict[str, str], waveform_files: dict[str, list[str]]) -> None:
    print("\n== langgraph ==")
    cme = invoke_one(samples["CME"])
    _require(cme["trace"] == ["load", "classify", "json_rules", "explain", "no_vision", "merge", "score"], cme["trace"])
    _require(cme["score"]["quality"] is not None, cme["score"])
    _require(cme["branch"] == "无", cme["branch"])
    _require(cme["kind"] == "event_catalog", cme["kind"])
    _require(cme["vision_text"] == "", "CME should not call vision")
    print(f"CME overall={cme['overall']} branch={cme['branch']}")

    boxed = invoke_one(samples["HMI"])
    _require(boxed["branch"] == "明暗图", boxed["branch"])
    _require("spatial" in boxed["trace"], boxed["trace"])
    print(f"HMI overall={boxed['overall']} branch={boxed['branch']}")

    plain = invoke_one(samples["DMSP_plain"])
    _require(plain["branch"] == "无", "DMSP without a rectangle skips vision")

    clean_csv = waveform_files["clean"][0]
    ulf_json = clean_csv + ".json" if clean_csv.endswith(".csv") else clean_csv
    if not os.path.exists(ulf_json):
        ulf_json = os.path.splitext(clean_csv)[0] + ".csv.json"
    ulf = invoke_one(ulf_json)
    _require(ulf["branch"] == "波形", ulf["branch"])
    _require(_status(ulf["checks"], "波形行数")["status"] == PASS, "clean waveform length")
    print(f"ULF overall={ulf['overall']} rows={ulf['waveform']['rows']}")

    oov = _find("EPB_seg_sample_pb72bbq4bp", lambda obj, path: any(
        shape.get("label") == "__OOV__"
        for shape in ((obj.get("science_annotation") or {}).get("mask") or {}).get("shapes") or []
    ))
    failed = invoke_one(oov)
    _require(failed["overall"] == FAIL, "OOV must stay 不通过")
    kept = merge_node({
        "checks": [{"check": "类别OOV", "status": FAIL, "detail": "", "counts": True}],
        "vision_text": "是，轮廓贴边",
        "trace": [],
    })
    _require(kept["overall"] == GRAPH_FAIL, "a yes from vision must not clear a JSON failure")
    print(f"OOV EPB overall={failed['overall']}")


def _csv_json(csv_path: str) -> str:
    direct = csv_path + ".json"
    if os.path.exists(direct):
        return direct
    return os.path.splitext(csv_path)[0] + ".csv.json"


def test_vision(spatial_report: dict[str, list[dict]], waveform_files: dict[str, list[str]]) -> None:
    print("\n== vision ==")
    os.makedirs(OUT, exist_ok=True)
    secrets = load_secrets()
    from spatial_precision import near_threshold
    threshold = json.load(open(THRESHOLD_PATH, encoding="utf-8"))["threshold"]
    shown = 0
    for name, family in spatial_report.items():
        ranked = sorted(family, key=lambda item: abs(item["positive"]["margin"] - threshold))
        sent = 0
        for item in ranked:
            if not near_threshold(item["positive"]["margin"], threshold):
                continue
            if sent >= 2:
                break
            obj = _load(item["json"])
            labels = [ring["label"] for ring in pixel_rings(obj)]
            text = judge_spatial(item["image"], item["rings"], labels, secrets)
            print(f"spatial {name} {os.path.basename(item['image'])}: {text}")
            _require(text.strip() and not text.startswith("调用失败"), text)
            sent += 1
            shown += 1
        if sent == 0:
            print(f"spatial {name}: no sample near the threshold")
    _require(shown > 0, "no spatial sample was close enough to call vision")

    aia_path = next(_jsons("AIA_AR_sample_mugm2urshy"))
    explained = invoke_one(aia_path, use_text=True, time_count=8)
    _require(_status(explained["checks"], "时刻重复")["status"] == REVIEW, "shared time stays 待复核")
    _require(explained["text_note"] and not explained["text_note"].startswith("调用失败"), explained["text_note"])
    print("text note:", explained["text_note"].replace("\n", " "))

    for label, paths in waveform_files.items():
        for csv_path in paths:
            json_path = _csv_json(csv_path)
            record = invoke_one(json_path, use_vision=True)
            print(
                f"waveform {label} {os.path.basename(csv_path)}: "
                f"overall={record['overall']} standard={record['vision_standard']}"
            )
            print(" ", record["vision_text"].replace("\n", " "))
            _require(record["branch"] == "波形", record["branch"])
            _require(record["vision_standard"] == "时间窗对准峰谷", record["vision_standard"])
            _require("调用失败" not in record["vision_text"], record["vision_text"])
            if label == "bad":
                _require(record["overall"] == FAIL, "a bad row count must stay 不通过")
                _require("补充" in record["vision_text"], record["vision_text"])
            png = render_waveform(csv_path, _load(json_path))
            with open(os.path.join(OUT, os.path.basename(csv_path) + ".png"), "wb") as handle:
                handle.write(png)


def main() -> None:
    samples = test_router()
    test_json_rules(samples)
    test_timestamps()
    waveform_files = test_waveform_numeric()
    spatial_report = test_spatial()
    test_graph(samples, waveform_files)
    if "--no-vision" not in sys.argv:
        test_vision(spatial_report, waveform_files)
    print("\nmodule tests passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print("FAILED:", exc)
        sys.exit(1)
