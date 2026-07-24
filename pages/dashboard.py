# pages/1_dashboard.py
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from core.db import load_product_sales, load_org_targets, fetch_sales_summary
from core.utils import date_quick_buttons
from core.ai import get_ai_summary

st.set_page_config(page_title="经营驾驶舱", layout="wide")

# 确保全局变量存在
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""
if "target_dict" not in st.session_state:
    st.session_state.target_dict = {}

# ---------- 自定义样式（简化，可复用主文件样式） ----------
st.markdown("""
<style>
    .glass-card { background: rgba(255,255,255,0.9); border-radius: 16px; padding: 22px 24px; border: 1px solid rgba(0,0,0,0.06); backdrop-filter: blur(10px); box-shadow: 0 8px 32px rgba(0,0,0,0.08); margin-bottom: 8px; }
    .kpi-number { font-size: 38px; font-weight: 700; background: linear-gradient(135deg, #0f172a 60%, #475569); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .kpi-label { color: #475569; font-size: 13px; font-weight: 500; text-transform: uppercase; }
    .change-up { color: #16a34a; font-weight: 600; }
    .change-down { color: #dc2626; font-weight: 600; }
    .change-neutral { color: #64748b; }
    .progress-track { width: 100%; height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; margin: 8px 0 4px 0; }
    .progress-fill { height: 100%; border-radius: 3px; transition: width 0.8s ease; }
    .rank-item { display: flex; align-items: center; padding: 6px 0; border-bottom: 1px solid rgba(0,0,0,0.05); }
    .rank-emoji { font-size: 22px; width: 36px; }
    .rank-name { flex: 1; color: #1e293b; font-size: 14px; }
    .rank-value { color: #16a34a; font-weight: 600; font-size: 14px; width: 80px; text-align: right; }
    .rank-bar-bg { width: 100px; height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; }
    .rank-bar-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, #22c55e, #14b8a6); }
    .alert-item { padding: 10px 14px; border-radius: 8px; margin-bottom: 6px; display: flex; align-items: center; gap: 10px; background: rgba(0,0,0,0.02); border-left: 3px solid; }
    .section-title { color: #1e293b; font-size: 16px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
    .section-title .badge { background: rgba(34, 197, 94, 0.15); color: #16a34a; font-size: 11px; padding: 2px 10px; border-radius: 12px; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

# ---------- 加载数据 ----------
with st.spinner("加载数据..."):
    prod_df = load_product_sales(st.session_state.table_suffix)

if prod_df.empty:
    st.info("📌 暂无商品销售数据，请先上传订单文件。")
    st.stop()

# ---------- 部门筛选 ----------
has_dept = 'dept' in prod_df.columns and prod_df['dept'].notna().any()
if has_dept:
    depts = sorted(prod_df['dept'].dropna().unique())
    depts = ['全部'] + depts
    selected_dept = st.selectbox("🏢 选择部门", depts, key="dashboard_dept_select")
    if selected_dept != '全部':
        prod_df = prod_df[prod_df['dept'] == selected_dept]
        if prod_df.empty:
            st.warning(f"当前部门「{selected_dept}」无销售数据，请切换其他部门。")
            st.stop()
else:
    selected_dept = '全部'
    st.caption("当前数据源无部门维度，显示全部数据。")

# ---------- 按日期汇总净销售额 ----------
daily_sales = prod_df.groupby(prod_df["sale_date"].dt.date)["net_amount"].sum().reset_index()
daily_sales.columns = ["日期", "amount"]
daily_sales = daily_sales.sort_values("日期")

if daily_sales.empty:
    st.info("📌 当前筛选条件无销售数据。")
    st.stop()

latest_date = daily_sales["日期"].max()
st.caption(f"📅 数据更新至：{latest_date.strftime('%Y年%m月%d日')}" + (f" | 部门：{selected_dept}" if selected_dept != '全部' else ""))

# ---------- 计算指标 ----------
prev_date = latest_date - timedelta(days=1)
mask_latest = daily_sales["日期"] == latest_date
latest_sales = daily_sales.loc[mask_latest, "amount"].sum() if not daily_sales.loc[mask_latest].empty else 0
mask_prev = daily_sales["日期"] == prev_date
prev_sales = daily_sales.loc[mask_prev, "amount"].sum() if not daily_sales.loc[mask_prev].empty else 0
change = ((latest_sales - prev_sales) / prev_sales * 100) if prev_sales != 0 else 0

month_start = latest_date.replace(day=1)
month_mask = daily_sales["日期"] >= month_start
month_sales = daily_sales.loc[month_mask, "amount"].sum()

target_dict = st.session_state.target_dict
if target_dict and has_dept and selected_dept != '全部':
    dept_shops = prod_df['shop_name'].unique()
    dept_target = sum([target_dict.get(shop, 0) for shop in dept_shops])
else:
    dept_target = sum(target_dict.values())
target_rate = (month_sales / dept_target * 100) if dept_target > 0 else 0

latest_prod = prod_df[prod_df["sale_date"].dt.date == latest_date]
ship_latest = latest_prod["ship_amount"].sum()
return_latest = latest_prod["return_amount"].sum()
return_rate = (return_latest / ship_latest * 100) if ship_latest > 0 else 0

health_score = 70
if target_rate > 80:
    health_score += 15
elif target_rate > 50:
    health_score += 5
if return_rate < 5:
    health_score += 10
elif return_rate < 10:
    health_score += 5
if latest_sales > prev_sales:
    health_score += 5
health_score = min(100, health_score)

# ---------- KPI 卡片 ----------
col1, col2, col3, col4 = st.columns(4)

with col1:
    if prev_sales < 0:
        change_text = f"▲ 由负转正 (+{latest_sales - prev_sales:,.0f})"
        change_class = "change-up"
    elif prev_sales == 0:
        change_text = "无前日数据"
        change_class = "change-neutral"
    else:
        change_text = f"{'▲' if change >= 0 else '▼'} {abs(change):.1f}%" if change != 0 else "持平"
        change_class = "change-up" if change >= 0 else "change-down"
    st.markdown(f"""
    <div class="glass-card">
        <div class="kpi-label">昨日销售</div>
        <div class="kpi-number">¥{latest_sales:,.0f}</div>
        <div style="font-size:16px; color:#475569; margin-top:4px;">月累计 ¥{month_sales:,.0f}</div>
        <div style="margin-top:6px;">
            <span class="{change_class}">{change_text}</span>
            <span style="color:#64748b;font-size:13px;margin-left:8px;">前日 ¥{prev_sales:,.0f}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    bar_color = "#4ade80" if target_rate >= 80 else "#fbbf24" if target_rate >= 50 else "#f87171"
    st.markdown(f"""
    <div class="glass-card">
        <div class="kpi-label">月目标完成率</div>
        <div style="font-size:38px;font-weight:700;color:#0f172a;letter-spacing:-0.5px;">{target_rate:.0f}%</div>
        <div class="progress-track">
            <div class="progress-fill" style="width:{min(target_rate,100)}%;background:{bar_color};"></div>
        </div>
        <div style="color:#475569;font-size:12px;">¥{month_sales:,.0f} / ¥{dept_target:,.0f}</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    return_color = "#f87171" if return_rate > 10 else "#fbbf24" if return_rate > 5 else "#4ade80"
    status_text = "正常" if return_rate < 5 else "偏高" if return_rate < 10 else "异常"
    st.markdown(f"""
    <div class="glass-card">
        <div class="kpi-label">退货率</div>
        <div style="font-size:38px;font-weight:700;color:#0f172a;letter-spacing:-0.5px;">{return_rate:.1f}%</div>
        <div style="margin-top:4px;">
            <span style="color:{return_color};font-weight:500;">● {status_text}</span>
            <span style="color:#64748b;font-size:13px;margin-left:8px;">退货 ¥{return_latest:,.0f}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    health_color = "#4ade80" if health_score >= 80 else "#fbbf24" if health_score >= 60 else "#f87171"
    health_text = "良好" if health_score >= 80 else "一般" if health_score >= 60 else "需关注"
    st.markdown(f"""
    <div class="glass-card">
        <div class="kpi-label">经营健康度</div>
        <div style="font-size:38px;font-weight:700;color:#0f172a;letter-spacing:-0.5px;">{health_score}分</div>
        <div class="progress-track">
            <div class="progress-fill" style="width:{health_score}%;background:{health_color};"></div>
        </div>
        <div style="color:{health_color};font-size:13px;font-weight:500;">● {health_text}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ---------- 异常提醒 ----------
st.markdown('<div class="section-title">⚠️ 异常提醒 <span class="badge">需关注</span></div>', unsafe_allow_html=True)

alerts = []
end_date = latest_date - timedelta(days=1)
start_date_recent = end_date - timedelta(days=6)
start_date_previous = start_date_recent - timedelta(days=7)

shop_daily = prod_df.groupby([prod_df["sale_date"].dt.date, "shop_name"])["net_amount"].sum().reset_index()
shop_daily.columns = ["日期", "shop_name", "amount"]

mask_recent = (shop_daily["日期"] >= start_date_recent) & (shop_daily["日期"] <= end_date)
mask_previous = (shop_daily["日期"] >= start_date_previous) & (shop_daily["日期"] <= start_date_recent - timedelta(days=1))

recent_data = shop_daily[mask_recent].copy()
previous_data = shop_daily[mask_previous].copy()

if not recent_data.empty and not previous_data.empty:
    recent_agg = recent_data.groupby("shop_name")["amount"].sum().reset_index().rename(columns={"amount": "近7天"})
    previous_agg = previous_data.groupby("shop_name")["amount"].sum().reset_index().rename(columns={"amount": "前7天"})
    merged = pd.merge(recent_agg, previous_agg, on="shop_name", how="inner")
    merged["下滑"] = ((merged["前7天"] - merged["近7天"]) / merged["前7天"] * 100) if not merged.empty else 0
    merged = merged[(merged["前7天"] > 0) & (merged["近7天"] < merged["前7天"])]
    merged = merged[merged["下滑"] >= 20].sort_values("下滑", ascending=False)
    for _, row in merged.head(3).iterrows():
        alerts.append(("#f87171" if row["下滑"] > 40 else "#fbbf24", f"📉 {row['shop_name']} 近7天销售下降 {row['下滑']:.0f}%"))

prod_recent = prod_df[(prod_df["sale_date"] >= pd.to_datetime(start_date_recent)) & (prod_df["sale_date"] <= pd.to_datetime(end_date))]
prod_previous = prod_df[(prod_df["sale_date"] >= pd.to_datetime(start_date_previous)) & (prod_df["sale_date"] <= pd.to_datetime(start_date_recent - timedelta(days=1)))]

if not prod_recent.empty and not prod_previous.empty:
    recent_prod = prod_recent.groupby("style_code").agg(ship=("ship_amount", "sum"), ret=("return_amount", "sum")).reset_index()
    prev_prod = prod_previous.groupby("style_code").agg(ship=("ship_amount", "sum"), ret=("return_amount", "sum")).reset_index()
    merged_prod = pd.merge(recent_prod, prev_prod, on="style_code", suffixes=("_近", "_前"))
    merged_prod["退货率近"] = (merged_prod["ret_近"] / merged_prod["ship_近"] * 100).fillna(0)
    merged_prod["退货率前"] = (merged_prod["ret_前"] / merged_prod["ship_前"] * 100).fillna(0)
    mask_valid = (merged_prod["ship_前"] > 0) & (merged_prod["ship_近"] > 0)
    merged_prod["变化"] = 0.0
    merged_prod.loc[mask_valid, "变化"] = merged_prod.loc[mask_valid, "退货率近"] - merged_prod.loc[mask_valid, "退货率前"]
    merged_prod = merged_prod[(merged_prod["变化"] >= 10) & np.isfinite(merged_prod["变化"])].sort_values("变化", ascending=False)
    for _, row in merged_prod.head(3).iterrows():
        alerts.append(("#f87171" if row["变化"] > 20 else "#fbbf24", f"📦 {row['style_code']} 退货率上升 {row['变化']:.1f} 个百分点"))

if target_dict and has_dept and selected_dept != '全部':
    dept_shop_names = prod_df['shop_name'].unique()
    for shop in dept_shop_names:
        target = target_dict.get(shop, 0)
        if target > 0:
            shop_sales = shop_daily[(shop_daily["日期"] >= month_start) & (shop_daily["shop_name"] == shop)]["amount"].sum()
            if shop_sales / target < 0.3:
                alerts.append(("#f87171", f"🎯 {shop} 月目标完成率不足30%"))
elif target_dict and (not has_dept or selected_dept == '全部'):
    for shop, target in target_dict.items():
        shop_sales = shop_daily[(shop_daily["日期"] >= month_start) & (shop_daily["shop_name"] == shop)]["amount"].sum()
        if target > 0 and shop_sales / target < 0.3:
            alerts.append(("#f87171", f"🎯 {shop} 月目标完成率不足30%"))

if alerts:
    alert_html = '<div style="background:rgba(255,255,255,0.03);border-radius:12px;padding:12px 16px;">'
    for color, msg in alerts[:5]:
        alert_html += f'<div class="alert-item" style="border-left-color:{color};">'
        alert_html += f'<span class="msg">{msg}</span></div>'
    if len(alerts) > 5:
        alert_html += f'<div style="color:#64748b;font-size:13px;padding:4px 0;">还有 {len(alerts)-5} 条异常，请查看「异常预警」</div>'
    alert_html += '</div>'
    st.markdown(alert_html, unsafe_allow_html=True)
else:
    st.success("🎉 昨日一切正常，无异常项")

st.markdown("---")

# ---------- 双列布局 ----------
col_left, col_right = st.columns([1, 1])

with col_left:
    st.markdown('<div class="section-title">🏆 店铺排行</div>', unsafe_allow_html=True)
    shop_latest = prod_df[prod_df["sale_date"].dt.date == latest_date].groupby("shop_name")["net_amount"].sum().sort_values(ascending=False).head(5)
    if not shop_latest.empty:
        max_val = shop_latest.iloc[0]
        rank_html = ""
        for i, (shop, amt) in enumerate(shop_latest.items()):
            emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i]
            pct = (amt / max_val * 100) if max_val > 0 else 0
            rank_html += f"""
            <div class="rank-item">
                <div class="rank-emoji">{emoji}</div>
                <div class="rank-name">{shop}</div>
                <div class="rank-value">¥{amt/10000:.1f}万</div>
                <div class="rank-bar-bg">
                    <div class="rank-bar-fill" style="width:{pct}%;"></div>
                </div>
            </div>
            """
        st.markdown(rank_html, unsafe_allow_html=True)
    else:
        st.info("暂无数据")

    st.markdown('<div class="section-title" style="margin-top:16px;">📊 退货排行</div>', unsafe_allow_html=True)
    prod_latest = prod_df[prod_df["sale_date"].dt.date == latest_date]
    if not prod_latest.empty:
        return_rank = prod_latest.groupby("shop_name").agg(发货=("ship_amount", "sum"), 退货=("return_amount", "sum")).reset_index()
        return_rank = return_rank[return_rank["发货"] > 0]
        return_rank["退货率"] = (return_rank["退货"] / return_rank["发货"] * 100).round(1)
        return_rank = return_rank.sort_values("退货率", ascending=False).head(3)
        if not return_rank.empty:
            for _, row in return_rank.iterrows():
                shop = row["shop_name"]
                rate = row["退货率"]
                if abs(rate) < 0.05:
                    rate = 0.0
                color = "#f87171" if rate > 10 else "#fbbf24" if rate > 5 else "#4ade80"
                st.markdown(f"""
                <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(0,0,0,0.06);">
                    <span style="color:#1e293b;">{shop}</span>
                    <span style="color:{color};font-weight:600;">{rate:.1f}%</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("暂无数据")
    else:
        st.info("暂无数据")

with col_right:
    st.markdown('<div class="section-title">📈 近7日销售趋势</div>', unsafe_allow_html=True)
    last_7 = daily_sales[daily_sales["日期"] >= (latest_date - timedelta(days=6))]
    trend = last_7.sort_values("日期").copy()
    trend["日期"] = pd.to_datetime(trend["日期"])
    if not trend.empty:
        fig = px.line(trend, x="日期", y="amount", title="", markers=True, template="plotly_white")
        fig.update_layout(height=240, margin=dict(l=0, r=0, t=10, b=0), hovermode="x unified", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        fig.update_traces(line=dict(color="#22c55e", width=2.5), marker=dict(color="#22c55e", size=6))
        st.plotly_chart(fig, use_container_width=True)
        trend["日期_str"] = trend["日期"].dt.strftime("%m-%d")
        trend["销售"] = trend["amount"].apply(lambda x: f"¥{x:,.0f}")
        st.dataframe(trend[["日期_str", "销售"]], hide_index=True, use_container_width=True)
    else:
        st.info("近7日无数据")

st.markdown("---")

# ---------- AI 智能总结 ----------
st.markdown('<div class="section-title">🤖 智能总结</div>', unsafe_allow_html=True)
model_options = {
    "DeepSeek-V3": "deepseek-ai/DeepSeek-V3",
    "DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
    "Qwen2.5-72B": "Qwen/Qwen2.5-72B-Instruct",
    "Qwen2.5-7B": "Qwen/Qwen2.5-7B-Instruct",
    "GLM-4-9B": "glm-4-9b-chat"
}
selected_model_name = st.selectbox("选择 AI 模型", options=list(model_options.keys()), index=1, key="ai_model_select")
selected_model = model_options[selected_model_name]

if st.button("🚀 生成智能总结", key="generate_ai_summary"):
    shop_rank_items = list(shop_latest.items()) if not shop_latest.empty else []
    rank_text = "\n".join([f"{i+1}. {shop}: ¥{amt:,.0f}" for i, (shop, amt) in enumerate(shop_rank_items[:3])]) if shop_rank_items else "暂无"
    context = f"""
    部门：{selected_dept if selected_dept != '全部' else '全部'}
    昨日销售：¥{latest_sales:,.0f}
    月累计：¥{month_sales:,.0f}
    前日销售：¥{prev_sales:,.0f}
    环比变化：{change:+.1f}%
    月目标完成率：{target_rate:.0f}%
    退货率：{return_rate:.1f}%
    店铺排行 TOP3：{rank_text}
    异常提醒数：{len(alerts)}条
    """
    prompt = """你是一位资深的电商数据分析师。请根据提供的经营数据，用一段专业、简洁的中文总结昨日的经营状况。要求：1. 指出亮点；2. 发现风险；3. 给出1-2条可操作的建议。"""
    with st.spinner("🤖 AI 正在分析，请稍候..."):
        ai_summary = get_ai_summary(prompt, context, selected_model)
    st.session_state.ai_summary_result = ai_summary
    st.rerun()

if "ai_summary_result" in st.session_state and st.session_state.ai_summary_result:
    st.markdown(f"""
    <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);border-radius:12px;padding:16px 20px;margin-top:10px;">
        <div style="color:#1e293b;font-size:14px;line-height:1.7;">{st.session_state.ai_summary_result}</div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("点击上方按钮生成 AI 智能总结。")
