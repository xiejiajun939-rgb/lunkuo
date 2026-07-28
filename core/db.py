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

# ---------- 获取 Supabase 配置（兼容多种 secrets 写法） ----------
def get_supabase_config():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return url, key
    except KeyError:
        pass
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return url, key
    except KeyError:
        pass
    st.error(
        "❌ 未找到 Supabase 配置。请在 `.streamlit/secrets.toml` 中设置：\n"
        "```toml\n"
        "[supabase]\n"
        "url = \"https://your-project.supabase.co\"\n"
        "key = \"your-anon-key\"\n"
        "```"
    )
    st.stop()

@st.cache_resource
def init_supabase():
    url, key = get_supabase_config()
    try:
        return create_client(url, key)
    except Exception as e:
        st.error(f"Supabase 连接失败：{e}")
        st.stop()

def get_table_name(base_name, suffix=None):
    if suffix is None:
        suffix = st.session_state.get("table_suffix", "")
    return f"{base_name}{suffix}"

# ---------- 维度映射 ----------
@st.cache_data(ttl=600)
def load_dimension_mapping():
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        resp = supabase.table("mapping").select("*").execute()
        if resp.data:
            df = pd.DataFrame(resp.data)
            df['shop_name'] = df['shop_name'].astype(str).str.strip()
            df['anchor_name'] = df['anchor_name'].fillna('NONE').astype(str).str.strip()
            df['org_name'] = df['org_name'].fillna('未分配组织').astype(str).str.strip()
            df['dept'] = df['dept'].fillna('未分配部门').astype(str).str.strip()
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载维度映射表失败：{e}")
        return pd.DataFrame()

# ---------- 主播提取辅助（用于内部） ----------
def _extract_anchor(remark):
    import re
    if not isinstance(remark, str):
        return None
    match = re.search(r'主播[：:]([^_]+)', remark)
    return match.group(1).strip() if match else None

# ---------- 商品销售数据加载（含 include_offline 参数） ----------
@st.cache_data(ttl=300)
def load_product_sales(suffix=None, apply_filter=True, include_offline=True):
    """加载商品销售数据，支持 include_offline 控制是否合并线下收入"""
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        table_name = get_table_name("product_sales", suffix)
        all_data = []
        page = 0
        page_size = 1000
        needed_cols = "sale_date, shop_name, product_code, style_code, brand, year, season, product_category, style, color_code, size_code, ship_amount, return_amount, net_amount, remark"
        while True:
            resp = supabase.table(table_name)\
                           .select(needed_cols)\
                           .range(page * page_size, (page + 1) * page_size - 1)\
                           .execute()
            if not resp.data:
                break
            all_data.extend(resp.data)
            if len(resp.data) < page_size:
                break
            page += 1
        if not all_data:
            return pd.DataFrame()
        df = pd.DataFrame(all_data)
        df["sale_date"] = pd.to_datetime(df["sale_date"])
        if "style_code" not in df.columns or df["style_code"].isnull().all():
            df["style_code"] = df["product_code"].str[:8]
        else:
            df["style_code"] = df["style_code"].fillna(df["product_code"].str[:8])
        for col in ["ship_amount", "return_amount", "net_amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        if suffix == "_all" and "anchor" not in df.columns:
            df["anchor"] = df["remark"].apply(_extract_anchor)

        # 维度关联
        if suffix == "_all":
            mapping_df = load_dimension_mapping()
            if not mapping_df.empty:
                if "anchor" not in df.columns:
                    df["anchor"] = "NONE"
                df["anchor"] = df["anchor"].fillna("NONE")
                df = df.merge(
                    mapping_df,
                    left_on=["shop_name", "anchor"],
                    right_on=["shop_name", "anchor_name"],
                    how="left"
                )
                df["org_name"] = df["org_name"].fillna("未分配组织")
                df["dept"] = df["dept"].fillna("未分配部门")
            else:
                df["org_name"] = "未分配组织"
                df["dept"] = "未分配部门"
        else:
            df["org_name"] = None
            df["dept"] = None

        # 合并线下收入（仅当 include_offline=True 且 suffix="_all"）
        if suffix == "_all" and include_offline:
            try:
                offline_resp = supabase.table("offline_sales_all").select("*").execute()
                if offline_resp.data:
                    offline_df = pd.DataFrame(offline_resp.data)
                    offline_df["sale_date"] = pd.to_datetime(offline_df["sale_date"])
                    # 补全字段
                    offline_df["product_code"] = None
                    offline_df["style_code"] = None
                    offline_df["brand"] = None
                    offline_df["year"] = None
                    offline_df["season"] = None
                    offline_df["product_category"] = None
                    offline_df["style"] = None
                    offline_df["color_code"] = None
                    offline_df["size_code"] = None
                    offline_df["image_url"] = None
                    offline_df["master_category"] = None
                    offline_df["remark"] = offline_df["remark"].fillna("线下收入")
                    offline_df["anchor"] = "NONE"
                    for col in df.columns:
                        if col not in offline_df.columns:
                            offline_df[col] = None
                    offline_df = offline_df[df.columns]
                    df = pd.concat([df, offline_df], ignore_index=True)
            except Exception as e:
                pass

        # 补全组织/部门（针对线下或未匹配）
        if suffix == "_all":
            mapping_df = load_dimension_mapping()
            if not mapping_df.empty:
                map_shop = mapping_df[mapping_df['anchor_name'] == 'NONE'].set_index('shop_name')[['org_name', 'dept']].to_dict('index')
                mask = df['org_name'].isna()
                if mask.any():
                    df.loc[mask, 'org_name'] = df.loc[mask, 'shop_name'].map(lambda s: map_shop.get(s, {}).get('org_name'))
                    df.loc[mask, 'dept'] = df.loc[mask, 'shop_name'].map(lambda s: map_shop.get(s, {}).get('dept'))
                    df['org_name'] = df['org_name'].fillna('未分配组织')
                    df['dept'] = df['dept'].fillna('未分配部门')

        if apply_filter:
            from core.utils import apply_data_permission
            df = apply_data_permission(df)
        return df
    except Exception as e:
        st.error(f"加载商品销售数据失败：{e}")
        return pd.DataFrame()

# ---------- 商品主数据 ----------
@st.cache_data(ttl=300)
def load_product_master():
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        all_data = []
        page = 0
        page_size = 1000
        while True:
            resp = supabase.table("product_master").select("*").range(page*page_size, (page+1)*page_size-1).execute()
            if not resp.data:
                break
            all_data.extend(resp.data)
            if len(resp.data) < page_size:
                break
            page += 1
        if all_data:
            df = pd.DataFrame(all_data)
            if "has_newbie_coupon" not in df.columns:
                df["has_newbie_coupon"] = False
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载商品库失败：{e}")
        return pd.DataFrame()

# ---------- 组织目标 ----------
@st.cache_data(ttl=300)
def load_org_targets(suffix=None):
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
    supabase = init_supabase()
    if supabase is None:
        return
    # 全量替换（先清空再插入）
    table_name = get_table_name("arg_targets", suffix)
    supabase.table(table_name).delete().neq("id", 0).execute()
    records = [{"org_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        supabase.table(table_name).insert(records).execute()

# ---------- 店铺目标 ----------
def load_targets(suffix=None):
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
    supabase = init_supabase()
    if supabase is None:
        return
    # 全量替换
    table_name = get_table_name("shop_targets", suffix)
    supabase.table(table_name).delete().neq("id", 0).execute()
    records = [{"shop_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        supabase.table(table_name).insert(records).execute()

def clear_targets(suffix=None):
    supabase = init_supabase()
    if supabase:
        table_name = get_table_name("shop_targets", suffix)
        supabase.table(table_name).delete().neq("id", 0).execute()
    st.session_state.target_dict = {}
    st.rerun()

# ---------- RPC 聚合（用于组织/部门分析） ----------
@st.cache_data(ttl=300)
def fetch_sales_summary(start_date, end_date, suffix=""):
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
