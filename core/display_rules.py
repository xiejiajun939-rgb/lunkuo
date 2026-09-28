"""全站数字显示口径；计算和排序始终使用原始数值，仅在展示层格式化。"""
from __future__ import annotations

import pandas as pd


MISSING_DISPLAY = "—"


def is_missing(value) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def format_amount(value) -> str:
    return MISSING_DISPLAY if is_missing(value) else f"{float(value):,.2f}"


def format_count(value) -> str:
    return MISSING_DISPLAY if is_missing(value) else f"{float(value):,.0f}"


def format_percent(value) -> str:
    return MISSING_DISPLAY if is_missing(value) else f"{float(value):.2%}"


def format_ratio(value) -> str:
    return MISSING_DISPLAY if is_missing(value) else f"{float(value):,.2f}"
