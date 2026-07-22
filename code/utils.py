# -*- coding: utf-8 -*-
import streamlit as st
import re
from datetime import date, timedelta
import pandas as pd

# ========== 常量 ==========
SEASON_MAP = {"1": "春", "2": "夏", "3": "秋", "4": "冬"}
SIZE_MAP = {"001": "S", "002": "M", "003": "L", "004": "XL", "008": "均码"}

# ========== 辅助函数 ==========
def extract_anchor(remark):
    if not isinstance(remark, str):
        return None
    match = re.search(r'主播[：:]([^_]+)', remark)
    return match.group(1).strip() if match else None

def parse_product_code(remark):
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

def date_quick_buttons(start_key, end_key, default_start=None, default_end=None, min_date=None, max_date=None):
    if start_key not in st.session_state:
        st.session_state[start_key] = default_start or date.today().replace(day=1)
    if end_key not in st.session_state:
        st.session_state[end_key] = default_end or date.today()

    def clamp(d):
        if min_date and d < min_date:
            return min_date
        if max_date and d > max_date:
            return max_date
        return d

    cols = st.columns([1, 1, 1, 1, 1, 1.5])
    with cols[0]:
        if st.button("📅 昨日", key=f"{start_key}_yesterday", use_container_width=True):
            yesterday = date.today() - timedelta(days=1)
            st.session_state[start_key] = clamp(yesterday)
            st.session_state[end_key] = clamp(yesterday)
            st.rerun()
    with cols[1]:
        if st.button("📊 近7天", key=f"{start_key}_7days", use_container_width=True):
            yesterday = date.today() - timedelta(days=1)
            start = yesterday - timedelta(days=6)
            st.session_state[start_key] = clamp(start)
            st.session_state[end_key] = clamp(yesterday)
            st.rerun()
    with cols[2]:
        if st.button("📆 上周", key=f"{start_key}_last_week", use_container_width=True):
            today = date.today()
            last_monday = today - timedelta(days=today.weekday() + 7)
            last_sunday = last_monday + timedelta(days=6)
            st.session_state[start_key] = clamp(last_monday)
            st.session_state[end_key] = clamp(last_sunday)
            st.rerun()
    with cols[3]:
        if st.button("📆 本周", key=f"{start_key}_week", use_container_width=True):
            today = date.today()
            start_of_week = today - timedelta(days=today.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            if end_of_week > today:
                end_of_week = today
            st.session_state[start_key] = clamp(start_of_week)
            st.session_state[end_key] = clamp(end_of_week)
            st.rerun()
    with cols[4]:
        if st.button("📆 本月", key=f"{start_key}_month", use_container_width=True):
            today = date.today()
            start_of_month = today.replace(day=1)
            if today.month == 12:
                end_of_month = today.replace(year=today.year+1, month=1, day=1) - timedelta(days=1)
            else:
                end_of_month = today.replace(month=today.month+1, day=1) - timedelta(days=1)
            if end_of_month > today:
                end_of_month = today - timedelta(days=1)
            st.session_state[start_key] = clamp(start_of_month)
            st.session_state[end_key] = clamp(end_of_month)
            st.rerun()
    with cols[5]:
        more_options = ["更多 ▼", "自然月", "自然年", "自定义月"]
        selected_more = st.selectbox("", options=more_options, index=0, key=f"{start_key}_more", label_visibility="collapsed")
        if selected_more != "更多 ▼":
            if selected_more == "自然月":
                col_y, col_m = st.columns(2)
                with col_y:
                    year = st.number_input("年", min_value=2020, max_value=2030, value=date.today().year, key=f"{start_key}_year", label_visibility="collapsed")
                with col_m:
                    month = st.number_input("月", min_value=1, max_value=12, value=date.today().month, key=f"{start_key}_month_num", label_visibility="collapsed")
                if st.button("确定", key=f"{start_key}_month_apply"):
                    start_d = date(year, month, 1)
                    if month == 12:
                        end_d = date(year+1, 1, 1) - timedelta(days=1)
                    else:
                        end_d = date(year, month+1, 1) - timedelta(days=1)
                    today = date.today()
                    if end_d > today:
                        end_d = today - timedelta(days=1)
                    st.session_state[start_key] = clamp(start_d)
                    st.session_state[end_key] = clamp(end_d)
                    st.rerun()
            elif selected_more == "自然年":
                year = st.number_input("年份", min_value=2020, max_value=2030, value=date.today().year, key=f"{start_key}_year_only", label_visibility="collapsed")
                if st.button("确定", key=f"{start_key}_year_apply"):
                    start_d = date(year, 1, 1)
                    end_d = date(year, 12, 31)
                    today = date.today()
                    if end_d > today:
                        end_d = today - timedelta(days=1)
                    st.session_state[start_key] = clamp(start_d)
                    st.session_state[end_key] = clamp(end_d)
                    st.rerun()
            elif selected_more == "自定义月":
                st.info("可自行扩展更多功能")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_val = st.session_state.get(start_key, default_start or date.today())
        if min_date and start_val < min_date:
            start_val = min_date
        if max_date and start_val > max_date:
            start_val = max_date
        st.date_input("开始日期", value=start_val, key=start_key, min_value=min_date, max_value=max_date, label_visibility="collapsed")
    with col_d2:
        end_val = st.session_state.get(end_key, default_end or date.today())
        if min_date and end_val < min_date:
            end_val = min_date
        if max_date and end_val > max_date:
            end_val = max_date
        st.date_input("结束日期", value=end_val, key=end_key, min_value=min_date, max_value=max_date, label_visibility="collapsed")

def apply_data_permission(df, username=None, role=None):
    if username is None:
        username = st.session_state.get("username", "")
    if role is None:
        role = st.session_state.get("role", "")
    if role == "admin" or username == "admin":
        return df
    user_info = st.session_state.sub_users.get(username)
    if not user_info:
        return df
    filter_platform = user_info.get("filter_platform", "all")
    filter_shop_names = user_info.get("filter_shop_names", [])
    if filter_platform != "all":
        if "shop_name" in df.columns:
            if filter_platform == "抖音":
                df = df[df["shop_name"].str.contains("抖音", case=False, na=False)]
            elif filter_platform == "视频号":
                df = df[df["shop_name"].str.contains("视频号", case=False, na=False)]
    if filter_shop_names:
        if "shop_name" in df.columns:
            df = df[df["shop_name"].isin(filter_shop_names)]
        elif "anchor" in df.columns:
            df = df[df["anchor"].isin(filter_shop_names)]
    return df
