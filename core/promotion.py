# -*- coding: utf-8 -*-
from datetime import date, timedelta
import math
from pathlib import Path
import re

import pandas as pd
import streamlit as st

from core.db import init_supabase


DAILY_TABLE_NAME = "promotion_product_daily"
PAGE_SIZE = 1000
COLUMN_MAP = {
    "商品ID": "product_id", "商品名称": "product_name",
    "整体展示次数": "impressions", "整体点击次数": "clicks",
    "整体点击率": "ctr", "整体转化率": "conversion_rate",
    "整体消耗": "spend", "整体成交金额": "gross_gmv",
    "整体成交订单数": "gross_orders", "整体支付ROI": "gross_roi",
    "整体成交订单成本": "gross_order_cost", "用户实际支付金额": "user_paid_amount",
    "智能优惠券金额": "coupon_amount", "电商平台补贴金额": "platform_subsidy",
}
REQUIRED_SOURCE_COLUMNS = {"商品ID", "商品名称"}
NUMERIC_COLUMNS = [
    "impressions", "clicks", "ctr", "conversion_rate", "spend", "gross_gmv",
    "gross_orders", "gross_roi", "gross_order_cost", "user_paid_amount",
    "coupon_amount", "platform_subsidy",
]
PERCENT_COLUMNS = {"ctr", "conversion_rate"}
PROMOTION_FILENAME_RE = re.compile(
    r"^(?P<shop>.+)_商品_(?P<date>\d{4}-\d{2}-\d{2})\.(?:xlsx|xls)$", re.IGNORECASE
)
STYLE_CODE_RE = re.compile(r"([A-Za-z]\d{3}[A-Za-z]\d{3})")


def parse_promotion_filename(filename: str) -> tuple[str, date]:
    name = Path(str(filename or "")).name
    match = PROMOTION_FILENAME_RE.match(name)
    if not match:
        raise ValueError("文件名必须为“店铺名_商品_YYYY-MM-DD.xlsx”；素材文件不会导入。")
    return match.group("shop").strip().upper(), date.fromisoformat(match.group("date"))


def _numeric(series, percent=False):
    text = (series.astype("string").fillna("0").str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False).str.strip())
    values = pd.to_numeric(text, errors="coerce").fillna(0.0)
    if percent:
        values = values / 100.0
    return values.replace([float("inf"), float("-inf")], 0.0)


def parse_daily_promotion_file(file_obj, source_file: str):
    shop_name, report_date = parse_promotion_filename(source_file)
    source = pd.read_excel(file_obj)
    missing = sorted(REQUIRED_SOURCE_COLUMNS - set(source.columns))
    if missing:
        raise ValueError(f"文件缺少必要列：{', '.join(missing)}")
    available = {name: target for name, target in COLUMN_MAP.items() if name in source.columns}
    result = source[list(available)].rename(columns=available).copy()
    for target in COLUMN_MAP.values():
        if target not in result.columns:
            result[target] = 0.0 if target in NUMERIC_COLUMNS else ""
    result["product_id"] = result["product_id"].astype("string").fillna("").str.strip()
    result["product_name"] = result["product_name"].astype("string").fillna("").str.strip()
    result["style_code"] = result["product_name"].str.extract(STYLE_CODE_RE, expand=False).fillna("").str.upper()
    result = result[(result["product_id"] != "") & (result["style_code"] != "")].copy()
    if result.empty:
        raise ValueError("文件中未识别到同时包含商品ID和标准货号的有效记录。")
    for column in NUMERIC_COLUMNS:
        result[column] = _numeric(result[column], percent=column in PERCENT_COLUMNS)
    # A platform export can contain more than one row for the same product ID.
    # Daily storage has one row per shop/product, so consolidate first instead
    # of allowing an upsert statement to hit the same conflict key twice.
    result = result.groupby("product_id", as_index=False).agg(
        product_name=("product_name", "first"), style_code=("style_code", "first"),
        impressions=("impressions", "sum"), clicks=("clicks", "sum"),
        spend=("spend", "sum"), gross_gmv=("gross_gmv", "sum"),
        gross_orders=("gross_orders", "sum"), user_paid_amount=("user_paid_amount", "sum"),
        coupon_amount=("coupon_amount", "sum"), platform_subsidy=("platform_subsidy", "sum"),
    )
    result["ctr"] = result["clicks"].div(result["impressions"]).where(result["impressions"] > 0, 0.0)
    result["conversion_rate"] = result["gross_orders"].div(result["clicks"]).where(result["clicks"] > 0, 0.0)
    result["gross_roi"] = result["gross_gmv"].div(result["spend"]).where(result["spend"] > 0, 0.0)
    result["gross_order_cost"] = result["spend"].div(result["gross_orders"]).where(result["gross_orders"] > 0, 0.0)
    result["report_date"] = report_date.isoformat()
    result["shop_name"] = shop_name
    result["source_file"] = Path(source_file).name[:255]
    return result


def save_daily_promotion_rows(df):
    client = init_supabase()
    if client is None:
        raise RuntimeError("Supabase 未连接。")
    records = []
    for record in df.to_dict(orient="records"):
        clean = {}
        for key, value in record.items():
            if pd.isna(value) or (isinstance(value, float) and not math.isfinite(value)):
                clean[key] = 0.0 if key in NUMERIC_COLUMNS else None
            elif hasattr(value, "item"):
                clean[key] = value.item()
            else:
                clean[key] = value
        records.append(clean)
    client.table(DAILY_TABLE_NAME).upsert(records, on_conflict="report_date,shop_name,product_id").execute()
    st.cache_data.clear()
    return len(records)


@st.cache_data(ttl=120, show_spinner=False)
def load_daily_promotion_rows(start_date: date, end_date: date, shops=None):
    client = init_supabase()
    if client is None:
        return pd.DataFrame()
    rows, page = [], 0
    while True:
        query = (client.table(DAILY_TABLE_NAME).select("*")
                 .gte("report_date", start_date.isoformat()).lte("report_date", end_date.isoformat()))
        if shops:
            query = query.in_("shop_name", list(shops))
        page_rows = (query.order("report_date", desc=True).order("id")
                     .range(page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1).execute().data or [])
        rows.extend(page_rows)
        if len(page_rows) < PAGE_SIZE:
            break
        page += 1
    return pd.DataFrame(rows)


@st.cache_data(ttl=300, show_spinner=False)
def daily_promotion_date_bounds():
    client = init_supabase()
    if client is None:
        return None, None
    newest = client.table(DAILY_TABLE_NAME).select("report_date").order("report_date", desc=True).limit(1).execute().data or []
    oldest = client.table(DAILY_TABLE_NAME).select("report_date").order("report_date").limit(1).execute().data or []
    return (date.fromisoformat(oldest[0]["report_date"]) if oldest else None,
            date.fromisoformat(newest[0]["report_date"]) if newest else None)


# Old helpers remain during rollout so stale Streamlit workers do not fail imports.
def sunday_of(value=None):
    value = value or date.today()
    return value - timedelta(days=(value.weekday() + 1) % 7)


def completed_week_starts(count=104, today=None):
    latest = sunday_of(today or date.today()) - timedelta(days=7)
    return [latest - timedelta(days=7 * index) for index in range(count)]


def week_label(week_start):
    return f"{week_start:%Y-%m-%d} — {week_start + timedelta(days=6):%Y-%m-%d}（周日—周六）"
