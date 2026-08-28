# pages/4_distribution.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import io
import plotly.express as px

from core.db import get_sales_date_range, load_product_master, load_product_sales_cube
from core.product_tags import normalize_product_tags, product_tags_text
from core.utils import date_quick_buttons, clear_cache_on_page_change
from core.theme import page_header

st.set_page_config(page_title="销售分布与品牌", layout="wide")
clear_cache_on_page_change("distribution")

# 确保全局状态
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""

page_header("销售分布与品牌", "从品牌、年份、季节和款式结构洞察销售分布", "PORTFOLIO ANALYTICS", "结构洞察")

min_date, max_date = get_sales_date_range("_all")
if min_date is None or max_date is None:
    st.warning("暂无商品销售数据，请先上传订单文件。")
    st.stop()

default_start = max(min_date, max_date.replace(day=1))
date_quick_buttons(
    "dist_start_v3", "dist_end_v3",
    default_start=default_start,
    default_end=max_date,
    min_date=min_date,
    max_date=max_date,
)
start_date = st.session_state.get("dist_start_v3", default_start)
end_date = st.session_state.get("dist_end_v3", max_date)

selected_scope = st.selectbox(
    "数据范围", ["小店运营组", "全部销售"], key="dist_scope_v2"
)
selected_department = "小店运营" if selected_scope == "小店运营组" else None

with st.spinner("正在加载所选日期的销售分布..."):
    prod_df = load_product_sales_cube(
        start_date, end_date, department=selected_department
    )

if prod_df.empty:
    st.warning("暂无商品销售数据，请先上传订单文件。")
    st.stop()

if "style_code" in prod_df.columns:
    prod_df["style_code"] = prod_df["style_code"].astype(str).str.strip().str.upper()
else:
    prod_df["style_code"] = prod_df["product_code"].str[:8].str.strip().str.upper()

if "year" not in prod_df.columns:
    prod_df["year"] = prod_df["style_code"].str.slice(1, 3).replace("", pd.NA)
if "season" not in prod_df.columns:
    season_map = {"1": "春", "2": "夏", "3": "秋", "4": "冬"}
    prod_df["season"] = prod_df["style_code"].str.slice(3, 4).map(season_map).fillna("未知")

st.markdown("#### 筛选条件")

scope_df = prod_df
col_platform, col_shop = st.columns(2)
with col_platform:
    platform_options = ["全部", "抖音", "视频号"]
    selected_platform = st.selectbox("平台", platform_options, key="dist_platform_v2")
with col_shop:
    all_shops_all = scope_df["shop_name"].dropna().unique()
    if selected_platform == "抖音":
        shop_options = [shop for shop in all_shops_all if "抖音" in shop]
    elif selected_platform == "视频号":
        shop_options = [shop for shop in all_shops_all if "视频号" in shop]
    else:
        shop_options = list(all_shops_all)
    selected_shops = st.multiselect("店铺（可多选）", options=sorted(shop_options), default=[], key="dist_shop_v3")

col_brand, col_anchor = st.columns(2)
with col_brand:
    brands_all = ["全部"] + sorted(scope_df["brand"].dropna().unique())
    selected_brand = st.selectbox("品牌", brands_all, key="dist_brand_v2")
with col_anchor:
    selected_anchors = []
    if st.session_state.table_suffix == "_all":
        all_anchors = scope_df["anchor"].dropna().unique().tolist()
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

# 商品标签分析
master_df = load_product_master()
tag_map = {}
all_product_tags = []
if not master_df.empty and "style_code" in master_df.columns:
    master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
    tag_map = master_df.set_index("style_code")["tags"].to_dict()
    all_product_tags = sorted({tag for value in master_df["tags"] for tag in normalize_product_tags(value)})
filtered["product_tags"] = filtered["style_code"].map(tag_map).map(normalize_product_tags)

st.markdown("#### 商品标签销售分析")
if not all_product_tags:
    st.info("暂无商品标签，请先在“商品信息管理 → 商品标签”中创建。")
    st.stop()

# 标签总览饼图：首单礼金不单独展示，无其他自定义标签时统一归入“其他”。
# 多标签商品按标签数量均分金额，确保饼图合计仍等于当前筛选条件下的实际金额。
tag_distribution = filtered[["product_tags", metric_col]].copy()
tag_distribution["对比标签"] = tag_distribution["product_tags"].map(
    lambda tags: [tag for tag in normalize_product_tags(tags) if tag != "首单礼金"] or ["其他"]
)
tag_distribution["标签数量"] = tag_distribution["对比标签"].map(len)
tag_distribution["标签分摊金额"] = (
    tag_distribution[metric_col] / tag_distribution["标签数量"]
)
tag_distribution = tag_distribution.explode("对比标签")
tag_distribution = tag_distribution.groupby("对比标签", as_index=False)["标签分摊金额"].sum()
tag_distribution = tag_distribution[tag_distribution["标签分摊金额"] > 0]

if not tag_distribution.empty:
    fig_tag_overview = px.pie(
        tag_distribution,
        names="对比标签",
        values="标签分摊金额",
        title=f"商品标签{metric_name}占比（首单礼金归入其他）",
        hole=0.35,
        color_discrete_sequence=px.colors.qualitative.Set3,
    )
    fig_tag_overview.update_traces(textposition="inside", textinfo="percent+label")
    st.plotly_chart(fig_tag_overview, use_container_width=True, key="pie_product_tags_overview")
    st.caption("多标签商品按自定义标签数量均分金额；仅有“首单礼金”或无标签的商品计入“其他”。")
else:
    st.info("当前筛选条件下暂无可展示的标签销售额。")

selected_product_tag = st.selectbox("选择商品标签", all_product_tags, key="dist_product_tag")
coupon_filtered = filtered[filtered["product_tags"].map(lambda tags: selected_product_tag in tags)].copy()
non_coupon_filtered = filtered[~filtered["product_tags"].map(lambda tags: selected_product_tag in tags)].copy()

col_left, col_right = st.columns(2)
with col_left:
    coupon_total = coupon_filtered[metric_col].sum()
    non_coupon_total = non_coupon_filtered[metric_col].sum()
    if coupon_total > 0 or non_coupon_total > 0:
        coupon_pie_data = pd.DataFrame({
            "类型": [f"含标签：{selected_product_tag}", "其他商品"],
            metric_name: [coupon_total, non_coupon_total]
        })
        coupon_pie_data = coupon_pie_data[coupon_pie_data[metric_name] > 0]
        fig_coupon_total = px.pie(coupon_pie_data, names="类型", values=metric_name,
                                  title=f"“{selected_product_tag}”商品{metric_name}占比", hole=0.3,
                                  color_discrete_sequence=["#FF6B6B", "#4ECDC4"])
        fig_coupon_total.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_coupon_total, use_container_width=True, key="pie_coupon_total_v2")
    else:
        st.info(f"无“{selected_product_tag}”标签数据")
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
                                      title=f"“{selected_product_tag}”商品{metric_name}品牌占比", hole=0.3,
                                      color_discrete_sequence=px.colors.qualitative.Set2)
            fig_coupon_brand.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_coupon_brand, use_container_width=True, key="pie_coupon_brand_v2")
        else:
            st.info("该标签暂无品牌数据")
    else:
        st.info(f"当前条件下无“{selected_product_tag}”商品数据")

# 标签商品明细
if not coupon_filtered.empty:
    st.markdown(f"#### “{selected_product_tag}”商品销售明细（按货号汇总）")
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
        image_values = coupon_detail["货号"].map(img_map).astype(object)
        coupon_detail["图片"] = image_values.where(image_values.notna(), None)
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
        f"💾 导出“{selected_product_tag}”商品明细",
        data=output.getvalue(),
        file_name=f"商品标签_{selected_product_tag}_{start_date}_{end_date}.xlsx",
        key="export_coupon_detail_v2"
    )
else:
    st.info(f"当前筛选条件下无“{selected_product_tag}”商品")
