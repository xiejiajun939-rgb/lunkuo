# -*- coding: utf-8 -*-
import streamlit as st
from datetime import date, timedelta

def date_quick_buttons(start_key, end_key, default_start=None, default_end=None, min_date=None, max_date=None):
    """
    日期快捷按钮 + 日期输入框，自动钳制日期范围到 [min_date, max_date]
    """
    # ---------- 初始化 session_state ----------
    if start_key not in st.session_state:
        st.session_state[start_key] = default_start
    if end_key not in st.session_state:
        st.session_state[end_key] = default_end

    # ---------- 强制钳制到合法范围 ----------
    if min_date is not None and max_date is not None:
        # 将 start 和 end 限制在 [min_date, max_date] 内
        st.session_state[start_key] = max(min_date, min(st.session_state[start_key], max_date))
        st.session_state[end_key] = max(min_date, min(st.session_state[end_key], max_date))
        # 保证 start <= end
        if st.session_state[start_key] > st.session_state[end_key]:
            st.session_state[start_key] = st.session_state[end_key]

    # ---------- 快捷按钮行 ----------
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
