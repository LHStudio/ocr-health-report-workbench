from __future__ import annotations

"""Recover unresolved food-frequency cells from fixed-layout questionnaires.

This module deliberately separates *physical evidence* from OCR interpretation:
the aligned questionnaire is first compared with an unfilled reference, and only
rows with new ink are sent to the lightweight ``/classic-ocr`` endpoint.  A row is
accepted only when the evidence points to one frequency column and one reliable
count (or when the physical ``不吃`` cell is marked).  Ambiguous rows remain for
review; the script never chooses a value merely because it looks most likely.
"""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import cv2
import fitz
import numpy as np
import requests
from openpyxl import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.enhance_nutrition_crops import (  # noqa: E402
    ordered_source_pdfs,
    person_sort_key,
    write_json_atomic,
)


PARSER_VERSION = "nutrition-food-cell-classic-v1"
SCHEMA_VERSION = 1

PERIODS = ("每天", "每周", "每月", "每年", "不吃")
FOOD_CODES = (
    "1.1", "1.2", "2.1", "2.2", "2.3", "2.4", "3.1", "3.2", "3.3",
    "4.1", "4.2", "4.3", "4.4", "5.1", "5.2", "6", "7.1", "7.2",
    "8", "9", "10.1", "10.2", "11", "12", "13", "14", "15", "16",
    "17", "18", "19", "20", "21", "22", "23", "24", "25", "26",
)

TABLE_WIDTH = 900
TABLE_HEADER_HEIGHT = 120
TABLE_ROW_HEIGHT = 40
PERIOD_X_BOUNDARIES = (516, 602, 675, 748, 824, 900)
ROW_CELL_LABELS = ("食物名称", "平均每次食用量", *PERIODS)
ROW_CELL_X_BOUNDARIES = (0, 330, *PERIOD_X_BOUNDARIES)
CELL_INSET = 5

CURRENT_INK_THRESHOLD = 225
REFERENCE_INK_THRESHOLD = 235
REFERENCE_DILATION = 5
NOVEL_INK_OPENING = 2
MIN_COMPONENT_AREA = 3
BLANK_INK_THRESHOLD = 15

MIN_ALIGNMENT_CONFIDENCE = 0.25
MIN_OCR_SCORE = 0.60
MAX_COUNT_BY_PERIOD = {"每天": 10.0, "每周": 21.0, "每月": 31.0, "每年": 365.0}

OCR_CELL_WIDTH = 220
OCR_CELL_HEIGHT = 100
OCR_CELL_GAP = 20
OCR_BAND_GAP = 36
OCR_BAND_WIDTH = len(PERIODS) * OCR_CELL_WIDTH + (len(PERIODS) - 1) * OCR_CELL_GAP

PAGE1_REFERENCE = PROJECT_ROOT / "questionnaire_templates" / "food_frequency_blank_reference.png"
PAGE2_REFERENCE_FILENAME = "food_page2_median_reference.png"
GLOBAL_BATCH_FILENAME = "food_cell_batch.json"
GLOBAL_COMPOSITE_FILENAME = "food_cell_batch.png"
PERSON_RESULT_FILENAME = "food_cell_classic_ocr.json"
IMAGE_VARIANTS = ("novel-ink", "grayscale")


@dataclass(frozen=True)
class TableSpec:
    page_number: int
    source_page_index: int
    codes: tuple[str, ...]
    corners: tuple[tuple[float, float], ...]
    output_width: int
    output_height: int
    header_height: int = TABLE_HEADER_HEIGHT
    row_height: int = TABLE_ROW_HEIGHT

    def row_index(self, code: str) -> int:
        return self.codes.index(code)


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        page_number=1,
        source_page_index=0,
        codes=FOOD_CODES[:18],
        corners=((184, 716), (1080, 732), (1070, 1567), (172, 1551)),
        output_width=TABLE_WIDTH,
        output_height=840,
    ),
    TableSpec(
        page_number=2,
        source_page_index=1,
        codes=FOOD_CODES[18:],
        corners=((220, 165), (1114, 175), (1103, 1092), (208, 1081)),
        output_width=TABLE_WIDTH,
        output_height=920,
    ),
)
TABLE_BY_CODE = {code: spec for spec in TABLE_SPECS for code in spec.codes}


def utcish_now() -> str:
    """Use local time, matching the other job artifacts in this project."""

    return datetime.now().isoformat(timespec="seconds")


def read_gray_image(path: Path) -> np.ndarray:
    raw = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"无法读取图像：{path}")
    return image


def write_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not success:
        raise RuntimeError(f"无法编码 PNG：{path}")
    encoded.tofile(str(path))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render_pdf_page_gray(pdf_path: Path, target_shape: tuple[int, int], zoom: float = 2.0) -> np.ndarray:
    with fitz.open(pdf_path) as document:
        if not document.page_count:
            raise RuntimeError(f"PDF 没有页面：{pdf_path}")
        pixmap = document[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width).copy()
    height, width = target_shape
    if image.shape != (height, width):
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    return image


def align_orb(image: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Align ``image`` to ``reference`` and return auditable ORB diagnostics."""

    if image.ndim != 2 or reference.ndim != 2:
        raise ValueError("align_orb expects grayscale images")
    if image.shape != reference.shape:
        image = cv2.resize(image, (reference.shape[1], reference.shape[0]), interpolation=cv2.INTER_AREA)

    detector = cv2.ORB_create(5000)
    source_keys, source_desc = detector.detectAndCompute(image, None)
    target_keys, target_desc = detector.detectAndCompute(reference, None)
    empty = {
        "confidence": 0.0,
        "good_matches": 0,
        "inliers": 0,
        "source_keypoints": len(source_keys or []),
        "reference_keypoints": len(target_keys or []),
        "homography": [],
        "median_reprojection_error": None,
    }
    if source_desc is None or target_desc is None:
        return image.copy(), empty

    raw_pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(source_desc, target_desc, k=2)
    good = [pair[0] for pair in raw_pairs if len(pair) >= 2 and pair[0].distance < 0.72 * pair[1].distance]
    empty["good_matches"] = len(good)
    if len(good) < 30:
        return image.copy(), empty

    source_points = np.float32([source_keys[item.queryIdx].pt for item in good]).reshape(-1, 1, 2)
    target_points = np.float32([target_keys[item.trainIdx].pt for item in good]).reshape(-1, 1, 2)
    matrix, mask = cv2.findHomography(source_points, target_points, cv2.RANSAC, 4.0)
    if matrix is None or mask is None:
        return image.copy(), empty
    inliers = int(mask.sum())
    empty["inliers"] = inliers
    if inliers < 20:
        return image.copy(), empty

    confidence = inliers / max(len(good), 1)
    projected = cv2.perspectiveTransform(source_points, matrix)
    errors = np.linalg.norm(projected.reshape(-1, 2) - target_points.reshape(-1, 2), axis=1)
    inlier_errors = errors[mask.reshape(-1).astype(bool)]
    aligned = cv2.warpPerspective(
        image,
        matrix,
        (reference.shape[1], reference.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )
    empty["confidence"] = round(float(confidence), 6)
    empty["homography"] = [[round(float(value), 10) for value in row] for row in matrix.tolist()]
    empty["median_reprojection_error"] = round(float(np.median(inlier_errors)), 6) if inlier_errors.size else None
    return aligned, empty


def warp_table(image: np.ndarray, spec: TableSpec) -> np.ndarray:
    source = np.float32(spec.corners)
    destination = np.float32(
        ((0, 0), (spec.output_width - 1, 0), (spec.output_width - 1, spec.output_height - 1), (0, spec.output_height - 1))
    )
    matrix = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(
        image,
        matrix,
        (spec.output_width, spec.output_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )


def novel_ink_mask(current_table: np.ndarray, reference_table: np.ndarray) -> np.ndarray:
    current_ink = cv2.threshold(current_table, CURRENT_INK_THRESHOLD, 255, cv2.THRESH_BINARY_INV)[1]
    reference_ink = cv2.threshold(reference_table, REFERENCE_INK_THRESHOLD, 255, cv2.THRESH_BINARY_INV)[1]
    reference_ink = cv2.dilate(
        reference_ink,
        np.ones((REFERENCE_DILATION, REFERENCE_DILATION), dtype=np.uint8),
        iterations=1,
    )
    novel = cv2.bitwise_and(current_ink, cv2.bitwise_not(reference_ink))
    return cv2.morphologyEx(
        novel,
        cv2.MORPH_OPEN,
        np.ones((NOVEL_INK_OPENING, NOVEL_INK_OPENING), dtype=np.uint8),
    )


def filter_components(mask: np.ndarray, min_area: int = MIN_COMPONENT_AREA) -> tuple[np.ndarray, dict[str, int]]:
    if mask.size == 0:
        return np.zeros_like(mask), {"pixels": 0, "component_count": 0, "largest_component": 0}
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    kept = np.zeros_like(mask)
    areas: list[int] = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area >= min_area:
            kept[labels == label] = 255
            areas.append(area)
    return kept, {
        "pixels": int(np.count_nonzero(kept)),
        "component_count": len(areas),
        "largest_component": max(areas, default=0),
    }


def period_cell_bounds(spec: TableSpec, row_index: int, period_index: int, inset: int = CELL_INSET) -> tuple[int, int, int, int]:
    if not 0 <= row_index < len(spec.codes):
        raise IndexError(f"row_index {row_index} outside page {spec.page_number}")
    if not 0 <= period_index < len(PERIODS):
        raise IndexError(f"period_index {period_index} outside frequency columns")
    y0 = spec.header_height + row_index * spec.row_height + inset
    y1 = spec.header_height + (row_index + 1) * spec.row_height - inset
    x0 = PERIOD_X_BOUNDARIES[period_index] + inset
    x1 = PERIOD_X_BOUNDARIES[period_index + 1] - inset
    return x0, y0, x1, y1


def analyze_row_ink(mask: np.ndarray, spec: TableSpec, row_index: int) -> tuple[dict[str, int], dict[str, dict[str, int]], dict[str, np.ndarray]]:
    scores: dict[str, int] = {}
    details: dict[str, dict[str, int]] = {}
    cells: dict[str, np.ndarray] = {}
    for period_index, period in enumerate(PERIODS):
        x0, y0, x1, y1 = period_cell_bounds(spec, row_index, period_index)
        filtered, diagnostic = filter_components(mask[y0:y1, x0:x1])
        scores[period] = diagnostic["pixels"]
        details[period] = diagnostic
        cells[period] = filtered
    return scores, details, cells


def analyze_all_row_cells(
    mask: np.ndarray,
    spec: TableSpec,
    row_index: int,
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Score every physical row cell for blank/nonblank screening.

    Only the five period cells are sent to OCR, but handwriting in the food-name
    or quantity cell is still evidence that the source row is not genuinely blank.
    This distinction keeps descriptive handwriting and quantity-only answers in
    the review loop instead of silently classifying them as empty frequency rows.
    """

    y0 = spec.header_height + row_index * spec.row_height + CELL_INSET
    y1 = spec.header_height + (row_index + 1) * spec.row_height - CELL_INSET
    scores: dict[str, int] = {}
    details: dict[str, dict[str, int]] = {}
    for index, label in enumerate(ROW_CELL_LABELS):
        x0 = ROW_CELL_X_BOUNDARIES[index] + CELL_INSET
        x1 = ROW_CELL_X_BOUNDARIES[index + 1] - CELL_INSET
        _, diagnostic = filter_components(mask[y0:y1, x0:x1])
        scores[label] = diagnostic["pixels"]
        details[label] = diagnostic
    return scores, details


def is_blank_ink(ink_by_period: dict[str, int], threshold: int = BLANK_INK_THRESHOLD) -> bool:
    return max((int(value) for value in ink_by_period.values()), default=0) <= threshold


def _fit_binary_cell(mask: np.ndarray) -> np.ndarray:
    target = np.full((OCR_CELL_HEIGHT, OCR_CELL_WIDTH), 255, dtype=np.uint8)
    if mask.size == 0 or not np.any(mask):
        return target
    foreground = 255 - mask
    source_height, source_width = foreground.shape
    padding = 10
    scale = min((OCR_CELL_WIDTH - 2 * padding) / source_width, (OCR_CELL_HEIGHT - 2 * padding) / source_height)
    resized_width = max(1, round(source_width * scale))
    resized_height = max(1, round(source_height * scale))
    resized = cv2.resize(foreground, (resized_width, resized_height), interpolation=cv2.INTER_NEAREST)
    x = (OCR_CELL_WIDTH - resized_width) // 2
    y = (OCR_CELL_HEIGHT - resized_height) // 2
    target[y : y + resized_height, x : x + resized_width] = resized
    return target


def _fit_grayscale_cell(image: np.ndarray) -> np.ndarray:
    target = np.full((OCR_CELL_HEIGHT, OCR_CELL_WIDTH), 255, dtype=np.uint8)
    if image.size == 0:
        return target
    foreground = image[image < 250]
    if foreground.size == 0:
        normalized = np.full_like(image, 255)
    else:
        low = float(np.percentile(foreground, 5))
        normalized = np.clip((image.astype(np.float32) - low) * (255.0 / max(255.0 - low, 1.0)), 0, 255).astype(np.uint8)
        normalized[image >= 250] = 255
    resized = cv2.resize(normalized, (OCR_CELL_WIDTH - 12, OCR_CELL_HEIGHT - 12), interpolation=cv2.INTER_CUBIC)
    target[6:-6, 6:-6] = resized
    return target


def extract_grayscale_period_cells(
    current_table: np.ndarray,
    spec: TableSpec,
    row_index: int,
) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    for period_index, period in enumerate(PERIODS):
        x0, y0, x1, y1 = period_cell_bounds(spec, row_index, period_index)
        result[period] = current_table[y0:y1, x0:x1]
    return result


def select_ocr_period_cells(
    current_table: np.ndarray,
    spec: TableSpec,
    row_index: int,
    ink_cells: dict[str, np.ndarray],
    image_variant: str,
) -> dict[str, np.ndarray]:
    """Select OCR pixels without letting template subtraction damage grayscale strokes."""

    if image_variant == "novel-ink":
        return ink_cells
    if image_variant == "grayscale":
        return extract_grayscale_period_cells(current_table, spec, row_index)
    raise ValueError(f"Unsupported image variant: {image_variant}")


def build_target_strip(
    cells: dict[str, np.ndarray],
    *,
    image_variant: str = "novel-ink",
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    if image_variant not in IMAGE_VARIANTS:
        raise ValueError(f"Unsupported image variant: {image_variant}")
    strip = np.full((OCR_CELL_HEIGHT, OCR_BAND_WIDTH), 255, dtype=np.uint8)
    mappings: list[dict[str, Any]] = []
    for index, period in enumerate(PERIODS):
        x0 = index * (OCR_CELL_WIDTH + OCR_CELL_GAP)
        x1 = x0 + OCR_CELL_WIDTH
        if image_variant == "novel-ink":
            fitted = _fit_binary_cell(cells[period])
        else:
            fitted = _fit_grayscale_cell(cells[period])
        strip[:, x0:x1] = fitted
        mappings.append({"period": period, "x_start": x0, "x_end": x1, "y_start": 0, "y_end": OCR_CELL_HEIGHT})
    return strip, mappings


def build_batch_composite(prepared: list[dict[str, Any]]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    if not prepared:
        return np.full((1, OCR_BAND_WIDTH), 255, dtype=np.uint8), []
    height = len(prepared) * OCR_CELL_HEIGHT + (len(prepared) - 1) * OCR_BAND_GAP
    composite = np.full((height, OCR_BAND_WIDTH), 255, dtype=np.uint8)
    bands: list[dict[str, Any]] = []
    y = 0
    for target in prepared:
        strip = target["ocr_strip"]
        composite[y : y + OCR_CELL_HEIGHT, :] = strip
        cells = []
        for cell in target["ocr_cells"]:
            mapped = dict(cell)
            mapped["y_start"] = y
            mapped["y_end"] = y + OCR_CELL_HEIGHT
            cells.append(mapped)
        bands.append(
            {
                "id": target["id"],
                "person": target["person"],
                "code": target["code"],
                "x_start": 0,
                "x_end": OCR_BAND_WIDTH,
                "y_start": y,
                "y_end": y + OCR_CELL_HEIGHT,
                "cells": cells,
            }
        )
        y += OCR_CELL_HEIGHT + OCR_BAND_GAP
    return composite, bands


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


def _interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def map_ocr_items_with_diagnostics(items: Sequence[object], bands: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Map PP-OCR boxes conservatively and retain every rejected item."""

    mapped: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for source_index, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            unmapped.append({"source_index": source_index, "reason": "item_not_object", "item": raw_item})
            continue
        box = normalized_box(raw_item.get("box"))
        if not box:
            unmapped.append({"source_index": source_index, "reason": "box_missing", "item": raw_item})
            continue
        x0, y0, x1, y1 = box
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        box_height = max(1.0, y1 - y0)
        band_candidates = [
            (
                _interval_overlap(y0, y1, float(item["y_start"]), float(item["y_end"])),
                item,
            )
            for item in bands
        ]
        band_candidates.sort(key=lambda pair: pair[0], reverse=True)
        if not band_candidates:
            unmapped.append({"source_index": source_index, "reason": "no_bands", "item": raw_item, "box": box})
            continue
        vertical_overlap, band = band_candidates[0]
        second_vertical = band_candidates[1][0] if len(band_candidates) > 1 else 0.0
        vertical_overlap = _interval_overlap(y0, y1, float(band["y_start"]), float(band["y_end"]))
        if (
            vertical_overlap / box_height < 0.50
            or not (float(band["y_start"]) <= center_y <= float(band["y_end"]))
        ):
            unmapped.append({"source_index": source_index, "reason": "band_overlap_low", "item": raw_item, "box": box})
            continue
        if second_vertical and second_vertical >= vertical_overlap * 0.80:
            ambiguous.append({"source_index": source_index, "reason": "band_overlap_ambiguous", "item": raw_item, "box": box})
            continue
        box_width = max(1.0, x1 - x0)
        cell_candidates = [
            (
                _interval_overlap(x0, x1, float(item["x_start"]), float(item["x_end"])),
                item,
            )
            for item in band["cells"]
        ]
        cell_candidates.sort(key=lambda pair: pair[0], reverse=True)
        if not cell_candidates:
            unmapped.append({"source_index": source_index, "reason": "no_cells", "item": raw_item, "box": box})
            continue
        horizontal_overlap, cell = cell_candidates[0]
        second_horizontal = cell_candidates[1][0] if len(cell_candidates) > 1 else 0.0
        horizontal_overlap = _interval_overlap(x0, x1, float(cell["x_start"]), float(cell["x_end"]))
        if (
            horizontal_overlap / box_width < 0.50
            or not (float(cell["x_start"]) <= center_x <= float(cell["x_end"]))
        ):
            unmapped.append({"source_index": source_index, "reason": "cell_overlap_low", "item": raw_item, "box": box})
            continue
        if second_horizontal and second_horizontal >= horizontal_overlap * 0.80:
            ambiguous.append({"source_index": source_index, "reason": "cell_overlap_ambiguous", "item": raw_item, "box": box})
            continue
        mapped.append(
            {
                "source_index": source_index,
                "person": band["person"],
                "code": band["code"],
                "period": cell["period"],
                "text": str(raw_item.get("text") or "").strip(),
                "score": round(float(raw_item.get("score") or 0.0), 6),
                "box": box,
                "vertical_overlap_ratio": round(vertical_overlap / box_height, 4),
                "horizontal_overlap_ratio": round(horizontal_overlap / box_width, 4),
            }
        )
    return {"mapped": mapped, "ambiguous": ambiguous, "unmapped": unmapped}


def map_ocr_items(items: Sequence[object], bands: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility wrapper returning only safely mapped OCR items."""

    return map_ocr_items_with_diagnostics(items, bands)["mapped"]


_DIGIT_TRANSLATION = str.maketrans("０１２３４５６７８９", "0123456789")


def count_candidates(text: object, period: str) -> list[str]:
    """Extract plausible positive counts/ranges without inventing missing digits."""

    raw = str(text or "").translate(_DIGIT_TRANSLATION)
    raw = raw.replace("～", "-").replace("~", "-").replace("—", "-").replace("–", "-").replace("−", "-")
    raw = raw.replace("至", "-").replace("^", "-")
    raw = re.sub(r"(?<![\d.])(\d+)\.(?!\d)", r"\1", raw)
    tokens = re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?(?![\d.])", raw)
    maximum = MAX_COUNT_BY_PERIOD.get(period)
    result: list[str] = []
    for token in tokens:
        compact = re.sub(r"\s+", "", token)
        numbers = [float(value) for value in compact.split("-")]
        if not numbers or all(value == 0 for value in numbers):
            continue
        if len(numbers) == 2 and numbers[0] > numbers[1]:
            continue
        if maximum is not None and any(value > maximum for value in numbers):
            continue
        normalized_parts = [str(int(value)) if value.is_integer() else f"{value:g}" for value in numbers]
        normalized = "-".join(normalized_parts)
        if normalized not in result:
            result.append(normalized)
    return result


def is_explicit_not_eat_text(value: object) -> bool:
    text = re.sub(r"\s+", "", str(value or "")).translate(_DIGIT_TRANSLATION)
    text = text.strip("。；;，,:：")
    return bool(
        re.fullmatch(r"0(?:[.]0*)?", text)
        or text in {"无", "不吃", "✓", "√", "✔", "☑"}
    )


def quantity_is_explicit_zero(value: object) -> bool:
    """Accept only a literal zero, optionally followed by a known quantity unit."""

    text = re.sub(r"\s+", "", str(value or "")).translate(_DIGIT_TRANSLATION)
    text = text.replace("ＭＬ", "ml").replace("ｍｌ", "ml").replace("ML", "ml")
    unit = r"(?:kg|mg|ml|g|L|l|克|千克|毫升|升|勺|个|只|粒|片|瓶|杯)?"
    return bool(re.fullmatch(rf"0(?:\.0+)?{unit}", text, re.I))


def resolve_row(
    ink_by_period: dict[str, int],
    items_by_period: dict[str, list[dict[str, Any]]],
    *,
    blank_threshold: int = BLANK_INK_THRESHOLD,
    minimum_ocr_score: float = MIN_OCR_SCORE,
) -> dict[str, Any]:
    """Apply the conservative acceptance policy used by the rebuild stage."""

    marked = [period for period in PERIODS if int(ink_by_period.get(period, 0)) > blank_threshold]
    if not marked:
        return {
            "status": "frequency_blank",
            "selected_period": "",
            "count": "",
            "reliable_counts": {},
            "reason_codes": ["no_detectable_frequency_ink"],
            "manual_review_required": True,
        }

    reliable: dict[str, list[str]] = {}
    for period in PERIODS[:-1]:
        values: list[str] = []
        for item in items_by_period.get(period, []):
            if float(item.get("score") or 0.0) < minimum_ocr_score:
                continue
            for value in count_candidates(item.get("text"), period):
                if value not in values:
                    values.append(value)
        if values:
            reliable[period] = values

    numeric_marked = [period for period in marked if period != "不吃"]
    if "不吃" in marked:
        if numeric_marked or reliable:
            return {
                "status": "conflict",
                "selected_period": "",
                "count": "",
                "reliable_counts": reliable,
                "reason_codes": ["not_eat_and_numeric_ink_conflict"],
                "manual_review_required": True,
            }
        not_eat_items = items_by_period.get("不吃", [])
        explicit = [
            item
            for item in not_eat_items
            if float(item.get("score") or 0.0) >= minimum_ocr_score and is_explicit_not_eat_text(item.get("text"))
        ]
        invalid = [
            item
            for item in not_eat_items
            if float(item.get("score") or 0.0) >= minimum_ocr_score and str(item.get("text") or "").strip()
            and not is_explicit_not_eat_text(item.get("text"))
        ]
        if invalid:
            return {
                "status": "conflict",
                "selected_period": "",
                "count": "",
                "reliable_counts": reliable,
                "reason_codes": ["invalid_not_eat_value"],
                "manual_review_required": True,
            }
        if explicit:
            return {
                "status": "accepted",
                "selected_period": "不吃",
                "count": "0",
                "reliable_counts": reliable,
                "reason_codes": ["explicit_not_eat_cell"],
                "manual_review_required": False,
            }
        return {
            "status": "low_confidence",
            "selected_period": "",
            "count": "",
            "reliable_counts": reliable,
            "reason_codes": ["not_eat_ink_without_explicit_value"],
            "manual_review_required": True,
        }

    if len(reliable) > 1:
        return {
            "status": "conflict",
            "selected_period": "",
            "count": "",
            "reliable_counts": reliable,
            "reason_codes": ["multiple_reliable_periods"],
            "manual_review_required": True,
        }
    if len(reliable) == 1:
        period, values = next(iter(reliable.items()))
        if len(values) != 1 or numeric_marked != [period]:
            return {
                "status": "conflict",
                "selected_period": "",
                "count": "",
                "reliable_counts": reliable,
                "reason_codes": ["ocr_and_ink_period_mismatch"],
                "manual_review_required": True,
            }
        return {
            "status": "accepted",
            "selected_period": period,
            "count": values[0],
            "reliable_counts": reliable,
            "reason_codes": ["single_marked_period_single_count"],
            "manual_review_required": False,
        }
    if len(numeric_marked) > 1:
        return {
            "status": "conflict",
            "selected_period": "",
            "count": "",
            "reliable_counts": reliable,
            "reason_codes": ["multiple_marked_periods"],
            "manual_review_required": True,
        }
    return {
        "status": "low_confidence",
        "selected_period": "",
        "count": "",
        "reliable_counts": reliable,
        "reason_codes": ["marked_period_without_reliable_count"],
        "manual_review_required": True,
    }


def classic_api_url(cloud_url: str) -> str:
    url = cloud_url.strip().rstrip("/")
    if url.endswith("/classic-ocr"):
        return url
    if url.endswith("/parse-file"):
        return url[: -len("/parse-file")] + "/classic-ocr"
    return f"{url}/classic-ocr"


def _header_row(worksheet) -> int:
    best_row, best_count = 1, 0
    for row_number, values in enumerate(
        worksheet.iter_rows(min_row=1, max_row=min(30, worksheet.max_row), values_only=True), start=1
    ):
        count = sum(bool(str(value).strip()) for value in values if value is not None)
        if count > best_count:
            best_row, best_count = row_number, count
    return best_row


def collect_targets(
    workbook_path: Path,
    include_review: bool = False,
    review_scope: str = "all",
) -> tuple[list[dict[str, str]], list[str]]:
    """Collect unresolved rows, optionally including rows carrying review notes."""

    if review_scope not in {"all", "period"}:
        raise ValueError("review_scope must be all or period")
    period_markers = ("频率列", "多个频率", "正数与零", "次数疑似异常")

    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        worksheet = next((sheet for sheet in workbook.worksheets if "食物" in sheet.title), None)
        if worksheet is None:
            raise RuntimeError("汇总表中没有名称包含“食物”的工作表")
        header_row = _header_row(worksheet)
        headers = [
            "" if worksheet.cell(header_row, column).value is None else str(worksheet.cell(header_row, column).value).strip()
            for column in range(1, worksheet.max_column + 1)
        ]
        required = {"人员文件夹", "食物编号", "食物名称", "频率周期(请核对)"}
        if not required.issubset(headers):
            missing = "、".join(sorted(required - set(headers)))
            raise RuntimeError(f"食物明细缺少列：{missing}")
        people: list[str] = []
        targets: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for values in worksheet.iter_rows(min_row=header_row + 1, values_only=True):
            row = {
                header: "" if index >= len(values) or values[index] is None else str(values[index]).strip()
                for index, header in enumerate(headers)
                if header
            }
            person = row.get("人员文件夹", "").replace("\\", "/")
            code = row.get("食物编号", "")
            if person and person not in people:
                people.append(person)
            period = row.get("频率周期(请核对)", "")
            review_note = row.get("人工核对备注", "")
            include_note = include_review and bool(review_note)
            if include_note and review_scope == "period":
                include_note = any(marker in review_note for marker in period_markers)
            if period != "未识别" and not include_note:
                continue
            if code not in TABLE_BY_CODE:
                raise RuntimeError(f"无法定位食物编号 {code!r}（人员 {person!r}）")
            key = (person, code)
            if not person or key in seen:
                continue
            seen.add(key)
            targets.append(
                {
                    "person": person,
                    "code": code,
                    "name": row.get("食物名称", ""),
                    "quantity": row.get("平均每次食用量", ""),
                    "workbook_count": row.get("次数", ""),
                    "workbook_not_eat": row.get("是否不吃", ""),
                    "workbook_raw": row.get("OCR原始行", ""),
                    "workbook_period": period,
                    "workbook_review_note": review_note,
                }
            )
    finally:
        workbook.close()

    code_order = {code: index for index, code in enumerate(FOOD_CODES)}
    people = sorted(people, key=person_sort_key)
    targets.sort(key=lambda item: (person_sort_key(item["person"]), code_order[item["code"]]))
    return targets, people


# Backwards-friendly name for callers written against the first implementation.
load_targets = collect_targets


def source_pages(job_dir: Path, person: str) -> list[Path]:
    sources = ordered_source_pdfs(job_dir, person)
    if len(sources) < 2:
        raise RuntimeError(f"{person} 应至少有两份按 OCR 顺序保存的问卷 PDF，实际 {len(sources)} 份")
    return sources


def build_page2_reference(
    job_dir: Path,
    people: Sequence[str],
    target_shape: tuple[int, int],
    *,
    force: bool,
) -> tuple[np.ndarray, dict[str, Any]]:
    output_path = job_dir / "ocr_enhanced" / PAGE2_REFERENCE_FILENAME
    if output_path.is_file() and not force:
        image = read_gray_image(output_path)
        if image.shape != target_shape:
            image = cv2.resize(image, (target_shape[1], target_shape[0]), interpolation=cv2.INTER_AREA)
        return image, {
            "path": str(output_path.resolve()),
            "cached": True,
            "people_requested": len(people),
            "people_used": None,
        }

    if not people:
        raise RuntimeError("无法生成第 2 页中位数参考：汇总表没有人员")
    seed_person = sorted(people, key=person_sort_key)[0]
    seed_pdf = source_pages(job_dir, seed_person)[1]
    seed = render_pdf_page_gray(seed_pdf, target_shape)
    aligned_images: list[np.ndarray] = [seed]
    alignments: list[dict[str, Any]] = [
        {"person": seed_person, "source_pdf": str(seed_pdf.resolve()), "confidence": 1.0, "seed": True}
    ]
    for person in sorted((value for value in people if value != seed_person), key=person_sort_key):
        try:
            source_pdf = source_pages(job_dir, person)[1]
            image = render_pdf_page_gray(source_pdf, target_shape)
            aligned, diagnostic = align_orb(image, seed)
            record = {"person": person, "source_pdf": str(source_pdf.resolve()), **diagnostic, "seed": False}
            if float(diagnostic["confidence"]) >= MIN_ALIGNMENT_CONFIDENCE:
                aligned_images.append(aligned)
                record["included"] = True
            else:
                record["included"] = False
                record["warning"] = "alignment_low"
            alignments.append(record)
        except Exception as error:
            alignments.append({"person": person, "included": False, "error": str(error), "seed": False})
    if len(aligned_images) < 3:
        raise RuntimeError(f"第 2 页中位数参考仅得到 {len(aligned_images)} 个可对齐页面，拒绝生成")

    stack = np.stack(aligned_images, axis=0)
    median = np.empty(target_shape, dtype=np.uint8)
    for y0 in range(0, target_shape[0], 64):
        y1 = min(target_shape[0], y0 + 64)
        median[y0:y1] = np.median(stack[:, y0:y1], axis=0).astype(np.uint8)
    write_png(output_path, median)
    return median, {
        "path": str(output_path.resolve()),
        "cached": False,
        "seed_person": seed_person,
        "seed_pdf": str(seed_pdf.resolve()),
        "people_requested": len(people),
        "people_used": len(aligned_images),
        "alignments": alignments,
    }


def _artifact_suffix(image_variant: str) -> str:
    return "" if image_variant == "novel-ink" else f"_{image_variant}"


def _target_crop_path(job_dir: Path, person: str, code: str, image_variant: str) -> Path:
    safe_code = code.replace(".", "_")
    return job_dir / "ocr_enhanced" / Path(person) / "food_cells" / f"food_{safe_code}{_artifact_suffix(image_variant)}.png"


def prepare_targets(
    job_dir: Path,
    targets: Sequence[dict[str, str]],
    references: dict[int, np.ndarray],
    *,
    image_variant: str = "novel-ink",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_person: dict[str, list[dict[str, str]]] = {}
    for target in targets:
        by_person.setdefault(target["person"], []).append(target)

    rows: list[dict[str, Any]] = []
    ocr_ready: list[dict[str, Any]] = []
    for person in sorted(by_person, key=person_sort_key):
        sources = source_pages(job_dir, person)
        page_cache: dict[int, tuple[np.ndarray, np.ndarray, dict[str, Any], Path]] = {}
        needed_specs = {TABLE_BY_CODE[item["code"]] for item in by_person[person]}
        for spec in needed_specs:
            source_pdf = sources[spec.source_page_index]
            reference = references[spec.page_number]
            rendered = render_pdf_page_gray(source_pdf, reference.shape)
            aligned, alignment = align_orb(rendered, reference)
            current_table = warp_table(aligned, spec)
            reference_table = warp_table(reference, spec)
            ink = novel_ink_mask(current_table, reference_table)
            page_cache[spec.page_number] = (current_table, ink, alignment, source_pdf)

        for target in by_person[person]:
            spec = TABLE_BY_CODE[target["code"]]
            row_index = spec.row_index(target["code"])
            current_table, ink, alignment, source_pdf = page_cache[spec.page_number]
            scores, ink_details, cells = analyze_row_ink(ink, spec, row_index)
            ink_by_cell, ink_details_by_cell = analyze_all_row_cells(ink, spec, row_index)
            ocr_source_cells = select_ocr_period_cells(current_table, spec, row_index, cells, image_variant)
            strip, ocr_cells = build_target_strip(ocr_source_cells, image_variant=image_variant)
            crop_path = _target_crop_path(job_dir, person, target["code"], image_variant)
            write_png(crop_path, strip)
            alignment_confidence = float(alignment.get("confidence") or 0.0)
            row: dict[str, Any] = {
                "id": f"{person}|{target['code']}",
                "person": person,
                "code": target["code"],
                "name": target.get("name", ""),
                "quantity": target.get("quantity", ""),
                "workbook_count": target.get("workbook_count", ""),
                "workbook_not_eat": target.get("workbook_not_eat", ""),
                "workbook_raw": target.get("workbook_raw", ""),
                "workbook_period": target.get("workbook_period", ""),
                "workbook_review_note": target.get("workbook_review_note", ""),
                "eligible_for_apply": target.get("workbook_period", "") == "未识别",
                "source_pdf": str(source_pdf.resolve()),
                "source_pdf_sha256": sha256_file(source_pdf),
                "source_page_index": spec.source_page_index + 1,
                "table_page": spec.page_number,
                "table_row_index": row_index,
                "crop": str(crop_path.resolve()),
                "crop_sha256": sha256_file(crop_path),
                "image_variant": image_variant,
                "alignment_confidence": round(alignment_confidence, 6),
                "alignment": alignment,
                "ink_by_period": scores,
                "ink_details_by_period": ink_details,
                "ink_by_cell": ink_by_cell,
                "ink_details_by_cell": ink_details_by_cell,
                "max_new_ink": max(ink_by_cell.values(), default=0),
                "items_by_period": {period: [] for period in PERIODS},
                "text_by_period": {period: "" for period in PERIODS},
                "status": "ocr_pending",
                "selected_period": "",
                "count": "",
                "reason_codes": ["classic_ocr_pending"],
                "manual_review_required": True,
            }
            if alignment_confidence < MIN_ALIGNMENT_CONFIDENCE:
                row["status"] = "alignment_low"
                row["reason_codes"] = ["alignment_confidence_below_threshold"]
            elif is_blank_ink(scores) and quantity_is_explicit_zero(target.get("quantity")):
                row["status"] = "accepted"
                row["selected_period"] = "不吃"
                row["count"] = "0"
                row["reason_codes"] = ["explicit_zero_quantity"]
                row["manual_review_required"] = False
            elif is_blank_ink(scores):
                row["status"] = "frequency_blank"
                row["reason_codes"] = ["no_detectable_frequency_ink"]
            else:
                row["ocr_strip"] = strip
                row["ocr_cells"] = ocr_cells
                ocr_ready.append(row)
            rows.append(row)
    return rows, ocr_ready


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"ocr_strip", "ocr_cells"}}


def apply_ocr_response(rows: Sequence[dict[str, Any]], response: dict[str, Any], bands: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    raw_items = response.get("items") if isinstance(response, dict) else []
    mapping = map_ocr_items_with_diagnostics(raw_items if isinstance(raw_items, list) else [], bands)
    mapped = mapping["mapped"]
    mapped_by_id: dict[str, list[dict[str, Any]]] = {}
    for item in mapped:
        mapped_by_id.setdefault(f"{item['person']}|{item['code']}", []).append(item)
    for row in rows:
        if row.get("status") != "ocr_pending":
            continue
        items = mapped_by_id.get(row["id"], [])
        items_by_period = {period: [] for period in PERIODS}
        for item in items:
            items_by_period[item["period"]].append(item)
        text_by_period = {
            period: "\n".join(item["text"] for item in period_items if item.get("text"))
            for period, period_items in items_by_period.items()
        }
        resolution = resolve_row(row["ink_by_period"], items_by_period)
        row.update(resolution)
        row["items_by_period"] = items_by_period
        row["text_by_period"] = text_by_period
    return mapping


def _load_cached_batch(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_results(
    job_dir: Path,
    workbook_path: Path,
    rows: Sequence[dict[str, Any]],
    batch_payload: dict[str, Any],
    batch_path: Path,
    person_result_filename: str,
) -> None:
    public_rows = [_public_row(row) for row in rows]
    batch_payload["rows"] = public_rows
    write_json_atomic(batch_path, batch_payload)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in public_rows:
        grouped.setdefault(row["person"], []).append(row)
    for person, person_rows in grouped.items():
        output_path = job_dir / "ocr_enhanced" / Path(person) / person_result_filename
        payload = {
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
            "generated_at": batch_payload["generated_at"],
            "person": person,
            "job_dir": str(job_dir.resolve()),
            "workbook": str(workbook_path.resolve()),
            "workbook_sha256": batch_payload["workbook_sha256"],
            "batch": str(batch_path.resolve()),
            "rows": person_rows,
        }
        write_json_atomic(output_path, payload)


def enhance(
    job_dir: Path,
    workbook_path: Path,
    cloud_url: str | None,
    *,
    force: bool = False,
    prepare_only: bool = False,
    include_review: bool = False,
    review_scope: str = "all",
    image_variant: str = "novel-ink",
    timeout: int = 900,
) -> dict[str, Any]:
    job_dir = job_dir.resolve()
    workbook_path = workbook_path.resolve()
    if not job_dir.is_dir():
        raise FileNotFoundError(f"任务目录不存在：{job_dir}")
    if not workbook_path.is_file():
        raise FileNotFoundError(f"汇总表不存在：{workbook_path}")
    if not PAGE1_REFERENCE.is_file():
        raise FileNotFoundError(f"第 1 页空白参考不存在：{PAGE1_REFERENCE}")
    if image_variant not in IMAGE_VARIANTS:
        raise ValueError(f"image_variant must be one of {', '.join(IMAGE_VARIANTS)}")

    targets, people = collect_targets(workbook_path, include_review=include_review, review_scope=review_scope)
    page1_reference = read_gray_image(PAGE1_REFERENCE)
    page2_reference, page2_metadata = build_page2_reference(
        job_dir,
        people,
        page1_reference.shape,
        force=force,
    )
    references = {1: page1_reference, 2: page2_reference}
    rows, ocr_ready = prepare_targets(job_dir, targets, references, image_variant=image_variant)
    composite, bands = build_batch_composite(ocr_ready)
    suffix = _artifact_suffix(image_variant)
    composite_path = job_dir / "ocr_enhanced" / f"{Path(GLOBAL_COMPOSITE_FILENAME).stem}{suffix}.png"
    write_png(composite_path, composite)
    composite_bytes = cv2.imencode(".png", composite, [cv2.IMWRITE_PNG_COMPRESSION, 6])[1].tobytes()
    composite_hash = sha256_bytes(composite_bytes)

    batch_path = job_dir / "ocr_enhanced" / f"{Path(GLOBAL_BATCH_FILENAME).stem}{suffix}.json"
    person_result_filename = f"{Path(PERSON_RESULT_FILENAME).stem}{suffix}.json"
    cached = _load_cached_batch(batch_path)
    cloud_response: dict[str, Any] = {}
    cloud_error = ""
    cache_reused = False
    cached_response = cached.get("cloud_response") if isinstance(cached.get("cloud_response"), dict) else {}
    if (
        not force
        and cached.get("parser_version") == PARSER_VERSION
        and cached.get("image_variant", "novel-ink") == image_variant
        and cached.get("composite_sha256") == composite_hash
        and cached_response.get("success")
    ):
        cloud_response = cached_response
        cache_reused = True
    elif ocr_ready and not prepare_only:
        if not cloud_url:
            raise ValueError("非 --prepare-only 模式必须提供 --cloud-url")
        try:
            response = requests.post(
                classic_api_url(cloud_url),
                files={"file": (composite_path.name, composite_bytes, "image/png")},
                timeout=(30, timeout),
            )
            try:
                cloud_response = response.json()
            except ValueError as error:
                raise RuntimeError(f"经典 OCR 返回非 JSON：{response.text[:200]}") from error
            if not response.ok or not cloud_response.get("success"):
                raise RuntimeError(cloud_response.get("detail") or f"HTTP {response.status_code}")
        except Exception as error:
            cloud_error = str(error)

    mapping_diagnostics: dict[str, list[dict[str, Any]]] = {"mapped": [], "ambiguous": [], "unmapped": []}
    if cloud_response.get("success"):
        mapping_diagnostics = apply_ocr_response(rows, cloud_response, bands)
    elif cloud_error:
        for row in rows:
            if row.get("status") == "ocr_pending":
                row["status"] = "ocr_error"
                row["error"] = cloud_error
                row["reason_codes"] = ["classic_ocr_request_failed"]
                row["manual_review_required"] = True

    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "generated_at": utcish_now(),
        "job_dir": str(job_dir),
        "workbook": str(workbook_path),
        "workbook_sha256": sha256_file(workbook_path),
        "prepare_only": prepare_only,
        "include_review": include_review,
        "review_scope": review_scope,
        "image_variant": image_variant,
        "force": force,
        "thresholds": {
            "current_ink": CURRENT_INK_THRESHOLD,
            "reference_ink": REFERENCE_INK_THRESHOLD,
            "reference_dilation": REFERENCE_DILATION,
            "opening": NOVEL_INK_OPENING,
            "minimum_component_area": MIN_COMPONENT_AREA,
            "blank_max_pixels": BLANK_INK_THRESHOLD,
            "minimum_alignment_confidence": MIN_ALIGNMENT_CONFIDENCE,
            "minimum_ocr_score": MIN_OCR_SCORE,
        },
        "page1_reference": {"path": str(PAGE1_REFERENCE.resolve()), "sha256": sha256_file(PAGE1_REFERENCE)},
        "page2_reference": {**page2_metadata, "sha256": sha256_file(job_dir / "ocr_enhanced" / PAGE2_REFERENCE_FILENAME)},
        "composite_image": str(composite_path.resolve()),
        "composite_sha256": composite_hash,
        "bands": bands,
        "cloud_url": classic_api_url(cloud_url) if cloud_url else "",
        "cloud_response_reused": cache_reused,
        "cloud_response": cloud_response,
        "cloud_error": cloud_error,
        "mapped_items": mapping_diagnostics["mapped"],
        "ambiguous_items": mapping_diagnostics["ambiguous"],
        "unmapped_items": mapping_diagnostics["unmapped"],
        "target_count": len(rows),
        "ocr_target_count": len(ocr_ready),
        "status_counts": status_counts,
    }
    _write_results(job_dir, workbook_path, rows, payload, batch_path, person_result_filename)
    return {
        "parser_version": PARSER_VERSION,
        "job_dir": str(job_dir),
        "workbook": str(workbook_path),
        "batch": str(batch_path.resolve()),
        "composite": str(composite_path.resolve()),
        "target_count": len(rows),
        "ocr_target_count": len(ocr_ready),
        "status_counts": status_counts,
        "cloud_response_reused": cache_reused,
        "cloud_error": cloud_error,
        "image_variant": image_variant,
        "review_scope": review_scope,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="对齐食物频率问卷，筛掉真空白行，并批量经典 OCR 未识别的频率单元格。"
    )
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--cloud-url", help="云端基地址、/parse-file 或 /classic-ocr 地址。")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--force", action="store_true", help="重建第 2 页参考并忽略已有经典 OCR 响应。")
    parser.add_argument("--prepare-only", action="store_true", help="只生成对齐诊断、单元格裁剪和合成图，不请求云端。")
    parser.add_argument(
        "--image-variant",
        choices=IMAGE_VARIANTS,
        default="novel-ink",
        help="OCR 图像：novel-ink=模板差分墨迹，grayscale=对齐后的原始灰度单元格。",
    )
    parser.add_argument(
        "--include-review",
        action="store_true",
        help="除“未识别”外，同时纳入人工核对备注非空的食物行。默认关闭。",
    )
    parser.add_argument(
        "--review-scope",
        choices=("all", "period"),
        default="all",
        help="与 --include-review 配合：all=所有备注，period=只处理周期/次数相关风险。",
    )
    args = parser.parse_args()
    result = enhance(
        args.job_dir,
        args.workbook,
        args.cloud_url,
        force=args.force,
        prepare_only=args.prepare_only,
        include_review=args.include_review,
        review_scope=args.review_scope,
        image_variant=args.image_variant,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("cloud_error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
