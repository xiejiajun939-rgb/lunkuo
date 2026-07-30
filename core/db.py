# -*- coding: utf-8 -*-
"""
数据库操作公共模块（最终稳定版）
- 映射表缓存 60 秒，保证实时性
- 线下数据全量查询后内存过滤，避免日期比较问题
- 直接按 shop_name 映射部门，忽略 anchor
- 支持强制刷新缓存
"""

import streamlit as st
import pandas as pd
import re
from supabase import create_client

# ---------- Supabase 配置 ----------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_supabase():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Supabase 连接失败：{e}")
        return None

supabase = init_supabase()

def get_table_name(base_name, suffix=None):
    if suffix is None:
        suffix = st.session_state.get("table_suffix", "")
    return f"{base_name}{suffix}"

# ---------- 辅助：提取主播 ----------
def extract_anchor(remark):
    if not isinstance(remark, str):
        return None
    match = re.search(r'主播[：:]([^_]+)', remark)
    return match.group(1).strip() if match else None

# ---------- 维度映射加载（ttl=60） ----------
@st.cache_data(ttl=60)
def load_dimension_mapping():
    if supabase is None:
        return pd.DataFrame()
    try:
        resp = supabase.table("mapping").select("*").execute()
        if resp.data:
            df = pd.DataFrame(resp.data)
            df['shop_name'] = df['shop_name'].astype(str).str.strip().str.upper()
            df['anchor_name'] = df['anchor_name'].fillna('NONE').astype(str).str.strip().str.upper()
            df['org_name'] = df['org_name'].fillna('未分配组织').astype(str).str.strip()
            df['dept'] = df['dept'].fillna('未分配部门').astype(str).str.strip()
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载维度映射表失败：{e}")
        return pd.DataFrame()

# ---------- 核心聚合函数（缓存 60 秒） ----------
@st.cache_data(ttl=60)
def fetch_sales_summary(start_date, end_date, suffix=""):
    if supabase is None:
        return pd.DataFrame()

    def clean_shop_names(df):
        if 'shop_name' in df.columns:
            df['shop_name'] = df['shop_name'].astype(str).str.strip().str.upper()
        return df

    # 1. 线上数据（分页查询，带日期过滤）
    product_table = get_table_name("product_sales", suffix)
    online_data = []
    page = 0
    page_size = 1000
    while True:
        resp = supabase.table(product_table)\
                       .select("sale_date, shop_name, remark, ship_amount, return_amount, net_amount")\
                       .gte("sale_date", start_date.isoformat())\
                       .lte("sale_date", end_date.isoformat())\
                       .range(page * page_size, (page + 1) * page_size - 1)\
                       .execute()
        if not resp.data:
            break
        online_data.extend(resp.data)
        if len(resp.data) < page_size:
            break
        page += 1

    if online_data:
        df_online = pd.DataFrame(online_data)
        df_online["sale_date"] = pd.to_datetime(df_online["sale_date"])
        if suffix == "_all":
            df_online["anchor"] = df_online["remark"].apply(extract_anchor).fillna("NONE")
        else:
            df_online["anchor"] = "NONE"
        df_online = df_online.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
            "ship_amount": "sum",
            "return_amount": "sum",
            "net_amount": "sum"
        })
        df_online = clean_shop_names(df_online)
    else:
        df_online = pd.DataFrame()

    # 2. 线下数据（全量查询，内存过滤）
    df_offline = pd.DataFrame()
    if suffix == "_all":
        offline_resp = supabase.table("offline_sales_all").select("*").execute()
        if offline_resp.data:
            df_offline = pd.DataFrame(offline_resp.data)
            df_offline["sale_date"] = pd.to_datetime(df_offline["sale_date"])
            # 过滤日期范围
            start_ts = pd.Timestamp(start_date)
            end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            df_offline = df_offline[(df_offline["sale_date"] >= start_ts) & (df_offline["sale_date"] <= end_ts)]
            if not df_offline.empty:
                df_offline["anchor"] = "NONE"
                df_offline = df_offline.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
                    "ship_amount": "sum",
                    "return_amount": "sum",
                    "net_amount": "sum"
                })
                df_offline = clean_shop_names(df_offline)

    # 3. 合并线上和线下
    if df_online.empty and df_offline.empty:
        return pd.DataFrame()
    elif df_online.empty:
        df = df_offline
    elif df_offline.empty:
        df = df_online
    else:
        df = pd.concat([df_online, df_offline], ignore_index=True)

    # 4. 加载映射表
    mapping_df = load_dimension_mapping()

    # 5. 直接按 shop_name 映射部门（忽略 anchor）
    if suffix == "_all" and not mapping_df.empty:
        # 确保 shop_name 统一大写
        mapping_df['shop_name'] = mapping_df['shop_name'].astype(str).str.strip().str.upper()
        # 取每个 shop_name 的第一条记录作为映射（通常部门唯一）
        shop_dept_map = mapping_df.drop_duplicates(subset=['shop_name'], keep='first').set_index('shop_name')['dept'].to_dict()
        shop_org_map = mapping_df.drop_duplicates(subset=['shop_name'], keep='first').set_index('shop_name')['org_name'].to_dict()
        df['dept'] = df['shop_name'].map(shop_dept_map).fillna('未分配部门')
        df['org_name'] = df['shop_name'].map(shop_org_map).fillna('未分配组织')
    else:
        df["org_name"] = "未分配组织"
        df["dept"] = "未分配部门"

    # 6. 重命名金额列
    df = df.rename(columns={
        "ship_amount": "total_ship",
        "return_amount": "total_return",
        "net_amount": "total_net"
    })

    return df[["sale_date", "org_name", "dept", "shop_name", "total_ship", "total_return", "total_net"]]

# ---------- 以下为其他现有函数（保持不变） ----------
# 包括 load_product_sales, get_sales_date_range, load_product_master,
# load_org_targets, save_org_targets, clear_org_targets,
# load_targets, save_targets, clear_targets
# 为了节省篇幅，此处省略，请保留您的原有实现。
# 但务必确保 load_dimension_mapping 和 fetch_sales_summary 已被替换。
