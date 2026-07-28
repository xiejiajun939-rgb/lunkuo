# -*- coding: utf-8 -*-
"""
工具函数模块
包含：日期快捷按钮、主播提取、货号解析、数据权限过滤等
"""

import streamlit as st
import pandas as pd
import re
from datetime import date, timedelta

# ---------- 日期快捷按钮（最终稳定版） ----------
def date_quick_buttons(start_key, end_key, default_start=None, default_end=None, min_date=None, max_date=None):
    """
    日期选择器 + 快捷按钮。
    直接使用 start_key 和 end_key 作为 st.date_input 的 key，
    快捷按钮通过修改 session_state 并刷新页面来更新日期。
    """
    # 处理 None 值
    if min_date is None:
        min_date = date.today() - timedelta(days=30)
    if max_date is None:
        max_date = date.today()
    if default_start is None:
        default_start = max_date - timedelta(days=7)
    if default_end is None:
        default_end = max_date

    # 确保默认值在范围内
    if default_start < min_date:
        default_start = min_date
    if default_end > max_date:
        default_end = max_date

    # 初始化 session_state
    if start_key not in st.session_state:
        st.session_state[start_key] = default_start
    if end_key not in st.session_state:
        st.session_state[end_key] = default_end

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

# ---------- 货号解析（修正版：取第二部分为商品编码） ----------
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
    if len(parts) < 2:
        # 如果只有一个部分，尝试直接作为商品编码（兼容旧格式）
        product_code = parts[0]
    else:
        # 新格式：第二个部分是商品编码（例如：16072512213877_G253Y043421001_...）
        product_code = parts[1]
    
    # 验证 product_code 是否有效（长度>=8，且首字母为字母）
    if len(product_code) < 8 or not product_code[0].isalpha():
        return None
    
    style_code = product_code[:8]
    brand = product_code[0] if len(product_code) > 0 else ''
    year = product_code[1:3] if len(product_code) > 3 else ''
    season_map = {"1": "春", "2": "夏", "3": "秋", "4": "冬"}
    season = season_map.get(product_code[3] if len(product_code) > 3 else '', '')
    category = product_code[4:6] if len(product_code) > 6 else ''
    style = product_code[6:8] if len(product_code) > 8 else ''
    # 颜色和尺码可能在其他部分，但此处暂不处理
    color_code = ''
    size = ''
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
