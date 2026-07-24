# core/utils.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import re
from datetime import date, timedelta

# ---------- 从备注提取主播 ----------
def extract_anchor(remark):
    """从备注中提取主播名称，格式：主播：xxx 或 主播:xxx"""
    if not isinstance(remark, str):
        return None
    match = re.search(r'主播[：:]([^_]+)', remark)
    if match:
        return match.group(1).strip()
    # 尝试其他格式
    match2 = re.search(r'主播\s*[:：]\s*([^\s_]+)', remark)
    if match2:
        return match2.group(1).strip()
    return None

# ---------- 解析商品编码 ----------
def parse_product_code(remark):
    """
    从备注中解析商品编码，返回字典
    格式示例：L262Y050-黑-S
    """
    if not isinstance(remark, str):
        return None
    # 简单解析，根据实际格式调整
    parts = remark.split('-')
    if len(parts) < 3:
        return None
    code = parts[0].strip()
    color = parts[1].strip() if len(parts) > 1 else ''
    size = parts[2].strip() if len(parts) > 2 else ''
    # 进一步解析 code 获取品牌、年份、季节等
    # 根据实际逻辑调整，以下为示例
    brand = code[:2] if len(code) >= 2 else ''
    year = code[1:3] if len(code) >= 3 else ''
    season = code[3] if len(code) >= 4 else ''
    category = code[4] if len(code) >= 5 else ''
    style = code[5:8] if len(code) >= 8 else ''
    color_code = color
    size_code = size
    style_code = code
    return {
        "product_code": code,
        "style_code": style_code,
        "brand": brand,
        "year": year,
        "season": season,
        "category": category,
        "style": style,
        "color_code": color_code,
        "size": size_code
    }

# ---------- 日期快捷按钮 ----------
def date_quick_buttons(start_key, end_key, default_start=None, default_end=None, min_date=None, max_date=None):
    """在页面上生成日期快捷按钮和日期选择器"""
    # 初始化 session_state 中的日期
    if start_key not in st.session_state:
        st.session_state[start_key] = default_start or (min_date if min_date else date.today() - timedelta(days=30))
    if end_key not in st.session_state:
        st.session_state[end_key] = default_end or (max_date if max_date else date.today())
    
    cols = st.columns([1, 2, 1, 2, 1])
    with cols[0]:
        if st.button("今日", key=f"today_{start_key}"):
            st.session_state[start_key] = date.today()
            st.session_state[end_key] = date.today()
            st.rerun()
    with cols[1]:
        st.date_input("开始", value=st.session_state[start_key], min_value=min_date, max_value=max_date, key=start_key)
    with cols[2]:
        if st.button("近7天", key=f"week_{start_key}"):
            st.session_state[end_key] = date.today()
            st.session_state[start_key] = date.today() - timedelta(days=7)
            st.rerun()
    with cols[3]:
        st.date_input("结束", value=st.session_state[end_key], min_value=min_date, max_value=max_date, key=end_key)
    with cols[4]:
        if st.button("本月", key=f"month_{start_key}"):
            today = date.today()
            st.session_state[end_key] = today
            st.session_state[start_key] = today.replace(day=1)
            st.rerun()

# ---------- 数据权限过滤 ----------
def apply_data_permission(df):
    """根据当前用户的权限过滤数据（平台/店铺）"""
    if df.empty:
        return df
    username = st.session_state.get("username")
    if not username or username == "admin":
        return df  # 管理员或未登录，不过滤
    # 获取子账号权限
    sub_users = st.session_state.get("sub_users", {})
    user_info = sub_users.get(username, {})
    filter_platform = user_info.get("filter_platform", "all")
    filter_shops = user_info.get("filter_shop_names", [])
    # 如果未设置过滤，返回全部
    if filter_platform == "all" and not filter_shops:
        return df
    # 平台过滤
    if filter_platform != "all" and "shop_name" in df.columns:
        df = df[df["shop_name"].str.contains(filter_platform, case=False, na=False)]
    # 店铺/主播过滤
    if filter_shops:
        # 检测维度列：若是全部数据，可能用 anchor 或 shop_name
        if "anchor" in df.columns and df["anchor"].notna().any():
            df = df[df["anchor"].isin(filter_shops)]
        elif "shop_name" in df.columns:
            df = df[df["shop_name"].isin(filter_shops)]
    return df
