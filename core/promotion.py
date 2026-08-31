# -*- coding: utf-8 -*-
from datetime import date, timedelta
import math

import pandas as pd
import streamlit as st

from core.db import init_supabase


TABLE_NAME = "promotion_product_weekly"

COLUMN_MAP = {
    "商品ID": "product_id",
    "商品名称": "product_name",
    "货号": "style_code",
    "整体展示次数": "impressions",
    "整体点击次数": "clicks",
    "整体点击率": "ctr",
    "整体转化率": "conversion_rate",
    "整体消耗": "spend",
    "整体成交金额": "gross_gmv",
    "整体支付ROI": "gross_roi",
    "整体成交订单成本": "gross_order_cost",
    "用户实际支付金额": "user_paid_amount",
    "电商平台补贴金额": "platform_subsidy",
    "净成交ROI": "net_roi",
    "净成交金额": "net_gmv",
    "净成交订单成本": "net_order_cost",
    "净成交金额结算率": "net_settlement_rate",
    "1小时内退款率": "refund_rate_1h",
}

NUMERIC_COLUMNS = [
    "impressions", "clicks", "ctr", "conversion_rate", "spend", "gross_gmv",
    "gross_roi", "gross_order_cost", "user_paid_amount", "platform_subsidy",
    "net_roi", "net_gmv", "net_order_cost", "net_settlement_rate", "refund_rate_1h",
]
PERCENT_COLUMNS = {"ctr", "conversion_rate", "net_settlement_rate", "refund_rate_1h"}


def sunday_of(value=None):
    value = value or date.today()
    return value - timedelta(days=(value.weekday() + 1) % 7)


def completed_week_starts(count=104, today=None):
    today = today or date.today()
    current_sunday = sunday_of(today)
    latest = current_sunday - timedelta(days=7)
    return [latest - timedelta(days=7 * i) for i in range(count)]


def week_label(week_start):
    week_end = week_start + timedelta(days=6)
    return f"{week_start:%Y-%m-%d} — {week_end:%Y-%m-%d}（周日—周六）"


def validate_week(week_start, week_end):
    if week_start.weekday() != 6:
        raise ValueError("周期开始日期必须是周日。")
    if week_end != week_start + timedelta(days=6):
        raise ValueError("周期结束日期必须是紧接着的周六。")


def _numeric(series, percent=False):
    text = (
        series.astype("string").fillna("0")
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    values = pd.to_numeric(text, errors="coerce").fillna(0.0)
    if percent:
        values = values / 100.0
    return values.replace([float("inf"), float("-inf")], 0.0)


def parse_promotion_file(file_obj, shop_name, week_start, source_file=""):
    shop_name = str(shop_name or "").strip().upper()
    if not shop_name:
        raise ValueError("请填写推广数据所属的抖音店铺。")
    week_end = week_start + timedelta(days=6)
    validate_week(week_start, week_end)

    df = pd.read_excel(file_obj)
    missing = [name for name in COLUMN_MAP if name not in df.columns]
    if missing:
        raise ValueError(f"文件缺少必要列：{', '.join(missing)}")
    result = df[list(COLUMN_MAP)].rename(columns=COLUMN_MAP).copy()
    result["product_id"] = result["product_id"].astype("string").fillna("").str.strip()
    result["product_name"] = result["product_name"].astype("string").fillna("").str.strip()
    result["style_code"] = result["style_code"].astype("string").fillna("").str.strip().str.upper()
    # 平台导出偶尔漏填货号，但商品名称末尾仍带标准款号；优先补全，避免丢失推广消耗。
    missing_style = result["style_code"] == ""
    inferred_style = result.loc[missing_style, "product_name"].str.extract(
        r"([A-Za-z]\d{3}[A-Za-z]\d{3})", expand=False
    )
    result.loc[missing_style, "style_code"] = inferred_style.fillna("").str.upper()
    result = result[(result["product_id"] != "") & (result["style_code"] != "")].copy()
    if result.empty:
        raise ValueError("文件中没有同时包含商品ID和货号的有效记录。")

    for column in NUMERIC_COLUMNS:
        result[column] = _numeric(result[column], percent=column in PERCENT_COLUMNS)
    result["week_start"] = week_start.isoformat()
    result["week_end"] = week_end.isoformat()
    result["shop_name"] = shop_name
    result["source_file"] = str(source_file or "")[:255]
    return result


def save_promotion_rows(df):
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
    client.table(TABLE_NAME).upsert(
        records, on_conflict="week_start,shop_name,product_id"
    ).execute()
    st.cache_data.clear()
    return len(records)


@st.cache_data(ttl=120, show_spinner=False)
def load_promotion_rows(week_start, shops=None):
    client = init_supabase()
    if client is None:
        return pd.DataFrame()
    query = client.table(TABLE_NAME).select("*").eq("week_start", week_start.isoformat())
    if shops:
        query = query.in_("shop_name", list(shops))
    response = query.order("shop_name").order("style_code").execute()
    return pd.DataFrame(response.data or [])


@st.cache_data(ttl=300, show_spinner=False)
def load_promotion_shops():
    client = init_supabase()
    if client is None:
        return []
    response = client.table(TABLE_NAME).select("shop_name").execute()
    return sorted({row.get("shop_name") for row in (response.data or []) if row.get("shop_name")})
