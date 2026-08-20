"""从旧营养 Vue 项目隔离迁移的本地报告生成包。"""

from .adapter import AdaptedNutritionInput, FOOD_REFERENCE_MAP, build_payload_from_ocr_person
from .cloud import FoodDataResult, clear_food_data_cache, fetch_cloud_foods, resolve_food_data
from .service import (
    NutritionReportService,
    generate_excel_from_ocr_person,
    generate_pdf_from_ocr_person,
)

__all__ = [
    "AdaptedNutritionInput",
    "FOOD_REFERENCE_MAP",
    "FoodDataResult",
    "NutritionReportService",
    "build_payload_from_ocr_person",
    "clear_food_data_cache",
    "fetch_cloud_foods",
    "generate_excel_from_ocr_person",
    "generate_pdf_from_ocr_person",
    "resolve_food_data",
]
