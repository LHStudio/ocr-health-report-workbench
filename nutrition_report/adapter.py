"""把本项目 OCR 的食物频率人员结构转换成原营养报告输入模型。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as date_type
from typing import Any, Mapping


# 原报告数据库只覆盖问卷的一部分名称。这里显式声明替代来源，禁止隐式模糊匹配。
# exact=False 表示使用同类代表食物的每 100g 营养值，生成结果中必须留下提示。
FOOD_REFERENCE_MAP: dict[str, tuple[str, bool]] = {
    "米饭": ("米饭", True),
    "大米粥": ("米饭", False),
    "馒头": ("小麦面粉", False),
    "面包": ("小麦面粉", False),
    "面条": ("小麦面粉", False),
    "包子/饺子": ("小麦面粉", False),
    "玉米": ("杂粮", False),
    "小米": ("杂粮", False),
    "窝头": ("杂粮", False),
    "红薯": ("土豆", False),
    "山药": ("土豆", False),
    "芋头": ("土豆", False),
    "土豆": ("土豆", True),
    "油条": ("油条", True),
    "油饼": ("油条", False),
    "猪肉": ("猪肉", True),
    "牛肉": ("牛肉", True),
    "羊肉": ("羊肉", True),
    "鸡肉、鸭肉": ("鸡肉", False),
    "内脏类": ("猪肝", False),
    "鱼": ("带鱼", False),
    "虾": ("海白虾", False),
    "鲜奶": ("鲜奶", True),
    "奶粉": ("奶粉", True),
    "奶酪": ("奶酪", True),
    "酸奶": ("酸奶", True),
    "蛋类": ("蛋类", True),
    "豆腐": ("豆腐", True),
    "豆腐丝/千张/豆腐干": ("豆腐丝/千张/豆腐干", True),
    "豆浆": ("豆浆", True),
    "新鲜蔬菜": ("白菜", False),
    "糕点": ("蛋糕", False),
    "新鲜水果": ("苹果", False),
    "坚果": ("核桃仁", False),
    "果汁饮料": ("苹果汁", False),
    "咖啡": ("咖啡", True),
    "茶/茶饮料": ("茶", False),
    "其他饮料": ("运动饮料", False),
}

PERIOD_DIVISORS = {
    "每天": 1.0,
    "每日": 1.0,
    "每周": 7.0,
    "每月": 30.0,
    "每年": 365.0,
}

_NUMBER = r"\d+(?:\.\d+)?"
_RANGE_RE = re.compile(
    rf"(?P<low>{_NUMBER})\s*[-~～至]\s*(?P<high>{_NUMBER})\s*"
    r"(?P<unit>公斤|千克|kg|毫升|ml|克|g|升|l)?",
    re.IGNORECASE,
)
_MEASURE_RE = re.compile(
    rf"(?P<number>{_NUMBER})\s*(?P<unit>公斤|千克|kg|毫升|ml|克|g|升|l)",
    re.IGNORECASE,
)
_PLAIN_NUMBER_RE = re.compile(rf"^\s*(?P<number>{_NUMBER})\s*$")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _warning(code: str, message: str, *, food: str = "", severity: str = "warning") -> dict[str, str]:
    result = {"code": code, "severity": severity, "message": message}
    if food:
        result["food"] = food
    return result


@dataclass
class AdaptedNutritionInput:
    """JSON 兼容的报告输入及 OCR 到日报摄入量的追溯信息。"""

    payload: dict[str, Any]
    warnings: list[dict[str, str]] = field(default_factory=list)
    source_foods: list[dict[str, Any]] = field(default_factory=list)

    @property
    def usable_food_count(self) -> int:
        return len(self.payload.get("meals") or [])


def _parse_number_or_range(value: Any, *, field_name: str, food_name: str) -> tuple[float | None, list[dict[str, str]]]:
    text = _text(value).replace("^", "-").replace("—", "-")
    if not text:
        return None, [_warning(f"missing_{field_name}", f"{food_name}缺少{field_name}，未计入营养报告", food=food_name)]
    match = _RANGE_RE.search(text)
    if match:
        low, high = float(match.group("low")), float(match.group("high"))
        midpoint = (low + high) / 2
        return midpoint, [
            _warning(
                f"range_{field_name}",
                f"{food_name}的{field_name}“{text}”按区间中点 {midpoint:g} 换算，请核对",
                food=food_name,
            )
        ]
    numbers = re.findall(_NUMBER, text)
    if len(numbers) == 1:
        return float(numbers[0]), []
    return None, [_warning(f"invalid_{field_name}", f"{food_name}的{field_name}“{text}”无法可靠换算，未计入营养报告", food=food_name)]


def parse_quantity_grams(value: Any, food_name: str) -> tuple[float | None, list[dict[str, str]]]:
    """只自动换算克/千克；毫升按 1ml≈1g 并明确标注，份/个/勺不猜重量。"""
    text = _text(value).lower().replace("，", ",").replace("—", "-").replace("^", "-")
    if not text:
        return None, [_warning("missing_quantity", f"{food_name}缺少平均每次食用量，未计入营养报告", food=food_name)]

    range_match = _RANGE_RE.search(text)
    warnings: list[dict[str, str]] = []
    if range_match and range_match.group("unit"):
        low, high = float(range_match.group("low")), float(range_match.group("high"))
        number = (low + high) / 2
        unit = range_match.group("unit").lower()
        warnings.append(_warning("range_quantity", f"{food_name}食用量“{text}”按区间中点 {number:g}{unit} 换算，请核对", food=food_name))
    else:
        explicit = list(_MEASURE_RE.finditer(text))
        if explicit:
            # “1袋(200g)”优先选取明确质量/体积单位，而不是份数。
            number = float(explicit[-1].group("number"))
            unit = explicit[-1].group("unit").lower()
        else:
            plain = _PLAIN_NUMBER_RE.fullmatch(text)
            if plain:
                number = float(plain.group("number"))
                unit = "g"
                warnings.append(_warning("quantity_unit_assumed", f"{food_name}食用量“{text}”无单位，按克换算，请核对", food=food_name))
            elif re.fullmatch(r"\s*0(?:\.0+)?\s*[^\d]*", text):
                return 0.0, []
            else:
                return None, [_warning("unsupported_quantity_unit", f"{food_name}食用量“{text}”不是克/千克/毫升，未猜测份、个、勺的重量", food=food_name)]

    if unit in {"kg", "公斤", "千克"}:
        return number * 1000, warnings
    if unit in {"ml", "毫升"}:
        warnings.append(_warning("volume_density_assumed", f"{food_name}按 1 ml≈1 g 换算体积，实际密度可能不同", food=food_name))
        return number, warnings
    if unit in {"l", "升"}:
        warnings.append(_warning("volume_density_assumed", f"{food_name}按 1 L≈1000 g 换算体积，实际密度可能不同", food=food_name))
        return number * 1000, warnings
    return number, warnings


def _normalise_gender(value: Any) -> str:
    text = _text(value).lower()
    if text in {"女", "女性", "female", "f"}:
        return "female"
    if text in {"男", "男性", "male", "m"}:
        return "male"
    return text


def _build_user(person: Mapping[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    general = person.get("general") if isinstance(person.get("general"), Mapping) else {}
    override = dict(overrides or {})

    def pick(english: str, chinese: str, default: Any = "") -> Any:
        if english in override and override[english] not in (None, ""):
            return override[english]
        if chinese in override and override[chinese] not in (None, ""):
            return override[chinese]
        return general.get(chinese, default)

    user = {
        "name": pick("name", "姓名", _text(person.get("id"))),
        "age": pick("age", "年龄"),
        "projectType": pick("projectType", "项目种类"),
        "trainingYears": pick("trainingYears", "训练年限"),
        "currentStatus": pick("currentStatus", "当前状态"),
        "height": pick("height", "身高"),
        "weight": pick("weight", "体重"),
        "fatFreeMass": pick("fatFreeMass", "去脂体重"),
        "gender": _normalise_gender(pick("gender", "性别")),
        "bmi": pick("bmi", "BMI"),
        "activityLevel": pick("activityLevel", "运动量"),
        "physiologicalStage": pick("physiologicalStage", "生理阶段"),
    }
    return user


def build_payload_from_ocr_person(
    person: Mapping[str, Any],
    *,
    user_overrides: Mapping[str, Any] | None = None,
    report_date: str | None = None,
    auto_evaluation: bool = True,
    manual_evaluations: Mapping[str, Any] | None = None,
) -> AdaptedNutritionInput:
    """将 `local_service` 的单人 OCR 结果换算为原报告服务的 `user + meals`。

    频率统一折算为日均次数：每天不变、每周除以 7、每月除以 30、每年除以 365。
    无法可靠识别的频率或非质量单位不会进入营养计算，并在 warnings 中保留原因。
    """
    warnings: list[dict[str, str]] = []
    source_foods: list[dict[str, Any]] = []
    meals: list[dict[str, Any]] = []

    rows = person.get("food_rows") or []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            warnings.append(_warning("invalid_food_row", f"第 {index + 1} 条食物记录不是对象，已跳过"))
            continue
        food_name = _text(row.get("食物名称"))
        if not food_name:
            warnings.append(_warning("missing_food_name", f"第 {index + 1} 条食物记录缺少名称，已跳过"))
            continue

        period = _text(row.get("频率周期(请核对)"))
        not_eat = _text(row.get("是否不吃")) in {"是", "1", "true", "True", "✓", "√"} or period == "不吃"
        if not_eat:
            source_foods.append({"food": food_name, "status": "not_eaten", "daily_grams": 0.0})
            continue

        reference = FOOD_REFERENCE_MAP.get(food_name)
        if reference is None:
            warnings.append(_warning("unmapped_food", f"{food_name}在迁移的营养数据库中没有明确映射，未计入营养报告", food=food_name))
            continue
        reference_name, exact_reference = reference

        divisor = PERIOD_DIVISORS.get(period)
        if divisor is None:
            warnings.append(_warning("unresolved_period", f"{food_name}频率周期为“{period or '空'}”，未计入营养报告", food=food_name))
            continue

        grams, quantity_warnings = parse_quantity_grams(row.get("平均每次食用量"), food_name)
        warnings.extend(quantity_warnings)
        count, count_warnings = _parse_number_or_range(row.get("次数"), field_name="次数", food_name=food_name)
        warnings.extend(count_warnings)
        if grams is None or count is None:
            continue
        if grams < 0 or count < 0:
            warnings.append(_warning("negative_value", f"{food_name}出现负数食用量或次数，未计入营养报告", food=food_name))
            continue
        if grams == 0 or count == 0:
            source_foods.append({"food": food_name, "status": "zero", "daily_grams": 0.0})
            continue

        daily_grams = round(grams * count / divisor, 4)
        meals.append({"name": reference_name, "amount": daily_grams})
        source_foods.append({
            "food": food_name,
            "reference_food": reference_name,
            "reference_exact": exact_reference,
            "quantity": _text(row.get("平均每次食用量")),
            "count": _text(row.get("次数")),
            "period": period,
            "daily_grams": daily_grams,
        })
        if not exact_reference:
            warnings.append(_warning("proxy_food_reference", f"{food_name}暂按同类代表食物“{reference_name}”的每 100g 营养值估算", food=food_name))

    user = _build_user(person, user_overrides)
    general = person.get("general") if isinstance(person.get("general"), Mapping) else {}
    effective_date = report_date or _text(general.get("调查日期")) or date_type.today().isoformat()
    if not user.get("age") or not user.get("gender") or not user.get("activityLevel"):
        warnings.append(_warning(
            "missing_energy_profile",
            "年龄、性别或运动量信息不完整，报告无法套用女性 EER 个体能量标准",
            severity="info",
        ))
    if not meals:
        warnings.append(_warning("no_usable_foods", "没有可可靠换算为日均克数的食物，营养值将为 0", severity="error"))

    # 同一参考食物可由多个问卷条目产生，原 NutritionService 会在计算前自动合并。
    payload = {
        "user": user,
        "meals": meals,
        "date": effective_date,
        "autoEvaluation": bool(auto_evaluation),
        "source_person_id": _text(person.get("id")),
        "source_foods": source_foods,
        "conversion_warnings": warnings,
    }
    if manual_evaluations is not None:
        payload["manualEvaluations"] = dict(manual_evaluations)
    return AdaptedNutritionInput(payload=payload, warnings=warnings, source_foods=source_foods)
