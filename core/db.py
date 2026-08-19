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
def fetch_sales_summary(start_date, end_date, suffix="", view_mode=None):
    """
    获取销售汇总数据，返回明细（含组织、部门、店铺、主播），用于组织排行、部门排行及线下明细。
    返回字段：sale_date, org_name, dept, shop_name, anchor, source, total_ship, total_return, total_net
    """
    required_columns = ["sale_date", "org_name", "dept", "shop_name", "anchor", "source", "total_ship", "total_return", "total_net"]
    
    if supabase is None:
        return pd.DataFrame(columns=required_columns)

    def clean_str_upper(s):
        if isinstance(s, str):
            return s.strip().upper()
        return s

    # ---- 加载 mapping 表 ----
    mapping_df = load_dimension_mapping()
    mapping_exists = suffix == "_all" and not mapping_df.empty

    # ---- 线上数据处理 ----
    product_table = get_table_name("product_sales", suffix)
    use_anchor = True
    try:
        supabase.table(product_table).select("anchor_name").limit(1).execute()
    except Exception:
        use_anchor = False

    online_data = []
    page = 0
    page_size = 1000
    while True:
        try:
            if use_anchor:
                select_cols = "sale_date, shop_name, remark, ship_amount, return_amount, net_amount, anchor_name"
            else:
                select_cols = "sale_date, shop_name, remark, ship_amount, return_amount, net_amount"
            resp = supabase.table(product_table)\
                           .select(select_cols)\
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

    df_online = pd.DataFrame()
    if online_data:
        df_online = pd.DataFrame(online_data)
        df_online["sale_date"] = pd.to_datetime(df_online["sale_date"])
        if use_anchor and "anchor_name" in df_online.columns:
            df_online["anchor"] = df_online["anchor_name"].fillna("NONE")
        else:
            df_online["anchor"] = df_online["remark"].apply(extract_anchor).fillna("NONE")
        # 清理字符串
        df_online['shop_name'] = df_online['shop_name'].astype(str).str.strip().str.upper()
        df_online['anchor'] = df_online['anchor'].astype(str).str.strip().str.upper()
        # 按日期、店铺、主播聚合（保留明细）
        df_online = df_online.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
            "ship_amount": "sum",
            "return_amount": "sum",
            "net_amount": "sum"
        })
        # 映射组织与部门
        if mapping_exists:
            mapping_clean = mapping_df.copy()
            mapping_clean['shop_name'] = mapping_clean['shop_name'].astype(str).str.strip().str.upper()
            mapping_clean['anchor_name'] = mapping_clean['anchor_name'].astype(str).str.strip().str.upper()
            mapping_unique = mapping_clean.drop_duplicates(subset=['shop_name', 'anchor_name'], keep='first')
            key_to_org = mapping_unique.set_index(['shop_name', 'anchor_name'])['org_name'].to_dict()
            key_to_dept = mapping_unique.set_index(['shop_name', 'anchor_name'])['dept'].to_dict()
            df_online['org_name'] = df_online.apply(lambda row: key_to_org.get((row['shop_name'], row['anchor']), '未分配组织'), axis=1)
            df_online['dept'] = df_online.apply(lambda row: key_to_dept.get((row['shop_name'], row['anchor']), '未分配部门'), axis=1)
        else:
            df_online['org_name'] = '未分配组织'
            df_online['dept'] = '未分配部门'
        df_online['source'] = 'online'

    # ---- 线下数据处理（仅当 suffix == "_all"） ----
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
                    # 清理字段：线下有 org_name 列（从上传Excel的“组织名称”而来）
                    df_offline['org_name'] = df_offline['org_name'].astype(str).str.strip().str.upper()
                    df_offline['shop_name'] = df_offline['shop_name'].astype(str).str.strip().str.upper()
                    # 按日期、店铺聚合（线下无主播）
                    df_offline = df_offline.groupby(["sale_date", "shop_name", "org_name"], as_index=False).agg({
                        "ship_amount": "sum",
                        "return_amount": "sum",
                        "net_amount": "sum"
                    })
                    # 映射部门：用 org_name 匹配 mapping 表的 org_name
                    if mapping_exists:
                        mapping_clean = mapping_df.copy()
                        mapping_clean['org_name'] = mapping_clean['org_name'].astype(str).str.strip().str.upper()
                        mapping_unique_org = mapping_clean.drop_duplicates(subset=['org_name'], keep='first')
                        org_to_dept = mapping_unique_org.set_index('org_name')['dept'].to_dict()
                        df_offline['dept'] = df_offline['org_name'].map(org_to_dept).fillna('未分配部门')
                    else:
                        df_offline['dept'] = '未分配部门'
                    df_offline['anchor'] = 'NONE'
                    df_offline['source'] = 'offline'
        except Exception as e:
            st.warning(f"查询线下数据出错：{e}")

    # ---- 合并 ----
    if df_online.empty and df_offline.empty:
        return pd.DataFrame(columns=required_columns)
    elif df_online.empty:
        df = df_offline
    elif df_offline.empty:
        df = df_online
    else:
        df = pd.concat([df_online, df_offline], ignore_index=True)

    # ---- 重命名金额字段 ----
    df = df.rename(columns={
        "ship_amount": "total_ship",
        "return_amount": "total_return",
        "net_amount": "total_net"
    })

    # ---- 确保所有列存在 ----
    for col in required_columns:
        if col not in df.columns:
            if col in ["total_ship", "total_return", "total_net"]:
                df[col] = 0
            elif col == "anchor":
                df[col] = "NONE"
            else:
                df[col] = "未知"

    # ---- view_mode 过滤 ----
    view_mode_to_use = view_mode if view_mode is not None else st.session_state.get("view_mode")
    if view_mode_to_use == "shop":
        if 'dept' in df.columns:
            df = df[df['dept'] == '小店运营']
        else:
            df = pd.DataFrame(columns=required_columns)

    return df[required_columns]

# ---------- 完整的销售汇总（兼容旧版） ----------
@st.cache_data(ttl=60)
def fetch_complete_sales_summary(start_date, end_date, suffix="_all", view_mode=None):
    return fetch_sales_summary(start_date, end_date, suffix, view_mode=view_mode)

# ---------- 其余函数（load_product_sales, get_sales_date_range, load_product_master 等）保持不变 ----------
# ...（此处省略，可继续使用您原有的代码）
