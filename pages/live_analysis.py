# -*- coding: utf-8 -*-
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.live_analytics import load_live_actuals, load_live_dataset
from core.db import load_product_master
from core.theme import page_header
from core.utils import clear_cache_on_page_change


st.set_page_config(page_title="直播分析", layout="wide")
clear_cache_on_page_change("live_analysis")
page_header("直播经营分析", "连接直播间表现与数据罗盘履约结果", "LIVE COMMERCE", "GMV仅展示原始金额")

st.info("当前直播GMV数据覆盖尚不完整，只展示原始金额，不计算主播、店铺或公司层面的GMV占比。对比结论优先使用讲解效率、点击转化、成交件数和数据罗盘实销。")

today = date.today()
if "live_start_date" not in st.session_state:
    st.session_state.live_start_date = today - timedelta(days=14)
if "live_end_date" not in st.session_state:
    st.session_state.live_end_date = today

quick_cols = st.columns([1, 1, 1, 1, 2, 2])
for column, label, days in zip(quick_cols[:3], ["近7天", "近15天", "近30天"], [7, 15, 30]):
    with column:
        if st.button(label, use_container_width=True):
            st.session_state.live_start_date = today - timedelta(days=days - 1)
            st.session_state.live_end_date = today
            st.rerun()
with quick_cols[3]:
    if st.button("本月", use_container_width=True):
        st.session_state.live_start_date = today.replace(day=1)
        st.session_state.live_end_date = today
        st.rerun()
with quick_cols[4]:
    st.date_input("开始日期", key="live_start_date")
with quick_cols[5]:
    st.date_input("结束日期", key="live_end_date")

start_date = st.session_state.live_start_date
end_date = st.session_state.live_end_date
if start_date > end_date:
    st.error("开始日期不能晚于结束日期。")
    st.stop()

with st.spinner("正在加载直播与实销数据..."):
    sessions, products, metrics = load_live_dataset(start_date, end_date)
    actuals = load_live_actuals(start_date, end_date)
    product_master = load_product_master()

if sessions.empty:
    st.warning("所选日期范围没有直播数据。当前已导入数据可尝试选择2026年9月1日至10日。")
    st.stop()

products = products.merge(
    sessions[["live_room_id", "shop_name", "anchor_name", "start_time", "duration_seconds"]],
    on="live_room_id", how="left", validate="many_to_one",
)
for column in ["talk_count", "click_users", "sold_units", "paid_amount", "pre_ship_refund_amount", "post_ship_refund_amount"]:
    products[column] = pd.to_numeric(products.get(column), errors="coerce").fillna(0)
for column in ["exposure_click_rate", "click_conversion_rate", "pre_ship_refund_rate", "post_ship_refund_rate"]:
    products[column] = pd.to_numeric(products.get(column), errors="coerce")

filter_cols = st.columns([1.4, 1.2, 1.2])
shops = sorted(sessions["shop_name"].dropna().astype(str).unique())
anchors = sorted(sessions["anchor_name"].dropna().astype(str).unique())
with filter_cols[0]:
    selected_shops = st.multiselect("店铺", shops, default=shops)
with filter_cols[1]:
    selected_anchors = st.multiselect("主播", anchors, default=anchors)
with filter_cols[2]:
    match_options = ["全部", "已识别货号", "待确认"]
    match_filter = st.selectbox("货号状态", match_options)

sessions = sessions[sessions["shop_name"].isin(selected_shops) & sessions["anchor_name"].isin(selected_anchors)]
products = products[products["live_room_id"].isin(sessions["live_room_id"])]
if match_filter == "已识别货号":
    products = products[products["style_code"].notna()]
elif match_filter == "待确认":
    products = products[products["style_code"].isna() | products["match_status"].isin(["unmatched", "catalog_missing"])]

if products.empty:
    st.warning("当前筛选条件下没有商品数据。")
    st.stop()

actual_by_style = pd.DataFrame(columns=["style_code", "ship_amount", "return_amount", "net_amount"])
if not actuals.empty and "style_code" in actuals.columns:
    actuals = actuals.copy()
    actuals["shop_key"] = actuals["shop_name"].astype(str).str.strip().str.upper()
    selected_shop_keys = {str(x).strip().upper() for x in selected_shops}
    actuals = actuals[actuals["shop_key"].isin(selected_shop_keys)]
    actuals["style_code"] = actuals["style_code"].astype(str).str.strip().str.upper()
    actual_by_style = actuals.groupby("style_code", as_index=False).agg(
        ship_amount=("ship_amount", "sum"), return_amount=("return_amount", "sum"), net_amount=("net_amount", "sum")
    )

total_duration = sessions["duration_seconds"].sum() / 3600
total_refund = products["pre_ship_refund_amount"].sum() + products["post_ship_refund_amount"].sum()
metric_cols = st.columns(6)
metric_cols[0].metric("直播场次", f"{len(sessions):,}", f"{total_duration:,.1f}小时")
metric_cols[1].metric("支付GMV（原始）", f"¥{products['paid_amount'].sum():,.0f}")
metric_cols[2].metric("成交件数", f"{products['sold_units'].sum():,.0f}")
metric_cols[3].metric("商品点击人数", f"{products['click_users'].sum():,.0f}")
metric_cols[4].metric("平台退款金额", f"¥{total_refund:,.0f}")
metric_cols[5].metric("关联实销", f"¥{actual_by_style['net_amount'].sum():,.0f}")

tabs = st.tabs(["经营总览", "对比分析", "场次分析", "商品分析", "单货品分析", "待确认商品"])

with tabs[0]:
    left, right = st.columns([1.1, 0.9])
    with left:
        st.subheader("直播流量与成交漏斗")
        metric_lookup = metrics.groupby("metric_name")["metric_value"].sum() if not metrics.empty else pd.Series(dtype=float)
        funnel = pd.DataFrame({"阶段": ["曝光人数", "进入直播间", "商品点击", "成交件数"], "数量": [
            metric_lookup.get("直播间曝光人数", 0), metric_lookup.get("进入直播间人数", 0),
            products["click_users"].sum(), products["sold_units"].sum(),
        ]})
        fig = go.Figure(go.Funnel(y=funnel["阶段"], x=funnel["数量"], textinfo="value+percent initial"))
        fig.update_layout(height=330, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("GMV与履约趋势")
        live_daily = products.assign(日期=pd.to_datetime(products["start_time"]).dt.date).groupby("日期", as_index=False)["paid_amount"].sum()
        live_daily = live_daily.rename(columns={"paid_amount": "直播支付GMV"})
        if not actuals.empty:
            actual_daily = actuals.assign(日期=pd.to_datetime(actuals["sale_date"]).dt.date).groupby("日期", as_index=False).agg(
                关联发货=("ship_amount", "sum"), 关联退货=("return_amount", "sum"), 关联实销=("net_amount", "sum"))
            trend = live_daily.merge(actual_daily, on="日期", how="outer").fillna(0).sort_values("日期")
        else:
            trend = live_daily.assign(关联发货=0, 关联退货=0, 关联实销=0)
        fig = px.line(trend, x="日期", y=["直播支付GMV", "关联发货", "关联退货", "关联实销"], markers=True)
        fig.update_layout(height=330, legend_title_text="口径", yaxis_title="金额（元）")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("直播支付GMV与数据罗盘履约金额是不同口径，只用于并列观察。")

with tabs[1]:
    st.subheader("店铺 / 主播对比")
    compare_dimension = st.radio("对比维度", ["主播", "店铺"], horizontal=True)
    dimension = "anchor_name" if compare_dimension == "主播" else "shop_name"
    grouped = products.groupby(dimension, as_index=False).agg(
        直播场次=("live_room_id", "nunique"), 讲解次数=("talk_count", "sum"), 点击人数=("click_users", "sum"),
        成交件数=("sold_units", "sum"), 支付GMV=("paid_amount", "sum"),
        平台退款=("pre_ship_refund_amount", "sum"),
    )
    grouped["成交件数/讲解"] = grouped["成交件数"].div(grouped["讲解次数"].replace(0, pd.NA))
    grouped["点击成交率"] = grouped["成交件数"].div(grouped["点击人数"].replace(0, pd.NA))
    st.dataframe(grouped.rename(columns={dimension: compare_dimension}), use_container_width=True, hide_index=True,
                 column_config={"支付GMV": st.column_config.NumberColumn(format="¥ %.0f"), "平台退款": st.column_config.NumberColumn(format="¥ %.0f"), "点击成交率": st.column_config.NumberColumn(format="%.1%%"), "成交件数/讲解": st.column_config.NumberColumn(format="%.2f")})
    chart = px.bar(grouped, x=dimension, y=["成交件数", "讲解次数"], barmode="group", title="成交件数与讲解次数")
    st.plotly_chart(chart, use_container_width=True)

with tabs[2]:
    st.subheader("场次表现")
    session_summary = products.groupby(["live_room_id", "shop_name", "anchor_name", "start_time"], as_index=False).agg(
        商品数=("product_id", "nunique"), 讲解次数=("talk_count", "sum"), 点击人数=("click_users", "sum"),
        成交件数=("sold_units", "sum"), 支付GMV=("paid_amount", "sum"),
    )
    session_summary["点击成交率"] = session_summary["成交件数"].div(session_summary["点击人数"].replace(0, pd.NA))
    st.dataframe(session_summary.rename(columns={"start_time": "开播时间", "shop_name": "店铺", "anchor_name": "主播"}), use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader("商品经营表现")
    style_summary = products[products["style_code"].notna()].groupby(["style_code", "product_name"], as_index=False).agg(
        场次数=("live_room_id", "nunique"), 讲解次数=("talk_count", "sum"), 点击人数=("click_users", "sum"),
        成交件数=("sold_units", "sum"), 支付GMV=("paid_amount", "sum"),
        平台退款=("pre_ship_refund_amount", "sum"),
    ).merge(actual_by_style, on="style_code", how="left").fillna({"ship_amount": 0, "return_amount": 0, "net_amount": 0})
    style_summary["成交件数/讲解"] = style_summary["成交件数"].div(style_summary["讲解次数"].replace(0, pd.NA))
    style_summary["点击成交率"] = style_summary["成交件数"].div(style_summary["点击人数"].replace(0, pd.NA))
    style_summary = style_summary.sort_values(["成交件数", "net_amount"], ascending=False)
    st.dataframe(style_summary.rename(columns={"style_code": "货号", "product_name": "商品名称", "ship_amount": "关联发货", "return_amount": "关联退货", "net_amount": "关联实销"}), use_container_width=True, hide_index=True)

with tabs[4]:
    style_options = (
        products[products["style_code"].notna()]
        .groupby("style_code")["sold_units"].sum()
        .sort_values(ascending=False).index.astype(str).tolist()
    )
    selected_style = st.selectbox("选择货号", style_options)
    item = products[products["style_code"] == selected_style].copy()
    master_row = pd.DataFrame()
    if not product_master.empty and "style_code" in product_master.columns:
        master_row = product_master[
            product_master["style_code"].astype(str).str.strip().str.upper() == selected_style
        ]
    info_col, title_col = st.columns([1, 5])
    with info_col:
        if not master_row.empty and master_row.iloc[0].get("image_url"):
            st.image(master_row.iloc[0]["image_url"], use_container_width=True)
    with title_col:
        st.subheader(f"{selected_style} · {item['product_name'].iloc[0]}")
        if not master_row.empty:
            category = master_row.iloc[0].get("category") or "未维护品类"
            launch_date = master_row.iloc[0].get("launch_date") or "未维护"
            st.caption(f"品类：{category}　上新时间：{launch_date}　货号来源：商品名称自动识别并通过商品库校验")
    item_metrics = st.columns(4)
    item_metrics[0].metric("累计讲解", f"{item['talk_count'].sum():,.0f}次")
    item_metrics[1].metric("成交件数", f"{item['sold_units'].sum():,.0f}件")
    item_metrics[2].metric("商品点击人数", f"{item['click_users'].sum():,.0f}")
    item_actual = actual_by_style[actual_by_style["style_code"] == selected_style]
    item_net = item_actual["net_amount"].sum() if not item_actual.empty else 0
    item_metrics[3].metric("关联实销", f"¥{item_net:,.0f}")
    anchor_item = item.groupby("anchor_name", as_index=False).agg(
        场次数=("live_room_id", "nunique"), 讲解次数=("talk_count", "sum"), 点击人数=("click_users", "sum"),
        成交件数=("sold_units", "sum"), 支付GMV原始值=("paid_amount", "sum"),
        发货前退款=("pre_ship_refund_amount", "sum"), 发货后退款=("post_ship_refund_amount", "sum"),
    )
    anchor_item["成交件数/讲解"] = anchor_item["成交件数"].div(anchor_item["讲解次数"].replace(0, pd.NA))
    anchor_item["点击成交率"] = anchor_item["成交件数"].div(anchor_item["点击人数"].replace(0, pd.NA))
    st.markdown("#### 主播对比")
    st.dataframe(anchor_item.rename(columns={"anchor_name": "主播"}), use_container_width=True, hide_index=True)
    st.caption("GMV仅显示原始金额，不计算商品占主播、平台或公司的GMV比例。")

with tabs[5]:
    review = products[products["style_code"].isna() | products["match_status"].isin(["unmatched", "catalog_missing"])][
        ["shop_name", "product_id", "product_name", "style_code", "match_status"]
    ].drop_duplicates()
    st.subheader("待确认商品")
    if review.empty:
        st.success("当前筛选范围内所有商品名称都已识别出货号并通过校验。")
    else:
        st.dataframe(review, use_container_width=True, hide_index=True)
