# pages/3_anchor.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from core.db import load_product_sales, load_product_master
from core.utils import extract_anchor, date_quick_buttons

st.set_page_config(page_title="主播分析", layout="wide")

# 确保全局状态
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""

# ========== 页面内容（原 idx_anchor_compare 块） ==========
use_anchor = st.session_state.table_suffix in ["_live", "_all"]
dimension_name = "主播" if use_anchor else "店铺"
dimension_col = "anchor" if use_anchor else "shop_name"

with st.spinner("正在加载数据..."):
    prod_df = load_product_sales(st.session_state.table_suffix)

if prod_df.empty:
    st.info("暂无商品销售数据，请先上传订单文件。")
    st.stop()

if dimension_col not in prod_df.columns:
    if use_anchor:
        prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)
    else:
        if "shop_name" not in prod_df.columns:
            st.error("数据中缺少店铺名称信息，无法进行店铺对比。")
            st.stop()
prod_df = prod_df[prod_df[dimension_col].notna()].copy()
if prod_df.empty:
    st.info(f"当前数据中未识别到任何{dimension_name}信息，请检查数据。")
    st.stop()

all_dimensions = sorted(prod_df[dimension_col].unique())
col_select1, col_select2, col_select3 = st.columns(3)
with col_select1:
    selected_dimensions = st.multiselect(
        f"选择对比的{dimension_name}（最多3个）",
        options=all_dimensions,
        default=[],
        key="dimension_multiselect"
    )
    if len(selected_dimensions) > 3:
        st.warning("最多只能选择3个，请取消多余的选项。")
        selected_dimensions = selected_dimensions[:3]
with col_select2:
    metric_options = ["净销售金额", "发货金额", "退货金额"]
    selected_metrics = st.multiselect("选择要对比的指标", options=metric_options, default=["净销售金额"])
with col_select3:
    chart_type = st.radio("图表类型", ["折线图", "柱状图"], horizontal=True, key="compare_chart_type")

min_date = prod_df["sale_date"].min().date()
max_date = prod_df["sale_date"].max().date()

date_quick_buttons("compare_start", "compare_end",
                   default_start=min_date,
                   default_end=max_date,
                   min_date=min_date,
                   max_date=max_date)
start_date = st.session_state.get("compare_start", min_date)
end_date = st.session_state.get("compare_end", max_date)

if not selected_dimensions:
    st.info(f"请至少选择一个{dimension_name}")
else:
    mask_date = (prod_df["sale_date"] >= pd.to_datetime(start_date)) & (prod_df["sale_date"] <= pd.to_datetime(end_date))
    filtered = prod_df[mask_date].copy()
    if filtered.empty:
        st.warning("所选日期范围内无销售数据")
    else:
        daily_agg = filtered.groupby(["sale_date", dimension_col]).agg(
            净销售金额=("net_amount", "sum"),
            发货金额=("ship_amount", "sum"),
            退货金额=("return_amount", "sum")
        ).reset_index()
        daily_agg = daily_agg[daily_agg[dimension_col].isin(selected_dimensions)]
        if daily_agg.empty:
            st.warning(f"所选{dimension_name}在日期范围内无销售数据")
        else:
            st.caption(f"当前选中的 {dimension_name}：{selected_dimensions}")
            
            for metric in selected_metrics:
                st.markdown(f"#### {metric} 趋势对比")
                pivot_df = daily_agg.pivot(index="sale_date", columns=dimension_col, values=metric)
                pivot_df = pivot_df.reindex(columns=selected_dimensions, fill_value=0)
                st.caption(f"补全后的列：{list(pivot_df.columns)}")
                
                if chart_type == "折线图":
                    fig = go.Figure()
                    for dim in pivot_df.columns:
                        fig.add_trace(go.Scatter(
                            x=pivot_df.index,
                            y=pivot_df[dim],
                            mode="lines+markers",
                            name=dim,
                            hovertemplate=f"{dim}<br>日期: %{{x|%Y-%m-%d}}<br>{metric}: %{{y:,.2f}}<extra></extra>"
                        ))
                    fig.update_layout(
                        title=f"{metric} 按日对比（折线图）",
                        xaxis_title="日期",
                        yaxis_title=f"{metric} (¥)",
                        legend_title=dimension_name,
                        hovermode="x unified"
                    )
                else:
                    fig = go.Figure()
                    for dim in pivot_df.columns:
                        fig.add_trace(go.Bar(
                            x=pivot_df.index,
                            y=pivot_df[dim],
                            name=dim,
                            hovertemplate=f"{dim}<br>日期: %{{x|%Y-%m-%d}}<br>{metric}: %{{y:,.2f}}<extra></extra>"
                        ))
                    fig.update_layout(
                        title=f"{metric} 按日对比（柱状图）",
                        xaxis_title="日期",
                        yaxis_title=f"{metric} (¥)",
                        legend_title=dimension_name,
                        barmode='group',
                        hovermode="x unified"
                    )
                st.plotly_chart(fig, use_container_width=True, key=f"compare_{metric}_{chart_type}")
            
            # ---------- 品类分析 ----------
            st.markdown(f"#### {dimension_name}品类销售分析")
            col_cat1, col_cat2 = st.columns([1, 2])
            with col_cat1:
                cat_chart_type = st.radio("品类图表类型", ["柱状图（对比品类）", "饼图（各维度品类分布）"], horizontal=False, key="cat_chart_type")
            with col_cat2:
                cat_metric = st.selectbox("品类金额指标", ["净销售金额", "发货金额", "退货金额"], key="cat_metric")
            cat_metric_col = {"净销售金额": "net_amount", "发货金额": "ship_amount", "退货金额": "return_amount"}[cat_metric]
            cat_metric_name = cat_metric
            
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
            
            if cat_chart_type == "柱状图（对比品类）":
                cat_agg = filtered.groupby([dimension_col, "master_category"])[cat_metric_col].sum().reset_index()
                cat_agg.rename(columns={cat_metric_col: "金额"}, inplace=True)
                top_cats_per_dim = {}
                for dim in selected_dimensions:
                    dim_data = cat_agg[cat_agg[dimension_col] == dim].copy()
                    if not dim_data.empty:
                        dim_data = dim_data.sort_values("金额", ascending=False)
                        top5 = dim_data.head(5)
                        top_cats_per_dim[dim] = top5
                all_top_cats = set()
                for dim, df_top in top_cats_per_dim.items():
                    all_top_cats.update(df_top["master_category"].tolist())
                all_top_cats = sorted(list(all_top_cats))
                if all_top_cats:
                    compare_df = pd.DataFrame(index=all_top_cats)
                    for dim in selected_dimensions:
                        dim_sales = {}
                        if dim in top_cats_per_dim:
                            for _, row in top_cats_per_dim[dim].iterrows():
                                dim_sales[row["master_category"]] = row["金额"]
                        compare_df[dim] = [dim_sales.get(cat, 0) for cat in all_top_cats]
                    compare_df = compare_df.reindex(columns=selected_dimensions, fill_value=0)
                    fig_cat = px.bar(
                        compare_df,
                        x=compare_df.index,
                        y=selected_dimensions,
                        barmode='group',
                        title=f"{dimension_name}Top5品类{cat_metric_name}对比",
                        labels={"value": f"{cat_metric_name}(¥)", "index": "商品品类"},
                        color_discrete_sequence=px.colors.qualitative.Set2
                    )
                    fig_cat.update_layout(xaxis_title="商品品类", yaxis_title=f"{cat_metric_name}(¥)", legend_title=dimension_name)
                    st.plotly_chart(fig_cat, use_container_width=True)
                else:
                    st.info("无法获取品类数据，无法生成对比图。")
            else:
                cat_agg = filtered.groupby([dimension_col, "master_category"])[cat_metric_col].sum().reset_index()
                cat_agg.rename(columns={cat_metric_col: "金额"}, inplace=True)
                dim_pie_data = {}
                for dim in selected_dimensions:
                    dim_data = cat_agg[cat_agg[dimension_col] == dim].copy()
                    if dim_data.empty:
                        continue
                    dim_data = dim_data.sort_values("金额", ascending=False)
                    top5 = dim_data.head(5)
                    other_sum = dim_data.iloc[5:]["金额"].sum() if len(dim_data) > 5 else 0
                    if other_sum > 0:
                        other_row = pd.DataFrame({"master_category": ["其他"], "金额": [other_sum]})
                        top5 = pd.concat([top5, other_row], ignore_index=True)
                    dim_pie_data[dim] = top5
                if dim_pie_data:
                    cols = st.columns(len(dim_pie_data))
                    for idx, (dim, data) in enumerate(dim_pie_data.items()):
                        with cols[idx]:
                            fig_pie = px.pie(
                                data,
                                names="master_category",
                                values="金额",
                                title=f"{dim} - 品类分布 ({cat_metric_name})",
                                hole=0.3,
                                color_discrete_sequence=px.colors.qualitative.Pastel
                            )
                            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                            st.plotly_chart(fig_pie, use_container_width=True)
                else:
                    st.info("无有效数据")
            
            # ---------- 季节分析 ----------
            st.markdown(f"#### {dimension_name}季节销售分析")
            col_season1, col_season2 = st.columns([1, 2])
            with col_season1:
                season_chart_type = st.radio("季节图表类型", ["柱状图（对比季节）", "饼图（各维度季节分布）"], horizontal=False, key="season_chart_type")
            with col_season2:
                season_metric = st.selectbox("季节金额指标", ["净销售金额", "发货金额", "退货金额"], key="season_metric")
            season_metric_col = {"净销售金额": "net_amount", "发货金额": "ship_amount", "退货金额": "return_amount"}[season_metric]
            season_metric_name = season_metric
            
            if "season" not in filtered.columns:
                st.info("数据中缺少季节信息，无法生成季节对比图。")
            else:
                season_data = filtered[filtered["season"].notna()].copy()
                if season_data.empty:
                    st.info("所选范围内无季节数据")
                else:
                    if season_chart_type == "柱状图（对比季节）":
                        season_agg = season_data.groupby([dimension_col, "season"])[season_metric_col].sum().reset_index()
                        season_agg.rename(columns={season_metric_col: "金额"}, inplace=True)
                        season_agg = season_agg[season_agg[dimension_col].isin(selected_dimensions)]
                        if not season_agg.empty:
                            pivot_season = season_agg.pivot(index="season", columns=dimension_col, values="金额").fillna(0)
                            pivot_season = pivot_season.reindex(columns=selected_dimensions, fill_value=0)
                            season_order = ["春", "夏", "秋", "冬"]
                            pivot_season = pivot_season.reindex([s for s in season_order if s in pivot_season.index])
                            if not pivot_season.empty:
                                fig_season = px.bar(
                                    pivot_season,
                                    x=pivot_season.index,
                                    y=selected_dimensions,
                                    barmode='group',
                                    title=f"{dimension_name}季节{season_metric_name}对比",
                                    labels={"value": f"{season_metric_name}(¥)", "index": "季节"},
                                    color_discrete_sequence=px.colors.qualitative.Set1
                                )
                                fig_season.update_layout(xaxis_title="季节", yaxis_title=f"{season_metric_name}(¥)", legend_title=dimension_name)
                                st.plotly_chart(fig_season, use_container_width=True)
                            else:
                                st.info("无有效季节数据")
                        else:
                            st.info(f"所选{dimension_name}无季节数据")
                    else:
                        season_agg = season_data.groupby([dimension_col, "season"])[season_metric_col].sum().reset_index()
                        season_agg.rename(columns={season_metric_col: "金额"}, inplace=True)
                        dim_season_data = {}
                        for dim in selected_dimensions:
                            dim_season = season_agg[season_agg[dimension_col] == dim].copy()
                            if not dim_season.empty:
                                dim_season_data[dim] = dim_season
                        if dim_season_data:
                            cols = st.columns(len(dim_season_data))
                            for idx, (dim, data) in enumerate(dim_season_data.items()):
                                with cols[idx]:
                                    fig_pie_season = px.pie(
                                        data,
                                        names="season",
                                        values="金额",
                                        title=f"{dim} - 季节分布 ({season_metric_name})",
                                        hole=0.3,
                                        color_discrete_sequence=px.colors.qualitative.Set2
                                    )
                                    fig_pie_season.update_traces(textposition='inside', textinfo='percent+label')
                                    st.plotly_chart(fig_pie_season, use_container_width=True)
                        else:
                            st.info("无有效数据")
            
            # ---------- 年份分析 ----------
            st.markdown(f"#### {dimension_name}年份销售分析")
            col_year1, col_year2 = st.columns([1, 2])
            with col_year1:
                year_chart_type = st.radio("年份图表类型", ["柱状图（对比年份）", "饼图（各维度年份分布）"], horizontal=False, key="year_chart_type")
            with col_year2:
                year_metric = st.selectbox("年份金额指标", ["净销售金额", "发货金额", "退货金额"], key="year_metric")
            year_metric_col = {"净销售金额": "net_amount", "发货金额": "ship_amount", "退货金额": "return_amount"}[year_metric]
            year_metric_name = year_metric
            
            if "year" not in filtered.columns:
                st.info("数据中缺少年份信息，无法生成年份对比图。")
            else:
                year_data = filtered[filtered["year"].notna()].copy()
                if year_data.empty:
                    st.info("所选范围内无年份数据")
                else:
                    if year_chart_type == "柱状图（对比年份）":
                        year_agg = year_data.groupby([dimension_col, "year"])[year_metric_col].sum().reset_index()
                        year_agg.rename(columns={year_metric_col: "金额"}, inplace=True)
                        year_agg = year_agg[year_agg[dimension_col].isin(selected_dimensions)]
                        if not year_agg.empty:
                            pivot_year = year_agg.pivot(index="year", columns=dimension_col, values="金额").fillna(0)
                            pivot_year = pivot_year.reindex(columns=selected_dimensions, fill_value=0)
                            pivot_year = pivot_year.sort_index()
                            if not pivot_year.empty:
                                fig_year = px.bar(
                                    pivot_year,
                                    x=pivot_year.index,
                                    y=selected_dimensions,
                                    barmode='group',
                                    title=f"{dimension_name}年份{year_metric_name}对比",
                                    labels={"value": f"{year_metric_name}(¥)", "index": "年份"},
                                    color_discrete_sequence=px.colors.qualitative.Pastel
                                )
                                fig_year.update_layout(xaxis_title="年份", yaxis_title=f"{year_metric_name}(¥)", legend_title=dimension_name)
                                st.plotly_chart(fig_year, use_container_width=True)
                            else:
                                st.info("无有效年份数据")
                        else:
                            st.info(f"所选{dimension_name}无年份数据")
                    else:
                        year_agg = year_data.groupby([dimension_col, "year"])[year_metric_col].sum().reset_index()
                        year_agg.rename(columns={year_metric_col: "金额"}, inplace=True)
                        dim_year_data = {}
                        for dim in selected_dimensions:
                            dim_year = year_agg[year_agg[dimension_col] == dim].copy()
                            if not dim_year.empty:
                                dim_year = dim_year.sort_values("year")
                                dim_year_data[dim] = dim_year
                        if dim_year_data:
                            cols = st.columns(len(dim_year_data))
                            for idx, (dim, data) in enumerate(dim_year_data.items()):
                                with cols[idx]:
                                    fig_pie_year = px.pie(
                                        data,
                                        names="year",
                                        values="金额",
                                        title=f"{dim} - 年份分布 ({year_metric_name})",
                                        hole=0.3,
                                        color_discrete_sequence=px.colors.qualitative.Set3
                                    )
                                    fig_pie_year.update_traces(textposition='inside', textinfo='percent+label')
                                    st.plotly_chart(fig_pie_year, use_container_width=True)
                        else:
                            st.info("无有效数据")
