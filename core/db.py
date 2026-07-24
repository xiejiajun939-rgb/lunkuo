# -*- coding: utf-8 -*-
"""
core/db.py - 数据库操作公共模块
包含 Supabase 连接、表名工具、数据加载、映射表、目标管理、RPC 等。
"""

import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client
import re
from datetime import date, timedelta
import time

# ---------- 配置 ----------
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

# ---------- 连接缓存 ----------
@st.cache_resource
def init_supabase():
    """初始化 Supabase 客户端（单例）"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("请在 Streamlit secrets 中配置 SUPABASE_URL 和 SUPABASE_KEY")
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Supabase 连接失败：{e}")
        return None

# ---------- 表名工具 ----------
def get_table_name(base_name, suffix=None):
    """
    根据后缀生成实际表名。
    例如：get_table_name("product_sales", "_all") -> "product_sales_all"
          get_table_name("product_sales", "") -> "product_sales"
    """
    if suffix and suffix.startswith("_"):
        return f"{base_name}{suffix}"
    elif suffix:
        return f"{base_name}_{suffix}"
    else:
        return base_name

# ---------- 商品销售数据加载 ----------
@st.cache_data(ttl=300)
def load_product_sales(suffix=None, apply_filter=True):
    """
    加载商品销售明细表（product_sales 或 product_sales_live 或 product_sales_all）。
    apply_filter: 是否应用数据权限过滤（由 utils.apply_data_permission 处理）
    """
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        table_name = get_table_name("product_sales", suffix)
        # 分页获取所有数据
        all_data = []
        page = 0
        page_size = 1000
        while True:
            resp = supabase.table(table_name).select("*").range(page * page_size, (page + 1) * page_size - 1).execute()
            if not resp.data:
                break
            all_data.extend(resp.data)
            if len(resp.data) < page_size:
                break
            page += 1
        if not all_data:
            return pd.DataFrame()
        df = pd.DataFrame(all_data)
        # 日期转换
        if "sale_date" in df.columns:
            df["sale_date"] = pd.to_datetime(df["sale_date"])
        # 应用权限过滤（如果有）
        if apply_filter:
            from core.utils import apply_data_permission  # 延迟导入避免循环
            df = apply_data_permission(df)
        return df
    except Exception as e:
        st.error(f"加载商品销售数据失败：{e}")
        return pd.DataFrame()

# ---------- 商品主数据加载 ----------
@st.cache_data(ttl=600)
def load_product_master():
    """加载商品主数据表 product_master"""
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        resp = supabase.table("product_master").select("*").execute()
        if resp.data:
            df = pd.DataFrame(resp.data)
            # 确保 style_code 列为字符串
            if "style_code" in df.columns:
                df["style_code"] = df["style_code"].astype(str).str.strip().str.upper()
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载商品主数据失败：{e}")
        return pd.DataFrame()

# ---------- 映射表加载（表名：mapping） ----------
@st.cache_data(ttl=600)
def load_dimension_mapping():
    """
    从 mapping 表加载组织/部门映射。
    映射表至少包含 shop_name（或 anchor）与 org_name, dept 等字段。
    """
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        resp = supabase.table("mapping").select("*").execute()
        if resp.data:
            return pd.DataFrame(resp.data)
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载映射表失败：{e}")
        return pd.DataFrame()

# ---------- 店铺目标加载 ----------
@st.cache_data(ttl=300)
def load_targets(suffix=None):
    """从 shop_targets 表加载店铺目标"""
    supabase = init_supabase()
    if supabase is None:
        return {}
    try:
        table_name = get_table_name("shop_targets", suffix)
        resp = supabase.table(table_name).select("*").execute()
        if resp.data:
            return {row["shop_name"]: row["target_amount"] for row in resp.data}
        else:
            return {}
    except Exception as e:
        st.error(f"加载店铺目标失败：{e}")
        return {}

def save_targets(target_dict, suffix=None):
    """保存店铺目标到 shop_targets 表"""
    supabase = init_supabase()
    if supabase is None:
        return
    records = [{"shop_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        table_name = get_table_name("shop_targets", suffix)
        try:
            supabase.table(table_name).upsert(records, on_conflict="shop_name").execute()
        except Exception as e:
            st.error(f"保存店铺目标失败：{e}")

# ---------- 组织目标加载（表名：arg_targets） ----------
@st.cache_data(ttl=300)
def load_org_targets(suffix=None):
    """从 arg_targets 表加载组织目标"""
    supabase = init_supabase()
    if supabase is None:
        return {}
    try:
        table_name = get_table_name("arg_targets", suffix)
        resp = supabase.table(table_name).select("*").execute()
        if resp.data:
            return {row["org_name"]: row["target_amount"] for row in resp.data}
        else:
            return {}
    except Exception as e:
        st.error(f"加载组织目标失败：{e}")
        return {}

def save_org_targets(target_dict, suffix=None):
    """保存组织目标到 arg_targets 表"""
    supabase = init_supabase()
    if supabase is None:
        return
    records = [{"org_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        table_name = get_table_name("arg_targets", suffix)
        try:
            supabase.table(table_name).upsert(records, on_conflict="org_name").execute()
        except Exception as e:
            st.error(f"保存组织目标失败：{e}")

# ---------- RPC 聚合数据加载 ----------
@st.cache_data(ttl=300)
def fetch_sales_summary(start_date, end_date, suffix=""):
    """
    调用 Supabase RPC 函数 get_sales_summary 获取聚合数据。
    RPC 应返回包含 total_ship, total_return, total_net, org_name, dept, shop_name 等字段。
    """
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        response = supabase.rpc('get_sales_summary', {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'table_suffix': suffix
        }).execute()
        if response.data:
            return pd.DataFrame(response.data)
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"聚合数据加载失败：{e}")
        return pd.DataFrame()

# ---------- 获取日期范围（用于组织页面） ----------
@st.cache_data(ttl=600)
def get_date_range(suffix):
    """获取 product_sales 表（及 offline_sales_all）的最早和最晚日期"""
    supabase = init_supabase()
    if supabase is None:
        return None, None
    try:
        min_dates, max_dates = [], []
        table_name = get_table_name("product_sales", suffix)
        # 最早
        resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=False).limit(1).execute()
        if resp.data:
            min_dates.append(pd.to_datetime(resp.data[0]["sale_date"]).date())
        # 最晚
        resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=True).limit(1).execute()
        if resp.data:
            max_dates.append(pd.to_datetime(resp.data[0]["sale_date"]).date())
        # 如果是全部数据，还要查询 offline_sales_all
        if suffix == "_all":
            offline_resp = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=False).limit(1).execute()
            if offline_resp.data:
                min_dates.append(pd.to_datetime(offline_resp.data[0]["sale_date"]).date())
            offline_resp = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=True).limit(1).execute()
            if offline_resp.data:
                max_dates.append(pd.to_datetime(offline_resp.data[0]["sale_date"]).date())
        if min_dates and max_dates:
            return min(min_dates), max(max_dates)
        return None, None
    except Exception as e:
        st.error(f"获取日期范围失败：{e}")
        return None, None

# ---------- 每日业绩加载 ----------
@st.cache_data(ttl=300)
def load_daily_sales(suffix=None, apply_filter=True):
    """加载每日汇总表 daily_sales 或 daily_sales_live 等"""
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        table_name = get_table_name("daily_sales", suffix)
        all_data = []
        page = 0
        page_size = 1000
        query_columns = "id, sale_date, shop_name, amount, cumulative_amount"
        while True:
            resp = supabase.table(table_name).select(query_columns).range(page * page_size, (page + 1) * page_size - 1).execute()
            if not resp.data:
                break
            all_data.extend(resp.data)
            if len(resp.data) < page_size:
                break
            page += 1
        if all_data:
            df = pd.DataFrame(all_data)
            df["sale_date"] = pd.to_datetime(df["sale_date"])
            if apply_filter:
                from core.utils import apply_data_permission
                df = apply_data_permission(df)
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载每日业绩失败：{e}")
        return pd.DataFrame()

def save_daily_sales(records, suffix=None):
    """保存每日业绩记录（upsert）"""
    supabase = init_supabase()
    if supabase is None or not records:
        return
    table_name = get_table_name("daily_sales", suffix)
    try:
        supabase.table(table_name).upsert(records, on_conflict="sale_date,shop_name").execute()
    except Exception as e:
        st.error(f"保存每日业绩失败：{e}")

# ---------- 刷新物化视图 ----------
def refresh_materialized_view(suffix=""):
    """刷新物化视图（若存在）"""
    supabase = init_supabase()
    if supabase is None:
        return
    try:
        supabase.rpc('refresh_mv', {'suffix': suffix}).execute()
    except Exception as e:
        st.warning(f"物化视图刷新失败（不影响数据入库）：{e}")

# ---------- 其他可能需要的函数 ----------
# 以下函数在原主文件中存在，但子页面可能不需要，保留以供兼容。

def get_all_shop_names(suffix=None):
    """获取所有店铺名称（用于权限过滤）"""
    df = load_product_sales(suffix, apply_filter=False)
    if df.empty:
        return []
    if suffix == "_all" and "anchor" in df.columns:
        return sorted(df["anchor"].dropna().unique().tolist())
    elif "shop_name" in df.columns:
        return sorted(df["shop_name"].dropna().unique().tolist())
    return []

# 如果需要，可以添加更多辅助函数。
