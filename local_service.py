"""本机批量服务：按人员文件夹调用云端 OCR，自动回写并留存每页 OCR Excel。"""
from __future__ import annotations

import base64
import difflib
import json
import math
import re
import shutil
import time
import uuid
from collections import Counter, defaultdict
from copy import copy
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from datetime import datetime
from nutrition_report import NutritionReportService

ROOT = Path(__file__).resolve().parent
JOB_ROOT = ROOT / "data" / "jobs"
JOB_ROOT.mkdir(parents=True, exist_ok=True)
TEMPLATE_ROOT = ROOT / "templates"
TEMPLATE_ROOT.mkdir(parents=True, exist_ok=True)
MEDICAL_TEMPLATE_ROOT = ROOT / "data" / "templates"
MEDICAL_TEMPLATE_ROOT.mkdir(parents=True, exist_ok=True)
LAST_MEDICAL_TEMPLATE = MEDICAL_TEMPLATE_ROOT / "medical_last_template.xlsx"
LAST_MEDICAL_TEMPLATE_META = MEDICAL_TEMPLATE_ROOT / "medical_last_template.json"
MEDICAL_NORMAL_RANGE_CONFIG = MEDICAL_TEMPLATE_ROOT / "medical_normal_ranges.json"
NUTRITION_TEMPLATE = TEMPLATE_ROOT / "食物频率调查_汇总模板.xlsx"
JOBS: dict[str, dict[str, Any]] = {}

app = FastAPI(title="本地 OCR 批量回写服务")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.mount("/files", StaticFiles(directory=JOB_ROOT), name="files")

NUTRITION_GENERAL_COLUMNS = ["人员文件夹", "受试者编号", "姓名", "调查日期", "访视号", "每日餐次", "每周在家吃饭天数", "早餐地点", "午餐地点", "晚餐地点", "每周户外日照天数", "每日户外日照时长(小时)", "晒太阳时段", "皮肤暴露部位", "去脂体重", "人工备注"]
NUTRITION_FOOD_COLUMNS = ["人员文件夹", "姓名", "食物编号", "食物名称", "平均每次食用量", "次数", "频率周期(请核对)", "是否不吃", "人工核对备注"]
NUTRITION_SUPPLEMENT_COLUMNS = ["人员文件夹", "姓名", "保健品种类", "保健品名称", "平均每次服用量", "次数", "频率周期(请核对)", "是否不吃", "备注"]
NUTRITION_PERIODS = ("每天", "每周", "每月", "每年", "不吃")
NUTRITION_FOOD_ITEMS = {
    "1.1": "米饭", "1.2": "大米粥", "2.1": "馒头", "2.2": "面包", "2.3": "面条", "2.4": "包子/饺子",
    "3.1": "玉米", "3.2": "小米", "3.3": "窝头", "4.1": "红薯", "4.2": "山药", "4.3": "芋头",
    "4.4": "土豆", "5.1": "油条", "5.2": "油饼", "6": "猪肉", "7.1": "牛肉", "7.2": "羊肉",
    "8": "鸡肉、鸭肉", "9": "内脏类", "10.1": "鱼", "10.2": "虾", "11": "鲜奶", "12": "奶粉",
    "13": "奶酪", "14": "酸奶", "15": "蛋类", "16": "豆腐", "17": "豆腐丝/千张/豆腐干",
    "18": "豆浆", "19": "新鲜蔬菜", "20": "糕点", "21": "新鲜水果", "22": "坚果",
    "23": "果汁饮料", "24": "咖啡", "25": "茶/茶饮料", "26": "其他饮料",
}
NUTRITION_SUPPLEMENT_ITEMS = ("维生素D", "钙", "鱼油", "酵素", "其他保健品(如蛋白粉)")
CLOUD_OCR_TIMEOUT = (30, 900)
CLOUD_OCR_MAX_ATTEMPTS = 4
CLOUD_OCR_RETRY_DELAYS = (2, 5, 10)


def ensure_nutrition_template() -> None:
    if NUTRITION_TEMPLATE.exists():
        # 迁移已在本机保存的旧默认模板：明细表不再导出 OCR 原始行，
        # 并在人员文件夹后增加姓名，方便跨表人工核对。
        workbook = load_workbook(NUTRITION_TEMPLATE)
        changed = False
        for sheet_name in ("食物频率明细", "营养保健品"):
            if sheet_name not in workbook.sheetnames:
                continue
            worksheet = workbook[sheet_name]
            headers = [str(worksheet.cell(1, column).value or "").strip() for column in range(1, worksheet.max_column + 1)]
            for column in reversed([index + 1 for index, header in enumerate(headers) if header == "OCR原始行"]):
                worksheet.delete_cols(column)
                changed = True
            headers = [str(worksheet.cell(1, column).value or "").strip() for column in range(1, worksheet.max_column + 1)]
            if "姓名" not in headers and "人员文件夹" in headers:
                folder_column = headers.index("人员文件夹") + 1
                insert_column = folder_column + 1
                worksheet.insert_cols(insert_column)
                for row in range(1, worksheet.max_row + 1):
                    worksheet.cell(row, insert_column)._style = copy(worksheet.cell(row, folder_column)._style)
                    if row == 1:
                        worksheet.cell(row, insert_column).value = "姓名"
                changed = True
            if changed:
                worksheet.auto_filter.ref = worksheet.dimensions
        if changed:
            workbook.save(NUTRITION_TEMPLATE)
        workbook.close()
        return
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = [("人员汇总", NUTRITION_GENERAL_COLUMNS), ("食物频率明细", NUTRITION_FOOD_COLUMNS), ("营养保健品", NUTRITION_SUPPLEMENT_COLUMNS)]
    for name, headers in sheets:
        worksheet = workbook.create_sheet(name)
        worksheet.append(headers)
        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="167D73")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        for index, header in enumerate(headers, start=1):
            worksheet.column_dimensions[chr(64 + min(index, 26))].width = max(14, min(28, len(header) + 5))
    note = workbook.create_sheet("填写说明")
    note.append(["说明"])
    note.append(["1. 本模板由系统自动生成。人员汇总是一人一行；食物频率明细与营养保健品是一人多行。"])
    note.append(["2. OCR 对手写数值、勾选项和频率所在列可能不稳定；“频率周期(请核对)”应在核对页人工确认。"])
    note.append(["3. 原始 OCR Excel 和 PDF 会按任务、人员分别留存，便于复核。"])
    note.column_dimensions["A"].width = 110
    workbook.save(NUTRITION_TEMPLATE)
    workbook.close()


ensure_nutrition_template()

ALIASES = {
    "姓名": ("姓名", "受检者", "患者姓名"), "年龄": ("年龄", "年龄岁"), "性别": ("性别",),
    "病历号": ("病历号", "门诊号", "住院号", "编号"), "报告日期": ("报告日期", "检验日期"),
    "转铁蛋白": ("转铁蛋白", "trf"), "25羟维生素d": ("25羟维生素d", "维生素d", "vd"), "类胰岛素样生长因子": ("类胰岛素样生长因子", "igf1"),
    "生长激素": ("生长激素", "hgh"), "游离三碘甲状腺原氨酸": ("游离三碘甲状腺原氨酸", "ft3"), "游离甲状腺素": ("游离甲状腺素", "ft4"),
    "促甲状腺素": ("促甲状腺素", "促甲状腺激素", "tsh"), "孕酮": ("孕酮",), "睾酮": ("睾酮",), "卵泡生成素": ("卵泡生成素", "fsh"),
    "雄烯二酮": ("雄烯二酮",), "抗缪勒管激素": ("抗缪勒管激素", "抗继勒管激素", "抗穆勒管激素", "amh"), "促黄体生成素": ("促黄体生成素", "lh"),
    "雌二醇": ("雌二醇", "e2"), "垂体泌乳素": ("垂体泌乳素", "prl"), "白细胞": ("白细胞", "白细胞计数", "wbc"),
    "红细胞": ("红细胞", "红细胞计数", "rbc"), "血红蛋白": ("血红蛋白", "hgb"), "红细胞压积": ("红细胞压积", "hct"),
    "平均红细胞体积": ("平均红细胞体积", "mcv"), "平均血红蛋白含量": ("平均血红蛋白含量", "mch"),
    "平均血红蛋白浓度": ("平均血红蛋白浓度", "mchc"), "血小板": ("血小板", "血小板计数", "plt"), "淋巴细胞百分数": ("淋巴细胞百分数", "lymph"),
    "嗜酸性粒细胞百分数": ("嗜酸性粒细胞百分数", "eo%", "eo"), "嗜碱性粒细胞百分数": ("嗜碱性粒细胞百分数", "baso%", "baso"),
    "卵巢储备评估得分": ("卵巢储备评估得分", "卵巢储备评分", "卵巢储备评估分数"),
    "推测卵巢储备减退年龄": ("推测卵巢储备减退年龄", "预测卵巢储备减退年龄", "卵巢储备减退年龄"),
    "推测围绝经期开始年龄": ("推测围绝经期开始年龄", "预测围绝经期开始年龄", "围绝经期开始年龄"),
    "卵巢功能等级": ("卵巢功能等级", "卵巢功能分级", "卵巢功能级别"),
}
SKIP_LABELS = {"序号", "项目", "检验项目", "检测项目", "结果", "检测结果", "参考范围", "单位", "指标"}
PROFILE_FIELDS = {"姓名", "年龄", "性别", "病历号", "报告日期"}

# 这些默认值来自当前项目同一检验体系的既有报告。性激素等会受月经周期、
# 年龄等影响的项目不预设范围，需由使用者在页面设置后才参与异常判断。
MEDICAL_NORMAL_RANGE_FIELDS = tuple(key for key in ALIASES if key not in PROFILE_FIELDS)
DEFAULT_MEDICAL_NORMAL_RANGES: dict[str, dict[str, float | None]] = {
    "转铁蛋白": {"min": 212, "max": 360},
    "25羟维生素d": {"min": 20, "max": None},
    "生长激素": {"min": None, "max": 8},
    "游离三碘甲状腺原氨酸": {"min": 2.3, "max": 4.2},
    "游离甲状腺素": {"min": 0.89, "max": 1.80},
    "促甲状腺素": {"min": 0.55, "max": 4.78},
    "雄烯二酮": {"min": 1.08, "max": 11.73},
    "抗缪勒管激素": {"min": 0.97, "max": 12.53},
    "垂体泌乳素": {"min": 3.34, "max": 26.72},
    "白细胞": {"min": 3.5, "max": 9.5},
    "红细胞": {"min": 3.8, "max": 5.1},
    "血红蛋白": {"min": 115, "max": 150},
    "红细胞压积": {"min": 0.35, "max": 0.45},
    "平均红细胞体积": {"min": 82, "max": 100},
    "平均血红蛋白含量": {"min": 27, "max": 34},
    "平均血红蛋白浓度": {"min": 316, "max": 354},
    "血小板": {"min": 125, "max": 350},
    "淋巴细胞百分数": {"min": 20, "max": 50},
    "嗜酸性粒细胞百分数": {"min": 0.4, "max": 8.0},
    "嗜碱性粒细胞百分数": {"min": 0, "max": 1},
}
METADATA_SOURCE_WORDS = (
    "采样", "送检", "签收", "接收", "登记", "审核", "审签", "打印", "时间", "日期", "科别", "科室",
    "病区", "病床", "床号", "标本", "样本", "诊断", "备注", "检验者", "审核者", "检测岗位", "申请医生",
)


def is_metadata_source(source: object, target: str) -> bool:
    """过滤医院报告页眉/页脚的时间、人员和样本信息，避免误写成检验结果。"""
    source_text = short_label(source)
    source_norm = normalized(source_text)
    if target == "报告日期" and source_norm in {normalized("报告日期"), normalized("检验日期")}:
        return False
    return any(word in source_text for word in METADATA_SOURCE_WORDS)


def result_value_is_safe(target: str, value: str) -> bool:
    """检验项目只允许数值/区间或少量明确的分级结果，杜绝英文缩写、时间被写入。"""
    text = clean(value)
    if not text:
        return False
    if target == "姓名":
        return bool(re.fullmatch(r"[\u4e00-\u9fff·]{2,12}", text))
    if target == "年龄":
        return bool(re.fullmatch(r"\d{1,3}", text))
    if target == "性别":
        return text in {"男", "女"}
    if target == "病历号":
        return bool(re.fullmatch(r"[A-Za-z0-9-]{3,32}", text))
    if target == "报告日期":
        return bool(re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text))
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", text):
        return False
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", text):
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_#%.-]{0,20}", text):
        return "等级" in target and bool(re.fullmatch(r"[A-E]", text, re.I))
    return bool(re.fullmatch(r"[<>≤≥]?\s*\d+(?:\.\d+)?(?:\s*[-~至]\s*\d+(?:\.\d+)?)?%?", text))


def clean(value: object) -> str:
    return "" if value is None else str(value).strip().replace("\u3000", " ")


def normalized(value: object) -> str:
    text = clean(value).lower().replace("\n", "")
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    return re.sub(r"[\s:：_\-*★↑↓【】\[\]/]", "", text)


OCR_MEDICAL_LABEL_CORRECTIONS = {
    "25轻维生素d": "25羟维生素d",
    "抗缬勒管激素": "抗缪勒管激素",
    "抗继勒管激素": "抗缪勒管激素",
    "抗穆勒管激素": "抗缪勒管激素",
    "雌烯二酮": "雄烯二酮",
}
MEDICAL_TRAILING_CODES = (
    "lymph", "baso", "mchc", "igf1", "ft3", "ft4", "tsh", "trf", "hgh", "fsh", "amh",
    "wbc", "rbc", "hgb", "hct", "mcv", "mch", "plt", "prl", "vd", "e2", "eo",
)


def medical_label_variants(value: object) -> set[str]:
    """Generate stable medical-label forms for glued codes and recurring OCR glyph errors."""
    text = normalized(short_label(value))
    if not text:
        return set()
    for wrong, correct in OCR_MEDICAL_LABEL_CORRECTIONS.items():
        text = text.replace(wrong, correct)
    variants = {text}
    for suffix in MEDICAL_TRAILING_CODES:
        if text.endswith(suffix) and len(text) > len(suffix):
            variants.add(text[:-len(suffix)])
    # These reports commonly glue one-letter hormone codes directly to the Chinese name.
    if text == "孕酮p":
        variants.add("孕酮")
    if text == "睾酮t":
        variants.add("睾酮")
    if text == "游离三碘甲状腺原氨酸t3":
        variants.add("游离三碘甲状腺原氨酸")
    return {item for item in variants if item}


def medical_alias_keys(value: object) -> set[str]:
    variants = medical_label_variants(value)
    keys: set[str] = set()
    for canonical, aliases in ALIASES.items():
        alias_variants: set[str] = set()
        for alias in aliases:
            alias_variants.update(medical_label_variants(alias))
        if variants.intersection(alias_variants):
            keys.add(normalized(canonical))
    return keys


def canonical_medical_range_key(value: object) -> str:
    """Return the configured canonical field name for a template/OCR label."""
    candidates = medical_alias_keys(value)
    for field in MEDICAL_NORMAL_RANGE_FIELDS:
        if normalized(field) in candidates:
            return field
    return ""


def range_number(value: object) -> float | None:
    """Parse one user-entered range boundary; blanks intentionally disable a side."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalized_medical_normal_ranges(raw_ranges: object, *, strict: bool = False) -> dict[str, dict[str, float | None]]:
    """Validate the persisted/API range shape and keep only supported medical fields."""
    if not isinstance(raw_ranges, dict):
        if strict:
            raise HTTPException(status_code=400, detail="正常范围设置格式错误")
        return {}
    result: dict[str, dict[str, float | None]] = {}
    for raw_key, raw_range in raw_ranges.items():
        key = canonical_medical_range_key(raw_key) or clean(raw_key)
        if key not in MEDICAL_NORMAL_RANGE_FIELDS:
            if strict:
                raise HTTPException(status_code=400, detail=f"不支持设置“{clean(raw_key)}”的正常范围")
            continue
        if not isinstance(raw_range, dict):
            if strict:
                raise HTTPException(status_code=400, detail=f"{key} 的正常范围格式错误")
            continue
        lower_raw, upper_raw = raw_range.get("min"), raw_range.get("max")
        lower, upper = range_number(lower_raw), range_number(upper_raw)
        if lower_raw not in (None, "") and lower is None:
            if strict:
                raise HTTPException(status_code=400, detail=f"{key} 的下限必须是有限数字")
            continue
        if upper_raw not in (None, "") and upper is None:
            if strict:
                raise HTTPException(status_code=400, detail=f"{key} 的上限必须是有限数字")
            continue
        if lower is None and upper is None:
            continue
        if lower is not None and upper is not None and lower > upper:
            if strict:
                raise HTTPException(status_code=400, detail=f"{key} 的下限不能大于上限")
            continue
        result[key] = {"min": lower, "max": upper}
    return result


def load_medical_normal_ranges() -> dict[str, dict[str, float | None]]:
    """Load user settings once saved; otherwise expose verified project defaults."""
    if not MEDICAL_NORMAL_RANGE_CONFIG.exists():
        return {key: dict(value) for key, value in DEFAULT_MEDICAL_NORMAL_RANGES.items()}
    try:
        payload = json.loads(MEDICAL_NORMAL_RANGE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {key: dict(value) for key, value in DEFAULT_MEDICAL_NORMAL_RANGES.items()}
    ranges = normalized_medical_normal_ranges(payload.get("ranges") if isinstance(payload, dict) else payload)
    return ranges


def save_medical_normal_ranges(ranges: dict[str, dict[str, float | None]]) -> None:
    """Persist the full setting atomically so future batches do not need OCR reference values."""
    payload = {
        "version": 1,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ranges": ranges,
    }
    temporary = MEDICAL_NORMAL_RANGE_CONFIG.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(MEDICAL_NORMAL_RANGE_CONFIG)


def normal_range_text(value: dict[str, float | None] | None) -> str:
    if not value:
        return ""
    lower, upper = value.get("min"), value.get("max")
    def formatted(number: float | None) -> str:
        return "" if number is None else f"{number:g}"
    if lower is not None and upper is not None:
        return f"{formatted(lower)}–{formatted(upper)}"
    if lower is not None:
        return f"≥ {formatted(lower)}"
    if upper is not None:
        return f"≤ {formatted(upper)}"
    return ""


def measurement_for_range(value: object) -> tuple[str, float] | None:
    """Read a single numeric result, including a leading comparison operator when present."""
    text = normalize_measurement_text(value)
    match = re.fullmatch(r"\s*(<=|>=|<|>|≤|≥)?\s*(\d+(?:\.\d+)?)\s*%?\s*", text)
    if not match:
        return None
    return (match.group(1) or "", float(match.group(2)))


def medical_range_assessment(header: object, value: object, ranges: dict[str, dict[str, float | None]]) -> dict[str, Any]:
    """Assess only values that are definitely outside the configured numeric interval."""
    key = canonical_medical_range_key(header)
    reference = ranges.get(key) if key else None
    display = normal_range_text(reference)
    assessment: dict[str, Any] = {"range_key": key, "normal_range": display, "is_abnormal": False, "abnormal_reason": ""}
    measurement = measurement_for_range(value)
    if not reference or not measurement:
        return assessment
    operator, measured = measurement
    lower, upper = reference.get("min"), reference.get("max")
    # A comparison result can be indeterminate. Mark it only when every possible
    # value represented by the result lies outside the configured range.
    below = lower is not None and (
        measured < lower if operator in {"", "<="} else measured <= lower if operator == "<" else False
    )
    above = upper is not None and (
        measured > upper if operator in {"", ">="} else measured >= upper if operator == ">" else False
    )
    if below:
        assessment.update(is_abnormal=True, abnormal_reason="低于正常范围")
    elif above:
        assessment.update(is_abnormal=True, abnormal_reason="高于正常范围")
    return assessment


def short_label(value: object) -> str:
    return re.sub(r"[（(].*?[）)]", "", clean(value).split("\n")[0]).strip()


def safe_relative(relative_path: str, fallback: str) -> Path:
    parts = [part for part in PurePosixPath(relative_path or fallback).parts if part not in {"", ".", "..", "/", "\\"}]
    return Path(*parts) if parts else Path(fallback)


def is_sequence(value: str) -> bool:
    match = re.fullmatch(r"(\d{1,3})[、.]?", clean(value))
    return bool(match and int(match.group(1)) <= 99)


def looks_like_label(value: str) -> bool:
    text = clean(value).lstrip("*↑↓ ")
    if not text or normalized(text) in {normalized(item) for item in SKIP_LABELS}:
        return False
    if is_sequence(text) or re.fullmatch(r"[<>]?\d+(?:\.\d+)?%?", text):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", text))


def normalize_measurement_text(raw_value: object) -> str:
    """Normalize common OCR punctuation noise without changing the numeric content."""
    value = clean(raw_value).lstrip("*↑↓ ")
    value = re.sub(r"\s*[↑↓]+\s*$", "", value)
    value = re.sub(r"\s+[HhLl]\s*$", "", value)
    # Range separators are often duplicated or read as a full-width dash / Chinese “一”.
    value = re.sub(r"(?<=\d)\s*[-—–－~～至一]{1,3}\s*(?=\d)", "-", value)
    return value


def result_only(label: str, raw_value: str) -> str:
    """实验室结果只取前置实测值，不把紧随其后的参考范围/指标说明写入模板。"""
    value = normalize_measurement_text(raw_value)
    if not value or value.replace("_", "") == "" or value.lower() in {"null", "none", "nan", "-", "—"}:
        return ""
    date = re.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", value)
    if date:
        return date.group(0).replace("/", "-").replace(".", "-")
    # 数值后面常跟单位和参考范围，如“2.23 nmol/L <0.32-1.91”；模板已有单位，写入数值即可。
    numeric = re.match(r"^([<>≤≥]?\s*\d+(?:\.\d+)?)\b", value)
    if numeric and (re.search(r"[A-Za-z\u4e00-\u9fff%*/]", value[numeric.end():]) or re.search(r"[<>≤≥]\s*\d", value[numeric.end():])):
        return numeric.group(1).replace(" ", "")
    if numeric and normalized(label) in {"年龄", "病历号"}:
        return numeric.group(1).replace(" ", "")
    # 非数值结果（女、A 级等）去掉后续的解释说明。
    return re.split(r"[；;]|(?<=级)[：:]|参考范围|正常范围", value, maxsplit=1)[0].strip()


def put_field(fields: dict[str, str], label: str, raw_value: str) -> None:
    label = re.sub(r"^\d{1,3}(?:[、.]|\s+)+", "", clean(label)).rstrip("：:")
    value = result_only(label, raw_value)
    if looks_like_label(label) and value and len(value) <= 80:
        fields.setdefault(label, value)


def looks_like_measurement(value: str) -> bool:
    """数值结果可带升降箭头、比较符、单位；排除项目序号。"""
    text = normalize_measurement_text(value)
    return bool(
        re.match(
            r"^[<>≤≥]?\s*\d+(?:\.\d+)?(?:\s*[-~至]\s*\d+(?:\.\d+)?)*(?=\s|$|[%*/↑↓])",
            text,
        )
    )


def looks_like_project_label(value: str) -> bool:
    """Project names need real Chinese content; units such as ng/mL are not labels."""
    text = clean(value).lstrip("*↑↓ ")
    if not looks_like_label(text) or is_metadata_source(text, ""):
        return False
    if medical_alias_keys(text):
        return True
    return len(re.findall(r"[\u3400-\u9fff]", text)) >= 2


def table_result_after(values: list[str], label_index: int) -> str:
    """从项目名后向右取实测结果；跳过英文缩写、单位和参考范围。"""
    following = []
    for position in range(label_index + 1, len(values)):
        value = values[position]
        # A new sequence starts only when the number is followed by another Chinese project.
        # Integer results such as RBC=4, EO%=5 or score=98 must remain valid measurements.
        if (
            position > label_index + 1
            and is_sequence(value)
            and position + 1 < len(values)
            and looks_like_project_label(values[position + 1])
        ):
            break
        following.append(value)
    for value in following:
        if looks_like_measurement(value):
            return result_only("", value)
    # 只有字段明确表示等级/分级时，才允许采用 A/B/C/D 这类短文本。
    # 普通检验项紧随其后的 TRF、VD、IGF1 等是项目英文缩写，不是实测值。
    label = clean(values[label_index]) if 0 <= label_index < len(values) else ""
    if following and re.search(r"等级|分级|级别|评级|分类", label):
        candidate = clean(following[0])
        if re.fullmatch(r"(?:[A-Da-d][+-]?|[ⅠⅡⅢⅣⅤ]+|正常|异常|阴性|阳性)", candidate):
            return candidate
    return ""


def valid_person_name(value: object) -> str:
    candidate = re.sub(r"\s+", "", clean(value)).strip("_＿—-：:")
    if candidate in {"", "无", "未签", "未填写"} or "_" in candidate or "＿" in candidate:
        return ""
    if any(word in candidate for word in ("姓名", "调查", "日期", "编号", "签字", "签名", "受试者", "研究者", "患者", "性别", "年龄", "报告", "检验", "访视")):
        return ""
    return candidate if re.fullmatch(r"[\u3400-\u9fff·]{2,8}", candidate) else ""


def extract_person_name_candidates(text: str) -> list[tuple[str, str]]:
    """提取打印姓名和受试者签字；排除研究者签字、空白线及粘连的下一字段。"""
    normalized_text = clean(text).replace("\r", "\n")
    terminator = r"(?=\s*(?:调查日期|报告日期|访视号|性别|别[：:]?|年龄|龄[：:]?|病历号|病床号|样本编号|采样时间|日期|[，,；;。|<>\n]|$))"
    patterns = [
        ("姓名", rf"(?<!研究者)(?:(?:受试者|患者|受检者)\s*)?姓名\s*[：:]?\s*([\u3400-\u9fff·\s_＿—-]{{2,18}}?){terminator}"),
        ("错列姓名", rf"(?<!姓)(?<!研究者)名\s*[：:]\s*([\u3400-\u9fff·\s_＿—-]{{2,18}}?){terminator}"),
        ("受试者签字", rf"(?:受试者|患者|受检者)\s*(?:签字|签名)\s*[：:]?\s*([\u3400-\u9fff·\s_＿—-]{{2,18}}?){terminator}"),
    ]
    candidates: list[tuple[str, str]] = []
    for source, pattern in patterns:
        for match in re.finditer(pattern, normalized_text):
            name = valid_person_name(match.group(1))
            if name and (name, source) not in candidates:
                candidates.append((name, source))
    return candidates


def choose_person_name(candidates: list[tuple[str, str]]) -> str:
    """跨页加权投票；冲突同分时保持空白，避免把不确定姓名强写入汇总表。"""
    weights = {"云端增强": 4, "裁剪增强": 4, "姓名": 3, "错列姓名": 3, "解析字段": 3, "受试者签字": 2}
    scores: Counter[str] = Counter()
    sources: dict[str, set[str]] = {}
    for raw_name, source in candidates:
        name = valid_person_name(raw_name)
        if name:
            # 固定版式营养问卷的姓名位于第一份文件页眉。后续页的空白签字栏
            # 偶尔会被整页 OCR 幻读成示例姓名，因此首份文件的同类候选加 3 分。
            base_source = source.removeprefix("首份")
            scores[name] += weights.get(base_source, 1) + (3 if source.startswith("首份") else 0)
            sources.setdefault(name, set()).add(source)
    if not scores:
        return ""
    ranking = scores.most_common()
    if len(ranking) > 1 and ranking[0][1] == ranking[1][1]:
        return ""
    if len(ranking) > 1:
        top_name, top_score = ranking[0]
        runner_name, runner_score = ranking[1]
        # 只有一个云端候选以 4:3 压过一个完全不同的本地姓名时，不强行覆盖。
        # 同姓且仅一字差的候选仍由整页增强结果决胜；跨姓/多字冲突留给人工核对。
        different_characters = sum(left != right for left, right in zip(top_name, runner_name)) + abs(len(top_name) - len(runner_name))
        if (
            sources.get(top_name) == {"云端增强"}
            and top_score == weights["云端增强"]
            and runner_score == weights["解析字段"]
            and different_characters >= 2
        ):
            return ""
    return ranking[0][0]


def first_page_name_candidates(candidates: list[tuple[str, str]], page_index: int) -> list[tuple[str, str]]:
    """Mark first-upload candidates so the fixed questionnaire header wins over later-page hallucinations."""
    if page_index != 1:
        return candidates
    return [(name, f"首份{source}") for name, source in candidates]


def extract_person_name(text: str) -> str:
    return choose_person_name(extract_person_name_candidates(text))


def cloud_name_candidates(data: dict[str, Any]) -> list[tuple[str, str]]:
    identity = (data.get("structured") or {}).get("identity") or {}
    names: list[str] = []
    for item in identity.get("name_candidates") or []:
        if isinstance(item, dict):
            name = valid_person_name(item.get("value"))
        else:
            name = valid_person_name(item)
        if name and name not in names:
            names.append(name)
    selected = valid_person_name(identity.get("selected_name"))
    if selected and selected not in names:
        names.append(selected)
    return [(name, "云端增强") for name in names]


def apply_cloud_questionnaire_result(data: dict[str, Any], person: dict[str, Any]) -> None:
    questionnaire = (data.get("structured") or {}).get("questionnaire") or {}
    general = person.setdefault("general", {})
    locations = questionnaire.get("meal_locations") or {}
    field_map = {"breakfast": "早餐地点", "lunch": "午餐地点", "dinner": "晚餐地点"}
    for source_key, target_key in field_map.items():
        result = locations.get(source_key) or {}
        selected = [clean(item) for item in result.get("selected") or [] if clean(item)]
        # 题目后直接填写的 1～4 数字由 Markdown 精确解析，优先级高于图像勾选推断。
        if selected and not general.get(target_key):
            general[target_key] = "、".join(selected)
    sunlight = questionnaire.get("sunlight") or {}
    no_sunlight = any(clean(general.get(key)) in {"0", "无"} for key in ("每周户外日照天数", "每日户外日照时长(小时)", "晒太阳时段"))
    if not no_sunlight:
        for source_key, target_key in (("time", "晒太阳时段"), ("body_parts", "皮肤暴露部位")):
            result = sunlight.get(source_key) or {}
            selected = [clean(item) for item in result.get("selected") or [] if clean(item)]
            if selected and not general.get(target_key):
                general[target_key] = "、".join(selected)
    visual_elements = data.get("visual_elements") or []
    if isinstance(visual_elements, list):
        person.setdefault("checkbox_review", []).extend(item for item in visual_elements if isinstance(item, dict))


def parse_medical_table_rows(rows: list[list[str]], fields: dict[str, str]) -> None:
    in_result_table = False
    pending_growth_hormone = False
    for values in rows:
        if not values:
            continue
        header_text = " ".join(values)
        if "中文名称" in header_text and "结果" in header_text:
            in_result_table = True
            continue
        sequence_positions = [
            index
            for index, value in enumerate(values[:-1])
            if is_sequence(value) and looks_like_project_label(values[index + 1])
        ]
        # Some compact reports omit the complete “中文名称 / 结果” header after OCR, while
        # the data row is still intact (for example 25-羟维生素D). Enter result mode only
        # when a numbered Chinese project has a real measurement to its right.
        if not in_result_table and sequence_positions:
            in_result_table = any(table_result_after(values, index + 1) for index in sequence_positions)
        if in_result_table:
            # 这两项在部分报告中共用 rowspan，OCR 会把中文名、英文名甚至两个结果粘成一格。
            # 先利用 IGF1 / hGH 的固定顺序拆开，再走通用项目解析。
            combined_growth_index = next(
                (
                    index
                    for index, value in enumerate(values)
                    if "类胰岛素样生长因子" in clean(value) and "生长激素" in clean(value)
                ),
                None,
            )
            if combined_growth_index is not None:
                english = clean(values[combined_growth_index + 1]) if combined_growth_index + 1 < len(values) else ""
                result_cell = clean(values[combined_growth_index + 2]) if combined_growth_index + 2 < len(values) else ""
                result_numbers = re.findall(r"[<>≤≥]?\s*\d+(?:\.\d+)?", result_cell)
                result_numbers = [number.replace(" ", "") for number in result_numbers]
                if "IGF1" in english.upper() and result_numbers:
                    if len(result_numbers) >= 2:
                        put_field(fields, "类胰岛素样生长因子", result_numbers[0])
                        put_field(fields, "生长激素", result_numbers[1])
                    else:
                        merged = result_numbers[0]
                        split_values: tuple[str, str] | None = None
                        # 例如“1821.87”实际是 IGF1=182、hGH=1.87；按两项合理量级拆分。
                        if "HGH" in english.upper() and re.fullmatch(r"\d+(?:\.\d+)?", merged):
                            candidates: list[tuple[float, float, str, str]] = []
                            for position in range(2, len(merged) - 1):
                                left, right = merged[:position], merged[position:]
                                try:
                                    left_value, right_value = float(left), float(right)
                                except ValueError:
                                    continue
                                if 50 <= left_value <= 500 and 0 <= right_value < 20:
                                    candidates.append((abs(left_value - 220), right_value, left, right))
                            if candidates:
                                _, _, first, second = min(candidates)
                                split_values = first, second
                        if split_values:
                            put_field(fields, "类胰岛素样生长因子", split_values[0])
                            put_field(fields, "生长激素", split_values[1])
                        else:
                            put_field(fields, "类胰岛素样生长因子", merged)
                            pending_growth_hormone = "HGH" in english.upper()

            if pending_growth_hormone and combined_growth_index is None:
                sequence_index = next((index for index, value in enumerate(values) if is_sequence(value)), None)
                start = (sequence_index + 1) if sequence_index is not None else 0
                next_result = next((clean(value) for value in values[start:] if looks_like_measurement(value)), "")
                if next_result:
                    put_field(fields, "生长激素", next_result)
                    pending_growth_hormone = False

            if sequence_positions:
                for index in sequence_positions:
                    if (
                        index + 1 < len(values)
                        and looks_like_project_label(values[index + 1])
                        and not (
                            "类胰岛素样生长因子" in clean(values[index + 1])
                            and "生长激素" in clean(values[index + 1])
                        )
                    ):
                        result = table_result_after(values, index + 1)
                        if result:
                            put_field(fields, values[index + 1], result)
            elif looks_like_project_label(values[0]) and combined_growth_index is None:
                result = table_result_after(values, 0)
                if result:
                    put_field(fields, values[0], result)


def parse_ocr_excel(content: bytes) -> dict[str, str]:
    """解析云端 result.xlsx 的表格，按真实检验表行提取项目后的实测值。"""
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    fields: dict[str, str] = {}
    all_text: list[str] = []
    for worksheet in workbook.worksheets:
        rows: list[list[str]] = []
        for row in worksheet.iter_rows(values_only=True):
            values = [clean(value) for value in row if clean(value)]
            if not values:
                continue
            rows.append(values)
            all_text.extend(values)
            # 报告基本信息是“字段：值”形式，表格内容不会走这一分支。
            for value in values:
                match = re.match(r"^([^：:]{1,80})[：:]\s*(.+)$", value)
                if match:
                    put_field(fields, match.group(1), match.group(2))
        parse_medical_table_rows(rows, fields)
    workbook.close()
    name = extract_person_name(" ".join(all_text))
    if name:
        fields["姓名"] = name
    return fields


def parse_medical_markdown(markdown: str) -> dict[str, str]:
    soup = BeautifulSoup(markdown or "", "html.parser")
    fields: dict[str, str] = {}
    text = soup.get_text(" ", strip=True)
    for label, value in re.findall(r"([^：:\n]{1,40})[：:]\s*([^\s|]+)", text):
        put_field(fields, label, value)
    all_rows = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            values = [clean(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
            if values:
                rows.append(values)
        parse_medical_table_rows(rows, fields)
        all_rows.extend(rows)
    name = extract_person_name(text + " " + " ".join(" ".join(row) for row in all_rows))
    if name:
        fields["姓名"] = name
    return fields


def parse_medical_page_fields(excel_content: bytes, markdown_text: str = "", parse_mode: str = "markdown") -> dict[str, str]:
    """Merge one saved cloud OCR Excel/Markdown pair using the same rules as a live job."""
    excel_fields = parse_ocr_excel(excel_content)
    if parse_mode == "markdown" and markdown_text:
        markdown_fields = parse_medical_markdown(markdown_text)
        return {**excel_fields, **{key: value for key, value in markdown_fields.items() if value}}
    return excel_fields


def value_for_header(header: object, fields: dict[str, str]) -> tuple[str, str]:
    label, target = short_label(header), normalized(short_label(header))
    if not target or target == "序号":
        return "", ""
    # 模板常写成“生长激素 hGH (ng/mL)”。中文主名称是严格匹配依据；英文缩写只能辅助确认，
    # 不能把另一个含同样词尾的项目（如类胰岛素样生长因子）匹配过来。
    target_main = normalized(re.sub(r"\s+[A-Za-z][A-Za-z0-9_#%.-]*$", "", label))
    target_variants = medical_label_variants(label) | {item for item in {target, target_main} if item}
    target_alias_keys = medical_alias_keys(label)
    candidates: list[tuple[int, str, str]] = []
    for source, value in fields.items():
        source_norm = normalized(source)
        source_variants = medical_label_variants(source) | {source_norm}
        # 序号、单独的数字和参考范围绝不能作为字段名参与匹配。
        if len(source_norm) < 2 or not re.search(r"[a-z\u4e00-\u9fff]", source_norm):
            continue
        if is_metadata_source(source, label):
            continue
        score = 0
        if source_variants.intersection(target_variants):
            score = 100
        elif any(
            len(source_variant) >= 4
            and len(target_variant) >= 4
            and (source_variant in target_variant or target_variant in source_variant)
            and abs(len(source_variant) - len(target_variant)) <= 2
            for source_variant in source_variants
            for target_variant in target_variants
        ):
            score = 82
        if target_alias_keys.intersection(medical_alias_keys(source)):
            score = max(score, 98)
        if score and result_value_is_safe(label, value):
            candidates.append((score, source, value))
    if not candidates:
        return "", ""
    _, source, value = max(candidates, key=lambda item: (item[0], len(normalized(item[1]))))
    return value, source


def detect_header_row(worksheet) -> int:
    best_row, best_count = 1, 0
    for number, row in enumerate(worksheet.iter_rows(min_row=1, max_row=min(30, worksheet.max_row), values_only=True), start=1):
        count = sum(bool(clean(value)) for value in row)
        if count > best_count:
            best_row, best_count = number, count
    return best_row


def first_empty_data_row(worksheet, header_row: int, headers: list[object]) -> int:
    serial_index = next((index + 1 for index, value in enumerate(headers) if clean(value) == "序号"), None)
    for number in range(header_row + 1, max(worksheet.max_row + 2, header_row + 2)):
        values = [clean(worksheet.cell(number, col).value) for col in range(1, len(headers) + 1) if col != serial_index]
        if not any(values):
            return number
    return worksheet.max_row + 1


def cloud_api_url(ocr_url: str) -> str:
    url = ocr_url.strip().rstrip("/")
    return url if url.endswith("/parse-file") else f"{url}/parse-file"


def request_cloud_ocr(
    state: dict[str, Any],
    ocr_url: str,
    source_path: Path,
    *,
    document_kind: str,
    page_index: int,
) -> requests.Response:
    """上传单页并对公网映射的短暂 TLS/连接中断自动重试。

    每次重试都会重新打开 PDF，避免第一次上传中断后复用已读完的文件流。
    OCR 接口按文件独立处理，未拿到 HTTP 响应时的重传不会影响已完成页。
    """
    request_url = cloud_api_url(ocr_url)
    request_data = {
        "processing_mode": state.get("processing_mode", "accurate"),
        "document_kind": document_kind,
        "page_index": str(page_index),
        "include_assets": "false",
    }
    last_error: requests.RequestException | None = None
    for attempt in range(1, CLOUD_OCR_MAX_ATTEMPTS + 1):
        try:
            with source_path.open("rb") as payload:
                response = requests.post(
                    request_url,
                    files={"file": (source_path.name, payload, "application/pdf")},
                    data=request_data,
                    timeout=CLOUD_OCR_TIMEOUT,
                )
            if response.status_code not in {429, 502, 503, 504}:
                return response
            last_error = requests.HTTPError(f"云端暂时返回 HTTP {response.status_code}")
        except requests.RequestException as error:
            last_error = error

        if attempt == CLOUD_OCR_MAX_ATTEMPTS:
            break
        delay = CLOUD_OCR_RETRY_DELAYS[min(attempt - 1, len(CLOUD_OCR_RETRY_DELAYS) - 1)]
        state.update(
            message=(
                f"云端连接短暂中断，正在重试 {source_path.name} "
                f"（第 {attempt + 1}/{CLOUD_OCR_MAX_ATTEMPTS} 次，{delay} 秒后继续）"
            )
        )
        time.sleep(delay)

    detail = str(last_error or "未知连接错误")
    raise RuntimeError(
        f"{source_path.name} 连续 {CLOUD_OCR_MAX_ATTEMPTS} 次未能连接云端 OCR：{detail}"
    ) from last_error


def normalize_processing_mode(processing_mode: object) -> str:
    """Keep old clients accurate by default and reject unsupported mode names."""
    mode = clean(processing_mode).lower() or "accurate"
    if mode not in {"fast", "accurate"}:
        raise HTTPException(status_code=400, detail="processing_mode 仅支持 fast 或 accurate")
    return mode


def file_url(job_id: str, path: Path) -> str:
    return f"/local-files/{job_id}/{path.as_posix()}"


def timestamped_filename(stem: str, suffix: str = ".xlsx") -> str:
    return f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"


def report_filename_stem(person: dict[str, Any]) -> str:
    """Return a Windows-safe, human-readable base name for a single-person report."""
    general = person.get("general") if isinstance(person.get("general"), dict) else {}
    candidate = clean(general.get("姓名")) or clean(person.get("id")) or "未命名受访者"
    candidate = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", candidate).strip(" ._")
    return (candidate or "未命名受访者")[:80]


def cached_medical_template_status() -> dict[str, Any]:
    # 兼容本次升级前已完成的体检任务：首次打开页面时将最近一次体检回写所用模板迁移为默认模板。
    if not LAST_MEDICAL_TEMPLATE.exists():
        candidates: list[Path] = []
        for job_dir in JOB_ROOT.iterdir():
            if not job_dir.is_dir() or not any((job_dir / "output").glob("*已自动填写*.xlsx")):
                continue
            candidates.extend((job_dir / "input").glob("*.xlsx"))
            candidates.extend((job_dir / "input").glob("*.xlsm"))
        if candidates:
            latest = max(candidates, key=lambda item: item.stat().st_mtime)
            save_as_last_medical_template(latest, latest.name)
    if not LAST_MEDICAL_TEMPLATE.exists():
        return {"exists": False}
    metadata: dict[str, Any] = {}
    try:
        metadata = json.loads(LAST_MEDICAL_TEMPLATE_META.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "exists": True,
        "filename": metadata.get("filename") or LAST_MEDICAL_TEMPLATE.name,
        "saved_at": metadata.get("saved_at") or datetime.fromtimestamp(LAST_MEDICAL_TEMPLATE.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        "path": str(LAST_MEDICAL_TEMPLATE),
    }


def save_as_last_medical_template(source_path: Path, original_name: str) -> None:
    shutil.copy2(source_path, LAST_MEDICAL_TEMPLATE)
    LAST_MEDICAL_TEMPLATE_META.write_text(
        json.dumps({"filename": original_name, "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False),
        encoding="utf-8",
    )


def annotate_review_field(field: dict[str, Any], ranges: dict[str, dict[str, float | None]]) -> None:
    field.update(medical_range_assessment(field.get("header"), field.get("value"), ranges))


def create_review_fields(
    headers: list[object], fields: dict[str, str], ranges: dict[str, dict[str, float | None]] | None = None
) -> list[dict[str, Any]]:
    ranges = load_medical_normal_ranges() if ranges is None else ranges
    review = []
    for header in headers:
        title = clean(header)
        if not title or title == "序号":
            continue
        value, source = value_for_header(title, fields)
        field: dict[str, Any] = {"header": title, "source": source, "value": value}
        annotate_review_field(field, ranges)
        review.append(field)
    return review


def apply_medical_range_style(cell: Any, is_abnormal: bool, original_cell: Any | None = None) -> None:
    """Tint abnormal Excel values red without changing the configured result itself."""
    if not is_abnormal:
        if original_cell is not None:
            cell.font = copy(original_cell.font)
            cell.fill = copy(original_cell.fill)
        return
    font = copy(cell.font)
    font.color = "FFFF0000"
    font.bold = True
    cell.font = font
    cell.fill = PatternFill("solid", fgColor="FFFFE5E5")


def process_job(
    job_id: str,
    ocr_url: str,
    template_path: Path,
    groups: dict[str, list[Path]],
    parse_mode: str,
    processing_mode: str = "accurate",
) -> None:
    state = JOBS[job_id]
    try:
        state.update(status="processing", message="正在读取汇总模板…")
        workbook = load_workbook(template_path)
        worksheet = workbook.active
        header_row = detect_header_row(worksheet)
        headers = [worksheet.cell(header_row, column).value for column in range(1, worksheet.max_column + 1)]
        normal_ranges = load_medical_normal_ranges()
        people = []
        ocr_root = state["job_dir"] / "ocr_excel"
        for person, page_paths in sorted(groups.items()):
            person_fields: dict[str, str] = {}
            person_name_candidates: list[tuple[str, str]] = []
            saved_excels: list[str] = []
            saved_markdowns: list[str] = []
            person_dir = ocr_root / safe_relative(person, "unknown")
            person_dir.mkdir(parents=True, exist_ok=True)
            for page_number, source_path in enumerate(page_paths, start=1):
                state.update(current_file=source_path.name, current_person=person, message=f"正在识别 {person} / {source_path.name}")
                response = request_cloud_ocr(
                    state,
                    ocr_url,
                    source_path,
                    document_kind="medical",
                    page_index=page_number,
                )
                try:
                    data = response.json()
                except ValueError as error:
                    raise RuntimeError(f"{source_path.name} 的云端响应不是 JSON：{response.text[:160]}") from error
                if not response.ok or not data.get("success") or not data.get("excel"):
                    raise RuntimeError(f"{source_path.name} OCR 失败：{data.get('detail') or response.status_code}")
                excel_bytes = base64.b64decode(data["excel"])
                excel_relative = Path("ocr_excel") / safe_relative(person, "unknown") / f"{page_number:02d}_{source_path.stem}_ocr.xlsx"
                excel_path = state["job_dir"] / excel_relative
                excel_path.parent.mkdir(parents=True, exist_ok=True)
                excel_path.write_bytes(excel_bytes)
                saved_excels.append(file_url(job_id, excel_relative))
                markdown_text = str(data.get("markdown") or "")
                person_name_candidates.extend(extract_person_name_candidates(markdown_text))
                person_name_candidates.extend(cloud_name_candidates(data))
                markdown_relative = Path("ocr_markdown") / safe_relative(person, "unknown") / f"{page_number:02d}_{source_path.stem}_ocr.md"
                markdown_path = state["job_dir"] / markdown_relative
                markdown_path.parent.mkdir(parents=True, exist_ok=True)
                markdown_path.write_text(markdown_text, encoding="utf-8")
                saved_markdowns.append(file_url(job_id, markdown_relative))
                parsed_fields = parse_medical_page_fields(excel_bytes, markdown_text, parse_mode)
                for key, value in parsed_fields.items():
                    if normalized(key) == normalized("姓名"):
                        name = valid_person_name(value)
                        if name:
                            person_name_candidates.append((name, "解析字段"))
                    else:
                        person_fields.setdefault(key, value)
                state["completed_files"] += 1
            selected_name = choose_person_name(person_name_candidates)
            if selected_name:
                person_fields["姓名"] = selected_name
            target_row = first_empty_data_row(worksheet, header_row, headers)
            review_fields = create_review_fields(headers, person_fields, normal_ranges)
            for column, field in enumerate(review_fields, start=1):
                # review_fields 排除了“序号”，需按实际标题找列，避免列号偏移。
                actual_column = next(index + 1 for index, value in enumerate(headers) if clean(value) == field["header"])
                if field["value"]:
                    target_cell = worksheet.cell(target_row, actual_column)
                    target_cell.value = field["value"]
                    apply_medical_range_style(target_cell, bool(field["is_abnormal"]))
            people.append({"id": person, "row": target_row, "page_count": len(page_paths), "ocr_files": saved_excels, "markdown_files": saved_markdowns, "fields": person_fields, "review_fields": review_fields})
        output_relative = Path("output") / timestamped_filename(f"{template_path.stem}_已自动填写")
        output_path = state["job_dir"] / output_relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output_path)
        workbook.close()
        state.update(status="completed", header_row=header_row, people=people, output_relative=output_relative, output_url=file_url(job_id, output_relative), message=f"已处理 {len(people)} 名受检者；可逐人核对、修改后再保存下载。")
    except Exception as error:
        state.update(status="failed", message=str(error))


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/test-ocr")
def test_ocr(ocr_url: Annotated[str, Form()]):
    try:
        response = requests.get(cloud_api_url(ocr_url).removesuffix("/parse-file") + "/", timeout=15)
        response.raise_for_status()
        return {"success": True, "message": "云端 OCR 服务连接正常"}
    except requests.RequestException as error:
        raise HTTPException(status_code=502, detail=f"无法连接云端 OCR：{error}") from error


@app.post("/process", status_code=202)
def process_reports(
    background_tasks: BackgroundTasks,
    ocr_url: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    relative_paths: Annotated[list[str], Form()],
    template: UploadFile | None = File(None),
    parse_mode: str = Form("markdown"),
    processing_mode: str = Form("accurate"),
):
    processing_mode = normalize_processing_mode(processing_mode)
    if template and template.filename and not template.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="汇总模板仅支持 xlsx 或 xlsm")
    if not (template and template.filename) and not LAST_MEDICAL_TEMPLATE.exists():
        raise HTTPException(status_code=400, detail="请先上传 xlsx 或 xlsm 汇总模板；之后系统会自动记住该模板")
    if not files or len(files) != len(relative_paths):
        raise HTTPException(status_code=400, detail="报告文件与目录信息不一致，请重新选择 PDF 或文件夹")
    job_id, job_dir = uuid.uuid4().hex, JOB_ROOT / uuid.uuid4().hex
    # 目录名使用 job_id，避免输入文件名造成路径冲突。
    job_dir = JOB_ROOT / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    if template and template.filename:
        template_name = Path(template.filename).name
        template_path = input_dir / template_name
        with template_path.open("wb") as target:
            shutil.copyfileobj(template.file, target)
        save_as_last_medical_template(template_path, template_name)
    else:
        cached = cached_medical_template_status()
        template_name = Path(str(cached["filename"])).name
        template_path = input_dir / template_name
        shutil.copy2(LAST_MEDICAL_TEMPLATE, template_path)
    groups: dict[str, list[Path]] = defaultdict(list)
    for index, pdf in enumerate(files):
        relative = relative_paths[index] or pdf.filename or f"report_{index + 1}.pdf"
        safe_path = safe_relative(relative, pdf.filename or f"report_{index + 1}.pdf")
        source_path = input_dir / "reports" / safe_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("wb") as target:
            shutil.copyfileobj(pdf.file, target)
        parent = str(safe_path.parent).replace("\\", "/")
        person = parent if parent != "." else source_path.stem
        groups[person].append(source_path)
    JOBS[job_id] = {"parse_mode": parse_mode, "processing_mode": processing_mode, "template_name": template_name, "template_path": template_path, "status": "queued", "job_dir": job_dir, "total_files": len(files), "completed_files": 0, "current_file": "", "current_person": "", "message": "文件已上传到本机，等待开始识别…", "people": []}
    background_tasks.add_task(process_job, job_id, ocr_url, template_path, dict(groups), parse_mode, processing_mode)
    return {"success": True, "job_id": job_id, "total_files": len(files), "people_count": len(groups)}


@app.get("/medical-template-status")
def medical_template_status():
    return cached_medical_template_status()


@app.get("/medical-normal-ranges")
def medical_normal_ranges():
    ranges = load_medical_normal_ranges()
    return {
        "ranges": ranges,
        "items": [
            {"key": key, "label": key, "min": ranges.get(key, {}).get("min"), "max": ranges.get(key, {}).get("max")}
            for key in MEDICAL_NORMAL_RANGE_FIELDS
        ],
        "source": "saved" if MEDICAL_NORMAL_RANGE_CONFIG.exists() else "project_defaults",
    }


@app.put("/medical-normal-ranges")
def update_medical_normal_ranges(payload: dict[str, Any]):
    ranges = normalized_medical_normal_ranges(payload.get("ranges"), strict=True)
    save_medical_normal_ranges(ranges)
    return {"success": True, "message": "正常范围默认值已保存，之后的体检批次会直接使用这些范围。", "ranges": ranges}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    state = JOBS.get(job_id) or recover_nutrition_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="任务不存在或本地服务已重启")
    return {key: value for key, value in state.items() if key not in {"job_dir", "output_relative", "template_path"}}


@app.post("/jobs/{job_id}/save-review")
def save_review(job_id: str, payload: dict[str, Any]):
    state = JOBS.get(job_id)
    if not state or state.get("status") != "completed":
        raise HTTPException(status_code=409, detail="任务尚未完成，无法保存人工修改")
    people = payload.get("people")
    if not isinstance(people, list):
        raise HTTPException(status_code=400, detail="缺少核对数据")
    output_path = state["job_dir"] / state["output_relative"]
    workbook = load_workbook(output_path)
    worksheet = workbook.active
    template_workbook = load_workbook(state["template_path"])
    template_worksheet = template_workbook.active
    headers = [worksheet.cell(state["header_row"], column).value for column in range(1, worksheet.max_column + 1)]
    column_by_header = {clean(value): index + 1 for index, value in enumerate(headers) if clean(value)}
    ranges = load_medical_normal_ranges()
    for person in people:
        row = person.get("row")
        for field in person.get("review_fields", []):
            column = column_by_header.get(clean(field.get("header")))
            if row and column:
                target_row = int(row)
                target_cell = worksheet.cell(target_row, column)
                target_cell.value = clean(field.get("value")) or None
                annotate_review_field(field, ranges)
                apply_medical_range_style(
                    target_cell,
                    bool(field["is_abnormal"]),
                    template_worksheet.cell(target_row, column),
                )
    workbook.save(output_path)
    workbook.close()
    template_workbook.close()
    state["people"] = people
    return {"success": True, "message": "人工修改已保存到汇总 Excel", "output_url": state["output_url"], "people": people}


# ========================== 食物频率调查独立流程 ==========================

def append_nutrition_note(existing: object, note: object) -> str:
    current = clean(existing)
    candidate = clean(note)
    if not candidate:
        return current
    parts = [part.strip() for part in current.split("；") if part.strip()]
    if candidate not in parts:
        parts.append(candidate)
    return "；".join(parts)


def nutrition_food_note_requires_review(value: object) -> bool:
    """Treat provenance and deterministic zero-to-not-eat normalization as informational."""
    parts = [part.strip() for part in clean(value).split("；") if part.strip()]
    informational = (
        "OCR项目原文：",
        "仅识别到 0（",
        "食用量为 0，按不吃处理",
        "数量约",
        "数量栏最终可读作",
        "每天格仅有淡污点",
        "OCR报告的另一个",
        "每周和每月区域的旧值",
    )
    return any(not part.startswith(informational) for part in parts)


def canonical_supplement_name(value: object) -> str:
    text = clean(value)
    compact = re.sub(r"[\s（）()：:·._-]", "", text).lower()
    if "维生素d" in compact:
        return "维生素D"
    if compact.startswith("钙"):
        return "钙"
    if "鱼油" in compact:
        return "鱼油"
    if "酵素" in compact:
        return "酵素"
    if "其他保健品" in compact or "蛋白粉" in compact:
        return "其他保健品(如蛋白粉)"
    return ""


def normalize_nutrition_quantity(value: object) -> tuple[str, list[str]]:
    """Remove printed unit placeholders while preserving handwritten free-form quantities."""
    raw = clean(value)
    if not raw:
        return "", []
    text = raw.replace("ＭＬ", "ml").replace("ｍｌ", "ml").replace("ML", "ml")
    text = re.sub(r"\s+(?=(?:kg|mg|ml|g|L|l|克|千克|毫升|升|勺|个|只|粒|片|瓶|杯)\b)", "", text, flags=re.I)
    unit_only = r"(?:kg|mg|ml|g|L|l|克|千克|毫升|升|勺|个|只|粒|片|瓶|杯)"
    if re.fullmatch(unit_only, text, re.I):
        return "", []
    if re.fullmatch(r"[./·—_\-~～]+", text):
        return "", [f"食用量仅识别到符号“{raw}”"]
    notes: list[str] = []
    numeric_tokens = re.findall(r"\d+(?:\.\d+)?", text)
    if len(numeric_tokens) >= 2 and not re.search(r"[-~～至×xX*/]", text):
        notes.append(f"食用量疑似粘连“{raw}”")
    for token in numeric_tokens:
        try:
            if float(token) > 1500:
                notes.append(f"食用量疑似异常“{raw}”")
                break
        except ValueError:
            pass
    return text, notes


def nutrition_count_value(value: object) -> str:
    text = clean(value).replace("～", "-").replace("~", "-").replace("—", "-")
    text = re.sub(r"\s+", "", text).replace("^", "-")
    text = re.sub(r"次$", "", text)
    if re.fullmatch(r"\d+\.", text):
        text = text[:-1]
    if text in {"无", "不吃"}:
        return "0"
    if re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?", text):
        return text
    return ""


def choose_nutrition_period(raw_values: list[object]) -> tuple[str, str, list[str]]:
    values = [clean(value) for value in (raw_values + [""] * 5)[:5]]
    positive: list[tuple[str, str, str]] = []
    zero_sources: list[str] = []
    not_eat_sources: list[str] = []
    ignored: list[str] = []
    for period, raw in zip(NUTRITION_PERIODS, values):
        if not raw:
            continue
        if period == "不吃":
            compact = re.sub(r"\s+", "", raw)
            if compact in {"无", "不吃", "✓", "√", "✔", "☑"} or re.fullmatch(r"0(?:[.,]0*)?", compact):
                not_eat_sources.append(f"不吃列“{raw}”")
            else:
                ignored.append(f"不吃列“{raw}”")
            continue
        count = nutrition_count_value(raw)
        if count and all(float(item) == 0 for item in re.findall(r"\d+(?:\.\d+)?", count)):
            zero_sources.append(f"{period}列“{raw}”")
        elif count:
            positive.append((period, count, raw))
        else:
            ignored.append(f"{period}列“{raw}”")
    notes = [f"频率列疑似错位：{item}" for item in ignored]
    if len(positive) == 1:
        period, count, _ = positive[0]
        if zero_sources or not_eat_sources:
            notes.append(f"唯一正数与零/不吃标记并存，采用{period}={count}，请核对")
        limits = {"每天": 10, "每周": 21, "每月": 31, "每年": 365}
        if any(float(item) > limits[period] for item in re.findall(r"\d+(?:\.\d+)?", count)):
            notes.append(f"{period}次数疑似异常“{count}”")
        return period, count, notes
    if len(positive) > 1:
        display = "、".join(f"{period}={raw}" for period, _, raw in positive)
        notes.append(f"多个频率列同时有正数：{display}")
        return "未识别", "", notes
    if zero_sources or not_eat_sources:
        sources = "、".join(zero_sources + not_eat_sources)
        if zero_sources and not not_eat_sources:
            notes.append(f"仅识别到 0（{sources}），按不吃处理")
        return "不吃", "0", notes
    return "未识别", "", notes


def normalize_food_row(code: str, raw_name: object, quantity: object, period_values: list[object], raw_line: str) -> dict[str, str] | None:
    canonical = NUTRITION_FOOD_ITEMS.get(clean(code))
    if not canonical:
        return None
    raw_name_text = clean(raw_name)
    notes: list[str] = []
    if raw_name_text and normalized(raw_name_text) != normalized(canonical):
        notes.append(f"OCR项目原文：{raw_name_text}")
    clean_quantity, quantity_notes = normalize_nutrition_quantity(quantity)
    notes.extend(quantity_notes)
    period, count, period_notes = choose_nutrition_period(period_values)
    notes.extend(period_notes)
    if period == "未识别" and re.fullmatch(
        r"0(?:\.0+)?(?:kg|mg|ml|g|L|l|克|千克|毫升|升|勺|个|只|粒|片|瓶|杯)?",
        clean_quantity,
        re.I,
    ):
        period, count = "不吃", "0"
        notes.append("食用量为 0，按不吃处理")
    if period in NUTRITION_PERIODS[:4]:
        if not re.search(r"\d", clean_quantity):
            notes.append("已识别进食频率，但食用量没有有效数字")
        elif not re.search(r"(?:kg|mg|ml|g|L|l|克|千克|毫升|升|勺|个|只|粒|片|瓶|杯)", clean_quantity, re.I):
            notes.append(f"食用量未识别到单位“{clean_quantity}”")
    return {
        "食物编号": clean(code), "食物名称": canonical, "平均每次食用量": clean_quantity,
        "次数": "0" if period == "不吃" else count, "频率周期(请核对)": period,
        "是否不吃": "是" if period == "不吃" else "", "OCR原始行": raw_line,
        "人工核对备注": "；".join(dict.fromkeys(note for note in notes if note)),
    }


def split_nutrition_food_cells(values: list[object]) -> tuple[object, list[object]]:
    """Keep fixed columns 1-6; OCR sometimes appends an extra empty cell after 不吃."""
    padded = list(values)
    if len(padded) < 7:
        padded.extend([""] * (7 - len(padded)))
    not_eat_cells = [clean(item) for item in padded[6:] if clean(item)]
    accepted_not_eat = next(
        (item for item in not_eat_cells if re.sub(r"\s+", "", item) in {"0", "0.0", "无", "不吃", "✓", "√", "✔", "☑"}),
        not_eat_cells[0] if not_eat_cells else "",
    )
    return padded[1], [*padded[2:6], accepted_not_eat]


def split_nutrition_supplement_cells(values: list[object]) -> list[object]:
    """Return category/name/quantity/five periods/note using the stable right edge of the table."""
    padded = list(values)
    if len(padded) < 9:
        padded.extend([""] * (9 - len(padded)))
    trailing = padded[-6:]
    prefix = padded[:-6]
    category = prefix[0] if prefix else ""
    product = prefix[1] if len(prefix) > 1 else ""
    quantity = " ".join(clean(item) for item in prefix[2:] if clean(item))
    return [category, product, quantity, *trailing]


def normalize_supplement_row(values: list[object]) -> dict[str, str] | None:
    values = split_nutrition_supplement_cells(values)
    if not values:
        return None
    raw_category = clean(values[0])
    canonical = canonical_supplement_name(raw_category)
    extra_category = False
    if not canonical:
        if not re.search(r"[\u3400-\u9fff]", raw_category) or any(word in raw_category for word in ("版本", "回忆", "选择", "填写", "次数", "备注")):
            return None
        canonical = "其他保健品(如蛋白粉)"
        extra_category = True
    name = clean(values[1]) if len(values) > 1 else ""
    if extra_category:
        name = " / ".join(item for item in (raw_category, name) if item)
    quantity, quantity_notes = normalize_nutrition_quantity(values[2] if len(values) > 2 else "")
    period, count, period_notes = choose_nutrition_period(list(values[3:8]))
    notes = quantity_notes + period_notes
    if extra_category:
        notes.append(f"OCR发现模板外保健品：{raw_category}")
    if raw_category and normalized(raw_category) != normalized(canonical):
        notes.append(f"OCR种类原文：{raw_category}")
    if "维生素" in raw_category and "钙" in raw_category:
        notes.append("OCR疑似将维生素D与钙合并为一行，钙项目需回查")
    printed_note = clean(values[8]) if len(values) > 8 else ""
    if printed_note:
        notes.append(f"OCR备注：{printed_note}")
    return {
        "保健品种类": canonical, "保健品名称": name, "平均每次服用量": quantity,
        "次数": "0" if period == "不吃" else count, "频率周期(请核对)": period,
        "是否不吃": "是" if period == "不吃" else "", "备注": "；".join(dict.fromkeys(notes)),
    }


def nutrition_row_score(row: dict[str, Any], *, supplement: bool = False) -> int:
    period = clean(row.get("频率周期(请核对)"))
    quantity_key = "平均每次服用量" if supplement else "平均每次食用量"
    note_key = "备注" if supplement else "人工核对备注"
    return (
        (5 if period in NUTRITION_PERIODS else 0)
        + (2 if clean(row.get("次数")) else 0)
        + (2 if clean(row.get(quantity_key)) else 0)
        + (1 if supplement and clean(row.get("保健品名称")) else 0)
        - (1 if "多个频率列" in clean(row.get(note_key)) else 0)
    )


def finalize_nutrition_person(person: dict[str, Any]) -> None:
    """Enforce the fixed questionnaire structure and make every uncertainty reviewable."""
    food_by_code: dict[str, dict[str, Any]] = {}
    discarded_food: list[str] = []
    for row in person.get("food_rows") or []:
        code = clean(row.get("食物编号"))
        if code not in NUTRITION_FOOD_ITEMS:
            if code:
                discarded_food.append(code)
            continue
        row["食物名称"] = NUTRITION_FOOD_ITEMS[code]
        current = food_by_code.get(code)
        if current is None or nutrition_row_score(row) > nutrition_row_score(current):
            food_by_code[code] = row
    final_food: list[dict[str, Any]] = []
    for code, name in NUTRITION_FOOD_ITEMS.items():
        row = food_by_code.get(code)
        if row is None:
            row = {
                "食物编号": code, "食物名称": name, "平均每次食用量": "", "次数": "",
                "频率周期(请核对)": "未识别", "是否不吃": "", "OCR原始行": "",
                "人工核对备注": "OCR 未发现该固定项目",
            }
        final_food.append(row)
    person["food_rows"] = final_food

    supplement_by_name: dict[str, dict[str, Any]] = {}
    for row in person.get("supplement_rows") or []:
        canonical = canonical_supplement_name(row.get("保健品种类"))
        if not canonical:
            continue
        row["保健品种类"] = canonical
        current = supplement_by_name.get(canonical)
        if current is None:
            supplement_by_name[canonical] = row
        elif nutrition_row_score(row, supplement=True) > nutrition_row_score(current, supplement=True):
            row["备注"] = append_nutrition_note(row.get("备注"), f"另一个 OCR 候选：{clean(current.get('保健品名称')) or clean(current.get('备注')) or '空白行'}")
            supplement_by_name[canonical] = row
        else:
            current["备注"] = append_nutrition_note(current.get("备注"), f"另一个 OCR 候选：{clean(row.get('保健品名称')) or clean(row.get('备注')) or '空白行'}")
    merged_vitamin_calcium = any("维生素D与钙合并" in clean(row.get("备注")) for row in supplement_by_name.values())
    final_supplements: list[dict[str, Any]] = []
    for name in NUTRITION_SUPPLEMENT_ITEMS:
        row = supplement_by_name.get(name)
        if row is None:
            row = {
                "保健品种类": name, "保健品名称": "", "平均每次服用量": "", "次数": "",
                "频率周期(请核对)": "未识别", "是否不吃": "", "备注": "OCR 未发现该固定项目",
            }
            if name == "钙" and merged_vitamin_calcium:
                row["备注"] = "OCR 疑似与维生素D合并，需回查原图"
        final_supplements.append(row)
    person["supplement_rows"] = final_supplements

    general = person.setdefault("general", {})
    if discarded_food:
        general["人工备注"] = append_nutrition_note(general.get("人工备注"), f"已排除非食物题号：{'、'.join(sorted(set(discarded_food)))}")
    review_fields = [
        "姓名", "每日餐次", "每周在家吃饭天数", "早餐地点", "午餐地点", "晚餐地点",
        "每周户外日照天数", "每日户外日照时长(小时)", "晒太阳时段", "皮肤暴露部位",
    ]
    missing = [field for field in review_fields if not clean(general.get(field))]
    if missing:
        general["人工备注"] = append_nutrition_note(general.get("人工备注"), f"未自动识别：{'、'.join(missing)}")

def nutrition_blank_person(person_id: str) -> dict[str, Any]:
    general = {column: "" for column in NUTRITION_GENERAL_COLUMNS}
    general["人员文件夹"] = person_id
    return {"id": person_id, "general": general, "food_rows": [], "supplement_rows": [], "ocr_files": [], "markdown_files": [], "json_files": [], "checkbox_review": []}


def nutrition_job_state_path(job_dir: Path) -> Path:
    return job_dir / "nutrition_job_state.json"


def persist_nutrition_job(job_id: str) -> None:
    """Persist completed nutrition UI state so a local-service restart is recoverable."""
    state = JOBS.get(job_id)
    if not state or state.get("kind") != "nutrition" or state.get("status") != "completed":
        return
    job_dir = Path(state["job_dir"])
    payload = {
        key: value
        for key, value in state.items()
        if key not in {"job_dir", "template_path", "output_relative"}
    }
    payload["job_id"] = job_id
    payload["output_relative"] = Path(state.get("output_relative") or Path("output") / state["output_filename"]).as_posix()
    path = nutrition_job_state_path(job_dir)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def recover_nutrition_job(job_id: str) -> dict[str, Any] | None:
    """Recover a completed nutrition job from persisted state or saved OCR artifacts."""
    if not re.fullmatch(r"[0-9a-f]{32}", clean(job_id)):
        return None
    job_dir = JOB_ROOT / job_id
    if not job_dir.is_dir():
        return None

    persisted_path = nutrition_job_state_path(job_dir)
    if persisted_path.is_file():
        try:
            payload = json.loads(persisted_path.read_text(encoding="utf-8"))
            if payload.get("kind") == "nutrition" and isinstance(payload.get("people"), list):
                output_relative = Path(payload.pop("output_relative", Path("output") / payload["output_filename"]))
                state = {**payload, "job_dir": job_dir, "output_relative": output_relative}
                state["output_url"] = file_url(job_id, output_relative)
                JOBS[job_id] = state
                return state
        except (OSError, ValueError, TypeError, KeyError):
            pass

    excel_root = job_dir / "ocr_excel"
    output_dir = job_dir / "output"
    if not excel_root.is_dir() or not output_dir.is_dir():
        return None
    output_candidates = sorted(output_dir.glob("*.xlsx"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not output_candidates:
        return None

    grouped: dict[str, list[Path]] = defaultdict(list)
    for excel_path in sorted(excel_root.rglob("*.xlsx")):
        relative = excel_path.relative_to(excel_root)
        grouped[relative.parent.as_posix()].append(excel_path)
    people: list[dict[str, Any]] = []
    markdown_root, json_root = job_dir / "ocr_markdown", job_dir / "ocr_json"
    for person_id, excel_paths in sorted(grouped.items()):
        person = nutrition_blank_person(person_id)
        name_candidates: list[tuple[str, str]] = []
        for page_number, excel_path in enumerate(excel_paths, start=1):
            relative = excel_path.relative_to(excel_root)
            markdown_relative = relative.with_suffix(".md")
            markdown_path = markdown_root / markdown_relative
            markdown_text = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else ""
            parsed = parse_nutrition_page_fields(excel_path.read_bytes(), markdown_text, "markdown")
            for key, value in parsed["general"].items():
                if key == "姓名":
                    name = valid_person_name(value)
                    if name:
                        name_candidates.extend(first_page_name_candidates([(name, "本地恢复")], page_number))
                elif key == "人工备注" and value:
                    person["general"][key] = append_nutrition_note(person["general"].get(key), value)
                elif value and not person["general"].get(key):
                    person["general"][key] = value
            person["food_rows"].extend(parsed["food_rows"])
            person["supplement_rows"].extend(parsed["supplement_rows"])
            person["ocr_files"].append(file_url(job_id, Path("ocr_excel") / relative))
            if markdown_path.is_file():
                person["markdown_files"].append(file_url(job_id, Path("ocr_markdown") / markdown_relative))
                name_candidates.extend(first_page_name_candidates(extract_person_name_candidates(markdown_text), page_number))
            json_relative = relative.with_suffix(".json")
            json_path = json_root / json_relative
            if json_path.is_file():
                cloud_data = json.loads(json_path.read_text(encoding="utf-8"))
                apply_cloud_questionnaire_result(cloud_data, person)
                name_candidates.extend(first_page_name_candidates(cloud_name_candidates(cloud_data), page_number))
                person["json_files"].append(file_url(job_id, Path("ocr_json") / json_relative))
        selected_name = choose_person_name(name_candidates)
        if selected_name:
            person["general"]["姓名"] = selected_name
        finalize_nutrition_person(person)
        person["page_count"] = len(excel_paths)
        people.append(person)

    if not people or not any(person["food_rows"] for person in people):
        return None
    output_path = output_candidates[0]
    output_relative = output_path.relative_to(job_dir)
    state = {
        "kind": "nutrition", "parse_mode": "markdown", "processing_mode": "recovered",
        "output_filename": output_path.name, "status": "completed", "job_dir": job_dir,
        "total_files": sum(person.get("page_count", 0) for person in people), "completed_files": sum(person.get("page_count", 0) for person in people),
        "current_file": "", "current_person": "", "people": people,
        "output_relative": output_relative, "output_url": file_url(job_id, output_relative),
        "message": f"已从本机保存的 OCR 原件恢复 {len(people)} 名受访者，无需重新调用云端 OCR。",
    }
    JOBS[job_id] = state
    persist_nutrition_job(job_id)
    return state


def parse_nutrition_excel(content: bytes) -> dict[str, Any]:
    """兼容云端将问卷识别为文字行、简化表格或混合表格的 Excel 输出。"""
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    result = {"general": {}, "food_rows": [], "supplement_rows": []}
    mode = ""
    for worksheet in workbook.worksheets:
        for raw_row in worksheet.iter_rows(values_only=True):
            values = [clean(value) for value in raw_row if clean(value)]
            if not values:
                continue
            joined = " ".join(values)
            for source, target in [("受试者编号", "受试者编号"), ("受试者姓名", "姓名"), ("调查日期", "调查日期"), ("访视号", "访视号")]:
                match = re.search(rf"{source}[：:]\s*([^\s，,；;]+)", joined)
                if match and match.group(1) not in {"___", "_"}:
                    result["general"].setdefault(target, match.group(1))
            if "食物名称" in joined and "进食次数" in joined:
                mode = "food"
                continue
            if "营养保健品种类" in joined:
                mode = "supplement"
                continue
            if joined.startswith("7.") or "营养保健品" in joined and "回忆" in joined:
                mode = ""
                continue
            if mode == "food":
                # 云端常输出：1.1米饭 | 50g | 1；频率列位置可能在版面还原时丢失。
                match = re.match(r"^(\d+(?:\.\d+)?)\s*(.+)$", values[0])
                if match and match.group(1) in NUTRITION_FOOD_ITEMS:
                    quantity, quantity_notes = normalize_nutrition_quantity(values[1] if len(values) > 1 else "")
                    count = nutrition_count_value(values[2] if len(values) > 2 else "")
                    result["food_rows"].append({
                        "食物编号": match.group(1), "食物名称": NUTRITION_FOOD_ITEMS[match.group(1)], "平均每次食用量": quantity,
                        # Excel 版常丢失“每天/每周/不吃”所在列；仅凭 0 不能断言为不吃。
                        "次数": count, "频率周期(请核对)": "未识别", "是否不吃": "",
                        "OCR原始行": " | ".join(values),
                        "人工核对备注": "；".join(quantity_notes + (["Excel 结果无法确定频率周期"] if count else [])),
                    })
            elif mode == "supplement":
                if values[0] in {"每天", "每周", "每月", "每年", "不吃", "请选择适当周期填写次数", "填0"}:
                    continue
                canonical = canonical_supplement_name(values[0]) if values else ""
                if canonical and not values[0].startswith("版本号"):
                    only_not_eat = len(values) == 2 and values[1] == "0"
                    quantity, quantity_notes = normalize_nutrition_quantity(values[2] if len(values) > 2 else "")
                    result["supplement_rows"].append({
                        "保健品种类": canonical, "保健品名称": "" if only_not_eat else (values[1] if len(values) > 1 else ""),
                        "平均每次服用量": quantity, "次数": "0" if only_not_eat else nutrition_count_value(values[3] if len(values) > 3 else ""),
                        "频率周期(请核对)": "不吃" if only_not_eat else "未识别", "是否不吃": "是" if only_not_eat else "",
                        "备注": "；".join(quantity_notes + (["Excel 结果无法确定频率周期"] if not only_not_eat else [])),
                    })
    workbook.close()
    return result


def nutrition_numeric_answer(text: str, prompt: str, max_value: float) -> tuple[str, str]:
    answer_pattern = r"(?:无|\d+(?:\.\d+)?(?:\s*[-~～至]\s*\d+(?:\.\d+)?)?)"
    match = re.search(rf"{prompt}[ \t]*[？?]?[ \t_＿—\-]*({answer_pattern})\.?(?=[ \t]|\n|小时|天|餐|饭|[。；;，,]|$)", text, re.I)
    if not match:
        return "", ""
    answer = match.group(1).strip().replace("～", "-").replace("~", "-").replace("至", "-")
    if answer == "无":
        return "0", ""
    values = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", answer)]
    if not values or any(item < 0 or item > max_value for item in values):
        return "", f"“{prompt}”疑似异常值“{answer}”"
    return re.sub(r"\s+", "", answer), ""


def explicitly_marked_options(text: str, options: list[str]) -> list[str]:
    mark = r"[☑✓✔√]"
    selected = []
    for option in options:
        if re.search(rf"(?:{mark}\s*{re.escape(option)}|{re.escape(option)}\s*{mark})", text):
            selected.append(option)
    return selected


def nutrition_general_from_text(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    name = extract_person_name(text)
    if name:
        fields["姓名"] = name
    rules = [
        ("受试者编号", "受试者编号", r"[A-Za-z0-9-]{5,32}"),
        ("调查日期", "调查日期", r"\d{4}[./年-]\d{1,2}[./月-]\d{1,2}日?"),
        ("访视号", "访视号", r"[A-Za-z0-9-]{1,20}"),
    ]
    for source, target, value_pattern in rules:
        match = re.search(rf"{source}\s*[：:]\s*({value_pattern})(?=\s|[，,；;。|<]|$)", text)
        if match:
            fields[target] = match.group(1)
    location_options = {"1": "家", "2": "学校食堂", "3": "餐馆或街头", "4": "不吃"}
    for meal, target in (("早餐", "早餐地点"), ("午餐", "午餐地点"), ("晚餐", "晚餐地点")):
        match = re.search(rf"你一般{meal}的就餐地点是\s*[？?]?\s*([1-4])(?=\s|[（(]|$)", text)
        if match:
            fields[target] = location_options[match.group(1)]
            continue
        line_match = re.search(rf"你一般{meal}的就餐地点是[^\n]*(?:\n[^\n]*)?", text)
        if line_match:
            selected = explicitly_marked_options(line_match.group(0), list(location_options.values()))
            if selected:
                fields[target] = "、".join(selected)

    numeric_rules = [
        ("每日餐次", r"你一般每天吃几餐", 10),
        ("每周在家吃饭天数", r"你一般每周在家吃几天饭", 7),
        ("每周户外日照天数", r"你每周有", 7),
        ("每日户外日照时长(小时)", r"你平均每天的户外日照时长是", 12),
    ]
    for target, prompt, maximum in numeric_rules:
        value, warning = nutrition_numeric_answer(text, prompt, maximum)
        if value:
            fields[target] = value
        if warning:
            fields["人工备注"] = append_nutrition_note(fields.get("人工备注"), warning)

    if re.search(r"日照情况\s*[：:]\s*(?:无|0)(?=\s|\n|[。；;]|$)", text):
        fields.update({
            "每周户外日照天数": "0", "每日户外日照时长(小时)": "0",
            "晒太阳时段": "无", "皮肤暴露部位": "无",
        })
    if re.search(r"晒太阳的大概时间段是\s*[：:]?\s*(?:无|0)(?=\s|\n|[。；;]|$)", text):
        fields["晒太阳时段"] = "无"
    if re.search(r"皮肤暴露部位包括[^：:\n]*[：:]\s*(?:无|0)(?=\s|\n|[。；;]|$)", text):
        fields["皮肤暴露部位"] = "无"

    description_match = re.search(r"混合时间段请描述\s*[：:]\s*([^\n]{1,100})", text)
    if description_match:
        description = re.sub(r"^[_＿—\-]+|[_＿—\-]+$", "", description_match.group(1)).strip(" 。；;")
        if description and not re.fullmatch(r"[_＿—\-]+", description):
            fields["晒太阳时段"] = description
    time_options = ["上午9点之前", "上午9点至下午3点", "下午3点之后"]
    selected_times = explicitly_marked_options(text, time_options)
    if selected_times:
        fields["晒太阳时段"] = "、".join(selected_times + ([fields["晒太阳时段"]] if fields.get("晒太阳时段") else []))
    body_options = ["脸部", "颈部", "后背", "胳膊", "腿", "全身"]
    selected_parts = explicitly_marked_options(text, body_options)
    if selected_parts:
        fields["皮肤暴露部位"] = "、".join(selected_parts)
    return fields


def extract_body_composition_name_candidates(text: str) -> list[tuple[str, str]]:
    """Extract a subject name from InBody-style report headers as a fallback."""
    candidates = extract_person_name_candidates(text)
    for pattern in (
        r"(?:ID|编号)\s*[:：]?\s*[A-Za-z0-9_-]+\s*[（(]\s*([\u3400-\u9fff·]{2,8})\s*[）)]",
        r"[（(]\s*([\u3400-\u9fff·]{2,8})\s*[）)]",
    ):
        for match in re.finditer(pattern, clean(text), re.IGNORECASE):
            name = valid_person_name(match.group(1))
            if name and (name, "体成分报告") not in candidates:
                candidates.append((name, "体成分报告"))
    return candidates


def extract_fat_free_mass(text: str) -> str:
    """Return the first plausible fat-free mass (kg) from an OCR transcript.

    InBody exports commonly call this value ``去脂体重``; some devices use
    ``瘦体重`` or ``Fat Free Mass (FFM)``.  The range guard avoids accepting a
    nearby reference interval, body-fat value, or percentage as the result.
    """
    normalized_text = clean(text).replace("\r", "\n")
    soup = BeautifulSoup(normalized_text, "html.parser")
    for table in soup.find_all("table"):
        rows = [
            [clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["td", "th"])]
            for row in table.find_all("tr")
        ]
        header_index = next(
            (index for index, row in enumerate(rows) if any("去脂体重" in cell or "瘦体重" in cell for cell in row)),
            None,
        )
        if header_index is None:
            continue
        # InBody's 人体成分分析 table uses rowspans.  After HTML is flattened,
        # the values with reference intervals end in: 肌肉量、去脂体重、体重.
        for row in rows[header_index + 1:header_index + 4]:
            ranged_values = re.findall(r"(?<!\d)(\d{2,3}(?:\.\d{1,2})?)\s*\(\s*\d+(?:\.\d+)?\s*[~～-]", " ".join(row))
            if len(ranged_values) >= 2:
                value = float(ranged_values[-2])
                if 20 <= value <= 180:
                    return f"{value:g}"
    patterns = (
        r"(?:去\s*脂\s*体\s*重|除\s*脂\s*体\s*重|瘦\s*体\s*重|fat\s*free\s*mass|FFM)"
        r"\s*(?:\([^)]{0,24}\))?\s*[:：]?\s*(\d{2,3}(?:\.\d{1,2})?)\s*(?:kg|公斤|千克)?",
        r"(?:去\s*脂\s*体\s*重|除\s*脂\s*体\s*重|瘦\s*体\s*重|fat\s*free\s*mass|FFM)"
        r"[\s|，,;；:：\n]{1,12}(\d{2,3}(?:\.\d{1,2})?)\s*(?:kg|公斤|千克)?",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, normalized_text, re.IGNORECASE):
            value = float(match.group(1))
            if 20 <= value <= 180:
                return f"{value:g}"
    return ""


def merge_body_composition_records(
    people: list[dict[str, Any]], records: list[dict[str, str]],
) -> tuple[int, list[str]]:
    """Merge recognised fat-free mass values only when the person name is unique."""
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for person in people:
        name = valid_person_name((person.get("general") or {}).get("姓名"))
        if name:
            by_name[name].append(person)

    matched = 0
    unmatched: list[str] = []
    for record in records:
        name = valid_person_name(record.get("name"))
        fat_free_mass = clean(record.get("fat_free_mass"))
        matches = by_name.get(name, [])
        if not name or not fat_free_mass or len(matches) != 1:
            unmatched.append(clean(record.get("filename")) or "未命名体成分报告")
            continue
        person = matches[0]
        person.setdefault("general", {})["去脂体重"] = fat_free_mass
        person.setdefault("body_composition_files", []).append(record.get("file_url", ""))
        matched += 1
    return matched, unmatched


def body_composition_match_candidates(record_name: object, people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return reviewable name-pairing candidates without auto-merging fuzzy names."""
    source_name = valid_person_name(record_name)
    if not source_name:
        return []
    candidates: list[dict[str, Any]] = []
    for person in people:
        general = person.get("general") if isinstance(person.get("general"), dict) else {}
        target_name = valid_person_name(general.get("姓名"))
        person_id = clean(person.get("id"))
        if not target_name or not person_id:
            continue
        if source_name == target_name:
            score = 100
        else:
            score = round(difflib.SequenceMatcher(a=source_name, b=target_name).ratio() * 100)
            if source_name[:1] == target_name[:1]:
                score = min(99, score + 12)
        if score >= 45:
            candidates.append({"person_id": person_id, "name": target_name, "score": score})
    return sorted(candidates, key=lambda item: (-item["score"], item["name"]))[:5]


def attach_body_composition_match_candidates(records: list[dict[str, Any]], people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach suggestions; only an exact, unique name match is preselected."""
    for record in records:
        candidates = body_composition_match_candidates(record.get("name"), people)
        exact = [item for item in candidates if item["score"] == 100]
        record["match_candidates"] = candidates
        record["suggested_person_id"] = exact[0]["person_id"] if len(exact) == 1 else ""
    return records


def parse_nutrition_markdown(markdown: str) -> dict[str, Any]:
    """Markdown 保留了食物频率各列，是此问卷的推荐解析模式。"""
    soup = BeautifulSoup(markdown or "", "html.parser")
    result = {"general": nutrition_general_from_text(soup.get_text("\n", strip=True)), "food_rows": [], "supplement_rows": []}
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            values = [clean(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
            if values:
                rows.append(values)
        if not rows:
            continue
        table_text = " ".join(" ".join(row) for row in rows[:5])
        if "食物名称" in table_text:
            for values in rows:
                match = re.match(r"^(\d+(?:\.\d+)?)\s*(.+)$", values[0]) if values else None
                if not match:
                    continue
                quantity, period_values = split_nutrition_food_cells(values)
                row = normalize_food_row(match.group(1), match.group(2), quantity, period_values, " | ".join(values))
                if row:
                    result["food_rows"].append(row)
        elif "营养保健品种类" in table_text:
            for values in rows:
                if not values or values[0] in {"营养保健品种类", "每天", "每周", "每月", "每年", "不吃", "请选择适当周期填写次数", "填0"}:
                    continue
                row = normalize_supplement_row(values)
                if row:
                    result["supplement_rows"].append(row)
    return result


def parse_nutrition_page_fields(excel_content: bytes, markdown_text: str = "", parse_mode: str = "markdown") -> dict[str, Any]:
    """Parse a saved/live nutrition OCR pair with the same fallback rules."""
    excel_parsed = parse_nutrition_excel(excel_content)
    if parse_mode != "markdown" or not markdown_text:
        return excel_parsed
    parsed = parse_nutrition_markdown(markdown_text)
    merged_general = dict(excel_parsed["general"])
    for key, value in parsed["general"].items():
        if key == "人工备注":
            merged_general[key] = append_nutrition_note(merged_general.get(key), value)
        elif value:
            merged_general[key] = value
    parsed["general"] = merged_general
    if not parsed["food_rows"]:
        parsed["food_rows"] = excel_parsed["food_rows"]
    if not parsed["supplement_rows"]:
        parsed["supplement_rows"] = excel_parsed["supplement_rows"]
    return parsed


def nutrition_output_path(state: dict[str, Any]) -> Path:
    return state["job_dir"] / "output" / state["output_filename"]


def nutrition_sheet(workbook, preferred_name: str, keyword: str, headers: list[str]):
    for worksheet in workbook.worksheets:
        if preferred_name == worksheet.title or keyword in worksheet.title:
            return worksheet
        detected_row = detect_header_row(worksheet)
        existing_headers = " ".join(clean(worksheet.cell(detected_row, column).value) for column in range(1, worksheet.max_column + 1))
        if preferred_name == "人员汇总" and ("姓名" in existing_headers or "受试者编号" in existing_headers):
            return worksheet
        if preferred_name == "食物频率明细" and "食物名称" in existing_headers:
            return worksheet
        if preferred_name == "营养保健品" and ("保健品" in existing_headers or "营养保健品" in existing_headers):
            return worksheet
    worksheet = workbook.create_sheet(preferred_name)
    worksheet.append(headers)
    return worksheet


def prepare_nutrition_detail_export_sheet(worksheet) -> None:
    """Keep export detail sheets concise and identifiable even for old/custom templates."""
    header_row = detect_header_row(worksheet)
    headers = [clean(worksheet.cell(header_row, column).value) for column in range(1, worksheet.max_column + 1)]
    for column in reversed([index + 1 for index, header in enumerate(headers) if normalized(header) == normalized("OCR原始行")]):
        worksheet.delete_cols(column)
    headers = [clean(worksheet.cell(header_row, column).value) for column in range(1, worksheet.max_column + 1)]
    if "姓名" not in headers and "人员文件夹" in headers:
        folder_column = headers.index("人员文件夹") + 1
        insert_column = folder_column + 1
        worksheet.insert_cols(insert_column)
        for row in range(1, worksheet.max_row + 1):
            source = worksheet.cell(row, folder_column)
            target = worksheet.cell(row, insert_column)
            target._style = copy(source._style)
            target.number_format = source.number_format
            target.alignment = copy(source.alignment)
            if row == header_row:
                target.value = "姓名"
        worksheet.column_dimensions[worksheet.cell(header_row, insert_column).column_letter].width = 14
    worksheet.auto_filter.ref = worksheet.dimensions


def append_adaptive_row(worksheet, data: dict[str, Any], fallback_headers: list[str]) -> None:
    header_row = detect_header_row(worksheet)
    headers = [clean(worksheet.cell(header_row, column).value) for column in range(1, max(worksheet.max_column, len(fallback_headers)) + 1)]
    if not any(headers):
        headers = fallback_headers
        for index, value in enumerate(headers, start=1):
            worksheet.cell(header_row, index).value = value
    row = first_empty_data_row(worksheet, header_row, headers)
    for column, header in enumerate(headers, start=1):
        value = data.get(header, "")
        if value == "":
            normalized_header = normalized(header)
            for key, candidate in data.items():
                if normalized_header and (normalized_header == normalized(key) or normalized_header in normalized(key) or normalized(key) in normalized_header):
                    value = candidate
                    break
        if value != "":
            worksheet.cell(row, column).value = value


def write_nutrition_workbook(state: dict[str, Any], people: list[dict[str, Any]], output_path: Path | None = None) -> Path:
    template_path = state.get("template_path") or NUTRITION_TEMPLATE
    workbook = load_workbook(template_path)
    general_sheet = nutrition_sheet(workbook, "人员汇总", "人员", NUTRITION_GENERAL_COLUMNS)
    food_sheet = nutrition_sheet(workbook, "食物频率明细", "食物", NUTRITION_FOOD_COLUMNS)
    supplement_sheet = nutrition_sheet(workbook, "营养保健品", "保健", NUTRITION_SUPPLEMENT_COLUMNS)
    prepare_nutrition_detail_export_sheet(food_sheet)
    prepare_nutrition_detail_export_sheet(supplement_sheet)
    for person in people:
        general = {**{column: "" for column in NUTRITION_GENERAL_COLUMNS}, **person.get("general", {})}
        general["人员文件夹"] = person["id"]
        append_adaptive_row(general_sheet, general, NUTRITION_GENERAL_COLUMNS)
        person_name = clean(general.get("姓名"))
        for row in person.get("food_rows", []):
            append_adaptive_row(food_sheet, {"人员文件夹": person["id"], "姓名": person_name, **row}, NUTRITION_FOOD_COLUMNS)
        for row in person.get("supplement_rows", []):
            append_adaptive_row(supplement_sheet, {"人员文件夹": person["id"], "姓名": person_name, **row}, NUTRITION_SUPPLEMENT_COLUMNS)
    for worksheet in (general_sheet, food_sheet, supplement_sheet):
        worksheet.auto_filter.ref = worksheet.dimensions
    output = output_path or nutrition_output_path(state)
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    workbook.close()
    return output


def recognize_body_composition_reports(
    state: dict[str, Any],
    ocr_url: str,
    source_paths: list[Path],
    *,
    artifact_root: Path,
    progress_key: str = "completed_files",
) -> list[dict[str, Any]]:
    """OCR body-composition reports and retain results for a later pairing review."""
    records: list[dict[str, Any]] = []
    for index, source_path in enumerate(source_paths, start=1):
        state.update(current_file=source_path.name, message=f"正在识别体成分报告 {index}/{len(source_paths)}：{source_path.name}")
        response = request_cloud_ocr(
            state,
            ocr_url,
            source_path,
            document_kind="auto",
            page_index=1,
        )
        try:
            data = response.json()
        except ValueError as error:
            raise RuntimeError(f"{source_path.name} 的体成分 OCR 响应不是 JSON：{response.text[:160]}") from error
        if not response.ok or not data.get("success"):
            raise RuntimeError(f"{source_path.name} 体成分 OCR 失败：{data.get('detail') or response.status_code}")

        markdown_text = str(data.get("markdown") or "")
        ocr_text = "\n".join((markdown_text, str(data.get("json_text") or "")))
        relative = artifact_root / f"{index:03d}_{source_path.stem}_ocr.md"
        markdown_path = state["job_dir"] / relative
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown_text, encoding="utf-8")
        candidates = extract_body_composition_name_candidates(ocr_text)
        candidates.extend(cloud_name_candidates(data))
        records.append({
            "id": uuid.uuid4().hex,
            "name": choose_person_name(candidates),
            "fat_free_mass": extract_fat_free_mass(ocr_text),
            "filename": source_path.name,
            "file_url": file_url(state["job_id"], relative),
        })
        state[progress_key] = int(state.get(progress_key, 0)) + 1

    return records


def process_body_composition_reports(
    state: dict[str, Any],
    ocr_url: str,
    source_paths: list[Path],
    people: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """OCR optional initial reports and merge only an unambiguous exact name match."""
    records = recognize_body_composition_reports(
        state, ocr_url, source_paths, artifact_root=Path("body_composition_markdown")
    )

    return merge_body_composition_records(people, records)


def process_appended_body_composition_reports(job_id: str, ocr_url: str, source_paths: list[Path], append_id: str) -> None:
    """Recognise only newly added body reports; leave existing food data untouched."""
    state = JOBS[job_id]
    try:
        records = recognize_body_composition_reports(
            state,
            ocr_url,
            source_paths,
            artifact_root=Path("body_composition_append") / append_id,
            progress_key="body_composition_completed_files",
        )
        state["body_composition_pending_matches"] = attach_body_composition_match_candidates(records, state["people"])
        state.update(
            body_composition_status="awaiting_match",
            message=f"已识别 {len(records)} 份体成分报告，请确认姓名配对后写入去脂体重。",
        )
        persist_nutrition_job(job_id)
    except Exception as error:
        state.update(body_composition_status="failed", message=f"体成分追加失败：{error}")
        persist_nutrition_job(job_id)


def process_nutrition_job(
    job_id: str,
    ocr_url: str,
    groups: dict[str, list[Path]],
    parse_mode: str,
    processing_mode: str = "accurate",
    body_composition_paths: list[Path] | None = None,
) -> None:
    state = JOBS[job_id]
    try:
        state.update(status="processing", message="正在识别食物频率调查问卷…")
        people: list[dict[str, Any]] = []
        for person_id, page_paths in sorted(groups.items()):
            person = nutrition_blank_person(person_id)
            person_name_candidates: list[tuple[str, str]] = []
            for page_number, source_path in enumerate(page_paths, start=1):
                state.update(current_file=source_path.name, current_person=person_id, message=f"正在识别 {person_id} / {source_path.name}")
                response = request_cloud_ocr(
                    state,
                    ocr_url,
                    source_path,
                    document_kind="nutrition",
                    page_index=page_number,
                )
                try:
                    data = response.json()
                except ValueError as error:
                    raise RuntimeError(f"{source_path.name} 的云端响应不是 JSON：{response.text[:160]}") from error
                if not response.ok or not data.get("success") or not data.get("excel"):
                    raise RuntimeError(f"{source_path.name} OCR 失败：{data.get('detail') or response.status_code}")
                excel_bytes = base64.b64decode(data["excel"])
                relative = Path("ocr_excel") / safe_relative(person_id, "unknown") / f"{page_number:02d}_{source_path.stem}_ocr.xlsx"
                excel_path = state["job_dir"] / relative
                excel_path.parent.mkdir(parents=True, exist_ok=True)
                excel_path.write_bytes(excel_bytes)
                person["ocr_files"].append(file_url(job_id, relative))
                markdown_text = str(data.get("markdown") or "")
                markdown_relative = Path("ocr_markdown") / safe_relative(person_id, "unknown") / f"{page_number:02d}_{source_path.stem}_ocr.md"
                markdown_path = state["job_dir"] / markdown_relative
                markdown_path.parent.mkdir(parents=True, exist_ok=True)
                markdown_path.write_text(markdown_text, encoding="utf-8")
                person["markdown_files"].append(file_url(job_id, markdown_relative))
                json_relative = Path("ocr_json") / safe_relative(person_id, "unknown") / f"{page_number:02d}_{source_path.stem}_ocr.json"
                json_path = state["job_dir"] / json_relative
                json_path.parent.mkdir(parents=True, exist_ok=True)
                json_payload = {key: value for key, value in data.items() if key not in {"excel", "markdown", "assets"}}
                json_payload["assets_count"] = len(data.get("assets") or []) if isinstance(data.get("assets"), list) else 0
                json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                person["json_files"].append(file_url(job_id, json_relative))
                person_name_candidates.extend(
                    first_page_name_candidates(extract_person_name_candidates(markdown_text), page_number)
                )
                person_name_candidates.extend(
                    first_page_name_candidates(cloud_name_candidates(data), page_number)
                )
                parsed = parse_nutrition_page_fields(excel_bytes, markdown_text, parse_mode)
                for key, value in parsed["general"].items():
                    if key == "姓名":
                        name = valid_person_name(value)
                        if name:
                            person_name_candidates.extend(
                                first_page_name_candidates([(name, "解析字段")], page_number)
                            )
                    elif key == "人工备注" and value:
                        person["general"][key] = append_nutrition_note(person["general"].get(key), value)
                    elif value and not person["general"].get(key):
                        person["general"][key] = value
                apply_cloud_questionnaire_result(data, person)
                person["food_rows"].extend(parsed["food_rows"])
                person["supplement_rows"].extend(parsed["supplement_rows"])
                state["completed_files"] += 1
            selected_name = choose_person_name(person_name_candidates)
            if selected_name:
                person["general"]["姓名"] = selected_name
            finalize_nutrition_person(person)
            people.append(person)
        if not any(person["food_rows"] for person in people):
            raise RuntimeError("未发现“食物名称 / 进食次数”问卷表格。当前文件很可能是体检报告，请切换到“体检报告回写”工作台处理。")
        body_composition_paths = body_composition_paths or []
        matched_body_composition, unmatched_body_composition = process_body_composition_reports(
            state, ocr_url, body_composition_paths, people
        ) if body_composition_paths else (0, [])
        state["body_composition_unmatched"] = unmatched_body_composition
        write_nutrition_workbook(state, people)
        relative = Path("output") / state["output_filename"]
        body_message = ""
        if body_composition_paths:
            body_message = f" 已从 {len(body_composition_paths)} 份体成分报告匹配 {matched_body_composition} 项去脂体重。"
            if unmatched_body_composition:
                body_message += f" {len(unmatched_body_composition)} 份未能按姓名唯一匹配，请在报告导出窗口手动补充。"
        state.update(status="completed", people=people, output_relative=relative, output_url=file_url(job_id, relative), message=f"已处理 {len(people)} 名受访者。{body_message}请逐人核对频率周期、手写数值与勾选项。")
        persist_nutrition_job(job_id)
    except Exception as error:
        state.update(status="failed", message=str(error))


@app.get("/nutrition-template")
def download_nutrition_template():
    ensure_nutrition_template()
    return FileResponse(NUTRITION_TEMPLATE, filename="食物频率调查_汇总模板.xlsx")


@app.post("/nutrition/process", status_code=202)
def process_nutrition_reports(
    background_tasks: BackgroundTasks,
    ocr_url: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    relative_paths: Annotated[list[str], Form()],
    template: UploadFile | None = File(None),
    parse_mode: str = Form("markdown"),
    processing_mode: str = Form("accurate"),
    body_composition_files: list[UploadFile] = File(default=[]),
    body_composition_relative_paths: list[str] = Form(default=[]),
):
    processing_mode = normalize_processing_mode(processing_mode)
    if not files or len(files) != len(relative_paths):
        raise HTTPException(status_code=400, detail="报告文件与目录信息不一致，请重新选择 PDF 或文件夹")
    job_id, job_dir = uuid.uuid4().hex, JOB_ROOT / uuid.uuid4().hex
    job_dir = JOB_ROOT / job_id
    input_dir = job_dir / "input" / "reports"
    input_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[Path]] = defaultdict(list)
    for index, pdf in enumerate(files):
        relative = relative_paths[index] or pdf.filename or f"report_{index + 1}.pdf"
        safe_path = safe_relative(relative, pdf.filename or f"report_{index + 1}.pdf")
        source_path = input_dir / safe_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("wb") as target:
            shutil.copyfileobj(pdf.file, target)
        parent = str(safe_path.parent).replace("\\", "/")
        groups[parent if parent != "." else source_path.stem].append(source_path)
    if len(body_composition_files) != len(body_composition_relative_paths):
        raise HTTPException(status_code=400, detail="体成分报告与目录信息不一致，请重新选择文件夹")
    body_composition_dir = job_dir / "input" / "body_composition"
    body_composition_paths: list[Path] = []
    for index, pdf in enumerate(body_composition_files):
        relative = body_composition_relative_paths[index] or pdf.filename or f"body_composition_{index + 1}.pdf"
        safe_path = safe_relative(relative, pdf.filename or f"body_composition_{index + 1}.pdf")
        source_path = body_composition_dir / safe_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("wb") as target:
            shutil.copyfileobj(pdf.file, target)
        body_composition_paths.append(source_path)
    template_path = None
    if template and template.filename:
        template_path = job_dir / "input" / Path(template.filename).name
        with template_path.open("wb") as target:
            shutil.copyfileobj(template.file, target)
    JOBS[job_id] = {"job_id": job_id, "kind": "nutrition", "parse_mode": parse_mode, "processing_mode": processing_mode, "template_path": template_path, "output_filename": timestamped_filename("食物频率调查_自动汇总"), "status": "queued", "job_dir": job_dir, "total_files": len(files) + len(body_composition_paths), "completed_files": 0, "current_file": "", "current_person": "", "message": "文件已上传到本机，等待开始识别…", "people": []}
    background_tasks.add_task(process_nutrition_job, job_id, ocr_url, dict(groups), parse_mode, processing_mode, body_composition_paths)
    return {"success": True, "job_id": job_id, "total_files": len(files) + len(body_composition_paths), "people_count": len(groups), "body_composition_count": len(body_composition_paths)}


@app.post("/nutrition/jobs/{job_id}/body-composition", status_code=202)
def append_body_composition_reports(
    job_id: str,
    background_tasks: BackgroundTasks,
    ocr_url: Annotated[str, Form()],
    people_json: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    relative_paths: Annotated[list[str], Form()],
):
    """Append body-composition OCR to a completed nutrition job without rerunning food OCR."""
    state = JOBS.get(job_id) or recover_nutrition_job(job_id)
    if not state or state.get("kind") != "nutrition" or state.get("status") != "completed":
        raise HTTPException(status_code=409, detail="营养问卷任务尚未完成，无法追加体成分报告")
    if state.get("body_composition_status") == "processing":
        raise HTTPException(status_code=409, detail="体成分报告正在识别，请等待当前任务完成")
    if not files or len(files) != len(relative_paths):
        raise HTTPException(status_code=400, detail="体成分报告与目录信息不一致，请重新选择 PDF")
    try:
        people = json.loads(people_json)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="当前人员数据格式不正确") from error
    if not isinstance(people, list) or not all(isinstance(person, dict) and clean(person.get("id")) for person in people):
        raise HTTPException(status_code=400, detail="当前人员数据不完整，无法保留人工核对结果")

    append_id = uuid.uuid4().hex
    input_dir = Path(state["job_dir"]) / "input" / "body_composition_append" / append_id
    source_paths: list[Path] = []
    for index, pdf in enumerate(files):
        relative = relative_paths[index] or pdf.filename or f"body_composition_{index + 1}.pdf"
        safe_path = safe_relative(relative, pdf.filename or f"body_composition_{index + 1}.pdf")
        source_path = input_dir / safe_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("wb") as target:
            shutil.copyfileobj(pdf.file, target)
        source_paths.append(source_path)

    state["people"] = people
    state.update(
        body_composition_status="processing",
        body_composition_total_files=len(source_paths),
        body_composition_completed_files=0,
        body_composition_pending_matches=[],
        message=f"已保留当前食物问卷核对结果，正在追加识别 {len(source_paths)} 份体成分报告…",
    )
    persist_nutrition_job(job_id)
    background_tasks.add_task(process_appended_body_composition_reports, job_id, ocr_url, source_paths, append_id)
    return {"success": True, "body_composition_count": len(source_paths)}


@app.post("/nutrition/jobs/{job_id}/body-composition/apply-matches")
def apply_body_composition_matches(job_id: str, payload: dict[str, Any]):
    """Apply user-confirmed body-report pairings to the existing reviewed people."""
    state = JOBS.get(job_id) or recover_nutrition_job(job_id)
    if not state or state.get("kind") != "nutrition" or state.get("status") != "completed":
        raise HTTPException(status_code=409, detail="营养问卷任务不可用")
    if state.get("body_composition_status") != "awaiting_match":
        raise HTTPException(status_code=409, detail="当前没有等待确认的体成分配对")
    people = payload.get("people")
    assignments = payload.get("assignments")
    if not isinstance(people, list) or not isinstance(assignments, dict):
        raise HTTPException(status_code=400, detail="配对确认数据不完整")
    people_by_id = {clean(person.get("id")): person for person in people if isinstance(person, dict) and clean(person.get("id"))}
    if not people_by_id:
        raise HTTPException(status_code=400, detail="当前人员数据不完整")

    applied, skipped = 0, []
    for record in state.get("body_composition_pending_matches") or []:
        record_id = clean(record.get("id"))
        person_id = clean(assignments.get(record_id))
        person = people_by_id.get(person_id)
        fat_free_mass = clean(record.get("fat_free_mass"))
        if person is None or not fat_free_mass:
            skipped.append(clean(record.get("filename")) or "未命名体成分报告")
            continue
        person.setdefault("general", {})["去脂体重"] = fat_free_mass
        source_files = person.setdefault("body_composition_files", [])
        if record.get("file_url") and record["file_url"] not in source_files:
            source_files.append(record["file_url"])
        applied += 1

    state["people"] = list(people_by_id.values())
    state.update(
        body_composition_status="completed",
        body_composition_pending_matches=[],
        body_composition_unmatched=skipped,
        message=f"已追加 {applied} 项去脂体重。" + (f" {len(skipped)} 份未写入，请人工补充。" if skipped else ""),
    )
    write_nutrition_workbook(state, state["people"])
    persist_nutrition_job(job_id)
    return {"success": True, "people": state["people"], "applied": applied, "skipped": skipped, "message": state["message"]}


@app.post("/nutrition/jobs/{job_id}/save-review")
def save_nutrition_review(job_id: str, payload: dict[str, Any]):
    state = JOBS.get(job_id) or recover_nutrition_job(job_id)
    if not state or state.get("kind") != "nutrition" or state.get("status") != "completed":
        raise HTTPException(status_code=409, detail="营养问卷任务尚未完成，无法保存")
    people = payload.get("people")
    if not isinstance(people, list):
        raise HTTPException(status_code=400, detail="缺少核对数据")
    write_nutrition_workbook(state, people)
    state["people"] = people
    persist_nutrition_job(job_id)
    return {"success": True, "message": "食物频率调查汇总表已保存", "output_url": state["output_url"]}


@app.get("/nutrition/latest-job")
def latest_nutrition_job():
    candidates = sorted((item for item in JOB_ROOT.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime, reverse=True)
    for job_dir in candidates:
        state = JOBS.get(job_dir.name) or recover_nutrition_job(job_dir.name)
        if state and state.get("kind") == "nutrition" and state.get("status") == "completed":
            snapshot = {key: value for key, value in state.items() if key not in {"job_dir", "output_relative", "template_path"}}
            return {"success": True, "job_id": job_dir.name, **snapshot}
    raise HTTPException(status_code=404, detail="没有可恢复的本地营养任务")


@app.post("/nutrition/preview")
def preview_nutrition_person(payload: dict[str, Any]):
    person = payload.get("person")
    user_overrides = payload.get("user_overrides")
    if not isinstance(person, dict):
        raise HTTPException(status_code=400, detail="缺少当前受访者的核对数据")
    if user_overrides is not None and not isinstance(user_overrides, dict):
        raise HTTPException(status_code=400, detail="人员补充信息格式不正确")
    try:
        service = NutritionReportService()
        adapted = service.adapt_ocr_person(person, user_overrides=user_overrides, report_date=clean(payload.get("report_date")) or None)
        # 预览返回与导出相同的机器初稿（分类评价、建议、能量/钙评价），
        # 前端据此提供人工复核，而不是把固定阈值直接当最终结论。
        preview = service.build_report_data(adapted.payload)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"营养摄入预览计算失败：{error}") from error
    return {
        "success": True, "preview": preview, "warnings": adapted.warnings,
        "usable_food_count": adapted.usable_food_count,
        "food_data_source": preview.get("food_data_source", {}),
    }


@app.post("/nutrition/jobs/{job_id}/people/{person_id}/report")
def generate_nutrition_person_report(job_id: str, person_id: str, payload: dict[str, Any]):
    """Generate one migrated nutrition report from the reviewed OCR person data.

    The report is deliberately generated on the local OCR service: the cloud server
    remains responsible only for OCR and no reviewed questionnaire data is uploaded
    again.
    """
    state = JOBS.get(job_id) or recover_nutrition_job(job_id)
    if not state or state.get("kind") != "nutrition" or state.get("status") != "completed":
        raise HTTPException(status_code=409, detail="营养问卷任务尚未完成，无法生成报告")

    person = payload.get("person")
    if not isinstance(person, dict):
        raise HTTPException(status_code=400, detail="缺少当前受访者的核对数据")
    if clean(person.get("id")) != person_id:
        raise HTTPException(status_code=400, detail="受访者标识与当前任务不一致")
    if person_id not in {clean(item.get("id")) for item in state.get("people", []) if isinstance(item, dict)}:
        raise HTTPException(status_code=404, detail="当前任务中不存在该受访者")

    report_format = clean(payload.get("format")).lower()
    if report_format not in {"pdf", "excel"}:
        raise HTTPException(status_code=400, detail="报告格式仅支持 pdf 或 excel")
    user_overrides = payload.get("user_overrides")
    if user_overrides is not None and not isinstance(user_overrides, dict):
        raise HTTPException(status_code=400, detail="人员补充信息格式不正确")
    manual_evaluations = payload.get("manual_evaluations")
    if manual_evaluations is not None and not isinstance(manual_evaluations, dict):
        raise HTTPException(status_code=400, detail="人工营养评价格式不正确")
    auto_evaluation = payload.get("auto_evaluation") is not False
    if not auto_evaluation and manual_evaluations is None:
        raise HTTPException(status_code=400, detail="请先提交人工复核后的营养评价")

    report_date = clean(payload.get("report_date")) or None
    extension = ".pdf" if report_format == "pdf" else ".xlsx"
    label = "营养健康评估报告" if report_format == "pdf" else "营养分析报告"
    filename_person = person
    override_name = clean((user_overrides or {}).get("name"))
    if override_name:
        filename_person = {
            **person,
            "general": {**(person.get("general") or {}), "姓名": override_name},
        }
    # Timestamp plus a short task-local token keeps simultaneous exports from
    # different browser tabs from overwriting one another.
    output_path = state["job_dir"] / "output" / "nutrition_reports" / timestamped_filename(
        f"{report_filename_stem(filename_person)}_{label}_{uuid.uuid4().hex[:8]}", extension
    )
    try:
        service = NutritionReportService()
        if report_format == "pdf":
            result = service.generate_pdf_from_ocr_person(
                person, output_path, user_overrides=user_overrides, report_date=report_date,
                auto_evaluation=auto_evaluation, manual_evaluations=manual_evaluations,
            )
            media_type = "application/pdf"
        else:
            result = service.generate_excel_from_ocr_person(
                person, output_path, user_overrides=user_overrides, report_date=report_date,
                auto_evaluation=auto_evaluation, manual_evaluations=manual_evaluations,
            )
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"营养报告生成失败：{error}") from error

    source = result.get("report_data", {}).get("food_data_source", {})
    reports = state.setdefault("nutrition_reports", {})
    reports.setdefault(person_id, []).append({
        "format": report_format,
        "path": output_path.relative_to(state["job_dir"]).as_posix(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "usable_food_count": result["usable_food_count"],
        "warning_count": len(result["warnings"]),
        "food_data_source": source,
        "evaluation_mode": "automatic" if auto_evaluation else "manual_reviewed",
    })
    return FileResponse(
        output_path,
        media_type=media_type,
        filename=output_path.name,
        headers={
            "X-Nutrition-Data-Source": str(source.get("kind") or "unknown"),
            "X-Nutrition-Cloud-Available": str(source.get("cloud_available") is True).lower(),
            "X-Nutrition-Queried-At": str(source.get("queried_at") or ""),
            "X-Report-Filename": quote(output_path.name, safe=""),
        },
    )


@app.post("/nutrition/jobs/{job_id}/report")
def generate_nutrition_report(job_id: str, payload: dict[str, Any]):
    """Slash-safe report endpoint: the person id stays in JSON instead of the URL path."""
    person = payload.get("person")
    if not isinstance(person, dict):
        raise HTTPException(status_code=400, detail="缺少当前受访者的核对数据")
    person_id = clean(person.get("id"))
    if not person_id:
        raise HTTPException(status_code=400, detail="当前受访者缺少人员标识")
    return generate_nutrition_person_report(job_id, person_id, payload)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
