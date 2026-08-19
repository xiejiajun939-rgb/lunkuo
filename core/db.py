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

# ---------- 辅助：从备注中提取组织名称（修复版） ----------
def extract_org_from_remark(remark):
    """
    从备注中提取组织名称
    注意：备注格式通常为：商品信息_店铺名_组织名 或 组织名_商品信息_店铺名
    """
    if not remark or not isinstance(remark, str):
        return None
    
    remark_str = str(remark).strip()
    
    # 排除明显的订单号/编号模式（纯数字、订单号格式等）
    # 如果整个备注是纯数字或短数字，不提取
    if re.match(r'^\d+$', remark_str):
        return None
    if re.match(r'^[A-Z0-9]{8,}$', remark_str):
        return None
    
    # 优先匹配明确标识：组织：xxx、部门：xxx、阿米巴：xxx
    patterns = [
        r'组织[：:]\s*([^\s_，,]+)',
        r'部门[：:]\s*([^\s_，,]+)',
        r'阿米巴[：:]\s*([^\s_，,]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, remark_str)
        if match:
            result = match.group(1).strip()
            # 排除数字和订单号
            if not re.match(r'^\d+$', result) and len(result) > 1:
                return result
    
    # 尝试从下划线分割中提取
    parts = remark_str.split('_')
    
    # 如果分割后有多个部分，尝试识别组织名称
    if len(parts) >= 2:
        # 常见组织名称关键词
        org_keywords = ['组', '部', '团队', '中心', '事业', '阿米巴', 'BU', '部门']
        
        # 从后往前查找，因为组织名通常在最后
        for part in reversed(parts):
            part_clean = part.strip()
            if not part_clean:
                continue
            # 排除纯数字
            if re.match(r'^\d+$', part_clean):
                continue
            # 排除过短的内容
            if len(part_clean) < 2:
                continue
            # 检查是否包含组织关键词
            for keyword in org_keywords:
                if keyword in part_clean:
                    return part_clean
            # 检查是否包含"商店"、"店铺"等店铺关键词（这些应该被排除）
            if '商店' in part_clean or '店铺' in part_clean:
                continue
        
        # 如果都没有匹配，取最后一个非数字、非店铺名的部分
        for part in reversed(parts):
            part_clean = part.strip()
            if not part_clean:
                continue
            if re.match(r'^\d+$', part_clean):
                continue
            if len(part_clean) < 2:
                continue
            if '商店' in part_clean or '店铺' in part_clean:
                continue
            return part_clean
    
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
            # 清理店铺名（大写，去除空格）
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

# ---------- 核心聚合函数（缓存60秒）- 修复版 ----------
@st.cache_data(ttl=60)
def fetch_sales_summary(start_date, end_date, suffix=""):
    """
    获取销售汇总数据（修复版）
    1. 优先使用 mapping 表映射组织名称和部门
    2. 只有 mapping 表无法匹配时，才尝试从 remark 提取
    3. 正确区分组织名称和店铺名称
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

    # 5. 映射组织名称和部门 - 优先使用 mapping 表
    if suffix == "_all" and not mapping_df.empty:
        # 创建 shop_name -> (org_name, dept) 的映射
        mapping_df['shop_name'] = mapping_df['shop_name'].astype(str).str.strip().str.upper()
        
        # 使用 drop_duplicates 确保每个 shop_name 只有一条映射
        mapping_unique = mapping_df.drop_duplicates(subset=['shop_name'], keep='first')
        shop_org_map = mapping_unique.set_index('shop_name')['org_name'].to_dict()
        shop_dept_map = mapping_unique.set_index('shop_name')['dept'].to_dict()
        
        # 先用 mapping 表映射
        df['org_name'] = df['shop_name'].map(shop_org_map)
        df['dept'] = df['shop_name'].map(shop_dept_map)
        
        # 对于 mapping 表无法匹配的店铺，尝试从 remark 提取组织名称
        # 注意：只对 "未分配组织" 的记录尝试提取
        unmasked = df['org_name'].isna() | (df['org_name'] == '未分配组织')
        if unmasked.any():
            # 获取这些记录的 remark 信息
            # 注意：此时 df 中可能没有 remark 列，需要重新关联
            # 由于聚合后丢失了 remark，我们只能从 shop_name 中尝试提取
            df.loc[unmapped, 'org_name'] = df.loc[unmapped, 'shop_name'].apply(
                lambda x: extract_org_from_shop_name(x) if isinstance(x, str) else None
            )
            # 如果还是无法提取，使用 '未分配组织'
            df['org_name'] = df['org_name'].fillna('未分配组织')
            # 部门默认使用组织名称
            df.loc[df['dept'].isna() | (df['dept'] == '未分配部门'), 'dept'] = df.loc[df['dept'].isna() | (df['dept'] == '未分配部门'), 'org_name']
        
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

# ---------- 辅助：从店铺名提取组织（用于无法匹配的情况） ----------
def extract_org_from_shop_name(shop_name):
    """从店铺名中提取组织名称（备用方案）"""
    if not shop_name or not isinstance(shop_name, str):
        return None
    
    shop_name = str(shop_name).strip()
    
    # 排除纯数字
    if re.match(r'^\d+$', shop_name):
        return None
    
    # 常见的组织名称关键词
    org_keywords = ['组', '部', '团队', '中心', '事业', '阿米巴', 'BU']
    
    for keyword in org_keywords:
        if keyword in shop_name:
            # 提取包含关键词的部分
            match = re.search(r'([^\s_]+' + keyword + r')', shop_name)
            if match:
                return match.group(1)
    
    # 如果店铺名包含下划线，尝试取第一部分
    if '_' in shop_name:
        parts = shop_name.split('_')
        for part in parts:
            part_clean = part.strip()
            if not part_clean:
                continue
            if re.match(r'^\d+$', part_clean):
                continue
            if len(part_clean) >= 2:
                return part_clean
    
    return None

# ---------- 完整的销售汇总（兼容旧版） ----------
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
                    # 使用映射表或从备注提取组织
                    if mapping_df is not None and not mapping_df.empty:
                        shop_org_map = mapping_df.drop_duplicates(subset=['shop_name'], keep='first').set_index('shop_name')['org_name'].to_dict()
                        shop_dept_map = mapping_df.drop_duplicates(subset=['shop_name'], keep='first').set_index('shop_name')['dept'].to_dict()
                        offline_df["org_name"] = offline_df["shop_name"].map(shop_org_map)
                        offline_df["dept"] = offline_df["shop_name"].map(shop_dept_map)
                    else:
                        offline_df["org_name"] = offline_df["remark"].apply(extract_org_from_remark)
                        offline_df["dept"] = offline_df["org_name"]
                    
                    offline_df["org_name"] = offline_df["org_name"].fillna("未分配组织")
                    offline_df["dept"] = offline_df["dept"].fillna("未分配部门")
                    
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
