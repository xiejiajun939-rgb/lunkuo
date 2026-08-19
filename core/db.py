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

# ---------- 辅助：从备注中提取组织名称 ----------
def extract_org_from_remark(remark):
    """从备注中提取组织名称"""
    if not remark or not isinstance(remark, str):
        return None
    
    # 常见的组织标识模式
    patterns = [
        r'组织[：:]\s*([^\s_]+)',
        r'部门[：:]\s*([^\s_]+)',
        r'阿米巴[：:]\s*([^\s_]+)',
        r'([^_\s]+)组',
        r'([^_\s]+)部',
        r'([^_\s]+)团队',
        r'([^_\s]+)中心',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, remark)
        if match:
            return match.group(1).strip()
    
    # 如果都没有匹配，尝试从 _ 分割中提取
    parts = remark.split('_')
    if len(parts) >= 2:
        # 通常第一个部分可能是组织标识
        first_part = parts[0].strip()
        if len(first_part) > 1:
            return first_part
    
    return None

# ---------- 辅助：从店铺名提取平台 ----------
def classify_platform(shop_name):
    """从店铺名称识别平台"""
    if not shop_name or not isinstance(shop_name, str):
        return '其他'
    shop_name = str(shop_name)
    if shop_name.startswith('天猫'):
        return '天猫'
    elif shop_name.startswith('小红书'):
        return '小红书'
    elif shop_name.startswith('抖音'):
        return '抖音'
    elif shop_name.startswith('视频号'):
        return '视频号'
    elif shop_name.startswith('京东'):
        return '京东'
    elif shop_name.startswith('拼多多'):
        return '拼多多'
    elif shop_name.startswith('淘宝'):
        return '淘宝'
    elif '线下' in shop_name or '门店' in shop_name or shop_name.startswith('线下'):
        return '线下门店'
    elif '微信' in shop_name or '小程序' in shop_name:
        return '微信'
    else:
        return '其他'

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

# ---------- 核心聚合函数（缓存60秒）- 增强版 ----------
@st.cache_data(ttl=60)
def fetch_sales_summary(start_date, end_date, suffix=""):
    """
    获取销售汇总数据（增强版）
    支持从 product_sales 和 offline_sales 两个表获取数据
    并自动映射组织名称和部门
    """
    if supabase is None:
        return pd.DataFrame()

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
        except Exception as e:
            st.warning(f"查询线上数据出错：{e}")
            break

    if online_data:
        df_online = pd.DataFrame(online_data)
        df_online["sale_date"] = pd.to_datetime(df_online["sale_date"])
        
        # 提取主播信息
        if suffix == "_all":
            df_online["anchor"] = df_online["remark"].apply(extract_anchor).fillna("NONE")
        else:
            df_online["anchor"] = "NONE"
        
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
        return pd.DataFrame()
    elif df_online.empty:
        df = df_offline
    elif df_offline.empty:
        df = df_online
    else:
        df = pd.concat([df_online, df_offline], ignore_index=True)

    # 4. 加载映射表
    mapping_df = load_dimension_mapping()

    # 5. 映射组织名称和部门
    if suffix == "_all" and not mapping_df.empty:
        # 创建 shop_name -> (org_name, dept) 的映射
        mapping_df['shop_name'] = mapping_df['shop_name'].astype(str).str.strip().str.upper()
        shop_dept_map = mapping_df.drop_duplicates(subset=['shop_name'], keep='first').set_index('shop_name')['dept'].to_dict()
        shop_org_map = mapping_df.drop_duplicates(subset=['shop_name'], keep='first').set_index('shop_name')['org_name'].to_dict()
        
        # 使用映射填充
        df['dept'] = df['shop_name'].map(shop_dept_map)
        df['org_name'] = df['shop_name'].map(shop_org_map)
        
        # 对于未能映射的店铺，尝试从 remark 中提取组织名称
        unmasked = df['org_name'].isna()
        if unmasked.any():
            # 尝试从 shop_name 本身提取
            df.loc[unmasked, 'org_name'] = df.loc[unmasked, 'shop_name'].apply(
                lambda x: extract_org_from_remark(x) if isinstance(x, str) else None
            )
        
        # 填充默认值
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

    # 7. 确保所有必要的列都存在
    for col in ["sale_date", "org_name", "dept", "shop_name", "total_ship", "total_return", "total_net"]:
        if col not in df.columns:
            if col in ["total_ship", "total_return", "total_net"]:
                df[col] = 0
            else:
                df[col] = "未知"

    return df[["sale_date", "org_name", "dept", "shop_name", "total_ship", "total_return", "total_net"]]

# ---------- 新增：完整的销售汇总（兼容旧版） ----------
@st.cache_data(ttl=60)
def fetch_complete_sales_summary(start_date, end_date, suffix="_all"):
    """
    完整的销售汇总数据获取函数
    与 fetch_sales_summary 功能相同，但更明确地包含线下数据
    保留此函数以保持向后兼容
    """
    return fetch_sales_summary(start_date, end_date, suffix)

# ---------- 商品销售数据加载（用于商品详情页） ----------
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

        # 合并线下收入
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
                    # 从 remark 或 shop_name 中提取组织信息
                    offline_df["org_name"] = offline_df["remark"].apply(extract_org_from_remark)
                    offline_df["dept"] = offline_df["org_name"]  # 默认使用组织名作为部门
                    
                    # 对齐列
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
        
        # 如果是 _all 模式，也检查线下数据
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
