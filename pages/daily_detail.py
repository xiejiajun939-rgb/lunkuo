# pages/daily_detail.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import io

from core.db import fetch_sales_summary, load_org_targets, load_dimension_mapping
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
</style>
""", unsafe_allow_html=True)

st.subheader("📋 每日明细查询")
st.info("此处展示最新日销售明细，并支持按日期范围查询任意时间段的销售数据。")

# ---------- 数据源与日期范围 ----------
suffix = st.session_state.table_suffix
is_all = suffix == "_all"

# 获取日期范围（从商品数据中读取）
from core.db import load_product_sales
date_df = load_product_sales(suffix, apply_filter=False)
if date_df.empty:
    st.warning("暂无商品销售数据，请先上传订单文件。")
    st.stop()
min_date = date_df["sale_date"].min().date()
max_date = date_df["sale_date"].max().date()

# ---------- 维度选择 ----------
if is_all:
    mapping_df = load_dimension_mapping()
    has_org = not mapping_df.empty and 'org_name' in mapping_df.columns
    if has_org:
        org_targets = load_org_targets("_all")
        dimension_options = ["阿米巴组织", "部门"]
        selected_dim = st.radio("选择维度", dimension_options, horizontal=True, key="dimension_select_daily")
        if selected_dim == "阿米巴组织":
            group_col = "org_name"
            dim_label = "组织"
            target_dict = org_targets
        else:
            group_col = "dept"
            dim_label = "部门"
            # 汇总部门目标
            dept_targets = {}
            if not mapping_df.empty:
                org_dept_map = mapping_df[['org_name', 'dept']].drop_duplicates()
                for _, row in org_dept_map.iterrows():
                    org = row['org_name']
                    dept = row['dept']
                    target = org_targets.get(org, 0)
                    dept_targets[dept] = dept_targets.get(dept, 0) + target
            target_dict = dept_targets
    else:
        has_org = False
        group_col = "shop_name"
        dim_label = "店铺名称"
        target_dict = st.session_state.target_dict
else:
    group_col = "shop_name"
    dim_label = "店铺名称"
    target_dict = st.session_state.target_dict

# ---------- 缓存数据加载函数 ----------
@st.cache_data(ttl=300)
def load_aggregated_data(start_date, end_date, suffix):
    return fetch_sales_summary(start_date, end_date, suffix)

# ---------- 第一部分：最新日明细 ----------
st.markdown("#### 📅 最新日明细")
source_names = {"": "非直播数据", "_all": "全部数据"}
current_source = source_names.get(suffix, "未知")
latest_date = max_date
month_start = latest_date.replace(day=1)

with st.spinner("加载最新日数据..."):
    df_today = load_aggregated_data(latest_date, latest_date, suffix)
    df_mtd = load_aggregated_data(month_start, latest_date, suffix)

# 按维度分组聚合函数
def aggregate_by_dim(df, group_col, dim_label):
    if df.empty:
        return pd.DataFrame()
    # 确保 group_col 存在
    if group_col not in df.columns:
        return pd.DataFrame()
    agg = df.groupby(group_col).agg(
        发货金额=("total_ship", "sum"),
        退货金额=("total_return", "sum"),
        净销售金额=("total_net", "sum")
    ).reset_index().rename(columns={group_col: dim_label})
    return agg

today_agg = aggregate_by_dim(df_today, group_col, dim_label)
month_agg = aggregate_by_dim(df_mtd, group_col, dim_label)

if not today_agg.empty or not month_agg.empty:
    # 合并
    df_latest = pd.merge(today_agg, month_agg, on=dim_label, suffixes=("_日", "_月"), how="outer").fillna(0)
    df_latest["日退货率_数值"] = df_latest.apply(
        lambda r: (r['退货金额_日'] / r['发货金额_日'] * 100) if r['发货金额_日'] != 0 else 0.0, axis=1
    )
    df_latest["月累计退货率_数值"] = df_latest.apply(
        lambda r: (r['退货金额_月'] / r['发货金额_月'] * 100) if r['发货金额_月'] != 0 else 0.0, axis=1
    )
    df_latest["目标金额"] = df_latest[dim_label].map(target_dict).fillna(0)
    df_latest["达成率_数值"] = df_latest.apply(
        lambda r: (r['净销售金额_月'] / r['目标金额'] * 100) if r['目标金额'] != 0 else 0.0, axis=1
    )
    df_latest = df_latest.sort_values(dim_label)

    display_cols = [
        dim_label,
        "发货金额_日", "退货金额_日", "净销售金额_日", "日退货率_数值",
        "发货金额_月", "退货金额_月", "净销售金额_月", "月累计退货率_数值",
        "目标金额", "达成率_数值"
    ]
    rename_map = {
        dim_label: dim_label,
        "发货金额_日": "日发货",
        "退货金额_日": "日退货",
        "净销售金额_日": "日净额",
        "日退货率_数值": "日退货率",
        "发货金额_月": "月累计发货",
        "退货金额_月": "月累计退货",
        "净销售金额_月": "月累计净额",
        "月累计退货率_数值": "月累计退货率",
        "目标金额": "目标金额",
        "达成率_数值": "达成率"
    }
    display_df = df_latest[display_cols].rename(columns=rename_map)
    column_config = {
        dim_label: st.column_config.TextColumn(dim_label),
        "日发货": st.column_config.NumberColumn("日发货", format="%.2f"),
        "日退货": st.column_config.NumberColumn("日退货", format="%.2f"),
        "日净额": st.column_config.NumberColumn("日净额", format="%.2f"),
        "日退货率": st.column_config.NumberColumn("日退货率", format="%.2f%%"),
        "月累计发货": st.column_config.NumberColumn("月累计发货", format="%.2f"),
        "月累计退货": st.column_config.NumberColumn("月累计退货", format="%.2f"),
        "月累计净额": st.column_config.NumberColumn("月累计净额", format="%.2f"),
        "月累计退货率": st.column_config.NumberColumn("月累计退货率", format="%.2f%%"),
        "目标金额": st.column_config.NumberColumn("目标金额", format="%.2f"),
        "达成率": st.column_config.NumberColumn("达成率", format="%.2f%%")
    }
    st.dataframe(display_df, column_config=column_config, use_container_width=True, hide_index=True)

    total_today_ship = df_latest["发货金额_日"].sum()
    total_today_return = df_latest["退货金额_日"].sum()
    total_today_net = df_latest["净销售金额_日"].sum()
    total_month_ship = df_latest["发货金额_月"].sum()
    total_month_return = df_latest["退货金额_月"].sum()
    total_month_net = df_latest["净销售金额_月"].sum()
    total_target = df_latest["目标金额"].sum()
    total_return_rate = (total_month_return / total_month_ship * 100) if total_month_ship != 0 else 0.0
    total_rate = (total_month_net / total_target * 100) if total_target != 0 else 0.0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📊 当日合计", f"净额: ¥{total_today_net:,.2f}", delta=f"发货 ¥{total_today_ship:,.2f} / 退货 ¥{total_today_return:,.2f}")
    with col2:
        st.metric("📆 月累计合计", f"净额: ¥{total_month_net:,.2f}", delta=f"发货 ¥{total_month_ship:,.2f} / 退货 ¥{total_month_return:,.2f} | 退货率 {total_return_rate:.2f}%")
    with col3:
        st.metric("🎯 目标完成率", f"{total_rate:.2f}%", delta=f"总目标: ¥{total_target:,.2f}")

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        export_df = display_df.copy()
        for col in ['日退货率', '月累计退货率', '达成率']:
            if col in export_df.columns:
                export_df[col] = export_df[col].apply(lambda x: f"{x:.2f}%")
        export_df.to_excel(writer, index=False)
    st.download_button(
        "💾 导出最新日明细",
        data=output.getvalue(),
        file_name=f"最新日明细_{latest_date}.xlsx",
        key="export_latest_detail_dim"
    )
else:
    st.info("无最新日数据")

st.markdown("---")

# ---------- 第二部分：日期范围查询 ----------
st.markdown("#### 🔍 日期范围查询")
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("起始日期", value=max_date - timedelta(days=6), min_value=min_date, max_value=max_date, key="range_start")
with col2:
    end_date = st.date_input("结束日期", value=max_date, min_value=min_date, max_value=max_date, key="range_end")

# 快捷按钮
col_btns = st.columns(4)
with col_btns[0]:
    if st.button("📅 今日", key="range_today"):
        st.session_state["range_start"] = max_date
        st.session_state["range_end"] = max_date
        st.rerun()
with col_btns[1]:
    if st.button("📆 近7天", key="range_7days"):
        st.session_state["range_start"] = max_date - timedelta(days=6)
        st.session_state["range_end"] = max_date
        st.rerun()
with col_btns[2]:
    if st.button("📆 本月", key="range_month"):
        st.session_state["range_start"] = max_date.replace(day=1)
        st.session_state["range_end"] = max_date
        st.rerun()
with col_btns[3]:
    if st.button("📆 上月", key="range_last_month"):
        first_day_this_month = max_date.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        st.session_state["range_start"] = first_day_last_month
        st.session_state["range_end"] = last_day_last_month
        st.rerun()

if st.button("🔍 查询", key="range_query"):
    if start_date > end_date:
        st.error("起始日期不能晚于结束日期")
    else:
        with st.spinner(f"加载 {start_date} 至 {end_date} 的数据..."):
            df_range = load_aggregated_data(start_date, end_date, suffix)
            if df_range.empty:
                st.warning("所选范围内无数据")
            else:
                st.success(f"共加载 {len(df_range)} 条记录")
                # 1. 汇总总计
                total_ship = df_range["total_ship"].sum()
                total_return = df_range["total_return"].sum()
                total_net = df_range["total_net"].sum()
                return_rate = (total_return / total_ship * 100) if total_ship > 0 else 0.0
                col1, col2, col3 = st.columns(3)
                col1.metric("总发货", f"¥{total_ship:,.2f}")
                col2.metric("总退货", f"¥{total_return:,.2f}")
                col3.metric("总净额", f"¥{total_net:,.2f}", delta=f"退货率 {return_rate:.2f}%")

                # 2. 按维度分组汇总（范围总计）
                if group_col in df_range.columns:
                    dim_agg = df_range.groupby(group_col).agg(
                        发货金额=("total_ship", "sum"),
                        退货金额=("total_return", "sum"),
                        净销售金额=("total_net", "sum")
                    ).reset_index().rename(columns={group_col: dim_label})
                    dim_agg["退款率"] = dim_agg.apply(
                        lambda r: f"{(r['退货金额'] / r['发货金额'] * 100):.2f}%" if r['发货金额'] != 0 else "-", axis=1
                    )
                    st.markdown(f"#### 按 {dim_label} 汇总（{start_date} ~ {end_date}）")
                    st.dataframe(dim_agg, use_container_width=True, hide_index=True)

                # 3. 每日明细（透视表：日期 × 维度）
                if group_col in df_range.columns:
                    # 按日期和维度分组
                    daily_dim = df_range.groupby(["sale_date", group_col]).agg(
                        净销售金额=("total_net", "sum")
                    ).reset_index()
                    # 透视
                    pivot = daily_dim.pivot(index="sale_date", columns=group_col, values="净销售金额").fillna(0)
                    # 重命名列
                    pivot.columns = [f"{col}" for col in pivot.columns]
                    pivot.index = pd.to_datetime(pivot.index).date
                    # 显示
                    st.markdown(f"#### 每日{ dim_label}净销售金额明细")
                    st.dataframe(pivot, use_container_width=True)

                # 4. 导出
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    # 汇总表
                    if group_col in df_range.columns:
                        dim_agg.to_excel(writer, sheet_name="按维度汇总", index=False)
                    # 每日明细
                    if group_col in df_range.columns and not pivot.empty:
                        pivot.reset_index().to_excel(writer, sheet_name="每日明细", index=False)
                    # 原始数据（可选）
                    df_range.to_excel(writer, sheet_name="原始数据", index=False)
                st.download_button(
                    "💾 导出范围查询结果",
                    data=output.getvalue(),
                    file_name=f"范围查询_{start_date}_{end_date}.xlsx",
                    key="export_range_result"
                )
