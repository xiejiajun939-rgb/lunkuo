# -*- coding: utf-8 -*-
import io
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from core.db import load_product_sales
from core.promotion import completed_week_starts, load_promotion_rows, week_label
from core.theme import page_header
from core.utils import clear_cache_on_page_change


st.set_page_config(page_title="推广参考", layout="wide")
clear_cache_on_page_change("promotion_reference")
page_header(
    "推广参考",
    "按完整自然周对照抖音店铺整体实销、小店运营实销与商品推广表现",
    "PROMOTION REFERENCE",
    "周度复盘",
)

week_options = completed_week_starts()
selected_week = st.selectbox(
    "查询周期",
    week_options,
    format_func=week_label,
    key="promotion_reference_week",
)
week_end = selected_week + timedelta(days=6)

try:
    promotion = load_promotion_rows(selected_week)
except Exception as exc:
    st.error(f"推广数据表尚未初始化或读取失败：{exc}")
    st.info("请先执行仓库中的 promotion_reference.sql，再到系统设置上传推广数据。")
    st.stop()

if promotion.empty:
    st.info(f"{week_label(selected_week)} 暂无推广数据，请到“系统设置 → 文件与目标”上传。")
    st.stop()

shop_options = sorted(promotion["shop_name"].dropna().astype(str).unique())
# 多个管理员会陆续上传新店铺。Streamlit 会保留旧的 multiselect 状态，
# 因此仅在可选店铺集合发生变化时，把新出现的店铺补入已选列表；
# 平时用户手动取消某店后，不会在页面重跑时被强制选回。
previous_shop_options = st.session_state.get("_promotion_reference_shop_options", [])
if previous_shop_options != shop_options:
    current_selected = st.session_state.get("promotion_reference_shops", previous_shop_options)
    retained = [shop for shop in current_selected if shop in shop_options]
    newly_available = [
        shop for shop in shop_options
        if shop not in previous_shop_options and shop not in retained
    ]
    st.session_state["promotion_reference_shops"] = retained + newly_available
    st.session_state["_promotion_reference_shop_options"] = shop_options
selected_shops = st.multiselect(
    "抖音店铺", shop_options, default=shop_options, key="promotion_reference_shops"
)
if not selected_shops:
    st.warning("请至少选择一个店铺。")
    st.stop()

promotion = promotion[promotion["shop_name"].isin(selected_shops)].copy()
if promotion.empty:
    st.warning("没有符合当前筛选条件的推广数据。")
    st.stop()

with st.spinner("正在关联实销数据..."):
    sales = load_product_sales(
        "_all", apply_filter=True, include_offline=False, view_mode=None,
        start_date=selected_week, end_date=week_end,
    )

sales_columns = ["shop_name", "style_code", "ship_amount", "return_amount", "net_amount", "dept"]
if sales.empty:
    sales = pd.DataFrame(columns=sales_columns)
for column in sales_columns:
    if column not in sales.columns:
        sales[column] = "" if column in {"shop_name", "style_code", "dept"} else 0.0
sales["shop_name"] = sales["shop_name"].astype("string").fillna("").str.strip().str.upper()
sales["style_code"] = sales["style_code"].astype("string").fillna("").str.strip().str.upper()
sales = sales[sales["shop_name"].isin(selected_shops)]

overall = sales.groupby(["shop_name", "style_code"], as_index=False).agg(
    overall_ship=("ship_amount", "sum"),
    overall_return=("return_amount", "sum"),
    overall_actual=("net_amount", "sum"),
)
small_mask = sales["dept"].astype("string").fillna("").str.contains("小店运营", na=False)
small = sales[small_mask].groupby(["shop_name", "style_code"], as_index=False).agg(
    small_shop_ship=("ship_amount", "sum"),
    small_shop_return=("return_amount", "sum"),
    small_shop_actual=("net_amount", "sum"),
)

promo_summary = promotion.groupby(["shop_name", "style_code"], as_index=False).agg(
    product_name=("product_name", "first"),
    impressions=("impressions", "sum"),
    clicks=("clicks", "sum"),
    spend=("spend", "sum"),
    gross_gmv=("gross_gmv", "sum"),
    net_gmv=("net_gmv", "sum"),
)
detail = promo_summary.merge(overall, on=["shop_name", "style_code"], how="outer")
detail = detail.merge(small, on=["shop_name", "style_code"], how="left")
numeric_columns = [
    "impressions", "clicks", "spend", "gross_gmv", "net_gmv",
    "overall_ship", "overall_return", "overall_actual",
    "small_shop_ship", "small_shop_return", "small_shop_actual",
]
for column in numeric_columns:
    detail[column] = pd.to_numeric(detail.get(column), errors="coerce").fillna(0.0)
detail["live_actual"] = detail["overall_actual"] - detail["small_shop_actual"]
detail["live_ship"] = detail["overall_ship"] - detail["small_shop_ship"]
detail["small_shop_share"] = np.where(
    detail["overall_actual"] != 0, detail["small_shop_actual"] / detail["overall_actual"], 0.0
)
detail["ctr"] = np.where(detail["impressions"] > 0, detail["clicks"] / detail["impressions"], 0.0)
detail["net_roi"] = np.where(detail["spend"] > 0, detail["net_gmv"] / detail["spend"], 0.0)
detail["spend_to_small_shop_actual"] = np.where(
    detail["small_shop_actual"] > 0, detail["spend"] / detail["small_shop_actual"], 0.0
)

overall_actual = detail["overall_actual"].sum()
small_actual = detail["small_shop_actual"].sum()
overall_ship = detail["overall_ship"].sum()
small_ship = detail["small_shop_ship"].sum()
spend = detail["spend"].sum()
net_gmv = detail["net_gmv"].sum()
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("抖音整体发货", f"¥{overall_ship:,.0f}")
k2.metric("小店运营发货", f"¥{small_ship:,.0f}")
k3.metric("抖音整体实销", f"¥{overall_actual:,.0f}")
k4.metric("小店运营实销", f"¥{small_actual:,.0f}")
k5.metric("推广消耗", f"¥{spend:,.0f}")
k6.metric("推广净ROI", f"{net_gmv / spend:.2f}" if spend else "-")
st.caption("实销口径：发货金额 − 退货金额；推广成交及ROI为平台归因数据，仅作推广参考，不参与实销拆分。")

display = detail.rename(columns={
    "shop_name": "抖音店铺", "style_code": "货号", "product_name": "商品名称",
    "overall_ship": "整体发货", "overall_return": "整体退货", "overall_actual": "整体实销",
    "small_shop_ship": "小店发货", "small_shop_return": "小店退货", "small_shop_actual": "小店实销",
    "live_ship": "直播发货", "live_actual": "直播实销", "small_shop_share": "小店贡献率",
    "impressions": "推广展示", "clicks": "推广点击", "ctr": "推广CTR", "spend": "推广消耗",
    "gross_gmv": "推广整体成交", "net_gmv": "推广净成交", "net_roi": "推广净ROI",
    "spend_to_small_shop_actual": "消耗/小店实销",
})
display_columns = [
    "抖音店铺", "货号", "商品名称",
    "整体发货", "小店发货", "直播发货", "整体实销", "小店实销", "直播实销", "小店贡献率",
    "推广消耗", "推广展示", "推广点击", "推广CTR", "推广净成交", "推广净ROI", "消耗/小店实销",
]
display = display[display_columns].sort_values(["小店实销", "整体实销"], ascending=False)

style_summary = detail.groupby("style_code", as_index=False).agg(
    product_name=("product_name", lambda values: next((str(v) for v in values if pd.notna(v) and str(v).strip()), "")),
    shop_count=("shop_name", "nunique"),
    overall_ship=("overall_ship", "sum"),
    small_shop_ship=("small_shop_ship", "sum"),
    live_ship=("live_ship", "sum"),
    overall_actual=("overall_actual", "sum"),
    small_shop_actual=("small_shop_actual", "sum"),
    live_actual=("live_actual", "sum"),
    impressions=("impressions", "sum"),
    clicks=("clicks", "sum"),
    spend=("spend", "sum"),
    net_gmv=("net_gmv", "sum"),
)
style_summary["small_shop_share"] = np.where(
    style_summary["overall_actual"] != 0,
    style_summary["small_shop_actual"] / style_summary["overall_actual"],
    0.0,
)
style_summary["ctr"] = np.where(
    style_summary["impressions"] > 0,
    style_summary["clicks"] / style_summary["impressions"],
    0.0,
)
style_summary["net_roi"] = np.where(
    style_summary["spend"] > 0,
    style_summary["net_gmv"] / style_summary["spend"],
    0.0,
)
style_summary["spend_to_small_shop_actual"] = np.where(
    style_summary["small_shop_actual"] > 0,
    style_summary["spend"] / style_summary["small_shop_actual"],
    0.0,
)

style_display = style_summary.rename(columns={
    "style_code": "货号", "product_name": "商品名称", "shop_count": "覆盖店铺数",
    "overall_ship": "整体发货", "small_shop_ship": "小店发货", "live_ship": "直播发货",
    "overall_actual": "整体实销", "small_shop_actual": "小店实销", "live_actual": "直播实销",
    "small_shop_share": "小店贡献率", "impressions": "推广展示", "clicks": "推广点击",
    "ctr": "推广CTR", "spend": "推广消耗", "net_gmv": "推广净成交",
    "net_roi": "推广净ROI", "spend_to_small_shop_actual": "消耗/小店实销",
})[[
    "货号", "商品名称", "覆盖店铺数",
    "整体发货", "小店发货", "直播发货", "整体实销", "小店实销", "直播实销", "小店贡献率",
    "推广消耗", "推广展示", "推广点击", "推广CTR", "推广净成交", "推广净ROI", "消耗/小店实销",
]].sort_values(["小店实销", "整体实销"], ascending=False).reset_index(drop=True)

common_column_config = {
    column: st.column_config.NumberColumn(column, format="¥%.2f")
    for column in [
        "整体发货", "小店发货", "直播发货",
        "整体实销", "小店实销", "直播实销", "推广消耗", "推广净成交",
    ]
} | {
    "小店贡献率": st.column_config.NumberColumn("小店贡献率", format="percent"),
    "推广CTR": st.column_config.NumberColumn("推广CTR", format="percent"),
    "推广净ROI": st.column_config.NumberColumn("推广净ROI", format="%.2f"),
    "消耗/小店实销": st.column_config.NumberColumn("消耗/小店实销", format="percent"),
    "推广展示": st.column_config.NumberColumn("推广展示", format="%d"),
    "推广点击": st.column_config.NumberColumn("推广点击", format="%d"),
    "覆盖店铺数": st.column_config.NumberColumn("覆盖店铺数", format="%d"),
}

st.markdown("### 货号汇总（所选店铺合计）")
st.caption("同一货号在所选抖音店铺中合并展示；点击一行，即可在下方查看该货号的各店铺明细。")
summary_event = st.dataframe(
    style_display, use_container_width=True, hide_index=True,
    column_config=common_column_config,
    on_select="rerun",
    selection_mode="single-row",
    key="promotion_reference_style_summary",
)

selected_rows = list(summary_event.selection.rows)
if selected_rows:
    selected_position = selected_rows[0]
    if 0 <= selected_position < len(style_display):
        selected_style = str(style_display.iloc[selected_position]["货号"])
        product_value = style_display.iloc[selected_position]["商品名称"]
        selected_product = "" if pd.isna(product_value) else str(product_value)
        detail_display = display[display["货号"].astype(str) == selected_style].copy()
        with st.expander(
            f"📂 {selected_style} · 各抖音店铺明细（{len(detail_display)} 家）",
            expanded=True,
        ):
            if selected_product and selected_product.lower() not in {"nan", "none"}:
                st.caption(selected_product)
            st.dataframe(
                detail_display, use_container_width=True, hide_index=True,
                column_config=common_column_config,
            )
else:
    st.info("请点击上方货号汇总表中的一行，查看该货号在各抖音店铺的明细。")

shop_summary = detail.groupby("shop_name", as_index=False).agg(
    整体实销=("overall_actual", "sum"), 小店实销=("small_shop_actual", "sum"),
    直播实销=("live_actual", "sum"), 推广消耗=("spend", "sum"), 推广净成交=("net_gmv", "sum"),
)
chart_data = shop_summary.melt(
    id_vars="shop_name", value_vars=["整体实销", "小店实销", "直播实销"],
    var_name="实销构成", value_name="金额",
)
chart = px.bar(chart_data, x="shop_name", y="金额", color="实销构成", barmode="group", title="各店铺实销与构成")
chart.update_layout(height=420, xaxis_title="抖音店铺", yaxis_title="金额")
st.plotly_chart(chart, use_container_width=True)

output = io.BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    style_display.to_excel(writer, index=False, sheet_name="货号汇总")
    display.to_excel(writer, index=False, sheet_name="推广参考")
    shop_summary.rename(columns={"shop_name": "抖音店铺"}).to_excel(writer, index=False, sheet_name="店铺汇总")
st.download_button(
    "📥 下载本周推广参考",
    data=output.getvalue(),
    file_name=f"推广参考_{selected_week}_{week_end}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
