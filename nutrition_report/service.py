"""营养报告纯 Python 门面，可直接由 FastAPI 本地服务导入调用。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .adapter import AdaptedNutritionInput, build_payload_from_ocr_person
from .builders.excel import NutritionExcelBuilder
from .builders.pdf import NutritionPDFBuilder
from .nutrition import NutritionService
from .cloud import FoodDataResult, resolve_food_data


class NutritionReportService:
    def __init__(
        self,
        *,
        font_path: str | Path | None = None,
        prefer_cloud: bool = True,
        food_data: FoodDataResult | None = None,
    ):
        resolved = food_data or resolve_food_data(prefer_cloud=prefer_cloud)
        self.nutrition_service = NutritionService(
            food_db=resolved.foods,
            food_data_source=resolved.metadata,
        )
        self.pdf_builder = NutritionPDFBuilder(font_path=font_path)
        self.excel_builder = NutritionExcelBuilder()

    def build_report_data(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise TypeError("营养报告输入必须是 JSON 对象")
        return self.nutrition_service.build_report_data(dict(payload))

    def preview_intake(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise TypeError("营养报告输入必须是 JSON 对象")
        return self.nutrition_service.build_intake_preview(dict(payload))

    def generate_pdf_from_json(self, payload: Mapping[str, Any], output_path: str | Path) -> dict[str, Any]:
        report_data = self.build_report_data(payload)
        self.pdf_builder.build(report_data, output_path)
        return report_data

    def generate_excel_from_json(self, payload: Mapping[str, Any], output_path: str | Path) -> dict[str, Any]:
        report_data = self.build_report_data(payload)
        self.excel_builder.build(report_data, output_path)
        return report_data

    def adapt_ocr_person(
        self,
        person: Mapping[str, Any],
        *,
        user_overrides: Mapping[str, Any] | None = None,
        report_date: str | None = None,
        auto_evaluation: bool = True,
        manual_evaluations: Mapping[str, Any] | None = None,
    ) -> AdaptedNutritionInput:
        return build_payload_from_ocr_person(
            person,
            user_overrides=user_overrides,
            report_date=report_date,
            auto_evaluation=auto_evaluation,
            manual_evaluations=manual_evaluations,
        )

    def generate_pdf_from_ocr_person(
        self,
        person: Mapping[str, Any],
        output_path: str | Path,
        *,
        user_overrides: Mapping[str, Any] | None = None,
        report_date: str | None = None,
        auto_evaluation: bool = True,
        manual_evaluations: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapted = self.adapt_ocr_person(
            person,
            user_overrides=user_overrides,
            report_date=report_date,
            auto_evaluation=auto_evaluation,
            manual_evaluations=manual_evaluations,
        )
        report_data = self.generate_pdf_from_json(adapted.payload, output_path)
        return {
            "output_path": str(Path(output_path).resolve()),
            "payload": adapted.payload,
            "report_data": report_data,
            "warnings": adapted.warnings,
            "usable_food_count": adapted.usable_food_count,
        }

    def generate_excel_from_ocr_person(
        self,
        person: Mapping[str, Any],
        output_path: str | Path,
        *,
        user_overrides: Mapping[str, Any] | None = None,
        report_date: str | None = None,
        auto_evaluation: bool = True,
        manual_evaluations: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapted = self.adapt_ocr_person(
            person,
            user_overrides=user_overrides,
            report_date=report_date,
            auto_evaluation=auto_evaluation,
            manual_evaluations=manual_evaluations,
        )
        report_data = self.generate_excel_from_json(adapted.payload, output_path)
        return {
            "output_path": str(Path(output_path).resolve()),
            "payload": adapted.payload,
            "report_data": report_data,
            "warnings": adapted.warnings,
            "usable_food_count": adapted.usable_food_count,
        }


def generate_pdf_from_ocr_person(
    person: Mapping[str, Any],
    output_path: str | Path,
    *,
    user_overrides: Mapping[str, Any] | None = None,
    report_date: str | None = None,
    font_path: str | Path | None = None,
    auto_evaluation: bool = True,
    manual_evaluations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """无 Web 框架依赖的便捷函数。`local_service.py` 可直接调用。"""
    return NutritionReportService(font_path=font_path).generate_pdf_from_ocr_person(
        person,
        output_path,
        user_overrides=user_overrides,
        report_date=report_date,
        auto_evaluation=auto_evaluation,
        manual_evaluations=manual_evaluations,
    )


def generate_excel_from_ocr_person(
    person: Mapping[str, Any],
    output_path: str | Path,
    *,
    user_overrides: Mapping[str, Any] | None = None,
    report_date: str | None = None,
    auto_evaluation: bool = True,
    manual_evaluations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """把同一单人 OCR 数据导出为原项目格式的营养分析 Excel。"""
    return NutritionReportService().generate_excel_from_ocr_person(
        person,
        output_path,
        user_overrides=user_overrides,
        report_date=report_date,
        auto_evaluation=auto_evaluation,
        manual_evaluations=manual_evaluations,
    )
