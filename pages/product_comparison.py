# -*- coding: utf-8 -*-
import io
from datetime import date

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from core.db import get_sales_date_range, load_product_master, load_product_sales
try:
    from core.db import load_product_sales_cube
except ImportError:
    # 兼容 Streamlit Cloud 在滚动部署过程中短暂缓存旧版 core.db。
    def load_product_sales_cube(start_date, end_date, apply_filter=True):
        return load_product_sales(
            "_all", apply_filter=apply_filter, include_offline=False,
            start_date=start_date, end_date=end_date,
        )
from core.theme import page_header
from core.utils import clear_cache_on_page_change, date_quick_buttons


st.set_page_config(page_title="商品销售对比", layout="wide")
clear_cache_on_page_change("product_comparison")
page_header(
    "商品销售对比",
    "对比多个主播、组织、部门或店铺在单品层面的销售表现",
    "PRODUCT BENCHMARK",
    "多对象对比",
)

min_date, max_date = get_sales_date_range("_all")
if min_date is None or max_date is None:
    st.warning("暂无销售数据")
    st.stop()

default_start = max(min_date, max_date.replace(day=1))
date_quick_buttons(
    "compare_start", "compare_end",
    default_start=default_start, default_end=max_date,
    min_date=min_date, max_date=max_date,
)
start_date = st.session_state.get("compare_start", default_start)
end_date = st.session_state.get("compare_end", max_date)

with st.spinner("加载本月商品销售数据..."):
    sales = load_product_sales_cube(start_date, end_date)
if sales.empty:
    st.warning("当前日期范围没有商品销售数据")
    st.stop()

if "anchor_display" not in sales.columns:
    anchor = sales.get("anchor", pd.Series("NONE", index=sales.index)).fillna("NONE").astype(str)
    missing = anchor.str.upper().isin(["", "NONE", "NAN", "<NA>"])
    sales["anchor_display"] = anchor
    sales.loc[missing, "anchor_display"] = (
        "未识别主播｜" + sales.loc[missing, "shop_name"].fillna("未知店铺").astype(str)
    )

dimension_fields = {
    "主播": "anchor_display",
    "组织": "org_name",
    "部门": "dept",
    "店铺": "shop_name",
}

filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([1, 2, 1, 2])
with filter_col1:
    compare_type = st.selectbox("对比对象类型", list(dimension_fields), key="compare_type")
dimension_field = dimension_fields[compare_type]
with filter_col2:
    object_options = sorted(sales[dimension_field].dropna().astype(str).unique())
    selected_objects = st.multiselect(
        f"选择至少两个{compare_type}", object_options, key="compare_objects"
    )
with filter_col3:
    metric = st.selectbox(
        "表格主指标", ["净销售额", "发货额", "退货额", "订单数", "退货率"],
        key="compare_metric",
    )
with filter_col4:
    style_search = st.text_input("货号筛选", placeholder="支持多个货号，用逗号分隔")

if len(selected_objects) < 2:
    st.info(f"请选择至少两个{compare_type}开始对比")
    st.stop()

sales = sales[sales[dimension_field].astype(str).isin(selected_objects)].copy()
if style_search.strip():
    codes = [item.strip().upper() for item in style_search.split(",") if item.strip()]
    sales = sales[sales["style_code"].astype(str).str.upper().isin(codes)]
if sales.empty:
    st.warning("没有符合条件的商品数据")
    st.stop()

detail = sales.groupby(["style_code", dimension_field], as_index=False).agg(
    发货额=("ship_amount", "sum"),
    退货额=("return_amount", "sum"),
    净销售额=("net_amount", "sum"),
    订单数=("order_count", "sum"),
)
detail["退货率"] = np.where(detail["发货额"] > 0, detail["退货额"] / detail["发货额"] * 100, 0)

pivot = detail.pivot_table(
    index="style_code", columns=dimension_field, values=metric, aggfunc="sum", fill_value=0
).reindex(columns=selected_objects, fill_value=0)
pivot["合计"] = pivot.sum(axis=1)
pivot["表现最好"] = pivot[selected_objects].idxmax(axis=1)
pivot = pivot.sort_values("合计", ascending=False).reset_index().rename(columns={"style_code": "货号"})

master = load_product_master()
if not master.empty and {"style_code", "image_url"}.issubset(master.columns):
    master = master.copy()
    master["style_code"] = master["style_code"].astype(str).str.strip().str.upper()
    image_map = master.drop_duplicates("style_code", keep="last").set_index("style_code")["image_url"]
    pivot.insert(1, "商品图片", pivot["货号"].astype(str).str.upper().map(image_map))

total_net = sales["net_amount"].sum()
total_ship = sales["ship_amount"].sum()
total_return = sales["return_amount"].sum()
k1, k2, k3, k4 = st.columns(4)
k1.metric("对比对象", f"{len(selected_objects)} 个")
k2.metric("涉及商品", f"{sales['style_code'].nunique()} 款")
k3.metric("净销售额", f"¥{total_net:,.0f}")
k4.metric("综合退货率", f"{total_return / total_ship * 100:.1f}%" if total_ship else "-")

st.markdown(f"#### 单品 × {compare_type}对比（{metric}）")
column_config = {
    "商品图片": st.column_config.ImageColumn("商品图片", width="small"),
    "合计": st.column_config.NumberColumn("合计", format="%.2f"),
}
for item in selected_objects:
    column_config[item] = st.column_config.NumberColumn(item, format="%.2f")
st.dataframe(pivot, use_container_width=True, hide_index=True, column_config=column_config)

top_styles = pivot.head(15)["货号"].tolist()
chart_data = detail[detail["style_code"].isin(top_styles)].copy()
fig = px.bar(
    chart_data,
    x="style_code", y=metric, color=dimension_field,
    barmode="group",
    labels={"style_code": "货号", dimension_field: compare_type},
    title=f"TOP 15 商品{metric}对比",
)
fig.update_layout(height=460, legend_title=compare_type)
st.plotly_chart(fig, use_container_width=True)

trend = sales.groupby(["sale_date", dimension_field], as_index=False)["net_amount"].sum()
trend_fig = px.line(
    trend, x="sale_date", y="net_amount", color=dimension_field, markers=True,
    labels={"sale_date": "日期", "net_amount": "净销售额", dimension_field: compare_type},
    title=f"{compare_type}净销售趋势",
)
trend_fig.update_layout(height=400, hovermode="x unified")
st.plotly_chart(trend_fig, use_container_width=True)

output = io.BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    pivot.drop(columns=["商品图片"], errors="ignore").to_excel(writer, index=False, sheet_name="商品对比")
    detail.rename(columns={dimension_field: compare_type, "style_code": "货号"}).to_excel(
        writer, index=False, sheet_name="对比明细"
    )
st.download_button(
    "📥 下载对比结果 Excel",
    data=output.getvalue(),
    file_name=f"商品销售对比_{start_date}_{end_date}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
