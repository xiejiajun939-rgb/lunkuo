# -*- coding: utf-8 -*-
"""
订单业绩统计工具 - 完整版（支持全部数据源的组织/部门维度）
管理员账号：admin / 1234567890
子账号存储在 Supabase 的 sub_accounts 表中
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
import io
import hashlib
import time
import re
import numpy as np
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from openai import OpenAI

# ========== 导入公共模块（替代原先直接定义的函数） ==========
from core.db import init_supabase, get_table_name, load_product_sales, load_product_master, load_dimension_mapping
from core.utils import extract_anchor, parse_product_code, date_quick_buttons, apply_data_permission
from core.ai import get_siliconflow_client, get_ai_summary

# 添加一个全局防抖变量
if "last_rerun" not in st.session_state:
    st.session_state.last_rerun = 0

def safe_rerun():
    """防止过于频繁的重绘"""
    now = time.time()
    if now - st.session_state.last_rerun > 0.5:  # 至少间隔 0.5 秒
        st.session_state.last_rerun = now
        st.rerun()

st.set_page_config(page_title="业绩统计工具", layout="wide", page_icon="📊")

# ========== 自定义CSS ==========
st.markdown("""
<style>
    .custom-main-title { font-size: 28px !important; font-weight: 600 !important; margin-top: -0.5rem !important; margin-bottom: 0.25rem !important; padding-bottom: 0 !important; color: #1e293b !important; }
    .welcome-text { font-size: 14px !important; color: #475569 !important; margin-top: 0 !important; margin-bottom: 0.5rem !important; }
    h1 { font-size: 28px !important; margin-top: -0.5rem !important; margin-bottom: 0.25rem !important; color: #1e293b !important; }
    h2 { font-size: 24px !important; margin-top: 0.5rem !important; margin-bottom: 0.25rem !important; font-weight: 500 !important; color: #1e293b !important; }
    h3 { font-size: 20px !important; margin-top: 0.5rem !important; margin-bottom: 0.25rem !important; font-weight: 500 !important; color: #1e293b !important; }
    h4 { font-size: 18px !important; margin-top: 0.5rem !important; margin-bottom: 0.25rem !important; font-weight: 500 !important; color: #1e293b !important; }
    h5, h6 { font-size: 16px !important; margin-top: 0.25rem !important; margin-bottom: 0.25rem !important; color: #1e293b !important; }
    hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; border-color: #e2e8f0 !important; }
    .css-1d391kg h1, .css-1d391kg h2, .css-1d391kg h3 { font-size: 1.2rem !important; }
    div[data-testid="stButton"] button {
        padding: 4px 12px !important;
        font-size: 13px !important;
        border-radius: 6px !important;
        background-color: #f8fafc !important;
        border: 1px solid #d1d5db !important;
        color: #1f2937 !important;
        white-space: nowrap !important;
    }
    div[data-testid="stButton"] button:hover {
        background-color: #e2e8f0 !important;
    }
    div[data-testid="stDateInput"] label {
        display: none !important;
    }
   
    div[data-testid="stDateInput"] {
        margin-top: -5px !important;
    }
    .date-row {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
    }
    .css-1d391kg, .css-1d391kg .st-emotion-cache-1v0mbdj {
        background: #f1f5f9 !important;
    }
    .stDataFrame, .stTable, .stMarkdown table {
        color: #1e293b !important;
    }
    .stMarkdown td, .stMarkdown th {
        color: #1e293b !important;
    }
</style>
""", unsafe_allow_html=True)

# ========== Supabase 连接（使用公共模块的 init_supabase） ==========
# 注意：原脚本中定义 init_supabase 已删除，使用 from core.db import init_supabase
# 此处直接使用 supabase = init_supabase() 即可
# 但原脚本中多处使用 supabase 变量，为了兼容，我们可以定义全局 supabase 变量
# 不过原脚本中将 supabase 作为全局变量并使用，我们也在文件顶部获取一次并存储到 session_state? 
# 更好的方式：保持原脚本风格，在需要的地方调用 init_supabase()，因为它是带缓存的。
# 原脚本中在函数内部大多直接使用 supabase 变量，但由于我们删除了全局定义，需要修改。
# 但原脚本在函数内部调用 supabase 时，大多是在局部作用域内引用了外部全局变量 supabase，
# 由于我们删除了全局 supabase，会报错。因此需要将原脚本中所有直接使用 supabase 的地方改为调用 init_supabase()。
# 但这样改动较大，我们可以在文件顶部重新定义 supabase = init_supabase() 以兼容旧代码。
# 但 init_supabase 是带缓存的，多次调用也无妨，但为了最小改动，我们可以在文件顶部设置一个全局 supabase 变量。
# 因为原脚本很多地方直接使用 supabase.table() 等，所以我们定义一个全局 supabase 并赋值。

# 为了保持与原脚本兼容，我们重新建立全局 supabase 变量
supabase = init_supabase()

# 但注意：原脚本中有些函数内部也定义了自己的 supabase 局部变量，那没事。
# 我们保留原脚本中那些函数定义，它们内部可能直接引用全局 supabase。

# 以下保留原脚本中特有的函数（这些函数未移到 core，因为它们涉及写入、管理等）

# ========== 子账号数据库操作（不变） ==========
def load_sub_accounts_from_db():
    if supabase is None:
        return {}
    try:
        resp = supabase.table("sub_accounts").select("*").execute()
        if resp.data:
            sub_users = {}
            for row in resp.data:
                perms = row.get("permissions", {})
                if not perms and "allowed_tabs" in row:
                    perms = {"": row["allowed_tabs"], "_live": row["allowed_tabs"], "_all": row["allowed_tabs"]}
                sub_users[row["username"]] = {
                    "password": row["password"],
                    "role": row.get("role", "viewer"),
                    "default_suffix": row.get("default_suffix", ""),
                    "permissions": perms,
                    "filter_platform": row.get("filter_platform", "all"),
                    "filter_shop_names": row.get("filter_shop_names", [])
                }
            return sub_users
        else:
            return {}
    except Exception as e:
        st.error(f"加载子账号失败：{e}")
        return {}

def save_sub_account_to_db(username, info):
    if supabase is None:
        return False, "Supabase 未连接"
    try:
        data = {
            "username": username,
            "password": info["password"],
            "role": info["role"],
            "default_suffix": info["default_suffix"],
            "permissions": info.get("permissions", {}),
            "filter_platform": info.get("filter_platform", "all"),
            "filter_shop_names": info.get("filter_shop_names", [])
        }
        resp = supabase.table("sub_accounts").upsert(data, on_conflict="username").execute()
        return True, "保存成功"
    except Exception as e:
        return False, str(e)

def delete_sub_account_from_db(username):
    if supabase is None:
        return False, "Supabase 未连接"
    try:
        resp = supabase.table("sub_accounts").delete().eq("username", username).execute()
        return True, "删除成功"
    except Exception as e:
        return False, str(e)

def get_all_users():
    users = {
        "admin": {"password": "1234567890", "role": "admin", "default_suffix": ""},
        "XDZ01": {"password": "94949468", "role": "user", "default_suffix": ""},
        "ZBZ01": {"password": "123456", "role": "user", "default_suffix": "_live"}
    }
    if "sub_users" in st.session_state:
        for username, info in st.session_state.sub_users.items():
            users[username] = info
    return users

def login():
    st.title("🔐 数据罗盘 - 登录")
    with st.form("login_form"):
        username = st.text_input("用户名")
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录")
        if submitted:
            users = get_all_users()
            if username in users and users[username]["password"] == password:
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.role = users[username]["role"]
                st.session_state.table_suffix = users[username]["default_suffix"]
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("用户名或密码错误")

# ========== 初始化 session_state ==========
if "sub_users" not in st.session_state:
    st.session_state.sub_users = load_sub_accounts_from_db()
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if not st.session_state.authenticated:
    login()
    st.stop()

# ========== 主页面 ==========
st.markdown('<div class="custom-main-title">📊 抖音&视频号商品销售分析罗盘</div>', unsafe_allow_html=True)
st.markdown(f'<div class="welcome-text">欢迎，**{st.session_state.username}** ({"管理员" if st.session_state.role == "admin" else ("子账号" if st.session_state.role == "viewer" else "成员")})</div>', unsafe_allow_html=True)
st.markdown("---")

if "df_all_daily" not in st.session_state:
    st.session_state.df_all_daily = None
if "target_dict" not in st.session_state:
    st.session_state.target_dict = {}
if "latest_date" not in st.session_state:
    st.session_state.latest_date = None
if "uploaded_file_hash" not in st.session_state:
    st.session_state.uploaded_file_hash = None
if "daily_latest" not in st.session_state:
    st.session_state.daily_latest = None
if "monthly_actual" not in st.session_state:
    st.session_state.monthly_actual = None
if "processing_upload" not in st.session_state:
    st.session_state.processing_upload = False

# ========== 数据权限过滤函数（使用公共模块的 apply_data_permission，但原脚本中也有自定义，我们保留原脚本中的? 
# 因为原脚本中也有一个 apply_data_permission 定义，但我们已经导入，所以注释掉本地定义，使用导入的。
# 但原脚本中在 load_daily_sales 等函数里调用 apply_data_permission，我们只需确保导入的函数可用。
# 由于我们已 from core.utils import apply_data_permission，所以可以直接使用。
# 但我们还需保留一个本地函数吗？不需要，因为已经导入。

# ========== 新日期快捷按钮函数（使用公共模块的 date_quick_buttons，不再定义） ==========

# ========== 辅助函数 ==========
def extract_anchor(remark):
    # 已从 utils 导入，但为了兼容原脚本中其他地方调用，我们保留一个本地别名或者直接使用导入的。
    # 为了避免冲突，我们可以不定义，因为导入的已经可用。
    # 但原脚本中有些地方可能直接调用 extract_anchor，由于我们已导入，函数可用。
    # 为了安全，不定义本地函数，使用导入的。
    pass  # 实际使用 from core.utils import extract_anchor

# ========== RPC 聚合与刷新函数 ==========
@st.cache_data(ttl=300)
def fetch_sales_summary(start_date, end_date, suffix=""):
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

def refresh_materialized_view(suffix=""):
    """刷新物化视图"""
    if supabase is None:
        return
    try:
        supabase.rpc('refresh_mv', {'suffix': suffix}).execute()
    except Exception as e:
        st.warning(f"物化视图刷新失败（不影响数据入库）：{e}")

# ========== 数据加载函数 ==========
@st.cache_data(ttl=300)
def load_daily_sales(suffix=None, apply_filter=True):
    if supabase is None:
        return pd.DataFrame()
    try:
        table_name = get_table_name("daily_sales", suffix)
        all_data = []
        page = 0
        page_size = 1000
        query_columns = "id, sale_date, shop_name, amount, cumulative_amount"
        while True:
            resp = supabase.table(table_name)\
                           .select(query_columns)\
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
            if apply_filter:
                df = apply_data_permission(df)
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载店铺业绩失败：{e}")
        return pd.DataFrame()

def save_daily_sales(records, suffix=None):
    if supabase is None or not records:
        return
    table_name = get_table_name("daily_sales", suffix)
    supabase.table(table_name).upsert(records, on_conflict="sale_date,shop_name").execute()

def rebuild_daily_data(suffix=None):
    df = load_daily_sales(suffix)
    if df.empty:
        st.session_state.df_all_daily = None
        st.session_state.daily_latest = None
        st.session_state.monthly_actual = None
        st.session_state.latest_date = None
        return
    df = df.rename(columns={"sale_date": "日期", "shop_name": "店铺名称",
                            "amount": "当日金额", "cumulative_amount": "月累计金额"})
    df_all = df.sort_values(["店铺名称", "日期"])
    latest_date = df_all["日期"].max()
    daily_latest = df_all.loc[df_all.groupby("店铺名称")["日期"].idxmax()].copy()
    monthly_actual = df_all.groupby("店铺名称")["当日金额"].sum().reset_index()
    monthly_actual["月累计金额"] = monthly_actual["当日金额"].round(2)
    monthly_actual = monthly_actual[["店铺名称", "月累计金额"]].sort_values("店铺名称")
    st.session_state.df_all_daily = df_all
    st.session_state.daily_latest = daily_latest
    st.session_state.monthly_actual = monthly_actual
    st.session_state.latest_date = latest_date

def rebuild_daily_from_product(suffix=None):
    if supabase is None:
        return False, "Supabase 未连接"
    try:
        with st.spinner("正在重建每日业绩，请稍候..."):
            product_table = get_table_name("product_sales", suffix)
            all_data = []
            page = 0
            page_size = 1000
            while True:
                resp = supabase.table(product_table).select("sale_date, shop_name, net_amount, remark").range(page*page_size, (page+1)*page_size-1).execute()
                if not resp.data:
                    break
                all_data.extend(resp.data)
                if len(resp.data) < page_size:
                    break
                page += 1
            if not all_data:
                daily_table = get_table_name("daily_sales", suffix)
                supabase.table(daily_table).delete().neq("id", 0).execute()
                return True, "商品销售表无数据，已清空每日业绩表"
            df = pd.DataFrame(all_data)
            df["sale_date"] = pd.to_datetime(df["sale_date"])
            if suffix == "_all":
                df["anchor"] = df["remark"].apply(extract_anchor)
                daily_agg = df.groupby(["sale_date", "anchor"])["net_amount"].sum().reset_index()
                daily_agg.columns = ["sale_date", "店铺名称", "amount"]
            else:
                daily_agg = df.groupby(["sale_date", "shop_name"])["net_amount"].sum().reset_index()
                daily_agg.columns = ["sale_date", "店铺名称", "amount"]
            daily_agg = daily_agg.sort_values(["店铺名称", "sale_date"])
            daily_agg["cumulative_amount"] = daily_agg.groupby("店铺名称")["amount"].cumsum().round(2)
            records = []
            for _, row in daily_agg.iterrows():
                records.append({
                    "sale_date": row["sale_date"].strftime("%Y-%m-%d"),
                    "shop_name": row["店铺名称"],
                    "amount": float(row["amount"]),
                    "cumulative_amount": float(row["cumulative_amount"])
                })
            if records:
                daily_table = get_table_name("daily_sales", suffix)
                supabase.table(daily_table).delete().neq("id", 0).execute()
                batch_size = 1000
                for i in range(0, len(records), batch_size):
                    batch = records[i:i+batch_size]
                    supabase.table(daily_table).insert(batch).execute()
        return True, f"成功重建每日业绩，共 {len(records)} 条记录"
    except Exception as e:
        return False, str(e)

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

# ========== 组织目标管理（仅全部数据） ==========
@st.cache_data(ttl=300)
def load_org_targets(suffix=None):
    """从 arg_targets 表加载组织目标"""
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
    """保存组织目标到 arg_targets 表"""
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

# ========== 商品相关函数 ==========
SEASON_MAP = {"1": "春", "2": "夏", "3": "秋", "4": "冬"}
SIZE_MAP = {"001": "S", "002": "M", "003": "L", "004": "XL", "008": "均码"}

def parse_product_code(remark):
    # 使用导入的 parse_product_code，这里不再定义，但为了兼容，调用导入的。
    # 直接使用 from core.utils import parse_product_code
    pass

def update_product_master_flag(style_code, flag_value):
    if supabase is None:
        return False, "Supabase 未连接"
    try:
        resp = supabase.table("product_master").update({"has_newbie_coupon": flag_value}).eq("style_code", style_code).execute()
        return True, "更新成功"
    except Exception as e:
        return False, str(e)

def save_product_sales(df_orders, suffix=None):
    if supabase is None:
        return
    master_df = load_product_master()
    master_map = {}
    if not master_df.empty:
        for _, row in master_df.iterrows():
            code = row["style_code"]
            master_map[code] = {
                "image_url": row.get("image_url", None),
                "master_category": row.get("category", None),
                "has_newbie_coupon": row.get("has_newbie_coupon", False)
            }
    temp_records = {}
    for _, row in df_orders.iterrows():
        remark = row["备注"]
        parsed = parse_product_code(remark)
        if parsed is None:
            continue
        amount = float(row["金额/时间"])
        short_code = parsed["style_code"]
        img = master_map.get(short_code, {}).get("image_url")
        cat = master_map.get(short_code, {}).get("master_category")
        if remark not in temp_records:
            temp_records[remark] = {
                "remark": remark,
                "sale_date": row["日期"].strftime("%Y-%m-%d"),
                "shop_name": row["店铺名称"],
                "product_code": parsed["product_code"],
                "style_code": short_code,
                "brand": parsed["brand"],
                "year": parsed["year"],
                "season": parsed["season"],
                "product_category": parsed["category"],
                "style": parsed["style"],
                "color_code": parsed["color_code"],
                "size_code": parsed["size"],
                "ship_amount": max(amount, 0),
                "return_amount": max(-amount, 0),
                "net_amount": amount,
                "image_url": img,
                "master_category": cat
            }
        else:
            existing = temp_records[remark]
            existing["ship_amount"] += max(amount, 0)
            existing["return_amount"] += max(-amount, 0)
            existing["net_amount"] += amount
    records = list(temp_records.values())
    if records:
        table_name = get_table_name("product_sales", suffix)
        batch_size = 500
        for i in range(0, len(records), batch_size):
            batch = records[i:i+batch_size]
            supabase.table(table_name).upsert(batch, on_conflict="remark").execute()

def save_offline_sales(df_orders):
    """专门处理线下收入数据，写入 offline_sales_all 表（含发货/退货拆分）"""
    if supabase is None or df_orders.empty:
        return

    df = df_orders.copy()
    df['sale_date'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')
    df['shop_name'] = df['组织名称'].astype(str).str.strip()
    df['amount'] = pd.to_numeric(df['金额/时间'], errors='coerce').fillna(0)
    
    df['ship_amount'] = df['amount'].clip(lower=0)
    df['return_amount'] = (-df['amount']).clip(lower=0)
    df['net_amount'] = df['amount']
    df['remark'] = df['备注'].astype(str).str.strip()

    records = df[['sale_date', 'shop_name', 'ship_amount', 'return_amount', 'net_amount', 'remark']].to_dict(orient='records')
    if not records:
        return

    table_name = "offline_sales_all"
    batch_size = 500
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        for attempt in range(3):
            try:
                supabase.table(table_name).insert(batch).execute()
                break
            except Exception as e:
                if attempt == 2:
                    raise e
                time.sleep(2 ** attempt)
    refresh_materialized_view("_all")

def refresh_materialized_view(suffix=""):
    """刷新对应的物化视图（异步）"""
    if supabase is None:
        return
    try:
        supabase.rpc('refresh_mv', {'suffix': suffix}).execute()
    except Exception as e:
        st.warning(f"物化视图刷新失败（不影响数据入库）：{e}")

# ========== 验证和上传处理 ==========
def validate_order_data(df):
    try:
        required = ["日期", "金额/时间", "备注"]
        missing_cols = [col for col in required if col not in df.columns]
        if missing_cols:
            return False, f"缺少必要列: {', '.join(missing_cols)}。", None
        df_valid = df.copy()
        df_valid["日期"] = pd.to_datetime(df_valid["日期"], errors='coerce')
        if df_valid["日期"].isnull().any():
            return False, "日期列包含无效日期，请检查格式（如 2026-06-01）。", None
        df_valid["店铺名称"] = df_valid["备注"].astype(str).str.split("_").str[-1]
        df_valid["店铺名称"] = df_valid["店铺名称"].str.replace(r'^商店[：:]', '', regex=True).str.strip()
        df_valid = df_valid[df_valid["店铺名称"].notna() & (df_valid["店铺名称"] != "")].copy()
        if df_valid.empty:
            return False, "未提取到有效的店铺名称，请检查备注格式。", None
        df_valid["金额/时间"] = pd.to_numeric(df_valid["金额/时间"], errors='coerce')
        if df_valid["金额/时间"].isnull().any():
            return False, "金额/时间列包含非数值内容，请检查。", None
        return True, "验证通过", df_valid
    except Exception as e:
        return False, f"验证过程发生异常: {str(e)}", None

def process_uploaded_file(uploaded_file, suffix):
    try:
        try:
            df = pd.read_excel(uploaded_file, header=1)
        except Exception as e:
            return False, f"文件读取失败：{str(e)}。"
        is_valid, err_msg, df_valid = validate_order_data(df)
        if not is_valid:
            return False, err_msg
        try:
            save_product_sales(df_valid, suffix)
        except Exception as e:
            if "duplicate key" in str(e).lower():
                return False, "数据重复：该文件中的订单备注与已存在数据冲突。"
            return False, f"保存商品销售明细失败：{str(e)}。"
        if suffix == "_all":
            df_valid["anchor"] = df_valid["备注"].apply(extract_anchor)
            new_daily = df_valid.groupby(["日期", "anchor"])["金额/时间"].sum().reset_index()
            new_daily.columns = ["日期", "店铺名称", "当日金额"]
        else:
            new_daily = df_valid.groupby(["日期", "店铺名称"])["金额/时间"].sum().reset_index()
            new_daily.columns = ["日期", "店铺名称", "当日金额"]
        new_daily["日期"] = pd.to_datetime(new_daily["日期"])
        existing = load_daily_sales(suffix)
        if not existing.empty:
            new_dates = new_daily["日期"].dt.date.unique()
            existing = existing[~existing["sale_date"].dt.date.isin(new_dates)]
            if not existing.empty:
                existing_df = existing[["sale_date", "shop_name", "amount"]].rename(
                    columns={"sale_date": "日期", "shop_name": "店铺名称", "amount": "当日金额"}
                )
                merged = pd.concat([existing_df, new_daily], ignore_index=True)
            else:
                merged = new_daily.copy()
        else:
            merged = new_daily.copy()
        merged = merged.sort_values(["店铺名称", "日期"])
        merged["当日金额"] = pd.to_numeric(merged["当日金额"], errors="coerce").fillna(0)
        merged["月累计金额"] = merged.groupby("店铺名称")["当日金额"].cumsum().round(2)
        records = []
        for _, row in merged.iterrows():
            records.append({
                "sale_date": row["日期"].strftime("%Y-%m-%d"),
                "shop_name": row["店铺名称"],
                "amount": float(row["当日金额"]),
                "cumulative_amount": float(row["月累计金额"])
            })
        save_daily_sales(records, suffix)
        if suffix == st.session_state.get("table_suffix", ""):
            rebuild_daily_data(suffix)
            st.session_state.target_dict = load_targets(suffix)
        latest_date = merged["日期"].max().strftime('%Y-%m-%d') if not merged.empty else "无数据"
        refresh_materialized_view(suffix)
        return True, f"处理完成！最新日期：{latest_date}"
    except Exception as e:
        return False, f"未预料的错误：{str(e)}"

def load_target_file(uploaded_file, suffix):
    try:
        df_target = pd.read_excel(uploaded_file, header=None)
        first_cell = str(df_target.iloc[0, 0]) if len(df_target) > 0 else ""
        if "月目标" in first_cell or "目标" in first_cell:
            df_target = df_target.iloc[1:].reset_index(drop=True)
        if df_target.shape[1] < 2:
            raise ValueError("需要两列：店铺名称、目标金额")
        shop_names = df_target.iloc[:, 0].astype(str).str.strip()
        target_vals = pd.to_numeric(df_target.iloc[:, 1], errors='coerce')
        target_dict = {}
        for name, val in zip(shop_names, target_vals):
            if pd.notna(val) and name not in ["", "nan", "None"]:
                target_dict[name] = val
        save_targets(target_dict, suffix)
        if suffix == st.session_state.get("table_suffix", ""):
            st.session_state.target_dict = target_dict
        return True, f"成功加载 {len(target_dict)} 个店铺目标"
    except Exception as e:
        return False, str(e)

def manage_newbie_coupon():
    st.subheader("🏷️ 单商品礼金标签管理")
    master_df = load_product_master()
    if master_df.empty:
        st.info("暂无商品数据")
        return
    if "has_newbie_coupon" not in master_df.columns:
        st.warning("数据库表中缺少 has_newbie_coupon 字段，请先执行 ALTER TABLE product_master ADD COLUMN has_newbie_coupon BOOLEAN DEFAULT FALSE;")
        return
    search = st.text_input("搜索货号", key="coupon_search")
    style_codes = master_df["style_code"].dropna().unique()
    if search:
        style_codes = [code for code in style_codes if search.upper() in code.upper()]
    selected_style = st.selectbox("选择商品货号", options=sorted(style_codes), key="coupon_style")
    current_flag = master_df[master_df["style_code"] == selected_style]["has_newbie_coupon"].values[0] if not master_df[master_df["style_code"] == selected_style].empty else False
    new_flag = st.checkbox("参与新人礼金", value=bool(current_flag), key="coupon_flag")
    if st.button("更新标签", key="coupon_update"):
        ok, msg = update_product_master_flag(selected_style, new_flag)
        if ok:
            st.success(msg)
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(msg)

def batch_manage_newbie_coupon():
    st.subheader("📦 批量礼金标签管理")
    master_df = load_product_master()
    if master_df.empty:
        st.warning("暂无商品数据")
        return
    if "has_newbie_coupon" not in master_df.columns:
        st.warning("数据库表中缺少 has_newbie_coupon 字段，请先执行 ALTER TABLE product_master ADD COLUMN has_newbie_coupon BOOLEAN DEFAULT FALSE;")
        return
    current_coupon_codes = master_df[master_df["has_newbie_coupon"] == True]["style_code"].tolist()
    st.info(f"当前共有 **{len(current_coupon_codes)}** 个商品参与新人礼金活动。")
    operation = st.radio("选择操作模式", ["批量新增", "批量删除", "整体替换"], horizontal=True, key="batch_op")
    input_method = st.radio("输入方式", ["文本框（每行一个货号）", "上传文件（每行一个货号）"], horizontal=True, key="input_method")
    style_codes_input = []
    if input_method == "文本框（每行一个货号）":
        text_area = st.text_area("请输入货号，每行一个", height=200, key="batch_codes_text")
        if text_area:
            style_codes_input = [line.strip().upper() for line in text_area.splitlines() if line.strip()]
    else:
        uploaded_file = st.file_uploader("上传文本文件（每行一个货号）", type=["txt", "csv"], key="batch_file")
        if uploaded_file is not None:
            content = uploaded_file.read().decode("utf-8")
            style_codes_input = [line.strip().upper() for line in content.splitlines() if line.strip()]
    if style_codes_input:
        st.write(f"共识别 **{len(style_codes_input)}** 个货号：")
        st.text(", ".join(style_codes_input[:20]) + ("..." if len(style_codes_input) > 20 else ""))
    if st.button("确认执行", key="batch_execute"):
        if not style_codes_input:
            st.error("请至少输入一个货号")
            return
        existing_codes = master_df["style_code"].tolist()
        invalid_codes = [code for code in style_codes_input if code not in existing_codes]
        if invalid_codes:
            st.warning(f"以下货号不存在于商品库中：{', '.join(invalid_codes[:10])}{'...' if len(invalid_codes) > 10 else ''}")
            if st.button("仍要执行（忽略不存在货号）", key="ignore_invalid"):
                valid_codes = [code for code in style_codes_input if code in existing_codes]
                if not valid_codes:
                    st.error("没有有效的货号")
                    return
                style_codes_input = valid_codes
            else:
                st.stop()
        with st.spinner("正在更新数据库，请稍候..."):
            try:
                if operation == "批量新增":
                    for code in style_codes_input:
                        update_product_master_flag(code, True)
                    st.success(f"成功为 {len(style_codes_input)} 个商品启用新人礼金标签")
                elif operation == "批量删除":
                    for code in style_codes_input:
                        update_product_master_flag(code, False)
                    st.success(f"成功为 {len(style_codes_input)} 个商品停用新人礼金标签")
                else:
                    all_codes = master_df["style_code"].tolist()
                    for code in all_codes:
                        update_product_master_flag(code, False)
                    for code in style_codes_input:
                        update_product_master_flag(code, True)
                    st.success(f"整体替换完成，现有 {len(style_codes_input)} 个商品启用新人礼金标签")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"操作失败：{e}")

# ========== 页面初始化 ==========
rebuild_daily_data(st.session_state.table_suffix)
if st.session_state.target_dict == {}:
    st.session_state.target_dict = load_targets(st.session_state.table_suffix)

with st.sidebar:
    
    st.header("📂 数据加载")
    st.subheader("🔄 数据源切换")
    suffix_names = {"": "非直播数据", "_all": "全部数据"}
    current_source_name = suffix_names.get(st.session_state.table_suffix, "未知")
    st.info(f"📌 当前正在查看：**{current_source_name}**")

    if st.session_state.role == "admin":
        available_suffixes = {"非直播数据": "", "全部数据": "_all"}
    else:
        user_info = st.session_state.sub_users.get(st.session_state.username, {})
        default_suffix = user_info.get("default_suffix", "")
        perms = user_info.get("permissions", {})
        available = {}
        for name, suf in [("非直播数据", ""), ("全部数据", "_all")]:
            if suf in perms and perms[suf]:
                available[name] = suf
        if not available:
            available = {"非直播数据": ""}
        available_suffixes = available

    options = list(available_suffixes.keys())
    if current_source_name in options:
        default_index = options.index(current_source_name)
    else:
        default_index = 0
    selected_source = st.selectbox("选择数据源", options=options, index=default_index, key="source_selectbox_sidebar")
    if st.button("✅ 确认切换", key="confirm_switch_sidebar"):
        new_suffix = available_suffixes[selected_source]
        if new_suffix != st.session_state.table_suffix:
            st.session_state.table_suffix = new_suffix
            st.cache_data.clear()
            st.rerun()
    st.markdown("---")

    if st.session_state.role == "admin":
        current_display_suffix = st.session_state.table_suffix
        def handle_upload(uploaded_file, suffix, file_type="order"):
            if st.session_state.processing_upload:
                st.warning("上一个文件正在处理中，请稍后...")
                return
            if uploaded_file is None:
                st.warning("请先选择文件")
                return
            file_content = uploaded_file.getvalue()
            file_hash = hashlib.md5(file_content).hexdigest()
            if file_type == "order" and st.session_state.get("uploaded_file_hash") == file_hash:
                st.info("该文件内容已上传过，无需重复处理")
                return
            st.session_state.processing_upload = True
            with st.spinner("正在处理文件，请稍候..."):
                file_bytes = io.BytesIO(file_content)
                if file_type == "order":
                    ok, msg = process_uploaded_file(file_bytes, suffix)
                else:
                    ok, msg = load_target_file(file_bytes, suffix)
            if ok:
                st.success(msg)
                if file_type == "order":
                    st.session_state.uploaded_file_hash = file_hash
                st.cache_data.clear()
                st.session_state.processing_upload = False
                time.sleep(0.3)
                st.rerun()
            else:
                st.error(msg)
                st.session_state.processing_upload = False

        if current_display_suffix == "":
            st.subheader("📁 非直播数据上传")
            uploaded_order = st.file_uploader("选择订单文件 (Excel)", type=["xlsx", "xls"], key="order_uploader_normal_final")
            if st.button("📤 确认上传", key="confirm_upload_normal_final"):
                handle_upload(uploaded_order, "", "order")
            target_file = st.file_uploader("选择目标文件 (Excel)", type=["xlsx", "xls"], key="target_upload_normal_final")
            if st.button("📤 确认上传目标", key="confirm_target_normal_final"):
                handle_upload(target_file, "", "target")
        elif current_display_suffix == "_live":
            st.subheader("🎥 直播数据上传")
            uploaded_order = st.file_uploader("选择订单文件 (Excel)", type=["xlsx", "xls"], key="order_uploader_live_final")
            if st.button("📤 确认上传", key="confirm_upload_live_final"):
                handle_upload(uploaded_order, "_live", "order")
            target_file = st.file_uploader("选择目标文件 (Excel)", type=["xlsx", "xls"], key="target_upload_live_final")
            if st.button("📤 确认上传目标", key="confirm_target_live_final"):
                handle_upload(target_file, "_live", "target")
        else:
            st.subheader("📊 全部数据上传")
            uploaded_order = st.file_uploader("选择订单文件 (Excel)", type=["xlsx", "xls"], key="order_uploader_all_final")
            if st.button("📤 确认上传", key="confirm_upload_all_final"):
                handle_upload(uploaded_order, "_all", "order")
            target_file = st.file_uploader("选择目标文件 (Excel)", type=["xlsx", "xls"], key="target_upload_all_final")
            if st.button("📤 确认上传目标", key="confirm_target_all_final"):
                handle_upload(target_file, "_all", "target")
            st.markdown("---")
            st.subheader("🏷️ 线下收入上传")
            uploaded_offline = st.file_uploader("选择线下收入文件 (Excel)", type=["xlsx", "xls"], key="offline_uploader")
            if uploaded_offline is not None:
                if st.button("📤 上传线下收入", key="upload_offline"):
                    try:
                        df = pd.read_excel(uploaded_offline, header=1)
                        required_cols = ["日期", "金额/时间", "备注", "组织名称"]
                        if not all(col in df.columns for col in required_cols):
                            st.error(f"文件必须包含列：{', '.join(required_cols)}")
                        else:
                            save_offline_sales(df)
                            st.success(f"✅ 成功上传 {len(df)} 条线下收入记录")
                            st.cache_data.clear()
                            time.sleep(0.5)
                            st.rerun()
                    except Exception as e:
                        st.error(f"上传失败：{e}")           
        st.markdown("---")
        st.header("⚙️ 工具")
        # ---- 组织目标上传（仅全部数据） ----
        if st.session_state.table_suffix == "_all":
            st.markdown("---")
            st.subheader("📊 组织目标管理")
            uploaded_org_target = st.file_uploader("上传组织目标文件 (Excel)", type=["xlsx", "xls"], key="org_target_upload")
            if uploaded_org_target is not None:
                if st.button("📤 上传组织目标", key="upload_org_target_btn"):
                    try:
                        df_target = pd.read_excel(uploaded_org_target, header=None)
                        # 第一列：组织名称，第二列：目标金额
                        org_names = df_target.iloc[:, 0].astype(str).str.strip()
                        target_vals = pd.to_numeric(df_target.iloc[:, 1], errors='coerce')
                        target_dict = {}
                        for name, val in zip(org_names, target_vals):
                            if pd.notna(val) and name not in ["", "nan", "None"]:
                                target_dict[name] = val
                        save_org_targets(target_dict, "_all")
                        st.success(f"成功加载 {len(target_dict)} 个组织目标")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"上传失败：{e}")
        
        template_df = pd.DataFrame({"店铺名称": ["示例店铺A", "示例店铺B"], "目标金额": [100000, 200000]})
        template_bytes = io.BytesIO()
        with pd.ExcelWriter(template_bytes, engine='openpyxl') as writer:
            template_df.to_excel(writer, index=False)
        st.download_button("📄 下载目标模板", data=template_bytes.getvalue(), file_name="目标模板.xlsx", key="download_template_final")
        if st.button("🗑️ 清除当前用户的目标记忆", key="clear_targets_final"):
            clear_targets(st.session_state.table_suffix)
        if st.button("🔄 强制刷新所有数据", key="force_refresh_final"):
            st.cache_data.clear()
            st.rerun()
        if st.button("🔁 重置为非直播数据", key="reset_to_normal_final"):
            st.session_state.table_suffix = ""
            st.cache_data.clear()
            st.rerun()
        if st.button("🔄 从商品明细重建每日业绩", key="rebuild_daily_final"):
            ok, msg = rebuild_daily_from_product(st.session_state.table_suffix)
            if ok:
                st.success(msg)
                rebuild_daily_data(st.session_state.table_suffix)
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(msg)
        st.markdown("---")
        with st.expander("🏷️ 单商品礼金标签管理"):
            manage_newbie_coupon()
        with st.expander("📦 批量礼金标签管理"):
            batch_manage_newbie_coupon()
    else:
        st.info("您只有查看权限，无法上传文件。如需上传，请联系管理员。")
    st.markdown("---")
    if st.button("🚪 退出登录", key="logout_final"):
        st.session_state.authenticated = False
        for key in ["username", "role", "table_suffix"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()
    st.markdown("---")
    st.subheader("📌 快捷跳转")
    st.page_link("product_page.py", label="📦 商品分析独立页", icon="📦")

# ========== 动态创建选项卡 ==========
base_tabs = [
    "📊 经营驾驶舱",
    "📋 每日明细",
    "📦 商品分析",
    "🎤 主播分析",
    "📈 销售分布与品牌"
]
admin_extra_tabs = ["📚 商品库导出", "⚙️ 系统设置"]

# ---------- 动态插入“组织与部门分析” Tab（仅 _all） ----------
if st.session_state.table_suffix == "_all":
    base_tabs_with_org = base_tabs.copy()
    try:
        pos = base_tabs_with_org.index("🎤 主播分析") + 1
    except ValueError:
        pos = len(base_tabs_with_org)
    base_tabs_with_org.insert(pos, "🏢 组织与部门分析")
else:
    base_tabs_with_org = base_tabs

if st.session_state.role == "admin":
    tab_labels = base_tabs_with_org + admin_extra_tabs
else:
    current_suffix = st.session_state.table_suffix
    user_info = st.session_state.sub_users.get(st.session_state.username, {})
    perms = user_info.get("permissions", {})
    allowed = perms.get(current_suffix, [])
    if not allowed and "" in perms:
        allowed = perms[""]
    if not allowed:
        allowed = base_tabs_with_org
    valid_tabs = [tab for tab in allowed if tab in base_tabs_with_org]
    tab_labels = valid_tabs if valid_tabs else base_tabs_with_org

tabs = st.tabs(tab_labels, key="main_tabs")

def get_tab_index(label):
    return tab_labels.index(label) if label in tab_labels else None

idx_dashboard = get_tab_index("📊 经营驾驶舱")
idx_daily = get_tab_index("📋 每日明细")
idx_product = get_tab_index("📦 商品分析")
idx_anchor = get_tab_index("🎤 主播分析")
idx_distribution = get_tab_index("📈 销售分布与品牌")
idx_org = get_tab_index("🏢 组织与部门分析")
idx_export = get_tab_index("📚 商品库导出")
idx_system = get_tab_index("⚙️ 系统设置")

# 兼容旧变量（已删除模块置为 None）
idx_anchor_compare = idx_anchor
idx_ship_return = None
idx_history = None

# ========== 经营驾驶舱 ==========
if idx_dashboard is not None:
    with tabs[idx_dashboard]:
        st.markdown("""
        <style>
        .stApp {
            background: #f5f7fa;
        }
        .main > div {
            background: transparent;
        }
        .glass-card {
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(245, 247, 250, 0.9));
            border-radius: 16px;
            padding: 22px 24px;
            border: 1px solid rgba(0, 0, 0, 0.06);
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            margin-bottom: 8px;
        }
        .glass-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 48px rgba(0, 0, 0, 0.12);
        }
        .kpi-number {
            font-size: 38px;
            font-weight: 700;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #0f172a 60%, #475569);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .kpi-label {
            color: #475569;
            font-size: 13px;
            font-weight: 500;
            letter-spacing: 0.3px;
            text-transform: uppercase;
        }
        .change-up { color: #16a34a; font-weight: 600; }
        .change-down { color: #dc2626; font-weight: 600; }
        .change-neutral { color: #64748b; }
        .progress-track {
            width: 100%;
            height: 6px;
            background: #e2e8f0;
            border-radius: 3px;
            overflow: hidden;
            margin: 8px 0 4px 0;
        }
        .progress-fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.8s ease;
        }
        .rank-item {
            display: flex;
            align-items: center;
            padding: 6px 0;
            border-bottom: 1px solid rgba(0,0,0,0.05);
        }
        .rank-item:last-child {
            border-bottom: none;
        }
        .rank-emoji { font-size: 22px; width: 36px; }
        .rank-name { flex: 1; color: #1e293b; font-size: 14px; }
        .rank-value { color: #16a34a; font-weight: 600; font-size: 14px; width: 80px; text-align: right; }
        .rank-bar-bg { width: 100px; height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; }
        .rank-bar-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, #22c55e, #14b8a6); }
        .alert-item {
            padding: 10px 14px;
            border-radius: 8px;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(0,0,0,0.02);
            border-left: 3px solid;
        }
        .alert-item .icon { font-size: 16px; }
        .alert-item .msg { color: #1e293b; font-size: 14px; }
        .section-title {
            color: #1e293b;
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 12px;
            letter-spacing: 0.2px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .section-title .badge {
            background: rgba(34, 197, 94, 0.15);
            color: #16a34a;
            font-size: 11px;
            padding: 2px 10px;
            border-radius: 12px;
            font-weight: 500;
        }
        .stMarkdown, .stText, .stCaption, .stInfo, .stWarning, .stSuccess {
            color: #1e293b !important;
        }
        </style>
        """, unsafe_allow_html=True)

        # ---------- 加载数据 ----------
        with st.spinner("加载数据..."):
            prod_df = load_product_sales(st.session_state.table_suffix)
        
        if prod_df.empty:
            st.info("📌 暂无商品销售数据，请先上传订单文件。")
            st.stop()

        # ---------- 部门筛选 ----------
        has_dept = 'dept' in prod_df.columns and prod_df['dept'].notna().any()
        if has_dept:
            depts = sorted(prod_df['dept'].dropna().unique())
            depts = ['全部'] + depts
            selected_dept = st.selectbox("🏢 选择部门", depts, key="dashboard_dept_select")
            if selected_dept != '全部':
                prod_df = prod_df[prod_df['dept'] == selected_dept]
                if prod_df.empty:
                    st.warning(f"当前部门「{selected_dept}」无销售数据，请切换其他部门。")
                    st.stop()
        else:
            selected_dept = '全部'
            st.caption("当前数据源无部门维度，显示全部数据。")

        # ---------- 按日期汇总净销售额 ----------
        daily_sales = prod_df.groupby(prod_df["sale_date"].dt.date)["net_amount"].sum().reset_index()
        daily_sales.columns = ["日期", "amount"]
        daily_sales = daily_sales.sort_values("日期")

        if daily_sales.empty:
            st.info("📌 当前筛选条件无销售数据。")
            st.stop()

        latest_date = daily_sales["日期"].max()
        st.caption(f"📅 数据更新至：{latest_date.strftime('%Y年%m月%d日')}" + (f" | 部门：{selected_dept}" if selected_dept != '全部' else ""))

        # ---------- 计算指标 ----------
        prev_date = latest_date - timedelta(days=1)

        mask_latest = daily_sales["日期"] == latest_date
        latest_sales = daily_sales.loc[mask_latest, "amount"].sum() if not daily_sales.loc[mask_latest].empty else 0

        mask_prev = daily_sales["日期"] == prev_date
        prev_sales = daily_sales.loc[mask_prev, "amount"].sum() if not daily_sales.loc[mask_prev].empty else 0

        if prev_sales != 0:
            change = ((latest_sales - prev_sales) / prev_sales) * 100
        else:
            change = 0

        month_start = latest_date.replace(day=1)
        month_mask = daily_sales["日期"] >= month_start
        month_sales = daily_sales.loc[month_mask, "amount"].sum()

        # ========== 关键修正：定义 target_dict ==========
        target_dict = st.session_state.target_dict  # 获取全局店铺目标

        if target_dict and has_dept and selected_dept != '全部':
            dept_shops = prod_df['shop_name'].unique()
            dept_target = sum([target_dict.get(shop, 0) for shop in dept_shops])
        else:
            dept_target = sum(target_dict.values())

        target_rate = (month_sales / dept_target * 100) if dept_target > 0 else 0

        latest_prod = prod_df[prod_df["sale_date"].dt.date == latest_date]
        ship_latest = latest_prod["ship_amount"].sum()
        return_latest = latest_prod["return_amount"].sum()
        return_rate = (return_latest / ship_latest * 100) if ship_latest > 0 else 0

        health_score = 70
        if target_rate > 80:
            health_score += 15
        elif target_rate > 50:
            health_score += 5
        if return_rate < 5:
            health_score += 10
        elif return_rate < 10:
            health_score += 5
        if latest_sales > prev_sales:
            health_score += 5
        health_score = min(100, health_score)

        # ---------- KPI 卡片 ----------
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            if prev_sales < 0:
                abs_increase = latest_sales - prev_sales
                change_text = f"▲ 由负转正 (+{abs_increase:,.0f})"
                change_class = "change-up"
            elif prev_sales == 0:
                change_text = "无前日数据"
                change_class = "change-neutral"
            else:
                change_text = f"{'▲' if change >= 0 else '▼'} {abs(change):.1f}%" if change != 0 else "持平"
                change_class = "change-up" if change >= 0 else "change-down"
        
            st.markdown(f"""
            <div class="glass-card">
                <div class="kpi-label">昨日销售</div>
                <div class="kpi-number">¥{latest_sales:,.0f}</div>
                <!-- 月累计销售额 -->
                <div style="font-size:16px; color:#475569; margin-top:4px;">月累计 ¥{month_sales:,.0f}</div>
                <div style="margin-top:6px;">
                    <span class="{change_class}">{change_text}</span>
                    <span style="color:#64748b;font-size:13px;margin-left:8px;">前日 ¥{prev_sales:,.0f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            bar_color = "#4ade80" if target_rate >= 80 else "#fbbf24" if target_rate >= 50 else "#f87171"
            st.markdown(f"""
            <div class="glass-card">
                <div class="kpi-label">月目标完成率</div>
                <div style="font-size:38px;font-weight:700;color:#0f172a;letter-spacing:-0.5px;">{target_rate:.0f}%</div>
                <div class="progress-track">
                    <div class="progress-fill" style="width:{min(target_rate,100)}%;background:{bar_color};"></div>
                </div>
                <div style="color:#475569;font-size:12px;">¥{month_sales:,.0f} / ¥{dept_target:,.0f}</div>
            </div>
            """, unsafe_allow_html=True)

        with col3:
            return_color = "#f87171" if return_rate > 10 else "#fbbf24" if return_rate > 5 else "#4ade80"
            status_text = "正常" if return_rate < 5 else "偏高" if return_rate < 10 else "异常"
            st.markdown(f"""
            <div class="glass-card">
                <div class="kpi-label">退货率</div>
                <div style="font-size:38px;font-weight:700;color:#0f172a;letter-spacing:-0.5px;">{return_rate:.1f}%</div>
                <div style="margin-top:4px;">
                    <span style="color:{return_color};font-weight:500;">● {status_text}</span>
                    <span style="color:#64748b;font-size:13px;margin-left:8px;">退货 ¥{return_latest:,.0f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with col4:
            health_color = "#4ade80" if health_score >= 80 else "#fbbf24" if health_score >= 60 else "#f87171"
            health_text = "良好" if health_score >= 80 else "一般" if health_score >= 60 else "需关注"
            st.markdown(f"""
            <div class="glass-card">
                <div class="kpi-label">经营健康度</div>
                <div style="font-size:38px;font-weight:700;color:#0f172a;letter-spacing:-0.5px;">{health_score}分</div>
                <div class="progress-track">
                    <div class="progress-fill" style="width:{health_score}%;background:{health_color};"></div>
                </div>
                <div style="color:{health_color};font-size:13px;font-weight:500;">● {health_text}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        # ---------- 异常提醒 ----------
        st.markdown('<div class="section-title">⚠️ 异常提醒 <span class="badge">需关注</span></div>', unsafe_allow_html=True)

        alerts = []
        end_date = latest_date - timedelta(days=1)
        start_date_recent = end_date - timedelta(days=6)
        start_date_previous = start_date_recent - timedelta(days=7)

        shop_daily = prod_df.groupby([prod_df["sale_date"].dt.date, "shop_name"])["net_amount"].sum().reset_index()
        shop_daily.columns = ["日期", "shop_name", "amount"]

        mask_recent = (shop_daily["日期"] >= start_date_recent) & (shop_daily["日期"] <= end_date)
        mask_previous = (shop_daily["日期"] >= start_date_previous) & (shop_daily["日期"] <= start_date_recent - timedelta(days=1))

        recent_data = shop_daily[mask_recent].copy()
        previous_data = shop_daily[mask_previous].copy()

        if not recent_data.empty and not previous_data.empty:
            recent_agg = recent_data.groupby("shop_name")["amount"].sum().reset_index().rename(columns={"amount": "近7天"})
            previous_agg = previous_data.groupby("shop_name")["amount"].sum().reset_index().rename(columns={"amount": "前7天"})
            merged = pd.merge(recent_agg, previous_agg, on="shop_name", how="inner")
            merged["下滑"] = ((merged["前7天"] - merged["近7天"]) / merged["前7天"] * 100) if not merged.empty else 0
            merged = merged[(merged["前7天"] > 0) & (merged["近7天"] < merged["前7天"])]
            merged = merged[merged["下滑"] >= 20].sort_values("下滑", ascending=False)

            for _, row in merged.head(3).iterrows():
                alerts.append(("#f87171" if row["下滑"] > 40 else "#fbbf24", f"📉 {row['shop_name']} 近7天销售下降 {row['下滑']:.0f}%"))

        prod_recent = prod_df[(prod_df["sale_date"] >= pd.to_datetime(start_date_recent)) & (prod_df["sale_date"] <= pd.to_datetime(end_date))]
        prod_previous = prod_df[(prod_df["sale_date"] >= pd.to_datetime(start_date_previous)) & (prod_df["sale_date"] <= pd.to_datetime(start_date_recent - timedelta(days=1)))]

        if not prod_recent.empty and not prod_previous.empty:
            recent_prod = prod_recent.groupby("style_code").agg(ship=("ship_amount", "sum"), ret=("return_amount", "sum")).reset_index()
            prev_prod = prod_previous.groupby("style_code").agg(ship=("ship_amount", "sum"), ret=("return_amount", "sum")).reset_index()
            merged_prod = pd.merge(recent_prod, prev_prod, on="style_code", suffixes=("_近", "_前"))
            merged_prod["退货率近"] = (merged_prod["ret_近"] / merged_prod["ship_近"] * 100).fillna(0)
            merged_prod["退货率前"] = (merged_prod["ret_前"] / merged_prod["ship_前"] * 100).fillna(0)
            mask_valid = (merged_prod["ship_前"] > 0) & (merged_prod["ship_近"] > 0)
            merged_prod["变化"] = 0.0
            merged_prod.loc[mask_valid, "变化"] = merged_prod.loc[mask_valid, "退货率近"] - merged_prod.loc[mask_valid, "退货率前"]
            merged_prod = merged_prod[(merged_prod["变化"] >= 10) & np.isfinite(merged_prod["变化"])].sort_values("变化", ascending=False)

            for _, row in merged_prod.head(3).iterrows():
                alerts.append(("#f87171" if row["变化"] > 20 else "#fbbf24", f"📦 {row['style_code']} 退货率上升 {row['变化']:.1f} 个百分点"))

        if target_dict and has_dept and selected_dept != '全部':
            dept_shop_names = prod_df['shop_name'].unique()
            for shop in dept_shop_names:
                target = target_dict.get(shop, 0)
                if target > 0:
                    shop_sales = shop_daily[(shop_daily["日期"] >= month_start) & (shop_daily["shop_name"] == shop)]["amount"].sum()
                    if shop_sales / target < 0.3:
                        alerts.append(("#f87171", f"🎯 {shop} 月目标完成率不足30%"))
        elif target_dict and (not has_dept or selected_dept == '全部'):
            for shop, target in target_dict.items():
                shop_sales = shop_daily[(shop_daily["日期"] >= month_start) & (shop_daily["shop_name"] == shop)]["amount"].sum()
                if target > 0 and shop_sales / target < 0.3:
                    alerts.append(("#f87171", f"🎯 {shop} 月目标完成率不足30%"))

        if alerts:
            alert_html = '<div style="background:rgba(255,255,255,0.03);border-radius:12px;padding:12px 16px;">'
            for color, msg in alerts[:5]:
                alert_html += f'<div class="alert-item" style="border-left-color:{color};">'
                alert_html += f'<span class="msg">{msg}</span></div>'
            if len(alerts) > 5:
                alert_html += f'<div style="color:#64748b;font-size:13px;padding:4px 0;">还有 {len(alerts)-5} 条异常，请查看「异常预警」</div>'
            alert_html += '</div>'
            st.markdown(alert_html, unsafe_allow_html=True)
        else:
            st.success("🎉 昨日一切正常，无异常项")

        st.markdown("---")

        # ---------- 双列布局 ----------
        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.markdown('<div class="section-title">🏆 店铺排行</div>', unsafe_allow_html=True)
            shop_latest = prod_df[prod_df["sale_date"].dt.date == latest_date].groupby("shop_name")["net_amount"].sum().sort_values(ascending=False).head(5)

            if not shop_latest.empty:
                max_val = shop_latest.iloc[0]
                rank_html = ""
                for i, (shop, amt) in enumerate(shop_latest.items()):
                    emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i]
                    pct = (amt / max_val * 100) if max_val > 0 else 0
                    rank_html += f"""
                    <div class="rank-item">
                        <div class="rank-emoji">{emoji}</div>
                        <div class="rank-name">{shop}</div>
                        <div class="rank-value">¥{amt/10000:.1f}万</div>
                        <div class="rank-bar-bg">
                            <div class="rank-bar-fill" style="width:{pct}%;"></div>
                        </div>
                    </div>
                    """
                st.markdown(rank_html, unsafe_allow_html=True)
            else:
                st.info("暂无数据")

            st.markdown('<div class="section-title" style="margin-top:16px;">📊 退货排行</div>', unsafe_allow_html=True)
            prod_latest = prod_df[prod_df["sale_date"].dt.date == latest_date]
            if not prod_latest.empty:
                return_rank = prod_latest.groupby("shop_name").agg(
                    发货=("ship_amount", "sum"),
                    退货=("return_amount", "sum")
                ).reset_index()
                return_rank = return_rank[return_rank["发货"] > 0]
                return_rank["退货率"] = (return_rank["退货"] / return_rank["发货"] * 100).round(1)
                return_rank = return_rank.sort_values("退货率", ascending=False).head(3)

                if not return_rank.empty:
                    for _, row in return_rank.iterrows():
                        shop = row["shop_name"]
                        rate = row["退货率"]
                        if abs(rate) < 0.05:
                            rate = 0.0
                        color = "#f87171" if rate > 10 else "#fbbf24" if rate > 5 else "#4ade80"
                        st.markdown(f"""
                        <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(0,0,0,0.06);">
                            <span style="color:#1e293b;">{shop}</span>
                            <span style="color:{color};font-weight:600;">{rate:.1f}%</span>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("暂无数据")
            else:
                st.info("暂无数据")

        with col_right:
            st.markdown('<div class="section-title">📈 近7日销售趋势</div>', unsafe_allow_html=True)
            last_7 = daily_sales[daily_sales["日期"] >= (latest_date - timedelta(days=6))]
            trend = last_7.sort_values("日期").copy()
            trend["日期"] = pd.to_datetime(trend["日期"])

            if not trend.empty:
                fig = px.line(
                    trend,
                    x="日期",
                    y="amount",
                    title="",
                    labels={"日期": "", "amount": ""},
                    markers=True,
                    template="plotly_white"
                )
                fig.update_layout(
                    height=240,
                    margin=dict(l=0, r=0, t=10, b=0),
                    hovermode="x unified",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#1e293b", size=11),
                )
                fig.update_traces(
                    line=dict(color="#22c55e", width=2.5),
                    marker=dict(color="#22c55e", size=6)
                )
                st.plotly_chart(fig, use_container_width=True)

                trend["日期_str"] = trend["日期"].dt.strftime("%m-%d")
                trend["销售"] = trend["amount"].apply(lambda x: f"¥{x:,.0f}")
                st.dataframe(trend[["日期_str", "销售"]], hide_index=True, use_container_width=True)
            else:
                st.info("近7日无数据")

        st.markdown("---")

        # ---------- AI 智能总结 ----------
        st.markdown('<div class="section-title">🤖 智能总结</div>', unsafe_allow_html=True)

        model_options = {
            "DeepSeek-V3": "deepseek-ai/DeepSeek-V3",
            "DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
            "Qwen2.5-72B": "Qwen/Qwen2.5-72B-Instruct",
            "Qwen2.5-7B": "Qwen/Qwen2.5-7B-Instruct",
            "GLM-4-9B": "glm-4-9b-chat"
        }
        selected_model_name = st.selectbox(
            "选择 AI 模型",
            options=list(model_options.keys()),
            index=1,
            key="ai_model_select"
        )
        selected_model = model_options[selected_model_name]

        if st.button("🚀 生成智能总结", key="generate_ai_summary"):
            shop_rank_items = list(shop_latest.items()) if not shop_latest.empty else []
            rank_text = "\n".join([f"{i+1}. {shop}: ¥{amt:,.0f}" for i, (shop, amt) in enumerate(shop_rank_items[:3])]) if shop_rank_items else "暂无"

            context = f"""
            部门：{selected_dept if selected_dept != '全部' else '全部'}
            昨日销售：¥{latest_sales:,.0f}
            月累计：¥{month_sales:,.0f}
            前日销售：¥{prev_sales:,.0f}
            环比变化：{change:+.1f}%
            月目标完成率：{target_rate:.0f}%
            退货率：{return_rate:.1f}%
            店铺排行 TOP3：{rank_text}
            异常提醒数：{len(alerts)}条
            """

            prompt = """
            你是一位资深的电商数据分析师。请根据提供的经营数据，用一段专业、简洁的中文总结昨日的经营状况。
            要求：
            1. 指出亮点（如增长明显的店铺或指标）。
            2. 发现风险（如下滑、高退货率等）。
            3. 给出1-2条可操作的建议。
            """

            with st.spinner("🤖 AI 正在分析，请稍候..."):
                ai_summary = get_ai_summary(prompt, context, selected_model)

            st.session_state.ai_summary_result = ai_summary
            st.rerun()

        if "ai_summary_result" in st.session_state and st.session_state.ai_summary_result:
            st.markdown(f"""
            <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);border-radius:12px;padding:16px 20px;margin-top:10px;">
                <div style="color:#1e293b;font-size:14px;line-height:1.7;">{st.session_state.ai_summary_result}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("点击上方按钮生成 AI 智能总结。")

# ========== 每日明细（合并“最新日明细”和“日期查询”） ==========
if idx_daily is not None:
    with tabs[idx_daily]:
        st.subheader("📋 每日明细查询")
        st.info("此处展示最新日销售明细，并支持按日期查询任意一天的销售情况。")

        # ---------- 加载商品数据 ----------
        with st.spinner("加载数据..."):
            prod_df = load_product_sales(st.session_state.table_suffix, apply_filter=False)
        if prod_df.empty:
            st.warning("暂无商品销售数据，请先上传订单文件。")
        else:
            # ---------- 确定维度 ----------
            is_all = st.session_state.table_suffix == "_all"
            if is_all:
                org_targets = load_org_targets("_all")
                dimension_options = ["阿米巴组织", "部门"]
                selected_dim = st.radio("选择维度", dimension_options, horizontal=True, key="dimension_select_daily")
                if selected_dim == "阿米巴组织":
                    group_col = "org_name"
                    dim_label = "组织"
                    target_dict = org_targets
                else:
                    group_col = "dept"
                    dim_label = "部门"
                    org_dept_map = prod_df[['org_name', 'dept']].drop_duplicates()
                    dept_targets = {}
                    for _, row in org_dept_map.iterrows():
                        org = row['org_name']
                        dept = row['dept']
                        target = org_targets.get(org, 0)
                        dept_targets[dept] = dept_targets.get(dept, 0) + target
                    target_dict = dept_targets
                if group_col not in prod_df.columns or prod_df[group_col].isna().all():
                    st.warning("当前数据中无组织/部门信息，请检查映射表。")
                    st.stop()
            else:
                group_col = "shop_name"
                dim_label = "店铺名称"
                target_dict = st.session_state.target_dict

            # ---------- 聚合辅助函数 ----------
            def aggregate_dim(df, group_col, dim_label):
                agg = df.groupby(group_col).agg(
                    发货金额=("ship_amount", "sum"),
                    退货金额=("return_amount", "sum"),
                    净销售金额=("net_amount", "sum")
                ).reset_index().rename(columns={group_col: dim_label})
                return agg

            # ---------- 第一部分：最新日明细 ----------
            st.markdown("#### 📅 最新日明细")
            source_names = {"": "非直播数据", "_all": "全部数据"}
            current_source = source_names.get(st.session_state.table_suffix, "未知")
            st.caption(f"当前数据源：**{current_source}**")

            latest_date = prod_df["sale_date"].max().date()
            month_start = latest_date.replace(day=1)

            # 当日数据
            mask_today = prod_df["sale_date"].dt.date == latest_date
            today_data = prod_df[mask_today]
            today_agg = aggregate_dim(today_data, group_col, dim_label)

            # 月累计数据
            mask_month = (prod_df["sale_date"].dt.date >= month_start) & (prod_df["sale_date"].dt.date <= latest_date)
            month_data = prod_df[mask_month]
            month_agg = aggregate_dim(month_data, group_col, dim_label)

            # 合并
            df_latest = pd.merge(today_agg, month_agg, on=dim_label, suffixes=("_日", "_月"), how="outer").fillna(0)

            # 计算退货率（数值）
            df_latest["日退货率_数值"] = df_latest.apply(
                lambda r: (r['退货金额_日'] / r['发货金额_日'] * 100) if r['发货金额_日'] != 0 else 0.0, axis=1
            )
            df_latest["月累计退货率_数值"] = df_latest.apply(
                lambda r: (r['退货金额_月'] / r['发货金额_月'] * 100) if r['发货金额_月'] != 0 else 0.0, axis=1
            )

            # 添加目标
            df_latest["目标金额"] = df_latest[dim_label].map(target_dict).fillna(0)
            # 达成率数值 = 月累计净额 / 目标 * 100
            df_latest["达成率_数值"] = df_latest.apply(
                lambda r: (r['净销售金额_月'] / r['目标金额'] * 100) if r['目标金额'] != 0 else 0.0, axis=1
            )

            # 排序（按维度名称）
            df_latest = df_latest.sort_values(dim_label)

            if not df_latest.empty:
                # 显示表格
                display_cols = [
                    dim_label,
                    "发货金额_日", "退货金额_日", "净销售金额_日", "日退货率_数值",
                    "发货金额_月", "退货金额_月", "净销售金额_月", "月累计退货率_数值",
                    "目标金额", "达成率_数值"
                ]
                # 重命名列（用于显示）
                rename_map = {
                    dim_label: dim_label,
                    "发货金额_日": "日发货",
                    "退货金额_日": "日退货",
                    "净销售金额_日": "日净额",
                    "日退货率_数值": "日退货率",
                    "发货金额_月": "月累计发货",
                    "退货金额_月": "月累计退货",
                    "净销售金额_月": "月累计净额",
                    "月累计退货率_数值": "月累计退货率",
                    "目标金额": "目标金额",
                    "达成率_数值": "达成率"
                }
                display_df = df_latest[display_cols].rename(columns=rename_map)

                # 使用 column_config 将百分比列格式化为百分数，并保留两位小数
                column_config = {
                    dim_label: st.column_config.TextColumn(dim_label),
                    "日发货": st.column_config.NumberColumn("日发货", format="%.2f"),
                    "日退货": st.column_config.NumberColumn("日退货", format="%.2f"),
                    "日净额": st.column_config.NumberColumn("日净额", format="%.2f"),
                    "日退货率": st.column_config.NumberColumn("日退货率", format="%.2f%%"),
                    "月累计发货": st.column_config.NumberColumn("月累计发货", format="%.2f"),
                    "月累计退货": st.column_config.NumberColumn("月累计退货", format="%.2f"),
                    "月累计净额": st.column_config.NumberColumn("月累计净额", format="%.2f"),
                    "月累计退货率": st.column_config.NumberColumn("月累计退货率", format="%.2f%%"),
                    "目标金额": st.column_config.NumberColumn("目标金额", format="%.2f"),
                    "达成率": st.column_config.NumberColumn("达成率", format="%.2f%%")
                }
                st.dataframe(display_df, column_config=column_config, use_container_width=True, hide_index=True)

                # 汇总行
                total_today_ship = df_latest["发货金额_日"].sum()
                total_today_return = df_latest["退货金额_日"].sum()
                total_today_net = df_latest["净销售金额_日"].sum()
                total_month_ship = df_latest["发货金额_月"].sum()
                total_month_return = df_latest["退货金额_月"].sum()
                total_month_net = df_latest["净销售金额_月"].sum()
                total_target = df_latest["目标金额"].sum()
                total_return_rate = (total_month_return / total_month_ship * 100) if total_month_ship != 0 else 0.0
                total_rate = (total_month_net / total_target * 100) if total_target != 0 else 0.0

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("📊 当日合计", f"净额: ¥{total_today_net:,.2f}", delta=f"发货 ¥{total_today_ship:,.2f} / 退货 ¥{total_today_return:,.2f}")
                with col2:
                    st.metric("📆 月累计合计", f"净额: ¥{total_month_net:,.2f}", delta=f"发货 ¥{total_month_ship:,.2f} / 退货 ¥{total_month_return:,.2f} | 退货率 {total_return_rate:.2f}%")
                with col3:
                    st.metric("🎯 目标完成率", f"{total_rate:.2f}%", delta=f"总目标: ¥{total_target:,.2f}")

                # 导出
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    # 导出时显示为字符串百分比（便于阅读）
                    export_df = display_df.copy()
                    # 将数值百分比转换为字符串，添加 "%"
                    for col in ['日退货率', '月累计退货率', '达成率']:
                        if col in export_df.columns:
                            export_df[col] = export_df[col].apply(lambda x: f"{x:.2f}%")
                    export_df.to_excel(writer, index=False)
                st.download_button(
                    "💾 导出最新日明细",
                    data=output.getvalue(),
                    file_name=f"最新日明细_{latest_date}.xlsx",
                    key="export_latest_detail_dim"
                )
            else:
                st.info("无数据")

            st.markdown("---")

            # ---------- 第二部分：日期查询 ----------
            st.markdown("#### 🔍 日期查询")
            if st.button("📅 今日", key="query_today_daily"):
                st.session_state["query_date_daily"] = date.today()
                st.rerun()
            query_date = st.date_input(
                "查询日期",
                value=st.session_state.get("query_date_daily", date.today()),
                key="query_date_daily"
            )
            if st.button("查询", key="query_btn_daily"):
                mask_query = prod_df["sale_date"].dt.date == query_date
                query_data = prod_df[mask_query]
                if query_data.empty:
                    st.warning("该日期无数据")
                else:
                    query_agg = aggregate_dim(query_data, group_col, dim_label)
                    month_start_q = query_date.replace(day=1)
                    mask_month_q = (prod_df["sale_date"].dt.date >= month_start_q) & (prod_df["sale_date"].dt.date <= query_date)
                    month_data_q = prod_df[mask_month_q]
                    month_agg_q = aggregate_dim(month_data_q, group_col, dim_label)

                    df_query = pd.merge(query_agg, month_agg_q, on=dim_label, suffixes=("_日", "_月"), how="outer").fillna(0)
                    df_query["日退货率_数值"] = df_query.apply(
                        lambda r: (r['退货金额_日'] / r['发货金额_日'] * 100) if r['发货金额_日'] != 0 else 0.0, axis=1
                    )
                    df_query["月累计退货率_数值"] = df_query.apply(
                        lambda r: (r['退货金额_月'] / r['发货金额_月'] * 100) if r['发货金额_月'] != 0 else 0.0, axis=1
                    )
                    df_query = df_query.sort_values(dim_label)

                    display_cols_q = [
                        dim_label,
                        "发货金额_日", "退货金额_日", "净销售金额_日", "日退货率_数值",
                        "发货金额_月", "退货金额_月", "净销售金额_月", "月累计退货率_数值"
                    ]
                    rename_map_q = {
                        dim_label: dim_label,
                        "发货金额_日": "当日发货",
                        "退货金额_日": "当日退货",
                        "净销售金额_日": "当日净额",
                        "日退货率_数值": "日退货率",
                        "发货金额_月": "月累计发货",
                        "退货金额_月": "月累计退货",
                        "净销售金额_月": "月累计净额",
                        "月累计退货率_数值": "月累计退货率"
                    }
                    display_q = df_query[display_cols_q].rename(columns=rename_map_q)

                    column_config_q = {
                        dim_label: st.column_config.TextColumn(dim_label),
                        "当日发货": st.column_config.NumberColumn("当日发货", format="%.2f"),
                        "当日退货": st.column_config.NumberColumn("当日退货", format="%.2f"),
                        "当日净额": st.column_config.NumberColumn("当日净额", format="%.2f"),
                        "日退货率": st.column_config.NumberColumn("日退货率", format="%.2f%%"),
                        "月累计发货": st.column_config.NumberColumn("月累计发货", format="%.2f"),
                        "月累计退货": st.column_config.NumberColumn("月累计退货", format="%.2f"),
                        "月累计净额": st.column_config.NumberColumn("月累计净额", format="%.2f"),
                        "月累计退货率": st.column_config.NumberColumn("月累计退货率", format="%.2f%%")
                    }
                    st.dataframe(display_q, column_config=column_config_q, use_container_width=True, hide_index=True)

                    total_q_ship = df_query["发货金额_日"].sum()
                    total_q_return = df_query["退货金额_日"].sum()
                    total_q_net = df_query["净销售金额_日"].sum()
                    total_q_month_ship = df_query["发货金额_月"].sum()
                    total_q_month_return = df_query["退货金额_月"].sum()
                    total_q_month_net = df_query["净销售金额_月"].sum()
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("📊 当日合计", f"净额: ¥{total_q_net:,.2f}", delta=f"发货 ¥{total_q_ship:,.2f} / 退货 ¥{total_q_return:,.2f}")
                    with col2:
                        st.metric("📆 截止当日月累计", f"净额: ¥{total_q_month_net:,.2f}", delta=f"发货 ¥{total_q_month_ship:,.2f} / 退货 ¥{total_q_month_return:,.2f}")

                    # 导出
                    output_q = io.BytesIO()
                    with pd.ExcelWriter(output_q, engine='openpyxl') as writer:
                        export_q = display_q.copy()
                        for col in ['日退货率', '月累计退货率']:
                            if col in export_q.columns:
                                export_q[col] = export_q[col].apply(lambda x: f"{x:.2f}%")
                        export_q.to_excel(writer, index=False)
                    st.download_button(
                        "💾 导出查询结果",
                        data=output_q.getvalue(),
                        file_name=f"查询_{query_date}.xlsx",
                        key="export_query_result_daily"
                    )
# ========== 发货退货明细 ==========
if idx_ship_return is not None:
    with tabs[idx_ship_return]:
        with st.spinner("正在加载商品数据，请稍候..."):
            prod_df = load_product_sales(st.session_state.table_suffix)
        if prod_df.empty:
            st.info("暂无商品数据，请先上传订单文件")
        else:
            dates = sorted(prod_df["sale_date"].unique(), reverse=True)
            if dates:
                if st.button("📅 今日", key="ship_today"):
                    max_date = prod_df["sale_date"].max().date()
                    st.session_state["ship_return_date_final"] = max_date
                    st.rerun()
                selected_date = st.selectbox("选择日期", dates, format_func=lambda x: x.strftime("%Y-%m-%d"), key="ship_return_date_final")
                filtered = prod_df[prod_df["sale_date"] == selected_date]
                if st.session_state.table_suffix == "_all":
                    filtered["anchor"] = filtered["remark"].apply(extract_anchor)
                    summary = filtered.groupby("anchor").agg(当日发货=("ship_amount", "sum"), 当日退货=("return_amount", "sum")).reset_index().rename(columns={"anchor": "主播"})
                else:
                    summary = filtered.groupby("shop_name").agg(当日发货=("ship_amount", "sum"), 当日退货=("return_amount", "sum")).reset_index()
                st.dataframe(summary, use_container_width=True, hide_index=True)
                if st.session_state.table_suffix == "_all":
                    st.metric("📊 总合计", f"发货: {summary['当日发货'].sum():,.2f}", delta=f"退货: {summary['当日退货'].sum():,.2f}")
                else:
                    douyin_df = summary[summary["shop_name"].str.contains("抖音", case=False, na=False)]
                    video_df = summary[summary["shop_name"].str.contains("视频号", case=False, na=False)]
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("📱 抖音合计", f"发货: {douyin_df['当日发货'].sum():,.2f}", delta=f"退货: {douyin_df['当日退货'].sum():,.2f}")
                    with col2:
                        st.metric("📺 视频号合计", f"发货: {video_df['当日发货'].sum():,.2f}", delta=f"退货: {video_df['当日退货'].sum():,.2f}")
                    with col3:
                        st.metric("📊 总业绩合计", f"发货: {summary['当日发货'].sum():,.2f}", delta=f"退货: {summary['当日退货'].sum():,.2f}")
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    summary.to_excel(writer, index=False)
                st.download_button("💾 导出", data=output.getvalue(), file_name=f"发货退货_{selected_date.strftime('%Y%m%d')}.xlsx", key="export_ship_return")
            else:
                st.info("无日期数据")

# ========== 商品分析 ==========
if idx_product is not None:
    with tabs[idx_product]:
        if st.session_state.get("detail_clicked", False):
            st.session_state.detail_clicked = False
        else:
            st.session_state.show_dialog = False
            st.session_state.dialog_style_code = None
            st.session_state.cached_detail_data = None
        if st.session_state.get("trend_clicked", False):
            st.session_state.trend_clicked = False
        else:
            st.session_state.show_trend_dialog = False
            st.session_state.trend_style_code = None
            st.session_state.trend_data = None

        col_btn, _ = st.columns([1, 5])
        with col_btn:
            if st.button("🔄 刷新数据", key="refresh_analysis_final"):
                st.session_state.show_dialog = False
                st.session_state.dialog_style_code = None
                st.session_state.cached_detail_data = None
                st.session_state.detail_clicked = False
                st.session_state.show_trend_dialog = False
                st.session_state.trend_style_code = None
                st.session_state.trend_data = None
                st.session_state.trend_clicked = False
                st.cache_data.clear()
                st.rerun()
        
        if "dialog_style_code" not in st.session_state:
            st.session_state.dialog_style_code = None
        if "show_dialog" not in st.session_state:
            st.session_state.show_dialog = False
        if "cached_detail_data" not in st.session_state:
            st.session_state.cached_detail_data = None
        if "detail_clicked" not in st.session_state:
            st.session_state.detail_clicked = False
        if "trend_style_code" not in st.session_state:
            st.session_state.trend_style_code = None
        if "show_trend_dialog" not in st.session_state:
            st.session_state.show_trend_dialog = False
        if "trend_data" not in st.session_state:
            st.session_state.trend_data = None
        if "trend_clicked" not in st.session_state:
            st.session_state.trend_clicked = False
        if "product_page_num" not in st.session_state:
            st.session_state.product_page_num = 1
        if "product_page_size" not in st.session_state:
            st.session_state.product_page_size = 10
        if "sort_by" not in st.session_state:
            st.session_state.sort_by = "净销售金额"
        if "sort_ascending" not in st.session_state:
            st.session_state.sort_ascending = False
        
        with st.spinner("正在加载商品销售数据，请稍候..."):
            prod_df = load_product_sales(st.session_state.table_suffix)
        
        if prod_df.empty:
            st.warning("暂无商品销售数据，请先上传订单文件。")
        else:
            if "style_code" in prod_df.columns:
                prod_df["style_code"] = prod_df["style_code"].astype(str).str.strip().str.upper()
            else:
                prod_df["style_code"] = prod_df["product_code"].str[:8].str.strip().str.upper()
            
            if st.session_state.table_suffix in ["_live", "_all"]:
                if "anchor" not in prod_df.columns:
                    prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)
            
            min_date = prod_df["sale_date"].min().date()
            max_date = prod_df["sale_date"].max().date()
            
            date_quick_buttons("prod_start_final", "prod_end_final",
                               default_start=min_date,
                               default_end=max_date,
                               min_date=min_date,
                               max_date=max_date)
            start_date = st.session_state.get("prod_start_final", min_date)
            end_date = st.session_state.get("prod_end_final", max_date)
            
            st.subheader("🔍 筛选条件")
            col_platform, col_shop = st.columns(2)
            with col_platform:
                platform_options = ["全部", "抖音", "视频号"]
                selected_platform = st.selectbox("平台", platform_options, key="platform_filter_final")
            with col_shop:
                all_shops_all = prod_df["shop_name"].unique()
                if selected_platform == "抖音":
                    shop_options = [shop for shop in all_shops_all if "抖音" in shop]
                elif selected_platform == "视频号":
                    shop_options = [shop for shop in all_shops_all if "视频号" in shop]
                else:
                    shop_options = list(all_shops_all)
                selected_shops = st.multiselect("店铺（可多选）", options=sorted(shop_options), default=[], key="shop_filter_final")
            
            col_code, col_brand = st.columns(2)
            with col_code:
                style_codes_input = st.text_input("货号筛选（多个用英文逗号分隔）", placeholder="例如: L262Y050, G262Y030", key="style_code_filter_final")
            with col_brand:
                brands_all = ["全部"] + sorted(prod_df["brand"].dropna().unique())
                selected_brand = st.selectbox("品牌", brands_all, key="brand_filter_final")
            
            coupon_filter_options = ["全部", "仅首单礼金", "非首单礼金"]
            selected_coupon_filter = st.selectbox("是否首单礼金款式", coupon_filter_options, key="coupon_filter_final")
            
            selected_anchors = []
            if st.session_state.table_suffix in ["_live", "_all"]:
                if "anchor" not in prod_df.columns:
                    prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)
                all_anchors = prod_df["anchor"].dropna().unique().tolist()
                if all_anchors:
                    selected_anchors = st.multiselect("主播（可多选）", options=sorted(all_anchors), default=[], key="anchor_filter_final")
                else:
                    st.info("当前数据中未识别到任何主播信息，请检查备注字段是否包含“主播：xxx”格式。")
            
            mask_date = (prod_df["sale_date"] >= pd.to_datetime(start_date)) & (prod_df["sale_date"] <= pd.to_datetime(end_date))
            filtered = prod_df[mask_date].copy()
            
            if selected_platform == "抖音":
                filtered = filtered[filtered["shop_name"].str.contains("抖音", case=False, na=False)]
            elif selected_platform == "视频号":
                filtered = filtered[filtered["shop_name"].str.contains("视频号", case=False, na=False)]
            if selected_shops:
                filtered = filtered[filtered["shop_name"].isin(selected_shops)]
            if style_codes_input.strip():
                target_codes = [code.strip().upper() for code in style_codes_input.split(",") if code.strip()]
                if target_codes:
                    filtered = filtered[filtered["style_code"].isin(target_codes)]
            if selected_brand != "全部":
                filtered = filtered[filtered["brand"] == selected_brand]
            if selected_anchors:
                filtered = filtered[filtered["anchor"].isin(selected_anchors)]
            
            master_df = load_product_master()
            coupon_map = {}
            if not master_df.empty and "style_code" in master_df.columns:
                master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
                coupon_map = master_df.set_index("style_code")["has_newbie_coupon"].to_dict()
            filtered["has_newbie_coupon"] = filtered["style_code"].map(coupon_map).fillna(False)
            if selected_coupon_filter == "仅首单礼金":
                filtered = filtered[filtered["has_newbie_coupon"] == True]
            elif selected_coupon_filter == "非首单礼金":
                filtered = filtered[filtered["has_newbie_coupon"] == False]
            
            if filtered.empty:
                st.warning("所选条件下无销售数据")
            else:
                grouped = filtered.groupby("style_code").agg(
                    发货金额=("ship_amount", "sum"),
                    退货金额=("return_amount", "sum"),
                    净销售金额=("net_amount", "sum")
                ).reset_index().rename(columns={"style_code": "货号"})
                
                if not master_df.empty and "style_code" in master_df.columns:
                    master_df = master_df.drop_duplicates(subset="style_code", keep="first")
                    img_map = master_df.set_index("style_code")["image_url"].to_dict()
                    cat_map = master_df.set_index("style_code")["category"].to_dict()
                    coupon_map = master_df.set_index("style_code")["has_newbie_coupon"].to_dict()
                    grouped["image_url"] = grouped["货号"].map(img_map).fillna(None)
                    grouped["has_newbie_coupon"] = grouped["货号"].map(coupon_map).fillna(False)
                    if "master_category" not in filtered.columns:
                        filtered["master_category"] = None
                    cat_series = filtered.groupby("style_code")["master_category"].first()
                    grouped["master_category"] = grouped["货号"].map(cat_series).fillna(grouped["货号"].map(cat_map))
                else:
                    grouped["master_category"] = None
                    grouped["image_url"] = None
                    grouped["has_newbie_coupon"] = False
                
                grouped["退款率"] = np.where(
                    grouped["发货金额"] != 0,
                    ((grouped["退货金额"] / grouped["发货金额"].replace(0, np.nan)) * 100).map("{:.2f}%".format),
                    "-"
                )
                
                st.markdown("#### 货号汇总表")
                
                col_sort1, col_sort2, col_sort3 = st.columns([1, 1, 2])
                with col_sort1:
                    sort_options = ["货号", "发货金额", "退货金额", "净销售金额", "退款率"]
                    selected_sort = st.selectbox("排序字段", sort_options, index=sort_options.index(st.session_state.sort_by) if st.session_state.sort_by in sort_options else 3, key="sort_by_selector")
                with col_sort2:
                    sort_order = st.radio("排序顺序", ["降序", "升序"], horizontal=True, index=0 if not st.session_state.sort_ascending else 1, key="sort_order_radio")
                with col_sort3:
                    page_size_options = [10, 20, 50, 100]
                    selected_page_size = st.selectbox(
                        "每页显示行数",
                        options=page_size_options,
                        index=page_size_options.index(st.session_state.product_page_size),
                        key="page_size_selector"
                    )
                    if selected_page_size != st.session_state.product_page_size:
                        st.session_state.product_page_size = selected_page_size
                        st.session_state.product_page_num = 1
                        st.rerun()
                
                if selected_sort != st.session_state.sort_by or (sort_order == "降序" and st.session_state.sort_ascending) or (sort_order == "升序" and not st.session_state.sort_ascending):
                    st.session_state.show_dialog = False
                    st.session_state.dialog_style_code = None
                    st.session_state.cached_detail_data = None
                    st.session_state.detail_clicked = False
                    st.session_state.show_trend_dialog = False
                    st.session_state.trend_style_code = None
                    st.session_state.trend_data = None
                    st.session_state.trend_clicked = False
                    st.session_state.sort_by = selected_sort
                    st.session_state.sort_ascending = (sort_order == "升序")
                    st.session_state.product_page_num = 1
                    st.rerun()
                
                if st.session_state.sort_by == "货号":
                    grouped = grouped.sort_values("货号", ascending=st.session_state.sort_ascending)
                elif st.session_state.sort_by == "发货金额":
                    grouped = grouped.sort_values("发货金额", ascending=st.session_state.sort_ascending)
                elif st.session_state.sort_by == "退货金额":
                    grouped = grouped.sort_values("退货金额", ascending=st.session_state.sort_ascending)
                elif st.session_state.sort_by == "净销售金额":
                    grouped = grouped.sort_values("净销售金额", ascending=st.session_state.sort_ascending)
                elif st.session_state.sort_by == "退款率":
                    grouped["退款率_num"] = grouped["退款率"].str.rstrip("%").astype(float)
                    grouped = grouped.sort_values("退款率_num", ascending=st.session_state.sort_ascending)
                    grouped = grouped.drop(columns=["退款率_num"])
                
                page_size = st.session_state.product_page_size
                total_rows = len(grouped)
                total_pages = (total_rows + page_size - 1) // page_size if total_rows > 0 else 1
                if st.session_state.product_page_num > total_pages:
                    st.session_state.product_page_num = 1
                
                col_prev, col_page, col_next, col_export = st.columns([1, 2, 1, 1.5])
                with col_prev:
                    if st.button("◀ 上一页", key="product_prev_page"):
                        st.session_state.show_dialog = False
                        st.session_state.dialog_style_code = None
                        st.session_state.cached_detail_data = None
                        st.session_state.detail_clicked = False
                        st.session_state.show_trend_dialog = False
                        st.session_state.trend_style_code = None
                        st.session_state.trend_data = None
                        st.session_state.trend_clicked = False
                        if st.session_state.product_page_num > 1:
                            st.session_state.product_page_num -= 1
                            st.rerun()
                with col_page:
                    st.write(f"第 {st.session_state.product_page_num} / {total_pages} 页")
                with col_next:
                    if st.button("下一页 ▶", key="product_next_page"):
                        st.session_state.show_dialog = False
                        st.session_state.dialog_style_code = None
                        st.session_state.cached_detail_data = None
                        st.session_state.detail_clicked = False
                        st.session_state.show_trend_dialog = False
                        st.session_state.trend_style_code = None
                        st.session_state.trend_data = None
                        st.session_state.trend_clicked = False
                        if st.session_state.product_page_num < total_pages:
                            st.session_state.product_page_num += 1
                            st.rerun()
                with col_export:
                    is_live_or_all = st.session_state.table_suffix in ["_live", "_all"]
                    if is_live_or_all:
                        detail_type_name = "明细（货号+主播）"
                    else:
                        detail_type_name = "明细（货号+店铺）"
                    
                    export_type = st.radio(
                        "导出类型",
                        ["汇总（货号级别）", detail_type_name],
                        horizontal=True,
                        key="export_type_radio"
                    )
                    
                    if st.button("📥 下载数据", key="export_filtered_data"):
                        if export_type == "汇总（货号级别）":
                            export_df = grouped.copy()
                            if "image_url" in export_df.columns:
                                export_df = export_df.drop(columns=["image_url"])
                            cols_order = ["货号", "master_category", "发货金额", "退货金额", "净销售金额", "退款率", "has_newbie_coupon"]
                            export_cols = [c for c in cols_order if c in export_df.columns]
                            export_df = export_df[export_cols]
                            export_df.rename(columns={
                                "master_category": "商品分类",
                                "has_newbie_coupon": "是否新人礼金"
                            }, inplace=True)
                            export_df["是否新人礼金"] = export_df["是否新人礼金"].map({True: "是", False: "否"})
                            sheet_name = "货号汇总"
                            file_suffix = "货号汇总"
                        else:
                            if is_live_or_all:
                                group_col = "anchor"
                                group_name = "主播"
                            else:
                                group_col = "shop_name"
                                group_name = "店铺"
                            
                            if group_col not in filtered.columns:
                                st.error(f"数据中缺少 {group_name} 信息，无法导出明细。")
                                st.stop()
                            
                            detail_agg = filtered.groupby(["style_code", group_col]).agg(
                                明细发货金额=("ship_amount", "sum"),
                                明细退货金额=("return_amount", "sum"),
                                明细净销售金额=("net_amount", "sum")
                            ).reset_index()
                            
                            detail_agg["明细退款率"] = np.where(
                                detail_agg["明细发货金额"] != 0,
                                (detail_agg["明细退货金额"] / detail_agg["明细发货金额"] * 100).map("{:.2f}%".format),
                                "-"
                            )
                            
                            master_cols = grouped[["货号", "master_category", "发货金额", "退货金额", "净销售金额", "退款率", "has_newbie_coupon"]].copy()
                            export_df = pd.merge(
                                detail_agg,
                                master_cols,
                                left_on="style_code",
                                right_on="货号",
                                how="left"
                            )
                            export_df.drop(columns=["style_code"], inplace=True)
                            export_df.rename(columns={
                                group_col: group_name,
                                "master_category": "商品分类",
                                "has_newbie_coupon": "是否新人礼金"
                            }, inplace=True)
                            export_df["是否新人礼金"] = export_df["是否新人礼金"].map({True: "是", False: "否"})
                            
                            final_cols = [
                                "货号", "商品分类", "发货金额", "退货金额", "净销售金额", "退款率", "是否新人礼金",
                                group_name, "明细发货金额", "明细退货金额", "明细净销售金额", "明细退款率"
                            ]
                            export_df = export_df[final_cols]
                            sheet_name = f"货号{group_name}明细"
                            file_suffix = f"货号{group_name}明细"
                        
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            export_df.to_excel(writer, index=False, sheet_name=sheet_name)
                        st.success("导出成功！点击下方按钮下载")
                        st.download_button(
                            label="💾 点击下载 Excel",
                            data=output.getvalue(),
                            file_name=f"{file_suffix}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx",
                            key="download_export",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                
                start_idx = (st.session_state.product_page_num - 1) * page_size
                end_idx = min(start_idx + page_size, total_rows)
                page_df = grouped.iloc[start_idx:end_idx]
                
                cols = st.columns([2, 0.5, 1.5, 1.2, 1.2, 1.2, 1, 0.8, 0.8, 0.8])
                headers = ["货号", "图片", "商品分类", "发货金额(¥)", "退货金额(¥)", "净销售金额(¥)", "退款率", "新人礼金", "详情", "趋势"]
                for col, header in zip(cols, headers):
                    col.markdown(f"**{header}**")
                
                for idx, row in page_df.iterrows():
                    col1, col2, col3, col4, col5, col6, col7, col8, col9, col10 = st.columns([2, 0.5, 1.5, 1.2, 1.2, 1.2, 1, 0.8, 0.8, 0.8])
                    col1.write(row["货号"])
                    if row.get("image_url") and pd.notna(row["image_url"]):
                        col2.image(row["image_url"], width=50)
                    else:
                        col2.write("-")
                    col3.write(row["master_category"] if pd.notna(row["master_category"]) else "-")
                    col4.write(f"{row['发货金额']:,.2f}")
                    col5.write(f"{row['退货金额']:,.2f}")
                    col6.write(f"{row['净销售金额']:,.2f}")
                    col7.write(row["退款率"])
                    col8.write("✅" if row.get("has_newbie_coupon") else "❌")
                    if col9.button("📊", key=f"detail_btn_{row['货号']}_{idx}"):
                        style_code = row["货号"]
                        detail_df = filtered[filtered["style_code"] == style_code].copy()
                        if not detail_df.empty:
                            suffix = st.session_state.table_suffix
                            def extract_anchor_fn(remark):
                                match = re.search(r'主播[：:]([^_]+)', remark)
                                return match.group(1).strip() if match else None
                            if suffix in ["_live", "_all"]:
                                detail_df["anchor"] = detail_df["remark"].apply(extract_anchor_fn)
                                detail_df = detail_df[detail_df["anchor"].notna()]
                                if not detail_df.empty:
                                    shop_detail = detail_df.groupby("anchor").agg(
                                        发货金额=("ship_amount", "sum"),
                                        退货金额=("return_amount", "sum"),
                                        净销售金额=("net_amount", "sum")
                                    ).reset_index().rename(columns={"anchor": "主播"})
                                    shop_detail["退款率"] = shop_detail.apply(
                                        lambda r: f"{(r['退货金额']/r['发货金额']*100):.2f}%" if r['发货金额']!=0 else "-", axis=1
                                    )
                                    detail_type = "anchor"
                                else:
                                    shop_detail = pd.DataFrame()
                                    detail_type = "anchor"
                            else:
                                shop_detail = detail_df.groupby("shop_name").agg(
                                    发货金额=("ship_amount", "sum"),
                                    退货金额=("return_amount", "sum"),
                                    净销售金额=("net_amount", "sum")
                                ).reset_index()
                                shop_detail["退款率"] = shop_detail.apply(
                                    lambda r: f"{(r['退货金额']/r['发货金额']*100):.2f}%" if r['发货金额']!=0 else "-", axis=1
                                )
                                detail_type = "shop"
                            st.session_state.cached_detail_data = {"style_code": style_code, "shop_detail": shop_detail, "type": detail_type}
                        else:
                            st.session_state.cached_detail_data = None
                        st.session_state.show_trend_dialog = False
                        st.session_state.trend_style_code = None
                        st.session_state.trend_data = None
                        st.session_state.trend_clicked = False
                        st.session_state.dialog_style_code = style_code
                        st.session_state.show_dialog = True
                        st.session_state.detail_clicked = True
                        st.rerun()
                    if col10.button("📈", key=f"trend_btn_{row['货号']}_{idx}"):
                        style_code = row["货号"]
                        trend_data = filtered[filtered["style_code"] == style_code].copy()
                        if not trend_data.empty:
                            daily = trend_data.groupby("sale_date").agg(
                                ship_amount=("ship_amount", "sum"),
                                return_amount=("return_amount", "sum"),
                                net_amount=("net_amount", "sum")
                            ).reset_index().sort_values("sale_date")
                            st.session_state.trend_data = daily
                        else:
                            st.session_state.trend_data = None
                        st.session_state.show_dialog = False
                        st.session_state.dialog_style_code = None
                        st.session_state.cached_detail_data = None
                        st.session_state.detail_clicked = False
                        st.session_state.trend_style_code = style_code
                        st.session_state.show_trend_dialog = True
                        st.session_state.trend_clicked = True
                        st.rerun()
        
        if st.session_state.show_dialog and st.session_state.dialog_style_code:
            style_code = st.session_state.dialog_style_code
            cached = st.session_state.cached_detail_data
            @st.dialog(f"📋 货号 {style_code} 销售明细", width="large")
            def show_style_detail():
                if cached and cached.get("style_code") == style_code:
                    shop_detail = cached["shop_detail"]
                    if cached.get("type") == "anchor":
                        st.markdown("#### 主播销售汇总")
                    else:
                        st.markdown("#### 店铺销售汇总")
                    if not shop_detail.empty:
                        st.dataframe(shop_detail, column_config={
                            "主播" if cached.get("type") == "anchor" else "shop_name": st.column_config.TextColumn("主播" if cached.get("type") == "anchor" else "店铺"),
                            "发货金额": st.column_config.NumberColumn("发货金额(¥)", format="%.2f"),
                            "退货金额": st.column_config.NumberColumn("退货金额(¥)", format="%.2f"),
                            "净销售金额": st.column_config.NumberColumn("净销售金额(¥)", format="%.2f"),
                            "退款率": st.column_config.TextColumn("退款率")
                        }, hide_index=True, use_container_width=True)
                    else:
                        st.info("无有效数据")
                else:
                    st.info("该货号无销售数据")
                if st.button("关闭", key="close_dialog"):
                    st.session_state.show_dialog = False
                    st.session_state.dialog_style_code = None
                    st.session_state.cached_detail_data = None
                    st.session_state.detail_clicked = False
                    st.rerun()
            show_style_detail()
        
        if st.session_state.show_trend_dialog and st.session_state.trend_style_code:
            style_code = st.session_state.trend_style_code
            @st.dialog(f"📈 货号 {style_code} 销售趋势", width="large")
            def show_trend():
                st.subheader(f"货号：{style_code}")
                daily = st.session_state.trend_data
                if daily is None or daily.empty:
                    st.info("当前筛选条件下该货号无销售数据")
                else:
                    show_ship = st.checkbox("显示发货金额", value=True, key="trend_ship")
                    show_return = st.checkbox("显示退货金额", value=True, key="trend_return")
                    show_net = st.checkbox("显示净销售金额", value=True, key="trend_net")
                    lines = []
                    if show_ship and "ship_amount" in daily.columns:
                        lines.append(go.Scatter(x=daily["sale_date"], y=daily["ship_amount"], name="发货金额", mode="lines+markers"))
                    if show_return and "return_amount" in daily.columns:
                        lines.append(go.Scatter(x=daily["sale_date"], y=daily["return_amount"], name="退货金额", mode="lines+markers"))
                    if show_net and "net_amount" in daily.columns:
                        lines.append(go.Scatter(x=daily["sale_date"], y=daily["net_amount"], name="净销售金额", mode="lines+markers"))
                    if not lines:
                        st.info("请至少勾选一项")
                    else:
                        fig = go.Figure(data=lines)
                        fig.update_layout(title="每日销售趋势", xaxis_title="日期", yaxis_title="金额(¥)", legend_title="指标", hovermode="x unified")
                        st.plotly_chart(fig, use_container_width=True)
                if st.button("关闭", key="close_trend"):
                    st.session_state.show_trend_dialog = False
                    st.session_state.trend_style_code = None
                    st.session_state.trend_data = None
                    st.session_state.trend_clicked = False
                    st.rerun()
            show_trend()

# ========== 销售对比（主播/店铺维度） ==========
if idx_anchor_compare is not None:
    with tabs[idx_anchor_compare]:
        use_anchor = st.session_state.table_suffix in ["_live", "_all"]
        dimension_name = "主播" if use_anchor else "店铺"
        dimension_col = "anchor" if use_anchor else "shop_name"
        
        with st.spinner("正在加载数据..."):
            prod_df = load_product_sales(st.session_state.table_suffix)
        if prod_df.empty:
            st.info("暂无商品销售数据，请先上传订单文件。")
        else:
            if dimension_col not in prod_df.columns:
                if use_anchor:
                    prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)
                else:
                    if "shop_name" not in prod_df.columns:
                        st.error("数据中缺少店铺名称信息，无法进行店铺对比。")
                        st.stop()
            prod_df = prod_df[prod_df[dimension_col].notna()].copy()
            if prod_df.empty:
                st.info(f"当前数据中未识别到任何{dimension_name}信息，请检查数据。")
            else:
                all_dimensions = sorted(prod_df[dimension_col].unique())
                col_select1, col_select2, col_select3 = st.columns(3)
                with col_select1:
                    selected_dimensions = st.multiselect(
                        f"选择对比的{dimension_name}（最多3个）",
                        options=all_dimensions,
                        default=[],
                        key="dimension_multiselect"
                    )
                    if len(selected_dimensions) > 3:
                        st.warning("最多只能选择3个，请取消多余的选项。")
                        selected_dimensions = selected_dimensions[:3]
                with col_select2:
                    metric_options = ["净销售金额", "发货金额", "退货金额"]
                    selected_metrics = st.multiselect("选择要对比的指标", options=metric_options, default=["净销售金额"])
                with col_select3:
                    chart_type = st.radio("图表类型", ["折线图", "柱状图"], horizontal=True, key="compare_chart_type")
                
                min_date = prod_df["sale_date"].min().date()
                max_date = prod_df["sale_date"].max().date()
                
                date_quick_buttons("compare_start", "compare_end",
                                   default_start=min_date,
                                   default_end=max_date,
                                   min_date=min_date,
                                   max_date=max_date)
                start_date = st.session_state.get("compare_start", min_date)
                end_date = st.session_state.get("compare_end", max_date)
                
                if not selected_dimensions:
                    st.info(f"请至少选择一个{dimension_name}")
                else:
                    mask_date = (prod_df["sale_date"] >= pd.to_datetime(start_date)) & (prod_df["sale_date"] <= pd.to_datetime(end_date))
                    filtered = prod_df[mask_date].copy()
                    if filtered.empty:
                        st.warning("所选日期范围内无销售数据")
                    else:
                        daily_agg = filtered.groupby(["sale_date", dimension_col]).agg(
                            净销售金额=("net_amount", "sum"),
                            发货金额=("ship_amount", "sum"),
                            退货金额=("return_amount", "sum")
                        ).reset_index()
                        daily_agg = daily_agg[daily_agg[dimension_col].isin(selected_dimensions)]
                        if daily_agg.empty:
                            st.warning(f"所选{dimension_name}在日期范围内无销售数据")
                        else:
                            st.caption(f"当前选中的 {dimension_name}：{selected_dimensions}")
                            
                            for metric in selected_metrics:
                                st.markdown(f"#### {metric} 趋势对比")
                                pivot_df = daily_agg.pivot(index="sale_date", columns=dimension_col, values=metric)
                                pivot_df = pivot_df.reindex(columns=selected_dimensions, fill_value=0)
                                st.caption(f"补全后的列：{list(pivot_df.columns)}")
                                
                                if chart_type == "折线图":
                                    fig = go.Figure()
                                    for dim in pivot_df.columns:
                                        fig.add_trace(go.Scatter(
                                            x=pivot_df.index,
                                            y=pivot_df[dim],
                                            mode="lines+markers",
                                            name=dim,
                                            hovertemplate=f"{dim}<br>日期: %{{x|%Y-%m-%d}}<br>{metric}: %{{y:,.2f}}<extra></extra>"
                                        ))
                                    fig.update_layout(
                                        title=f"{metric} 按日对比（折线图）",
                                        xaxis_title="日期",
                                        yaxis_title=f"{metric} (¥)",
                                        legend_title=dimension_name,
                                        hovermode="x unified"
                                    )
                                else:
                                    fig = go.Figure()
                                    for dim in pivot_df.columns:
                                        fig.add_trace(go.Bar(
                                            x=pivot_df.index,
                                            y=pivot_df[dim],
                                            name=dim,
                                            hovertemplate=f"{dim}<br>日期: %{{x|%Y-%m-%d}}<br>{metric}: %{{y:,.2f}}<extra></extra>"
                                        ))
                                    fig.update_layout(
                                        title=f"{metric} 按日对比（柱状图）",
                                        xaxis_title="日期",
                                        yaxis_title=f"{metric} (¥)",
                                        legend_title=dimension_name,
                                        barmode='group',
                                        hovermode="x unified"
                                    )
                                st.plotly_chart(fig, use_container_width=True, key=f"compare_{metric}_{chart_type}")
                            
                            # 品类分析
                            st.markdown(f"#### {dimension_name}品类销售分析")
                            col_cat1, col_cat2 = st.columns([1, 2])
                            with col_cat1:
                                cat_chart_type = st.radio("品类图表类型", ["柱状图（对比品类）", "饼图（各维度品类分布）"], horizontal=False, key="cat_chart_type")
                            with col_cat2:
                                cat_metric = st.selectbox("品类金额指标", ["净销售金额", "发货金额", "退货金额"], key="cat_metric")
                            cat_metric_col = {"净销售金额": "net_amount", "发货金额": "ship_amount", "退货金额": "return_amount"}[cat_metric]
                            cat_metric_name = cat_metric
                            
                            if "master_category" not in filtered.columns:
                                master_df = load_product_master()
                                if not master_df.empty and "style_code" in master_df.columns:
                                    master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
                                    cat_map = master_df.set_index("style_code")["category"].to_dict()
                                    filtered["master_category"] = filtered["style_code"].map(cat_map).fillna("未分类")
                                else:
                                    filtered["master_category"] = "未分类"
                            else:
                                filtered["master_category"] = filtered["master_category"].fillna("未分类")
                            
                            if cat_chart_type == "柱状图（对比品类）":
                                cat_agg = filtered.groupby([dimension_col, "master_category"])[cat_metric_col].sum().reset_index()
                                cat_agg.rename(columns={cat_metric_col: "金额"}, inplace=True)
                                top_cats_per_dim = {}
                                for dim in selected_dimensions:
                                    dim_data = cat_agg[cat_agg[dimension_col] == dim].copy()
                                    if not dim_data.empty:
                                        dim_data = dim_data.sort_values("金额", ascending=False)
                                        top5 = dim_data.head(5)
                                        top_cats_per_dim[dim] = top5
                                all_top_cats = set()
                                for dim, df_top in top_cats_per_dim.items():
                                    all_top_cats.update(df_top["master_category"].tolist())
                                all_top_cats = sorted(list(all_top_cats))
                                if all_top_cats:
                                    compare_df = pd.DataFrame(index=all_top_cats)
                                    for dim in selected_dimensions:
                                        dim_sales = {}
                                        if dim in top_cats_per_dim:
                                            for _, row in top_cats_per_dim[dim].iterrows():
                                                dim_sales[row["master_category"]] = row["金额"]
                                        compare_df[dim] = [dim_sales.get(cat, 0) for cat in all_top_cats]
                                    compare_df = compare_df.reindex(columns=selected_dimensions, fill_value=0)
                                    fig_cat = px.bar(
                                        compare_df,
                                        x=compare_df.index,
                                        y=selected_dimensions,
                                        barmode='group',
                                        title=f"{dimension_name}Top5品类{cat_metric_name}对比",
                                        labels={"value": f"{cat_metric_name}(¥)", "index": "商品品类"},
                                        color_discrete_sequence=px.colors.qualitative.Set2
                                    )
                                    fig_cat.update_layout(xaxis_title="商品品类", yaxis_title=f"{cat_metric_name}(¥)", legend_title=dimension_name)
                                    st.plotly_chart(fig_cat, use_container_width=True)
                                else:
                                    st.info("无法获取品类数据，无法生成对比图。")
                            else:
                                cat_agg = filtered.groupby([dimension_col, "master_category"])[cat_metric_col].sum().reset_index()
                                cat_agg.rename(columns={cat_metric_col: "金额"}, inplace=True)
                                dim_pie_data = {}
                                for dim in selected_dimensions:
                                    dim_data = cat_agg[cat_agg[dimension_col] == dim].copy()
                                    if dim_data.empty:
                                        continue
                                    dim_data = dim_data.sort_values("金额", ascending=False)
                                    top5 = dim_data.head(5)
                                    other_sum = dim_data.iloc[5:]["金额"].sum() if len(dim_data) > 5 else 0
                                    if other_sum > 0:
                                        other_row = pd.DataFrame({"master_category": ["其他"], "金额": [other_sum]})
                                        top5 = pd.concat([top5, other_row], ignore_index=True)
                                    dim_pie_data[dim] = top5
                                if dim_pie_data:
                                    cols = st.columns(len(dim_pie_data))
                                    for idx, (dim, data) in enumerate(dim_pie_data.items()):
                                        with cols[idx]:
                                            fig_pie = px.pie(
                                                data,
                                                names="master_category",
                                                values="金额",
                                                title=f"{dim} - 品类分布 ({cat_metric_name})",
                                                hole=0.3,
                                                color_discrete_sequence=px.colors.qualitative.Pastel
                                            )
                                            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                                            st.plotly_chart(fig_pie, use_container_width=True)
                                else:
                                    st.info("无有效数据")
                            
                            # 季节分析
                            st.markdown(f"#### {dimension_name}季节销售分析")
                            col_season1, col_season2 = st.columns([1, 2])
                            with col_season1:
                                season_chart_type = st.radio("季节图表类型", ["柱状图（对比季节）", "饼图（各维度季节分布）"], horizontal=False, key="season_chart_type")
                            with col_season2:
                                season_metric = st.selectbox("季节金额指标", ["净销售金额", "发货金额", "退货金额"], key="season_metric")
                            season_metric_col = {"净销售金额": "net_amount", "发货金额": "ship_amount", "退货金额": "return_amount"}[season_metric]
                            season_metric_name = season_metric
                            
                            if "season" not in filtered.columns:
                                st.info("数据中缺少季节信息，无法生成季节对比图。")
                            else:
                                season_data = filtered[filtered["season"].notna()].copy()
                                if season_data.empty:
                                    st.info("所选范围内无季节数据")
                                else:
                                    if season_chart_type == "柱状图（对比季节）":
                                        season_agg = season_data.groupby([dimension_col, "season"])[season_metric_col].sum().reset_index()
                                        season_agg.rename(columns={season_metric_col: "金额"}, inplace=True)
                                        season_agg = season_agg[season_agg[dimension_col].isin(selected_dimensions)]
                                        if not season_agg.empty:
                                            pivot_season = season_agg.pivot(index="season", columns=dimension_col, values="金额").fillna(0)
                                            pivot_season = pivot_season.reindex(columns=selected_dimensions, fill_value=0)
                                            season_order = ["春", "夏", "秋", "冬"]
                                            pivot_season = pivot_season.reindex([s for s in season_order if s in pivot_season.index])
                                            if not pivot_season.empty:
                                                fig_season = px.bar(
                                                    pivot_season,
                                                    x=pivot_season.index,
                                                    y=selected_dimensions,
                                                    barmode='group',
                                                    title=f"{dimension_name}季节{season_metric_name}对比",
                                                    labels={"value": f"{season_metric_name}(¥)", "index": "季节"},
                                                    color_discrete_sequence=px.colors.qualitative.Set1
                                                )
                                                fig_season.update_layout(xaxis_title="季节", yaxis_title=f"{season_metric_name}(¥)", legend_title=dimension_name)
                                                st.plotly_chart(fig_season, use_container_width=True)
                                            else:
                                                st.info("无有效季节数据")
                                        else:
                                            st.info(f"所选{dimension_name}无季节数据")
                                    else:
                                        season_agg = season_data.groupby([dimension_col, "season"])[season_metric_col].sum().reset_index()
                                        season_agg.rename(columns={season_metric_col: "金额"}, inplace=True)
                                        dim_season_data = {}
                                        for dim in selected_dimensions:
                                            dim_season = season_agg[season_agg[dimension_col] == dim].copy()
                                            if not dim_season.empty:
                                                dim_season_data[dim] = dim_season
                                        if dim_season_data:
                                            cols = st.columns(len(dim_season_data))
                                            for idx, (dim, data) in enumerate(dim_season_data.items()):
                                                with cols[idx]:
                                                    fig_pie_season = px.pie(
                                                        data,
                                                        names="season",
                                                        values="金额",
                                                        title=f"{dim} - 季节分布 ({season_metric_name})",
                                                        hole=0.3,
                                                        color_discrete_sequence=px.colors.qualitative.Set2
                                                    )
                                                    fig_pie_season.update_traces(textposition='inside', textinfo='percent+label')
                                                    st.plotly_chart(fig_pie_season, use_container_width=True)
                                        else:
                                            st.info("无有效数据")
                            
                            # 年份分析
                            st.markdown(f"#### {dimension_name}年份销售分析")
                            col_year1, col_year2 = st.columns([1, 2])
                            with col_year1:
                                year_chart_type = st.radio("年份图表类型", ["柱状图（对比年份）", "饼图（各维度年份分布）"], horizontal=False, key="year_chart_type")
                            with col_year2:
                                year_metric = st.selectbox("年份金额指标", ["净销售金额", "发货金额", "退货金额"], key="year_metric")
                            year_metric_col = {"净销售金额": "net_amount", "发货金额": "ship_amount", "退货金额": "return_amount"}[year_metric]
                            year_metric_name = year_metric
                            
                            if "year" not in filtered.columns:
                                st.info("数据中缺少年份信息，无法生成年份对比图。")
                            else:
                                year_data = filtered[filtered["year"].notna()].copy()
                                if year_data.empty:
                                    st.info("所选范围内无年份数据")
                                else:
                                    if year_chart_type == "柱状图（对比年份）":
                                        year_agg = year_data.groupby([dimension_col, "year"])[year_metric_col].sum().reset_index()
                                        year_agg.rename(columns={year_metric_col: "金额"}, inplace=True)
                                        year_agg = year_agg[year_agg[dimension_col].isin(selected_dimensions)]
                                        if not year_agg.empty:
                                            pivot_year = year_agg.pivot(index="year", columns=dimension_col, values="金额").fillna(0)
                                            pivot_year = pivot_year.reindex(columns=selected_dimensions, fill_value=0)
                                            pivot_year = pivot_year.sort_index()
                                            if not pivot_year.empty:
                                                fig_year = px.bar(
                                                    pivot_year,
                                                    x=pivot_year.index,
                                                    y=selected_dimensions,
                                                    barmode='group',
                                                    title=f"{dimension_name}年份{year_metric_name}对比",
                                                    labels={"value": f"{year_metric_name}(¥)", "index": "年份"},
                                                    color_discrete_sequence=px.colors.qualitative.Pastel
                                                )
                                                fig_year.update_layout(xaxis_title="年份", yaxis_title=f"{year_metric_name}(¥)", legend_title=dimension_name)
                                                st.plotly_chart(fig_year, use_container_width=True)
                                            else:
                                                st.info("无有效年份数据")
                                        else:
                                            st.info(f"所选{dimension_name}无年份数据")
                                    else:
                                        year_agg = year_data.groupby([dimension_col, "year"])[year_metric_col].sum().reset_index()
                                        year_agg.rename(columns={year_metric_col: "金额"}, inplace=True)
                                        dim_year_data = {}
                                        for dim in selected_dimensions:
                                            dim_year = year_agg[year_agg[dimension_col] == dim].copy()
                                            if not dim_year.empty:
                                                dim_year = dim_year.sort_values("year")
                                                dim_year_data[dim] = dim_year
                                        if dim_year_data:
                                            cols = st.columns(len(dim_year_data))
                                            for idx, (dim, data) in enumerate(dim_year_data.items()):
                                                with cols[idx]:
                                                    fig_pie_year = px.pie(
                                                        data,
                                                        names="year",
                                                        values="金额",
                                                        title=f"{dim} - 年份分布 ({year_metric_name})",
                                                        hole=0.3,
                                                        color_discrete_sequence=px.colors.qualitative.Set3
                                                    )
                                                    fig_pie_year.update_traces(textposition='inside', textinfo='percent+label')
                                                    st.plotly_chart(fig_pie_year, use_container_width=True)
                                        else:
                                            st.info("无有效数据")

# ========== 销售分布与品牌 ==========
if idx_distribution is not None:
    with tabs[idx_distribution]:
        with st.spinner("正在加载数据，请稍候..."):
            prod_df = load_product_sales(st.session_state.table_suffix)
        if prod_df.empty:
            st.warning("暂无商品销售数据，请先上传订单文件。")
        else:
            if "style_code" in prod_df.columns:
                prod_df["style_code"] = prod_df["style_code"].astype(str).str.strip().str.upper()
            else:
                prod_df["style_code"] = prod_df["product_code"].str[:8].str.strip().str.upper()
            if st.session_state.table_suffix in ["_live", "_all"]:
                if "anchor" not in prod_df.columns:
                    prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)
            
            st.markdown("#### 筛选条件")
            min_date = prod_df["sale_date"].min().date()
            max_date = prod_df["sale_date"].max().date()
            
            date_quick_buttons("dist_start_v2", "dist_end_v2",
                               default_start=min_date,
                               default_end=max_date,
                               min_date=min_date,
                               max_date=max_date)
            start_date = st.session_state.get("dist_start_v2", min_date)
            end_date = st.session_state.get("dist_end_v2", max_date)
            
            col_platform, col_shop = st.columns(2)
            with col_platform:
                platform_options = ["全部", "抖音", "视频号"]
                selected_platform = st.selectbox("平台", platform_options, key="dist_platform_v2")
            with col_shop:
                all_shops_all = prod_df["shop_name"].unique()
                if selected_platform == "抖音":
                    shop_options = [shop for shop in all_shops_all if "抖音" in shop]
                elif selected_platform == "视频号":
                    shop_options = [shop for shop in all_shops_all if "视频号" in shop]
                else:
                    shop_options = list(all_shops_all)
                selected_shops = st.multiselect("店铺（可多选）", options=sorted(shop_options), default=[], key="dist_shop_v2")
            
            col_brand, col_anchor = st.columns(2)
            with col_brand:
                brands_all = ["全部"] + sorted(prod_df["brand"].dropna().unique())
                selected_brand = st.selectbox("品牌", brands_all, key="dist_brand_v2")
            with col_anchor:
                selected_anchors = []
                if st.session_state.table_suffix in ["_live", "_all"]:
                    if "anchor" not in prod_df.columns:
                        prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)
                    all_anchors = prod_df["anchor"].dropna().unique().tolist()
                    if all_anchors:
                        selected_anchors = st.multiselect("主播（可多选）", options=sorted(all_anchors), default=[], key="dist_anchor_v2")
                    else:
                        st.info("当前数据中未识别到任何主播信息，请检查备注字段是否包含“主播：xxx”格式。")
            
            mask_date = (prod_df["sale_date"] >= pd.to_datetime(start_date)) & (prod_df["sale_date"] <= pd.to_datetime(end_date))
            filtered = prod_df[mask_date].copy()
            if selected_platform == "抖音":
                filtered = filtered[filtered["shop_name"].str.contains("抖音", case=False, na=False)]
            elif selected_platform == "视频号":
                filtered = filtered[filtered["shop_name"].str.contains("视频号", case=False, na=False)]
            if selected_shops:
                filtered = filtered[filtered["shop_name"].isin(selected_shops)]
            if selected_brand != "全部":
                filtered = filtered[filtered["brand"] == selected_brand]
            if selected_anchors:
                filtered = filtered[filtered["anchor"].isin(selected_anchors)]
            
            if filtered.empty:
                st.warning("所选条件下无销售数据")
            else:
                metric_options = ["净销售金额", "发货金额", "退货金额"]
                selected_metric = st.radio("金额指标", metric_options, horizontal=True, key="dist_metric_v2")
                metric_col = {"净销售金额": "net_amount", "发货金额": "ship_amount", "退货金额": "return_amount"}[selected_metric]
                metric_name = selected_metric
                
                if "master_category" not in filtered.columns:
                    master_df = load_product_master()
                    if not master_df.empty and "style_code" in master_df.columns:
                        master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
                        cat_map = master_df.set_index("style_code")["category"].to_dict()
                        filtered["master_category"] = filtered["style_code"].map(cat_map).fillna("未分类")
                    else:
                        filtered["master_category"] = "未分类"
                else:
                    filtered["master_category"] = filtered["master_category"].fillna("未分类")
                cat_data = filtered.groupby("master_category")[metric_col].sum().reset_index()
                
                if "year" in filtered.columns and not filtered["year"].isnull().all():
                    year_data = filtered.groupby("year")[metric_col].sum().reset_index()
                    year_data = year_data[year_data["year"].notna()]
                else:
                    total_val = filtered[metric_col].sum()
                    year_data = pd.DataFrame({"year": ["无年份信息"], metric_col: [total_val]}) if total_val > 0 else None
                
                if "season" in filtered.columns and not filtered["season"].isnull().all():
                    season_data = filtered.groupby("season")[metric_col].sum().reset_index()
                    season_data = season_data[season_data["season"].notna()]
                else:
                    total_val = filtered[metric_col].sum()
                    season_data = pd.DataFrame({"season": ["无季节信息"], metric_col: [total_val]}) if total_val > 0 else None
                
                def create_pie_chart(data, name_col, value_col, title, key):
                    if data is None:
                        return None
                    total = data[value_col].sum()
                    if total == 0 or total < 0 and metric_col == "net_amount":
                        return None
                    chart_data = data[data[value_col] != 0].copy()
                    if chart_data.empty:
                        return None
                    fig = px.pie(chart_data, names=name_col, values=value_col, title=title, hole=0.3, color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig, use_container_width=True, key=key)
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    if cat_data is not None and not cat_data.empty:
                        create_pie_chart(cat_data, "master_category", metric_col, f"分类{metric_name}占比", "pie_category_v2")
                    else:
                        st.info("无分类数据")
                with col2:
                    if year_data is not None and not year_data.empty:
                        create_pie_chart(year_data, "year", metric_col, f"年份{metric_name}占比", "pie_year_v2")
                    else:
                        st.info("无年份数据")
                with col3:
                    if season_data is not None and not season_data.empty:
                        create_pie_chart(season_data, "season", metric_col, f"季节{metric_name}占比", "pie_season_v2")
                    else:
                        st.info("无季节数据")
                
                master_df = load_product_master()
                if "has_newbie_coupon" not in filtered.columns:
                    if not master_df.empty and "style_code" in master_df.columns:
                        master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
                        coupon_map = master_df.set_index("style_code")["has_newbie_coupon"].to_dict()
                        filtered["has_newbie_coupon"] = filtered["style_code"].map(coupon_map).fillna(False)
                    else:
                        filtered["has_newbie_coupon"] = False
                else:
                    filtered["has_newbie_coupon"] = filtered["has_newbie_coupon"].fillna(False)
                
                coupon_filtered = filtered[filtered["has_newbie_coupon"] == True].copy()
                non_coupon_filtered = filtered[filtered["has_newbie_coupon"] == False].copy()
                
                st.markdown(f"#### 首单礼金销售分析")
                col_left, col_right = st.columns(2)
                with col_left:
                    coupon_total = coupon_filtered[metric_col].sum()
                    non_coupon_total = non_coupon_filtered[metric_col].sum()
                    if coupon_total > 0 or non_coupon_total > 0:
                        coupon_pie_data = pd.DataFrame({
                            "类型": ["参与首单礼金", "未参与首单礼金"],
                            metric_name: [coupon_total, non_coupon_total]
                        })
                        coupon_pie_data = coupon_pie_data[coupon_pie_data[metric_name] > 0]
                        fig_coupon_total = px.pie(coupon_pie_data, names="类型", values=metric_name,
                                                  title=f"首单礼金商品{metric_name}占比", hole=0.3,
                                                  color_discrete_sequence=["#FF6B6B", "#4ECDC4"])
                        fig_coupon_total.update_traces(textposition='inside', textinfo='percent+label')
                        st.plotly_chart(fig_coupon_total, use_container_width=True, key="pie_coupon_total_v2")
                    else:
                        st.info("无首单礼金数据")
                with col_right:
                    if not coupon_filtered.empty:
                        coupon_brand_data = coupon_filtered.groupby("brand")[metric_col].sum().reset_index()
                        coupon_brand_data = coupon_brand_data[coupon_brand_data[metric_col] != 0]
                        if not coupon_brand_data.empty:
                            if len(coupon_brand_data) > 8:
                                top8 = coupon_brand_data.nlargest(8, metric_col)
                                other_sum = coupon_brand_data[~coupon_brand_data["brand"].isin(top8["brand"])][metric_col].sum()
                                other_row = pd.DataFrame({"brand": ["其他"], metric_col: [other_sum]})
                                coupon_brand_data = pd.concat([top8, other_row], ignore_index=True)
                            fig_coupon_brand = px.pie(coupon_brand_data, names="brand", values=metric_col,
                                                      title=f"首单礼金商品{metric_name}品牌占比", hole=0.3,
                                                      color_discrete_sequence=px.colors.qualitative.Set2)
                            fig_coupon_brand.update_traces(textposition='inside', textinfo='percent+label')
                            st.plotly_chart(fig_coupon_brand, use_container_width=True, key="pie_coupon_brand_v2")
                        else:
                            st.info("无礼金品牌数据")
                    else:
                        st.info("无礼金商品数据")
                
                if not coupon_filtered.empty:
                    st.markdown(f"#### 首单礼金商品销售明细（按货号汇总）")
                    coupon_detail = coupon_filtered.groupby("style_code").agg(
                        发货金额=("ship_amount", "sum"),
                        退货金额=("return_amount", "sum"),
                        净销售金额=("net_amount", "sum")
                    ).reset_index()
                    coupon_detail.rename(columns={"style_code": "货号"}, inplace=True)
                    master_df = load_product_master()
                    if not master_df.empty and "style_code" in master_df.columns:
                        master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
                        img_map = master_df.set_index("style_code")["image_url"].to_dict()
                        coupon_detail["图片"] = coupon_detail["货号"].map(img_map).fillna(None)
                    else:
                        coupon_detail["图片"] = None
                    coupon_detail["退款率"] = coupon_detail.apply(
                        lambda r: f"{(r['退货金额']/r['发货金额']*100):.2f}%" if r['发货金额'] != 0 else "-", axis=1
                    )
                    col_order = ["货号", "图片", "发货金额", "退货金额", "净销售金额", "退款率"]
                    coupon_detail = coupon_detail[col_order]
                    st.dataframe(
                        coupon_detail,
                        column_config={
                            "货号": st.column_config.TextColumn("货号"),
                            "图片": st.column_config.ImageColumn("商品图片", help="点击放大"),
                            "发货金额": st.column_config.NumberColumn("发货金额(¥)", format="%.2f"),
                            "退货金额": st.column_config.NumberColumn("退货金额(¥)", format="%.2f"),
                            "净销售金额": st.column_config.NumberColumn("净销售金额(¥)", format="%.2f"),
                            "退款率": st.column_config.TextColumn("退款率")
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        export_df = coupon_detail.drop(columns=["图片"], errors='ignore')
                        export_df.to_excel(writer, index=False)
                    st.download_button(
                        "💾 导出首单礼金商品明细",
                        data=output.getvalue(),
                        file_name=f"首单礼金明细_{start_date}_{end_date}.xlsx",
                        key="export_coupon_detail_v2"
                    )
                else:
                    st.info("当前筛选条件下无首单礼金商品")

# ========== 组织与部门分析（仅 _all） ==========
if idx_org is not None:
    with tabs[idx_org]:

        # ======================== 独立日期选择器 ========================
        @st.cache_data(ttl=600)
        def get_date_range(suffix):
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

        suffix = st.session_state.table_suffix
        min_date, max_date = get_date_range(suffix)
        if min_date is None or max_date is None:
            st.warning("无法获取数据日期范围，请检查数据表是否存在。")
            st.stop()

        st.markdown("#### 📅 日期选择")
        base_date = st.date_input(
            "选择分析基准日期",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            key="org_base_date"
        )
        st.caption(f"当前数据日期范围：{min_date} ~ {max_date}，您可以选择任意日期查看对应数据。")

                # ======================== 1. 核心大盘 KPI ========================
        st.markdown("---")
        st.markdown("#### 📊 营销中心整体销售")
        latest_date = base_date
        month_start = latest_date.replace(day=1)

        # ---------- 加载目标 ----------
        if suffix == "_all":
            org_targets = load_org_targets("_all")
            total_target = sum(org_targets.values()) if org_targets else 0
        else:
            total_target = sum(st.session_state.target_dict.values())

        with st.spinner("加载 KPI 数据..."):
            df_today = fetch_sales_summary(latest_date, latest_date, suffix)
            df_mtd = fetch_sales_summary(month_start, latest_date, suffix)

        if df_today.empty:
            st.warning(f"所选日期 {latest_date} 无销售数据，以下显示月累计数据。")
            today_ship = 0
            today_return = 0
            today_net = 0
        else:
            today_ship = df_today['total_ship'].sum()
            today_return = df_today['total_return'].sum()
            today_net = df_today['total_net'].sum()

        if not df_mtd.empty:
            mtd_ship = df_mtd['total_ship'].sum()
            mtd_return = df_mtd['total_return'].sum()
            mtd_net = df_mtd['total_net'].sum()
            mtd_return_rate = (mtd_return / (mtd_ship + 1e-5) * 100) if mtd_ship > 0 else 0
        else:
            mtd_ship = 0
            mtd_return = 0
            mtd_net = 0
            mtd_return_rate = 0

        # 计算目标完成率
        target_rate = (mtd_net / total_target * 100) if total_target > 0 else 0

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**📅 最新日（{latest_date.strftime('%Y-%m-%d')}）**")
            if df_today.empty:
                st.metric("净销售额", "无数据")
            else:
                st.metric("净销售额", f"¥{today_net:,.2f}",
                          delta=f"发货 ¥{today_ship:,.2f} | 退货 ¥{today_return:,.2f}")
        with col2:
            st.markdown(f"**📆 月累计（{latest_date.strftime('%Y-%m')}）**")
            st.metric("净销售额", f"¥{mtd_net:,.2f}",
                      delta=f"发货 ¥{mtd_ship:,.2f} | 退货 ¥{mtd_return:,.2f} | 退货率 {mtd_return_rate:.2f}%")
            # ---------- 新增：月目标完成率 ----------
            bar_color = "#4ade80" if target_rate >= 80 else "#fbbf24" if target_rate >= 50 else "#f87171"
            st.markdown(f"""
            <div style="margin-top:12px; padding-top:8px; border-top:1px solid #e2e8f0;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:14px; color:#475569; font-weight:500;">月目标完成率</span>
                    <span style="font-size:18px; font-weight:700; color:#0f172a;">{target_rate:.1f}%</span>
                </div>
                <div style="width:100%; height:6px; background:#e2e8f0; border-radius:3px; margin-top:6px; overflow:hidden;">
                    <div style="width:{min(target_rate,100)}%; height:100%; background:{bar_color}; border-radius:3px; transition:width 0.8s ease;"></div>
                </div>
                <div style="display:flex; justify-content:space-between; margin-top:4px;">
                    <span style="color:#64748b; font-size:13px;">目标 ¥{total_target:,.0f}</span>
                    <span style="color:#64748b; font-size:13px;">已达成 ¥{mtd_net:,.0f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # ======================== 2. 趋势分析（近7天 vs 前7天） ========================
        st.markdown("---")
        st.markdown("#### 📈 趋势分析：近7天 vs 前7天")

        period_start = base_date - timedelta(days=6)
        prev_period_start = base_date - timedelta(days=13)
        prev_period_end = base_date - timedelta(days=7)

        with st.spinner("加载趋势数据..."):
            df_7d = fetch_sales_summary(period_start, base_date, suffix)
            df_prev = fetch_sales_summary(prev_period_start, prev_period_end, suffix)

        st.markdown("##### 汇总统计")
        if not df_7d.empty and 'total_net' in df_7d.columns:
            total_7d = df_7d['total_net'].sum()
            total_prev = df_prev['total_net'].sum() if not df_prev.empty else 0
            change = ((total_7d - total_prev) / (total_prev + 1e-5) * 100) if total_prev != 0 else 0

            col_stat1, col_stat2, col_stat3 = st.columns(3)
            col_stat1.metric("近7天净销售额", f"¥{total_7d:,.2f}")
            col_stat2.metric("前7天净销售额", f"¥{total_prev:,.2f}")
            col_stat3.metric("环比变化", f"{change:+.2f}%",
                             delta="增长" if change >= 0 else "下降", delta_color="normal")
        else:
            st.info("近7天无数据，无法统计。")

        st.markdown("##### 每日趋势对比（近7天 vs 前7天同期）")
        if (not df_7d.empty and 'sale_date' in df_7d.columns and 
            not df_prev.empty and 'sale_date' in df_prev.columns):
            df_7d_daily = df_7d.groupby('sale_date')['total_net'].sum().reset_index()
            df_prev_daily = df_prev.groupby('sale_date')['total_net'].sum().reset_index()

            df_7d_daily['sale_date'] = pd.to_datetime(df_7d_daily['sale_date'])
            df_prev_daily['sale_date'] = pd.to_datetime(df_prev_daily['sale_date'])
            df_prev_daily['sale_date_aligned'] = df_prev_daily['sale_date'] + pd.Timedelta(days=7)

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_7d_daily['sale_date'],
                y=df_7d_daily['total_net'],
                mode='lines+markers',
                name='近7天',
                line=dict(color='#22c55e', width=2.5),
                marker=dict(size=6)
            ))
            fig.add_trace(go.Scatter(
                x=df_prev_daily['sale_date_aligned'],
                y=df_prev_daily['total_net'],
                mode='lines+markers',
                name='前7天（同期）',
                line=dict(color='#3b82f6', width=2.5, dash='dash'),
                marker=dict(size=6)
            ))
            fig.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=10, b=0),
                hovermode='x unified',
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                yaxis_title='净销售额 (¥)',
                xaxis_title='日期（近7天）',
                xaxis=dict(
                    tickformat='%m-%d',
                    range=[df_7d_daily['sale_date'].min(), df_7d_daily['sale_date'].max()]
                )
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("无足够数据绘制趋势图（需同时拥有近7天和前7天数据）。")

        # ======================== 3. 组织与部门拆解 ========================
        st.markdown("---")
        st.markdown("#### 🏆 阿米巴组织与部门业绩拆解")

        # ---------- 3.1 组织饼图 + 部门排行 ----------
        st.markdown("##### 组织与部门分布")
        time_mode_main = st.radio(
            "查看周期",
            options=["近7天", "月累计"],
            index=0,
            horizontal=True,
            key="org_dept_main_mode"
        )
        if time_mode_main == "近7天":
            start_date = base_date - timedelta(days=6)
            end_date = base_date
            period_label = "近7天"
        else:
            start_date = base_date.replace(day=1)
            end_date = base_date
            period_label = f"月累计（{base_date.strftime('%Y-%m')}）"

        with st.spinner(f"加载 {period_label} 数据..."):
            df_period_main = fetch_sales_summary(start_date, end_date, suffix)

        if not df_period_main.empty:
            col_org, col_dept = st.columns(2)
            with col_org:
                org_agg = df_period_main.groupby('org_name')['total_net'].sum().reset_index()
                positive_org = org_agg[org_agg['total_net'] > 0].copy()
                if not positive_org.empty:
                    fig_org = px.pie(positive_org, names='org_name', values='total_net',
                                     title=f'各阿米巴净销售额占比（{period_label}）',
                                     hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig_org.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig_org, use_container_width=True)
                else:
                    st.info("无盈利阿米巴")

            with col_dept:
                dept_agg = df_period_main.groupby('dept')['total_net'].sum().reset_index()
                dept_agg = dept_agg[dept_agg['total_net'] != 0].sort_values('total_net', ascending=False)
                if not dept_agg.empty:
                    top10 = dept_agg.head(10)
                    fig_dept = px.bar(top10, x='total_net', y='dept', orientation='h',
                                      title=f'部门净销售额排行（TOP10，{period_label}）',
                                      labels={'total_net': '净销售额', 'dept': '渠道'},
                                      color='total_net', color_continuous_scale='Blues')
                    fig_dept.update_layout(yaxis={'categoryorder': 'total ascending'})
                    st.plotly_chart(fig_dept, use_container_width=True)
                else:
                    st.info("无渠道数据")
        else:
            st.warning(f"{period_label} 无数据，无法显示阿米巴/渠道分布。")

        # ---------- 3.2 退货率警告线 ----------
        st.markdown("#### 退货率警告线")
        time_mode_return = st.radio(
            "查看周期",
            options=["近7天", "月累计"],
            index=0,
            horizontal=True,
            key="org_dept_return_mode",
            label_visibility="collapsed"
        )
        if time_mode_return == "近7天":
            start_date_r = base_date - timedelta(days=6)
            end_date_r = base_date
            period_label_r = "近7天"
        else:
            start_date_r = base_date.replace(day=1)
            end_date_r = base_date
            period_label_r = f"月累计（{base_date.strftime('%Y-%m')}）"

        with st.spinner(f"加载退货率数据（{period_label_r}）..."):
            df_return = fetch_sales_summary(start_date_r, end_date_r, suffix)

        if not df_return.empty:
            dept_return = df_return.groupby('dept').agg(
                ship=('total_ship', 'sum'),
                return_amt=('total_return', 'sum')
            ).reset_index()
            dept_return['退货率'] = (dept_return['return_amt'] / (dept_return['ship'] + 1e-5) * 100).round(2)
            dept_return = dept_return[dept_return['ship'] > 0]
            if not dept_return.empty:
                top_return = dept_return.sort_values('退货率', ascending=False).head(10)
                fig_return = px.bar(top_return, x='dept', y='退货率',
                                    title=f'退货率 TOP10 部门（{period_label_r}）',
                                    labels={'dept': '部门', '退货率': '退货率 (%)'},
                                    color=top_return['退货率'], color_continuous_scale='RdYlGn_r')
                fig_return.add_hline(y=50, line_dash="dash", line_color="red", annotation_text="警戒线 50%")
                fig_return.add_hline(y=30, line_dash="dash", line_color="orange", annotation_text="注意线 30%")
                st.plotly_chart(fig_return, use_container_width=True)
            else:
                st.info("无有效渠道数据")
        else:
            st.warning(f"{period_label_r} 无数据，无法显示退货率。")

        # ---------- 3.3 多维透视 ----------
        st.markdown("#### 🔍 多维透视（渠道 → 平台 → 店铺）")
        time_mode_pivot = st.radio(
            "查看周期",
            options=["近7天", "月累计"],
            index=0,
            horizontal=True,
            key="org_dept_pivot_mode",
            label_visibility="collapsed"
        )
        if time_mode_pivot == "近7天":
            start_date_p = base_date - timedelta(days=6)
            end_date_p = base_date
            period_label_p = "近7天"
        else:
            start_date_p = base_date.replace(day=1)
            end_date_p = base_date
            period_label_p = f"月累计（{base_date.strftime('%Y-%m')}）"

        with st.spinner(f"加载透视数据（{period_label_p}）..."):
            df_pivot = fetch_sales_summary(start_date_p, end_date_p, suffix)

        if not df_pivot.empty:
            df_pivot['platform'] = df_pivot['shop_name'].apply(
                lambda x: '天猫' if x.startswith('天猫') else '小红书' if x.startswith('小红书') else '抖音' if x.startswith('抖音') else '视频号' if x.startswith('视频号') else '其他'
            )
            grouped = df_pivot.groupby(['org_name', 'platform', 'shop_name']).agg(
                ship=('total_ship', 'sum'),
                return_amt=('total_return', 'sum'),
                net=('total_net', 'sum')
            ).reset_index()
            grouped['退货率'] = (grouped['return_amt'] / (grouped['ship'] + 1e-5) * 100).round(2).map(lambda x: f"{x:.2f}%")

            org_order = grouped.groupby('org_name')['net'].sum().sort_values(ascending=False).index
            for org in org_order:
                org_data = grouped[grouped['org_name'] == org]
                org_net = org_data['net'].sum()
                org_ship = org_data['ship'].sum()
                org_return = org_data['return_amt'].sum()
                with st.expander(f"🏢 {org}  | 净额 ¥{org_net:,.2f} | 发货 ¥{org_ship:,.2f} | 退货 ¥{org_return:,.2f}"):
                    platform_order = org_data.groupby('platform')['net'].sum().sort_values(ascending=False).index
                    for plat in platform_order:
                        plat_data = org_data[org_data['platform'] == plat]
                        plat_net = plat_data['net'].sum()
                        plat_ship = plat_data['ship'].sum()
                        plat_return = plat_data['return_amt'].sum()
                        with st.expander(f"📱 {plat}  净额 ¥{plat_net:,.2f}（发货 ¥{plat_ship:,.2f} / 退货 ¥{plat_return:,.2f}）"):
                            display_df = plat_data[['shop_name', 'ship', 'return_amt', 'net', '退货率']]
                            display_df.columns = ['店铺', '发货额', '退货额', '净销售额', '退货率']
                            display_df = display_df.sort_values('净销售额', ascending=False)
                            st.dataframe(display_df, hide_index=True, use_container_width=True)
        else:
            st.warning(f"{period_label_p} 无数据，无法显示透视表。")

        # ---------- 3.4 异常预警 ----------
        st.markdown("---")
        st.markdown("#### ⚠️ 异常决策预警")
        if not df_period_main.empty:
            alert_df = df_period_main.groupby(['org_name', 'dept', 'shop_name']).agg(
                ship=('total_ship', 'sum'),
                return_amt=('total_return', 'sum'),
                net=('total_net', 'sum')
            ).reset_index()
            alert_df['退货率'] = (alert_df['return_amt'] / (alert_df['ship'] + 1e-5) * 100)
            alert_negative = alert_df[alert_df['net'] < 0]
            alert_high_return = alert_df[alert_df['退货率'] > 65]

            if not alert_negative.empty:
                for _, row in alert_negative.iterrows():
                    st.error(f"🚨 净销售额为负：{row['org_name']} -> {row['dept']} -> {row['shop_name']}，净额 ¥{row['net']:,.2f}")
            if not alert_high_return.empty:
                for _, row in alert_high_return.iterrows():
                    st.warning(f"⚠️ 退货率异常偏高（>{65}%）：{row['org_name']} -> {row['dept']} -> {row['shop_name']}，退货率 {row['退货率']:.1f}%")
            if alert_negative.empty and alert_high_return.empty:
                st.success("🎉 所有部门/店铺运营正常，无重大异常。")
        else:
            st.info("当前周期无数据，无法预警。")

        # ======================== 4. AI 智能总结 ========================
        st.markdown("---")
        st.markdown("#### 🤖 AI 智能总结")

        model_options = {
            "DeepSeek-V3": "deepseek-ai/DeepSeek-V3",
            "DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
            "Qwen2.5-72B": "Qwen/Qwen2.5-72B-Instruct",
            "Qwen2.5-7B": "Qwen/Qwen2.5-7B-Instruct",
            "GLM-4-9B": "glm-4-9b-chat"
        }
        selected_model_name = st.selectbox(
            "选择 AI 模型",
            options=list(model_options.keys()),
            index=1,
            key="org_ai_model_select"
        )
        selected_model = model_options[selected_model_name]

        if st.button("🚀 生成智能总结", key="org_generate_ai_summary"):
            total_net = mtd_net if not df_mtd.empty else 0
            return_rate = mtd_return_rate if not df_mtd.empty else 0
            if not df_7d.empty and not df_prev.empty:
                total_7d = df_7d['total_net'].sum()
                total_prev = df_prev['total_net'].sum() if not df_prev.empty else 0
                change_7d = ((total_7d - total_prev) / (total_prev + 1e-5) * 100) if total_prev != 0 else 0
                net_7d = total_7d
                net_prev = total_prev
            else:
                net_7d = 0
                net_prev = 0
                change_7d = 0

            if not df_period_main.empty:
                org_net = df_period_main.groupby('org_name')['total_net'].sum().sort_values(ascending=False).head(3)
                org_text = "\n".join([f"{i+1}. {org}: ¥{amt:,.0f}" for i, (org, amt) in enumerate(org_net.items())]) if not org_net.empty else "暂无"
            else:
                org_text = "暂无"

            if not df_period_main.empty:
                dept_return_ai = df_period_main.groupby('dept').agg(ship=('total_ship', 'sum'), return_amt=('total_return', 'sum')).reset_index()
                dept_return_ai['退货率'] = (dept_return_ai['return_amt'] / (dept_return_ai['ship'] + 1e-5) * 100)
                dept_return_ai = dept_return_ai.sort_values('退货率', ascending=False).head(3)
                dept_text = "\n".join([f"{row['dept']}: {row['退货率']:.1f}%" for _, row in dept_return_ai.iterrows()]) if not dept_return_ai.empty else "暂无"
            else:
                dept_text = "暂无"

            context = f"""
            分析期间（月累计）：{month_start} 至 {latest_date}
            总净销售额：¥{total_net:,.2f}
            综合退货率：{return_rate:.2f}%
            近7天净销售额：¥{net_7d:,.2f}（前7天：¥{net_prev:,.2f}，变化 {change_7d:+.1f}%）
            净销售额 TOP3 阿米巴：
            {org_text}
            退货率 TOP3 渠道：
            {dept_text}
            """

            prompt = """
            你是一位资深的电商运营总监。请根据以上数据，用一段专业、简洁的中文总结当前组织与部门的经营状况。
            要求：
            1. 突出表现最好的阿米巴和最需要关注的渠道。
            2. 结合近7天趋势，给出短期策略建议。
            3. 若发现异常（如退货率极高、净额下滑），明确指出来。
            """

            with st.spinner("🤖 AI 正在分析，请稍候..."):
                ai_summary = get_ai_summary(prompt, context, selected_model)

            st.session_state.org_ai_summary = ai_summary
            st.rerun()

        if st.session_state.get("org_ai_summary"):
            st.markdown(f"""
            <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);border-radius:12px;padding:16px 20px;margin-top:10px;">
                <div style="color:#1e293b;font-size:14px;line-height:1.7;">{st.session_state.org_ai_summary}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("点击上方按钮生成 AI 智能总结。")

# ========== 系统设置 ==========
if idx_system is not None:
    with tabs[idx_system]:
        st.subheader("👥 账号管理与权限设置（按数据源分别设置）")
        st.info("对每个子账号，可分别配置其在“非直播数据”、“直播数据”、“全部数据”下能看到的选项卡。")

        if st.button("🔄 重新从数据库加载账号"):
            st.session_state.sub_users = load_sub_accounts_from_db()
            st.success("已重新加载")
            st.rerun()

        if st.session_state.sub_users:
            for username, info in list(st.session_state.sub_users.items()):
                with st.expander(f"账号：{username}"):
                    st.markdown(f"**{username}** 的权限配置")
                    perms = info.get("permissions", {})
                    for suf in ["", "_live", "_all"]:
                        if suf not in perms:
                            perms[suf] = []
                    
                    suffix_display = {"": "非直播数据", "_live": "直播数据", "_all": "全部数据"}
                    
                    # ---- 使用 st.form 包裹配置，防止即时刷新 ----
                    with st.form(key=f"form_{username}"):
                        new_perms = {}
                        for suf, display_name in suffix_display.items():
                            # 构建选项列表：全部数据时额外添加“组织与部门分析”
                            if suf == "_all":
                                all_options = base_tabs + ["🏢 组织与部门分析"]
                            else:
                                all_options = base_tabs
                            # 默认选中当前权限
                            default_val = [tab for tab in perms.get(suf, []) if tab in all_options]
                            selected = st.multiselect(
                                f"{display_name} 允许的选项卡",
                                options=all_options,
                                default=default_val,
                                key=f"perm_{username}_{suf}"
                            )
                            new_perms[suf] = selected
                        
                        # 默认数据源
                        current_default = info.get("default_suffix", "")
                        default_options = {"非直播数据": "", "全部数据": "_all"}
                        default_display = [k for k, v in default_options.items() if v == current_default]
                        default_display = default_display[0] if default_display else "非直播数据"
                        new_default_display = st.selectbox(
                            "默认数据源",
                            options=list(default_options.keys()),
                            index=list(default_options.keys()).index(default_display),
                            key=f"default_suffix_{username}"
                        )
                        new_default = default_options[new_default_display]

                        # 数据过滤权限
                        st.markdown("**数据过滤权限**")
                        platform_options = ["all", "抖音", "视频号"]
                        current_platform = info.get("filter_platform", "all")
                        new_platform = st.selectbox(
                            "限制平台（all=全部）",
                            options=platform_options,
                            index=platform_options.index(current_platform) if current_platform in platform_options else 0,
                            key=f"platform_{username}"
                        )
                        
                        # 获取所有店铺/主播名称（用于过滤）
                        @st.cache_data(ttl=600)
                        def get_all_shop_names():
                            df = load_product_sales(apply_filter=False)
                            if df.empty:
                                return []
                            if st.session_state.table_suffix == "_all":
                                if "anchor" in df.columns:
                                    return sorted(df["anchor"].dropna().unique().tolist())
                                else:
                                    return []
                            else:
                                if "shop_name" in df.columns:
                                    return sorted(df["shop_name"].dropna().unique().tolist())
                                else:
                                    return []
                        all_shop_names = get_all_shop_names()
                        current_shop_names = info.get("filter_shop_names", [])
                        current_shop_names = [name for name in current_shop_names if name in all_shop_names]
                        new_shop_names = st.multiselect(
                            "限制店铺/主播（空表示全部）",
                            options=all_shop_names,
                            default=current_shop_names,
                            key=f"shops_{username}"
                        )

                        # 提交按钮：保存所有权限
                        submitted = st.form_submit_button("💾 保存全部权限")
                        if submitted:
                            st.session_state.sub_users[username]["permissions"] = new_perms
                            st.session_state.sub_users[username]["default_suffix"] = new_default
                            st.session_state.sub_users[username]["filter_platform"] = new_platform
                            st.session_state.sub_users[username]["filter_shop_names"] = new_shop_names
                            ok, msg = save_sub_account_to_db(username, st.session_state.sub_users[username])
                            if ok:
                                st.success(f"权限已保存到数据库")
                            else:
                                st.error(f"保存失败：{msg}")
                    
                    # 删除按钮（放在表单外部，单独操作）
                    if st.button(f"删除账号", key=f"del_{username}"):
                        ok, msg = delete_sub_account_from_db(username)
                        if ok:
                            del st.session_state.sub_users[username]
                            st.success(f"账号 {username} 已删除")
                            st.rerun()
                        else:
                            st.error(f"删除失败：{msg}")
        else:
            st.info("暂无子账号")
        
        with st.expander("➕ 创建新子账号"):
            col1, col2 = st.columns(2)
            with col1:
                new_username = st.text_input("用户名", key="new_username_sys")
                new_password = st.text_input("密码", type="password", key="new_password_sys")
            with col2:
                default_suffix = st.selectbox("默认数据源", ["非直播数据", "全部数据"], key="new_default_suffix_sys")
                suffix_map = {"非直播数据": "", "全部数据": "_all"}
                default_perms = {}
                for suf in ["", "_live", "_all"]:
                    if suf == "_all":
                        default_perms[suf] = base_tabs + ["🏢 组织与部门分析"]
                    else:
                        default_perms[suf] = base_tabs
                default_platform = "all"
            if st.button("创建子账号", key="create_sys"):
                if new_username and new_password:
                    if new_username in st.session_state.sub_users:
                        st.error("用户名已存在")
                    else:
                        new_info = {
                            "password": new_password,
                            "role": "viewer",
                            "default_suffix": suffix_map[default_suffix],
                            "permissions": default_perms,
                            "filter_platform": default_platform,
                            "filter_shop_names": []
                        }
                        ok, msg = save_sub_account_to_db(new_username, new_info)
                        if ok:
                            st.session_state.sub_users[new_username] = new_info
                            st.success(f"子账号 {new_username} 创建成功（已保存到数据库）")
                            st.rerun()
                        else:
                            st.error(f"创建失败：{msg}")

# ========== 商品库导出 ==========
if idx_export is not None:
    with tabs[idx_export]:
        st.subheader("📚 导出商品库数据（product_master）")
        master_df = load_product_master()
        if master_df.empty:
            st.warning("商品库（product_master）为空，无法导出。")
        else:
            st.write(f"当前商品库共有 **{len(master_df)}** 条记录。")
            with st.expander("点击预览商品库数据"):
                st.dataframe(master_df.head(10), use_container_width=True)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                master_df.to_excel(writer, index=False)
            st.download_button(
                label="📥 导出全部商品库数据 (Excel)",
                data=output.getvalue(),
                file_name=f"product_master_{date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
