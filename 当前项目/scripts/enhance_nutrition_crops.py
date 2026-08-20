from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
import requests
from PIL import Image, ImageFilter, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import local_service as service  # noqa: E402


PARSER_VERSION = "nutrition-classic-general-v9"
TARGET_WIDTH = 2000
BAND_GAP = 100
MIN_ACCEPT_SCORE = 0.20

# The source rectangles may overlap slightly to tolerate scan drift. Their output
# bands never overlap, and each answer is selected only from its field-specific ROI.
CROP_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "first_page_header",
        "kind": "identity",
        "source_index": 0,
        "relative_box": (0.04, 0.025, 0.99, 0.120),
    },
    {
        "id": "daily_meals",
        "kind": "numeric",
        "field": "每日餐次",
        "source_index": 0,
        "relative_box": (0.10, 0.135, 0.70, 0.225),
        "answer_roi": (0.45, 0.18, 0.76, 0.82),
        "maximum": 10.0,
    },
    {
        "id": "home_meal_days",
        "kind": "numeric",
        "field": "每周在家吃饭天数",
        "source_index": 0,
        "relative_box": (0.10, 0.180, 0.75, 0.255),
        "answer_roi": (0.45, 0.30, 0.76, 0.96),
        "maximum": 7.0,
    },
    {
        "id": "sunlight_days",
        "kind": "numeric",
        "field": "每周户外日照天数",
        "source_index": 2,
        "relative_box": (0.10, 0.130, 0.75, 0.215),
        "answer_roi": (0.25, 0.18, 0.50, 0.88),
        "maximum": 7.0,
    },
    {
        "id": "sunlight_hours",
        "kind": "numeric",
        "field": "每日户外日照时长(小时)",
        "source_index": 2,
        "relative_box": (0.10, 0.170, 0.80, 0.245),
        "answer_roi": (0.50, 0.18, 0.78, 0.90),
        "maximum": 12.0,
    },
)

ANSWER_TOKEN = (
    r"(?:无|[0-9Oo〇○Il|CcDd一工丁士]+(?:[.,，．][0-9]+)?"
    r"(?:\s*[-~～至]\s*[0-9Oo〇○Il|]+(?:[.,，．][0-9]+)?)?)"
)
NUMERIC_PROMPTS = {
    "每日餐次": re.compile(rf"每天吃几餐[ \t]*[？?]?[ \t_＿—:：-]*({ANSWER_TOKEN})", re.I),
    "每周在家吃饭天数": re.compile(rf"每周在家吃几天饭[ \t]*[？?]?[ \t_＿—:：-]*({ANSWER_TOKEN})", re.I),
    "每周户外日照天数": re.compile(rf"每周有[ \t_＿—:：-]*({ANSWER_TOKEN})[ \t]*天", re.I),
    "每日户外日照时长(小时)": re.compile(rf"日照时长(?:是)?[ \t_＿—:：-]*({ANSWER_TOKEN})[ \t]*小时", re.I),
}


def render_first_page(pdf_path: Path, zoom: float = 3.0) -> Image.Image:
    with fitz.open(pdf_path) as document:
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def relative_crop(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = box
    return image.crop((int(width * left), int(height * top), int(width * right), int(height * bottom)))


def ordered_source_pdfs(job_dir: Path, person_id: str) -> list[Path]:
    excel_dir = job_dir / "ocr_excel" / Path(person_id)
    input_dir = job_dir / "input" / "reports" / Path(person_id)
    pdf_by_stem = {path.stem: path for path in input_dir.glob("*.pdf")}
    result = []
    for excel_path in sorted(excel_dir.glob("*.xlsx")):
        source_stem = re.sub(r"^\d+_", "", excel_path.stem)
        source_stem = re.sub(r"_ocr$", "", source_stem)
        source_path = pdf_by_stem.get(source_stem)
        if source_path:
            result.append(source_path)
    if not result:
        result = sorted(input_dir.glob("*.pdf"))
    return result


def stack_bands(
    images: dict[int, Image.Image],
    sources: list[Path],
    *,
    target_width: int = TARGET_WIDTH,
    gap: int = BAND_GAP,
) -> tuple[Image.Image, list[dict[str, Any]]]:
    prepared: list[tuple[Image.Image, dict[str, Any], str]] = []
    for spec in CROP_SPECS:
        source_index = int(spec["source_index"])
        crop = relative_crop(images[source_index], tuple(spec["relative_box"]))
        scale = target_width / crop.width
        resized = crop.resize((target_width, max(1, round(crop.height * scale))), Image.Resampling.LANCZOS)
        original = ImageOps.autocontrast(resized)
        prepared.append((original, spec, "original"))
        if spec["kind"] == "numeric":
            grayscale = ImageOps.autocontrast(ImageOps.grayscale(original))
            sharpened = grayscale.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=3))
            thresholded = sharpened.point(lambda pixel: 0 if pixel < 210 else 255).convert("RGB")
            prepared.append((thresholded, spec, "threshold"))

    height = sum(image.height for image, _, _ in prepared) + gap * (len(prepared) - 1)
    canvas = Image.new("RGB", (target_width, height), "white")
    bands: list[dict[str, Any]] = []
    y = 0
    for image, spec, variant in prepared:
        canvas.paste(image, (0, y))
        source_index = int(spec["source_index"])
        band = {
            "id": f"{spec['id']}_{variant}" if spec["kind"] == "numeric" else spec["id"],
            "base_id": spec["id"],
            "variant": variant,
            "kind": spec["kind"],
            "field": spec.get("field", ""),
            "source_page_index": source_index + 1,
            "source_pdf": str(sources[source_index].resolve()),
            "relative_box": list(spec["relative_box"]),
            "answer_roi": list(spec.get("answer_roi", (0.0, 0.0, 1.0, 1.0))),
            "maximum": spec.get("maximum"),
            "x_start": 0,
            "x_end": target_width,
            "y_start": y,
            "y_end": y + image.height,
            "width": image.width,
            "height": image.height,
        }
        bands.append(band)
        y += image.height + gap
    return canvas, bands


def build_general_crop(job_dir: Path, person_id: str) -> tuple[Image.Image, list[Path], list[dict[str, Any]]]:
    pdfs = ordered_source_pdfs(job_dir, person_id)
    if len(pdfs) < 3:
        raise RuntimeError(f"{person_id} expected at least 3 questionnaire pages, found {len(pdfs)}")
    images = {0: render_first_page(pdfs[0]), 2: render_first_page(pdfs[2])}
    composite, bands = stack_bands(images, pdfs)
    return composite, [pdfs[0], pdfs[2]], bands


def parse_people(values: list[str] | None, job_dir: Path) -> list[str]:
    if values:
        result = []
        for value in values:
            for item in value.split(","):
                item = item.strip().replace("\\", "/")
                if item:
                    result.append(item if "/" in item else f"ocr/{item}")
        return list(dict.fromkeys(result))
    root = job_dir / "ocr_excel"
    people = [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir() and any(path.glob("*.xlsx"))]
    return sorted(people, key=person_sort_key)


def person_sort_key(person_id: str) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", person_id))


def normalized_box(raw_box: object) -> list[float]:
    if not isinstance(raw_box, (list, tuple)):
        return []
    if len(raw_box) >= 4 and all(isinstance(value, (int, float)) for value in raw_box[:4]):
        x1, y1, x2, y2 = (float(value) for value in raw_box[:4])
        return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
    points = [point for point in raw_box if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return []
    try:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    except (TypeError, ValueError):
        return []
    return [min(xs), min(ys), max(xs), max(ys)]


def map_items_to_bands(items: list[object], bands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            continue
        box = normalized_box(raw_item.get("box"))
        if not box:
            continue
        x1, y1, x2, y2 = box
        box_height = max(1.0, y2 - y1)
        best_band: dict[str, Any] | None = None
        best_overlap = 0.0
        for band in bands:
            overlap = max(0.0, min(y2, float(band["y_end"])) - max(y1, float(band["y_start"])))
            if overlap > best_overlap:
                best_overlap = overlap
                best_band = band
        if best_band is None or best_overlap / box_height < 0.20:
            continue
        local_box = [x1, y1 - best_band["y_start"], x2, y2 - best_band["y_start"]]
        mapped.append(
            {
                "index": index,
                "text": str(raw_item.get("text") or "").strip(),
                "score": float(raw_item.get("score") or 0.0),
                "box": box,
                "band_id": best_band["id"],
                "field": best_band.get("field", ""),
                "vertical_overlap_ratio": round(best_overlap / box_height, 4),
                "local_box": local_box,
                "local_center_ratio": [
                    round(((x1 + x2) / 2) / max(1, best_band["width"]), 4),
                    round((((y1 + y2) / 2) - best_band["y_start"]) / max(1, best_band["height"]), 4),
                ],
            }
        )
    return mapped


def normalize_numeric_token(raw: object, field: str = "") -> str:
    text = str(raw or "").strip()
    if text == "无":
        return "0"
    text = re.sub(r"[ \t餐饭天小时次_＿—]+", "", text)
    text = text.replace("，", ".").replace("．", ".").replace(",", ".")
    text = text.replace("～", "-").replace("~", "-").replace("至", "-")
    text = text.replace("O", "0").replace("o", "0").replace("〇", "0").replace("○", "0")
    text = text.replace("I", "1").replace("l", "1").replace("|", "1")
    text = text.replace("一", "1")
    if field == "每周在家吃饭天数":
        text = text.replace("C", "0").replace("c", "0").replace("D", "0").replace("d", "0")
    if field == "每日户外日照时长(小时)":
        text = text.replace("C", "0").replace("c", "0").replace("D", "0").replace("d", "0")
    if field == "每周户外日照天数":
        # A lightly written 7 is repeatedly classified as 工/丁 after binarization.
        # This substitution is allowed only inside the fixed answer slot for this field.
        text = text.replace("工", "7").replace("丁", "7").replace("士", "7")
    text = text.strip(".。；;，,：:？?()（）[]【】")
    if field == "每日户外日照时长(小时)" and re.fullmatch(r"\d{2}", text):
        # Decimal points written on the underline are frequently dropped: 05/15/25
        # are the recurring OCR forms of 0.5/1.5/2.5 in this fixed answer slot.
        if text.startswith("0") or int(text) > 12:
            text = f"{text[0]}.{text[1]}"
    if not re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?", text):
        return ""
    parts = text.split("-")
    normalized_parts = []
    for part in parts:
        number = float(part)
        normalized_parts.append(str(int(number)) if number.is_integer() else f"{number:g}")
    return "-".join(normalized_parts)


def numeric_in_range(value: str, maximum: float) -> bool:
    numbers = [float(item) for item in value.split("-") if item]
    return bool(numbers) and all(0 <= number <= maximum for number in numbers)


def candidate_record(value: str, raw: str, score: float, source: str, box: list[float] | None = None) -> dict[str, Any]:
    return {
        "value": value,
        "raw": raw,
        "score": round(float(score), 6),
        "source": source,
        "box": box or [],
    }


def deduplicate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[float, ...]]] = set()
    for candidate in candidates:
        key = (candidate["value"], candidate["source"], tuple(candidate.get("box") or []))
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def numeric_field_review(
    field: str,
    bands: list[dict[str, Any]],
    mapped_items: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    invalid_candidates: list[dict[str, Any]] = []
    prompt = NUMERIC_PROMPTS[field]
    raw_text_blocks: list[str] = []
    for band in bands:
        band_items = [item for item in mapped_items if item["band_id"] == band["id"]]
        maximum = float(band["maximum"])
        source_prefix = str(band.get("variant") or "original")

        for item in band_items:
            for match in prompt.finditer(item["text"]):
                value = normalize_numeric_token(match.group(1), field)
                if value:
                    target = candidates if numeric_in_range(value, maximum) else invalid_candidates
                    target.append(candidate_record(value, match.group(1), item["score"], f"{source_prefix}:prompt_item", item["box"]))

        joined_text = "\n".join(item["text"] for item in band_items if item["text"])
        raw_text_blocks.append(f"[{source_prefix}]\n{joined_text}")
        joined_score = max((item["score"] for item in band_items), default=0.0)
        for match in prompt.finditer(joined_text):
            value = normalize_numeric_token(match.group(1), field)
            if value:
                target = candidates if numeric_in_range(value, maximum) else invalid_candidates
                target.append(candidate_record(value, match.group(1), joined_score, f"{source_prefix}:prompt_joined"))

        roi_x1, roi_y1, roi_x2, roi_y2 = band["answer_roi"]
        for item in band_items:
            center_x, center_y = item["local_center_ratio"]
            if not (roi_x1 <= center_x <= roi_x2 and roi_y1 <= center_y <= roi_y2):
                continue
            value = normalize_numeric_token(item["text"], field)
            if value:
                target = candidates if numeric_in_range(value, maximum) else invalid_candidates
                target.append(candidate_record(value, item["text"], item["score"], f"{source_prefix}:answer_roi", item["box"]))

    candidates = deduplicate_candidates(candidates)
    invalid_candidates = deduplicate_candidates(invalid_candidates)
    values = sorted({candidate["value"] for candidate in candidates})
    best_score = max((candidate["score"] for candidate in candidates), default=0.0)
    variant_support = {
        value: {
            str(candidate.get("source") or "").split(":", 1)[0]
            for candidate in candidates
            if candidate["value"] == value
        }
        for value in values
    }
    cross_variant_values = [value for value, sources in variant_support.items() if {"original", "threshold"} <= sources]
    if invalid_candidates:
        status, selected = "invalid", ""
    elif len(values) > 1 and len(cross_variant_values) == 1:
        status, selected = "accepted", cross_variant_values[0]
    elif len(values) > 1:
        status, selected = "conflict", ""
    elif not values:
        status, selected = "missing", ""
    elif best_score < MIN_ACCEPT_SCORE:
        status, selected = "low_confidence", ""
    else:
        status, selected = "accepted", values[0]
    return {
        "field": field,
        "status": status,
        "selected": selected,
        "best_score": round(best_score, 6),
        "candidates": candidates,
        "invalid_candidates": invalid_candidates,
        "raw_text": "\n\n".join(raw_text_blocks),
    }


def normalize_date(raw: object) -> str:
    text = re.sub(r"\s+", "", str(raw or ""))
    text = text.replace("年", ".").replace("月", ".").replace("日", "")
    text = text.replace("/", ".").replace("-", ".").replace("，", ".").replace(",", ".")
    match = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", text)
    if not match:
        return ""
    year, month, day = (int(part) for part in match.groups())
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year}.{month}.{day}"


def normalize_identity_value(field: str, raw: object) -> str:
    text = re.sub(r"\s+", "", str(raw or "")).strip("_＿—-：:，,；;。")
    if field == "姓名":
        return service.valid_person_name(text)
    if field == "调查日期":
        return normalize_date(text)
    if field == "受试者编号":
        return text if re.fullmatch(r"[A-Za-z0-9-]{5,32}", text) and any(character.isdigit() for character in text) else ""
    if field == "访视号":
        return text if re.fullmatch(r"[A-Za-z0-9-]{1,20}", text) else ""
    return ""


def identity_field_review(
    field: str,
    header_band: dict[str, Any],
    header_items: list[dict[str, Any]],
) -> dict[str, Any]:
    patterns = {
        "受试者编号": re.compile(r"受试者编号\s*[：:]?\s*([A-Za-z0-9-]{5,32})(?=\s|受试者|姓名|调查|访视|$)", re.I),
        "姓名": re.compile(
            r"受试者姓名\s*[：:]?\s*([\u3400-\u9fff·]{2,8}?)(?=\s*[，,、；;。|]?\s*(?:调查日期|访视号|受试者编号|$))"
        ),
        "调查日期": re.compile(r"调查日期\s*[：:]?\s*(\d{4}\s*[./年-]\s*\d{1,2}\s*[./月-]\s*\d{1,2}\s*日?)"),
        "访视号": re.compile(r"访视号\s*[：:]?\s*([A-Za-z0-9-]{1,20})(?=\s|$)", re.I),
    }
    zones = {
        "受试者编号": (0.12, 0.00, 0.39, 0.84),
        "姓名": (0.35, 0.00, 0.63, 0.84),
        "调查日期": (0.59, 0.00, 0.87, 0.84),
        "访视号": (0.83, 0.00, 1.00, 0.84),
    }
    candidates: list[dict[str, Any]] = []
    pattern = patterns[field]
    for item in header_items:
        for match in pattern.finditer(item["text"]):
            value = normalize_identity_value(field, match.group(1))
            if value:
                candidates.append(candidate_record(value, match.group(1), item["score"], "label_item", item["box"]))

    joined_text = "\n".join(item["text"] for item in header_items if item["text"])
    joined_score = max((item["score"] for item in header_items), default=0.0)
    for match in pattern.finditer(joined_text):
        value = normalize_identity_value(field, match.group(1))
        if value:
            candidates.append(candidate_record(value, match.group(1), joined_score, "label_joined"))

    zone_x1, zone_y1, zone_x2, zone_y2 = zones[field]
    for item in header_items:
        center_x, center_y = item["local_center_ratio"]
        if not (zone_x1 <= center_x <= zone_x2 and zone_y1 <= center_y <= zone_y2):
            continue
        value = normalize_identity_value(field, item["text"])
        if value:
            candidates.append(candidate_record(value, item["text"], item["score"], "header_roi", item["box"]))

    candidates = deduplicate_candidates(candidates)
    values = sorted({candidate["value"] for candidate in candidates})
    best_score = max((candidate["score"] for candidate in candidates), default=0.0)
    if len(values) > 1:
        status, selected = "conflict", ""
    elif not values:
        status, selected = "missing", ""
    elif best_score < MIN_ACCEPT_SCORE:
        status, selected = "low_confidence", ""
    else:
        status, selected = "accepted", values[0]
    return {
        "field": field,
        "status": status,
        "selected": selected,
        "best_score": round(best_score, 6),
        "candidates": candidates,
        "raw_text": joined_text,
        "source_page_index": 1,
    }


def parse_classic_response(data: dict[str, Any], bands: list[dict[str, Any]]) -> dict[str, Any]:
    raw_items = data.get("items") or []
    mapped_items = map_items_to_bands(raw_items if isinstance(raw_items, list) else [], bands)
    band_by_id = {band["id"]: band for band in bands}
    header_band = band_by_id["first_page_header"]
    header_items = [item for item in mapped_items if item["band_id"] == header_band["id"]]
    reviews: dict[str, dict[str, Any]] = {}
    for field in ("受试者编号", "姓名", "调查日期", "访视号"):
        reviews[field] = identity_field_review(field, header_band, header_items)
    for field in ("每日餐次", "每周在家吃饭天数", "每周户外日照天数", "每日户外日照时长(小时)"):
        field_bands = [band for band in bands if band.get("field") == field]
        if field == "每日户外日照时长(小时)":
            # On slightly shifted scans the hour answer is detected at the bottom of
            # the preceding sunlight-days crop even when the dedicated crop misses it.
            for source_band in bands:
                if source_band.get("base_id") != "sunlight_days":
                    continue
                fallback = dict(source_band)
                fallback["field"] = field
                fallback["maximum"] = 12.0
                fallback["answer_roi"] = [0.55, 0.75, 0.82, 1.0]
                field_bands.append(fallback)
        reviews[field] = numeric_field_review(field, field_bands, mapped_items)
    return refresh_structured_summary({"field_reviews": reviews, "mapped_items": mapped_items})


def refresh_structured_summary(structured: dict[str, Any]) -> dict[str, Any]:
    reviews = structured.get("field_reviews") or {}
    structured["general_fields"] = {
        field: review["selected"]
        for field, review in reviews.items()
        if review.get("status") == "accepted" and review.get("selected") != ""
    }
    structured["conflict_fields"] = [field for field, review in reviews.items() if review.get("status") == "conflict"]
    structured["low_confidence_fields"] = [field for field, review in reviews.items() if review.get("status") == "low_confidence"]
    structured["invalid_fields"] = [field for field, review in reviews.items() if review.get("status") == "invalid"]
    structured["missing_fields"] = [field for field, review in reviews.items() if review.get("status") == "missing"]
    return structured


def write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def classic_api_url(cloud_url: str) -> str:
    return service.cloud_api_url(cloud_url).removesuffix("/parse-file") + "/classic-ocr"


def enhance_person(
    job_dir: Path,
    person_id: str,
    cloud_url: str,
    *,
    force: bool,
    timeout: int,
    retry_missing: bool = True,
) -> dict[str, Any]:
    output_dir = job_dir / "ocr_enhanced" / Path(person_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "general_classic_ocr.json"
    image_path = output_dir / "general_classic_crop.png"

    metadata: dict[str, Any] = {}
    reused_primary_response = False
    if json_path.is_file() and not force:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        if metadata.get("parser_version") == PARSER_VERSION:
            structured = metadata.get("structured") or {}
            return {
                "person": person_id,
                "cached": True,
                "parser_version": PARSER_VERSION,
                "artifact": str(json_path.resolve()),
                "parsed": structured.get("general_fields") or {},
                "conflicts": structured.get("conflict_fields") or [],
                "invalid": structured.get("invalid_fields") or [],
                "missing": structured.get("missing_fields") or [],
                "raw_text": (metadata.get("cloud_response") or {}).get("text", ""),
                "timings_ms": (metadata.get("cloud_response") or {}).get("timings_ms", {}),
            }
        saved_response = metadata.get("cloud_response") or {}
        saved_bands = metadata.get("crop_bands") or []
        if saved_response.get("success") and saved_bands and image_path.is_file():
            with Image.open(image_path) as saved_image:
                composite = saved_image.convert("RGB").copy()
            data = saved_response
            bands = saved_bands
            sources = [Path(value) for value in metadata.get("source_pdfs") or []]
            reused_primary_response = True

    if not reused_primary_response:
        composite, sources, bands = build_general_crop(job_dir, person_id)
        image_buffer = BytesIO()
        composite.save(image_buffer, format="PNG", optimize=True)
        image_bytes = image_buffer.getvalue()
        image_path.write_bytes(image_bytes)

        response = requests.post(
            classic_api_url(cloud_url),
            files={"file": (f"{person_id.replace('/', '_')}_general_classic.png", image_bytes, "image/png")},
            timeout=(30, timeout),
        )
        try:
            data = response.json()
        except ValueError as error:
            raise RuntimeError(f"{person_id} classic crop OCR returned non-JSON data: {response.text[:200]}") from error
        if not response.ok or not data.get("success"):
            raise RuntimeError(f"{person_id} classic crop OCR failed: {data.get('detail') or response.status_code}")

    structured = parse_classic_response(data, bands)
    retry_responses: list[dict[str, Any]] = []
    numeric_fields = {spec["field"] for spec in CROP_SPECS if spec.get("field")}
    for field in sorted(numeric_fields) if retry_missing else ():
        initial_review = (structured.get("field_reviews") or {}).get(field) or {}
        if initial_review.get("status") not in {"missing", "low_confidence"}:
            continue
        retry_band = next(
            (
                band
                for band in bands
                if band.get("field") == field and band.get("variant") == "threshold"
            ),
            None,
        )
        if retry_band is None:
            continue
        retry_image = composite.crop((0, retry_band["y_start"], retry_band["width"], retry_band["y_end"]))
        retry_buffer = BytesIO()
        retry_image.save(retry_buffer, format="PNG", optimize=True)
        retry_record: dict[str, Any] = {"field": field, "band_id": retry_band["id"]}
        try:
            retry_response = requests.post(
                classic_api_url(cloud_url),
                files={"file": (f"{person_id.replace('/', '_')}_{retry_band['id']}.png", retry_buffer.getvalue(), "image/png")},
                timeout=(30, timeout),
            )
            retry_data = retry_response.json()
            retry_record["cloud_response"] = retry_data
            if retry_response.ok and retry_data.get("success"):
                local_band = dict(retry_band)
                local_band.update(y_start=0, y_end=retry_image.height, height=retry_image.height)
                retry_items = retry_data.get("items") if isinstance(retry_data.get("items"), list) else []
                retry_mapped = map_items_to_bands(retry_items, [local_band])
                retry_review = numeric_field_review(field, [local_band], retry_mapped)
                retry_record["field_review"] = retry_review
                if retry_review.get("status") == "accepted":
                    structured["field_reviews"][field] = retry_review
                    structured.setdefault("mapped_items", []).extend(retry_mapped)
            else:
                retry_record["error"] = retry_data.get("detail") or f"HTTP {retry_response.status_code}"
        except Exception as error:
            retry_record["error"] = str(error)
        retry_responses.append(retry_record)
    refresh_structured_summary(structured)
    metadata = {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "primary_response_reused": reused_primary_response,
        "person": person_id,
        "source_pdfs": [str(path.resolve()) for path in sources],
        "crop_image": str(image_path.resolve()),
        "image_size": {"width": composite.width, "height": composite.height},
        "crop_bands": bands,
        "cloud_response": data,
        "retry_responses": retry_responses,
        "structured": structured,
    }
    write_json_atomic(json_path, metadata)
    return {
        "person": person_id,
        "cached": False,
        "reparsed": reused_primary_response,
        "parser_version": PARSER_VERSION,
        "artifact": str(json_path.resolve()),
        "parsed": structured["general_fields"],
        "conflicts": structured["conflict_fields"],
        "invalid": structured["invalid_fields"],
        "missing": structured["missing_fields"],
        "raw_text": data.get("text", ""),
        "timings_ms": data.get("timings_ms", {}),
    }


def merge_batch_report(report_path: Path, results: list[dict[str, Any]]) -> None:
    existing_people: dict[str, dict[str, Any]] = {}
    if report_path.is_file():
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
            for item in existing.get("people") or []:
                if isinstance(item, dict) and item.get("person"):
                    existing_people[str(item["person"])] = item
        except (OSError, ValueError, TypeError):
            existing_people = {}
    for result in results:
        person = str(result.get("person") or "")
        if not person:
            continue
        previous = existing_people.get(person)
        if "error" in result and previous and previous.get("parser_version") == PARSER_VERSION and "error" not in previous:
            preserved = dict(previous)
            preserved["last_error"] = result["error"]
            preserved["last_attempt_at"] = datetime.now().isoformat(timespec="seconds")
            existing_people[person] = preserved
        else:
            existing_people[person] = result
    payload = {
        "schema_version": 2,
        "parser_version": PARSER_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "people": [existing_people[key] for key in sorted(existing_people, key=person_sort_key)],
    }
    write_json_atomic(report_path, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PP-OCRv5 on fixed questionnaire identity/numeric crops.")
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--cloud-url", required=True)
    parser.add_argument("--people", nargs="*", help="Person ids such as ocr/1 or comma-separated numbers.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--skip-retries",
        action="store_true",
        help="Skip per-field retry requests after the main composite OCR (useful on slow CPU servers).",
    )
    parser.add_argument("--processing-mode", choices=("fast", "accurate"), default="accurate", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    job_dir = args.job_dir.resolve()
    people = parse_people(args.people, job_dir)
    results: list[dict[str, Any]] = []
    for index, person_id in enumerate(people, start=1):
        print(f"[{index}/{len(people)}] classic enhancing {person_id}", flush=True)
        try:
            result = enhance_person(
                job_dir,
                person_id,
                args.cloud_url,
                force=args.force,
                timeout=args.timeout,
                retry_missing=not args.skip_retries,
            )
            results.append(result)
            print(
                json.dumps(
                    {
                        "person": person_id,
                        "parsed": result.get("parsed", {}),
                        "conflicts": result.get("conflicts", []),
                        "invalid": result.get("invalid", []),
                        "missing": result.get("missing", []),
                        "raw_text": result.get("raw_text", ""),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as error:
            results.append({"person": person_id, "parser_version": PARSER_VERSION, "error": str(error)})
            print(f"  failed: {error}", flush=True)
    report_path = job_dir / "ocr_enhanced" / "general_crop_batch.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    merge_batch_report(report_path, results)
    print(
        json.dumps(
            {
                "report": str(report_path.resolve()),
                "processed": len(results),
                "failed": sum("error" in item for item in results),
                "conflicted": sum(bool(item.get("conflicts")) for item in results),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
