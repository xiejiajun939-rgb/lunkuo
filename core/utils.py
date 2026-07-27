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
    # 初始化 session_state 中的日期值（如果不存在）
    if start_key not in st.session_state:
        st.session_state[start_key] = default_start or date.today()
    if end_key not in st.session_state:
        st.session_state[end_key] = default_end or date.today()

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
        # 直接使用 start_key 和 end_key 作为 st.date_input 的 key
        # 这样当用户手动修改日期时，session_state 会自动更新
        col4_1, col4_2 = st.columns(2)
        with col4_1:
            st.date_input(
                "开始",
                key=start_key,                       # 直接使用 start_key
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
