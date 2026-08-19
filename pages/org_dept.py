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

# ---------- 新增：从多个数据源获取完整数据 ----------
@st.cache_data(ttl=300)
def fetch_complete_sales_summary(start_date, end_date, suffix="_all"):
    """
    从 product_sales 和 offline_sales 两个表获取完整数据，
    并补充组织名称和部门信息
    """
    supabase = init_supabase()
    if supabase is None:
        return pd.DataFrame()
    
    all_records = []
    
    try:
        # 1. 从 product_sales 获取数据
        table_name = get_table_name("product_sales", suffix)
        resp = supabase.table(table_name)\
            .select("sale_date, shop_name, net_amount, ship_amount, return_amount, remark")\
            .gte("sale_date", start_date.strftime("%Y-%m-%d"))\
            .lte("sale_date", end_date.strftime("%Y-%m-%d"))\
            .execute()
        
        if resp.data:
            for row in resp.data:
                # 提取组织名称（从 remark 中提取）
                remark = row.get("remark", "")
                # 尝试从 remark 中提取组织信息
                org_name = extract_org_from_remark(remark)
                # 如果提取不到，使用 shop_name 作为备选
                if not org_name:
                    org_name = row.get("shop_name", "未知组织")
                
                all_records.append({
                    "sale_date": row["sale_date"],
                    "shop_name": row.get("shop_name", "未知店铺"),
                    "org_name": org_name,
                    "dept": row.get("shop_name", "未知渠道"),  # 默认使用 shop_name 作为渠道
                    "net_amount": float(row.get("net_amount", 0)),
                    "ship_amount": float(row.get("ship_amount", 0)),
                    "return_amount": float(row.get("return_amount", 0)),
                    "source": "product_sales"
                })
        
        # 2. 从 offline_sales 获取数据（仅 _all 模式）
        if suffix == "_all":
            offline_resp = supabase.table("offline_sales_all")\
                .select("sale_date, shop_name, net_amount, ship_amount, return_amount, remark")\
                .gte("sale_date", start_date.strftime("%Y-%m-%d"))\
                .lte("sale_date", end_date.strftime("%Y-%m-%d"))\
                .execute()
            
            if offline_resp.data:
                for row in offline_resp.data:
                    shop_name = row.get("shop_name", "未知店铺")
                    # 从 shop_name 或 remark 提取组织
                    org_name = extract_org_from_remark(row.get("remark", "")) or shop_name
                    
                    all_records.append({
                        "sale_date": row["sale_date"],
                        "shop_name": shop_name,
                        "org_name": org_name,
                        "dept": shop_name,  # 线下默认使用店铺名作为渠道
                        "net_amount": float(row.get("net_amount", 0)),
                        "ship_amount": float(row.get("ship_amount", 0)),
                        "return_amount": float(row.get("return_amount", 0)),
                        "source": "offline_sales"
                    })
        
        if not all_records:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_records)
        df["sale_date"] = pd.to_datetime(df["sale_date"])
        
        # 按日期、店铺、组织聚合
        df_agg = df.groupby(["sale_date", "shop_name", "org_name", "dept"], as_index=False).agg({
            "net_amount": "sum",
            "ship_amount": "sum",
            "return_amount": "sum"
        })
        
        # 重命名列为标准格式
        df_agg.rename(columns={
            "net_amount": "total_net",
            "ship_amount": "total_ship",
            "return_amount": "total_return"
        }, inplace=True)
        
        return df_agg
        
    except Exception as e:
        st.error(f"获取数据失败：{e}")
        return pd.DataFrame()

def extract_org_from_remark(remark):
    """从备注中提取组织名称"""
    if not remark or not isinstance(remark, str):
        return None
    
    # 常见的组织标识模式
    import re
    patterns = [
        r'组织[：:]\s*([^\s_]+)',
        r'部门[：:]\s*([^\s_]+)',
        r'阿米巴[：:]\s*([^\s_]+)',
        r'([^_\s]+)组',
        r'([^_\s]+)部',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, remark)
        if match:
            return match.group(1).strip()
    
    # 如果都没有匹配，尝试从 _ 分割中提取
    parts = remark.split('_')
    if len(parts) >= 2:
        # 通常第一个部分可能是组织标识
        return parts[0].strip()
    
    return None

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
    # 使用新的完整数据获取函数
    df_today = fetch_complete_sales_summary(latest_date, latest_date, suffix)
    df_mtd = fetch_complete_sales_summary(month_start, latest_date, suffix)

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
    # 显示数据概览，帮助识别是否有数据遗漏
    with st.expander("📋 数据概览（检查是否有组织被遗漏）"):
        org_list = df_period_main['org_name'].unique().tolist()
        st.write(f"共识别到 **{len(org_list)}** 个组织：{', '.join(org_list)}")
        
        # 显示各组织的汇总数据
        org_summary = df_period_main.groupby('org_name').agg({
            'total_net': 'sum',
            'total_ship': 'sum',
            'total_return': 'sum'
        }).reset_index()
        org_summary['净额'] = org_summary['total_net'].apply(lambda x: f"¥{x:,.2f}")
        st.dataframe(org_summary[['org_name', '净额', 'total_ship', 'total_return']], 
                     hide_index=True, use_container_width=True)
    
    col_org, col_dept = st.columns(2)
    with col_org:
        # 修改：显示所有组织（包括负值），但用不同颜色区分
        org_agg = df_period_main.groupby('org_name')['total_net'].sum().reset_index()
        
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
    df_return = fetch_complete_sales_summary(start_date_r, end_date_r, suffix)

if not df_return.empty:
    dept_return = df_return.groupby('dept').agg(
        ship=('total_ship', 'sum'),
        return_amt=('total_return', 'sum'),
        net=('total_net', 'sum')
    ).reset_index()
    
    # 修改：不过滤 ship > 0，保留所有部门以便完整显示
    dept_return['退货率'] = (dept_return['return_amt'] / (dept_return['ship'] + 1e-5) * 100).round(2)
    dept_return = dept_return.sort_values('退货率', ascending=False)
    
    if not dept_return.empty:
        # 显示所有部门，不仅仅是TOP10
        top_return = dept_return.head(10)
        fig_return = px.bar(top_return, x='dept', y='退货率',
                            title=f'退货率 TOP10 部门（{period_label_r}）',
                            labels={'dept': '部门', '退货率': '退货率 (%)'},
                            color=top_return['退货率'], color_continuous_scale='RdYlGn_r')
        fig_return.add_hline(y=50, line_dash="dash", line_color="red", annotation_text="警戒线 50%")
        fig_return.add_hline(y=30, line_dash="dash", line_color="orange", annotation_text="注意线 30%")
        st.plotly_chart(fig_return, use_container_width=True)
        
        # 显示零发货但有退货的异常部门
        zero_ship_returns = dept_return[(dept_return['ship'] == 0) & (dept_return['return_amt'] > 0)]
        if not zero_ship_returns.empty:
            st.warning(f"⚠️ 以下部门有退货但无发货记录：{', '.join(zero_ship_returns['dept'].tolist())}")
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
    df_pivot = fetch_complete_sales_summary(start_date_p, end_date_p, suffix)

if not df_pivot.empty:
    # 平台分类（增加更多平台识别）
    def classify_platform(shop_name):
        if not shop_name:
            return '其他'
        shop_name = str(shop_name)
        if shop_name.startswith('天猫'):
            return '天猫'
        elif shop_name.startswith('小红书'):
            return '小红书'
        elif shop_name.startswith('抖音'):
            return '抖音'
        elif shop_name.startswith('视频号'):
            return '视频号'
        elif shop_name.startswith('京东'):
            return '京东'
        elif shop_name.startswith('拼多多'):
            return '拼多多'
        elif shop_name.startswith('淘宝'):
            return '淘宝'
        elif '线下' in shop_name or '门店' in shop_name:
            return '线下门店'
        else:
            return '其他'
    
    df_pivot['platform'] = df_pivot['shop_name'].apply(classify_platform)
    
    grouped = df_pivot.groupby(['org_name', 'platform', 'shop_name', 'dept']).agg(
        ship=('total_ship', 'sum'),
        return_amt=('total_return', 'sum'),
        net=('total_net', 'sum')
    ).reset_index()
    grouped['退货率'] = (grouped['return_amt'] / (grouped['ship'] + 1e-5) * 100).round(2).map(lambda x: f"{x:.2f}%")

    # 按组织净额排序
    org_order = grouped.groupby('org_name')['net'].sum().sort_values(ascending=False).index
    
    # 显示所有组织
    for org in org_order:
        org_data = grouped[grouped['org_name'] == org]
        org_net = org_data['net'].sum()
        org_ship = org_data['ship'].sum()
        org_return = org_data['return_amt'].sum()
        
        # 颜色标识：负值用红色
        color = "#ef4444" if org_net < 0 else "#22c55e"
        with st.expander(f"🏢 {org}  | 净额 ¥{org_net:,.2f} | 发货 ¥{org_ship:,.2f} | 退货 ¥{org_return:,.2f}"):
            platform_order = org_data.groupby('platform')['net'].sum().sort_values(ascending=False).index
            for plat in platform_order:
                plat_data = org_data[org_data['platform'] == plat]
                plat_net = plat_data['net'].sum()
                plat_ship = plat_data['ship'].sum()
                plat_return = plat_data['return_amt'].sum()
                with st.expander(f"📱 {plat}  净额 ¥{plat_net:,.2f}（发货 ¥{plat_ship:,.2f} / 退货 ¥{plat_return:,.2f}）"):
                    display_df = plat_data[['dept', 'shop_name', 'ship', 'return_amt', 'net', '退货率']]
                    display_df.columns = ['渠道', '店铺', '发货额', '退货额', '净销售额', '退货率']
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
        st.error(f"🚨 发现 {len(alert_negative)} 个净销售额为负的组织/店铺：")
        for _, row in alert_negative.iterrows():
            st.error(f"  • {row['org_name']} -> {row['dept']} -> {row['shop_name']}，净额 ¥{row['net']:,.2f}")
    if not alert_high_return.empty:
        st.warning(f"⚠️ 发现 {len(alert_high_return)} 个退货率异常偏高（>{65}%）的组织/店铺：")
        for _, row in alert_high_return.iterrows():
            st.warning(f"  • {row['org_name']} -> {row['dept']} -> {row['shop_name']}，退货率 {row['退货率']:.1f}%")
    if alert_negative.empty and alert_high_return.empty:
        st.success("🎉 所有部门/店铺运营正常，无重大异常。")
        
    # 新增：显示被排除的组织
    total_orgs = alert_df['org_name'].nunique()
    st.caption(f"📊 共分析 {total_orgs} 个组织，{alert_df['shop_name'].nunique()} 个店铺")
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
        org_net = df_period_main.groupby('org_name')['total_net'].sum().sort_values(ascending=False).head(5)
        org_text = "\n".join([f"{i+1}. {org}: ¥{amt:,.0f}" for i, (org, amt) in enumerate(org_net.items())]) if not org_net.empty else "暂无"
    else:
        org_text = "暂无"

    if not df_period_main.empty:
        dept_return_ai = df_period_main.groupby('dept').agg(ship=('total_ship', 'sum'), return_amt=('total_return', 'sum')).reset_index()
        dept_return_ai['退货率'] = (dept_return_ai['return_amt'] / (dept_return_ai['ship'] + 1e-5) * 100)
        dept_return_ai = dept_return_ai.sort_values('退货率', ascending=False).head(5)
        dept_text = "\n".join([f"{row['dept']}: {row['退货率']:.1f}%" for _, row in dept_return_ai.iterrows()]) if not dept_return_ai.empty else "暂无"
    else:
        dept_text = "暂无"
    
    # 增加组织统计
    total_orgs = df_period_main['org_name'].nunique() if not df_period_main.empty else 0
    total_shops = df_period_main['shop_name'].nunique() if not df_period_main.empty else 0

    context = f"""
    分析期间（月累计）：{month_start} 至 {latest_date}
    总净销售额：¥{total_net:,.2f}
    综合退货率：{return_rate:.2f}%
    近7天净销售额：¥{net_7d:,.2f}（前7天：¥{net_prev:,.2f}，变化 {change_7d:+.1f}%）
    涉及组织数：{total_orgs} 个，店铺数：{total_shops} 个
    净销售额 TOP5 阿米巴：
    {org_text}
    退货率 TOP5 渠道：
    {dept_text}
    """

    prompt = """
    你是一位资深的电商运营总监。请根据以上数据，用一段专业、简洁的中文总结当前组织与部门的经营状况。
    要求：
    1. 突出表现最好的阿米巴和最需要关注的渠道。
    2. 结合近7天趋势，给出短期策略建议。
    3. 若发现异常（如退货率极高、净额下滑），明确指出来。
    4. 如果某些组织或部门出现负值，要特别提醒注意。
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
