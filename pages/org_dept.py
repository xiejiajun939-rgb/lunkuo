# pages/org_dept.py
# -*- coding: utf-8 -*-
"""
组织与部门分析页面
展示阿米巴组织、部门、店铺的多维度业绩分析
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
import plotly.express as px
import plotly.graph_objects as go
import io

from core.db import init_supabase, get_table_name, fetch_sales_summary, load_org_targets, fetch_complete_sales_summary
from core.ai import get_ai_summary

st.set_page_config(page_title="组织与部门分析", layout="wide")

# 仅支持全部数据
if st.session_state.get("table_suffix") != "_all":
    st.warning("该页面仅支持“全部数据”源，请切换数据源后重试。")
    st.stop()

# ---------- 辅助函数 ----------
@st.cache_data(ttl=600)
def get_date_range(suffix):
    """获取数据表中的最早和最晚日期"""
    supabase = init_supabase()
    if supabase is None:
        return None, None
    try:
        min_dates, max_dates = [], []
        
        # 查询 product_sales 表
        table_name = get_table_name("product_sales", suffix)
        resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=False).limit(1).execute()
        if resp.data:
            min_dates.append(pd.to_datetime(resp.data[0]["sale_date"]).date())
        resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=True).limit(1).execute()
        if resp.data:
            max_dates.append(pd.to_datetime(resp.data[0]["sale_date"]).date())
        
        # 查询 offline_sales_all 表（全部数据时）
        if suffix == "_all":
            try:
                offline_resp = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=False).limit(1).execute()
                if offline_resp.data:
                    min_dates.append(pd.to_datetime(offline_resp.data[0]["sale_date"]).date())
                offline_resp = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=True).limit(1).execute()
                if offline_resp.data:
                    max_dates.append(pd.to_datetime(offline_resp.data[0]["sale_date"]).date())
            except:
                pass
        
        if min_dates and max_dates:
            return min(min_dates), max(max_dates)
        return None, None
    except Exception as e:
        st.error(f"获取日期范围失败：{e}")
        return None, None

# ---------- 日期选择 ----------
min_date, max_date = get_date_range("_all")
if min_date is None or max_date is None:
    st.warning("无法获取数据日期范围，请检查数据表是否存在。")
    st.stop()

st.markdown("#### 📅 日期选择")
base_date = st.date_input(
    "选择分析基准日期",
    value=max_date,
    min_value=min_date,
    max_value=max_date,
    key="org_base_date"
)
st.caption(f"当前数据日期范围：{min_date} ~ {max_date}，您可以选择任意日期查看对应数据。")

# ======================== 1. 核心大盘 KPI ========================
st.markdown("---")
st.markdown("#### 📊 营销中心整体销售")
latest_date = base_date
month_start = latest_date.replace(day=1)

suffix = "_all"
org_targets = load_org_targets("_all")
total_target = sum(org_targets.values()) if org_targets else 0

with st.spinner("加载 KPI 数据..."):
    # 使用完整的销售汇总函数
    df_today = fetch_complete_sales_summary(latest_date, latest_date, suffix)
    df_mtd = fetch_complete_sales_summary(month_start, latest_date, suffix)

# 调试信息 - 检查数据是否正常加载
if df_today.empty:
    st.info(f"📌 提示：{latest_date} 无销售数据，显示月累计数据。")
    today_ship = 0
    today_return = 0
    today_net = 0
else:
    today_ship = df_today['total_ship'].sum()
    today_return = df_today['total_return'].sum()
    today_net = df_today['total_net'].sum()

if not df_mtd.empty:
    mtd_ship = df_mtd['total_ship'].sum()
    mtd_return = df_mtd['total_return'].sum()
    mtd_net = df_mtd['total_net'].sum()
    mtd_return_rate = (mtd_return / (mtd_ship + 1e-5) * 100) if mtd_ship > 0 else 0
else:
    mtd_ship = 0
    mtd_return = 0
    mtd_net = 0
    mtd_return_rate = 0

target_rate = (mtd_net / total_target * 100) if total_target > 0 else 0

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"**📅 最新日（{latest_date.strftime('%Y-%m-%d')}）**")
    if df_today.empty:
        st.metric("净销售额", "无数据")
    else:
        st.metric("净销售额", f"¥{today_net:,.2f}",
                  delta=f"发货 ¥{today_ship:,.2f} | 退货 ¥{today_return:,.2f}")
with col2:
    st.markdown(f"**📆 月累计（{latest_date.strftime('%Y-%m')}）**")
    st.metric("净销售额", f"¥{mtd_net:,.2f}",
              delta=f"发货 ¥{mtd_ship:,.2f} | 退货 ¥{mtd_return:,.2f} | 退货率 {mtd_return_rate:.2f}%")
    bar_color = "#4ade80" if target_rate >= 80 else "#fbbf24" if target_rate >= 50 else "#f87171"
    st.markdown(f"""
    <div style="margin-top:12px; padding-top:8px; border-top:1px solid #e2e8f0;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:14px; color:#475569; font-weight:500;">月目标完成率</span>
            <span style="font-size:18px; font-weight:700; color:#0f172a;">{target_rate:.1f}%</span>
        </div>
        <div style="width:100%; height:6px; background:#e2e8f0; border-radius:3px; margin-top:6px; overflow:hidden;">
            <div style="width:{min(target_rate,100)}%; height:100%; background:{bar_color}; border-radius:3px; transition:width 0.8s ease;"></div>
        </div>
        <div style="display:flex; justify-content:space-between; margin-top:4px;">
            <span style="color:#64748b; font-size:13px;">目标 ¥{total_target:,.0f}</span>
            <span style="color:#64748b; font-size:13px;">已达成 ¥{mtd_net:,.0f}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ======================== 2. 趋势分析（近7天 vs 前7天） ========================
st.markdown("---")
st.markdown("#### 📈 趋势分析：近7天 vs 前7天")

period_start = base_date - timedelta(days=6)
prev_period_start = base_date - timedelta(days=13)
prev_period_end = base_date - timedelta(days=7)

with st.spinner("加载趋势数据..."):
    df_7d = fetch_complete_sales_summary(period_start, base_date, suffix)
    df_prev = fetch_complete_sales_summary(prev_period_start, prev_period_end, suffix)

st.markdown("##### 汇总统计")
if not df_7d.empty and 'total_net' in df_7d.columns:
    total_7d = df_7d['total_net'].sum()
    total_prev = df_prev['total_net'].sum() if not df_prev.empty else 0
    change = ((total_7d - total_prev) / (total_prev + 1e-5) * 100) if total_prev != 0 else 0
    col_stat1, col_stat2, col_stat3 = st.columns(3)
    col_stat1.metric("近7天净销售额", f"¥{total_7d:,.2f}")
    col_stat2.metric("前7天净销售额", f"¥{total_prev:,.2f}")
    col_stat3.metric("环比变化", f"{change:+.2f}%",
                     delta="增长" if change >= 0 else "下降", delta_color="normal")
else:
    st.info("近7天无数据，无法统计。")

st.markdown("##### 每日趋势对比（近7天 vs 前7天同期）")
if (not df_7d.empty and 'sale_date' in df_7d.columns and 
    not df_prev.empty and 'sale_date' in df_prev.columns):
    df_7d_daily = df_7d.groupby('sale_date')['total_net'].sum().reset_index()
    df_prev_daily = df_prev.groupby('sale_date')['total_net'].sum().reset_index()
    df_7d_daily['sale_date'] = pd.to_datetime(df_7d_daily['sale_date'])
    df_prev_daily['sale_date'] = pd.to_datetime(df_prev_daily['sale_date'])
    df_prev_daily['sale_date_aligned'] = df_prev_daily['sale_date'] + pd.Timedelta(days=7)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_7d_daily['sale_date'],
        y=df_7d_daily['total_net'],
        mode='lines+markers',
        name='近7天',
        line=dict(color='#22c55e', width=2.5),
        marker=dict(size=6)
    ))
    fig.add_trace(go.Scatter(
        x=df_prev_daily['sale_date_aligned'],
        y=df_prev_daily['total_net'],
        mode='lines+markers',
        name='前7天（同期）',
        line=dict(color='#3b82f6', width=2.5, dash='dash'),
        marker=dict(size=6)
    ))
    fig.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=10, b=0),
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        yaxis_title='净销售额 (¥)',
        xaxis_title='日期（近7天）',
        xaxis=dict(
            tickformat='%m-%d',
            range=[df_7d_daily['sale_date'].min(), df_7d_daily['sale_date'].max()]
        )
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("无足够数据绘制趋势图（需同时拥有近7天和前7天数据）。")

# ======================== 3. 组织与部门拆解 ========================
st.markdown("---")
st.markdown("#### 🏆 阿米巴组织与部门业绩拆解")

# ---------- 3.1 组织饼图 + 部门排行 ----------
st.markdown("##### 组织与部门分布")
time_mode_main = st.radio(
    "查看周期",
    options=["近7天", "月累计"],
    index=0,
    horizontal=True,
    key="org_dept_main_mode"
)
if time_mode_main == "近7天":
    start_date = base_date - timedelta(days=6)
    end_date = base_date
    period_label = "近7天"
else:
    start_date = base_date.replace(day=1)
    end_date = base_date
    period_label = f"月累计（{base_date.strftime('%Y-%m')}）"

with st.spinner(f"加载 {period_label} 数据..."):
    df_period_main = fetch_complete_sales_summary(start_date, end_date, suffix)

if not df_period_main.empty:
    # 数据概览 - 帮助识别是否有数据遗漏
    with st.expander("📋 数据概览（查看所有组织/部门映射情况）"):
        # 显示组织列表
        org_list = df_period_main['org_name'].unique().tolist()
        dept_list = df_period_main['dept'].unique().tolist()
        st.write(f"共识别到 **{len(org_list)}** 个组织：{', '.join(org_list)}")
        st.write(f"共识别到 **{len(dept_list)}** 个部门：{', '.join(dept_list[:20])}{'...' if len(dept_list) > 20 else ''}")
        
        # 显示各组织的汇总数据
        org_summary = df_period_main.groupby('org_name').agg({
            'total_net': 'sum',
            'total_ship': 'sum',
            'total_return': 'sum'
        }).reset_index()
        org_summary['净额'] = org_summary['total_net'].apply(lambda x: f"¥{x:,.2f}")
        org_summary = org_summary.sort_values('total_net', ascending=False)
        st.dataframe(org_summary[['org_name', '净额', 'total_ship', 'total_return']], 
                     hide_index=True, use_container_width=True)
        
        # 显示部门汇总
        dept_summary = df_period_main.groupby('dept').agg({
            'total_net': 'sum',
            'total_ship': 'sum',
            'total_return': 'sum'
        }).reset_index()
        dept_summary['净额'] = dept_summary['total_net'].apply(lambda x: f"¥{x:,.2f}")
        dept_summary = dept_summary.sort_values('total_net', ascending=False)
        st.dataframe(dept_summary[['dept', '净额', 'total_ship', 'total_return']], 
                     hide_index=True, use_container_width=True)
    
    col_org, col_dept = st.columns(2)
    with col_org:
        # 组织汇总 - 显示所有组织（包括负值）
        org_agg = df_period_main.groupby('org_name')['total_net'].sum().reset_index()
        org_agg = org_agg.sort_values('total_net', ascending=False)
        
        # 分离正负值用于显示
        org_agg_positive = org_agg[org_agg['total_net'] > 0].copy()
        org_agg_negative = org_agg[org_agg['total_net'] < 0].copy()
        
        if not org_agg_positive.empty:
            fig_org = px.pie(org_agg_positive, names='org_name', values='total_net',
                             title=f'各阿米巴净销售额占比（{period_label}）',
                             hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_org.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_org, use_container_width=True)
        else:
            st.info("无盈利阿米巴")
        
        # 显示负值组织警告
        if not org_agg_negative.empty:
            neg_text = ", ".join([f"{row['org_name']} (¥{row['total_net']:,.2f})" 
                                 for _, row in org_agg_negative.iterrows()])
            st.warning(f"⚠️ 以下组织净销售额为负：{neg_text}")
        
        # 显示组织排行（所有组织）
        st.markdown("**组织排行（完整）**")
        org_display = org_agg.copy()
        org_display['净额'] = org_display['total_net'].apply(lambda x: f"¥{x:,.2f}")
        st.dataframe(org_display[['org_name', '净额']], hide_index=True, use_container_width=True)
            
    with col_dept:
        dept_agg = df_period_main.groupby('dept')['total_net'].sum().reset_index()
        dept_agg = dept_agg[dept_agg['total_net'] != 0].sort_values('total_net', ascending=False)
        if not dept_agg.empty:
            # 显示所有部门，但图表只显示TOP10
            top10 = dept_agg.head(10)
            fig_dept = px.bar(top10, x='total_net', y='dept', orientation='h',
                              title=f'部门净销售额排行（TOP10，{period_label}）',
                              labels={'total_net': '净销售额', 'dept': '部门'},
                              color='total_net', color_continuous_scale='Blues')
            fig_dept.update_layout(yaxis={'categoryorder': 'total ascending'})
            st.plotly_chart(fig_dept, use_container_width=True)
            
            # 显示所有部门
            st.markdown("**部门排行（完整）**")
            dept_display = dept_agg.copy()
            dept_display['净额'] = dept_display['total_net'].apply(lambda x: f"¥{x:,.2f}")
            st.dataframe(dept_display[['dept', '净额']], hide_index=True, use_container_width=True)
        else:
            st.info("无部门数据")
else:
    st.warning(f"{period_label} 无数据，无法显示阿米巴/部门分布。")

# ---------- 3.2 退货率警告线 ----------
st.markdown("#### 退货率警告线")
time_mode_return = st.radio(
    "查看周期",
    options=["近7天", "月累计"],
    index=0,
    horizontal=True,
    key="org_dept_return_mode",
    label_visibility="collapsed"
)
if time_mode_return == "近7天":
    start_date_r = base_date - timedelta(days=6)
    end_date_r = base_date
    period_label_r = "近7天"
else:
    start_date_r = base_date.replace(day=1)
    end_date_r = base_date
    period_label_r = f"月累计（{base_date.strftime('%Y-%m')}）"

with st.spinner(f"加载退货率数据（{period_label_r}）..."):
    df_return = fetch_complete_sales_summary(start_date_r, end_date_r, suffix)

if not df_return.empty:
    dept_return = df_return.groupby('dept').agg(
        ship=('total_ship', 'sum'),
        return_amt=('total_return', 'sum'),
        net=('total_net', 'sum')
    ).reset_index()
    
    # 计算退货率（保留所有部门）
    dept_return['退货率'] = (dept_return['return_amt'] / (dept_return['ship'] + 1e-5) * 100).round(2)
    
    # 显示所有部门（按退货率排序）
    dept_return_sorted = dept_return.sort_values('退货率', ascending=False)
    
    if not dept_return_sorted.empty:
        # 图表显示TOP10
        top_return = dept_return_sorted.head(10)
        fig_return = px.bar(top_return, x='dept', y='退货率',
                            title=f'退货率 TOP10 部门（{period_label_r}）',
                            labels={'dept': '部门', '退货率': '退货率 (%)'},
                            color=top_return['退货率'], color_continuous_scale='RdYlGn_r')
        fig_return.add_hline(y=50, line_dash="dash", line_color="red", annotation_text="警戒线 50%")
        fig_return.add_hline(y=30, line_dash="dash", line_color="orange", annotation_text="注意线 30%")
        st.plotly_chart(fig_return, use_container_width=True)
        
        # 显示所有部门退货率
        with st.expander("📋 所有部门退货率明细"):
            dept_display = dept_return_sorted.copy()
            dept_display['退货率'] = dept_display['退货率'].apply(lambda x: f"{x:.2f}%")
            dept_display['净额'] = dept_display['net'].apply(lambda x: f"¥{x:,.2f}")
            dept_display['发货额'] = dept_display['ship'].apply(lambda x: f"¥{x:,.2f}")
            dept_display['退货额'] = dept_display['return_amt'].apply(lambda x: f"¥{x:,.2f}")
            st.dataframe(dept_display[['dept', '净额', '发货额', '退货额', '退货率']], 
                         hide_index=True, use_container_width=True)
        
        # 显示零发货但有退货的异常部门
        zero_ship_returns = dept_return[(dept_return['ship'] == 0) & (dept_return['return_amt'] > 0)]
        if not zero_ship_returns.empty:
            st.warning(f"⚠️ 以下部门有退货但无发货记录：{', '.join(zero_ship_returns['dept'].tolist())}")
    else:
        st.info("无有效部门数据")
else:
    st.warning(f"{period_label_r} 无数据，无法显示退货率。")

# ---------- 3.3 多维透视 ----------
st.markdown("#### 🔍 多维透视（组织 → 部门 → 店铺）")
time_mode_pivot = st.radio(
    "查看周期",
    options=["近7天", "月累计"],
    index=0,
    horizontal=True,
    key="org_dept_pivot_mode",
    label_visibility="collapsed"
)
if time_mode_pivot == "近7天":
    start_date_p = base_date - timedelta(days=6)
    end_date_p = base_date
    period_label_p = "近7天"
else:
    start_date_p = base_date.replace(day=1)
    end_date_p = base_date
    period_label_p = f"月累计（{base_date.strftime('%Y-%m')}）"

with st.spinner(f"加载透视数据（{period_label_p}）..."):
    df_pivot = fetch_complete_sales_summary(start_date_p, end_date_p, suffix)

if not df_pivot.empty:
    # 平台分类
    def classify_platform(shop_name):
        if not shop_name or not isinstance(shop_name, str):
            return '其他'
        shop_name = str(shop_name)
        if '天猫' in shop_name or shop_name.startswith('TM'):
            return '天猫'
        elif '小红书' in shop_name:
            return '小红书'
        elif '抖音' in shop_name or 'DOU' in shop_name:
            return '抖音'
        elif '视频号' in shop_name:
            return '视频号'
        elif '京东' in shop_name:
            return '京东'
        elif '拼多多' in shop_name:
            return '拼多多'
        elif '淘宝' in shop_name:
            return '淘宝'
        elif '线下' in shop_name or '门店' in shop_name:
            return '线下门店'
        elif '微信' in shop_name or '小程序' in shop_name:
            return '微信'
        else:
            return '其他'
    
    df_pivot['platform'] = df_pivot['shop_name'].apply(classify_platform)
    
    # 按组织、部门、平台、店铺聚合
    grouped = df_pivot.groupby(['org_name', 'dept', 'platform', 'shop_name']).agg(
        ship=('total_ship', 'sum'),
        return_amt=('total_return', 'sum'),
        net=('total_net', 'sum')
    ).reset_index()
    grouped['退货率'] = (grouped['return_amt'] / (grouped['ship'] + 1e-5) * 100).round(2)
    grouped['退货率显示'] = grouped['退货率'].apply(lambda x: f"{x:.2f}%")

    # 按组织净额排序
    org_order = grouped.groupby('org_name')['net'].sum().sort_values(ascending=False).index
    
    # 显示所有组织
    for org in org_order:
        org_data = grouped[grouped['org_name'] == org]
        org_net = org_data['net'].sum()
        org_ship = org_data['ship'].sum()
        org_return = org_data['return_amt'].sum()
        
        # 颜色标识：负值用红色
        color_icon = "🔴" if org_net < 0 else "🟢"
        with st.expander(f"{color_icon} 🏢 {org}  | 净额 ¥{org_net:,.2f} | 发货 ¥{org_ship:,.2f} | 退货 ¥{org_return:,.2f}"):
            
            # 按部门展开
            dept_order = org_data.groupby('dept')['net'].sum().sort_values(ascending=False).index
            for dept in dept_order:
                dept_data = org_data[org_data['dept'] == dept]
                dept_net = dept_data['net'].sum()
                dept_ship = dept_data['ship'].sum()
                dept_return = dept_data['return_amt'].sum()
                dept_return_rate = (dept_return / (dept_ship + 1e-5) * 100)
                dept_color = "🔴" if dept_net < 0 else "🟢"
                
                with st.expander(f"{dept_color} 📊 {dept}  | 净额 ¥{dept_net:,.2f} | 退货率 {dept_return_rate:.1f}%"):
                    
                    # 按平台展开
                    platform_order = dept_data.groupby('platform')['net'].sum().sort_values(ascending=False).index
                    for plat in platform_order:
                        plat_data = dept_data[dept_data['platform'] == plat]
                        plat_net = plat_data['net'].sum()
                        plat_ship = plat_data['ship'].sum()
                        plat_return = plat_data['return_amt'].sum()
                        plat_return_rate = (plat_return / (plat_ship + 1e-5) * 100)
                        
                        with st.expander(f"📱 {plat}  净额 ¥{plat_net:,.2f} | 退货率 {plat_return_rate:.1f}%"):
                            display_df = plat_data[['shop_name', 'ship', 'return_amt', 'net', '退货率显示']]
                            display_df.columns = ['店铺', '发货额', '退货额', '净销售额', '退货率']
                            display_df = display_df.sort_values('净销售额', ascending=False)
                            st.dataframe(display_df, hide_index=True, use_container_width=True)
else:
    st.warning(f"{period_label_p} 无数据，无法显示透视表。")

# ---------- 3.4 部门明细汇总表（新增） ----------
st.markdown("---")
st.markdown("#### 📋 部门明细汇总表")

# 选择周期
time_mode_detail = st.radio(
    "选择查看周期",
    options=["近7天", "月累计"],
    index=1,
    horizontal=True,
    key="org_dept_detail_mode"
)

if time_mode_detail == "近7天":
    start_date_detail = base_date - timedelta(days=6)
    end_date_detail = base_date
    period_label_detail = "近7天"
else:
    start_date_detail = base_date.replace(day=1)
    end_date_detail = base_date
    period_label_detail = f"月累计（{base_date.strftime('%Y-%m')}）"

with st.spinner(f"加载部门明细数据（{period_label_detail}）..."):
    df_detail = fetch_complete_sales_summary(start_date_detail, end_date_detail, suffix)

if not df_detail.empty:
    # 按部门汇总
    dept_detail = df_detail.groupby(['org_name', 'dept', 'shop_name']).agg({
        'total_ship': 'sum',
        'total_return': 'sum',
        'total_net': 'sum'
    }).reset_index()
    
    # 计算退货率
    dept_detail['退货率'] = (dept_detail['total_return'] / (dept_detail['total_ship'] + 1e-5) * 100).round(2)
    dept_detail['退货率显示'] = dept_detail['退货率'].apply(lambda x: f"{x:.2f}%")
    
    # 格式化金额
    dept_detail['发货额'] = dept_detail['total_ship'].apply(lambda x: f"¥{x:,.2f}")
    dept_detail['退货额'] = dept_detail['total_return'].apply(lambda x: f"¥{x:,.2f}")
    dept_detail['净额'] = dept_detail['total_net'].apply(lambda x: f"¥{x:,.2f}")
    
    # 添加排名
    dept_detail['净额排名'] = dept_detail['total_net'].rank(ascending=False, method='min').astype(int)
    
    # 显示汇总表
    st.markdown(f"**📊 部门明细汇总表（{period_label_detail}）**")
    st.caption(f"共 {len(dept_detail)} 个店铺/部门记录，涉及 {dept_detail['org_name'].nunique()} 个组织，{dept_detail['dept'].nunique()} 个部门")
    
    # 显示表格
    display_cols = ['净额排名', 'org_name', 'dept', 'shop_name', '净额', '发货额', '退货额', '退货率显示']
    st.dataframe(
        dept_detail[display_cols].sort_values('净额排名'),
        hide_index=True,
        use_container_width=True,
        column_config={
            "净额排名": st.column_config.NumberColumn("排名", width="small"),
            "org_name": st.column_config.TextColumn("组织", width="medium"),
            "dept": st.column_config.TextColumn("部门", width="medium"),
            "shop_name": st.column_config.TextColumn("店铺", width="medium"),
            "净额": st.column_config.TextColumn("净销售额", width="medium"),
            "发货额": st.column_config.TextColumn("发货额", width="medium"),
            "退货额": st.column_config.TextColumn("退货额", width="medium"),
            "退货率显示": st.column_config.TextColumn("退货率", width="small"),
        }
    )
    
    # ========== 部门明细导出功能 ==========
    st.markdown("---")
    st.markdown("#### 📥 导出部门明细数据")
    
    # 导出选项
    col_export1, col_export2, col_export3 = st.columns(3)
    
    with col_export1:
        export_format = st.selectbox(
            "选择导出格式",
            options=["Excel (.xlsx)", "CSV (.csv)"],
            key="export_format_select"
        )
    
    with col_export2:
        # 选择要导出的列
        export_cols = st.multiselect(
            "选择要导出的列",
            options=['org_name', 'dept', 'shop_name', 'total_ship', 'total_return', 'total_net', '退货率'],
            default=['org_name', 'dept', 'shop_name', 'total_ship', 'total_return', 'total_net', '退货率'],
            key="export_cols_select"
        )
    
    with col_export3:
        # 选择是否包含汇总行
        include_summary = st.checkbox("包含汇总行", value=True, key="export_include_summary")
    
    # 准备导出数据
    def prepare_export_data():
        export_df = dept_detail.copy()
        
        # 只选择用户指定的列
        export_cols_mapping = {
            'org_name': '组织',
            'dept': '部门',
            'shop_name': '店铺',
            'total_ship': '发货额',
            'total_return': '退货额',
            'total_net': '净销售额',
            '退货率': '退货率(%)'
        }
        
        selected_export_cols = [col for col in export_cols if col in export_cols_mapping]
        if not selected_export_cols:
            selected_export_cols = list(export_cols_mapping.keys())
        
        export_df = export_df[selected_export_cols].copy()
        export_df.columns = [export_cols_mapping[col] for col in selected_export_cols]
        
        # 按净销售额排序
        if '净销售额' in export_df.columns:
            export_df = export_df.sort_values('净销售额', ascending=False)
        
        # 添加汇总行
        if include_summary:
            summary_row = {}
            for col in export_df.columns:
                if col in ['发货额', '退货额', '净销售额']:
                    summary_row[col] = export_df[col].sum()
                elif col == '退货率(%)':
                    total_ship = export_df['发货额'].sum() if '发货额' in export_df.columns else 0
                    total_return = export_df['退货额'].sum() if '退货额' in export_df.columns else 0
                    summary_row[col] = (total_return / (total_ship + 1e-5) * 100).round(2)
                else:
                    summary_row[col] = '合计'
            export_df = pd.concat([export_df, pd.DataFrame([summary_row])], ignore_index=True)
        
        return export_df
    
    # 导出按钮
    if st.button("📥 下载部门明细数据", key="export_dept_detail"):
        try:
            export_df = prepare_export_data()
            
            if export_format == "Excel (.xlsx)":
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    export_df.to_excel(writer, sheet_name='部门明细', index=False)
                output.seek(0)
                
                st.download_button(
                    label="✅ 点击下载 Excel 文件",
                    data=output,
                    file_name=f"部门明细_{period_label_detail}_{base_date.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_excel_btn"
                )
            else:
                # CSV 导出
                csv_data = export_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="✅ 点击下载 CSV 文件",
                    data=csv_data,
                    file_name=f"部门明细_{period_label_detail}_{base_date.strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    key="download_csv_btn"
                )
            st.success("✅ 数据准备完成，请点击下载按钮获取文件")
        except Exception as e:
            st.error(f"导出失败：{e}")
    
    # 预览导出数据
    with st.expander("👁️ 预览导出数据"):
        preview_df = prepare_export_data()
        st.dataframe(preview_df, hide_index=True, use_container_width=True)
        
        # 显示统计信息
        st.caption(f"📊 共 {len(preview_df)} 行数据（包含汇总行）")
    
else:
    st.warning(f"{period_label_detail} 无数据，无法显示部门明细。")

# ---------- 3.5 异常预警 ----------
st.markdown("---")
st.markdown("#### ⚠️ 异常决策预警")

# 使用月累计数据或近7天数据
if not df_period_main.empty:
    alert_df = df_period_main.groupby(['org_name', 'dept', 'shop_name']).agg(
        ship=('total_ship', 'sum'),
        return_amt=('total_return', 'sum'),
        net=('total_net', 'sum')
    ).reset_index()
    alert_df['退货率'] = (alert_df['return_amt'] / (alert_df['ship'] + 1e-5) * 100)
    
    # 净额为负的店铺
    alert_negative = alert_df[alert_df['net'] < 0]
    # 退货率>65%的店铺
    alert_high_return = alert_df[alert_df['退货率'] > 65]
    # 退货率>80%的严重异常
    alert_critical_return = alert_df[alert_df['退货率'] > 80]
    
    # 显示严重异常
    if not alert_critical_return.empty:
        st.error(f"🚨🚨 严重异常：{len(alert_critical_return)} 个店铺退货率超过80%：")
        for _, row in alert_critical_return.iterrows():
            st.error(f"  • {row['org_name']} → {row['dept']} → {row['shop_name']}，退货率 {row['退货率']:.1f}%，净额 ¥{row['net']:,.2f}")
    
    # 显示净额为负
    if not alert_negative.empty:
        st.error(f"🚨 净销售额为负：{len(alert_negative)} 个店铺：")
        for _, row in alert_negative.iterrows():
            st.error(f"  • {row['org_name']} → {row['dept']} → {row['shop_name']}，净额 ¥{row['net']:,.2f}")
    
    # 显示退货率偏高
    if not alert_high_return.empty:
        st.warning(f"⚠️ 退货率异常偏高（>65%）：{len(alert_high_return)} 个店铺：")
        for _, row in alert_high_return.iterrows():
            st.warning(f"  • {row['org_name']} → {row['dept']} → {row['shop_name']}，退货率 {row['退货率']:.1f}%")
    
    if alert_negative.empty and alert_high_return.empty and alert_critical_return.empty:
        st.success("🎉 所有部门/店铺运营正常，无重大异常。")
    
    # 统计信息
    total_orgs = alert_df['org_name'].nunique()
    total_depts = alert_df['dept'].nunique()
    total_shops = alert_df['shop_name'].nunique()
    st.caption(f"📊 共分析 {total_orgs} 个组织，{total_depts} 个部门，{total_shops} 个店铺")
    
else:
    st.info("当前周期无数据，无法预警。")

# ======================== 4. AI 智能总结 ========================
st.markdown("---")
st.markdown("#### 🤖 AI 智能总结")

model_options = {
    "DeepSeek-V3": "deepseek-ai/DeepSeek-V3",
    "DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
    "Qwen2.5-72B": "Qwen/Qwen2.5-72B-Instruct",
    "Qwen2.5-7B": "Qwen/Qwen2.5-7B-Instruct",
    "GLM-4-9B": "glm-4-9b-chat"
}
selected_model_name = st.selectbox(
    "选择 AI 模型",
    options=list(model_options.keys()),
    index=1,
    key="org_ai_model_select"
)
selected_model = model_options[selected_model_name]

if st.button("🚀 生成智能总结", key="org_generate_ai_summary"):
    # 准备数据
    total_net = mtd_net if not df_mtd.empty else 0
    return_rate = mtd_return_rate if not df_mtd.empty else 0
    
    if not df_7d.empty and not df_prev.empty:
        total_7d = df_7d['total_net'].sum()
        total_prev = df_prev['total_net'].sum() if not df_prev.empty else 0
        change_7d = ((total_7d - total_prev) / (total_prev + 1e-5) * 100) if total_prev != 0 else 0
        net_7d = total_7d
        net_prev = total_prev
    else:
        net_7d = 0
        net_prev = 0
        change_7d = 0
    
    # 组织排行
    if not df_period_main.empty:
        org_net = df_period_main.groupby('org_name')['total_net'].sum().sort_values(ascending=False).head(5)
        org_text = "\n".join([f"{i+1}. {org}: ¥{amt:,.0f}" for i, (org, amt) in enumerate(org_net.items())]) if not org_net.empty else "暂无"
        # 负值组织
        org_negative = df_period_main.groupby('org_name')['total_net'].sum()
        org_negative = org_negative[org_negative < 0]
        neg_org_text = "\n".join([f"{org}: ¥{amt:,.0f}" for org, amt in org_negative.items()]) if not org_negative.empty else "无"
    else:
        org_text = "暂无"
        neg_org_text = "无"
    
    # 部门退货率排行
    if not df_period_main.empty:
        dept_return_ai = df_period_main.groupby('dept').agg(
            ship=('total_ship', 'sum'), 
            return_amt=('total_return', 'sum')
        ).reset_index()
        dept_return_ai['退货率'] = (dept_return_ai['return_amt'] / (dept_return_ai['ship'] + 1e-5) * 100)
        dept_return_ai = dept_return_ai.sort_values('退货率', ascending=False).head(5)
        dept_text = "\n".join([f"{row['dept']}: {row['退货率']:.1f}%" for _, row in dept_return_ai.iterrows()]) if not dept_return_ai.empty else "暂无"
    else:
        dept_text = "暂无"
    
    # 统计信息
    total_orgs = df_period_main['org_name'].nunique() if not df_period_main.empty else 0
    total_depts = df_period_main['dept'].nunique() if not df_period_main.empty else 0
    total_shops = df_period_main['shop_name'].nunique() if not df_period_main.empty else 0

    context = f"""
    分析期间（月累计）：{month_start} 至 {latest_date}
    总净销售额：¥{total_net:,.2f}
    综合退货率：{return_rate:.2f}%
    近7天净销售额：¥{net_7d:,.2f}（前7天：¥{net_prev:,.2f}，变化 {change_7d:+.1f}%）
    涉及组织数：{total_orgs} 个，部门数：{total_depts} 个，店铺数：{total_shops} 个
    
    净销售额 TOP5 组织：
    {org_text}
    
    净销售额为负的组织：
    {neg_org_text}
    
    退货率 TOP5 部门：
    {dept_text}
    """

    prompt = """
    你是一位资深的电商运营总监。请根据以上数据，用一段专业、简洁的中文总结当前组织与部门的经营状况。
    要求：
    1. 突出表现最好的组织（阿米巴）和最需要关注的部门。
    2. 结合近7天趋势，给出短期策略建议。
    3. 若发现异常（如退货率极高、净额下滑、净额为负的组织），明确指出来并给出改进建议。
    4. 分析要具体，不要泛泛而谈。
    """

    with st.spinner("🤖 AI 正在分析，请稍候..."):
        ai_summary = get_ai_summary(prompt, context, selected_model)

    st.session_state.org_ai_summary = ai_summary
    st.rerun()

if st.session_state.get("org_ai_summary"):
    st.markdown(f"""
    <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);border-radius:12px;padding:16px 20px;margin-top:10px;">
        <div style="color:#1e293b;font-size:14px;line-height:1.7;">{st.session_state.org_ai_summary}</div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("点击上方按钮生成 AI 智能总结。")

# ---------- 底部信息 ----------
st.markdown("---")
st.caption(f"📌 数据最后更新：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')} | 数据源：全部数据")
