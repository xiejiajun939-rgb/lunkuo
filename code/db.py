# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import re
import time
import numpy as np
from supabase import create_client
from core.utils import extract_anchor, apply_data_permission

# ========== Supabase 连接 ==========
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Supabase 连接失败：{e}")
        return None

def get_table_name(base_name, suffix=None):
    if suffix is None:
        suffix = st.session_state.get("table_suffix", "")
    return f"{base_name}{suffix}"

# ========== 维度映射加载 ==========
@st.cache_data(ttl=600)
def load_dimension_mapping() -> pd.DataFrame:
    """从 Supabase 加载 shop+anchor -> org/dept 映射表"""
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    try:
        resp = supabase.table("mapping_rows").select("*").execute()
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

# ========== 商品销售数据加载 ==========
@st.cache_data(ttl=300)
def load_product_sales(suffix=None, apply_filter=True):
    if suffix is None:
        suffix = st.session_state.get("table_suffix", "")
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
        if all_data:
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
                df["anchor"] = df["remark"].apply(extract_anchor)
            
            # 维度关联逻辑（仅当 suffix == "_all"）
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
            
            # 合并线下收入数据（仅全部数据）
            if suffix == "_all":
                try:
                    offline_resp = supabase.table("offline_sales_all").select("*").execute()
                    if offline_resp.data:
                        offline_df = pd.DataFrame(offline_resp.data)
                        offline_df["sale_date"] = pd.to_datetime(offline_df["sale_date"])
                        # 补全其他列（线下数据没有商品维度）
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
                        # 确保列顺序与 df 一致
                        for col in df.columns:
                            if col not in offline_df.columns:
                                offline_df[col] = None
                        offline_df = offline_df[df.columns]
                        # 合并
                        df = pd.concat([df, offline_df], ignore_index=True)
                except Exception as e:
                    pass
            
            # 为线下数据（以及任何未分配组织的数据）补全组织/部门
            if suffix == "_all":
                if not mapping_df.empty:
                    map_shop = mapping_df[mapping_df['anchor_name'] == 'NONE'].set_index('shop_name')[['org_name', 'dept']].to_dict('index')
                    mask = df['org_name'].isna()
                    if mask.any():
                        df.loc[mask, 'org_name'] = df.loc[mask, 'shop_name'].map(lambda s: map_shop.get(s, {}).get('org_name'))
                        df.loc[mask, 'dept'] = df.loc[mask, 'shop_name'].map(lambda s: map_shop.get(s, {}).get('dept'))
                        df['org_name'] = df['org_name'].fillna('未分配组织')
                        df['dept'] = df['dept'].fillna('未分配部门')
            
            if apply_filter:
                df = apply_data_permission(df)
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载商品销售数据失败：{e}")
        return pd.DataFrame()

# ========== 商品库加载 ==========
@st.cache_data(ttl=600)
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
