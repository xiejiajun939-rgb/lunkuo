# pages/5_org_dept.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import plotly.express as px
import plotly.graph_objects as go

from core.db import init_supabase, get_table_name, fetch_sales_summary, load_org_targets
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
        table_name = get_table_name("product_sales", suffix)
        resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=False).limit(1).execute()
        if resp.data:
            min_dates.append(pd.to_datetime(resp.data[0]["sale_date"]).date())
        resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=True).limit(1).execute()
        if resp.data:
            max_dates.append(pd.to_datetime(resp.data[0]["sale_date"]).date())
        if suffix == "_all":
            offline_resp = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=False).limit(1).execute()
            if offline_resp.data:
                min_dates.append(pd.to_datetime(offline_resp.data[0]["sale_date"]).date())
            offline_resp = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=True).limit(1).execute()
            if offline_resp.data:
                max_dates.append(pd.to_datetime(offline_resp.data[0]["sale_date"]).date())
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
    df_today = fetch_sales_summary(latest_date, latest_date, suffix)
    df_mtd = fetch_sales_summary(month_start, latest_date, suffix)

if df_today.empty:
    st.warning(f"所选日期 {latest_date} 无销售数据，以下显示月累计数据。")
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
    df_7d = fetch_sales_summary(period_start, base_date, suffix)
    df_prev = fetch_sales_summary(prev_period_start, prev_period_end, suffix)

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
    df_period_main = fetch_sales_summary(start_date, end_date, suffix)

if not df_period_main.empty:
    col_org, col_dept = st.columns(2)
    with col_org:
        org_agg = df_period_main.groupby('org_name')['total_net'].sum().reset_index()
        positive_org = org_agg[org_agg['total_net'] > 0].copy()
        if not positive_org.empty:
            fig_org = px.pie(positive_org, names='org_name', values='total_net',
                             title=f'各阿米巴净销售额占比（{period_label}）',
                             hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_org.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_org, use_container_width=True)
        else:
            st.info("无盈利阿米巴")
    with col_dept:
        dept_agg = df_period_main.groupby('dept')['total_net'].sum().reset_index()
        dept_agg = dept_agg[dept_agg['total_net'] != 0].sort_values('total_net', ascending=False)
        if not dept_agg.empty:
            top10 = dept_agg.head(10)
            fig_dept = px.bar(top10, x='total_net', y='dept', orientation='h',
                              title=f'部门净销售额排行（TOP10，{period_label}）',
                              labels={'total_net': '净销售额', 'dept': '渠道'},
                              color='total_net', color_continuous_scale='Blues')
            fig_dept.update_layout(yaxis={'categoryorder': 'total ascending'})
            st.plotly_chart(fig_dept, use_container_width=True)
        else:
            st.info("无渠道数据")
else:
    st.warning(f"{period_label} 无数据，无法显示阿米巴/渠道分布。")

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
    df_return = fetch_sales_summary(start_date_r, end_date_r, suffix)

if not df_return.empty:
    dept_return = df_return.groupby('dept').agg(
        ship=('total_ship', 'sum'),
        return_amt=('total_return', 'sum')
    ).reset_index()
    dept_return['退货率'] = (dept_return['return_amt'] / (dept_return['ship'] + 1e-5) * 100).round(2)
    dept_return = dept_return[dept_return['ship'] > 0]
    if not dept_return.empty:
        top_return = dept_return.sort_values('退货率', ascending=False).head(10)
        fig_return = px.bar(top_return, x='dept', y='退货率',
                            title=f'退货率 TOP10 部门（{period_label_r}）',
                            labels={'dept': '部门', '退货率': '退货率 (%)'},
                            color=top_return['退货率'], color_continuous_scale='RdYlGn_r')
        fig_return.add_hline(y=50, line_dash="dash", line_color="red", annotation_text="警戒线 50%")
        fig_return.add_hline(y=30, line_dash="dash", line_color="orange", annotation_text="注意线 30%")
        st.plotly_chart(fig_return, use_container_width=True)
    else:
        st.info("无有效渠道数据")
else:
    st.warning(f"{period_label_r} 无数据，无法显示退货率。")

# ---------- 3.3 多维透视 ----------
st.markdown("#### 🔍 多维透视（渠道 → 平台 → 店铺）")
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
    df_pivot = fetch_sales_summary(start_date_p, end_date_p, suffix)

if not df_pivot.empty:
    df_pivot['platform'] = df_pivot['shop_name'].apply(
        lambda x: '天猫' if x.startswith('天猫') else '小红书' if x.startswith('小红书') else '抖音' if x.startswith('抖音') else '视频号' if x.startswith('视频号') else '其他'
    )
    grouped = df_pivot.groupby(['org_name', 'platform', 'shop_name']).agg(
        ship=('total_ship', 'sum'),
        return_amt=('total_return', 'sum'),
        net=('total_net', 'sum')
    ).reset_index()
    grouped['退货率'] = (grouped['return_amt'] / (grouped['ship'] + 1e-5) * 100).round(2).map(lambda x: f"{x:.2f}%")

    org_order = grouped.groupby('org_name')['net'].sum().sort_values(ascending=False).index
    for org in org_order:
        org_data = grouped[grouped['org_name'] == org]
        org_net = org_data['net'].sum()
        org_ship = org_data['ship'].sum()
        org_return = org_data['return_amt'].sum()
        with st.expander(f"🏢 {org}  | 净额 ¥{org_net:,.2f} | 发货 ¥{org_ship:,.2f} | 退货 ¥{org_return:,.2f}"):
            platform_order = org_data.groupby('platform')['net'].sum().sort_values(ascending=False).index
            for plat in platform_order:
                plat_data = org_data[org_data['platform'] == plat]
                plat_net = plat_data['net'].sum()
                plat_ship = plat_data['ship'].sum()
                plat_return = plat_data['return_amt'].sum()
                with st.expander(f"📱 {plat}  净额 ¥{plat_net:,.2f}（发货 ¥{plat_ship:,.2f} / 退货 ¥{plat_return:,.2f}）"):
                    display_df = plat_data[['shop_name', 'ship', 'return_amt', 'net', '退货率']]
                    display_df.columns = ['店铺', '发货额', '退货额', '净销售额', '退货率']
                    display_df = display_df.sort_values('净销售额', ascending=False)
                    st.dataframe(display_df, hide_index=True, use_container_width=True)
else:
    st.warning(f"{period_label_p} 无数据，无法显示透视表。")

# ---------- 3.4 异常预警 ----------
st.markdown("---")
st.markdown("#### ⚠️ 异常决策预警")
if not df_period_main.empty:
    alert_df = df_period_main.groupby(['org_name', 'dept', 'shop_name']).agg(
        ship=('total_ship', 'sum'),
        return_amt=('total_return', 'sum'),
        net=('total_net', 'sum')
    ).reset_index()
    alert_df['退货率'] = (alert_df['return_amt'] / (alert_df['ship'] + 1e-5) * 100)
    alert_negative = alert_df[alert_df['net'] < 0]
    alert_high_return = alert_df[alert_df['退货率'] > 65]

    if not alert_negative.empty:
        for _, row in alert_negative.iterrows():
            st.error(f"🚨 净销售额为负：{row['org_name']} -> {row['dept']} -> {row['shop_name']}，净额 ¥{row['net']:,.2f}")
    if not alert_high_return.empty:
        for _, row in alert_high_return.iterrows():
            st.warning(f"⚠️ 退货率异常偏高（>{65}%）：{row['org_name']} -> {row['dept']} -> {row['shop_name']}，退货率 {row['退货率']:.1f}%")
    if alert_negative.empty and alert_high_return.empty:
        st.success("🎉 所有部门/店铺运营正常，无重大异常。")
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

    if not df_period_main.empty:
        org_net = df_period_main.groupby('org_name')['total_net'].sum().sort_values(ascending=False).head(3)
        org_text = "\n".join([f"{i+1}. {org}: ¥{amt:,.0f}" for i, (org, amt) in enumerate(org_net.items())]) if not org_net.empty else "暂无"
    else:
        org_text = "暂无"

    if not df_period_main.empty:
        dept_return_ai = df_period_main.groupby('dept').agg(ship=('total_ship', 'sum'), return_amt=('total_return', 'sum')).reset_index()
        dept_return_ai['退货率'] = (dept_return_ai['return_amt'] / (dept_return_ai['ship'] + 1e-5) * 100)
        dept_return_ai = dept_return_ai.sort_values('退货率', ascending=False).head(3)
        dept_text = "\n".join([f"{row['dept']}: {row['退货率']:.1f}%" for _, row in dept_return_ai.iterrows()]) if not dept_return_ai.empty else "暂无"
    else:
        dept_text = "暂无"

    context = f"""
    分析期间（月累计）：{month_start} 至 {latest_date}
    总净销售额：¥{total_net:,.2f}
    综合退货率：{return_rate:.2f}%
    近7天净销售额：¥{net_7d:,.2f}（前7天：¥{net_prev:,.2f}，变化 {change_7d:+.1f}%）
    净销售额 TOP3 阿米巴：
    {org_text}
    退货率 TOP3 渠道：
    {dept_text}
    """

    prompt = """
    你是一位资深的电商运营总监。请根据以上数据，用一段专业、简洁的中文总结当前组织与部门的经营状况。
    要求：
    1. 突出表现最好的阿米巴和最需要关注的渠道。
    2. 结合近7天趋势，给出短期策略建议。
    3. 若发现异常（如退货率极高、净额下滑），明确指出来。
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
