# core/db.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from supabase import create_client
import os
import re
import time

# Supabase 配置（从环境变量或硬编码，建议环境变量）
SUPABASE_URL = os.environ.get("SUPABASE_URL", "your_supabase_url")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your_supabase_key")

@st.cache_resource
def init_supabase():
    """初始化 Supabase 客户端"""
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Supabase 连接失败: {e}")
        return None

def get_table_name(base_name, suffix=""):
    """根据后缀生成表名"""
    return f"{base_name}{suffix}" if suffix else base_name

# ---------- 商品销售数据加载 ----------
@st.cache_data(ttl=300)
def load_product_sales(suffix=None, apply_filter=True):
    """加载 product_sales 表数据"""
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
            resp = supabase.table(table_name).select("*").range(page*page_size, (page+1)*page_size-1).execute()
            if not resp.data:
                break
            all_data.extend(resp.data)
            if len(resp.data) < page_size:
                break
            page += 1
        if all_data:
            df = pd.DataFrame(all_data)
            if "sale_date" in df.columns:
                df["sale_date"] = pd.to_datetime(df["sale_date"])
            # 应用数据权限过滤（如果需要）
            if apply_filter:
                from .utils import apply_data_permission  # 避免循环导入
                df = apply_data_permission(df)
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载商品销售数据失败：{e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_product_master():
    """加载商品主数据表 product_master"""
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        resp = supabase.table("product_master").select("*").execute()
        if resp.data:
            return pd.DataFrame(resp.data)
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载商品主数据失败：{e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_dimension_mapping():
    """加载维度映射表（组织-部门-平台等）"""
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        resp = supabase.table("dimension_mapping").select("*").execute()
        if resp.data:
            return pd.DataFrame(resp.data)
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载维度映射表失败：{e}")
        return pd.DataFrame()

# ---------- 每日销售数据加载 ----------
@st.cache_data(ttl=300)
def load_daily_sales(suffix=None, apply_filter=True):
    """加载 daily_sales 表数据"""
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
            resp = supabase.table(table_name).select(query_columns).range(page*page_size, (page+1)*page_size-1).execute()
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
                from .utils import apply_data_permission
                df = apply_data_permission(df)
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载每日销售数据失败：{e}")
        return pd.DataFrame()

def save_daily_sales(records, suffix=None):
    """保存每日销售记录"""
    supabase = init_supabase()
    if supabase is None or not records:
        return
    table_name = get_table_name("daily_sales", suffix)
    try:
        supabase.table(table_name).upsert(records, on_conflict="sale_date,shop_name").execute()
    except Exception as e:
        st.error(f"保存每日销售数据失败：{e}")

# ---------- 目标相关 ----------
@st.cache_data(ttl=300)
def load_targets(suffix=None):
    """加载店铺目标"""
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
    """保存店铺目标"""
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

@st.cache_data(ttl=300)
def load_org_targets(suffix=None):
    """加载组织目标（用于全部数据）"""
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
    """保存组织目标"""
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

# ---------- RPC 聚合函数 ----------
@st.cache_data(ttl=300)
def fetch_sales_summary(start_date, end_date, suffix=""):
    """调用 RPC get_sales_summary 获取聚合数据"""
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

# ---------- 主数据更新 ----------
def update_product_master_flag(style_code, flag_value):
    """更新商品的新人礼金标签"""
    supabase = init_supabase()
    if supabase is None:
        return False, "Supabase 未连接"
    try:
        resp = supabase.table("product_master").update({"has_newbie_coupon": flag_value}).eq("style_code", style_code).execute()
        return True, "更新成功"
    except Exception as e:
        return False, str(e)
