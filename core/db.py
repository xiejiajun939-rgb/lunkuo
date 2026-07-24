# -*- coding: utf-8 -*-
"""
数据库操作公共模块
包含：Supabase 连接、表名获取、商品数据加载、映射表、目标管理、RPC 调用等
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta
import time
from supabase import create_client

# ---------- Supabase 配置 ----------
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]

@st.cache_resource
def init_supabase():
    """初始化 Supabase 客户端（缓存）"""
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Supabase 连接失败：{e}")
        return None

def get_table_name(base_name, suffix=""):
    """根据后缀返回表名，例如 product_sales -> product_sales_live"""
    return f"{base_name}{suffix}" if suffix else base_name

# ---------- 数据加载函数 ----------
@st.cache_data(ttl=300)
def load_product_sales(suffix="", apply_filter=True):
    """加载商品销售数据（product_sales 表），并应用数据权限过滤"""
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        table_name = get_table_name("product_sales", suffix)
        # 分页查询所有数据
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
        if not all_data:
            return pd.DataFrame()
        df = pd.DataFrame(all_data)
        # 日期转换
        df["sale_date"] = pd.to_datetime(df["sale_date"])
        # 应用数据权限过滤（如果启用）
        if apply_filter:
            from core.utils import apply_data_permission
            df = apply_data_permission(df)
        return df
    except Exception as e:
        st.error(f"加载商品销售数据失败：{e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_product_master():
    """加载商品主数据（product_master）"""
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

@st.cache_data(ttl=600)
def load_dimension_mapping():
    """从 mapping 表加载组织/部门映射"""
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
        supabase.table(table_name).upsert(records, on_conflict="org_name").execute()

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

@st.cache_data(ttl=600)
def get_date_range(suffix):
    """获取数据表中最早和最晚日期（用于组织页面）"""
    supabase = init_supabase()
    if supabase is None:
        return None, None
    try:
        min_dates, max_dates = [], []
        table_name = get_table_name("product_sales", suffix)
        resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=False).limit(1).execute()
        if resp.data:
            min_dates.append(pd.to_datetime(resp.data[0]["sale_date"]).date())
        resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=True).limit(1).execute()
        if resp.data:
            max_dates.append(pd.to_datetime(resp.data[0]["sale_date"]).date())
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

# ---------- 其他可能用到的函数（从原主文件移入） ----------
# （如果还需要 load_targets, save_targets, clear_targets 等，可继续添加）
