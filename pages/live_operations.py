"""新版直播经营分析：历史直播表现 × 数据罗盘履约实销。"""
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from core.db import load_product_master
from core.live_analytics import load_live_actuals, load_live_auxiliary, load_live_dataset
from core.theme import page_header
from core.utils import clear_cache_on_page_change


st.set_page_config(page_title="直播经营分析", layout="wide")
clear_cache_on_page_change("live_operations")
page_header("直播经营分析", "历史直播表现 × 数据罗盘履约实销", "LIVE OPERATIONS", "新版")

st.info("平台支付按直播发生时间统计；发货、退货按仓库发生时间统计。两种口径并列观察，不进行逐日强制对账。")

today = date.today()
quick = st.segmented_control("分析周期", ["近7天", "近15天", "近30天", "本月", "自定义"], default="近30天")
if quick == "近7天":
    default_start = today - timedelta(days=6)
elif quick == "近15天":
    default_start = today - timedelta(days=14)
elif quick == "本月":
    default_start = today.replace(day=1)
else:
    default_start = today - timedelta(days=29)

date_cols = st.columns(2)
with date_cols[0]:
    start_date = st.date_input("开始日期", default_start, disabled=quick != "自定义")
with date_cols[1]:
    end_date = st.date_input("结束日期", today, disabled=quick != "自定义")
if start_date > end_date:
    st.error("开始日期不能晚于结束日期。")
    st.stop()

with st.spinner("正在加载直播与履约数据……"):
    sessions, products, metrics = load_live_dataset(start_date, end_date)
    actuals = load_live_actuals(start_date, end_date)
    product_master = load_product_master()

if sessions.empty:
    st.warning("所选范围暂无直播记录。可调整日期，或先在系统设置上传直播数据。")
    st.stop()

channels, talks = load_live_auxiliary(tuple(sessions["live_room_id"].astype(str)))
sessions = sessions.copy()
sessions["start_time"] = pd.to_datetime(sessions["start_time"], errors="coerce")
sessions["直播日期"] = sessions["start_time"].dt.date

filter_cols = st.columns(2)
all_shops = sorted(sessions["shop_name"].dropna().astype(str).unique())
all_anchors = sorted(sessions["anchor_name"].dropna().astype(str).unique())
with filter_cols[0]:
    selected_shops = st.multiselect("直播间／店铺", all_shops, default=all_shops)
with filter_cols[1]:
    selected_anchors = st.multiselect("主播", all_anchors, default=all_anchors)

sessions = sessions[sessions["shop_name"].isin(selected_shops) & sessions["anchor_name"].isin(selected_anchors)]
room_ids = sessions["live_room_id"].astype(str)
products = products[products["live_room_id"].astype(str).isin(room_ids)].copy()
metrics = metrics[metrics["live_room_id"].astype(str).isin(room_ids)].copy()
if not channels.empty:
    channels = channels[channels["live_room_id"].astype(str).isin(room_ids)].copy()
if not talks.empty:
    talks = talks[talks["live_room_id"].astype(str).isin(room_ids)].copy()
if sessions.empty:
    st.warning("当前筛选条件下没有直播记录。")
    st.stop()

products = products.merge(
    sessions[["live_room_id", "shop_name", "anchor_name", "start_time", "直播日期", "duration_seconds"]],
    on="live_room_id", how="left", validate="many_to_one",
)
for column in ["paid_amount", "sold_units", "click_users", "talk_count", "pre_ship_refund_amount", "post_ship_refund_amount"]:
    products[column] = pd.to_numeric(products.get(column), errors="coerce").fillna(0)

# 商品讲解区间：计算相对开播分钟、讲解效率和在线人数变化。
talk_summary = pd.DataFrame(columns=[
    "style_code", "讲解场次", "讲解区间数", "累计讲解分钟", "讲解区间支付",
    "讲解区间成交件数", "在线净变化", "平均在线变化", "在线上升场次占比", "分均在线人数",
])
if not talks.empty:
    talks["style_code"] = talks["style_code"].fillna("").astype(str).str.strip().str.upper()
    talks = talks[talks["style_code"] != ""].copy()
    talk_session_times = sessions[["live_room_id", "start_time"]].copy()
    talk_session_times["live_room_id"] = talk_session_times["live_room_id"].astype(str)
    talk_session_times["session_start_utc"] = pd.to_datetime(talk_session_times["start_time"], utc=True, errors="coerce")
    talks["live_room_id"] = talks["live_room_id"].astype(str)
    talks = talks.merge(talk_session_times[["live_room_id", "session_start_utc"]], on="live_room_id", how="left")
    talks["talk_start_time"] = pd.to_datetime(talks["talk_start_epoch"], unit="s", utc=True, errors="coerce")
    talks["开播后分钟"] = ((talks["talk_start_time"] - talks["session_start_utc"]).dt.total_seconds() / 60).clip(lower=0)
    for column in ["talk_duration_seconds", "paid_amount", "sold_units", "viewer_change", "avg_online_users"]:
        talks[column] = pd.to_numeric(talks.get(column), errors="coerce").fillna(0)
    talks["讲解分钟"] = talks["talk_duration_seconds"] / 60
    talks["在线上升"] = talks["viewer_change"] > 0
    talk_summary = talks.groupby("style_code", as_index=False).agg(
        讲解场次=("live_room_id", "nunique"), 讲解区间数=("product_id", "size"),
        累计讲解分钟=("讲解分钟", "sum"), 讲解区间支付=("paid_amount", "sum"),
        讲解区间成交件数=("sold_units", "sum"), 在线净变化=("viewer_change", "sum"),
        平均在线变化=("viewer_change", "mean"), 在线上升场次占比=("在线上升", "mean"),
        分均在线人数=("avg_online_users", "mean"),
    )
    talk_summary["支付/讲解分钟"] = talk_summary["讲解区间支付"].div(talk_summary["累计讲解分钟"].replace(0, pd.NA))
    talk_summary["成交件数/讲解分钟"] = talk_summary["讲解区间成交件数"].div(talk_summary["累计讲解分钟"].replace(0, pd.NA))
    talk_summary["每次讲解平均产出"] = talk_summary["讲解区间支付"].div(talk_summary["讲解区间数"].replace(0, pd.NA))

actual_scope = "店铺＋主播＋货号"
actual_by_style = pd.DataFrame(columns=["style_code", "ship_amount", "return_amount", "net_amount"])
if not actuals.empty and "style_code" in actuals:
    actuals = actuals.copy()
    actuals["shop_key"] = actuals["shop_name"].fillna("").astype(str).str.strip().str.upper()
    actuals = actuals[actuals["shop_key"].isin({x.strip().upper() for x in selected_shops})]
    anchor_source = actuals.get("anchor", actuals.get("anchor_display", pd.Series(index=actuals.index, dtype=str)))
    actuals["anchor_key"] = anchor_source.fillna("").astype(str).str.strip().str.upper()
    anchor_match = actuals["anchor_key"].isin({x.strip().upper() for x in selected_anchors})
    if anchor_match.any():
        actuals = actuals[anchor_match]
    else:
        actual_scope = "店铺＋货号（无法可靠区分主播）"
    actuals["style_code"] = actuals["style_code"].astype(str).str.strip().str.upper()
    actual_by_style = actuals.groupby("style_code", as_index=False).agg(
        ship_amount=("ship_amount", "sum"), return_amount=("return_amount", "sum"), net_amount=("net_amount", "sum")
    )

style_summary = products[products["style_code"].notna()].groupby("style_code", as_index=False).agg(
    商品名称=("product_name", "first"), 上播场次=("live_room_id", "nunique"),
    讲解次数=("talk_count", "sum"), 累计点击=("click_users", "sum"),
    成交件数=("sold_units", "sum"), 平台支付=("paid_amount", "sum"),
    平台退款=("pre_ship_refund_amount", "sum"),
)
style_summary = style_summary.merge(actual_by_style, on="style_code", how="left").fillna(0)
style_summary = style_summary.merge(talk_summary, on="style_code", how="left")
talk_columns = [
    "讲解场次", "讲解区间数", "累计讲解分钟", "讲解区间支付", "讲解区间成交件数",
    "在线净变化", "平均在线变化", "在线上升场次占比", "分均在线人数",
    "支付/讲解分钟", "成交件数/讲解分钟", "每次讲解平均产出",
]
for column in talk_columns:
    if column in style_summary:
        style_summary[column] = pd.to_numeric(style_summary[column], errors="coerce").fillna(0)
style_summary["点击成交率"] = style_summary["成交件数"].div(style_summary["累计点击"].replace(0, pd.NA))
style_summary["成交场次率"] = products.assign(成交=products["sold_units"] > 0).groupby("style_code")["成交"].mean().reindex(style_summary["style_code"]).values
style_summary["退款率"] = style_summary["平台退款"].div(style_summary["平台支付"].replace(0, pd.NA))

metric_wide = metrics.pivot_table(index="live_room_id", columns="metric_name", values="metric_value", aggfunc="sum") if not metrics.empty else pd.DataFrame()

tabs = st.tabs(["经营总览", "单场复盘", "直播间对比", "趋势分析", "完整商品分析", "商品机会", "单款历史档案"])

with tabs[0]:
    total_ship = actual_by_style["ship_amount"].sum()
    total_return = actual_by_style["return_amount"].sum()
    cards = st.columns(5)
    cards[0].metric("历史有效场次", f"{sessions['live_room_id'].nunique():,}")
    cards[1].metric("直播总时长", f"{sessions['duration_seconds'].sum()/3600:,.1f}小时")
    cards[2].metric("平台支付", f"¥{products['paid_amount'].sum():,.0f}")
    cards[3].metric("范围实销", f"¥{(total_ship-total_return):,.0f}")
    cards[4].metric("历史商品样本", f"{len(products):,}")
    st.caption(f"范围实销关联层级：{actual_scope}；实销＝发货－退货，不归因为单场直播。")
    daily_platform = products.groupby("直播日期", as_index=False)["paid_amount"].sum().rename(columns={"paid_amount": "平台支付"})
    if not actuals.empty:
        actual_daily = actuals.groupby("sale_date", as_index=False).agg(发货=("ship_amount", "sum"), 退货=("return_amount", "sum"), 实销=("net_amount", "sum"))
        actual_daily["直播日期"] = pd.to_datetime(actual_daily["sale_date"]).dt.date
        daily_platform = daily_platform.merge(actual_daily.drop(columns="sale_date"), on="直播日期", how="outer").fillna(0)
    trend_columns = [x for x in ["平台支付", "发货", "退货", "实销"] if x in daily_platform]
    st.plotly_chart(px.line(daily_platform.sort_values("直播日期"), x="直播日期", y=trend_columns, markers=True, title="历史经营趋势"), width="stretch")

with tabs[1]:
    labels = sessions.assign(场次=sessions["start_time"].dt.strftime("%m-%d %H:%M") + "｜" + sessions["shop_name"] + "｜" + sessions["anchor_name"])
    selected_label = st.selectbox("选择直播场次", labels["场次"].tolist())
    room = str(labels.loc[labels["场次"] == selected_label, "live_room_id"].iloc[0])
    room_products = products[products["live_room_id"].astype(str) == room].copy()
    room_metrics = metric_wide.loc[room] if room in metric_wide.index.astype(str) else pd.Series(dtype=float)
    cards = st.columns(5)
    cards[0].metric("观看人数", f"{float(room_metrics.get('直播间观看人数', 0) or 0):,.0f}")
    cards[1].metric("商品点击人数", f"{room_products['click_users'].sum():,.0f}")
    cards[2].metric("成交人数", f"{float(room_metrics.get('直播间成交人数', 0) or 0):,.0f}")
    cards[3].metric("成交件数", f"{room_products['sold_units'].sum():,.0f}")
    cards[4].metric("平台支付", f"¥{room_products['paid_amount'].sum():,.0f}")
    detail_tabs = st.tabs(["商品平台表现", "商品讲解区间", "渠道流量", "全部直播指标"])
    with detail_tabs[0]:
        st.dataframe(room_products[["style_code", "product_name", "click_users", "sold_units", "paid_amount", "pre_ship_refund_amount", "post_ship_refund_amount"]].sort_values("paid_amount", ascending=False), width="stretch", hide_index=True)
    with detail_tabs[1]:
        st.dataframe(talks[talks["live_room_id"].astype(str) == room].sort_values("talk_start_epoch") if not talks.empty else pd.DataFrame(), width="stretch", hide_index=True)
    with detail_tabs[2]:
        st.dataframe(channels[channels["live_room_id"].astype(str) == room].sort_values("paid_amount", ascending=False) if not channels.empty else pd.DataFrame(), width="stretch", hide_index=True)
    with detail_tabs[3]:
        st.dataframe(metrics[metrics["live_room_id"].astype(str) == room][["module", "metric_name", "raw_value", "comparison_display"]], width="stretch", hide_index=True)

with tabs[2]:
    room_compare = sessions.groupby(["shop_name", "anchor_name"], as_index=False).agg(场次=("live_room_id", "nunique"), 直播小时=("duration_seconds", lambda x: x.sum()/3600))
    performance = products.groupby(["shop_name", "anchor_name"], as_index=False).agg(商品点击=("click_users", "sum"), 成交件数=("sold_units", "sum"), 平台支付=("paid_amount", "sum"))
    room_compare = room_compare.merge(performance, on=["shop_name", "anchor_name"], how="left")
    room_compare["场均支付"] = room_compare["平台支付"].div(room_compare["场次"].replace(0, pd.NA))
    room_compare["每小时支付"] = room_compare["平台支付"].div(room_compare["直播小时"].replace(0, pd.NA))
    room_compare["点击成交率"] = room_compare["成交件数"].div(room_compare["商品点击"].replace(0, pd.NA))
    st.dataframe(room_compare.sort_values("平台支付", ascending=False), width="stretch", hide_index=True)
    st.plotly_chart(px.bar(room_compare, x="shop_name", y="每小时支付", color="anchor_name", title="直播间每小时产出对比"), width="stretch")

with tabs[3]:
    session_pay = products.groupby(["live_room_id", "直播日期"], as_index=False).agg(平台支付=("paid_amount", "sum"), 商品点击=("click_users", "sum"), 成交件数=("sold_units", "sum"))
    session_pay = session_pay.merge(sessions[["live_room_id", "shop_name", "anchor_name"]], on="live_room_id", how="left")
    metric_name = st.selectbox("趋势指标", ["平台支付", "商品点击", "成交件数"])
    st.plotly_chart(px.line(session_pay.sort_values("直播日期"), x="直播日期", y=metric_name, color="anchor_name", markers=True, hover_data=["shop_name", "live_room_id"]), width="stretch")

with tabs[4]:
    search = st.text_input("搜索商品名称或货号")
    table = style_summary.copy()
    if search:
        key = search.strip().upper()
        table = table[table["style_code"].astype(str).str.upper().str.contains(key, regex=False) | table["商品名称"].astype(str).str.upper().str.contains(key, regex=False)]
    table["诊断"] = "继续观察"
    table.loc[(table["上播场次"] >= 3) & (table["点击成交率"] >= .06), "诊断"] = "稳定转化"
    table.loc[(table["累计点击"] >= 100) & (table["点击成交率"] < .03), "诊断"] = "高点击低成交"
    table.loc[table["退款率"] >= .35, "诊断"] = "退款风险"
    st.dataframe(table.rename(columns={"style_code": "货号", "ship_amount": "范围发货", "return_amount": "范围退货", "net_amount": "范围实销"}).sort_values("平台支付", ascending=False), width="stretch", hide_index=True)

with tabs[5]:
    opportunity = st.segmented_control(
        "机会类型",
        ["开播阶段", "讲解高效", "在线提升", "高转化", "高引流", "稳定复销", "高点击低成交", "退款风险"],
        default="开播阶段",
    )
    min_sessions = st.slider("最少上播场次", 1, 10, 3)
    min_clicks = st.slider("最少累计点击", 0, 1000, 50, 10)
    candidates = style_summary.copy()
    if opportunity == "开播阶段":
        opening_window = st.segmented_control("开播后范围", [15, 30, 60, 90], default=60, format_func=lambda value: f"前{value}分钟")
        opening_talks = talks[talks["开播后分钟"] <= opening_window].copy() if not talks.empty else pd.DataFrame()
        if opening_talks.empty:
            candidates = candidates.iloc[0:0]
        else:
            opening = opening_talks.groupby("style_code", as_index=False).agg(
                开播阶段场次=("live_room_id", "nunique"), 开播阶段讲解次数=("product_id", "size"),
                开播阶段讲解分钟=("讲解分钟", "sum"), 开播阶段支付=("paid_amount", "sum"),
                开播阶段成交件数=("sold_units", "sum"), 开播阶段在线净变化=("viewer_change", "sum"),
                开播阶段平均在线变化=("viewer_change", "mean"), 开播阶段在线上升占比=("在线上升", "mean"),
            )
            opening["开播阶段分钟产出"] = opening["开播阶段支付"].div(opening["开播阶段讲解分钟"].replace(0, pd.NA))
            candidates = candidates.merge(opening, on="style_code", how="inner")
            candidates = candidates[candidates["开播阶段场次"] >= min_sessions].sort_values(
                ["开播阶段分钟产出", "开播阶段在线上升占比"], ascending=False
            )
        st.caption(f"只统计商品讲解开始时间位于开播后前{opening_window}分钟的区间。")
    else:
        candidates = candidates[(candidates["上播场次"] >= min_sessions) & (candidates["累计点击"] >= min_clicks)]
    if opportunity == "讲解高效": candidates = candidates.sort_values(["支付/讲解分钟", "成交件数/讲解分钟"], ascending=False)
    elif opportunity == "在线提升": candidates = candidates.sort_values(["在线上升场次占比", "平均在线变化"], ascending=False)
    elif opportunity == "高转化": candidates = candidates.sort_values("点击成交率", ascending=False)
    elif opportunity == "高引流": candidates = candidates.sort_values("累计点击", ascending=False)
    elif opportunity == "稳定复销": candidates = candidates.sort_values(["成交场次率", "上播场次"], ascending=False)
    elif opportunity == "高点击低成交": candidates = candidates[candidates["点击成交率"] < .03].sort_values("累计点击", ascending=False)
    elif opportunity == "退款风险": candidates = candidates.sort_values("退款率", ascending=False)
    if opportunity in ["讲解高效", "在线提升", "开播阶段"] and talks.empty:
        st.warning("当前范围没有新版商品讲解区间数据，上传新版直播工作簿后才能计算。")
    st.dataframe(candidates.rename(columns={"style_code": "货号", "net_amount": "范围实销"}), width="stretch", hide_index=True)

with tabs[6]:
    options = style_summary.sort_values("平台支付", ascending=False)["style_code"].astype(str).tolist()
    selected_style = st.selectbox("选择货号", options)
    item = products[products["style_code"].astype(str) == selected_style].copy()
    summary_row = style_summary[style_summary["style_code"].astype(str) == selected_style].iloc[0]
    cards = st.columns(5)
    cards[0].metric("历史上播场次", f"{summary_row['上播场次']:.0f}")
    cards[1].metric("成交场次率", f"{summary_row['成交场次率']:.1%}")
    cards[2].metric("点击成交率", f"{summary_row['点击成交率']:.1%}")
    cards[3].metric("平台支付", f"¥{summary_row['平台支付']:,.0f}")
    cards[4].metric("范围实销", f"¥{summary_row['net_amount']:,.0f}")
    anchor_item = item.groupby("anchor_name", as_index=False).agg(场次=("live_room_id", "nunique"), 点击=("click_users", "sum"), 成交件数=("sold_units", "sum"), 平台支付=("paid_amount", "sum"))
    anchor_item["点击成交率"] = anchor_item["成交件数"].div(anchor_item["点击"].replace(0, pd.NA))
    anchor_item["该货号占主播成交"] = anchor_item.apply(lambda r: r["成交件数"] / products.loc[products["anchor_name"] == r["anchor_name"], "sold_units"].sum() if products.loc[products["anchor_name"] == r["anchor_name"], "sold_units"].sum() else pd.NA, axis=1)
    anchor_item["主播占该货号成交"] = anchor_item["成交件数"].div(anchor_item["成交件数"].sum() or pd.NA)
    st.subheader("主播适配与占比")
    st.dataframe(anchor_item.sort_values("成交件数", ascending=False), width="stretch", hide_index=True)
    st.subheader("讲解效率与在线变化")
    item_talks = talks[talks["style_code"].astype(str) == selected_style].copy() if not talks.empty else pd.DataFrame()
    if item_talks.empty:
        st.info("该货号暂无新版商品讲解区间数据。")
    else:
        efficiency = st.columns(5)
        talk_minutes = item_talks["讲解分钟"].sum()
        efficiency[0].metric("累计讲解时长", f"{talk_minutes:,.1f}分钟")
        efficiency[1].metric("场均讲解时长", f"{talk_minutes / item_talks['live_room_id'].nunique():,.1f}分钟")
        efficiency[2].metric("支付/讲解分钟", f"¥{item_talks['paid_amount'].sum() / talk_minutes:,.0f}" if talk_minutes else "—")
        efficiency[3].metric("平均在线变化", f"{item_talks['viewer_change'].mean():+,.1f}")
        efficiency[4].metric("在线上升区间占比", f"{item_talks['在线上升'].mean():.1%}")
        st.dataframe(
            item_talks[["live_room_id", "开播后分钟", "讲解分钟", "paid_amount", "sold_units", "viewer_change", "avg_online_users"]]
            .sort_values(["live_room_id", "开播后分钟"]),
            width="stretch", hide_index=True,
        )
    st.subheader("逐场历史")
    st.dataframe(item[["直播日期", "shop_name", "anchor_name", "talk_count", "click_users", "sold_units", "paid_amount", "pre_ship_refund_amount", "post_ship_refund_amount"]].sort_values("直播日期", ascending=False), width="stretch", hide_index=True)

csv = style_summary.to_csv(index=False).encode("utf-8-sig")
st.download_button("下载当前商品分析", csv, f"直播经营商品分析_{start_date}_{end_date}.csv", "text/csv")
