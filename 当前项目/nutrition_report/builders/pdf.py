"""ReportLab 营养 PDF 构建器，迁移自原项目并修复路径/并发/字体问题。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from xml.sax.saxutils import escape
from .presentation import evaluation_rows, evaluation_warnings, evaluation_context

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _as_text(value: object) -> str:
    return "" if value is None else str(value)


def _evaluation_text(value: object) -> str:
    text = escape(_as_text(value))
    return f'<font color="#DC2626">{text}</font>' if str(value).strip() in {"不足", "过多", "建议尽量不吃", "能量占比偏低", "能量占比偏高"} else text


def _table_text(value: object, *, alert=True) -> str:
    """Keep percentage units and parenthesized phrases together when wrapping."""
    raw = _as_text(value)
    if alert and raw.strip() == '建议尽量不吃':
        return _evaluation_text(value)
    tokens = re.compile(r'[（(][^（）()]+[）)]|[≥≤约]?\s*[+\-]?\d+(?:\.\d+)?(?:[–—-]\d+(?:\.\d+)?)?\s*(?:%|mg/天|g/天|g/100g)')
    parts = []; start = 0
    for match in tokens.finditer(raw):
        parts.extend([escape(raw[start:match.start()]), '<nobr>' + escape(match.group()) + '</nobr>'])
        start = match.end()
    parts.append(escape(raw[start:]))
    return ''.join(parts)


class NutritionPDFBuilder:
    def __init__(self, image_dir: str | Path | None = None, font_path: str | Path | None = None):
        # image_dir 保留为兼容旧调用；占比图使用 PDF 原生矢量图，不依赖图片目录。
        _ = image_dir
        self.font_path = self._find_font(font_path)
        self.font_name = "NutritionReportCJK"
        if self.font_path:
            if self.font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(self.font_name, str(self.font_path)))
        else:
            self.font_name = "STSong-Light"
            if self.font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(UnicodeCIDFont(self.font_name))
        pdfmetrics.registerFontFamily(
            self.font_name,
            normal=self.font_name,
            bold=self.font_name,
            italic=self.font_name,
            boldItalic=self.font_name,
        )

    @staticmethod
    def _find_font(explicit: str | Path | None) -> Path | None:
        env_font = os.environ.get("NUTRITION_REPORT_FONT")
        candidates = [
            explicit,
            env_font,
            Path("C:/Windows/Fonts/simhei.ttf"),
            Path("C:/Windows/Fonts/msyh.ttf"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        return None

    def build(self, data: dict, output_path: str | Path) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(output),
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title="营养健康评估报告",
            author="OCR 营养报告系统",
        )
        normal = ParagraphStyle(
            "NutritionNormal",
            fontName=self.font_name,
            fontSize=10.5,
            leading=13,
            alignment=1,
        )
        left = ParagraphStyle(
            "NutritionLeft",
            parent=normal,
            alignment=0,
        )
        quality = ParagraphStyle(
            "NutritionQuality",
            parent=left,
            fontSize=9.5,
            leading=13,
        )
        title = ParagraphStyle(
            "NutritionTitle",
            parent=normal,
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#7E74B7"),
        )
        profile = ParagraphStyle(
            "NutritionProfile",
            parent=normal,
            fontSize=10.5,
            leading=14,
            alignment=0,
        )
        header = ParagraphStyle(
            "NutritionHeader",
            parent=normal,
            textColor=colors.white,
        )
        category_style = ParagraphStyle(
            "NutritionCategory",
            parent=normal,
            textColor=colors.white,
        )
        story = [Paragraph("营养健康评估报告", title), Spacer(1, 3 * mm)]

        user = data.get("user") or {}
        age = _as_text(user.get("age")).strip()
        age_display = f"{escape(age)} 岁" if age else ""
        fat_free_mass = _as_text(user.get("fatFreeMass")).strip()
        fat_free_mass_display = f"{escape(fat_free_mass)} kg" if fat_free_mass else ""
        label_color = "#7E74B7"

        def profile_line(label: str, value: object) -> Paragraph:
            return Paragraph(
                f'<font color="{label_color}"><b>{escape(label)}：</b></font> {escape(_as_text(value))}',
                profile,
            )

        profile_table = Table(
            [
                [profile_line("姓名", user.get("name") or ""), profile_line("年龄", age_display)],
                [profile_line("项目种类", user.get("projectType") or ""), profile_line("训练年限", user.get("trainingYears") or "")],
                [profile_line("当前状态", user.get("currentStatus") or ""), profile_line("去脂体重（瘦体重）", fat_free_mass_display)],
            ],
            colWidths=[87 * mm, 87 * mm],
        )
        profile_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), self.font_name),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.extend([profile_table, Spacer(1, 6 * mm)])

        page_groups = [
            ["谷类", "薯类", "蔬菜", "水果", "畜禽肉", "水产品", "蛋类", "豆类", "坚果", "奶类", "零食", "运动营养食品", "饮料", "酒类"],
            [],
        ]
        for page_index, categories in enumerate(page_groups):
            if page_index:
                story.append(PageBreak())
            story.append(self._build_food_report(
                data,
                categories,
                normal=normal,
                header=header,
                category_style=category_style,
                suggestions=(data.get("suggestions") or []) if page_index == len(page_groups) - 1 else None,
            ))
        story.append(PageBreak())

        nutrition = data.get("nutrition") or {}
        energy = nutrition.get("energy") or {}
        calcium = nutrition.get("calcium") or {}
        macro_summary = Table(
            [[
                Paragraph(self._format_macro_energy(nutrition), left),
                self._build_macro_energy_chart(nutrition),
            ]],
            colWidths=[58 * mm, 78 * mm],
            rowHeights=[30 * mm],
        )
        macro_summary.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        energy_table = [
            [Paragraph("能量及钙摄入量评估报告", header), "", ""],
            [Paragraph("项目", header), Paragraph("摄入量", header), Paragraph("评价", header)],
            [
                Paragraph("总能量摄入量", category_style),
                Paragraph(self._format_energy_intake(energy), normal),
                Paragraph(_evaluation_text(energy.get("evaluation", "-")), normal),
            ],
            [Paragraph("三大营养素供能占比", category_style), macro_summary, ""],
            [
                Paragraph("钙", category_style),
                Paragraph(f"{escape(_as_text(calcium.get('value', 0)))} mg/day", normal),
                Paragraph(_evaluation_text(calcium.get("evaluation", "-")), normal),
            ],
            [Paragraph("解读", category_style), Paragraph(self._interpretation(data), left), ""],
            [
                Paragraph("说明", category_style),
                Paragraph(escape(_as_text(data.get("nutrition_disclaimer") or "以上营养成分仅根据记录饮食计算，不包含其他补充剂摄入。")), left),
                "",
            ],
        ]
        energy_report = Table(
            energy_table,
            colWidths=[38 * mm, 108 * mm, 28 * mm],
            rowHeights=[12 * mm, 10 * mm, 28 * mm, 55 * mm, 20 * mm, None, None],
            repeatRows=2,
        )
        energy_style = TableStyle([
            ("SPAN", (0, 0), (-1, 0)),
            ("SPAN", (1, 3), (2, 3)),
            ("SPAN", (1, 5), (2, 5)),
            ("SPAN", (1, -1), (2, -1)),
            ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#BFC4D7")),
            ("BACKGROUND", (0, 2), (0, -1), colors.HexColor("#8D8FB6")),
            ("TEXTCOLOR", (0, 0), (-1, 1), colors.white),
            ("TEXTCOLOR", (0, 2), (0, -1), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
            ("FONTNAME", (0, 0), (-1, -1), self.font_name),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("VALIGN", (1, -1), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])
        energy_report.setStyle(energy_style)
        # Measure wrapped paragraphs first: interpretation/disclaimer never use a fixed short height.
        energy_report.wrap(doc.width, doc.height)
        measured = list(energy_report._rowHeights)
        spare = max(0, doc.height - 12 - sum(measured))
        measured[5] += spare * 0.8
        measured[6] += spare * 0.2
        energy_report = Table(energy_table, colWidths=[38 * mm, 108 * mm, 28 * mm],
                              rowHeights=measured, repeatRows=2)
        energy_report.setStyle(energy_style)
        story.append(energy_report)

        athlete = data.get("athlete_evaluation")
        if evaluation_rows(data):
            story.extend([PageBreak(), Paragraph("运动员专项膳食评价", title)])
            if evaluation_context(data):
                story.append(Paragraph(escape(evaluation_context(data)), quality))
            for line in evaluation_warnings(data):
                story.append(Paragraph(escape(line), quality))
            evaluation_body = ParagraphStyle('EvaluationBody', parent=normal, fontSize=9.5, leading=12)
            final_body = ParagraphStyle('FinalEvaluationBody', parent=evaluation_body, fontSize=8.5, leading=11)
            rows = [[Paragraph(text, header) for text in ["项目", "实际摄入", "参考目标", "差值", "最终评价"]]]
            for row in evaluation_rows(data):
                actual = "—" if row["actual"] is None else f"{row['actual']:g} {row['unit']}"
                # Give the reference value its own line; a long note must not pull its unit away.
                target_cell = [Paragraph(_table_text(row['target'], alert=False), evaluation_body)]
                if row.get('note'):
                    note = re.sub(r'([（(])', r'<br/>\1', escape(row['note']))
                    target_cell.append(Paragraph(note, evaluation_body))
                label = re.sub(r'([（(])', r'<br/>\1', _table_text(row['label']))
                rows.append([Paragraph(label, evaluation_body), Paragraph(_table_text(actual), evaluation_body), target_cell,
                             Paragraph("—" if row["gap"] is None else f"{row['gap']:+g}", evaluation_body),
                             Paragraph(_evaluation_text(row['evaluation']), final_body)])
            table = Table(rows, colWidths=[34*mm, 30*mm, 70*mm, 20*mm, 22*mm], repeatRows=1)
            table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F75B5")), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
            story.extend([Spacer(1, 3*mm), table])


        warnings = data.get("conversion_warnings") or []
        unmatched = data.get("unmatched_foods") or []
        source = data.get("food_data_source") or {}
        story.extend([PageBreak(), Paragraph("OCR 换算与数据质量说明", ParagraphStyle("QualityTitle", parent=title, fontSize=14, leading=17)), Spacer(1, 2 * mm)])
        story.append(Paragraph(
            "食物频率已折算为日均摄入量；无法可靠确定频率、次数或克数的项目不会静默计入。以下项目请在使用报告前复核。",
            quality,
        ))
        story.append(Spacer(1, 1 * mm))
        messages = [item.get("message", item) if isinstance(item, dict) else item for item in warnings]
        messages.extend(f"{item.get('name', '未知食物')}未在营养数据库中匹配" for item in unmatched if isinstance(item, dict))
        unique_messages = list(dict.fromkeys(_as_text(item) for item in messages if _as_text(item)))
        if not unique_messages:
            story.append(Paragraph("未发现额外的 OCR 换算警示。", quality))
        for index, message in enumerate(unique_messages, 1):
            story.append(Paragraph(f"{index}. {escape(message)}", quality))
            story.append(Spacer(1, 0.4 * mm))
        source_lines = [
            f"营养数据来源：{_as_text(source.get('label') or '未记录')}",
            f"查询时间：{_as_text(source.get('queried_at') or '-')}",
            f"云端地址：{_as_text(source.get('base_url') or '-')}",
            f"云端状态：{_as_text(source.get('message') or '未记录')}",
            f"人员文件夹：{_as_text(data.get('source_person_id') or '-')}",
        ]
        if source.get("error"):
            source_lines.append(f"回退原因：{_as_text(source.get('error'))}")
        story.extend([Spacer(1, 2 * mm), Paragraph("报告数据记录", quality), Spacer(1, 0.5 * mm)])
        for line in source_lines:
            story.append(Paragraph(escape(line), quality))
            story.append(Spacer(1, 0.3 * mm))

        doc.build(story)

    def _build_food_report(
        self,
        data: dict,
        categories: list[str],
        *,
        normal: ParagraphStyle,
        header: ParagraphStyle,
        category_style: ParagraphStyle,
        suggestions: list | None = None,
    ) -> Table:
        table_data = [
            [Paragraph("食物摄入量评估报告", header), "", ""],
            [Paragraph("种类", header), Paragraph("每日摄入量", header), Paragraph("评价", header)],
        ]
        if not categories:
            table_data.pop()  # Suggestions-only page has no food column headings.
        results = data.get("category_result") or {}
        for category in categories:
            # 当前问卷没有运动营养食品摄入量字段；仅保留标准模板版式，不虚构评价。
            default_info = {"value": "-", "evaluation": "-"} if category == "运动营养食品" else {"value": 0, "evaluation": "-"}
            info = results.get(category) or default_info
            value = info.get("value", 0)
            amount_text = "-" if value in (None, "", "-") else f"{escape(_as_text(value))} g"
            if category == '奶类' and 'equivalent_value' in info:
                equivalent = info['equivalent_value']
                amount_text += '<br/>鲜奶等价量（按蛋白质估计）：' + ('-' if equivalent is None else f'{equivalent:g} g')
            table_data.append([
                Paragraph(escape(category), category_style),
                Paragraph(amount_text, normal),
                Paragraph(_evaluation_text(info.get("evaluation", "-")), normal),
            ])
        if suggestions is not None:
            suggestion_start = len(table_data)
            table_data.append([Paragraph('整体评估及建议', ParagraphStyle(
                'NutritionSuggestionHeading', parent=category_style, alignment=0)), '', ''])
            suggestion_style = ParagraphStyle('NutritionSuggestion', parent=normal, alignment=0,
                fontSize=10, leading=15, leftIndent=14, firstLineIndent=-14)
            for index, item in enumerate(suggestions or ['暂无自动建议'], 1):
                text = escape(_as_text(item)).replace('\n', '<br/>')
                # 数值与单位整体换行，避免把 g/天 或 mg/天拆成碎片。
                text = re.sub(r'(?<![\w.])\d+(?:\.\d+)?\s*(?:kcal/天|kcal/day|mg/天|g/天|g/kg|个百分点|%|kg|mg|g)(?![A-Za-z/])',
                              lambda match: '<nobr>' + match.group(0) + '</nobr>', text)
                table_data.append([Paragraph(f'{index}. {text}', suggestion_style), '', ''])
        row_heights: list[float | None] = ([11 * mm, 9 * mm] if categories else [11 * mm]) + [17 * mm if c == '奶类' else 11 * mm for c in categories]
        if suggestions is not None:
            row_heights.extend([9 * mm] + [None] * max(1, len(suggestions)))
        report = Table(
            table_data,
            colWidths=[57 * mm, 72 * mm, 45 * mm],
            rowHeights=row_heights,
            repeatRows=2 if categories else 1,
        )
        style = [
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#BFC4D7")),
            ("BACKGROUND", (0, 2), (0, len(categories)+1), colors.HexColor("#8D8FB6")),
            ("TEXTCOLOR", (0, 0), (-1, 1), colors.white),
            ("TEXTCOLOR", (0, 2), (0, len(categories)+1), colors.white),
            ("GRID", (0, 0), (-1, len(categories)+1), 0.5, colors.HexColor("#D9D9D9")),
            ("FONTNAME", (0, 0), (-1, -1), self.font_name),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if suggestions is not None:
            for row_index in range(suggestion_start, len(table_data)):
                style.append(('SPAN', (0, row_index), (-1, row_index)))
            style.extend([
                ('BOX', (0, suggestion_start), (-1, -1), 0.5, colors.HexColor('#D9D9D9')),
                ('BACKGROUND', (0, suggestion_start), (-1, suggestion_start), colors.HexColor('#8D8FB6')),
                ('VALIGN', (0, suggestion_start+1), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, suggestion_start), (-1, -1), 10),
                ('RIGHTPADDING', (0, suggestion_start), (-1, -1), 10),
                ('TOPPADDING', (0, suggestion_start+1), (-1, -1), 5),
                ('BOTTOMPADDING', (0, suggestion_start+1), (-1, -1), 5),
            ])
        report.setStyle(TableStyle(style))
        return report

    @staticmethod
    def _format_energy_intake(energy: dict) -> str:
        value = escape(_as_text(energy.get("value", "-")))
        standard = energy.get("standard")
        if standard not in (None, ""):
            return f"{value} kcal/day<br/>推荐能量 {escape(_as_text(standard))} kcal/天<br/>{escape(_as_text(energy.get('activity_label')))}（女性EER）"
        return f"{value} kcal/day"

    @staticmethod
    def _format_macro_energy(nutrition: dict) -> str:
        grams, calories = NutritionPDFBuilder._macro_energy_values(nutrition)
        total = sum(calories)
        if total <= 0:
            return "暂无可计算的三大营养素数据"
        names = ("蛋白质", "脂肪", "碳水")
        return "<br/>".join(
            f"{name} {gram:g}g（{calorie / total * 100:.1f}%）"
            for name, gram, calorie in zip(names, grams, calories)
        )

    @staticmethod
    def _macro_energy_values(nutrition: dict) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        grams = (
            float(nutrition.get("protein") or 0),
            float(nutrition.get("fat") or 0),
            float(nutrition.get("carbohydrate") or 0),
        )
        return grams, (grams[0] * 4, grams[1] * 9, grams[2] * 4)

    @classmethod
    def _build_macro_energy_chart(cls, nutrition: dict) -> Drawing:
        """构建直接写入 PDF 的矢量饼图，避免磁盘临时图片和并发覆盖。"""
        _, calories = cls._macro_energy_values(nutrition)
        total = sum(calories)
        drawing = Drawing(78 * mm, 30 * mm)
        if total <= 0:
            return drawing

        pie = Pie()
        pie.x = 68
        pie.y = 3
        pie.width = 78
        pie.height = 78
        pie.data = list(calories)
        pie.labels = [f"{value / total * 100:.1f}%" for value in calories]
        pie.startAngle = 90
        pie.direction = "clockwise"
        pie.slices.labelRadius = 0.62
        pie.slices.fontName = "Helvetica-Bold"
        pie.slices.fontSize = 8
        pie.slices.fontColor = colors.white
        pie.slices.strokeColor = colors.white
        pie.slices.strokeWidth = 0.8
        for index, color in enumerate(("#756BB1", "#E28C45", "#4C9BB0")):
            pie.slices[index].fillColor = colors.HexColor(color)
        drawing.add(pie)
        return drawing

    @staticmethod
    def _interpretation(data: dict) -> str:
        if data.get("interpretation"):
            return "<br/>".join(escape(line.strip()) for line in _as_text(data["interpretation"]).splitlines() if line.strip())
        nutrition = data.get("nutrition") or {}
        lines = []
        energy_evaluation = (nutrition.get("energy") or {}).get("evaluation")
        calcium_evaluation = (nutrition.get("calcium") or {}).get("evaluation")
        if energy_evaluation == "不足":
            lines.append("总能量摄入不足，需结合训练量调整全天饮食。")
        elif energy_evaluation == "过多":
            lines.append("能量摄入过多，应适当控制总能量摄入")
        carb = next((r for r in (data.get('athlete_evaluation') or {}).get('rows', []) if r['key'] == 'carbohydrate'), {})
        grains = next((r for r in (data.get('food_standard_evaluation') or {}).get('rows', []) if r['key'] == 'grains_remainder'), {})
        if carb.get('evaluation') == '不足':
            lines.append('碳水化合物营养素摄入不足，需结合训练量补充碳水来源。')
        if grains.get('evaluation') == '过多':
            lines.append('谷类在主食总能量中占比偏高；建议增加豆类、薯类的搭配。')
        if calcium_evaluation == "不足":
            lines.append("钙摄入不足，应增加奶制品摄入")
        return "<br/>".join(lines) or "暂无"
