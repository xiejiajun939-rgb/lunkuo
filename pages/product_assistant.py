# pages/product_assistant.py
# -*- coding: utf-8 -*-
"""
商品分析助手
整合商品概览、四象限矩阵、智能预警、对比分析、AI报告、导出
仅支持“全部数据”源，并增加平台筛选
四象限图点击商品可弹出诊断窗口（商品诊断融入四象限）
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import io
import re

from core.db import load_product_sales, load_product_master
from core.utils import extract_anchor
from core.ai import get_ai_summary

st.set_page_config(page_title="商品分析助手", layout="wide", initial_sidebar_state="expanded")

# ---------- 固定使用全部数据 ----------
SUFFIX = "_all"

# ---------- 初始化 session_state ----------
if "product_assistant_filter" not in st.session_state:
    st.session_state.product_assistant_filter = {}
if "pa_selected_products" not in st.session_state:
    st.session_state.pa_selected_products = []
if "pa_current_product" not in st.session_state:
    st.session_state.pa_current_product = None
if "pa_diagnosis_result" not in st.session_state:
    st.session_state.pa_diagnosis_result = None
if "pa_compare_products" not in st.session_state:
    st.session_state.pa_compare_products = []
# 四象限点击诊断对话框状态
if "pa_quadrant_click_style" not in st.session_state:
    st.session_state.pa_quadrant_click_style = None
if "pa_show_quadrant_dialog" not in st.session_state:
    st.session_state.pa_show_quadrant_dialog = False

# ---------- 自定义样式 ----------
st.markdown("""
<style>
    .kpi-card { background: white; border-radius: 16px; padding: 18px 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.04); border: 1px solid #f0f0f0; }
    .kpi-number { font-size: 28px; font-weight: 700; color: #0f172a; }
    .kpi-label { font-size: 13px; color: #64748b; font-weight: 500; }
    .kpi-delta { font-size: 14px; font-weight: 600; }
    .kpi-delta.positive { color: #22c55e; }
    .kpi-delta.negative { color: #ef4444; }
    .alert-card { border-left: 4px solid #f59e0b; background: #fffbeb; padding: 12px 16px; border-radius: 8px; margin-bottom: 8px; }
    .alert-card.critical { border-left-color: #ef4444; background: #fef2f2; }
    .alert-card.success { border-left-color: #22c55e; background: #f0fdf4; }
    .section-title { font-size: 20px; font-weight: 600; color: #0f172a; margin: 20px 0 12px 0; display: flex; align-items: center; gap: 8px; }
    .section-title .badge { font-size: 12px; background: #e2e8f0; color: #475569; padding: 2px 10px; border-radius: 20px; font-weight: 400; }
    .stDataFrame { border-radius: 12px; overflow: hidden; }
    .diagnosis-box { background: #f8fafc; border-radius: 12px; padding: 20px; border: 1px solid #e2e8f0; }
    .diagnosis-box .highlight { color: #2563eb; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ---------- 加载数据 ----------
@st.cache_data(ttl=300)
def load_assistant_data(suffix, start_date, end_date, platform=None):
    """加载商品分析所需数据（聚合后的商品级别数据），支持平台筛选"""
    df = load_product_sales(suffix, include_offline=False)
    if df.empty:
        return pd.DataFrame()
    df = df[(df["sale_date"] >= pd.to_datetime(start_date)) & (df["sale_date"] <= pd.to_datetime(end_date))]
    if df.empty:
        return pd.DataFrame()
    
    if platform and platform != "全部":
        if platform == "抖音":
            df = df[df["shop_name"].str.contains("抖音", case=False, na=False)]
        elif platform == "视频号":
            df = df[df["shop_name"].str.contains("视频号", case=False, na=False)]
        elif platform == "小红书":
            df = df[df["shop_name"].str.contains("小红书", case=False, na=False)]
        elif platform == "天猫":
            df = df[df["shop_name"].str.contains("天猫", case=False, na=False)]
        elif platform == "唯品会":
            df = df[df["shop_name"].str.contains("唯品会", case=False, na=False)]
    
    if df.empty:
        return pd.DataFrame()
    
    if "style_code" not in df.columns:
        df["style_code"] = df["product_code"].str[:8].str.strip().str.upper()
    else:
        df["style_code"] = df["style_code"].astype(str).str.strip().str.upper()
    
    for col in ["ship_amount", "return_amount", "net_amount"]:
        if col not in df.columns:
            df[col] = 0
    
    agg_dict = {}
    agg_dict["ship_sum"] = ("ship_amount", "sum")
    agg_dict["return_sum"] = ("return_amount", "sum")
    agg_dict["net_sum"] = ("net_amount", "sum")
    agg_dict["order_count"] = ("net_amount", "count")
    
    if "brand" in df.columns:
        agg_dict["brands"] = ("brand", lambda x: x.mode()[0] if not x.empty else None)
    if "master_category" in df.columns:
        agg_dict["categories"] = ("master_category", lambda x: x.mode()[0] if not x.empty else None)
    if "shop_name" in df.columns:
        agg_dict["shops"] = ("shop_name", lambda x: list(set(x)) if not x.empty else [])
    if "remark" in df.columns:
        agg_dict["anchors"] = ("remark", lambda x: list(set([extract_anchor(r) for r in x if extract_anchor(r)])) if not x.empty else [])
    
    grouped = df.groupby("style_code").agg(**agg_dict).reset_index()
    
    if "brands" not in grouped.columns:
        grouped["brands"] = None
    if "categories" not in grouped.columns:
        grouped["categories"] = None
    if "shops" not in grouped.columns:
        grouped["shops"] = []
    if "anchors" not in grouped.columns:
        grouped["anchors"] = []
    
    grouped["退货率"] = np.where(grouped["ship_sum"] > 0, grouped["return_sum"] / grouped["ship_sum"] * 100, 0)
    grouped["净销售额"] = grouped["net_sum"]
    grouped["发货额"] = grouped["ship_sum"]
    grouped["退货额"] = grouped["return_sum"]
    
    df["sale_date_dt"] = pd.to_datetime(df["sale_date"])
    latest = df.groupby("style_code")["sale_date_dt"].max().reset_index().rename(columns={"sale_date_dt": "latest_sale"})
    first = df.groupby("style_code")["sale_date_dt"].min().reset_index().rename(columns={"sale_date_dt": "first_sale"})
    grouped = grouped.merge(latest, on="style_code", how="left")
    grouped = grouped.merge(first, on="style_code", how="left")
    grouped["动销天数"] = (grouped["latest_sale"] - grouped["first_sale"]).dt.days + 1
    grouped["最近销售日期"] = grouped["latest_sale"].dt.date
    grouped["首次销售日期"] = grouped["first_sale"].dt.date
    
    master_df = load_product_master()
    if not master_df.empty and "style_code" in master_df.columns:
        master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
        coupon_map = master_df.set_index("style_code")["has_newbie_coupon"].to_dict()
        grouped["has_newbie_coupon"] = grouped["style_code"].map(coupon_map).fillna(False)
    else:
        grouped["has_newbie_coupon"] = False
    
    return grouped

def load_product_detail(style_code, suffix, start_date, end_date, platform=None):
    """加载单个商品的详细销售数据（用于诊断）"""
    df = load_product_sales(suffix, include_offline=False)
    if df.empty:
        return pd.DataFrame()
    df = df[df["sale_date"] >= pd.to_datetime(start_date)]
    df = df[df["sale_date"] <= pd.to_datetime(end_date)]
    
    if platform and platform != "全部":
        if platform == "抖音":
            df = df[df["shop_name"].str.contains("抖音", case=False, na=False)]
        elif platform == "视频号":
            df = df[df["shop_name"].str.contains("视频号", case=False, na=False)]
        elif platform == "小红书":
            df = df[df["shop_name"].str.contains("小红书", case=False, na=False)]
        elif platform == "天猫":
            df = df[df["shop_name"].str.contains("天猫", case=False, na=False)]
        elif platform == "唯品会":
            df = df[df["shop_name"].str.contains("唯品会", case=False, na=False)]
    
    if df.empty:
        return pd.DataFrame()
    
    if "style_code" not in df.columns:
        df["style_code"] = df["product_code"].str[:8].str.strip().str.upper()
    else:
        df["style_code"] = df["style_code"].astype(str).str.strip().str.upper()
    
    style_code_str = str(style_code)
    detail = df[df["style_code"] == style_code_str].copy()
    return detail

# ---------- 商品诊断显示函数（供四象限对话框使用） ----------
def show_product_diagnosis(style_code, filtered_df, suffix, start_date, end_date, platform, diagnosis_result):
    """显示单个商品的诊断内容（指标、趋势、渠道、AI诊断）"""
    detail_df = load_product_detail(style_code, suffix, start_date, end_date, platform)
    if detail_df.empty:
        st.info("该商品在所选日期范围内无销售数据")
        return
    
    total_ship = detail_df["ship_amount"].sum() if "ship_amount" in detail_df.columns else 0
    total_return = detail_df["return_amount"].sum() if "return_amount" in detail_df.columns else 0
    total_net = detail_df["net_amount"].sum() if "net_amount" in detail_df.columns else 0
    return_rate = (total_return / total_ship * 100) if total_ship > 0 else 0
    order_count = len(detail_df)
    unique_shops = detail_df["shop_name"].nunique() if "shop_name" in detail_df.columns else 0
    if "remark" in detail_df.columns:
        anchors = detail_df["remark"].apply(extract_anchor).dropna().unique()
        anchor_count = len(anchors)
    else:
        anchor_count = 0
    
    product_info = filtered_df[filtered_df["style_code"] == style_code].iloc[0] if style_code in filtered_df["style_code"].values else None
    brand = product_info["brands"] if product_info is not None else "未知"
    category = product_info["categories"] if product_info is not None else "未知"
    coupon = product_info["has_newbie_coupon"] if product_info is not None else False

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("净销售额", f"¥{total_net:,.0f}")
    with col2:
        st.metric("退货率", f"{return_rate:.1f}%", delta=f"{return_rate - product_info['退货率']:.1f}%" if product_info is not None else None)
    with col3:
        st.metric("订单数", order_count)
    with col4:
        st.metric("店铺数", unique_shops)
    with col5:
        st.metric("主播数", anchor_count)
    
    if "sale_date" in detail_df.columns:
        daily = detail_df.groupby("sale_date").agg(
            ship=("ship_amount", "sum") if "ship_amount" in detail_df.columns else ("net_amount", "sum"),
            ret=("return_amount", "sum") if "return_amount" in detail_df.columns else 0,
            net=("net_amount", "sum") if "net_amount" in detail_df.columns else ("net_amount", "sum")
        ).reset_index().sort_values("sale_date")
        if not daily.empty:
            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(x=daily["sale_date"], y=daily["net"], mode="lines+markers", name="净销售额", line=dict(color="#22c55e")))
            if "ship" in daily.columns:
                fig_trend.add_trace(go.Bar(x=daily["sale_date"], y=daily["ship"], name="发货额", opacity=0.5))
            if "ret" in daily.columns:
                fig_trend.add_trace(go.Bar(x=daily["sale_date"], y=-daily["ret"], name="退货额", opacity=0.5, marker_color="#ef4444"))
            fig_trend.update_layout(height=300, margin=dict(l=0, r=0, t=20, b=0), hovermode="x unified", barmode="relative")
            st.plotly_chart(fig_trend, use_container_width=True)
    
    if "remark" in detail_df.columns and anchor_count > 0:
        anchor_agg = detail_df.groupby(detail_df["remark"].apply(extract_anchor)).agg(
            net=("net_amount", "sum") if "net_amount" in detail_df.columns else ("net_amount", "sum"),
            ship=("ship_amount", "sum") if "ship_amount" in detail_df.columns else 0,
            ret=("return_amount", "sum") if "return_amount" in detail_df.columns else 0
        ).reset_index()
        anchor_agg.columns = ["主播", "净销售额", "发货额", "退货额"]
        anchor_agg["退货率"] = anchor_agg.apply(lambda r: f"{r['退货额']/r['发货额']*100:.1f}%" if r['发货额']>0 else "-", axis=1)
        st.dataframe(anchor_agg, use_container_width=True, hide_index=True)
    
    # AI 诊断（若已有结果则显示，否则提供按钮）
    if diagnosis_result is not None and diagnosis_result.get("style") == style_code:
        st.markdown(f"""
        <div class="diagnosis-box">
            <div style="font-weight:600; margin-bottom:8px;">📋 诊断结论</div>
            <div>{diagnosis_result['text']}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        if st.button(f"🤖 生成AI诊断 ({style_code})", key=f"pa_ai_diag_{style_code}"):
            trend_desc = "销售趋势" + ("上升" if len(daily) > 1 and daily["net"].iloc[-1] > daily["net"].iloc[0] else "下降") if len(daily) > 1 else "无趋势"
            context = f"""
            商品货号: {style_code}
            品牌: {brand}
            品类: {category}
            总净销售额: ¥{total_net:,.2f}
            总发货额: ¥{total_ship:,.2f}
            总退货额: ¥{total_return:,.2f}
            退货率: {return_rate:.1f}%
            订单数: {order_count}
            覆盖店铺数: {unique_shops}
            覆盖主播数: {anchor_count}
            首单礼金: {"是" if coupon else "否"}
            {trend_desc}
            同类商品平均退货率: {filtered_df[filtered_df['categories']==category]['退货率'].mean() if category!='未知' else filtered_df['退货率'].mean():.1f}%
            """
            prompt = """
            你是一位资深的商品运营专家。请根据以下商品数据，给出简洁、专业的诊断报告（200字以内）。
            要求：
            1. 指出该商品的核心表现（亮点或问题）
            2. 如果有问题，分析可能原因
            3. 给出1-2条可操作的建议
            4. 语气专业但易懂
            """
            with st.spinner("AI 正在分析..."):
                diagnosis_text = get_ai_summary(prompt, context, "Qwen2.5-7B")
            st.session_state.pa_diagnosis_result = {"style": style_code, "text": diagnosis_text}
            st.rerun()

# ---------- 定义四象限点击诊断对话框（使用装饰器） ----------
@st.dialog("📦 商品诊断", width="large")
def show_quadrant_diagnosis(style_code, filtered_df, start_date, end_date, platform):
    """四象限点击弹出的诊断对话框"""
    show_product_diagnosis(style_code, filtered_df, "_all", start_date, end_date, platform, st.session_state.pa_diagnosis_result)
    if st.button("关闭", key="pa_quadrant_dialog_close"):
        st.session_state.pa_show_quadrant_dialog = False
        st.session_state.pa_quadrant_click_style = None
        st.rerun()

# ---------- 侧边栏筛选 ----------
st.sidebar.header("🔍 筛选条件")

platform_options = ["全部", "抖音", "视频号", "小红书", "天猫", "唯品会"]
selected_platform = st.sidebar.selectbox("平台", platform_options, index=0, key="pa_platform")

df_temp = load_product_sales("_all", include_offline=False)
min_date = date(2024, 1, 1)
max_date = date.today()
if not df_temp.empty:
    min_date = df_temp["sale_date"].min().date()
    max_date = df_temp["sale_date"].max().date()

st.sidebar.markdown("**日期范围**")
start_date = st.sidebar.date_input("开始日期", min_date, min_value=min_date, max_value=max_date, key="pa_start")
end_date = st.sidebar.date_input("结束日期", max_date, min_value=min_date, max_value=max_date, key="pa_end")
if start_date > end_date:
    st.sidebar.error("开始日期不能晚于结束日期")
    st.stop()

all_brands = []
all_categories = []
if not df_temp.empty:
    if "brand" in df_temp.columns:
        all_brands = sorted(df_temp["brand"].dropna().unique())
    if "master_category" in df_temp.columns:
        all_categories = sorted(df_temp["master_category"].dropna().unique())

st.sidebar.markdown("**商品属性**")
selected_brands = st.sidebar.multiselect("品牌", all_brands, default=[])
selected_categories = st.sidebar.multiselect("品类", all_categories, default=[])
min_net = st.sidebar.number_input("最小净销售额", value=0, step=100)
max_net = st.sidebar.number_input("最大净销售额", value=100000000, step=1000, format="%d")
max_return_rate = st.sidebar.slider("最大退货率 (%)", 0, 100, 100)

with st.spinner("加载商品数据..."):
    df_products = load_assistant_data("_all", start_date, end_date, selected_platform)
    if df_products.empty:
        st.warning("没有找到任何商品数据，请检查日期范围或筛选条件。")
        st.stop()

filtered = df_products.copy()
if selected_brands:
    filtered = filtered[filtered["brands"].isin(selected_brands)]
if selected_categories:
    filtered = filtered[filtered["categories"].isin(selected_categories)]
filtered = filtered[(filtered["净销售额"] >= min_net) & (filtered["净销售额"] <= max_net)]
filtered = filtered[filtered["退货率"] <= max_return_rate]

if filtered.empty:
    st.warning("没有商品满足当前筛选条件，请调整筛选条件。")
    st.stop()

# ---------- 主页面 ----------
st.title("📦 商品分析助手")
st.caption("基于商品销售数据的智能分析与决策支持")

# ---------- 概览 KPI ----------
st.markdown("#### 📊 概览")
total_products = len(filtered)
active_products = len(filtered[filtered["最近销售日期"] >= (date.today() - timedelta(days=30))])
total_net = filtered["净销售额"].sum()
total_return_rate = (filtered["退货额"].sum() / filtered["发货额"].sum() * 100) if filtered["发货额"].sum() > 0 else 0
avg_return_rate = filtered["退货率"].mean()
coupon_products = filtered[filtered["has_newbie_coupon"]].shape[0]

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">商品总数</div>
        <div class="kpi-number">{total_products}</div>
        <div style="font-size:13px; color:#64748b;">动销（近30天）: {active_products}</div>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">总净销售额</div>
        <div class="kpi-number">¥{total_net:,.0f}</div>
        <div style="font-size:13px; color:#64748b;">平均单品 ¥{total_net/total_products:,.0f}</div>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">综合退货率</div>
        <div class="kpi-number">{total_return_rate:.1f}%</div>
        <div style="font-size:13px; color:#64748b;">平均退货率 {avg_return_rate:.1f}%</div>
    </div>
    """, unsafe_allow_html=True)
with col4:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">首单礼金商品</div>
        <div class="kpi-number">{coupon_products}</div>
        <div style="font-size:13px; color:#64748b;">占比 {coupon_products/total_products*100:.1f}%</div>
    </div>
    """, unsafe_allow_html=True)
with col5:
    stagnant = filtered[filtered["最近销售日期"] < (date.today() - timedelta(days=30))]
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">滞销商品（>30天无销售）</div>
        <div class="kpi-number" style="color:#ef4444;">{len(stagnant)}</div>
        <div style="font-size:13px; color:#64748b;">占比 {len(stagnant)/total_products*100:.1f}%</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ---------- 四象限矩阵 ----------
st.markdown("#### 📐 商品四象限矩阵")
st.caption("横轴：退货率（越低越好），纵轴：净销售额（越高越好），点击任意商品点可弹出诊断窗口")

if len(filtered) > 1:
    x_threshold = filtered["退货率"].quantile(0.6)
    y_threshold = filtered["净销售额"].quantile(0.4)

    filtered["象限"] = "其他"
    filtered.loc[(filtered["净销售额"] >= y_threshold) & (filtered["退货率"] <= x_threshold), "象限"] = "🌟 明星品"
    filtered.loc[(filtered["净销售额"] >= y_threshold) & (filtered["退货率"] > x_threshold), "象限"] = "⚠️ 问题品"
    filtered.loc[(filtered["净销售额"] < y_threshold) & (filtered["退货率"] <= x_threshold), "象限"] = "💰 现金牛"
    filtered.loc[(filtered["净销售额"] < y_threshold) & (filtered["退货率"] > x_threshold), "象限"] = "🐶 瘦狗品"

    fig = px.scatter(filtered, x="退货率", y="净销售额", color="象限", 
                     hover_data={"style_code": True, "brands": True, "categories": True, "has_newbie_coupon": True},
                     custom_data=["style_code"],
                     title="商品四象限矩阵", labels={"退货率": "退货率 (%)", "净销售额": "净销售额 (¥)"},
                     color_discrete_map={
                         "🌟 明星品": "#22c55e",
                         "⚠️ 问题品": "#f59e0b",
                         "💰 现金牛": "#3b82f6",
                         "🐶 瘦狗品": "#94a3b8",
                         "其他": "#e2e8f0"
                     })
    
    fig.update_traces(
        marker=dict(
            size=12,
            line=dict(width=1, color='black'),
            opacity=0.9
        )
    )
    fig.update_traces(selectedpoints=[])
    
    fig.add_hline(y=y_threshold, line_dash="dash", line_color="gray", annotation_text=f"净额阈值 {y_threshold:,.0f}")
    fig.add_vline(x=x_threshold, line_dash="dash", line_color="gray", annotation_text=f"退货率阈值 {x_threshold:.1f}%")
    fig.update_layout(height=500, margin=dict(l=0, r=0, t=40, b=0), hovermode="closest")
    
    event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", key="quadrant_chart")
    
    if event and event.get("selection"):
        points = event["selection"].get("points", [])
        if points:
            customdata = points[0].get("customdata")
            if customdata and len(customdata) > 0:
                style_code = customdata[0]
                if style_code != st.session_state.pa_quadrant_click_style:
                    st.session_state.pa_quadrant_click_style = style_code
                    st.session_state.pa_show_quadrant_dialog = True
                    st.rerun()

    # 四象限说明按钮
    col_q1, col_q2, col_q3, col_q4 = st.columns(4)
    with col_q1:
        st.markdown("**🌟 明星品** (高销低退) 建议：维持并加大推广")
        if st.button("查看明星品", key="q_star"):
            st.session_state.pa_selected_products = filtered[filtered["象限"] == "🌟 明星品"]["style_code"].tolist()
            st.rerun()
    with col_q2:
        st.markdown("**⚠️ 问题品** (高销高退) 建议：检查质量/售后")
        if st.button("查看问题品", key="q_problem"):
            st.session_state.pa_selected_products = filtered[filtered["象限"] == "⚠️ 问题品"]["style_code"].tolist()
            st.rerun()
    with col_q3:
        st.markdown("**💰 现金牛** (低销低退) 建议：稳定维护")
        if st.button("查看现金牛", key="q_cow"):
            st.session_state.pa_selected_products = filtered[filtered["象限"] == "💰 现金牛"]["style_code"].tolist()
            st.rerun()
    with col_q4:
        st.markdown("**🐶 瘦狗品** (低销高退) 建议：考虑淘汰")
        if st.button("查看瘦狗品", key="q_dog"):
            st.session_state.pa_selected_products = filtered[filtered["象限"] == "🐶 瘦狗品"]["style_code"].tolist()
            st.rerun()
else:
    st.info("商品数量不足，无法生成四象限图。")

st.markdown("---")

# ---------- 处理四象限点击对话框 ----------
if st.session_state.pa_show_quadrant_dialog and st.session_state.pa_quadrant_click_style:
    show_quadrant_diagnosis(
        st.session_state.pa_quadrant_click_style,
        filtered,
        start_date,
        end_date,
        selected_platform
    )

# ---------- 智能预警 ----------
st.markdown("#### 🚨 智能预警")
alerts = []

stagnant_products = filtered[filtered["最近销售日期"] < (date.today() - timedelta(days=30))]
if not stagnant_products.empty:
    for _, row in stagnant_products.head(5).iterrows():
        alerts.append(("critical", f"📉 商品 {row['style_code']} 已滞销超过30天，最近销售日期 {row['最近销售日期']}"))

if len(filtered) > 0:
    df_detail = load_product_sales("_all", include_offline=False)
    if not df_detail.empty:
        df_detail["sale_date"] = pd.to_datetime(df_detail["sale_date"])
        if selected_platform and selected_platform != "全部":
            if selected_platform == "抖音":
                df_detail = df_detail[df_detail["shop_name"].str.contains("抖音", case=False, na=False)]
            elif selected_platform == "视频号":
                df_detail = df_detail[df_detail["shop_name"].str.contains("视频号", case=False, na=False)]
            elif selected_platform == "小红书":
                df_detail = df_detail[df_detail["shop_name"].str.contains("小红书", case=False, na=False)]
            elif selected_platform == "天猫":
                df_detail = df_detail[df_detail["shop_name"].str.contains("天猫", case=False, na=False)]
            elif selected_platform == "唯品会":
                df_detail = df_detail[df_detail["shop_name"].str.contains("唯品会", case=False, na=False)]
        today = pd.Timestamp(date.today())
        recent_start = today - pd.Timedelta(days=14)
        df_recent = df_detail[df_detail["sale_date"] >= recent_start]
        if not df_recent.empty:
            if "style_code" not in df_recent.columns:
                df_recent["style_code"] = df_recent["product_code"].str[:8].str.strip().str.upper()
            else:
                df_recent["style_code"] = df_recent["style_code"].astype(str).str.strip().str.upper()
            df_recent["week"] = np.where(df_recent["sale_date"] >= (today - pd.Timedelta(days=7)), "近7天", "前7天")
            if "ship_amount" in df_recent.columns and "return_amount" in df_recent.columns:
                weekly = df_recent.groupby(["style_code", "week"]).agg(ship=("ship_amount", "sum"), ret=("return_amount", "sum")).reset_index()
                pivot = weekly.pivot(index="style_code", columns="week", values=["ship", "ret"]).fillna(0)
                pivot.columns = ['_'.join(col).strip() for col in pivot.columns.values]
                if "ship_近7天" in pivot.columns and "ship_前7天" in pivot.columns:
                    pivot["退货率_近7天"] = pivot["ret_近7天"] / (pivot["ship_近7天"] + 1e-6) * 100
                    pivot["退货率_前7天"] = pivot["ret_前7天"] / (pivot["ship_前7天"] + 1e-6) * 100
                    pivot["退货率_变化"] = pivot["退货率_近7天"] - pivot["退货率_前7天"]
                    high_risk = pivot[(pivot["退货率_变化"] > 10) & (pivot["ship_前7天"] > 0)].sort_values("退货率_变化", ascending=False)
                    for style, row in high_risk.head(3).iterrows():
                        alerts.append(("critical", f"📦 商品 {style} 退货率飙升 {row['退货率_变化']:.1f} 个百分点（前7天 {row['退货率_前7天']:.1f}% → 近7天 {row['退货率_近7天']:.1f}%）"))

if len(filtered) > 0:
    new_products = filtered[filtered["首次销售日期"] >= (date.today() - timedelta(days=30))]
    if not new_products.empty:
        median_net = filtered["净销售额"].median()
        underperform = new_products[new_products["净销售额"] < median_net * 0.5]
        for _, row in underperform.head(3).iterrows():
            alerts.append(("warning", f"🆕 新品 {row['style_code']} 表现低于同类中位数，净销售额仅 {row['净销售额']:,.0f}（同类中位数 {median_net:,.0f}）"))

coupon_products_df = filtered[filtered["has_newbie_coupon"]]
if not coupon_products_df.empty:
    median_return = filtered["退货率"].median()
    high_return_coupon = coupon_products_df[coupon_products_df["退货率"] > median_return * 1.5]
    for _, row in high_return_coupon.head(3).iterrows():
        alerts.append(("warning", f"🎁 首单礼金商品 {row['style_code']} 退货率 {row['退货率']:.1f}% 高于整体水平（{median_return:.1f}%），建议检查活动设置"))

if not alerts:
    st.success("✅ 当前无重大异常预警，继续保持！")
else:
    for level, msg in alerts:
        cls = "critical" if level == "critical" else "warning"
        st.markdown(f"<div class='alert-card {cls}'>{msg}</div>", unsafe_allow_html=True)

st.markdown("---")

# ---------- 对比分析 ----------
st.markdown("#### 📊 对比分析")
st.caption("选择多个商品进行对比（最多5个）")

compare_options = st.multiselect("选择商品进行对比", options=sorted(filtered["style_code"].unique()), default=st.session_state.pa_compare_products, key="pa_compare_select_new")
if len(compare_options) > 5:
    st.warning("最多选择5个商品")
    compare_options = compare_options[:5]
st.session_state.pa_compare_products = compare_options

if len(st.session_state.pa_compare_products) >= 2:
    compare_df = filtered[filtered["style_code"].isin(st.session_state.pa_compare_products)].copy()
    metric_options = ["净销售额", "发货额", "退货额", "退货率", "订单数", "动销天数"]
    compare_metrics = st.multiselect("选择对比指标", metric_options, default=["净销售额", "退货率", "订单数"])
    if compare_metrics:
        radar_data = compare_df[["style_code"] + compare_metrics].copy()
        for m in compare_metrics:
            if m != "退货率":
                max_val = radar_data[m].max()
                if max_val > 0:
                    radar_data[f"{m}_norm"] = radar_data[m] / max_val * 100
                else:
                    radar_data[f"{m}_norm"] = 0
            else:
                radar_data[f"{m}_norm"] = radar_data[m]
        fig_radar = go.Figure()
        for _, row in radar_data.iterrows():
            fig_radar.add_trace(go.Scatterpolar(
                r=[row[f"{m}_norm"] for m in compare_metrics],
                theta=compare_metrics,
                fill='toself',
                name=row["style_code"]
            ))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            height=400,
            margin=dict(l=80, r=80, t=20, b=20)
        )
        st.plotly_chart(fig_radar, use_container_width=True)
        
        st.dataframe(compare_df[["style_code"] + compare_metrics], hide_index=True, use_container_width=True)

        if st.button("清除对比", key="pa_clear_compare_new"):
            st.session_state.pa_compare_products = []
            st.rerun()

st.markdown("---")

# ---------- AI 智能报告 ----------
st.markdown("#### 📄 AI 智能报告")
if st.button("🚀 生成当前筛选条件下的智能报告", key="pa_generate_report_new"):
    total_products = len(filtered)
    total_net = filtered["净销售额"].sum()
    avg_return = filtered["退货率"].mean()
    top_products = filtered.nlargest(5, "净销售额")[["style_code", "净销售额", "退货率"]]
    top_return = filtered.nlargest(5, "退货率")[["style_code", "退货率"]]
    coupon_perf = filtered.groupby("has_newbie_coupon")["净销售额"].sum()
    coupon_ratio = coupon_perf.get(True, 0) / total_net * 100 if total_net > 0 else 0
    
    context = f"""
    分析期间: {start_date} 至 {end_date}
    商品总数: {total_products}
    总净销售额: ¥{total_net:,.2f}
    平均退货率: {avg_return:.1f}%
    首单礼金商品贡献: {coupon_ratio:.1f}%
    销售额TOP5商品: {', '.join([f"{r['style_code']}(¥{r['净销售额']:,.0f})" for _, r in top_products.iterrows()])}
    退货率TOP5商品: {', '.join([f"{r['style_code']}({r['退货率']:.1f}%)" for _, r in top_return.iterrows()])}
    """
    prompt = """
    你是一位资深的电商商品运营总监。请根据以上数据，生成一份专业、简洁的商品分析报告（300字左右）。
    报告应包括：
    1. 整体商品表现概述
    2. 亮点（表现最好的商品/品类）
    3. 风险点（需关注的商品/问题）
    4. 优化建议（具体可执行）
    """
    with st.spinner("AI 正在生成报告..."):
        report = get_ai_summary(prompt, context, "Qwen2.5-7B")
    st.session_state.pa_report = report
    st.rerun()

if "pa_report" in st.session_state and st.session_state.pa_report:
    st.markdown(f"""
    <div class="diagnosis-box" style="background:#f0f9ff; border-color:#3b82f6;">
        <div style="font-weight:600; margin-bottom:8px;">📊 商品运营报告</div>
        <div>{st.session_state.pa_report}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ---------- 导出 ----------
st.markdown("#### 💾 导出数据")
if st.button("📥 导出当前筛选的商品列表（Excel）", key="pa_export_new"):
    export_df = filtered[["style_code", "brands", "categories", "净销售额", "发货额", "退货额", "退货率", "订单数", "最近销售日期", "has_newbie_coupon"]].copy()
    export_df.rename(columns={
        "style_code": "货号",
        "brands": "品牌",
        "categories": "品类",
        "净销售额": "净销售额(¥)",
        "发货额": "发货额(¥)",
        "退货额": "退货额(¥)",
        "退货率": "退货率(%)",
        "订单数": "订单数",
        "最近销售日期": "最近销售日期",
        "has_newbie_coupon": "首单礼金"
    }, inplace=True)
    export_df["首单礼金"] = export_df["首单礼金"].map({True: "是", False: "否"})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        export_df.to_excel(writer, index=False, sheet_name="商品分析")
    st.download_button(
        "点击下载 Excel",
        data=output.getvalue(),
        file_name=f"商品分析_{start_date}_{end_date}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="pa_download_new"
    )
