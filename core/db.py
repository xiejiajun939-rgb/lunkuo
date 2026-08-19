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
    获取销售汇总数据
    线上数据：使用 (shop_name, anchor) 匹配 mapping
    线下数据：使用 shop_name + 固定 anchor='NONE' 匹配 mapping
    自动探测 anchor_name 列是否存在。
    返回列包含 anchor 以便于明细追溯。
    view_mode: 可选，覆盖 session 中的 view_mode。若为 None 则从 session 读取。
    """
    required_columns = ["sale_date", "org_name", "dept", "shop_name", "anchor", "total_ship", "total_return", "total_net"]
    
    if supabase is None:
        return pd.DataFrame(columns=required_columns)

    def clean_shop_names(df):
        if 'shop_name' in df.columns:
            df['shop_name'] = df['shop_name'].astype(str).str.strip().str.upper()
        return df

    # ---- 探测 anchor_name 列是否存在 ----
    product_table = get_table_name("product_sales", suffix)
    use_anchor = True
    try:
        supabase.table(product_table).select("anchor_name").limit(1).execute()
    except Exception as e:
        if "does not exist" in str(e).lower() or "column" in str(e).lower():
            use_anchor = False
        else:
            raise

    # ---- 线上数据 ----
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

    if online_data:
        df_online = pd.DataFrame(online_data)
        df_online["sale_date"] = pd.to_datetime(df_online["sale_date"])
        if use_anchor and "anchor_name" in df_online.columns:
            df_online["anchor"] = df_online["anchor_name"].fillna("NONE")
        else:
            df_online["anchor"] = df_online["remark"].apply(extract_anchor).fillna("NONE")
        df_online = df_online.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
            "ship_amount": "sum",
            "return_amount": "sum",
            "net_amount": "sum"
        })
        df_online = clean_shop_names(df_online)
    else:
        df_online = pd.DataFrame()

    # ---- 线下数据 ----
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
                    df_offline["anchor"] = "NONE"
                    df_offline = df_offline.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
                        "ship_amount": "sum",
                        "return_amount": "sum",
                        "net_amount": "sum"
                    })
                    df_offline = clean_shop_names(df_offline)
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

    # ---- 映射 ----
    mapping_df = load_dimension_mapping()
    if suffix == "_all" and not mapping_df.empty:
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

    # ---- 重命名 ----
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

    # ========== 小店运营模式过滤 ==========
    view_mode_to_use = view_mode if view_mode is not None else st.session_state.get("view_mode")
    if view_mode_to_use == "shop":
        if 'dept' in df.columns:
            df = df[df['dept'] == '小店运营']
        else:
            df = pd.DataFrame(columns=required_columns)
    # 若 view_mode_to_use 为 "all" 或 "normal"，则不过滤

    return df[required_columns]

# ---------- 完整的销售汇总（兼容旧版） ----------
@st.cache_data(ttl=60)
def fetch_complete_sales_summary(start_date, end_date, suffix="_all", view_mode=None):
    """与 fetch_sales_summary 功能相同，增加 view_mode 参数"""
    return fetch_sales_summary(start_date, end_date, suffix, view_mode=view_mode)

# ---------- 商品销售数据加载（用于商品详情页） ----------
@st.cache_data(ttl=300)
def load_product_sales(suffix=None, apply_filter=True, include_offline=True):
    if supabase is None:
        return pd.DataFrame()
    try:
        table_name = get_table_name("product_sales", suffix)
        
        # ---- 探测 anchor_name 列是否存在 ----
        use_anchor = True
        try:
            supabase.table(table_name).select("anchor_name").limit(1).execute()
        except Exception as e:
            if "does not exist" in str(e).lower() or "column" in str(e).lower():
                use_anchor = False
            else:
                raise

        base_cols = "sale_date, shop_name, product_code, style_code, brand, year, season, product_category, style, color_code, size_code, ship_amount, return_amount, net_amount, remark"
        select_cols = base_cols + ", anchor_name" if use_anchor else base_cols

        all_data = []
        page = 0
        page_size = 1000
        while True:
            resp = supabase.table(table_name).select(select_cols).range(page*page_size, (page+1)*page_size-1).execute()
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

        # 生成 anchor 列
        if use_anchor and "anchor_name" in df.columns:
            df["anchor"] = df["anchor_name"].fillna("NONE")
        else:
            df["anchor"] = df["remark"].apply(extract_anchor).fillna("NONE")

        # 合并线下数据（仅 _all）
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

        # 映射组织和部门
        mapping_df = load_dimension_mapping()
        if suffix == "_all" and not mapping_df.empty:
            mapping_df['shop_name'] = mapping_df['shop_name'].astype(str).str.strip().str.upper()
            mapping_df['anchor_name'] = mapping_df['anchor_name'].astype(str).str.strip().str.upper()
            mapping_unique = mapping_df.drop_duplicates(subset=['shop_name', 'anchor_name'], keep='first')
            key_to_org = mapping_unique.set_index(['shop_name', 'anchor_name'])['org_name'].to_dict()
            key_to_dept = mapping_unique.set_index(['shop_name', 'anchor_name'])['dept'].to_dict()
            df['org_name'] = df.apply(lambda row: key_to_org.get((row['shop_name'], row['anchor']), '未分配组织'), axis=1)
            df['dept'] = df.apply(lambda row: key_to_dept.get((row['shop_name'], row['anchor']), '未分配部门'), axis=1)
        else:
            df["org_name"] = "未分配组织"
            df["dept"] = "未分配部门"

        # ========== 小店运营模式过滤 ==========
        view_mode_to_use = st.session_state.get("view_mode")
        if view_mode_to_use == "shop":
            if 'dept' in df.columns:
                df = df[df['dept'] == '小店运营']
            else:
                df = pd.DataFrame()

        if apply_filter:
            from core.utils import apply_data_permission
            df = apply_data_permission(df)
        return df
    except Exception as e:
        st.error(f"加载商品销售数据失败：{e}")
        return pd.DataFrame()

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
