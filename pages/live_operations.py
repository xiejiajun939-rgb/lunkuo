"""新版直播经营分析：历史直播表现 × 数据罗盘履约实销。"""
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from core.db import load_product_master
from core.live_analytics import load_live_actuals, load_live_auxiliary, load_live_dataset
from core.theme import page_header
from core.utils import clear_cache_on_page_change


DISPLAY_COLUMN_NAMES = {
    "live_room_id": "直播场次ID", "shop_name": "直播间／店铺", "anchor_name": "主播",
    "start_time": "开播时间", "duration_seconds": "直播时长（秒）", "style_code": "货号",
    "product_id": "商品ID", "product_name": "商品名称", "click_users": "商品点击人数",
    "sold_units": "成交件数", "paid_amount": "平台支付", "talk_count": "讲解次数",
    "pre_ship_refund_amount": "发货前退款", "post_ship_refund_amount": "发货后退款",
    "module": "指标分组", "metric_name": "指标名称", "metric_value": "指标数值",
    "raw_value": "原始值", "unit": "单位", "benchmark_value": "对标数值",
    "benchmark_raw": "对标原始值", "comparison_display": "对比表现", "channel_name": "流量渠道",
    "avg_watch_duration": "人均观看时长", "watch_count": "观看次数",
    "watch_users": "观看人数", "order_count": "成交订单数", "avg_order_amount": "笔单价",
    "watch_conversion_rate": "观看成交率", "shop_bound_spend": "店铺绑定投放消耗",
    "shop_promoted_spend": "店铺被投投放消耗", "product_image_url": "商品主图",
    "talk_start_epoch": "讲解开始时间戳", "talk_end_epoch": "讲解结束时间戳",
    "talk_duration_seconds": "讲解时长（秒）", "viewer_change": "在线人数变化",
    "avg_online_users": "平均在线人数", "session_start_utc": "开播时间",
    "talk_start_time": "讲解开始时间", "ship_amount": "范围发货",
    "return_amount": "范围退货", "net_amount": "范围实销", "sale_date": "销售日期",
    "created_at": "记录时间", "updated_at": "更新时间", "imported_at": "导入时间",
}


def localize_table(frame: pd.DataFrame) -> pd.DataFrame:
    """只调整页面展示：字段中文化，比例按两位小数显示。"""
    if frame is None:
        return pd.DataFrame()
    display = frame.copy().rename(columns=DISPLAY_COLUMN_NAMES)
    for column in display.columns:
        if "率" not in str(column) and "占比" not in str(column):
            continue
        numeric = pd.to_numeric(display[column], errors="coerce")
        if numeric.notna().any():
            display[column] = numeric.map(lambda value: "—" if pd.isna(value) else f"{value:.2%}")
    return display


def show_table(frame: pd.DataFrame) -> None:
    st.dataframe(localize_table(frame), width="stretch", hide_index=True)


st.set_page_config(page_title="直播经营分析", layout="wide")
clear_cache_on_page_change("live_operations")
page_header("直播经营分析", "历史直播表现 × 数据罗盘履约实销", "LIVE OPERATIONS", "新版")

st.markdown("""
<style>
/* 直播经营分析设计系统：覆盖全站旧样式，统一密度与节奏。 */
.main .block-container{max-width:1560px!important;padding:24px 26px 52px!important}
.main div[data-testid="stVerticalBlock"]{gap:12px}
.main div[data-testid="stHorizontalBlock"]{gap:12px}
.main .page-hero{margin:0 0 16px!important;padding:20px 22px!important;border-radius:16px!important;box-shadow:0 6px 24px rgba(12,44,73,.055)!important}
.main .page-hero__title{font-size:26px!important}.main .page-hero__subtitle{font-size:13px!important}
.scope-note{margin:0 0 16px;padding:11px 14px;border:1px solid #d7e4ee;border-radius:10px;background:#f7fafc;color:#526579;font-size:12px;line-height:1.65}
.section-kicker{margin:0 0 2px;color:#10263d;font-size:14px;font-weight:760}.section-help{margin:0 0 10px;color:#6e7e8e;font-size:11px}
.main div[data-testid="stVerticalBlockBorderWrapper"]{border:1px solid #dfe7ee!important;border-radius:14px!important;background:#fff!important;box-shadow:0 6px 22px rgba(16,48,82,.045)!important}
.main div[data-testid="stVerticalBlockBorderWrapper"]>div{padding:16px!important}
.main div[data-testid="stMetric"]{min-height:98px!important;padding:14px 15px!important;border-radius:12px!important;box-shadow:0 4px 16px rgba(16,48,82,.045)!important}
.main div[data-testid="stMetricLabel"]{font-size:12px!important}.main div[data-testid="stMetricValue"]{font-size:23px!important}
.main div[data-testid="stTabs"] [data-baseweb="tab-list"]{width:100%!important;gap:3px!important;padding:4px!important;border-radius:11px!important;background:#eaf0f5!important}
.main div[data-testid="stTabs"] [data-baseweb="tab-list"]>div{overflow-x:auto!important;scrollbar-width:thin}
.main div[data-testid="stTabs"] button[role="tab"]{height:36px!important;padding:0 12px!important;border-radius:8px!important;font-size:12px!important;white-space:nowrap!important}
.main div[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:#0a567d!important;box-shadow:0 2px 7px rgba(12,44,73,.1)!important}
.main [data-testid="stWidgetLabel"] p{font-size:11px!important;font-weight:650!important;color:#647589!important}
.main div[data-baseweb="select"]>div,.main div[data-baseweb="input"]>div{min-height:38px!important;border-radius:8px!important}
.main [data-testid="stSegmentedControl"]{margin-bottom:2px}.main [data-testid="stSegmentedControl"] button{min-height:34px!important;font-size:11px!important}
.main div[data-testid="stDataFrame"]{border-radius:11px!important;box-shadow:none!important;border-color:#dfe7ee!important}
.main div[data-testid="stPlotlyChart"]{padding:8px;border-radius:12px!important;box-shadow:none!important}
.main .stDownloadButton>button{height:38px!important;border-radius:8px!important;font-size:12px!important}
.main h3{margin-top:12px!important;margin-bottom:6px!important;font-size:17px!important}
.main [data-testid="stCaptionContainer"]{margin:2px 0 6px!important}
@media(max-width:900px){.main .block-container{padding:16px 12px 36px!important}.main .page-hero{padding:16px!important}}
</style>
<div class="scope-note">平台支付按直播发生时间统计；发货、退货按仓库发生时间统计。两种口径并列观察，不进行逐日强制对账。</div>
""", unsafe_allow_html=True)

today = date.today()
with st.container(border=True):
    st.markdown('<div class="section-kicker">分析周期</div><div class="section-help">选择快捷周期，或使用自定义日期。</div>', unsafe_allow_html=True)
    quick = st.segmented_control("分析周期", ["近7天", "近15天", "近30天", "本月", "自定义"], default="近30天", label_visibility="collapsed")
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

all_shops = sorted(sessions["shop_name"].dropna().astype(str).unique())
all_anchors = sorted(sessions["anchor_name"].dropna().astype(str).unique())
with st.container(border=True):
    st.markdown('<div class="section-kicker">分析对象</div><div class="section-help">筛选需要比较的直播间与主播。</div>', unsafe_allow_html=True)
    filter_cols = st.columns(2)
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
if not product_master.empty and "style_code" in product_master.columns:
    master_meta = product_master.copy()
    master_meta["style_code"] = master_meta["style_code"].astype(str).str.strip().str.upper()
    if "master_category" in master_meta.columns:
        master_meta["品类"] = master_meta["master_category"]
    elif "product_category" in master_meta.columns:
        master_meta["品类"] = master_meta["product_category"]
    else:
        master_meta["品类"] = None
    for source, target in [("brand", "品牌"), ("year", "年份")]:
        master_meta[target] = master_meta[source] if source in master_meta.columns else None
    master_meta["上新日期"] = master_meta["launch_date"] if "launch_date" in master_meta.columns else None
    master_meta = master_meta[["style_code", "品牌", "年份", "品类", "上新日期"]].drop_duplicates("style_code")
    style_summary = style_summary.merge(master_meta, on="style_code", how="left")
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

# 稳定复销不是单纯的成交场次率排行：同时判断跨周持续性、单场依赖、近期表现和退款健康度。
session_style = products[products["style_code"].notna()].groupby(
    ["style_code", "live_room_id", "直播日期"], as_index=False
).agg(场次成交件数=("sold_units", "sum"), 场次支付=("paid_amount", "sum"))
session_style["有成交"] = session_style["场次成交件数"] > 0
session_style["自然周"] = pd.to_datetime(session_style["直播日期"]).dt.to_period("W-SAT").astype(str)
stability_records = []
for style_code, history in session_style.groupby("style_code"):
    history = history.sort_values("直播日期")
    session_count = history["live_room_id"].nunique()
    sold_sessions = int(history["有成交"].sum())
    sold_units = history["场次成交件数"].sum()
    top_session_share = history["场次成交件数"].max() / sold_units if sold_units else 0
    recent_three_sales = int(history.tail(3)["有成交"].sum())
    stability_records.append({
        "style_code": style_code,
        "复销上播场次": session_count,
        "复销成交场次": sold_sessions,
        "复销成交场次率": sold_sessions / session_count if session_count else 0,
        "成交自然周数": history.loc[history["有成交"], "自然周"].nunique(),
        "最高单场成交占比": top_session_share,
        "最近3场成交场次": recent_three_sales,
    })
style_summary = style_summary.merge(pd.DataFrame(stability_records), on="style_code", how="left")
if "品类" in style_summary.columns:
    category_refund = style_summary.groupby("品类", dropna=False)["退款率"].transform("mean")
else:
    category_refund = pd.Series(style_summary["退款率"].mean(), index=style_summary.index)
style_summary["同品类平均退款率"] = category_refund.fillna(style_summary["退款率"].mean()).fillna(0)

def classify_repeat_sales(row):
    sessions_count = int(row.get("复销上播场次", 0) or 0)
    rate = float(row.get("复销成交场次率", 0) or 0)
    weeks = int(row.get("成交自然周数", 0) or 0)
    top_share = float(row.get("最高单场成交占比", 0) or 0)
    recent = int(row.get("最近3场成交场次", 0) or 0)
    clicks = float(row.get("累计点击", 0) or 0)
    sold_sessions = int(row.get("复销成交场次", 0) or 0)
    sold_units = float(row.get("成交件数", 0) or 0)
    refund = row.get("退款率")
    refund_benchmark = float(row.get("同品类平均退款率", 0) or 0)
    refund_risk = not pd.isna(refund) and float(refund) > refund_benchmark
    risk_note = "；退款率高于同品类平均" if refund_risk else ""
    if sessions_count < 2 or clicks < 20:
        return "样本不足", "上播少于2场或累计点击少于20"
    if sold_sessions >= 3 and recent == 0:
        return "近期转弱", f"历史至少3场成交，但最近3场均未成交{risk_note}"
    if sold_units >= 5 and top_share >= 0.7:
        return "单场爆发", f"累计成交至少5件，且最高单场贡献达到{top_share:.2%}{risk_note}"
    if sessions_count >= 5 and sold_sessions >= 3 and rate >= 0.6 and weeks >= 2 and recent >= 2:
        return "高置信稳定", f"至少5场、3场成交、成交率≥60%、跨2周且最近3场≥2场成交{risk_note}"
    if sessions_count >= 3 and sold_sessions >= 2 and rate >= 0.5 and recent >= 1:
        return "稳定复销", f"至少3场、2场成交、成交率≥50%且最近3场仍有成交{risk_note}"
    if sessions_count >= 2 and sold_sessions >= 1:
        return "有复销潜力", f"至少上播2场并产生过成交，继续积累重复成交样本{risk_note}"
    return "待观察", f"已有一定样本，但尚未形成重复成交{risk_note}"

repeat_classification = style_summary.apply(classify_repeat_sales, axis=1, result_type="expand")
style_summary[["复销分级", "复销判断依据"]] = repeat_classification

metric_wide = metrics.pivot_table(index="live_room_id", columns="metric_name", values="metric_value", aggfunc="sum") if not metrics.empty else pd.DataFrame()

tabs = st.tabs([
    "经营总览", "单场复盘", "直播间对比", "趋势分析", "完整商品分析",
    "前段销售排行", "商品机会", "单款历史档案",
])

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
    labels = sessions.sort_values("start_time", ascending=False).assign(
        场次=lambda frame: frame["start_time"].dt.strftime("%m-%d %H:%M") + "｜" + frame["shop_name"] + "｜" + frame["anchor_name"]
    )
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
        show_table(room_products[["style_code", "product_name", "click_users", "sold_units", "paid_amount", "pre_ship_refund_amount", "post_ship_refund_amount"]].sort_values("paid_amount", ascending=False))
    with detail_tabs[1]:
        show_table(talks[talks["live_room_id"].astype(str) == room].sort_values("talk_start_epoch") if not talks.empty else pd.DataFrame())
    with detail_tabs[2]:
        show_table(channels[channels["live_room_id"].astype(str) == room].sort_values("paid_amount", ascending=False) if not channels.empty else pd.DataFrame())
    with detail_tabs[3]:
        show_table(metrics[metrics["live_room_id"].astype(str) == room][["module", "metric_name", "raw_value", "comparison_display"]])

with tabs[2]:
    room_compare = sessions.groupby(["shop_name", "anchor_name"], as_index=False).agg(场次=("live_room_id", "nunique"), 直播小时=("duration_seconds", lambda x: x.sum()/3600))
    performance = products.groupby(["shop_name", "anchor_name"], as_index=False).agg(商品点击=("click_users", "sum"), 成交件数=("sold_units", "sum"), 平台支付=("paid_amount", "sum"))
    room_compare = room_compare.merge(performance, on=["shop_name", "anchor_name"], how="left")
    room_compare["场均支付"] = room_compare["平台支付"].div(room_compare["场次"].replace(0, pd.NA))
    room_compare["每小时支付"] = room_compare["平台支付"].div(room_compare["直播小时"].replace(0, pd.NA))
    room_compare["点击成交率"] = room_compare["成交件数"].div(room_compare["商品点击"].replace(0, pd.NA))
    show_table(room_compare.sort_values("平台支付", ascending=False))
    st.plotly_chart(px.bar(room_compare, x="shop_name", y="每小时支付", color="anchor_name", title="直播间每小时产出对比", labels={"shop_name": "直播间／店铺", "anchor_name": "主播"}), width="stretch")

with tabs[3]:
    session_pay = products.groupby(["live_room_id", "直播日期"], as_index=False).agg(平台支付=("paid_amount", "sum"), 商品点击=("click_users", "sum"), 成交件数=("sold_units", "sum"))
    session_pay = session_pay.merge(sessions[["live_room_id", "shop_name", "anchor_name"]], on="live_room_id", how="left")
    metric_name = st.selectbox("趋势指标", ["平台支付", "商品点击", "成交件数"])
    st.plotly_chart(px.line(session_pay.sort_values("直播日期"), x="直播日期", y=metric_name, color="anchor_name", markers=True, hover_data=["shop_name", "live_room_id"], labels={"anchor_name": "主播", "shop_name": "直播间／店铺", "live_room_id": "直播场次ID"}), width="stretch")

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
    show_table(table.sort_values("平台支付", ascending=False))

with tabs[5]:
    st.subheader("开播前段商品销售排行")
    rank_cols = st.columns([1.2, 1.2, 1.4, 1.5])
    with rank_cols[0]:
        rank_window = st.segmented_control(
            "统计范围", [15, 30, 60, 90], default=60,
            format_func=lambda value: f"前{value}分钟", key="opening_sales_window",
        )
    with rank_cols[1]:
        rank_by = st.selectbox(
            "排序指标", ["前段成交金额", "前段成交件数", "成交场次率", "支付/讲解分钟", "在线上升场次占比"]
        )
    with rank_cols[2]:
        minimum_room_count = st.slider("最少出现直播场次", 1, 10, 1, key="opening_min_rooms")
    with rank_cols[3]:
        launch_day_mode = st.selectbox(
            "上新当天口径", ["全部销售", "排除上新当天", "只看上新当天"],
            key="opening_launch_day_mode",
        )

    opening_talks = talks[talks["开播后分钟"] <= rank_window].copy() if not talks.empty else pd.DataFrame()
    if opening_talks.empty:
        st.warning("当前范围没有商品讲解区间数据，上传新版直播工作簿后才能生成排行。")
    else:
        opening_room = opening_talks.groupby(["style_code", "live_room_id"], as_index=False).agg(
            直播日期=("session_start_utc", lambda values: values.iloc[0].date() if len(values) else None),
            讲解次数=("product_id", "size"), 讲解分钟=("讲解分钟", "sum"),
            前段成交金额=("paid_amount", "sum"), 前段成交件数=("sold_units", "sum"),
            在线净变化=("viewer_change", "sum"), 分均在线人数=("avg_online_users", "mean"),
        )
        opening_room["有成交"] = opening_room["前段成交件数"] > 0
        opening_room["在线上升"] = opening_room["在线净变化"] > 0
        launch_lookup = style_summary[["style_code", "上新日期"]].drop_duplicates("style_code") if "上新日期" in style_summary else pd.DataFrame(columns=["style_code", "上新日期"])
        opening_room = opening_room.merge(launch_lookup, on="style_code", how="left")
        opening_room["上新日期"] = pd.to_datetime(opening_room["上新日期"], errors="coerce").dt.date
        opening_room["上新当天"] = opening_room["上新日期"].notna() & (opening_room["直播日期"] == opening_room["上新日期"])
        opening_room["日期异常"] = opening_room["上新日期"].notna() & (opening_room["直播日期"] < opening_room["上新日期"])

        launch_effect = opening_room.groupby("style_code", as_index=False).agg(
            原始前段成交金额=("前段成交金额", "sum"),
            上新当天成交金额=("前段成交金额", lambda values: values[opening_room.loc[values.index, "上新当天"]].sum()),
            原始前段成交件数=("前段成交件数", "sum"),
            上新当天成交件数=("前段成交件数", lambda values: values[opening_room.loc[values.index, "上新当天"]].sum()),
        )
        launch_effect["排除后成交金额"] = launch_effect["原始前段成交金额"] - launch_effect["上新当天成交金额"]
        launch_effect["排除后成交件数"] = launch_effect["原始前段成交件数"] - launch_effect["上新当天成交件数"]
        launch_effect["上新当天金额占比"] = launch_effect["上新当天成交金额"].div(launch_effect["原始前段成交金额"].replace(0, pd.NA))

        analysis_room = opening_room[~opening_room["日期异常"]].copy()
        if launch_day_mode == "排除上新当天":
            analysis_room = analysis_room[~analysis_room["上新当天"]]
        elif launch_day_mode == "只看上新当天":
            analysis_room = analysis_room[analysis_room["上新当天"]]

        opening_rank = analysis_room.groupby("style_code", as_index=False).agg(
            前段出现场次=("live_room_id", "nunique"), 前段成交场次=("有成交", "sum"),
            前段讲解次数=("讲解次数", "sum"), 前段讲解分钟=("讲解分钟", "sum"),
            前段成交金额=("前段成交金额", "sum"), 前段成交件数=("前段成交件数", "sum"),
            在线净变化=("在线净变化", "sum"), 平均在线变化=("在线净变化", "mean"),
            在线上升场次占比=("在线上升", "mean"), 分均在线人数=("分均在线人数", "mean"),
        )
        opening_rank["成交场次率"] = opening_rank["前段成交场次"].div(opening_rank["前段出现场次"].replace(0, pd.NA))
        opening_rank["支付/讲解分钟"] = opening_rank["前段成交金额"].div(opening_rank["前段讲解分钟"].replace(0, pd.NA))
        opening_rank["成交件数/讲解分钟"] = opening_rank["前段成交件数"].div(opening_rank["前段讲解分钟"].replace(0, pd.NA))
        context_column_names = [
            "style_code", "商品名称", "累计点击", "平台退款", "退款率",
            "ship_amount", "return_amount", "net_amount", "品牌", "年份", "品类", "上新日期",
        ]
        context_columns = style_summary[[column for column in context_column_names if column in style_summary.columns]]
        opening_rank = opening_rank.merge(context_columns, on="style_code", how="left").merge(
            launch_effect, on="style_code", how="left"
        )
        dimension_cols = st.columns(3)
        selected_brands = dimension_cols[0].multiselect(
            "品牌", sorted(opening_rank["品牌"].dropna().astype(str).unique()), key="opening_brands"
        ) if "品牌" in opening_rank else []
        selected_categories = dimension_cols[1].multiselect(
            "品类", sorted(opening_rank["品类"].dropna().astype(str).unique()), key="opening_categories"
        ) if "品类" in opening_rank else []
        selected_years = dimension_cols[2].multiselect(
            "年份", sorted(opening_rank["年份"].dropna().astype(str).unique()), key="opening_years"
        ) if "年份" in opening_rank else []
        if selected_brands:
            opening_rank = opening_rank[opening_rank["品牌"].astype(str).isin(selected_brands)]
        if selected_categories:
            opening_rank = opening_rank[opening_rank["品类"].astype(str).isin(selected_categories)]
        if selected_years:
            opening_rank = opening_rank[opening_rank["年份"].astype(str).isin(selected_years)]
        opening_rank = opening_rank[opening_rank["前段出现场次"] >= minimum_room_count]
        opening_rank = opening_rank.sort_values(rank_by, ascending=False).reset_index(drop=True)
        opening_rank.insert(0, "排名", opening_rank.index + 1)

        total_opening_pay = opening_rank["前段成交金额"].sum()
        total_opening_units = opening_rank["前段成交件数"].sum()
        top_ten_share = opening_rank.head(10)["前段成交金额"].sum() / total_opening_pay if total_opening_pay else 0
        total_talk_minutes = opening_rank["前段讲解分钟"].sum()
        summary_cards = st.columns(5)
        summary_cards[0].metric(f"前{rank_window}分钟成交金额", f"¥{total_opening_pay:,.0f}")
        summary_cards[1].metric("成交件数", f"{total_opening_units:,.0f}")
        summary_cards[2].metric("有成交商品", f"{(opening_rank['前段成交件数'] > 0).sum():,}")
        summary_cards[3].metric("前10商品金额占比", f"{top_ten_share:.2%}")
        summary_cards[4].metric("平均分钟产出", f"¥{total_opening_pay / total_talk_minutes:,.0f}" if total_talk_minutes else "—")

        unique_opening_styles = opening_room["style_code"].nunique()
        dated_opening_styles = opening_room.loc[opening_room["上新日期"].notna(), "style_code"].nunique()
        launch_day_pay = opening_room.loc[opening_room["上新当天"], "前段成交金额"].sum()
        launch_cards = st.columns(3)
        launch_cards[0].metric("上新日期识别覆盖", f"{dated_opening_styles}/{unique_opening_styles}款")
        launch_cards[1].metric("上新当天前段成交", f"¥{launch_day_pay:,.0f}")
        launch_cards[2].metric("排除后前段成交", f"¥{opening_room['前段成交金额'].sum() - launch_day_pay:,.0f}")

        st.caption(
            f"“前{rank_window}分钟”按讲解开始时间归入；跨越边界的讲解区间整段计入。"
            f"当前上新口径：{launch_day_mode}。直播日期等于商品上新日期时判定为上新当天；"
            "上新日期晚于直播日期的数据标记异常并排除。累计点击、平台退款为整场指标；"
            "范围发货、退货和实销为所选日期范围履约数据。"
        )
        display_rank = opening_rank.rename(columns={
            "style_code": "货号", "累计点击": "整场累计点击", "平台退款": "整场平台退款",
            "退款率": "整场退款率", "ship_amount": "范围发货", "return_amount": "范围退货",
            "net_amount": "范围实销",
        })
        show_table(display_rank)
        st.download_button(
            f"下载前{rank_window}分钟商品销售排行",
            display_rank.to_csv(index=False).encode("utf-8-sig"),
            f"直播前{rank_window}分钟商品销售排行_{start_date}_{end_date}.csv",
            "text/csv", key="download_opening_sales_rank",
        )

        if opening_rank.empty:
            st.info("当前筛选条件下没有符合要求的商品。")
        else:
            evidence_style = st.selectbox(
                "查看货号逐场证据", opening_rank["style_code"].astype(str).tolist(),
                format_func=lambda code: f"{code}｜{opening_rank.loc[opening_rank['style_code'].astype(str) == code, '商品名称'].iloc[0]}",
                key="opening_evidence_style",
            )
            evidence = analysis_room[analysis_room["style_code"].astype(str) == evidence_style].merge(
                sessions[["live_room_id", "shop_name", "anchor_name"]], on="live_room_id", how="left"
            )
            show_table(evidence.sort_values("直播日期", ascending=False))

with tabs[6]:
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
        if opportunity != "稳定复销":
            candidates = candidates[(candidates["上播场次"] >= min_sessions) & (candidates["累计点击"] >= min_clicks)]
    if opportunity == "讲解高效": candidates = candidates.sort_values(["支付/讲解分钟", "成交件数/讲解分钟"], ascending=False)
    elif opportunity == "在线提升": candidates = candidates.sort_values(["在线上升场次占比", "平均在线变化"], ascending=False)
    elif opportunity == "高转化": candidates = candidates.sort_values("点击成交率", ascending=False)
    elif opportunity == "高引流": candidates = candidates.sort_values("累计点击", ascending=False)
    elif opportunity == "稳定复销":
        stability_order = {
            "高置信稳定": 0, "稳定复销": 1, "有复销潜力": 2,
            "单场爆发": 3, "近期转弱": 4, "待观察": 5, "样本不足": 6,
        }
        candidates["复销排序"] = candidates["复销分级"].map(stability_order).fillna(9)
        candidates = candidates.sort_values(
            ["复销排序", "复销成交场次率", "复销上播场次"], ascending=[True, False, False]
        ).drop(columns="复销排序")
        level_counts = candidates["复销分级"].value_counts()
        stability_levels = ["高置信稳定", "稳定复销", "有复销潜力", "单场爆发", "近期转弱", "待观察", "样本不足"]
        level_options = [f"{label} · {int(level_counts.get(label, 0))}" for label in stability_levels]
        selected_level_option = st.segmented_control(
            "复销分类（点击查看具体款式）", level_options,
            default=f"稳定复销 · {int(level_counts.get('稳定复销', 0))}",
            key="stability_level_filter",
        )
        selected_stability_level = selected_level_option.rsplit(" · ", 1)[0]
        candidates = candidates[candidates["复销分级"] == selected_stability_level].copy()
        st.caption(
            "稳定复销：至少3场、至少2场成交、成交场次率≥50%，且最近3场仍有成交。"
            "高置信稳定：至少5场、至少3场成交、成交场次率≥60%、跨2周，且最近3场至少2场成交。"
            "退款率仅作为风险提示，不再否决复销分级。"
        )
    elif opportunity == "高点击低成交": candidates = candidates[candidates["点击成交率"] < .03].sort_values("累计点击", ascending=False)
    elif opportunity == "退款风险": candidates = candidates.sort_values("退款率", ascending=False)
    if opportunity in ["讲解高效", "在线提升", "开播阶段"] and talks.empty:
        st.warning("当前范围没有新版商品讲解区间数据，上传新版直播工作簿后才能计算。")
    show_table(candidates)
    if opportunity == "稳定复销":
        if candidates.empty:
            st.info(f"当前没有“{selected_stability_level}”商品。")
        else:
            repeat_style = st.selectbox(
                "选择货号查看逐场证据",
                candidates["style_code"].astype(str).tolist(),
                format_func=lambda code: (
                    f"{code}｜{candidates.loc[candidates['style_code'].astype(str) == code, '商品名称'].iloc[0]}"
                ),
                key="repeat_sales_evidence_style",
            )
            repeat_evidence = session_style[session_style["style_code"].astype(str) == repeat_style].merge(
                sessions[["live_room_id", "shop_name", "anchor_name"]], on="live_room_id", how="left"
            )
            repeat_evidence["该场成交占比"] = repeat_evidence["场次成交件数"].div(
                repeat_evidence["场次成交件数"].sum() or pd.NA
            )
            show_table(repeat_evidence.sort_values("直播日期", ascending=False))

with tabs[7]:
    options = style_summary.sort_values("平台支付", ascending=False)["style_code"].astype(str).tolist()
    selected_style = st.selectbox("选择货号", options)
    item = products[products["style_code"].astype(str) == selected_style].copy()
    summary_row = style_summary[style_summary["style_code"].astype(str) == selected_style].iloc[0]
    cards = st.columns(5)
    cards[0].metric("历史上播场次", f"{summary_row['上播场次']:.0f}")
    cards[1].metric("成交场次率", f"{summary_row['成交场次率']:.2%}")
    cards[2].metric("点击成交率", f"{summary_row['点击成交率']:.2%}")
    cards[3].metric("平台支付", f"¥{summary_row['平台支付']:,.0f}")
    cards[4].metric("范围实销", f"¥{summary_row['net_amount']:,.0f}")
    anchor_item = item.groupby("anchor_name", as_index=False).agg(场次=("live_room_id", "nunique"), 点击=("click_users", "sum"), 成交件数=("sold_units", "sum"), 平台支付=("paid_amount", "sum"))
    anchor_item["点击成交率"] = anchor_item["成交件数"].div(anchor_item["点击"].replace(0, pd.NA))
    anchor_item["该货号占主播成交"] = anchor_item.apply(lambda r: r["成交件数"] / products.loc[products["anchor_name"] == r["anchor_name"], "sold_units"].sum() if products.loc[products["anchor_name"] == r["anchor_name"], "sold_units"].sum() else pd.NA, axis=1)
    anchor_item["主播占该货号成交"] = anchor_item["成交件数"].div(anchor_item["成交件数"].sum() or pd.NA)
    st.subheader("主播适配与占比")
    show_table(anchor_item.sort_values("成交件数", ascending=False))
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
        efficiency[4].metric("在线上升区间占比", f"{item_talks['在线上升'].mean():.2%}")
        show_table(
            item_talks[["live_room_id", "开播后分钟", "讲解分钟", "paid_amount", "sold_units", "viewer_change", "avg_online_users"]]
            .sort_values(["live_room_id", "开播后分钟"])
        )
    st.subheader("逐场历史")
    show_table(item[["直播日期", "shop_name", "anchor_name", "talk_count", "click_users", "sold_units", "paid_amount", "pre_ship_refund_amount", "post_ship_refund_amount"]].sort_values("直播日期", ascending=False))

csv = style_summary.to_csv(index=False).encode("utf-8-sig")
st.download_button("下载当前商品分析", csv, f"直播经营商品分析_{start_date}_{end_date}.csv", "text/csv")
