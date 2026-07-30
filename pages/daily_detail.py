# pages/daily_detail.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import io

from core.db import (
    fetch_sales_summary,
    load_org_targets,
    load_dimension_mapping,
    load_targets,
    get_sales_date_range  # 新增高效日期范围函数
)
from core.utils import date_quick_buttons

st.set_page_config(page_title="每日明细", layout="wide")

# 确保全局状态
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""
if "target_dict" not in st.session_state:
    st.session_state.target_dict = {}

# ---------- 页面样式 ----------
st.markdown("""
<style>
    .stApp { background: #f3f6fa; font-family: 'Inter', sans-serif; }
    .stSubheader { font-weight: 500; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; margin-bottom: 16px; }
    .stColumns > .stColumn > div {
        background: rgba(255,255,255,0.6);
        backdrop-filter: blur(8px);
        border-radius: 16px;
        padding: 12px 16px;
        border: 1px solid rgba(255,255,255,0.3);
        box-shadow: 0 4px 16px rgba(0,20,40,0.04);
    }
    .stDataFrame {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    .stDataFrame thead tr th {
        background: #eef2f7 !important;
        color: #0f172a !important;
        font-weight: 600;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        padding: 10px 12px;
        border-bottom: 2px solid #cbd5e1;
    }
    .stDataFrame tbody tr td {
        padding: 8px 12px;
        border-bottom: 1px solid #e2e8f0;
        background: #ffffff;
    }
    .stDataFrame tbody tr:nth-child(even) td {
        background: #f8fafc;
    }
    .stDataFrame tbody tr:hover td {
        background: #f1f5f9;
    }
    .stButton button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #2563eb !important;
        font-weight: 400;
        padding: 4px 12px !important;
    }
    .stButton button:hover {
        text-decoration: underline !important;
        color: #1d4ed8 !important;
    }
    div[data-testid="stMetric"] {
        background: rgba(255,255,255,0.5);
        backdrop-filter: blur(8px);
        border-radius: 16px;
        padding: 16px;
        border: 1px solid rgba(255,255,255,0.3);
    }
    .stMetricValue {
        font-size: 1.8rem !important;
        font-weight: 600 !important;
        color: #0f172a;
    }
    .stDownloadButton button {
        background: #2563eb !important;
        color: white !important;
        border-radius: 20px !important;
        padding: 6px 20px !important;
        border: none !important;
        font-weight: 500;
        box-shadow: 0 4px 12px rgba(37,99,235,0.25);
    }
    .stDownloadButton button:hover {
        background: #1d4ed8 !important;
        box-shadow: 0 8px 20px rgba(37,99,235,0.35);
    }
    .stAlert {
        border-radius: 12px;
        background: rgba(255,255,255,0.6);
        backdrop-filter: blur(8px);
        border-left: 4px solid #3b82f6;
        padding: 12px 16px;
    }
</style>
""", unsafe_allow_html=True)

st.subheader("📋 每日明细查询")
st.info("此处展示任意日期的销售明细，支持按组织/部门/店铺维度汇总，并可查看特定组织的店铺明细。")

# ---------- 数据源 ----------
suffix = st.session_state.table_suffix
is_all = suffix == "_all"

# ===== 修改：使用高效的日期范围查询，避免全表加载 =====
min_date, max_date = get_sales_date_range(suffix)
if min_date is None or max_date is None:
    st.warning("暂无商品销售数据，请先上传订单文件。")
    st.stop()

# ---------- 维度选择 ----------
if is_all:
    mapping_df = load_dimension_mapping()
    has_org = not mapping_df.empty and 'org_name' in mapping_df.columns
    if has_org:
        org_targets = load_org_targets("_all")
        dimension_options = ["阿米巴组织", "部门", "小店运营组"]
        selected_dim = st.radio("选择维度", dimension_options, horizontal=True, key="dimension_select_daily")

        if selected_dim == "阿米巴组织":
            all_orgs = sorted(mapping_df['org_name'].dropna().unique())
            selected_org = st.selectbox("选择组织", all_orgs, key="org_select")
            group_col = "org_name"
            dim_label = "组织"
            target_dict = org_targets
            use_shop_detail = False
            org_filter = None

        elif selected_dim == "部门":
            group_col = "dept"
            dim_label = "部门"
            dept_targets = {}
            if not mapping_df.empty:
                org_dept_map = mapping_df[['org_name', 'dept']].drop_duplicates()
                for _, row in org_dept_map.iterrows():
                    org = row['org_name']
                    dept = row['dept']
                    target = org_targets.get(org, 0)
                    dept_targets[dept] = dept_targets.get(dept, 0) + target

            # 强制零售线上目标为 0
            if "零售线上" in dept_targets:
                dept_targets["零售线上"] = 0

            target_dict = dept_targets
            use_shop_detail = False
            org_filter = None

        else:  # 小店运营组
            group_col = "shop_name"
            dim_label = "店铺"
            target_dict = load_targets()
            use_shop_detail = True
            org_filter = "小店运营组"
            st.info("当前选择：小店运营组 → 展示该组织下所有店铺的销售明细，目标取自店铺目标表。")
    else:
        # 无映射表，回退到店铺
        group_col = "shop_name"
        dim_label = "店铺名称"
        target_dict = st.session_state.target_dict
        use_shop_detail = False
        org_filter = None
else:
    # 非全部数据，固定店铺维度
    group_col = "shop_name"
    dim_label = "店铺名称"
    target_dict = st.session_state.target_dict
    use_shop_detail = False
    org_filter = None

# ---------- 日期范围选择 ----------
# 确保 session_state 中的日期值有效
if "range_start" not in st.session_state or st.session_state["range_start"] < min_date or st.session_state["range_start"] > max_date:
    st.session_state["range_start"] = max_date
if "range_end" not in st.session_state or st.session_state["range_end"] < min_date or st.session_state["range_end"] > max_date:
    st.session_state["range_end"] = max_date

st.markdown("#### 📅 选择日期范围")
col_btns = st.columns(5)
with col_btns[0]:
    if st.button("📅 今日"):
        st.session_state["range_start"] = max_date
        st.session_state["range_end"] = max_date
        st.rerun()
with col_btns[1]:
    if st.button("📆 近7天"):
        st.session_state["range_start"] = max_date - timedelta(days=6)
        st.session_state["range_end"] = max_date
        st.rerun()
with col_btns[2]:
    if st.button("📆 本月"):
        st.session_state["range_start"] = max_date.replace(day=1)
        st.session_state["range_end"] = max_date
        st.rerun()
with col_btns[3]:
    if st.button("📆 上月"):
        first_day_this_month = max_date.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        st.session_state["range_start"] = first_day_last_month
        st.session_state["range_end"] = last_day_last_month
        st.rerun()
with col_btns[4]:
    if st.button("📆 全部"):
        st.session_state["range_start"] = min_date
        st.session_state["range_end"] = max_date
        st.rerun()

col1, col2 = st.columns(2)
with col1:
    st.date_input("起始日期", key="range_start", min_value=min_date, max_value=max_date)
with col2:
    st.date_input("结束日期", key="range_end", min_value=min_date, max_value=max_date)

if st.button("🔍 查询", key="range_query"):
    st.rerun()

# ---------- 加载数据 ----------
start = st.session_state["range_start"]
end = st.session_state["range_end"]
if start > end:
    start, end = end, start
    st.session_state["range_start"] = start
    st.session_state["range_end"] = end

@st.cache_data(ttl=300)
def load_aggregated_data(start_date, end_date, suffix):
    return fetch_sales_summary(start_date, end_date, suffix)

with st.spinner(f"加载 {start} 至 {end} 的数据..."):
    df = load_aggregated_data(start, end, suffix)

if df.empty:
    st.warning("所选范围内无销售数据")
    st.stop()

# ---------- 如果启用店铺明细模式，过滤组织 ----------
if use_shop_detail and org_filter:
    df = df[df['org_name'] == org_filter]
    if df.empty:
        st.warning(f"组织 {org_filter} 无销售数据")
        st.stop()

# ---------- 展示结果 ----------
st.markdown(f"#### 📊 查询结果（{start} ~ {end}）")
if start == end:
    # ---------- 单日模式 ----------
    st.caption("单日明细，同时显示当月累计数据")
    month_start = start.replace(day=1)
    df_mtd = load_aggregated_data(month_start, start, suffix)
    if use_shop_detail and org_filter:
        df_mtd = df_mtd[df_mtd['org_name'] == org_filter]

    # ===== 修复：确保部门列非空（若按部门分组） =====
    if group_col == "dept":
        df[group_col] = df[group_col].fillna("未分配部门")
        df_mtd[group_col] = df_mtd[group_col].fillna("未分配部门")

    def aggregate_by_dim(df, group_col, dim_label):
        if df.empty or group_col not in df.columns:
            return pd.DataFrame()
        agg = df.groupby(group_col).agg(
            发货金额=("total_ship", "sum"),
            退货金额=("total_return", "sum"),
            净销售金额=("total_net", "sum")
        ).reset_index().rename(columns={group_col: dim_label})
        return agg

    today_agg = aggregate_by_dim(df, group_col, dim_label)
    month_agg = aggregate_by_dim(df_mtd, group_col, dim_label)

    if today_agg.empty and month_agg.empty:
        st.info("无数据")
    else:
        merged = pd.merge(today_agg, month_agg, on=dim_label, suffixes=("_日", "_月"), how="outer").fillna(0)
        merged["日退货率"] = merged.apply(
            lambda r: (r['退货金额_日'] / r['发货金额_日'] * 100) if r['发货金额_日'] != 0 else 0.0, axis=1
        ).map(lambda x: f"{x:.2f}%")
        merged["月累计退货率"] = merged.apply(
            lambda r: (r['退货金额_月'] / r['发货金额_月'] * 100) if r['发货金额_月'] != 0 else 0.0, axis=1
        ).map(lambda x: f"{x:.2f}%")
        merged["目标金额"] = merged[dim_label].map(target_dict).fillna(0)
        merged["达成率"] = merged.apply(
            lambda r: (r['净销售金额_月'] / r['目标金额'] * 100) if r['目标金额'] != 0 else 0.0, axis=1
        ).map(lambda x: f"{x:.2f}%")
        merged = merged.sort_values(dim_label)

        display_cols = [
            dim_label,
            "发货金额_日", "退货金额_日", "净销售金额_日", "日退货率",
            "发货金额_月", "退货金额_月", "净销售金额_月", "月累计退货率",
            "目标金额", "达成率"
        ]
        column_config = {
            dim_label: st.column_config.TextColumn(dim_label),
            "发货金额_日": st.column_config.NumberColumn("日发货", format="%.2f"),
            "退货金额_日": st.column_config.NumberColumn("日退货", format="%.2f"),
            "净销售金额_日": st.column_config.NumberColumn("日净额", format="%.2f"),
            "日退货率": st.column_config.TextColumn("日退货率"),
            "发货金额_月": st.column_config.NumberColumn("月累计发货", format="%.2f"),
            "退货金额_月": st.column_config.NumberColumn("月累计退货", format="%.2f"),
            "净销售金额_月": st.column_config.NumberColumn("月累计净额", format="%.2f"),
            "月累计退货率": st.column_config.TextColumn("月累计退货率"),
            "目标金额": st.column_config.NumberColumn("目标金额", format="%.2f"),
            "达成率": st.column_config.TextColumn("达成率")
        }
        st.dataframe(merged[display_cols], column_config=column_config, use_container_width=True, hide_index=True)

        total_today_ship = float(merged["发货金额_日"].sum())
        total_today_return = float(merged["退货金额_日"].sum())
        total_today_net = float(merged["净销售金额_日"].sum())
        total_month_ship = float(merged["发货金额_月"].sum())
        total_month_return = float(merged["退货金额_月"].sum())
        total_month_net = float(merged["净销售金额_月"].sum())
        total_target = float(merged["目标金额"].sum())
        total_return_rate = (total_month_return / total_month_ship * 100) if total_month_ship != 0 else 0.0
        total_rate = (total_month_net / total_target * 100) if total_target != 0 else 0.0

        col1, col2, col3 = st.columns(3)
        col1.metric("📊 当日合计", f"净额: ¥{total_today_net:,.2f}", delta=f"发货 ¥{total_today_ship:,.2f} / 退货 ¥{total_today_return:,.2f}")
        col2.metric("📆 月累计合计", f"净额: ¥{total_month_net:,.2f}", delta=f"发货 ¥{total_month_ship:,.2f} / 退货 ¥{total_month_return:,.2f} | 退货率 {total_return_rate:.2f}%")
        col3.metric("🎯 目标完成率", f"{total_rate:.2f}%", delta=f"总目标: ¥{total_target:,.2f}")

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            merged[display_cols].to_excel(writer, index=False)
        st.download_button(
            "💾 导出明细",
            data=output.getvalue(),
            file_name=f"明细_{start}.xlsx",
            key="export_detail"
        )
else:
    # ================== 多日模式 ==================
    # 确保 df 非空且有必需列
    if df.empty:
        st.warning("所选范围内无销售数据")
        st.stop()
    required_cols = ['total_ship', 'total_return', 'total_net']
    if not all(col in df.columns for col in required_cols):
        st.error(f"数据缺少必需列：{required_cols}")
        st.stop()

    # 直接求和，得到 Series（或可能是标量，取决于版本）
    totals = df[required_cols].sum()
    # 确保每个值都是标量
    total_ship = totals['total_ship']
    total_return = totals['total_return']
    total_net = totals['total_net']

    # 如果还是 Series（极少见），则取第一个元素
    if isinstance(total_ship, pd.Series):
        total_ship = total_ship.iloc[0]
    if isinstance(total_return, pd.Series):
        total_return = total_return.iloc[0]
    if isinstance(total_net, pd.Series):
        total_net = total_net.iloc[0]

    return_rate = (total_return / total_ship * 100) if total_ship > 0 else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("总发货", f"¥{total_ship:,.2f}")
    col2.metric("总退货", f"¥{total_return:,.2f}")
    col3.metric("总净额", f"¥{total_net:,.2f}", delta=f"退货率 {return_rate:.2f}%")

    # ---------- 按维度汇总 ----------
    if group_col in df.columns:
        dim_agg = df.groupby(group_col).agg(
            发货金额=("total_ship", "sum"),
            退货金额=("total_return", "sum"),
            净销售金额=("total_net", "sum")
        ).reset_index().rename(columns={group_col: dim_label})
        dim_agg["退款率"] = dim_agg.apply(
            lambda r: f"{(r['退货金额'] / r['发货金额'] * 100):.2f}%" if r['发货金额'] != 0 else "-", axis=1
        )
        if use_shop_detail and group_col == "shop_name":
            dim_agg["目标金额"] = dim_agg[dim_label].map(target_dict).fillna(0)
            dim_agg["达成率"] = dim_agg.apply(
                lambda r: (r['净销售金额'] / r['目标金额'] * 100) if r['目标金额'] != 0 else 0.0, axis=1
            ).map(lambda x: f"{x:.2f}%")
        st.markdown(f"#### 按 {dim_label} 汇总")
        st.dataframe(dim_agg, use_container_width=True, hide_index=True)

    # ---------- 每日透视表 ----------
    if group_col in df.columns:
        daily_dim = df.groupby(["sale_date", group_col]).agg(
            净销售金额=("total_net", "sum")
        ).reset_index()
        pivot = daily_dim.pivot(index="sale_date", columns=group_col, values="净销售金额").fillna(0)
        pivot.index = pd.to_datetime(pivot.index).date
        st.markdown("#### 每日净销售金额明细")
        st.dataframe(pivot, use_container_width=True)

    # ---------- 导出 ----------
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if group_col in df.columns:
            dim_agg.to_excel(writer, sheet_name="按维度汇总", index=False)
        if group_col in df.columns and not pivot.empty:
            pivot.reset_index().to_excel(writer, sheet_name="每日明细", index=False)
        df.to_excel(writer, sheet_name="原始数据", index=False)
    st.download_button(
        "💾 导出范围查询结果",
        data=output.getvalue(),
        file_name=f"范围查询_{start}_{end}.xlsx",
        key="export_range"
    )
