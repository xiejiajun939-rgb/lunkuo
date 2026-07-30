# -*- coding: utf-8 -*-
"""
数据库操作公共模块（重构版）
采用分离缓存策略：原始销售数据缓存 + 映射实时加载
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

# ---------- 维度映射加载（短缓存，保证及时更新） ----------
@st.cache_data(ttl=60)  # 缩短至 60 秒
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

# ---------- 核心函数：只缓存原始销售数据（不含映射） ----------
@st.cache_data(ttl=300)
def _fetch_raw_sales(start_date, end_date, suffix=""):
    """
    从商品销售表中获取原始数据，按日期、店铺、主播聚合（不含组织/部门）
    返回列：sale_date, shop_name, anchor, ship_amount, return_amount, net_amount
    """
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
        # 提取主播
        if suffix == "_all":
            df["anchor"] = df["remark"].apply(extract_anchor).fillna("NONE")
        else:
            df["anchor"] = "NONE"
        # 聚合
        df = df.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
            "ship_amount": "sum",
            "return_amount": "sum",
            "net_amount": "sum"
        })
        return df
    except Exception as e:
        st.error(f"加载原始销售数据失败：{e}")
        return pd.DataFrame()

# ---------- 聚合函数（实时合并映射，确保最新） ----------
def fetch_sales_summary(start_date, end_date, suffix=""):
    """
    获取销售汇总，先取原始数据（缓存），再实时合并映射表
    """
    if supabase is None:
        return pd.DataFrame()

    # 1. 获取线上原始数据
    df = _fetch_raw_sales(start_date, end_date, suffix)
    if df.empty and suffix != "_all":
        # 如果线上无数据且非全部数据源，直接返回空（不合并线下）
        return pd.DataFrame()

    # 2. 如果是全部数据源，额外获取线下数据
    if suffix == "_all":
        # 获取线下数据（此处不分页，若线下数据量大可增加分页）
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
            # 合并线下数据
            if df.empty:
                df = offline_df
            else:
                df = pd.concat([df, offline_df], ignore_index=True)

    # 如果合并后仍为空，返回空
    if df.empty:
        return pd.DataFrame()

    # 3. 加载最新映射表（短缓存，保证更新）
    mapping_df = load_dimension_mapping()

    # 4. 合并映射（仅当 suffix == "_all" 且映射表非空）
    if suffix == "_all" and not mapping_df.empty:
        # 确保 anchor 列存在且填充
        df["anchor"] = df["anchor"].fillna("NONE")
        mapping_df["anchor_name"] = mapping_df["anchor_name"].fillna("NONE")
        df = df.merge(
            mapping_df[["shop_name", "anchor_name", "org_name", "dept"]],
            left_on=["shop_name", "anchor"],
            right_on=["shop_name", "anchor_name"],
            how="left"
        )
        # 处理未匹配到的店铺：使用 shop_name 级别的默认映射（如果存在）
        null_mask = df["org_name"].isna()
        if null_mask.any():
            # 以 shop_name 为键，取第一条映射作为后备
            fallback_map = mapping_df.drop_duplicates(subset=["shop_name"], keep="first")[["shop_name", "org_name", "dept"]]
            fallback_map = fallback_map.rename(columns={"org_name": "org_fallback", "dept": "dept_fallback"})
            df = df.merge(fallback_map, on="shop_name", how="left")
            df.loc[null_mask, "org_name"] = df.loc[null_mask, "org_fallback"]
            df.loc[null_mask, "dept"] = df.loc[null_mask, "dept_fallback"]
            df = df.drop(columns=["org_fallback", "dept_fallback"])
        # 填充最终默认值
        df["org_name"] = df["org_name"].fillna("未分配组织")
        df["dept"] = df["dept"].fillna("未分配部门")
    else:
        # 非全部数据或映射表为空，填充默认值
        df["org_name"] = "未分配组织"
        df["dept"] = "未分配部门"

    # 5. 重命名金额列
    df = df.rename(columns={
        "ship_amount": "total_ship",
        "return_amount": "total_return",
        "net_amount": "total_net"
    })

    # 6. 返回所需列
    return df[["sale_date", "org_name", "dept", "shop_name", "total_ship", "total_return", "total_net"]]

# ---------- 商品销售数据加载（用于商品详情页，保留原逻辑不变） ----------
@st.cache_data(ttl=300)
def load_product_sales(suffix=None, apply_filter=True, include_offline=True):
    # 此函数未改，保持原有逻辑（已在问题中提供，此处省略以节省篇幅，实际使用需保留）
    # 但为了完整性，这里给出占位，实际部署时请保留您原有的完整函数
    # 为了确保不丢失，我们在此处只写注释，您可将之前的完整函数复制过来。
    pass

# ---------- 获取日期范围（高效） ----------
@st.cache_data(ttl=600)
def get_sales_date_range(suffix=""):
    if supabase is None:
        return None, None
    try:
        table_name = get_table_name("product_sales", suffix)
        min_resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=False).limit(1).execute()
        max_resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=True).limit(1).execute()
        min_date = pd.to_datetime(min_resp.data[0]["sale_date"]).date() if min_resp.data else None
        max_date = pd.to_datetime(max_resp.data[0]["sale_date"]).date() if max_resp.data else None
        return min_date, max_date
    except Exception as e:
        st.error(f"获取日期范围失败：{e}")
        return None, None

# ---------- 其他函数（目标管理、商品主数据等，保持不变） ----------
# （此处省略，您可将原有的 load_product_master, load_org_targets, save_org_targets,
#  load_targets, save_targets, clear_targets 等函数复制进来）
# 确保它们被包含在最终的 db.py 中。

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
