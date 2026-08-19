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
# ---------- 核心聚合函数（已修复线下数据拉取与映射） ----------
@st.cache_data(ttl=60)
def fetch_sales_summary(start_date, end_date, suffix="", view_mode=None):
    required_columns = ["sale_date", "org_name", "dept", "shop_name", "anchor", "source", "total_ship", "total_return", "total_net"]
    
    if supabase is None:
        return pd.DataFrame(columns=required_columns)

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
    start_str = start_date.isoformat()
    end_str = f"{end_date.isoformat()}T23:59:59"

    while True:
        try:
            select_cols = "sale_date, shop_name, remark, ship_amount, return_amount, net_amount"
            if use_anchor:
                select_cols += ", anchor_name"

            resp = supabase.table(product_table)\
                           .select(select_cols)\
                           .gte("sale_date", start_str)\
                           .lte("sale_date", end_str)\
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
            df_online["anchor"] = df_online["anchor_name"].fillna("NONE").replace('', 'NONE')
        else:
            df_online["anchor"] = df_online["remark"].apply(extract_anchor).fillna("NONE").replace('', 'NONE')
        
        df_online['shop_name'] = df_online['shop_name'].astype(str).str.strip().str.upper()
        df_online['anchor'] = df_online['anchor'].astype(str).str.strip().str.upper()
        
        df_online = df_online.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
            "ship_amount": "sum",
            "return_amount": "sum",
            "net_amount": "sum"
        })
        
        if mapping_exists:
            mapping_clean = mapping_df.copy()
            mapping_clean['shop_name'] = mapping_clean['shop_name'].astype(str).str.strip().str.upper()
            mapping_clean['anchor_name'] = mapping_clean['anchor_name'].astype(str).str.strip().str.upper()
            
            # 双级映射逻辑：优先匹配 (shop_name, anchor_name)，若匹配不到降级使用 shop_name 匹配
            mapping_anchor = mapping_clean.drop_duplicates(subset=['shop_name', 'anchor_name'], keep='first')
            key_to_org = mapping_anchor.set_index(['shop_name', 'anchor_name'])['org_name'].to_dict()
            key_to_dept = mapping_anchor.set_index(['shop_name', 'anchor_name'])['dept'].to_dict()

            mapping_shop = mapping_clean.drop_duplicates(subset=['shop_name'], keep='first')
            shop_to_org = mapping_shop.set_index('shop_name')['org_name'].to_dict()
            shop_to_dept = mapping_shop.set_index('shop_name')['dept'].to_dict()

            def get_dept(row):
                dept = key_to_dept.get((row['shop_name'], row['anchor']))
                if not dept or dept == '未分配部门':
                    dept = shop_to_dept.get(row['shop_name'], '未分配部门')
                return dept

            def get_org(row):
                org = key_to_org.get((row['shop_name'], row['anchor']))
                if not org or org == '未分配组织':
                    org = shop_to_org.get(row['shop_name'], '未分配组织')
                return org

            df_online['dept'] = df_online.apply(get_dept, axis=1)
            df_online['org_name'] = df_online.apply(get_org, axis=1)
        else:
            df_online['org_name'] = '未分配组织'
            df_online['dept'] = '未分配部门'
        df_online['source'] = 'online'

    # ---- 线下数据处理（已修复：添加服务端日期筛选与分页循环） ----
    df_offline = pd.DataFrame()
    if suffix == "_all":
        try:
            offline_data = []
            page = 0
            
            while True:
                offline_resp = supabase.table("offline_sales_all")\
                                       .select("*")\
                                       .gte("sale_date", start_str)\
                                       .lte("sale_date", end_str)\
                                       .range(page * page_size, (page + 1) * page_size - 1)\
                                       .execute()
                if not offline_resp.data:
                    break
                offline_data.extend(offline_resp.data)
                if len(offline_resp.data) < page_size:
                    break
                page += 1

            if offline_data:
                df_offline = pd.DataFrame(offline_data)
                df_offline["sale_date"] = pd.to_datetime(df_offline["sale_date"])
                if not df_offline.empty:
                    df_offline['shop_name'] = df_offline['shop_name'].astype(str).str.strip().str.upper()
                    
                    df_offline = df_offline.groupby(["sale_date", "shop_name"], as_index=False).agg({
                        "ship_amount": "sum",
                        "return_amount": "sum",
                        "net_amount": "sum"
                    })
                    
                    if mapping_exists:
                        mapping_unique_offline = mapping_df.drop_duplicates(subset=['shop_name'], keep='first')
                        shop_to_org = mapping_unique_offline.set_index('shop_name')['org_name'].to_dict()
                        shop_to_dept = mapping_unique_offline.set_index('shop_name')['dept'].to_dict()
                        
                        df_offline['org_name'] = df_offline['shop_name'].map(shop_to_org).fillna('未分配组织')
                        df_offline['dept'] = df_offline['shop_name'].map(shop_to_dept).fillna('未分配部门')
                    else:
                        df_offline['org_name'] = '未分配组织'
                        df_offline['dept'] = '未分配部门'
                        
                    df_offline['anchor'] = 'NONE'
                    df_offline['source'] = 'offline'
        except Exception as e:
            st.warning(f"查询线下数据出错：{e}")

    # ---- 合并数据 ----
    if df_online.empty and df_offline.empty:
        return pd.DataFrame(columns=required_columns)
    elif df_online.empty:
        df = df_offline
    elif df_offline.empty:
        df = df_online
    else:
        df = pd.concat([df_online, df_offline], ignore_index=True)

    df = df.rename(columns={
        "ship_amount": "total_ship",
        "return_amount": "total_return",
        "net_amount": "total_net"
    })

    for col in required_columns:
        if col not in df.columns:
            if col in ["total_ship", "total_return", "total_net"]:
                df[col] = 0
            elif col == "anchor":
                df[col] = "NONE"
            else:
                df[col] = "未知"

    view_mode_to_use = view_mode if view_mode is not None else st.session_state.get("view_mode")
    if view_mode_to_use == "shop":
        if 'dept' in df.columns:
            df = df[df['dept'] == '小店运营']
        else:
            df = pd.DataFrame(columns=required_columns)

    return df[required_columns]
# ---------- 获取日期范围 ----------
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
        if suffix == "_all":
            try:
                offline_min = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=False).limit(1).execute()
                offline_max = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=True).limit(1).execute()
                if offline_min.data and offline_max.data:
                    off_min = pd.to_datetime(offline_min.data[0]["sale_date"]).date()
                    off_max = pd.to_datetime(offline_max.data[0]["sale_date"]).date()
                    if min_date is None or off_min < min_date:
                        min_date = off_min
                    if max_date is None or off_max > max_date:
                        max_date = off_max
            except:
                pass
        return min_date, max_date
    except Exception as e:
        st.error(f"获取日期范围失败：{e}")
        return None, None

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
