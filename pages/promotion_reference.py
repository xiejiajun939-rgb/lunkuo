# -*- coding: utf-8 -*-
import io
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from core.db import load_dimension_mapping, load_product_master, load_product_sales, load_product_tag_periods
from core.promotion import daily_promotion_date_bounds, load_daily_promotion_rows
from core.product_tags import active_product_tags, product_tags_text
from core.theme import page_header
from core.utils import clear_cache_on_page_change
from core.inventory import attach_inventory_summary
from core.interactive_inventory_grid import render_inventory_grid


st.set_page_config(page_title="推广参考", layout="wide")
clear_cache_on_page_change("promotion_reference")
page_header("推广参考", "按日对照抖音店铺整体实销、小店运营实销与商品推广表现", "PROMOTION REFERENCE", "每日更新")

try:
    min_date, max_date = daily_promotion_date_bounds()
except Exception as exc:
    st.error(f"每日推广数据表尚未初始化或读取失败：{exc}")
    st.info("请先执行 sql/20260929_create_promotion_product_daily.sql，再到系统设置上传每日推广商品数据。")
    st.stop()
if not max_date:
    st.info("暂无每日推广数据，请到“系统设置 → 文件与目标”上传。")
    st.stop()

if "promotion_start_date" not in st.session_state:
    st.session_state.promotion_start_date = max(min_date, max_date - timedelta(days=6))
if "promotion_end_date" not in st.session_state:
    st.session_state.promotion_end_date = max_date

with st.container(border=True):
    st.markdown("#### 查询范围")
    quick = st.columns(5)
    for column, days, label in zip(quick[:4], [1, 7, 15, 30], ["单日", "近7天", "近15天", "近30天"]):
        if column.button(label, key=f"promotion_quick_{days}", width="stretch"):
            st.session_state.promotion_end_date = max_date
            st.session_state.promotion_start_date = max(min_date, max_date - timedelta(days=days - 1))
            st.rerun()
    quick[4].caption(f"已有数据：{min_date} 至 {max_date}")
    date_cols = st.columns(2)
    start_date = date_cols[0].date_input("开始日期", min_value=min_date, max_value=max_date, key="promotion_start_date")
    end_date = date_cols[1].date_input("结束日期", min_value=min_date, max_value=max_date, key="promotion_end_date")
if start_date > end_date:
    st.error("开始日期不能晚于结束日期。")
    st.stop()

try:
    promotion = load_daily_promotion_rows(start_date, end_date)
except Exception as exc:
    st.error(f"查询每日推广数据失败：{exc}")
    st.stop()
if promotion.empty:
    st.info(f"{start_date} 至 {end_date} 暂无推广数据。")
    st.stop()

shop_options = sorted(promotion["shop_name"].dropna().astype(str).unique())
master = load_product_master()
tag_period_frame = load_product_tag_periods()
tag_periods = {
    row["tag_name"]: (row["start_date"], row["end_date"])
    for row in tag_period_frame.to_dict("records")
}
tag_map = {}
if not master.empty and {"style_code", "tags"}.issubset(master.columns):
    master = master.copy()
    master["style_code"] = master["style_code"].fillna("").astype(str).str.strip().str.upper()
    tag_map = master[master["style_code"] != ""].drop_duplicates("style_code", keep="last").set_index("style_code")["tags"].to_dict()

filter_cols = st.columns([2, 1, 2])
selected_shops = filter_cols[0].multiselect(
    "抖音店铺", shop_options, default=shop_options, key="promotion_reference_shops_daily"
)
show_inactive_tags = filter_cols[1].checkbox(
    "包含已失效标签", value=False, key="promotion_show_inactive_tags"
)
tag_options = sorted({
    tag for value in tag_map.values()
    for tag in active_product_tags(value, tag_periods, include_inactive=show_inactive_tags)
})
selected_tags = filter_cols[2].multiselect(
    "商品标签", tag_options, key="promotion_product_tag_filter"
)
if not selected_shops:
    st.warning("请至少选择一个店铺。")
    st.stop()
promotion = promotion[promotion["shop_name"].isin(selected_shops)].copy()
promotion["style_code"] = promotion["style_code"].fillna("").astype(str).str.strip().str.upper()
promotion["product_tags"] = promotion["style_code"].map(tag_map).map(
    lambda value: active_product_tags(value, tag_periods, include_inactive=show_inactive_tags)
)
if selected_tags:
    promotion = promotion[promotion["product_tags"].map(
        lambda tags: all(tag in tags for tag in selected_tags)
    )]
if promotion.empty:
    st.info("当前店铺与标签条件下暂无推广商品数据。")
    st.stop()

# Promotion filenames carry the platform shop name, while actual-sales rows use
# the internal shop name.  Reuse the maintained mapping before joining them.
mapping = load_dimension_mapping()
if not mapping.empty and {"platform_shop_name", "shop_name"}.issubset(mapping.columns):
    shop_mapping = mapping[["platform_shop_name", "shop_name"]].dropna().copy()
    shop_mapping["platform_shop_name"] = shop_mapping["platform_shop_name"].astype(str).str.strip().str.upper()
    shop_mapping["shop_name"] = shop_mapping["shop_name"].astype(str).str.strip().str.upper()
    shop_mapping = shop_mapping.drop_duplicates("platform_shop_name")
    promotion = promotion.merge(
        shop_mapping.rename(columns={"platform_shop_name": "shop_name", "shop_name": "sales_shop_name"}),
        on="shop_name", how="left",
    )
else:
    promotion["sales_shop_name"] = promotion["shop_name"]
promotion["sales_shop_name"] = promotion["sales_shop_name"].fillna(promotion["shop_name"])
sales_shop_names = promotion["sales_shop_name"].dropna().astype(str).unique().tolist()

with st.spinner("正在关联相同日期范围的实销数据..."):
    sales = load_product_sales(
        "_all", apply_filter=True, include_offline=False, view_mode=None,
        start_date=start_date, end_date=end_date,
    )
sales_columns = ["shop_name", "style_code", "ship_amount", "return_amount", "net_amount", "dept"]
if sales.empty:
    sales = pd.DataFrame(columns=sales_columns)
for column in sales_columns:
    if column not in sales.columns:
        sales[column] = "" if column in {"shop_name", "style_code", "dept"} else 0.0
sales["shop_name"] = sales["shop_name"].astype("string").fillna("").str.strip().str.upper()
sales["style_code"] = sales["style_code"].astype("string").fillna("").str.strip().str.upper()
sales = sales[sales["shop_name"].isin(sales_shop_names)]

overall = sales.groupby(["shop_name", "style_code"], as_index=False).agg(
    overall_ship=("ship_amount", "sum"), overall_return=("return_amount", "sum"), overall_actual=("net_amount", "sum"))
overall = overall.rename(columns={"shop_name": "sales_shop_name"})
small_mask = sales["dept"].astype("string").fillna("").str.contains("小店运营", na=False)
small = sales[small_mask].groupby(["shop_name", "style_code"], as_index=False).agg(
    small_shop_ship=("ship_amount", "sum"), small_shop_return=("return_amount", "sum"), small_shop_actual=("net_amount", "sum"))
small = small.rename(columns={"shop_name": "sales_shop_name"})
promo_summary = promotion.groupby(["shop_name", "sales_shop_name", "style_code"], as_index=False).agg(
    product_name=("product_name", "first"), impressions=("impressions", "sum"), clicks=("clicks", "sum"),
    spend=("spend", "sum"), gross_gmv=("gross_gmv", "sum"), gross_orders=("gross_orders", "sum"),
    user_paid_amount=("user_paid_amount", "sum"))
detail = promo_summary.merge(overall, on=["sales_shop_name", "style_code"], how="outer").merge(
    small, on=["sales_shop_name", "style_code"], how="left")
detail["shop_name"] = detail["shop_name"].fillna(detail["sales_shop_name"])
detail["商品标签"] = detail["style_code"].map(tag_map).map(
    lambda value: product_tags_text(
        active_product_tags(value, tag_periods, include_inactive=show_inactive_tags)
    )
)
numeric_columns = ["impressions", "clicks", "spend", "gross_gmv", "gross_orders", "user_paid_amount",
                   "overall_ship", "overall_return", "overall_actual", "small_shop_ship", "small_shop_return", "small_shop_actual"]
for column in numeric_columns:
    detail[column] = pd.to_numeric(detail.get(column), errors="coerce").fillna(0.0)
detail["live_ship"] = detail["overall_ship"] - detail["small_shop_ship"]
detail["live_actual"] = detail["overall_actual"] - detail["small_shop_actual"]
detail["small_shop_share"] = np.where(detail["overall_actual"] != 0, detail["small_shop_actual"] / detail["overall_actual"], 0.0)
detail["ctr"] = np.where(detail["impressions"] > 0, detail["clicks"] / detail["impressions"], 0.0)
detail["paid_roi"] = np.where(detail["spend"] > 0, detail["gross_gmv"] / detail["spend"], 0.0)
detail["spend_to_small_shop_actual"] = np.where(detail["small_shop_actual"] > 0, detail["spend"] / detail["small_shop_actual"], 0.0)

kpis = st.columns(6)
kpis[0].metric("抖音整体发货", f"¥{detail['overall_ship'].sum():,.0f}")
kpis[1].metric("小店运营发货", f"¥{detail['small_shop_ship'].sum():,.0f}")
kpis[2].metric("抖音整体实销", f"¥{detail['overall_actual'].sum():,.0f}")
kpis[3].metric("小店运营实销", f"¥{detail['small_shop_actual'].sum():,.0f}")
kpis[4].metric("推广消耗", f"¥{detail['spend'].sum():,.0f}")
kpis[5].metric("推广支付ROI", f"{detail['gross_gmv'].sum() / detail['spend'].sum():.2f}" if detail["spend"].sum() else "-")
st.caption("实销口径：发货金额 − 退货金额；推广成交和ROI为平台归因数据，按所选每日文件汇总。")

display = detail.rename(columns={
    "shop_name": "抖音店铺", "style_code": "货号", "product_name": "商品名称",
    "overall_ship": "整体发货", "small_shop_ship": "小店发货", "live_ship": "直播发货",
    "overall_actual": "整体实销", "small_shop_actual": "小店实销", "live_actual": "直播实销",
    "small_shop_share": "小店贡献率", "spend": "推广消耗", "impressions": "推广展示",
    "clicks": "推广点击", "ctr": "推广CTR", "gross_gmv": "推广成交金额",
    "gross_orders": "推广成交订单", "user_paid_amount": "用户实际支付", "paid_roi": "推广支付ROI",
    "spend_to_small_shop_actual": "消耗/小店实销",
})[["抖音店铺", "货号", "商品名称", "商品标签", "整体发货", "小店发货", "直播发货", "整体实销", "小店实销", "直播实销",
    "小店贡献率", "推广消耗", "推广展示", "推广点击", "推广CTR", "推广成交金额", "推广成交订单", "用户实际支付",
    "推广支付ROI", "消耗/小店实销"]]

style_display = display.groupby("货号", as_index=False).agg({
    "商品名称": "first", "商品标签": "first", "抖音店铺": "nunique", "整体发货": "sum", "小店发货": "sum", "直播发货": "sum",
    "整体实销": "sum", "小店实销": "sum", "直播实销": "sum", "推广消耗": "sum", "推广展示": "sum",
    "推广点击": "sum", "推广成交金额": "sum", "推广成交订单": "sum", "用户实际支付": "sum",
}).rename(columns={"抖音店铺": "覆盖店铺数"})
style_display["小店贡献率"] = np.where(style_display["整体实销"] != 0, style_display["小店实销"] / style_display["整体实销"], 0.0)
style_display["推广CTR"] = np.where(style_display["推广展示"] > 0, style_display["推广点击"] / style_display["推广展示"], 0.0)
style_display["推广支付ROI"] = np.where(style_display["推广消耗"] > 0, style_display["推广成交金额"] / style_display["推广消耗"], 0.0)
style_display["消耗/小店实销"] = np.where(style_display["小店实销"] > 0, style_display["推广消耗"] / style_display["小店实销"], 0.0)
style_display = attach_inventory_summary(style_display.sort_values(["小店实销", "整体实销"], ascending=False), "货号")
display = attach_inventory_summary(display.sort_values(["小店实销", "整体实销"], ascending=False), "货号")

st.markdown("### 货号汇总（所选店铺合计）")
selected_row = render_inventory_grid(style_display, "promotion_daily_style_summary_grid", pinned_columns=("货号", "商品名称"), selectable=True)
if selected_row:
    selected_style = str(selected_row["货号"])
    detail_display = display[display["货号"].astype(str) == selected_style]
    with st.expander(f"{selected_style} · 各抖音店铺明细（{len(detail_display)} 家）", expanded=True):
        render_inventory_grid(detail_display, f"promotion_daily_detail_{selected_style}", pinned_columns=("货号", "抖音店铺"))
else:
    st.info("点击上方货号汇总表中的一行，查看各店铺明细。")

shop_summary = display.groupby("抖音店铺", as_index=False)[["整体实销", "小店实销", "直播实销", "推广消耗", "推广成交金额"]].sum()
chart_data = shop_summary.melt(id_vars="抖音店铺", value_vars=["整体实销", "小店实销", "直播实销"], var_name="实销构成", value_name="金额")
chart = px.bar(chart_data, x="抖音店铺", y="金额", color="实销构成", barmode="group", title="各店铺实销与构成")
chart.update_layout(height=420, xaxis_title="抖音店铺", yaxis_title="金额")
st.plotly_chart(chart, width="stretch")

output = io.BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    style_display.to_excel(writer, index=False, sheet_name="货号汇总")
    display.to_excel(writer, index=False, sheet_name="推广参考")
    shop_summary.to_excel(writer, index=False, sheet_name="店铺汇总")
st.download_button("下载推广参考", output.getvalue(), file_name=f"推广参考_{start_date}_{end_date}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
