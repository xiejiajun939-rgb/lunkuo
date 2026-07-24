# -*- coding: utf-8 -*-
"""
订单业绩统计工具 - 多页应用入口（纯链接导航版）
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

# ========== 导入公共模块 ==========
from core.db import init_supabase, get_table_name, load_product_sales, load_product_master, load_dimension_mapping
from core.utils import extract_anchor, parse_product_code, date_quick_buttons, apply_data_permission
from core.ai import get_siliconflow_client, get_ai_summary

# 防抖
if "last_rerun" not in st.session_state:
    st.session_state.last_rerun = 0

def safe_rerun():
    now = time.time()
    if now - st.session_state.last_rerun > 0.5:
        st.session_state.last_rerun = now
        st.rerun()

st.set_page_config(
    page_title="业绩统计工具",
    layout="wide",
    page_icon="📊",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': None
    }
)

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

# ========== Supabase 连接 ==========
supabase = init_supabase()

# ========== 子账号数据库操作 ==========
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

# ========== 全局变量初始化 ==========
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
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""   # 默认非直播

# ========== 辅助函数 ==========
def refresh_materialized_view(suffix=""):
    if supabase is None:
        return
    try:
        supabase.rpc('refresh_mv', {'suffix': suffix}).execute()
    except Exception as e:
        st.warning(f"物化视图刷新失败（不影响数据入库）：{e}")

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

def update_product_master_flag(style_code, flag_value):
    if supabase is None:
        return False, "Supabase 未连接"
    try:
        resp = supabase.table("product_master").update({"has_newbie_coupon": flag_value}).eq("style_code", style_code).execute()
        return True, "更新成功"
    except Exception as e:
        return False, str(e)

# ========== 页面初始化（重建每日数据） ==========
rebuild_daily_data(st.session_state.table_suffix)
if st.session_state.target_dict == {}:
    st.session_state.target_dict = load_targets(st.session_state.table_suffix)

# ========== 侧边栏 ==========
with st.sidebar:
    # ========== 导航菜单（纯HTML链接，稳定可靠） ==========
    st.markdown("### 📌 导航")
    
    # 获取当前用户角色和权限
    role = st.session_state.role
    username = st.session_state.username
    user_info = st.session_state.sub_users.get(username, {})
    current_suffix = st.session_state.table_suffix

    # 主页链接
    st.sidebar.markdown("[🏠 主页](/)")
    
    if role == "admin":
        # 管理员显示全部页面
        st.sidebar.markdown("[📊 经营驾驶舱](/pages/dashboard)")
        st.sidebar.markdown("[📋 每日明细](/pages/daily_detail)")
        st.sidebar.markdown("[📦 商品分析](/pages/product_page)")
        st.sidebar.markdown("[🎤 主播分析](/pages/anchor)")
        st.sidebar.markdown("[📈 销售分布与品牌](/pages/distribution)")
        if current_suffix == "_all":
            st.sidebar.markdown("[🏢 组织与部门分析](/pages/org_dept)")
        st.sidebar.markdown("[📚 商品库导出](/pages/export)")
        st.sidebar.markdown("[⚙️ 系统设置](/pages/settings)")
    else:
        # 子账号：根据权限显示
        perms = user_info.get("permissions", {})
        allowed = perms.get(current_suffix, [])
        if not allowed and "" in perms:
            allowed = perms[""]
        page_map = {
            "📊 经营驾驶舱": "/pages/dashboard",
            "📋 每日明细": "/pages/daily_detail",
            "📦 商品分析": "/pages/product_page",
            "🎤 主播分析": "/pages/anchor",
            "📈 销售分布与品牌": "/pages/distribution",
            "🏢 组织与部门分析": "/pages/org_dept",
        }
        for label, path in page_map.items():
            if label == "🏢 组织与部门分析" and current_suffix != "_all":
                continue
            if label in allowed:
                st.sidebar.markdown(f"[{label}]({path})")
    st.markdown("---")

    # ---------- 数据加载 ----------
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

    # ---------- 文件上传与工具 ----------
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
        if st.session_state.table_suffix == "_all":
            st.markdown("---")
            st.subheader("📊 组织目标管理")
            uploaded_org_target = st.file_uploader("上传组织目标文件 (Excel)", type=["xlsx", "xls"], key="org_target_upload")
            if uploaded_org_target is not None:
                if st.button("📤 上传组织目标", key="upload_org_target_btn"):
                    try:
                        df_target = pd.read_excel(uploaded_org_target, header=None)
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
    
    # ========== 退出登录 ==========
    if st.button("🚪 退出登录", key="logout_final"):
        st.session_state.authenticated = False
        for key in ["username", "role", "table_suffix"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

# ========== 主内容区（欢迎信息） ==========
st.markdown("""
<div style="display: flex; justify-content: center; align-items: center; height: 50vh; flex-direction: column;">
    <h1 style="color: #1e293b;">📊 欢迎使用数据罗盘</h1>
    <p style="color: #475569; font-size: 18px;">请从左侧导航栏选择一个功能页面开始分析。</p>
    <p style="color: #94a3b8; font-size: 14px;">当前数据源：<strong>{}</strong></p>
</div>
""".format(current_source_name), unsafe_allow_html=True)

# ========== 保存组织目标（辅助函数） ==========
def save_org_targets(target_dict, suffix=None):
    if supabase is None:
        return
    records = [{"org_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        table_name = get_table_name("arg_targets", suffix)
        supabase.table(table_name).upsert(records, on_conflict="org_name").execute()
