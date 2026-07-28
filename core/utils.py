# -*- coding: utf-8 -*-
"""
工具函数模块
包含：日期快捷按钮、主播提取、货号解析、数据权限过滤等
"""

import streamlit as st
import pandas as pd
import re
from datetime import date, timedelta

# ---------- 常量映射 ----------
SEASON_MAP = {"1": "春", "2": "夏", "3": "秋", "4": "冬"}
SIZE_MAP = {"001": "S", "002": "M", "003": "L", "004": "XL", "008": "均码"}


# ---------- 日期快捷按钮（已修复边界问题） ----------
def date_quick_buttons(start_key, end_key, default_start=None, default_end=None, min_date=None, max_date=None):
    """
    日期快捷按钮 + 日期输入框
    自动将 session_state 中的日期钳制到 [min_date, max_date] 内
    """
    # 初始化 session_state
    if start_key not in st.session_state:
        st.session_state[start_key] = default_start
    if end_key not in st.session_state:
        st.session_state[end_key] = default_end

    # 强制钳制到合法范围（关键修复）
    if min_date is not None and max_date is not None:
        st.session_state[start_key] = max(min_date, min(st.session_state[start_key], max_date))
        st.session_state[end_key] = max(min_date, min(st.session_state[end_key], max_date))
        if st.session_state[start_key] > st.session_state[end_key]:
            st.session_state[start_key] = st.session_state[end_key]

    # 快捷按钮行
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
                key=start_key,
                min_value=min_date,
                max_value=max_date,
                label_visibility="collapsed"
            )
        with col4_2:
            st.date_input(
                "结束",
                key=end_key,
                min_value=min_date,
                max_value=max_date,
                label_visibility="collapsed"
            )


# ---------- 主播提取 ----------
def extract_anchor(remark):
    """从备注中提取主播名称（格式：主播：xxx）"""
    if not isinstance(remark, str):
        return None
    match = re.search(r'主播[：:]([^_]+)', remark)
    return match.group(1).strip() if match else None


# ---------- 货号解析（旧版正确函数） ----------
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
    try:
        parts = remark.split('_')
        if len(parts) < 2:
            return None
        product_code = parts[1]
        if len(product_code) < 14:
            return None
        brand = product_code[0]
        year_season = product_code[1:4]
        year = year_season[:2]
        season_code = year_season[2]
        category = product_code[4]
        style = product_code[5:8]
        color_code = product_code[8:11]
        size_code = product_code[11:14]
        style_code = product_code[:8]
        return {
            "product_code": product_code,
            "style_code": style_code,
            "brand": brand,
            "year": year,
            "season": SEASON_MAP.get(season_code, season_code),
            "category": category,
            "style": style,
            "color_code": color_code,
            "size": SIZE_MAP.get(size_code, size_code)
        }
    except:
        return None


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
