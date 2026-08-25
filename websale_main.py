# -*- coding: utf-8 -*-
"""
订单业绩统计工具 - 多页应用入口（标准导航版）
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
from core.db import init_supabase, get_table_name, load_product_sales, load_product_master, load_dimension_mapping, save_org_targets
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
    /* 固定导航侧栏，主体区域独立占用剩余宽度 */
    section[data-testid="stSidebar"] {
        width: 280px !important;
        min-width: 280px !important;
        max-width: 280px !important;
        flex: 0 0 280px !important;
    }
    section[data-testid="stSidebar"] > div {
        width: 280px !important;
        min-width: 280px !important;
    }
    div[data-testid="stAppViewContainer"] .main {
        min-width: 0 !important;
        flex: 1 1 auto !important;
    }
    div[data-testid="stAppViewContainer"] .main .block-container {
        width: 100% !important;
        max-width: none !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
    }
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
                    perms = {"": row["allowed_tabs"], "_all": row["allowed_tabs"]}
                sub_users[row["username"]] = {
                    "password": row["password"],
                    "role": row.get("role", "viewer"),
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
            "default_suffix": "_all",  # 兼容数据库现有字段
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
        "admin": {"password": "1234567890", "role": "admin"},
        "XDZ01": {"password": "94949468", "role": "user"},
        "ZBZ01": {"password": "123456", "role": "user"}
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
                # 系统现在只有一个统一数据源
                st.session_state.table_suffix = "_all"
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
if "target_dict" not in st.session_state:
    st.session_state.target_dict = {}
if "uploaded_file_hash" not in st.session_state:
    st.session_state.uploaded_file_hash = None
if "processing_upload" not in st.session_state:
    st.session_state.processing_upload = False
st.session_state.table_suffix = "_all"
if "uploaded_file_hashes" not in st.session_state:
    st.session_state.uploaded_file_hashes = []

# ========== 辅助函数 ==========
def refresh_materialized_view(suffix=""):
    if supabase is None:
        return
    try:
        supabase.rpc('refresh_mv', {'suffix': suffix}).execute()
    except Exception:
        # 物化视图仅供外部预聚合/BI 使用，lunkuo 自身所有查询都直接走源表，不读取它；
        # 刷新失败（如 statement timeout）不影响任何页面数据，静默忽略即可。
        pass

# daily_sales 表已废弃，所有页面直接从 product_sales 查询聚合

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
        master_cols = ["style_code", "image_url", "category", "has_newbie_coupon"]
        master_subset = master_df.copy()
        for col in master_cols:
            if col not in master_subset.columns:
                master_subset[col] = None if col != "has_newbie_coupon" else False
        master_subset = master_subset.drop_duplicates("style_code", keep="last")
        master_map = {
            row["style_code"]: {
                "image_url": row["image_url"],
                "master_category": row["category"],
                "has_newbie_coupon": bool(row["has_newbie_coupon"]),
            }
            for row in master_subset[master_cols].to_dict(orient="records")
        }

    table_name = get_table_name("product_sales", suffix)
    use_anchor = True
    try:
        supabase.table(table_name).select("anchor_name").limit(1).execute()
    except Exception as e:
        if "does not exist" in str(e).lower() or "column" in str(e).lower():
            use_anchor = False
        else:
            raise

    temp_records = {}
    for row in df_orders.to_dict(orient="records"):
        remark = row["备注"]
        parsed = parse_product_code(remark)
        if parsed is None:
            continue
        amount = float(row["金额/时间"])
        short_code = parsed["style_code"]
        img = master_map.get(short_code, {}).get("image_url")
        cat = master_map.get(short_code, {}).get("master_category")
        anchor_name = extract_anchor(remark) or "NONE"

        if remark not in temp_records:
            rec = {
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
            if use_anchor:
                rec["anchor_name"] = anchor_name
            temp_records[remark] = rec
        else:
            existing = temp_records[remark]
            existing["ship_amount"] += max(amount, 0)
            existing["return_amount"] += max(-amount, 0)
            existing["net_amount"] += amount
            if use_anchor and existing.get("anchor_name") in [None, "", "NONE"] and anchor_name not in [None, "", "NONE"]:
                existing["anchor_name"] = anchor_name

    records = list(temp_records.values())
    if records:
        batch_size = 500
        for i in range(0, len(records), batch_size):
            batch = records[i:i+batch_size]
            supabase.table(table_name).upsert(batch, on_conflict="remark").execute()

def save_offline_sales(df_orders):
    """保存线下收入，返回实际写入条数（0 表示无数据/空行被过滤）

    去重策略：以 remark（订单号）为唯一键，重复时覆盖更新——
    同一文件内后出现的覆盖先出现的；数据库已存在的 remark 则更新最早一条、
    删除多余重复记录，避免历史重复继续累积。
    """
    if supabase is None or df_orders.empty:
        return 0
    df = df_orders.copy()
    # 过滤掉日期为空的空行（当天无业绩时，润乾导出的是全空行）
    if '日期' in df.columns:
        df = df[df['日期'].notna()]
    if df.empty:
        return 0
    df['sale_date'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')
    df['shop_name'] = df['组织名称'].astype(str).str.strip()
    df['amount'] = pd.to_numeric(df['金额/时间'], errors='coerce').fillna(0)
    df['ship_amount'] = df['amount'].clip(lower=0)
    df['return_amount'] = (-df['amount']).clip(lower=0)
    df['net_amount'] = df['amount']
    df['remark'] = df['备注'].astype(str).str.strip()
    # 清理 NaN 为 None，避免 JSON 序列化报错
    df = df[['sale_date', 'shop_name', 'ship_amount', 'return_amount', 'net_amount', 'remark']]
    df = df.where(pd.notna(df), None)
    records = df.to_dict(orient='records')
    if not records:
        return 0

    # 同一文件内按 remark 去重（后出现的覆盖先出现的）
    merged = {}
    for rec in records:
        merged[rec['remark']] = rec
    records = list(merged.values())

    table_name = "offline_sales_all"
    remarks = [r['remark'] for r in records]

    # 查询数据库中已存在的 remark -> [id, ...]，用于判断是否需要覆盖更新
    existing = {}
    for i in range(0, len(remarks), 200):
        chunk = remarks[i:i+200]
        resp = supabase.table(table_name).select('id,remark').in_('remark', chunk).execute()
        for r in (resp.data or []):
            existing.setdefault(r['remark'], []).append(r['id'])

    to_insert = []       # 全新记录
    to_update = []       # (保留的 id, 新数据) 覆盖更新
    to_delete_ids = []   # 多余重复记录的 id
    for rec in records:
        rm = rec['remark']
        ids = existing.get(rm)
        if not ids:
            to_insert.append(rec)
        else:
            ids_sorted = sorted(ids)
            keep_id = ids_sorted[0]  # 保留最早一条（id 最小）
            to_update.append((keep_id, rec))
            for extra_id in ids_sorted[1:]:
                to_delete_ids.append(extra_id)

    # 插入新记录
    if to_insert:
        for i in range(0, len(to_insert), 500):
            supabase.table(table_name).insert(to_insert[i:i+500]).execute()
    # 覆盖更新已存在记录（remark 为键，值不变，故从 payload 中剔除）
    for keep_id, rec in to_update:
        update_payload = {k: v for k, v in rec.items() if k != 'remark'}
        supabase.table(table_name).update(update_payload).eq('id', keep_id).execute()
    # 删除多余重复记录
    if to_delete_ids:
        for i in range(0, len(to_delete_ids), 500):
            supabase.table(table_name).delete().in_('id', to_delete_ids[i:i+500]).execute()

    refresh_materialized_view("_all")
    return len(records)

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
        # 上传后清除缓存并刷新目标
        if suffix == st.session_state.get("table_suffix", ""):
            st.session_state.target_dict = load_targets(suffix)
        latest_date = df_valid["日期"].max().strftime('%Y-%m-%d') if not df_valid.empty else "无数据"
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

# ========== 数据版本号（用于智能刷新缓存） ==========
# 上传新数据时递增此版本号，页面切换时版本号不变则保留缓存
if "_data_version" not in st.session_state:
    st.session_state._data_version = 0
if "_cache_version" not in st.session_state:
    st.session_state._cache_version = -1

def mark_data_changed():
    """数据变更后调用：清缓存 + 递增版本号"""
    st.cache_data.clear()
    st.session_state._data_version += 1
    st.session_state._cache_version = st.session_state._data_version

# ========== 页面初始化 ==========
if st.session_state.target_dict == {}:
    st.session_state.target_dict = load_targets("_all")

# ========== 构建导航页面（根据权限动态显示） ==========
from streamlit import navigation, Page

all_pages = {
    "🏠 主页": "pages/home.py",
    "📊 经营驾驶舱": "pages/dashboard.py",
    "📋 每日明细": "pages/daily_detail.py",
    "📦 商品分析": "pages/product_page.py",
    "📊 商品分析助手": "pages/product_assistant.py",   # 新增
    "🎤 主播分析": "pages/anchor.py",
    "📈 销售分布与品牌": "pages/distribution.py",
    "🏢 组织与部门分析": "pages/org_dept.py",
    "📚 商品信息管理": "pages/export.py",
    "⚙️ 系统设置": "pages/settings.py",
}

role = st.session_state.role
username = st.session_state.username
current_suffix = "_all"

if role == "admin":
    allowed_labels = list(all_pages.keys())
else:
    user_info = st.session_state.sub_users.get(username, {})
    perms = user_info.get("permissions", {})
    allowed = perms.get(current_suffix, [])
    if not allowed and "" in perms:
        allowed = perms[""]
    allowed_labels = allowed

pages_to_show = []
for label, path in all_pages.items():
    if label == "⚙️ 系统设置" and role != "admin":
        continue
    if label == "🏢 组织与部门分析" and current_suffix != "_all":
        continue
    if label == "🎤 主播分析" and current_suffix != "_all":
        continue
    # 新页面添加任何特殊限制（例如只在全部数据源显示）可在此添加
    # 但商品分析助手不限数据源，所以不需要额外条件
    if label == "🏠 主页" or label in allowed_labels:
        pages_to_show.append(Page(path, title=label, default=(label == "🏠 主页")))

# ... 其余部分不变

if not pages_to_show:
    pages_to_show = [
        Page("pages/home.py", title="🏠 主页", default=True),
        Page("pages/dashboard.py", title="📊 经营驾驶舱"),
        Page("pages/daily_detail.py", title="📋 每日明细"),
        Page("pages/product_page.py", title="📦 商品分析"),
    ]

# 页面执行前注册管理员工具回调，供系统设置页复用
st.session_state["_admin_callbacks"] = {
    "process_uploaded_file": process_uploaded_file,
    "load_target_file": load_target_file,
    "save_offline_sales": save_offline_sales,
    "save_org_targets": save_org_targets,
    "load_targets": load_targets,
    "clear_targets": clear_targets,
    "mark_data_changed": mark_data_changed,
    "manage_newbie_coupon": manage_newbie_coupon,
    "batch_manage_newbie_coupon": batch_manage_newbie_coupon,
}

nav = st.navigation(pages_to_show, position="sidebar")
nav.run()

# ========== 侧边栏额外内容 ==========
with st.sidebar:
    # ===== 显示当前登录用户 =====
    st.markdown(f"**👤 {st.session_state.username}** ({st.session_state.role})")
    st.markdown("---")

    if True:
        # 管理功能已迁移到系统设置，侧栏仅保留退出登录
        if st.button("🚪 退出登录", key="logout_final"):
            st.session_state.authenticated = False
            for key in ["username", "role", "table_suffix"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    else:
        # 管理员完整侧边栏
        st.sidebar.markdown("---")
        st.sidebar.markdown("[🏠 主页](/)")
        st.sidebar.markdown("---")
        st.header("📂 文件上传")

        # 上传成功后清除文件选择器：Streamlit 禁止在 widget 实例化后直接改其 session_state，
        # 所以这里用标记记录，在下一轮 file_uploader 实例化之前统一清除。
        _pending_clear = st.session_state.pop("_pending_clear_uploader", None)
        if _pending_clear:
            st.session_state.pop(_pending_clear, None)

        def handle_multiple_upload(uploaded_files, suffix, file_type="order", uploader_key=None):
            if st.session_state.processing_upload:
                st.warning("上一个文件正在处理中，请稍后...")
                return
            if not uploaded_files:
                st.warning("请先选择文件")
                return
            total_success = 0
            total_fail = 0
            results = []
            progress_bar = st.progress(0, text="0%")
            status_text = st.empty()
            total_files = len(uploaded_files)
            for i, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"正在处理: {uploaded_file.name} ({i+1}/{total_files}) — {int(i/total_files*100)}%")
                file_content = uploaded_file.getvalue()
                file_hash = hashlib.md5(file_content).hexdigest()
                if file_type == "order" and file_hash in st.session_state.uploaded_file_hashes:
                    results.append(f"⏭️ {uploaded_file.name}: 已上传过，跳过")
                    progress_bar.progress((i + 1) / total_files, text=f"{int((i + 1) / total_files * 100)}%")
                    continue
                try:
                    uploaded_file.seek(0)
                    file_bytes = io.BytesIO(file_content)
                    if file_type == "order":
                        ok, msg = process_uploaded_file(file_bytes, suffix)
                        if ok:
                            st.session_state.uploaded_file_hashes.append(file_hash)
                            total_success += 1
                            results.append(f"✅ {uploaded_file.name}: {msg}")
                        else:
                            total_fail += 1
                            results.append(f"❌ {uploaded_file.name}: {msg}")
                    else:
                        ok, msg = load_target_file(file_bytes, suffix)
                        if ok:
                            total_success += 1
                            results.append(f"✅ {uploaded_file.name}: {msg}")
                        else:
                            total_fail += 1
                            results.append(f"❌ {uploaded_file.name}: {msg}")
                except Exception as e:
                    total_fail += 1
                    results.append(f"❌ {uploaded_file.name}: 处理异常 - {str(e)}")
                progress_bar.progress((i + 1) / total_files, text=f"{int((i + 1) / total_files * 100)}%")
            progress_bar.empty()
            status_text.empty()
            st.markdown("---")
            st.subheader(f"📊 处理完成：成功 {total_success}，失败 {total_fail}")
            for result in results:
                st.text(result)
            if total_success > 0:
                mark_data_changed()
                st.session_state.target_dict = load_targets(suffix)
                # 上传成功后清空文件选择器（通过标记，在下一轮 file_uploader 实例化前清除）
                if uploader_key:
                    st.session_state["_pending_clear_uploader"] = uploader_key
                time.sleep(0.3)
                st.rerun()
            else:
                st.warning("没有文件被成功处理，请检查文件格式和内容")

        st.subheader("📊 销售数据上传")
        uploaded_orders = st.file_uploader(
            "选择订单文件 (Excel)，支持多选", type=["xlsx", "xls"],
            key="order_uploader_all_multi", accept_multiple_files=True
        )
        if uploaded_orders and st.button("📤 确认上传", key="confirm_upload_all_multi"):
            handle_multiple_upload(uploaded_orders, "_all", "order", "order_uploader_all_multi")
        target_files = st.file_uploader(
            "选择目标文件 (Excel)，支持多选", type=["xlsx", "xls"],
            key="target_upload_all_multi", accept_multiple_files=True
        )
        if target_files and st.button("📤 确认上传目标", key="confirm_target_all_multi"):
            handle_multiple_upload(target_files, "_all", "target", "target_upload_all_multi")
        st.markdown("---")
        st.subheader("🏷️ 线下收入上传")
        uploaded_offline = st.file_uploader(
            "选择线下收入文件 (Excel)，支持多选", type=["xlsx", "xls"],
            key="offline_uploader_multi", accept_multiple_files=True
        )
        if uploaded_offline and st.button("📤 上传线下收入", key="upload_offline_multi"):
                try:
                    total_offline = 0
                    off_progress = st.progress(0, text="0%")
                    off_status = st.empty()
                    off_total = len(uploaded_offline)
                    for idx, off_file in enumerate(uploaded_offline):
                        off_status.text(f"正在处理: {off_file.name} ({idx+1}/{off_total}) — {int(idx/off_total*100)}%")
                        df = pd.read_excel(off_file, header=1)
                        required_cols = ["日期", "金额/时间", "备注", "组织名称"]
                        if not all(col in df.columns for col in required_cols):
                            st.error(f"文件 {off_file.name} 缺少必要列：{', '.join(required_cols)}")
                            off_progress.progress((idx + 1) / off_total, text=f"{int((idx + 1) / off_total * 100)}%")
                            continue
                        n = save_offline_sales(df)
                        total_offline += n
                        if n == 0:
                            st.info(f"⏭️ {off_file.name}: 无数据（当天无业绩），已跳过")
                        else:
                            st.info(f"✅ {off_file.name}: 上传 {n} 条记录")
                        off_progress.progress((idx + 1) / off_total, text=f"{int((idx + 1) / off_total * 100)}%")
                    off_progress.empty()
                    off_status.empty()
                    st.success(f"✅ 总共成功上传 {total_offline} 条线下收入记录")
                    if total_offline > 0:
                        mark_data_changed()
                    st.session_state["_pending_clear_uploader"] = "offline_uploader_multi"
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"上传失败：{e}")

        st.markdown("---")
        st.header("⚙️ 工具")
        st.markdown("---")
        st.subheader("📊 组织目标管理")
        if True:  # 单一数据源下始终显示组织目标管理
            uploaded_org_target = st.file_uploader(
                "上传组织目标文件 (Excel)，支持多选", type=["xlsx", "xls"],
                key="org_target_upload_multi", accept_multiple_files=True
            )
            if uploaded_org_target and st.button("📤 上传组织目标", key="upload_org_target_btn_multi"):
                try:
                    total_org = 0
                    org_progress = st.progress(0, text="0%")
                    org_status = st.empty()
                    org_total = len(uploaded_org_target)
                    for idx, org_file in enumerate(uploaded_org_target):
                        org_status.text(f"正在处理: {org_file.name} ({idx+1}/{org_total}) — {int(idx/org_total*100)}%")
                        df_target = pd.read_excel(org_file, header=None)
                        org_names = df_target.iloc[:, 0].astype(str).str.strip()
                        target_vals = pd.to_numeric(df_target.iloc[:, 1], errors='coerce')
                        target_dict = {}
                        for name, val in zip(org_names, target_vals):
                            if pd.notna(val) and name not in ["", "nan", "None"]:
                                target_dict[name] = val
                        save_org_targets(target_dict, "_all")
                        total_org += len(target_dict)
                        st.info(f"✅ {org_file.name}: 加载 {len(target_dict)} 个组织目标")
                        org_progress.progress((idx + 1) / org_total, text=f"{int((idx + 1) / org_total * 100)}%")
                    org_progress.empty()
                    org_status.empty()
                    st.success(f"✅ 总共加载 {total_org} 个组织目标")
                    if total_org > 0:
                        mark_data_changed()
                    st.session_state["_pending_clear_uploader"] = "org_target_upload_multi"
                    st.rerun()
                except Exception as e:
                    st.error(f"上传失败：{e}")

        template_df = pd.DataFrame({"店铺名称": ["示例店铺A", "示例店铺B"], "目标金额": [100000, 200000]})
        template_bytes = io.BytesIO()
        with pd.ExcelWriter(template_bytes, engine='openpyxl') as writer:
            template_df.to_excel(writer, index=False)
        st.download_button("📄 下载目标模板", data=template_bytes.getvalue(), file_name="目标模板.xlsx", key="download_template_final")

        if st.button("🔄 重置上传记录（允许重新上传相同文件）", key="reset_upload_hashes"):
            st.session_state.uploaded_file_hashes = []
            st.success("已重置上传记录，现在可以重新上传相同文件")
            st.rerun()
        if st.button("🗑️ 清除当前用户的目标记忆", key="clear_targets_final"):
            clear_targets(st.session_state.table_suffix)
        if st.button("🔄 强制刷新所有数据", key="force_refresh_final"):
            mark_data_changed()
            st.rerun()
        st.markdown("---")
        with st.expander("🏷️ 单商品礼金标签管理"):
            manage_newbie_coupon()
        with st.expander("📦 批量礼金标签管理"):
            batch_manage_newbie_coupon()

        st.markdown("---")
        if st.button("🚪 退出登录", key="logout_admin"):
            st.session_state.authenticated = False
            for key in ["username", "role", "table_suffix"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

# ========== 主内容区（根路径欢迎信息） ==========
if False:  # 主页内容由 pages/home.py 负责
    st.markdown("""
    <div style="display: flex; justify-content: center; align-items: center; height: 50vh; flex-direction: column;">
        <h1 style="color: #1e293b;">📊 欢迎使用数据罗盘</h1>
        <p style="color: #475569; font-size: 18px;">请从左侧导航栏选择一个功能页面开始分析。</p>
    </div>
    """, unsafe_allow_html=True)

# ========== 保存组织目标（辅助函数） ==========
def save_org_targets(target_dict, suffix=None):
    if supabase is None:
        return
    records = [{"org_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        table_name = get_table_name("arg_targets", suffix)
        supabase.table(table_name).upsert(records, on_conflict="org_name").execute()
