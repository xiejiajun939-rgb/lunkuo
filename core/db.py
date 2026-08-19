# core/db.py （完整修正版）

# -*- coding: utf-8 -*-
"""
数据库操作公共模块（完整版）
包含所有业务函数，并优化了线下数据查询与映射逻辑。
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

# ---------- 核心聚合函数（缓存60秒） ----------
@st.cache_data(ttl=60)
def fetch_sales_summary(start_date, end_date, suffix=""):
    """
    获取销售汇总数据
    线上数据：使用 (shop_name, anchor) 匹配 mapping
    线下数据：使用 shop_name + 固定 anchor='NONE' 匹配 mapping
    返回列包含 anchor 以便于明细追溯。
    """
    # 定义所有必须返回的列
    required_columns = ["sale_date", "org_name", "dept", "shop_name", "anchor", "total_ship", "total_return", "total_net"]
    
    if supabase is None:
        return pd.DataFrame(columns=required_columns)

    def clean_shop_names(df):
        if 'shop_name' in df.columns:
            df['shop_name'] = df['shop_name'].astype(str).str.strip().str.upper()
        return df

    # 1. 线上数据（分页）
    product_table = get_table_name("product_sales", suffix)
    online_data = []
    page = 0
    page_size = 1000
    while True:
        try:
            resp = supabase.table(product_table)\
                           .select("sale_date, shop_name, remark, ship_amount, return_amount, net_amount, anchor_name")\
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
        except Exception as e:
            st.warning(f"查询线上数据出错：{e}")
            break

    if online_data:
        df_online = pd.DataFrame(online_data)
        df_online["sale_date"] = pd.to_datetime(df_online["sale_date"])
        # 确保 anchor 字段存在，若没有则从 remark 提取
        if 'anchor_name' not in df_online.columns:
            df_online["anchor"] = df_online["remark"].apply(extract_anchor).fillna("NONE")
        else:
            df_online["anchor"] = df_online["anchor_name"].fillna("NONE")
        # 按日期、店铺、主播聚合
        df_online = df_online.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
            "ship_amount": "sum",
            "return_amount": "sum",
            "net_amount": "sum"
        })
        df_online = clean_shop_names(df_online)
    else:
        df_online = pd.DataFrame()

    # 2. 线下数据（全量，内存过滤）
    df_offline = pd.DataFrame()
    if suffix == "_all":
        try:
            offline_resp = supabase.table("offline_sales_all").select("*").execute()
            if offline_resp.data:
                df_offline = pd.DataFrame(offline_resp.data)
                df_offline["sale_date"] = pd.to_datetime(df_offline["sale_date"])
                start_ts = pd.Timestamp(start_date)
                end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                df_offline = df_offline[(df_offline["sale_date"] >= start_ts) & (df_offline["sale_date"] <= end_ts)]
                if not df_offline.empty:
                    # 线下数据没有 anchor_name，固定为 'NONE'
                    df_offline["anchor"] = "NONE"
                    df_offline = df_offline.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
                        "ship_amount": "sum",
                        "return_amount": "sum",
                        "net_amount": "sum"
                    })
                    df_offline = clean_shop_names(df_offline)
        except Exception as e:
            st.warning(f"查询线下数据出错：{e}")

    # 3. 合并
    if df_online.empty and df_offline.empty:
        # 返回包含所有列的空 DataFrame
        return pd.DataFrame(columns=required_columns)
    elif df_online.empty:
        df = df_offline
    elif df_offline.empty:
        df = df_online
    else:
        df = pd.concat([df_online, df_offline], ignore_index=True)

    # 4. 加载映射表
    mapping_df = load_dimension_mapping()

    # 5. 映射组织和部门
    if suffix == "_all" and not mapping_df.empty:
        # 创建 (shop_name, anchor_name) -> (org_name, dept) 的映射字典
        mapping_df['shop_name'] = mapping_df['shop_name'].astype(str).str.strip().str.upper()
        mapping_df['anchor_name'] = mapping_df['anchor_name'].astype(str).str.strip().str.upper()
        mapping_unique = mapping_df.drop_duplicates(subset=['shop_name', 'anchor_name'], keep='first')
        key_to_org = mapping_unique.set_index(['shop_name', 'anchor_name'])['org_name'].to_dict()
        key_to_dept = mapping_unique.set_index(['shop_name', 'anchor_name'])['dept'].to_dict()
        
        df['org_name'] = df.apply(lambda row: key_to_org.get((row['shop_name'], row['anchor']), None), axis=1)
        df['dept'] = df.apply(lambda row: key_to_dept.get((row['shop_name'], row['anchor']), None), axis=1)
        
        df['org_name'] = df['org_name'].fillna('未分配组织')
        df['dept'] = df['dept'].fillna('未分配部门')
    else:
        df["org_name"] = "未分配组织"
        df["dept"] = "未分配部门"

    # 6. 重命名列
    df = df.rename(columns={
        "ship_amount": "total_ship",
        "return_amount": "total_return",
        "net_amount": "total_net"
    })

    # 7. 确保所有必要的列都存在（包括 anchor）
    for col in required_columns:
        if col not in df.columns:
            if col in ["total_ship", "total_return", "total_net"]:
                df[col] = 0
            elif col == "anchor":
                df[col] = "NONE"
            else:
                df[col] = "未知"

    return df[required_columns]

# ---------- 其他函数保持不变 ----------
# （为了节省篇幅，以下省略 load_product_sales, get_sales_date_range, load_product_master, 等函数，它们与之前完全相同）
# 但实际使用时请确保它们都在文件中。
