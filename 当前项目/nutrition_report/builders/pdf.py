"""ReportLab 营养 PDF 构建器，迁移自原项目并修复路径/并发/字体问题。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from xml.sax.saxutils import escape
from ..energy_reference import energy_reference_text
from ..report_checks import energy_summary
from .presentation import evaluation_rows, evaluation_warnings, evaluation_context
from .pdf_legacy import NutritionPDFBuilder as LegacyNutritionPDFBuilder
from ..report_style import normalize_report_style

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect

MACRO_COLORS = ("#756BB1", "#E28C45", "#4C9BB0")
from reportlab.platypus import (
    Flowable,
    BaseDocTemplate,
    Frame,
    PageTemplate,
    KeepTogether,
    HRFlowable,
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
    return f'<font color="#DC2626">{text}</font>' if str(value).strip() in {"不足", "过少", "过多", "建议尽量不吃", "能量占比偏低", "能量占比偏高", "占比偏低", "占比偏高"} else text


def _table_text(value: object, *, alert=True) -> str:
    """Keep percentage units and parenthesized phrases together when wrapping."""
    raw = _as_text(value)
    if alert and raw.strip() == '建议尽量不吃':
        return _evaluation_text(value)
    tokens = re.compile(r'[（(][^（）()]+[）)]|[≥≤约]?\s*[+\-]?\d+(?:\.\d+)?(?:[–—-]\d+(?:\.\d+)?)?\s*(?:%|kcal/天|mg/天|g/天|g/100g)')
    parts = []; start = 0
    for match in tokens.finditer(raw):
        parts.extend([escape(raw[start:match.start()]), '<nobr>' + escape(match.group().replace(' ', '\u00a0')) + '</nobr>'])
        start = match.end()
    parts.append(escape(raw[start:]))
    return ''.join(parts)


_SUGGESTION_UNIT = r'(?:kcal/天|kcal/day|mg/天|g/天|g/kg|个百分点|%|kg|mg|g)(?![A-Za-z/])'
_SUGGESTION_NUMBER = r'\d+(?:\.\d+)?(?:[–—-]\d+(?:\.\d+)?)?'
_SUGGESTION_ATOM = re.compile(_SUGGESTION_NUMBER + r'[^\S\n]*' + _SUGGESTION_UNIT + r'|' + _SUGGESTION_NUMBER + r'|[A-Za-z]+|[^\n]')


def _suggestion_markup(text):
    text = escape(text)
    return re.sub(_SUGGESTION_NUMBER + r'[^\S\n]*' + _SUGGESTION_UNIT,
                  lambda m: '<nobr>' + m.group().replace(' ', '\u00a0') + '</nobr>', text)


class NaturalSuggestionParagraph(Paragraph):
    """Break Chinese at glyph boundaries, but keep each numeric value/unit atomic."""
    def __init__(self, *args, plain_text=None, **kwargs):
        self.plain_text = plain_text
        super().__init__(*args, **kwargs)

    def wrap(self, availWidth, availHeight):
        if self.plain_text is not None:
            style = self.style
            lines = []
            for paragraph in self.plain_text.split('\n'):
                line = []
                for atom in _SUGGESTION_ATOM.findall(paragraph):
                    limit = availWidth - style.leftIndent - style.rightIndent
                    if not lines:
                        limit -= style.firstLineIndent
                    candidate = ''.join(line) + atom
                    if line and pdfmetrics.stringWidth(candidate, style.fontName, style.fontSize) > limit - .1:
                        # Avoid a closing punctuation mark or an opening bracket orphan.
                        carry = []
                        if (atom[0] in '，。；：、！？）】》' or line[-1] in '（【《') and len(line) > 1:
                            carry = [line.pop()]
                            while carry[0][0] in '，。；：、！？）】》' and len(line) > 1:
                                carry.insert(0, line.pop())
                        lines.append(''.join(line).rstrip())
                        line = carry
                        if not line and atom.isspace():
                            continue
                    line.append(atom)
                lines.append(''.join(line).rstrip())
            markup = '<br/>'.join(_suggestion_markup(line) for line in lines)
            Paragraph.__init__(self, markup, style)
        return super().wrap(availWidth, availHeight)


class GenerationDateFooter(Flowable):
    """Attach the date to the last athlete-table page, including split tables."""
    def __init__(self, text, font_name):
        super().__init__()
        self.text, self.font_name = text, font_name
        self.width, self.height = 1, 1

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        # Flowable coordinates are translated; reset to the page coordinate system.
        canvas.resetTransforms()
        canvas.setFont(self.font_name, 9)
        canvas.setFillColor(colors.HexColor('#555555'))
        canvas.drawRightString(A4[0]-18*mm, 11*mm, self.text)
        canvas.restoreState()


class NutritionPDFBuilder:
    def __init__(self, image_dir: str | Path | None = None, font_path: str | Path | None = None):
        # image_dir 保留为兼容旧调用；占比图使用 PDF 原生矢量图，不依赖图片目录。
        _ = image_dir
        self._explicit_font_path = font_path
        self.font_path = self._find_font(font_path)
        # A separate registry name keeps modern/legacy fonts stable in one worker.
        self.font_name = "NutritionReportModernCJK"
        if self.font_path:
            if self.font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(self.font_name, str(self.font_path)))
        else:
            self.font_name = "STSong-Light"
            if self.font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(UnicodeCIDFont(self.font_name))
        self.bold_font_name = self.font_name
        if self.font_path and self.font_path.name.lower() == 'msyh.ttc':
            bold_path = self.font_path.with_name('msyhbd.ttc')
            if bold_path.exists():
                self.bold_font_name = self.font_name + 'Bold'
                if self.bold_font_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(self.bold_font_name, str(bold_path)))
        pdfmetrics.registerFontFamily(
            self.font_name,
            normal=self.font_name,
            bold=self.bold_font_name,
            italic=self.font_name,
            boldItalic=self.bold_font_name,
        )

    @staticmethod
    def _find_font(explicit: str | Path | None) -> Path | None:
        env_font = os.environ.get("NUTRITION_REPORT_FONT")
        candidates = [
            explicit,
            env_font,
            Path("C:/Windows/Fonts/msyh.ttc"),
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
        """Build a content-sized, pageable report without scaling the text."""
        if normalize_report_style(data.get('report_style', 'modern')) == 'legacy':
            return LegacyNutritionPDFBuilder(font_path=self._explicit_font_path).build(data, output_path)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        ink, muted = colors.HexColor('#243746'), colors.HexColor('#637681')
        navy, teal = colors.HexColor('#183B4E'), colors.HexColor('#087F8C')
        line, pale = colors.HexColor('#DCE5E9'), colors.HexColor('#F3F7F8')
        grid = colors.HexColor('#CAD3D9')
        width = 174 * mm
        normal = ParagraphStyle('NutritionNormal', fontName=self.font_name,
            fontSize=10.5, leading=15.5, alignment=1, textColor=ink, wordWrap='CJK')
        left = ParagraphStyle('NutritionLeft', parent=normal, alignment=0)
        profile_label = ParagraphStyle('NutritionProfileLabel', parent=left, textColor=muted)
        profile_value = ParagraphStyle('NutritionProfileValue', parent=left)
        quality = ParagraphStyle('NutritionQuality', parent=left, fontSize=9, leading=13, textColor=muted)
        title = ParagraphStyle('NutritionTitle', parent=normal, fontName=self.bold_font_name,
            fontSize=18, leading=25, textColor=navy, spaceAfter=12, keepWithNext=True)
        header = ParagraphStyle('NutritionHeader', parent=normal,
            fontName=self.bold_font_name, textColor=colors.white)
        category_style = ParagraphStyle('NutritionCategory', parent=normal, textColor=navy)
        subhead = ParagraphStyle('NutritionSubheading', parent=left, fontName=self.bold_font_name,
            fontSize=12, leading=18, textColor=teal, spaceBefore=14, spaceAfter=6, keepWithNext=True)

        doc = BaseDocTemplate(str(output), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
            topMargin=16*mm, bottomMargin=20*mm, title='营养健康评估报告', author='OCR 营养报告系统')
        def furniture(canvas, document):
            canvas.saveState()
            canvas.setFont(self.font_name, 8)
            canvas.setFillColor(muted)
            canvas.setStrokeColor(line)
            canvas.setLineWidth(.5)
            canvas.line(18*mm, 16*mm, A4[0]-18*mm, 16*mm)
            canvas.setFont(self.font_name, 8)
            canvas.drawString(18*mm, 10*mm, f'{document.page:02d}')
            canvas.restoreState()
        frame = Frame(18*mm, 20*mm, width, A4[1]-36*mm,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates(PageTemplate(id='Nutrition', frames=[frame], onPageEnd=furniture))

        def heading(label, section=None):
            p = Paragraph(escape(label), title)
            p.report_section = section or label
            return p

        story = [heading('营养健康评估报告', '食物摄入量评估报告')]
        user = data.get('user') or {}
        def profile_cell(label, value):
            return Paragraph(escape(label), profile_label), Paragraph(escape(_as_text(value)), profile_value)
        age = _as_text(user.get('age')).strip()
        ffm = _as_text(user.get('fatFreeMass')).strip()
        profile = Table([
            [*profile_cell('姓名', user.get('name') or ''), *profile_cell('年龄', age+' 岁' if age else '')],
            [*profile_cell('项目种类', user.get('projectType') or ''), *profile_cell('训练年限', user.get('trainingYears') or '')],
            [*profile_cell('当前状态', user.get('currentStatus') or ''), *profile_cell('去脂体重（瘦体重）', ffm+' kg' if ffm else '')],
        ], colWidths=[30*mm, 57*mm, 43*mm, 44*mm], splitInRow=1)
        profile.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),pale),
            ('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),10),
            ('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
            ('GRID',(0,0),(-1,-1),.5,grid)]))
        story.extend([profile, Spacer(1, 12)])
        if data.get('assessment_status') == 'needs_review':
            story.extend([Paragraph('待核对：存在未换算食物，本报告不是完整营养结论；具体条目见最后的整体评估及建议。', quality), Spacer(1, 6)])
        categories = ['谷类','薯类','蔬菜','水果','畜禽肉','水产品','蛋类','豆类','坚果','奶类','零食','运动营养食品','饮料','酒类']
        story.append(self._build_food_report(data, categories, normal=normal, header=header,
            category_style=category_style, suggestions=None))

        story.extend([PageBreak(), heading('能量及钙摄入量评估报告')])
        nutrition = data.get('nutrition') or {}
        energy, calcium = nutrition.get('energy') or {}, nutrition.get('calcium') or {}
        energy_rows = [[Paragraph(t, header) for t in ['项目','摄入量 / 参考值','评价']],
            [Paragraph('总能量摄入量',normal), Paragraph(self._format_energy_intake(energy),normal),
                Paragraph(_evaluation_text(energy.get('evaluation','-')),normal)],
            [Paragraph('钙',normal), Paragraph(f"{escape(_as_text(calcium.get('value',0)))} mg/day",normal),
                Paragraph(_evaluation_text(calcium.get('evaluation','-')),normal)]]
        energy_table = Table(energy_rows, colWidths=[42*mm,101*mm,31*mm], repeatRows=1, splitInRow=1)
        energy_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy),
            ('BACKGROUND',(0,1),(0,-1),pale),('LINEBELOW',(0,0),(-1,-1),.5,grid),
            ('BOX',(0,0),(-1,-1),.5,grid),('INNERGRID',(0,1),(-1,-1),.5,grid),
            ('INNERGRID',(0,0),(-1,0),.6,colors.white),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),10),
            ('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
        story.append(energy_table)
        macro_summary = Table([[self._build_macro_energy_legend(nutrition,left),self._build_macro_energy_chart(nutrition)]],
            colWidths=[91*mm,83*mm])
        macro_summary.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('BACKGROUND',(0,0),(-1,-1),pale),('LEFTPADDING',(0,0),(-1,-1),12),
            ('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
        story.extend([Paragraph('三大营养素供能占比',subhead), macro_summary,
            Paragraph('解读',subhead), Paragraph(self._interpretation(data),left)])
        note_style = ParagraphStyle('NutritionNote', parent=left, fontSize=9, leading=14,
            textColor=muted, borderColor=line, borderWidth=.5, borderPadding=9, backColor=colors.white,
            spaceBefore=16, spaceAfter=0)
        note = escape(_as_text(data.get('nutrition_disclaimer') or '以上营养成分仅根据记录饮食计算，不包含其他补充剂摄入。'))
        story.append(Paragraph('<b>说明</b>  '+note, note_style))

        if evaluation_rows(data):
            story.extend([PageBreak(),heading('运动员专项膳食评价')])
            if evaluation_context(data):
                story.append(Paragraph(escape(evaluation_context(data)),quality))
            for warning in evaluation_warnings(data):
                story.append(Paragraph(escape(warning),quality))
            story.append(Spacer(1,10))
            evaluation_body = ParagraphStyle('EvaluationBody',parent=normal,leading=14)
            target_body = ParagraphStyle('EvaluationTarget',parent=evaluation_body,alignment=1,textColor=colors.black)
            rows = [[Paragraph(t,header) for t in ['项目','实际摄入','参考目标','差值','最终评价']]]
            for row in evaluation_rows(data):
                actual = '—' if row['actual'] is None else f"{row['actual']:g} {row['unit']}"
                target_cell = [Paragraph(_table_text(row['target'],alert=False),target_body)]
                if row.get('note'):
                    note = re.sub(r'([（(])',r'<br/>\1',escape(row['note']))
                    target_cell.append(Paragraph(note,target_body))
                label = re.sub(r'([（(])',r'<br/>\1',_table_text(row['label']))
                rows.append([Paragraph(label,evaluation_body),Paragraph(_table_text(actual),evaluation_body),
                    target_cell,Paragraph('—' if row['gap'] is None else f"{row['gap']:+g}",evaluation_body),
                    Paragraph(_evaluation_text(row['evaluation']),evaluation_body)])
            table = Table(rows,colWidths=[34*mm,30*mm,62*mm,20*mm,28*mm],repeatRows=1,splitInRow=1)
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,pale]),
                ('LINEBELOW',(0,0),(-1,-1),.5,grid),('VALIGN',(0,0),(-1,-1),'TOP'),
                ('BOX',(0,0),(-1,-1),.5,grid),('INNERGRID',(0,1),(-1,-1),.5,grid),
                ('INNERGRID',(0,0),(-1,0),.6,colors.white),
                ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
            story.append(table)

        if data.get('include_quality_page') is True:
            story.extend([PageBreak(),heading('OCR 换算与数据质量说明')])
            story.append(Paragraph('食物频率已折算为日均摄入量；无法可靠确定频率、次数或克数的项目不会静默计入。以下项目请在使用报告前复核。',left))
            messages = [i.get('message',i) if isinstance(i,dict) else i for i in data.get('conversion_warnings') or []]
            messages.extend(f"{i.get('name','未知食物')}未在营养数据库中匹配" for i in data.get('unmatched_foods') or [] if isinstance(i,dict))
            messages = list(dict.fromkeys(_as_text(i) for i in messages if _as_text(i)))
            story.append(Spacer(1,10))
            for index,message in enumerate(messages or ['未发现额外的 OCR 换算警示。'],1):
                story.extend([Paragraph(f'{index}. {escape(message)}',left),Spacer(1,6)])
            source = data.get('food_data_source') or {}
            story.append(Paragraph('报告数据记录',subhead))
            source_lines = [f"营养数据来源：{_as_text(source.get('label') or '未记录')}",
                f"查询时间：{_as_text(source.get('queried_at') or '-')}",f"云端地址：{_as_text(source.get('base_url') or '-')}",
                f"云端状态：{_as_text(source.get('message') or '未记录')}",f"人员文件夹：{_as_text(data.get('source_person_id') or '-')}" ]
            if source.get('error'): source_lines.append(f"回退原因：{_as_text(source['error'])}")
            for item in source_lines: story.extend([Paragraph(escape(item),quality),Spacer(1,4)])
        story.extend([PageBreak(), heading('整体评估及建议', '食物摄入量评估报告 · 整体评估及建议')])
        advice = ParagraphStyle('NutritionSuggestionFlow', parent=left, leading=16,
            leftIndent=19, firstLineIndent=-19, spaceAfter=9)
        alerts = (data.get('report_checks') or {}).get('warnings') or []
        if alerts:
            story.append(Paragraph('自动核查提醒', advice))
            for message in alerts:
                story.append(Paragraph(escape(_as_text(message)), advice))
            story.append(Spacer(1, 6))
        for index, item in enumerate(data.get('suggestions') or ['暂无自动建议'], 1):
            plain = f'{index}. {_as_text(item)}'
            story.append(NaturalSuggestionParagraph(_suggestion_markup(plain), advice, plain_text=plain))

        story.append(GenerationDateFooter('报告生成日期：'+str(data.get('generated_at') or data.get('generated_date') or ''),self.font_name))
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
                equivalent_text = '-' if equivalent is None else f'{equivalent:.2f}'.rstrip('0').rstrip('.') + ' g'
                amount_text += '<br/>鲜奶等价量（按蛋白质估计）：<nobr>' + equivalent_text + '</nobr>'
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
                fontSize=10.5, leading=16, leftIndent=14, firstLineIndent=-14)
            for index, item in enumerate(suggestions or ['暂无自动建议'], 1):
                plain = f'{index}. {_as_text(item)}'
                table_data.append([NaturalSuggestionParagraph(_suggestion_markup(plain), suggestion_style,
                                                               plain_text=plain), '', ''])
        row_heights: list[float | None] = [None] * (2 if categories else 1) + [None] * len(categories)
        if suggestions is not None:
            row_heights.extend([9 * mm] + [None] * max(1, len(suggestions)))
        report = Table(
            table_data,
            colWidths=[39 * mm, 81 * mm, 54 * mm],
            rowHeights=row_heights,
            repeatRows=2 if categories else 1,
            splitInRow=1 if categories else 0,
        )
        style = [
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#183B4E")),
            ("BACKGROUND", (0, 2), (0, len(categories)+1), colors.HexColor("#EDF4F5")),
            ("TEXTCOLOR", (0, 0), (-1, 1), colors.white),
            ("TEXTCOLOR", (0, 2), (0, len(categories)+1), colors.white),
            ("LINEBELOW", (0, 0), (-1, len(categories)+1), 0.5, colors.HexColor("#CAD3D9")),
            ("BOX", (0, 0), (-1, len(categories)+1), 0.5, colors.HexColor("#CAD3D9")),
            ("INNERGRID", (0, 0), (-1, 1), 0.6, colors.white),
            ("FONTNAME", (0, 0), (-1, -1), self.font_name),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]
        if categories:
            style.append(("INNERGRID", (0, 2), (-1, len(categories)+1), 0.5, colors.HexColor("#CAD3D9")))
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
        if energy.get('reference_type') == 'bmr':
            return f"{value} kcal/day<br/>建议能量区间 {escape(energy_reference_text(energy))} kcal/天<br/>BMR（填写区间）"
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

    @classmethod
    def _build_macro_energy_legend(cls, nutrition: dict, style: ParagraphStyle):
        text = cls._format_macro_energy(nutrition)
        if sum(cls._macro_energy_values(nutrition)[1]) <= 0:
            return Paragraph(text, style)
        rows = []
        for color, label in zip(MACRO_COLORS, text.split("<br/>")):
            swatch = Drawing(8, 8)
            swatch.add(Rect(0, 0, 8, 8, fillColor=colors.HexColor(color), strokeColor=None))
            rows.append([swatch, Paragraph(label, style)])
        legend = Table(rows, colWidths=[6 * mm, 76 * mm])
        legend.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return legend

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
        # Twice the preview's 78pt diameter, within the padded 83mm chart cell.
        drawing = Drawing(73 * mm, 164)
        if total <= 0:
            return drawing

        pie = Pie()
        pie.x = (drawing.width - 156) / 2
        pie.y = 4
        pie.width = 156
        pie.height = 156
        pie.data = list(calories)
        pie.labels = [f"{value / total * 100:.1f}%" for value in calories]
        pie.startAngle = 90
        pie.direction = "clockwise"
        pie.slices.labelRadius = 0.62
        pie.slices.fontName = "Helvetica-Bold"
        pie.slices.fontSize = 11
        pie.slices.fontColor = colors.white
        pie.slices.strokeColor = colors.white
        pie.slices.strokeWidth = 0.8
        for index, color in enumerate(MACRO_COLORS):
            pie.slices[index].fillColor = colors.HexColor(color)
        drawing.add(pie)
        return drawing

    @staticmethod
    def _interpretation(data: dict) -> str:
        if data.get("interpretation"):
            return "<br/>".join(escape(line.strip()) for line in _as_text(data["interpretation"]).splitlines() if line.strip())
        if data.get('energy_guidance'):
            if data.get('assessment_status') == 'needs_review':
                return escape(data['energy_guidance'])
            return escape(energy_summary(data) + '各类食物按个人营养目标与实际摄入独立比较，不按总能量方向统一增减主食。')
        nutrition = data.get("nutrition") or {}
        lines = []
        energy_evaluation = (nutrition.get("energy") or {}).get("evaluation")
        calcium_evaluation = (nutrition.get("calcium") or {}).get("evaluation")
        if energy_evaluation in {"不足", "过少"}:
            lines.append("总能量摄入不足，需结合训练量调整全天饮食。")
        elif energy_evaluation == "过多":
            lines.append("能量摄入过多，应适当控制总能量摄入")
        carb = next((r for r in (data.get('athlete_evaluation') or {}).get('rows', []) if r['key'] == 'carbohydrate'), {})
        grains = next((r for r in (data.get('food_standard_evaluation') or {}).get('rows', []) if r['key'] == 'grains_remainder'), {})
        if carb.get('evaluation') == '不足':
            lines.append('碳水化合物营养素摄入不足，需结合训练量补充碳水来源。')
        if grains.get('evaluation_basis') == 'ratio' and grains.get('evaluation') in {'过多', '能量占比偏高'}:
            lines.append('谷类在主食总能量中占比偏高；建议增加豆类、薯类的搭配。')
        if calcium_evaluation == "不足":
            lines.append("钙摄入不足，应增加奶制品摄入")
        return "<br/>".join(lines) or "暂无"
