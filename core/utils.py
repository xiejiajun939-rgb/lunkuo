# -*- coding: utf-8 -*-
"""
工具函数模块
包含：日期快捷按钮、主播提取、货号解析、数据权限过滤等
"""

import streamlit as st
import pandas as pd
import re
from datetime import date, timedelta

# ---------- 日期快捷按钮（修复版） ----------
def date_quick_buttons(start_key, end_key, default_start=None, default_end=None, min_date=None, max_date=None):
    """
    在 session_state 中设置日期快捷按钮（今日、近7天、本月）
    使用独立的 widget key，避免与 session_state 存储 key 冲突。
    """
    # 初始化 session_state 中的日期值（如果不存在）
    if start_key not in st.session_state:
        st.session_state[start_key] = default_start or date.today()
    if end_key not in st.session_state:
        st.session_state[end_key] = default_end or date.today()
    
    # 定义回调函数，当用户手动修改日期时，更新 session_state
    def on_start_change():
        new_val = st.session_state.get(f"{start_key}_widget")
        if new_val:
            st.session_state[start_key] = new_val
    def on_end_change():
        new_val = st.session_state.get(f"{end_key}_widget")
        if new_val:
            st.session_state[end_key] = new_val
    
    # 快捷按钮
    col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
    with col1:
        if st.button("📅 今日", key=f"quick_today_{start_key}"):
            today = date.today()
            if min_date and today < min_date:
                today = min_date
            if max_date and today > max_date:
                today = max_date
            st.session_state[start_key] = today
            st.session_state[end_key] = today
            st.rerun()
    with col2:
        if st.button("📆 近7天", key=f"quick_7days_{start_key}"):
            today = date.today()
            if max_date and today > max_date:
                today = max_date
            start = today - timedelta(days=6)
            if min_date and start < min_date:
                start = min_date
            st.session_state[start_key] = start
            st.session_state[end_key] = today
            st.rerun()
    with col3:
        if st.button("📆 本月", key=f"quick_month_{start_key}"):
            today = date.today()
            if max_date and today > max_date:
                today = max_date
            start = today.replace(day=1)
            if min_date and start < min_date:
                start = min_date
            st.session_state[start_key] = start
            st.session_state[end_key] = today
            st.rerun()
    with col4:
        col4_1, col4_2 = st.columns(2)
        with col4_1:
            st.date_input(
                "开始",
                value=st.session_state[start_key],
                key=f"{start_key}_widget",
                min_value=min_date,
                max_value=max_date,
                on_change=on_start_change,
                label_visibility="collapsed"
            )
        with col4_2:
            st.date_input(
                "结束",
                value=st.session_state[end_key],
                key=f"{end_key}_widget",
                min_value=min_date,
                max_value=max_date,
                on_change=on_end_change,
                label_visibility="collapsed"
            )

# ---------- 主播提取 ----------
def extract_anchor(remark):
    """从备注中提取主播名称（格式：主播：xxx）"""
    if not isinstance(remark, str):
        return None
    match = re.search(r'主播[：:]([^_]+)', remark)
    return match.group(1).strip() if match else None

# ---------- 货号解析 ----------
def parse_product_code(remark):
    """
    解析备注中的货号信息，返回字典：
    {
        "product_code": 完整商品编码,
        "style_code": 款式码（前8位）,
        "brand": 品牌,
        "year": 年份,
        "season": 季节,
        "category": 品类,
        "style": 款式,
        "color_code": 颜色代码,
        "size": 尺码
    }
    若解析失败返回 None
    """
    if not isinstance(remark, str):
        return None
    parts = remark.split('_')
    if len(parts) < 3:
        return None
    product_code = parts[0]
    if len(product_code) < 8:
        return None
    style_code = product_code[:8]
    brand = product_code[0] if len(product_code) > 0 else ''
    year = product_code[1:3] if len(product_code) > 3 else ''
    season_map = {"1": "春", "2": "夏", "3": "秋", "4": "冬"}
    season = season_map.get(product_code[3] if len(product_code) > 3 else '', '')
    category = product_code[4:6] if len(product_code) > 6 else ''
    style = product_code[6:8] if len(product_code) > 8 else ''
    color_code = parts[1] if len(parts) > 1 else ''
    size = parts[2] if len(parts) > 2 else ''
    size_map = {"001": "S", "002": "M", "003": "L", "004": "XL", "008": "均码"}
    size = size_map.get(size, size)
    return {
        "product_code": product_code,
        "style_code": style_code,
        "brand": brand,
        "year": year,
        "season": season,
        "category": category,
        "style": style,
        "color_code": color_code,
        "size": size
    }

# ---------- 数据权限过滤 ----------
def apply_data_permission(df):
    """
    根据当前用户的过滤权限（平台、店铺/主播）过滤数据
    需要在 session_state 中有 username, table_suffix, sub_users
    """
    if df.empty:
        return df
    username = st.session_state.get("username", "")
    sub_users = st.session_state.get("sub_users", {})
    user_info = sub_users.get(username, {})
    filter_platform = user_info.get("filter_platform", "all")
    filter_shop_names = user_info.get("filter_shop_names", [])

    if filter_platform != "all" and "shop_name" in df.columns:
        df = df[df["shop_name"].str.contains(filter_platform, case=False, na=False)]

    if filter_shop_names and "shop_name" in df.columns:
        df = df[df["shop_name"].isin(filter_shop_names)]
    elif filter_shop_names and "anchor" in df.columns:
        df = df[df["anchor"].isin(filter_shop_names)]

    return df
