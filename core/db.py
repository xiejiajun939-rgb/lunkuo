# -*- coding: utf-8 -*-
"""
数据库操作公共模块
包含：Supabase 连接、表名获取、商品数据加载、映射表、目标管理、RPC 调用等
所有数据加载逻辑与单文件版本（websale (62).py）完全一致。
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta
import time
from supabase import create_client
import re

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

# 全局 supabase 实例
supabase = init_supabase()

def get_table_name(base_name, suffix=None):
    if suffix is None:
        suffix = st.session_state.get("table_suffix", "")
    return f"{base_name}{suffix}"

# ---------- 维度映射加载 ----------
@st.cache_data(ttl=600)
def load_dimension_mapping() -> pd.DataFrame:
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

# ---------- 辅助：提取主播 ----------
def extract_anchor(remark):
    if not isinstance(remark, str):
        return None
    match = re.search(r'主播[：:]([^_]+)', remark)
    return match.group(1).strip() if match else None

# ---------- 核心聚合函数（fetch_sales_summary） ----------
@st.cache_data(ttl=300)
def fetch_sales_summary(start_date, end_date, suffix=""):
    if supabase is None:
        return pd.DataFrame()
    try:
        product_table = get_table_name("product_sales", suffix)
        all_data = []
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
            all_data.extend(resp.data)
            if len(resp.data) < page_size:
                break
            page += 1
        if not all_data:
            return pd.DataFrame()
        df = pd.DataFrame(all_data)
        df["sale_date"] = pd.to_datetime(df["sale_date"])
        if suffix == "_all":
            df["anchor"] = df["remark"].apply(extract_anchor).fillna("NONE")
        else:
            df["anchor"] = "NONE"
        df = df.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
            "ship_amount": "sum",
            "return_amount": "sum",
            "net_amount": "sum"
        })
        if suffix == "_all":
            mapping_df = load_dimension_mapping()
            if not mapping_df.empty:
                mapping_df["anchor_name"] = mapping_df["anchor_name"].fillna("NONE")
                df = df.merge(
                    mapping_df[["shop_name", "anchor_name", "org_name", "dept"]],
                    left_on=["shop_name", "anchor"],
                    right_on=["shop_name", "anchor_name"],
                    how="left"
                )
                null_mask = df["org_name"].isna()
                if null_mask.any():
                    fallback_map = mapping_df.drop_duplicates(subset=["shop_name"], keep="first")[["shop_name", "org_name", "dept"]]
                    fallback_map = fallback_map.rename(columns={"org_name": "org_fallback", "dept": "dept_fallback"})
                    df = df.merge(fallback_map, on="shop_name", how="left")
                    df.loc[null_mask, "org_name"] = df.loc[null_mask, "org_fallback"]
                    df.loc[null_mask, "dept"] = df.loc[null_mask, "dept_fallback"]
                    df = df.drop(columns=["org_fallback", "dept_fallback"])
                df["org_name"] = df["org_name"].fillna("未分配组织")
                df["dept"] = df["dept"].fillna("未分配部门")
            else:
                df["org_name"] = "未分配组织"
                df["dept"] = "未分配部门"
            # 合并线下收入
            offline_resp = supabase.table("offline_sales_all")\
                                   .select("sale_date, shop_name, ship_amount, return_amount, net_amount")\
                                   .gte("sale_date", start_date.isoformat())\
                                   .lte("sale_date", end_date.isoformat())\
                                   .execute()
            if offline_resp.data:
                offline_df = pd.DataFrame(offline_resp.data)
                offline_df["sale_date"] = pd.to_datetime(offline_df["sale_date"])
                offline_df["anchor"] = "NONE"
                offline_df = offline_df.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
                    "ship_amount": "sum",
                    "return_amount": "sum",
                    "net_amount": "sum"
                })
                if not mapping_df.empty:
                    offline_df = offline_df.merge(
                        mapping_df[["shop_name", "anchor_name", "org_name", "dept"]],
                        left_on=["shop_name", "anchor"],
                        right_on=["shop_name", "anchor_name"],
                        how="left"
                    )
                    null_mask_off = offline_df["org_name"].isna()
                    if null_mask_off.any():
                        fallback_map = mapping_df.drop_duplicates(subset=["shop_name"], keep="first")[["shop_name", "org_name", "dept"]]
                        fallback_map = fallback_map.rename(columns={"org_name": "org_fallback", "dept": "dept_fallback"})
                        offline_df = offline_df.merge(fallback_map, on="shop_name", how="left")
                        offline_df.loc[null_mask_off, "org_name"] = offline_df.loc[null_mask_off, "org_fallback"]
                        offline_df.loc[null_mask_off, "dept"] = offline_df.loc[null_mask_off, "dept_fallback"]
                        offline_df = offline_df.drop(columns=["org_fallback", "dept_fallback"])
                    offline_df["org_name"] = offline_df["org_name"].fillna("未分配组织")
                    offline_df["dept"] = offline_df["dept"].fillna("未分配部门")
                else:
                    offline_df["org_name"] = "未分配组织"
                    offline_df["dept"] = "未分配部门"
                df = pd.concat([df, offline_df], ignore_index=True)
        else:
            df["org_name"] = None
            df["dept"] = None
        df = df.rename(columns={
            "ship_amount": "total_ship",
            "return_amount": "total_return",
            "net_amount": "total_net"
        })
        return df[["sale_date", "org_name", "dept", "shop_name", "total_ship", "total_return", "total_net"]]
    except Exception as e:
        st.error(f"聚合数据加载失败：{e}")
        return pd.DataFrame()

# ---------- 商品销售数据加载（包含 include_offline 参数） ----------
@st.cache_data(ttl=300)
def load_product_sales(suffix=None, apply_filter=True, include_offline=True):
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
            df["anchor"] = df["remark"].apply(extract_anchor)

        mapping_df = None
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

        # 补全组织/部门
        if suffix == "_all" and mapping_df is not None and not mapping_df.empty:
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

# ---------- 其他函数（load_product_master, load_org_targets, save_org_targets, load_targets, save_targets, clear_targets） ----------
# 请保留您原有的这些函数，这里不再重复粘贴以节省篇幅，但确保它们存在于文件中。


# ---------- 商品主数据加载 ----------
@st.cache_data(ttl=300)
def load_product_master():
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

# ---------- 组织目标管理 ----------
@st.cache_data(ttl=300)
def load_org_targets(suffix=None):
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
    if supabase is None:
        return
    records = [{"org_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        table_name = get_table_name("arg_targets", suffix)
        supabase.table(table_name).upsert(records, on_conflict="org_name").execute()

def clear_org_targets(suffix=None):
    if supabase:
        table_name = get_table_name("arg_targets", suffix)
        supabase.table(table_name).delete().neq("id", 0).execute()

# ---------- 店铺目标管理 ----------
def load_targets(suffix=None):
    if supabase is None:
        return {}
    try:
        table_name = get_table_name("shop_targets", suffix)
        resp = supabase.table(table_name).select("*").execute()
        if resp.data:
            return {row["shop_name"]: row["target_amount"] for row in resp.data}
        else:
            return {}
    except:
        return {}

def save_targets(target_dict, suffix=None):
    if supabase is None:
        return
    records = [{"shop_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        table_name = get_table_name("shop_targets", suffix)
        supabase.table(table_name).upsert(records, on_conflict="shop_name").execute()

def clear_targets(suffix=None):
    if supabase:
        table_name = get_table_name("shop_targets", suffix)
        supabase.table(table_name).delete().neq("id", 0).execute()
    st.session_state.target_dict = {}
    st.rerun()

# ---------- 辅助函数（从正确版本移植） ----------
def extract_anchor(remark):
    """从备注中提取主播名称"""
    if not isinstance(remark, str):
        return None
    import re
    match = re.search(r'主播[：:]([^_]+)', remark)
    return match.group(1).strip() if match else None

# ---------- 其他可能用到的函数（从正确版本移植） ----------
# 如果需要每日业绩相关函数，可参考正确版本，但此处未包含，可按需添加。
# 目前拆分版中的 daily_detail 页面直接使用 load_product_sales，所以不需要独立的 daily_sales 函数。

# 说明：正确版本中还有 save_product_sales, validate_order_data 等函数，
# 这些已在主文件中定义，不需要在 db.py 中重复。如果某些子页面需要，可自行导入。
