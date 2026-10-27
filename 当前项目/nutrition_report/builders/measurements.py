"""Shared measurement table for modern and legacy PDF reports."""
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle
from ..measurements import body_composition_rows, measurement_text


def body_composition_table(data, normal, header, legacy=False):
    rows = [[Paragraph(t, header) for t in ('项目', '实测结果')]]
    rows.extend([Paragraph(escape(label), normal),
                 Paragraph(escape(measurement_text(value, unit)).replace('²', '<super>2</super>'), normal)]
                for label, value, unit in body_composition_rows(data))
    table = Table(rows, colWidths=[100*mm, 74*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#8D8FB6' if legacy else '#183B4E')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#EDF4F5')]),
        ('GRID', (0,0), (-1,-1), .5, colors.HexColor('#CAD3D9')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    return table
