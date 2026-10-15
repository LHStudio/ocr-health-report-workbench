"""Validated PDF presentation metadata, separate from nutrition calculations."""
from __future__ import annotations


def normalize_report_style(value: object = "modern") -> str:
    """Default to modern only when omitted; reject coercion and unknown values."""
    if not isinstance(value, str) or value not in {"modern", "legacy"}:
        raise ValueError("报告版式仅支持 modern 或 legacy")
    return value
