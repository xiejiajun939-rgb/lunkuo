# -*- coding: utf-8 -*-
from datetime import date

import streamlit as st

from core.db import init_supabase
from core.price_adjustments import load_douyin_org_summary
from core.utils import clear_cache_on_page_change


st.set_page_config(page_title="抖音部门与阿米巴", layout="wide")
clear_cache_on_page_change("douyin_amoeba")
st.title("抖音部门与阿米巴销售")
st.caption("销售额为抖音实销（发货－退货），并包含退差价；未完成月初匹配的退差价暂归自媒体部 / 自媒体综合。")

today = date.today()
default_start = today.replace(day=1)
col1, col2 = st.columns(2)
start_date = col1.date_input("开始日期", value=default_start, key="douyin_amoeba_start")
end_date = col2.date_input("结束日期", value=today, key="douyin_amoeba_end")
if start_date > end_date:
    st.error("开始日期不能晚于结束日期")
    st.stop()

try:
    result = load_douyin_org_summary(init_supabase(), start_date, end_date)
except Exception as exc:
    st.error(f"查询失败：{exc}")
    st.stop()

if result.empty:
    st.info("所选时间内没有抖音数据")
else:
    total = result["销售额"].sum()
    st.metric("抖音销售额", f"¥{total:,.2f}")
    display = result.copy()
    display["销售额"] = display["销售额"].map(lambda value: f"¥{value:,.2f}")
    display["销售占比"] = display["销售占比"].map(lambda value: f"{value:.2%}")
    st.dataframe(display, use_container_width=True, hide_index=True)

    dept = result.groupby("部门", as_index=False)["销售额"].sum().sort_values("销售额", ascending=False)
    dept["销售占比"] = dept["销售额"] / total if total else 0
    dept["销售额"] = dept["销售额"].map(lambda value: f"¥{value:,.2f}")
    dept["销售占比"] = dept["销售占比"].map(lambda value: f"{value:.2%}")
    st.subheader("部门汇总")
    st.dataframe(dept, use_container_width=True, hide_index=True)
