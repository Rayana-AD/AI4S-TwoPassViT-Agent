"""Two visual standards. Spatial crops ask about the contour. Waveform plots ask about the time window."""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import urllib.error
import urllib.request

import yaml
from PIL import Image, ImageDraw

from audits import window_spans

SPATIAL_STANDARD = "轮廓贴住结构"
WAVEFORM_STANDARD = "时间窗对准峰谷"


def secrets_path() -> str | None:
    """Environment wins, then the working directory, then the project directory. No key is stored in code."""
    named = os.environ.get("SECRETS_PATH") or os.environ.get("MODEL_SECRETS")
    candidates = [
        named,
        os.path.join(os.getcwd(), "secrets.yaml"),
        os.path.join(os.path.dirname(__file__), "secrets.yaml"),
        os.path.join(os.path.dirname(__file__), "..", "secrets.yaml"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def load_secrets(path: str | None = None) -> dict:
    chosen = path or secrets_path()
    if not chosen:
        return {}
    with open(chosen, encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return loaded if isinstance(loaded, dict) else {}


def _pick(secrets: dict, env_name: str, *keys: str) -> str:
    if os.environ.get(env_name):
        return os.environ[env_name]
    for key in keys:
        value = secrets.get(key)
        if value:
            return str(value)
    return ""


def model_endpoint(secrets: dict | None = None) -> dict:
    """OpenAI-compatible chat endpoint. The organizer can replace the model without changing calls.

    Environment, in this order, overrides the yaml file:
    MODEL_BASE_URL, MODEL_API_KEY, MODEL_NAME.
    MODEL_TEXT_NAME and MODEL_VISION_NAME are optional. If omitted, both roles use MODEL_NAME.
    """
    secrets = load_secrets() if secrets is None else secrets
    base = _pick(secrets, "MODEL_BASE_URL", "model_base_url").rstrip("/")
    if not base:
        base = "https://api.openai.com/v1"
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    shared = _pick(secrets, "MODEL_NAME", "model_name")
    return {
        "url": url,
        "key": _pick(secrets, "MODEL_API_KEY", "model_api_key", "deepseek_api_key", "openrouter_api_key"),
        "text": _pick(secrets, "MODEL_TEXT_NAME", "model_text_name") or shared,
        "vision": _pick(secrets, "MODEL_VISION_NAME", "model_vision_name") or shared,
    }


def chat_with_usage(content, role: str, secrets: dict | None = None, timeout: int = 120, max_tokens: int = 200) -> dict:
    """One OpenAI-compatible call. Returns text plus token usage. Does not print the key."""
    endpoint = model_endpoint(secrets)
    model = endpoint["vision"] if role == "vision" else endpoint["text"]
    if not endpoint["key"] or not model:
        return {
            "text": "未配置模型接口。设置 MODEL_BASE_URL、MODEL_API_KEY、MODEL_NAME 后再调用。规则分数不受影响。",
            "model": model,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }
    if os.environ.get("MODEL_DISABLE_THINKING") == "1":
        payload["thinking"] = {"type": "disabled"}
    request = urllib.request.Request(
        endpoint["url"],
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {endpoint['key']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return {"text": f"调用失败 HTTP {exc.code} {detail}", "model": model, "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
    message = body["choices"][0]["message"]
    text = (message.get("content") or "").strip() or (message.get("reasoning_content") or "").strip()
    usage = body.get("usage") or {}
    return {
        "text": text,
        "model": body.get("model") or model,
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }


def _chat(content, role: str, secrets: dict | None = None, timeout: int = 90) -> str:
    return chat_with_usage(content, role, secrets, timeout=timeout)["text"]


def batch_vision(items: list[dict], standard: str, secrets: dict | None = None) -> dict:
    """One request, several images. items: id, png bytes, note."""
    intro = (
        f"下面有 {len(items)} 张图，请逐张判断。标准：{standard}。"
        "不要根据整张图亮不亮下结论。"
        "只输出一个 JSON 数组，不要其他文字。每项为 "
        '{"id":"图的id","verdict":"是或否","reason":"一句理由"}。'
    )
    content = [{"type": "text", "text": intro}]
    for item in items:
        content.append({"type": "text", "text": f"id={item['id']}。{item.get('note', '')}"})
        encoded = base64.b64encode(item["png"]).decode()
        content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}})
    result = chat_with_usage(content, "vision", secrets, timeout=180, max_tokens=800)
    bound = bind_reply(result["text"], [item["id"] for item in items])
    result["items"] = [
        {"id": item["id"], **bound[item["id"]]} for item in items
    ]
    result["bind"] = bound
    return result


def _parse_batch(text: str, ids: list[str]) -> list[dict]:
    """Keep model items only. Callers must bind them with bind_reply, never by list position."""
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    return []


def bind_reply(text: str, expected_ids: list[str]) -> dict[str, dict]:
    """Map a batch answer onto the ids that were actually sent.

    A verdict is kept only when the model returns that exact id.
    A missing id stays unbound. An unexpected id is recorded and not
    given to another file. Order in the JSON array is never used.
    """
    parsed = _parse_batch(text, expected_ids)
    expected = set(expected_ids)
    bound: dict[str, dict] = {}
    extra: list[str] = []
    for item in parsed:
        item_id = str(item.get("id") or "")
        if item_id in expected and item_id not in bound:
            bound[item_id] = {
                "verdict": str(item.get("verdict") or ""),
                "reason": str(item.get("reason") or ""),
                "bind": "matched",
            }
        elif item_id:
            extra.append(item_id)
    for item_id in expected_ids:
        if item_id not in bound:
            bound[item_id] = {
                "verdict": "",
                "reason": "",
                "bind": "missing_in_reply",
                "extra_ids": extra,
            }
    return bound


def crop_raw(image_path: str, bbox: dict[str, float] | None = None, pad: int = 48, max_side: int = 512) -> tuple[bytes, dict[str, int]]:
    """Crop without drawing annotations. Returns PNG bytes and crop_origin metadata in full-image pixels."""
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    if bbox:
        left = max(0, int(bbox["xmin"] - pad))
        top = max(0, int(bbox["ymin"] - pad))
        right = min(width, int(bbox["xmax"] + pad))
        bottom = min(height, int(bbox["ymax"] + pad))
    else:
        left, top, right, bottom = 0, 0, width, height
    if right <= left or bottom <= top:
        left, top, right, bottom = 0, 0, width, height
    crop = image.crop((left, top, right, bottom))
    crop_w, crop_h = crop.size
    longest = max(crop.size)
    if longest > max_side:
        ratio = max_side / longest
        crop = crop.resize((max(1, int(crop.size[0] * ratio)), max(1, int(crop.size[1] * ratio))), Image.BILINEAR)
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    origin = {
        "x0": left,
        "y0": top,
        "width": right - left,
        "height": bottom - top,
        "full_width": width,
        "full_height": height,
        "display_width": crop.size[0],
        "display_height": crop.size[1],
        "coordinate_system": "polygon_pixel in full image; if you read coords on the PNG, map via display_width/height to full_width/full_height then add x0,y0",
    }
    return buffer.getvalue(), origin


def crop_with_contour(image_path: str, rings: list[list[tuple[float, float]]], pad: int = 24) -> bytes:
    """Crop around the annotation and draw the contour. The model sees the line, not a bare coordinate."""
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    xs = [point[0] for ring in rings for point in ring]
    ys = [point[1] for ring in rings for point in ring]
    left = max(0, int(min(xs) - pad))
    top = max(0, int(min(ys) - pad))
    right = min(width, int(max(xs) + pad))
    bottom = min(height, int(max(ys) + pad))
    if right <= left or bottom <= top:
        left, top, right, bottom = 0, 0, width, height
    crop = image.crop((left, top, right, bottom))
    draw = ImageDraw.Draw(crop)
    for ring in rings:
        local = [(point[0] - left, point[1] - top) for point in ring]
        if len(local) >= 2:
            closed = local + [local[0]]
            draw.line(closed, fill=(255, 32, 32), width=2)
    longest = max(crop.size)
    if longest > 512:
        scale = 512 / longest
        crop = crop.resize((max(1, int(crop.size[0] * scale)), max(1, int(crop.size[1] * scale))), Image.BILINEAR)
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    return buffer.getvalue()


def _series(rows: list[dict], column: str) -> list[float] | None:
    if not rows or column not in rows[0]:
        return None
    try:
        return [float(row[column]) for row in rows]
    except (TypeError, ValueError):
        return None


def _polyline(values: list[float], left: int, top: int, width: int, height: int) -> list[tuple[int, int]]:
    low = min(values)
    high = max(values)
    span = high - low or 1.0
    last = max(1, len(values) - 1)
    points = []
    for index, value in enumerate(values):
        x = left + int(index / last * (width - 1))
        y = top + int((1 - (value - low) / span) * (height - 1))
        points.append((x, y))
    return points


def render_waveform(csv_path: str, obj: dict, *, draw_windows: bool = True) -> bytes:
    """H, and D/Z when present. Red window lines only when draw_windows is True."""
    with open(csv_path, newline="") as handle:
        rows = list(csv.DictReader(handle))
    width, height = 900, 320
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    left, top, plot_w, plot_h = 40, 24, 840, 250
    draw.rectangle((left, top, left + plot_w, top + plot_h), outline=(180, 180, 180))
    colors = (("H", (20, 20, 20)), ("D", (40, 90, 180)), ("Z", (30, 140, 70)))
    for column, color in colors:
        values = _series(rows, column)
        if not values:
            continue
        draw.line(_polyline(values, left, top, plot_w, plot_h), fill=color, width=1)
    if draw_windows:
        spans = window_spans(obj, len(rows))
        last = max(1, len(rows) - 1)
        for span in spans:
            if span.get("i0") is None:
                continue
            for index in (span["i0"], span["i1"]):
                x = left + int(index / last * (plot_w - 1))
                draw.line((x, top, x, top + plot_h), fill=(200, 30, 30), width=1)
        draw.text((40, 286), "H black   D blue   Z green   red lines = labeled window", fill=(40, 40, 40))
    else:
        draw.text((40, 286), "H black   D blue   Z green   (no annotation overlay)", fill=(40, 40, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _image_content(text: str, png: bytes) -> list:
    encoded = base64.b64encode(png).decode()
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}},
    ]


def judge_spatial(image_path: str, rings: list[list[tuple[float, float]]], labels: list[str], secrets: dict) -> str:
    label_text = "、".join(label for label in labels if label) or "无"
    question = (
        "红线是标注轮廓。只判断轮廓是否贴住结构边界。"
        "不要根据整张图亮不亮下结论。"
        f"JSON 里的类别是：{label_text}。如果图上有可读文字，用半句说明它和这个类别是否一致。"
        "回答先写是或否，再写一句理由。"
    )
    png = crop_with_contour(image_path, rings)
    return _chat(_image_content(question, png), "vision", secrets)


def judge_waveform(csv_path: str, obj: dict, secrets: dict) -> str:
    question = (
        "曲线是地磁 H，蓝线和绿线是 D、Z（各自缩放到图内）。红色竖线是标注时间窗。"
        "只判断时间窗是否对准峰、谷或时间轴上的事件。"
        "不要根据图面明暗下结论，也不要按空间框是否贴边来判断。"
        "回答先写是或否，再写一句理由。"
    )
    png = render_waveform(csv_path, obj)
    return _chat(_image_content(question, png), "vision", secrets)


def explain_pending(checks: list[dict], secrets: dict) -> str:
    """Explain 待复核 items. The model must not recompute file or event_count checks."""
    pending = [
        {"check": item["check"], "status": item["status"], "detail": item["detail"]}
        for item in checks
        if item.get("counts") and item.get("status") == "待复核"
    ]
    if not pending:
        return ""
    question = (
        "下面这些检查已经由规则标成待复核。请用一句话说明人工该看什么。"
        "不要改判，不要重新计算缺文件或 event_count。"
        "共用观测时刻只表示待复核，不要写成已经确认的重复样本。\n"
        + json.dumps(pending, ensure_ascii=False)
    )
    return _chat(question, "text", secrets)
