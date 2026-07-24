# pages/4_distribution.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import io
import plotly.express as px

from core.db import load_product_sales, load_product_master
from core.utils import extract_anchor, date_quick_buttons

st.set_page_config(page_title="销售分布与品牌", layout="wide")

# 确保全局状态
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""

with st.spinner("正在加载数据，请稍候..."):
    prod_df = load_product_sales(st.session_state.table_suffix)

if prod_df.empty:
    st.warning("暂无商品销售数据，请先上传订单文件。")
    st.stop()

if "style_code" in prod_df.columns:
    prod_df["style_code"] = prod_df["style_code"].astype(str).str.strip().str.upper()
else:
    prod_df["style_code"] = prod_df["product_code"].str[:8].str.strip().str.upper()

if st.session_state.table_suffix in ["_live", "_all"]:
    if "anchor" not in prod_df.columns:
        prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)

st.markdown("#### 筛选条件")
min_date = prod_df["sale_date"].min().date()
max_date = prod_df["sale_date"].max().date()

date_quick_buttons("dist_start_v2", "dist_end_v2",
                   default_start=min_date,
                   default_end=max_date,
                   min_date=min_date,
                   max_date=max_date)
start_date = st.session_state.get("dist_start_v2", min_date)
end_date = st.session_state.get("dist_end_v2", max_date)

col_platform, col_shop = st.columns(2)
with col_platform:
    platform_options = ["全部", "抖音", "视频号"]
    selected_platform = st.selectbox("平台", platform_options, key="dist_platform_v2")
with col_shop:
    all_shops_all = prod_df["shop_name"].unique()
    if selected_platform == "抖音":
        shop_options = [shop for shop in all_shops_all if "抖音" in shop]
    elif selected_platform == "视频号":
        shop_options = [shop for shop in all_shops_all if "视频号" in shop]
    else:
        shop_options = list(all_shops_all)
    selected_shops = st.multiselect("店铺（可多选）", options=sorted(shop_options), default=[], key="dist_shop_v2")

col_brand, col_anchor = st.columns(2)
with col_brand:
    brands_all = ["全部"] + sorted(prod_df["brand"].dropna().unique())
    selected_brand = st.selectbox("品牌", brands_all, key="dist_brand_v2")
with col_anchor:
    selected_anchors = []
    if st.session_state.table_suffix in ["_live", "_all"]:
        if "anchor" not in prod_df.columns:
            prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)
        all_anchors = prod_df["anchor"].dropna().unique().tolist()
        if all_anchors:
            selected_anchors = st.multiselect("主播（可多选）", options=sorted(all_anchors), default=[], key="dist_anchor_v2")
        else:
            st.info("当前数据中未识别到任何主播信息，请检查备注字段是否包含“主播：xxx”格式。")

mask_date = (prod_df["sale_date"] >= pd.to_datetime(start_date)) & (prod_df["sale_date"] <= pd.to_datetime(end_date))
filtered = prod_df[mask_date].copy()
if selected_platform == "抖音":
    filtered = filtered[filtered["shop_name"].str.contains("抖音", case=False, na=False)]
elif selected_platform == "视频号":
    filtered = filtered[filtered["shop_name"].str.contains("视频号", case=False, na=False)]
if selected_shops:
    filtered = filtered[filtered["shop_name"].isin(selected_shops)]
if selected_brand != "全部":
    filtered = filtered[filtered["brand"] == selected_brand]
if selected_anchors:
    filtered = filtered[filtered["anchor"].isin(selected_anchors)]

if filtered.empty:
    st.warning("所选条件下无销售数据")
    st.stop()

metric_options = ["净销售金额", "发货金额", "退货金额"]
selected_metric = st.radio("金额指标", metric_options, horizontal=True, key="dist_metric_v2")
metric_col = {"净销售金额": "net_amount", "发货金额": "ship_amount", "退货金额": "return_amount"}[selected_metric]
metric_name = selected_metric

# 处理分类
if "master_category" not in filtered.columns:
    master_df = load_product_master()
    if not master_df.empty and "style_code" in master_df.columns:
        master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
        cat_map = master_df.set_index("style_code")["category"].to_dict()
        filtered["master_category"] = filtered["style_code"].map(cat_map).fillna("未分类")
    else:
        filtered["master_category"] = "未分类"
else:
    filtered["master_category"] = filtered["master_category"].fillna("未分类")
cat_data = filtered.groupby("master_category")[metric_col].sum().reset_index()

# 年份
if "year" in filtered.columns and not filtered["year"].isnull().all():
    year_data = filtered.groupby("year")[metric_col].sum().reset_index()
    year_data = year_data[year_data["year"].notna()]
else:
    total_val = filtered[metric_col].sum()
    year_data = pd.DataFrame({"year": ["无年份信息"], metric_col: [total_val]}) if total_val > 0 else None

# 季节
if "season" in filtered.columns and not filtered["season"].isnull().all():
    season_data = filtered.groupby("season")[metric_col].sum().reset_index()
    season_data = season_data[season_data["season"].notna()]
else:
    total_val = filtered[metric_col].sum()
    season_data = pd.DataFrame({"season": ["无季节信息"], metric_col: [total_val]}) if total_val > 0 else None

def create_pie_chart(data, name_col, value_col, title, key):
    if data is None:
        return
    total = data[value_col].sum()
    if total == 0 or (total < 0 and metric_col == "net_amount"):
        return
    chart_data = data[data[value_col] != 0].copy()
    if chart_data.empty:
        return
    fig = px.pie(chart_data, names=name_col, values=value_col, title=title, hole=0.3, color_discrete_sequence=px.colors.qualitative.Pastel)
    fig.update_traces(textposition='inside', textinfo='percent+label')
    st.plotly_chart(fig, use_container_width=True, key=key)

col1, col2, col3 = st.columns(3)
with col1:
    if cat_data is not None and not cat_data.empty:
        create_pie_chart(cat_data, "master_category", metric_col, f"分类{metric_name}占比", "pie_category_v2")
    else:
        st.info("无分类数据")
with col2:
    if year_data is not None and not year_data.empty:
        create_pie_chart(year_data, "year", metric_col, f"年份{metric_name}占比", "pie_year_v2")
    else:
        st.info("无年份数据")
with col3:
    if season_data is not None and not season_data.empty:
        create_pie_chart(season_data, "season", metric_col, f"季节{metric_name}占比", "pie_season_v2")
    else:
        st.info("无季节数据")

# 首单礼金分析
master_df = load_product_master()
if "has_newbie_coupon" not in filtered.columns:
    if not master_df.empty and "style_code" in master_df.columns:
        master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
        coupon_map = master_df.set_index("style_code")["has_newbie_coupon"].to_dict()
        filtered["has_newbie_coupon"] = filtered["style_code"].map(coupon_map).fillna(False)
    else:
        filtered["has_newbie_coupon"] = False
else:
    filtered["has_newbie_coupon"] = filtered["has_newbie_coupon"].fillna(False)

coupon_filtered = filtered[filtered["has_newbie_coupon"] == True].copy()
non_coupon_filtered = filtered[filtered["has_newbie_coupon"] == False].copy()

st.markdown(f"#### 首单礼金销售分析")
col_left, col_right = st.columns(2)
with col_left:
    coupon_total = coupon_filtered[metric_col].sum()
    non_coupon_total = non_coupon_filtered[metric_col].sum()
    if coupon_total > 0 or non_coupon_total > 0:
        coupon_pie_data = pd.DataFrame({
            "类型": ["参与首单礼金", "未参与首单礼金"],
            metric_name: [coupon_total, non_coupon_total]
        })
        coupon_pie_data = coupon_pie_data[coupon_pie_data[metric_name] > 0]
        fig_coupon_total = px.pie(coupon_pie_data, names="类型", values=metric_name,
                                  title=f"首单礼金商品{metric_name}占比", hole=0.3,
                                  color_discrete_sequence=["#FF6B6B", "#4ECDC4"])
        fig_coupon_total.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_coupon_total, use_container_width=True, key="pie_coupon_total_v2")
    else:
        st.info("无首单礼金数据")
with col_right:
    if not coupon_filtered.empty:
        coupon_brand_data = coupon_filtered.groupby("brand")[metric_col].sum().reset_index()
        coupon_brand_data = coupon_brand_data[coupon_brand_data[metric_col] != 0]
        if not coupon_brand_data.empty:
            if len(coupon_brand_data) > 8:
                top8 = coupon_brand_data.nlargest(8, metric_col)
                other_sum = coupon_brand_data[~coupon_brand_data["brand"].isin(top8["brand"])][metric_col].sum()
                other_row = pd.DataFrame({"brand": ["其他"], metric_col: [other_sum]})
                coupon_brand_data = pd.concat([top8, other_row], ignore_index=True)
            fig_coupon_brand = px.pie(coupon_brand_data, names="brand", values=metric_col,
                                      title=f"首单礼金商品{metric_name}品牌占比", hole=0.3,
                                      color_discrete_sequence=px.colors.qualitative.Set2)
            fig_coupon_brand.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_coupon_brand, use_container_width=True, key="pie_coupon_brand_v2")
        else:
            st.info("无礼金品牌数据")
    else:
        st.info("无礼金商品数据")

# 首单礼金商品明细
if not coupon_filtered.empty:
    st.markdown(f"#### 首单礼金商品销售明细（按货号汇总）")
    coupon_detail = coupon_filtered.groupby("style_code").agg(
        发货金额=("ship_amount", "sum"),
        退货金额=("return_amount", "sum"),
        净销售金额=("net_amount", "sum")
    ).reset_index()
    coupon_detail.rename(columns={"style_code": "货号"}, inplace=True)
    master_df = load_product_master()
    if not master_df.empty and "style_code" in master_df.columns:
        master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
        img_map = master_df.set_index("style_code")["image_url"].to_dict()
        coupon_detail["图片"] = coupon_detail["货号"].map(img_map).fillna(None)
    else:
        coupon_detail["图片"] = None
    coupon_detail["退款率"] = coupon_detail.apply(
        lambda r: f"{(r['退货金额']/r['发货金额']*100):.2f}%" if r['发货金额'] != 0 else "-", axis=1
    )
    col_order = ["货号", "图片", "发货金额", "退货金额", "净销售金额", "退款率"]
    coupon_detail = coupon_detail[col_order]
    st.dataframe(
        coupon_detail,
        column_config={
            "货号": st.column_config.TextColumn("货号"),
            "图片": st.column_config.ImageColumn("商品图片", help="点击放大"),
            "发货金额": st.column_config.NumberColumn("发货金额(¥)", format="%.2f"),
            "退货金额": st.column_config.NumberColumn("退货金额(¥)", format="%.2f"),
            "净销售金额": st.column_config.NumberColumn("净销售金额(¥)", format="%.2f"),
            "退款率": st.column_config.TextColumn("退款率")
        },
        hide_index=True,
        use_container_width=True
    )
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        export_df = coupon_detail.drop(columns=["图片"], errors='ignore')
        export_df.to_excel(writer, index=False)
    st.download_button(
        "💾 导出首单礼金商品明细",
        data=output.getvalue(),
        file_name=f"首单礼金明细_{start_date}_{end_date}.xlsx",
        key="export_coupon_detail_v2"
    )
else:
    st.info("当前筛选条件下无首单礼金商品")
