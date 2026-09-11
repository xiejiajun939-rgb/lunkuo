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
        if st.button(label, width="stretch"):
            st.session_state.live_start_date = today - timedelta(days=days - 1)
            st.session_state.live_end_date = today
            st.rerun()
with quick_cols[3]:
    if st.button("本月", width="stretch"):
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
    sessions[["live_room_id", "shop_name", "anchor_name", "start_time", "end_time", "duration_seconds"]],
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
metrics = metrics[metrics["live_room_id"].isin(sessions["live_room_id"])]
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
    anchor_source = actuals["anchor"] if "anchor" in actuals.columns else actuals.get("anchor_display", pd.Series(index=actuals.index, dtype=str))
    actuals["anchor_key"] = anchor_source.fillna("").astype(str).str.strip().str.upper()
    selected_shop_keys = {str(x).strip().upper() for x in selected_shops}
    selected_anchor_keys = {str(x).strip().upper() for x in selected_anchors}
    actuals = actuals[
        actuals["shop_key"].isin(selected_shop_keys)
        & actuals["anchor_key"].isin(selected_anchor_keys)
    ]
    actuals["style_code"] = actuals["style_code"].astype(str).str.strip().str.upper()
    actual_by_style = actuals.groupby("style_code", as_index=False).agg(
        ship_amount=("ship_amount", "sum"), return_amount=("return_amount", "sum"), net_amount=("net_amount", "sum")
    )

def format_duration(total_seconds):
    total_seconds = int(total_seconds or 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}小时{minutes}分"
    if minutes:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"


total_duration_seconds = sessions["duration_seconds"].sum()
total_refund = products["pre_ship_refund_amount"].sum() + products["post_ship_refund_amount"].sum()
metric_cols = st.columns(5)
metric_cols[0].metric("直播场次", f"{len(sessions):,}", format_duration(total_duration_seconds))
metric_cols[1].metric("支付GMV（原始）", f"¥{products['paid_amount'].sum():,.0f}")
metric_cols[2].metric("成交件数", f"{products['sold_units'].sum():,.0f}")
metric_cols[3].metric("商品点击人数", f"{products['click_users'].sum():,.0f}")
metric_cols[4].metric("平台退款金额", f"¥{total_refund:,.0f}")

selected_ship = actual_by_style["ship_amount"].sum()
selected_return = actual_by_style["return_amount"].sum()
selected_net = actual_by_style["net_amount"].sum()
selected_return_rate = selected_return / selected_ship if selected_ship else 0
st.markdown("#### 所选范围履约数据")
fulfillment_cols = st.columns(4)
fulfillment_cols[0].metric("发货金额", f"¥{selected_ship:,.0f}")
fulfillment_cols[1].metric("退货金额", f"¥{selected_return:,.0f}")
fulfillment_cols[2].metric("实销金额", f"¥{selected_net:,.0f}")
fulfillment_cols[3].metric("退货率", f"{selected_return_rate:.1%}")
st.caption("数据罗盘口径：按当前日期、店铺和主播范围汇总；商品明细再按货号关联。实销金额＝发货金额－退货金额。")

tabs = st.tabs(["经营总览", "对比分析", "场次分析", "商品分析", "单货品分析", "待确认商品"])

with tabs[0]:
    left, right = st.columns([1.1, 0.9])
    with left:
        st.subheader("直播流量与成交转化")
        metric_lookup = metrics.groupby("metric_name")["metric_value"].sum() if not metrics.empty else pd.Series(dtype=float)
        exposure_users = float(metric_lookup.get("直播间曝光人数", 0) or 0)
        room_users = float(metric_lookup.get("进入直播间人数", 0) or 0)
        click_users = float(products["click_users"].sum() or 0)
        buyer_users = float(metric_lookup.get("直播间成交人数", 0) or 0)
        sold_units = float(products["sold_units"].sum() or 0)

        def _rate(numerator, denominator):
            return numerator / denominator * 100 if denominator else 0

        stages = [
            ("直播曝光", exposure_users, "人"),
            ("进入直播间", room_users, "人"),
            ("商品点击", click_users, "人次汇总"),
            ("成交人数", buyer_users, "人"),
        ]
        rates = [
            ("曝光→进房", _rate(room_users, exposure_users)),
            ("进房→点击", _rate(click_users, room_users)),
            ("点击→成交", _rate(buyer_users, click_users)),
        ]
        stage_html = []
        for index, (label, value, unit) in enumerate(stages):
            stage_html.append(
                f"<div class='flow-stage'><div class='flow-label'>{label}</div>"
                f"<div class='flow-value'>{value:,.0f}</div><div class='flow-unit'>{unit}</div></div>"
            )
            if index < len(rates):
                rate_label, rate_value = rates[index]
                stage_html.append(
                    f"<div class='flow-arrow'><div>{rate_value:.2f}%</div>"
                    f"<span>{rate_label}</span><b>→</b></div>"
                )
        st.markdown(
            """
            <style>
            .live-flow{display:flex;align-items:stretch;gap:10px;padding:18px 16px 14px;
                border:1px solid #d7e4ef;border-radius:18px;background:linear-gradient(135deg,#f8fbff,#eef7fb)}
            .flow-stage{flex:1;min-width:105px;padding:20px 12px;border-radius:14px;background:#0b2843;
                color:#fff;text-align:center;box-shadow:0 8px 20px rgba(8,42,72,.14)}
            .flow-stage:last-child{background:linear-gradient(135deg,#087f8c,#15a8b5)}
            .flow-label{font-size:13px;color:#d8e8f5}.flow-value{margin-top:7px;font-size:28px;font-weight:800;line-height:1.1}
            .flow-unit{margin-top:5px;font-size:11px;color:#b9cedd}.flow-arrow{min-width:74px;display:flex;flex-direction:column;
                align-items:center;justify-content:center;color:#0b6380;font-size:15px;font-weight:800;text-align:center}
            .flow-arrow span{margin-top:3px;color:#607487;font-size:10px;font-weight:500}.flow-arrow b{font-size:24px;line-height:1;color:#36a9bd}
            .flow-foot{display:flex;justify-content:space-between;gap:12px;margin-top:10px;padding:10px 14px;
                border-radius:12px;background:#edf4f8;color:#334a5f;font-size:12px}.flow-foot strong{color:#0b6380}
            @media(max-width:900px){.live-flow{flex-wrap:wrap}.flow-arrow{min-width:45px}.flow-stage{min-width:120px}}
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='live-flow'>{''.join(stage_html)}</div>"
            f"<div class='flow-foot'><span>成交件数：<strong>{sold_units:,.0f} 件</strong></span>"
            f"<span>件数 ÷ 点击人数：<strong>{_rate(sold_units, click_users):.2f}%</strong></span></div>",
            unsafe_allow_html=True,
        )
        st.caption("成交转化率采用“直播间成交人数 ÷ 商品点击人数”；件数效率单独展示。商品点击人数为商品明细汇总口径，同一用户点击多个商品时可能重复计算。")
    with right:
        st.subheader("GMV与履约趋势")
        live_daily = products.assign(日期=pd.to_datetime(products["start_time"]).dt.date).groupby("日期", as_index=False)["paid_amount"].sum()
        live_daily = live_daily.rename(columns={"paid_amount": "直播支付GMV"})
        if not actuals.empty:
            actual_daily = actuals.assign(日期=pd.to_datetime(actuals["sale_date"]).dt.date).groupby("日期", as_index=False).agg(
                所选范围发货=("ship_amount", "sum"), 所选范围退货=("return_amount", "sum"), 所选范围实销=("net_amount", "sum"))
            trend = live_daily.merge(actual_daily, on="日期", how="outer").fillna(0).sort_values("日期")
        else:
            trend = live_daily.assign(所选范围发货=0, 所选范围退货=0, 所选范围实销=0)
        fig = px.line(trend, x="日期", y=["直播支付GMV", "所选范围发货", "所选范围退货", "所选范围实销"], markers=True)
        fig.update_layout(height=330, legend_title_text="口径", yaxis_title="金额（元）")
        st.plotly_chart(fig, width="stretch")
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
    st.dataframe(grouped.rename(columns={dimension: compare_dimension}), width="stretch", hide_index=True,
                 column_config={"支付GMV": st.column_config.NumberColumn(format="¥ %.0f"), "平台退款": st.column_config.NumberColumn(format="¥ %.0f"), "点击成交率": st.column_config.NumberColumn(format="%.1%%"), "成交件数/讲解": st.column_config.NumberColumn(format="%.2f")})
    chart = px.bar(grouped, x=dimension, y=["成交件数", "讲解次数"], barmode="group", title="成交件数与讲解次数")
    st.plotly_chart(chart, width="stretch")

with tabs[0]:
    st.subheader("平台指标场次趋势")
    st.caption("横轴按北京时间的开播先后排列，每个节点代表一场直播；不同量级指标已分图展示。")
    trend_metric_groups = {
        "人数与数量": [
            "直播间曝光人数", "进入直播间人数", "自然流量观看人数", "付费流量观看人数",
            "平均在线人数", "最高在线人数", "直播间成交人数", "商品点击人数", "成交件数",
            "新增粉丝数", "评论次数", "点赞次数",
        ],
        "转化率": [
            "直播间观看-成交转化率(人数)", "直播间观看-互动率(人数)",
            "直播间观看-关注率(人数)", "首购率(人数)", "粉丝成交人数占比", "粉丝成交金额占比",
        ],
        "金额": ["支付GMV"],
    }
    available_platform_metrics = set(metrics["metric_name"].dropna().astype(str))
    product_trend_metrics = {"商品点击人数", "成交件数", "支付GMV"}
    trend_options = [
        name for names in trend_metric_groups.values() for name in names
        if name in available_platform_metrics or name in product_trend_metrics
    ]
    default_trend_metrics = [
        name for name in ["直播间曝光人数", "进入直播间人数", "直播间成交人数", "商品点击人数", "成交件数", "支付GMV"]
        if name in trend_options
    ]
    selected_trend_metrics = st.multiselect(
        "选择趋势指标",
        trend_options,
        default=default_trend_metrics,
        placeholder="选择一个或多个平台指标",
    )

    platform_trend = (
        metrics.sort_values(["live_room_id", "metric_name", "module"])
        .drop_duplicates(["live_room_id", "metric_name"], keep="first")
        [["live_room_id", "metric_name", "metric_value", "benchmark_value"]]
    )
    product_by_room = products.groupby("live_room_id", as_index=False).agg(
        商品点击人数=("click_users", "sum"), 成交件数=("sold_units", "sum"), 支付GMV=("paid_amount", "sum")
    )
    room_context = sessions[["live_room_id", "start_time", "shop_name", "anchor_name"]].copy()
    room_context["场次"] = room_context["start_time"].dt.strftime("%m-%d %H:%M")
    room_context = room_context.sort_values("start_time")

    if not selected_trend_metrics:
        st.info("请至少选择一个趋势指标。")
    else:
        trend_rows = []
        for metric_name in selected_trend_metrics:
            if metric_name in product_trend_metrics:
                values = product_by_room[["live_room_id", metric_name]].rename(columns={metric_name: "当前值"})
                values["基准值"] = pd.NA
            else:
                values = platform_trend[platform_trend["metric_name"] == metric_name][
                    ["live_room_id", "metric_value", "benchmark_value"]
                ].rename(columns={"metric_value": "当前值", "benchmark_value": "基准值"})
            values = room_context.merge(values, on="live_room_id", how="left")
            values["指标"] = metric_name.replace("直播间", "").replace("(人数)", "")
            trend_rows.append(values)
        trend_data = pd.concat(trend_rows, ignore_index=True)
        trend_data["当前值"] = pd.to_numeric(trend_data["当前值"], errors="coerce")
        trend_data["基准值"] = pd.to_numeric(trend_data["基准值"], errors="coerce")

        for group_name, group_metrics in trend_metric_groups.items():
            display_names = [name.replace("直播间", "").replace("(人数)", "") for name in group_metrics]
            group_data = trend_data[trend_data["指标"].isin(display_names) & trend_data["当前值"].notna()]
            if group_data.empty:
                continue
            st.markdown(f"#### {group_name}趋势")
            fig = px.line(
                group_data,
                x="场次",
                y="当前值",
                color="指标",
                markers=True,
                category_orders={"场次": room_context["场次"].tolist()},
                hover_data={"shop_name": True, "anchor_name": True, "live_room_id": True, "场次": True, "当前值": ":,.2f"},
                labels={"当前值": "金额（元）" if group_name == "金额" else ("比例（%）" if group_name == "转化率" else "人数 / 数量")},
            )
            benchmark_data = group_data[group_data["基准值"].notna()]
            for metric_name, benchmark_series in benchmark_data.groupby("指标", sort=False):
                fig.add_trace(go.Scatter(
                    x=benchmark_series["场次"],
                    y=benchmark_series["基准值"],
                    mode="lines",
                    line=dict(dash="dot", width=1.5),
                    opacity=0.65,
                    name=f"{metric_name}·近7天中位数",
                    hovertemplate="%{x}<br>近7天中位数：%{y:,.2f}<extra></extra>",
                ))
            fig.update_layout(height=360, legend_title_text="指标", xaxis_title="开播时间（北京时间）")
            st.plotly_chart(fig, width="stretch")

            if not benchmark_data.empty:
                benchmark_table = benchmark_data[["场次", "指标", "当前值", "基准值"]].copy()
                benchmark_table["较中位数"] = benchmark_table.apply(
                    lambda row: (row["当前值"] - row["基准值"]) / abs(row["基准值"])
                    if row["基准值"] else pd.NA,
                    axis=1,
                )
                with st.expander(f"查看{group_name}的近7天中位数对照"):
                    st.dataframe(
                        benchmark_table,
                        width="stretch",
                        hide_index=True,
                        column_config={"较中位数": st.column_config.NumberColumn(format="%.1f%%")},
                    )

with tabs[2]:
    st.subheader("场次表现")
    session_summary = products.groupby(["live_room_id", "shop_name", "anchor_name", "start_time", "end_time", "duration_seconds"], as_index=False).agg(
        商品数=("product_id", "nunique"), 讲解次数=("talk_count", "sum"), 点击人数=("click_users", "sum"),
        成交件数=("sold_units", "sum"), 支付GMV=("paid_amount", "sum"),
    )
    session_summary["点击成交率"] = session_summary["成交件数"].div(session_summary["点击人数"].replace(0, pd.NA))
    session_summary["直播时长"] = session_summary["duration_seconds"].map(format_duration)
    session_table = session_summary.rename(columns={
        "start_time": "开播时间", "end_time": "下播时间", "shop_name": "店铺", "anchor_name": "主播",
    }).drop(columns=["duration_seconds"])
    st.dataframe(
        session_table,
        width="stretch",
        hide_index=True,
        column_config={
            "开播时间": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "下播时间": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "支付GMV": st.column_config.NumberColumn(format="¥ %.0f"),
            "点击成交率": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )

    st.markdown("#### 单场直播下钻")
    session_rows = sessions.sort_values("start_time", ascending=False).set_index("live_room_id")
    room_options = session_rows.index.astype(str).tolist()

    def room_label(room_id):
        row = session_rows.loc[room_id]
        return f"{row['start_time']:%Y-%m-%d %H:%M}｜{row['anchor_name']}｜{row['live_title'] or '未命名场次'}"

    selected_room = st.selectbox("选择直播场次", room_options, format_func=room_label)
    room = session_rows.loc[selected_room]
    room_products = products[products["live_room_id"].astype(str) == selected_room].copy()
    room_metrics = metrics[metrics["live_room_id"].astype(str) == selected_room].copy()

    detail_cols = st.columns(5)
    detail_cols[0].metric("开播时间", room["start_time"].strftime("%m-%d %H:%M"))
    detail_cols[1].metric("下播时间", room["end_time"].strftime("%m-%d %H:%M") if pd.notna(room["end_time"]) else "-")
    detail_cols[2].metric("直播时长", format_duration(room["duration_seconds"]))
    detail_cols[3].metric("商品数", f"{room_products['product_id'].nunique():,}")
    detail_cols[4].metric("支付GMV（原始）", f"¥{room_products['paid_amount'].sum():,.0f}")
    st.caption(f"店铺：{room['shop_name']}　主播：{room['anchor_name']}　场次ID：{selected_room}")

    metric_tab, product_tab = st.tabs(["直播核心指标", "全部商品平台表现"])
    with metric_tab:
        if room_metrics.empty:
            st.info("该场次暂无直播指标。")
        else:
            metric_groups = {
                "流量": ["直播间曝光人数", "进入直播间人数", "自然流量观看人数", "付费流量观看人数", "平均在线人数", "最高在线人数"],
                "转化": ["直播间成交人数", "直播间观看-成交转化率(人数)"],
                "互动与沉淀": ["人均观看时长", "直播间观看-互动率(人数)", "直播间观看-关注率(人数)", "新增粉丝数", "评论次数", "点赞次数"],
                "人群": ["首购率(人数)", "粉丝成交人数占比", "粉丝成交金额占比"],
            }
            deduplicated = (
                room_metrics.sort_values(["metric_name", "module"])
                .drop_duplicates("metric_name", keep="first")
                .set_index("metric_name")
            )

            def display_metric_value(row, value_column, raw_column):
                raw = row.get(raw_column)
                if pd.notna(raw) and str(raw).strip() not in {"", "-"}:
                    text = str(raw).strip()
                else:
                    value = pd.to_numeric(row.get(value_column), errors="coerce")
                    text = "-" if pd.isna(value) else f"{value:,.2f}".rstrip("0").rstrip(".")
                unit_value = row.get("unit")
                unit = "" if pd.isna(unit_value) else str(unit_value).strip()
                if unit and unit not in text and not any(mark in text for mark in ["%", "秒", "分", "小时"]):
                    text = f"{text} {unit}"
                return text

            concise_rows = []
            for group_name, names in metric_groups.items():
                for name in names:
                    if name not in deduplicated.index:
                        continue
                    row = deduplicated.loc[name]
                    current = pd.to_numeric(row.get("metric_value"), errors="coerce")
                    benchmark = pd.to_numeric(row.get("benchmark_value"), errors="coerce")
                    if pd.notna(current) and pd.notna(benchmark) and benchmark != 0:
                        difference = (current - benchmark) / abs(benchmark) * 100
                        comparison = f"{'高于' if difference >= 0 else '低于'} {abs(difference):.1f}%"
                    else:
                        comparison = "-"
                    concise_rows.append({
                        "指标分组": group_name,
                        "指标": name.replace("直播间", "").replace("(人数)", ""),
                        "当前表现": display_metric_value(row, "metric_value", "raw_value"),
                        "近7天中位数": display_metric_value(row, "benchmark_value", "benchmark_raw"),
                        "对比结果": comparison,
                    })

            concise_rows.extend([
                {"指标分组": "转化", "指标": "商品点击人数（商品汇总）", "当前表现": f"{room_products['click_users'].sum():,.0f} 人次", "近7天中位数": "-", "对比结果": "-"},
                {"指标分组": "转化", "指标": "成交件数", "当前表现": f"{room_products['sold_units'].sum():,.0f} 件", "近7天中位数": "-", "对比结果": "-"},
                {"指标分组": "转化", "指标": "支付GMV", "当前表现": f"¥{room_products['paid_amount'].sum():,.0f}", "近7天中位数": "-", "对比结果": "-"},
            ])
            st.dataframe(pd.DataFrame(concise_rows), width="stretch", hide_index=True)
            st.caption("同名指标已去重；商品点击人数为商品明细汇总，同一用户点击多个商品时可能重复。")
    with product_tab:
        if room_products.empty:
            st.info("该场次暂无商品平台数据。")
        else:
            product_columns = [
                "style_code", "product_name", "product_id", "talk_count", "first_listed_at", "live_price",
                "paid_amount", "sold_units", "presale_orders", "click_users", "exposure_click_rate",
                "click_conversion_rate", "gmv_per_1000_exposure", "pre_ship_refund_orders",
                "pre_ship_refund_amount", "pre_ship_refund_users", "pre_ship_refund_rate",
                "post_ship_refund_orders", "post_ship_refund_amount", "post_ship_refund_users", "post_ship_refund_rate",
            ]
            product_columns = [column for column in product_columns if column in room_products.columns]
            product_detail = room_products[product_columns].rename(columns={
                "style_code": "货号", "product_name": "商品名称", "product_id": "平台商品ID",
                "talk_count": "讲解次数", "first_listed_at": "首次上架时间", "live_price": "直播间价格",
                "paid_amount": "用户支付金额", "sold_units": "成交件数", "presale_orders": "预售订单数",
                "click_users": "商品点击人数", "exposure_click_rate": "曝光点击率",
                "click_conversion_rate": "点击成交率", "gmv_per_1000_exposure": "千次曝光支付金额",
                "pre_ship_refund_orders": "发货前退款订单", "pre_ship_refund_amount": "发货前退款金额",
                "pre_ship_refund_users": "发货前退款人数", "pre_ship_refund_rate": "发货前退款率",
                "post_ship_refund_orders": "发货后退款订单", "post_ship_refund_amount": "发货后退款金额",
                "post_ship_refund_users": "发货后退款人数", "post_ship_refund_rate": "发货后退款率",
            }).sort_values(["用户支付金额", "成交件数"], ascending=False)
            st.dataframe(product_detail, width="stretch", hide_index=True)

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
    st.dataframe(style_summary.rename(columns={"style_code": "货号", "product_name": "商品名称", "ship_amount": "所选范围发货", "return_amount": "所选范围退货", "net_amount": "所选范围实销"}), width="stretch", hide_index=True)

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
            st.image(master_row.iloc[0]["image_url"], width="stretch")
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
    item_metrics[3].metric("所选范围实销", f"¥{item_net:,.0f}")
    anchor_item = item.groupby("anchor_name", as_index=False).agg(
        场次数=("live_room_id", "nunique"), 讲解次数=("talk_count", "sum"), 点击人数=("click_users", "sum"),
        成交件数=("sold_units", "sum"), 支付GMV原始值=("paid_amount", "sum"),
        发货前退款=("pre_ship_refund_amount", "sum"), 发货后退款=("post_ship_refund_amount", "sum"),
    )
    anchor_item["成交件数/讲解"] = anchor_item["成交件数"].div(anchor_item["讲解次数"].replace(0, pd.NA))
    anchor_item["点击成交率"] = anchor_item["成交件数"].div(anchor_item["点击人数"].replace(0, pd.NA))
    st.markdown("#### 主播对比")
    st.dataframe(anchor_item.rename(columns={"anchor_name": "主播"}), width="stretch", hide_index=True)
    st.caption("GMV仅显示原始金额，不计算商品占主播、平台或公司的GMV比例。")

with tabs[5]:
    review = products[products["style_code"].isna() | products["match_status"].isin(["unmatched", "catalog_missing"])][
        ["shop_name", "product_id", "product_name", "style_code", "match_status"]
    ].drop_duplicates()
    st.subheader("待确认商品")
    if review.empty:
        st.success("当前筛选范围内所有商品名称都已识别出货号并通过校验。")
    else:
        st.dataframe(review, width="stretch", hide_index=True)
