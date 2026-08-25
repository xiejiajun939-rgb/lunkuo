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
    get_sales_date_range
)
from core.utils import clear_cache_on_page_change

st.set_page_config(page_title="每日明细", layout="wide")
clear_cache_on_page_change("daily_detail")

# ---------- 状态初始化 ----------
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
    .stDataFrame { background: transparent !important; border: none !important; box-shadow: none !important; }
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
    .stDataFrame tbody tr:nth-child(even) td { background: #f8fafc; }
    .stDataFrame tbody tr:hover td { background: #f1f5f9; }
    .stButton button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #2563eb !important;
        font-weight: 400;
        padding: 4px 12px !important;
    }
    .stButton button:hover { text-decoration: underline !important; color: #1d4ed8 !important; }
    div[data-testid="stMetric"] {
        background: rgba(255,255,255,0.5);
        backdrop-filter: blur(8px);
        border-radius: 16px;
        padding: 16px;
        border: 1px solid rgba(255,255,255,0.3);
    }
    .stMetricValue { font-size: 1.8rem !important; font-weight: 600 !important; color: #0f172a; }
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
st.caption("展示所选日期范围内的销售数据，按组织/部门/店铺维度汇总。")

# ---------- 数据源 ----------
suffix = st.session_state.table_suffix
is_all = suffix == "_all"

# 获取日期范围
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
        dimension_options = ["部门", "小店运营组"]
        selected_dim = st.radio("选择维度", dimension_options, horizontal=True, key="dimension_select_daily")

        # 需要细分到组织的部门（其余部门只显示总计）
        detail_depts = ["零售线下", "阿里", "自媒体", "零售线上"]

        if selected_dim == "部门":
            all_depts = sorted(mapping_df['dept'].dropna().unique())
            # 小店运营有单独维度，从部门列表排除
            all_depts = [d for d in all_depts if d != "小店运营"]
            selected_dept = st.selectbox("选择部门", all_depts, key="dept_select")

            if selected_dept in detail_depts:
                # 细分到组织
                group_col = "org_name"
                dim_label = "组织"
                target_dict = org_targets
            else:
                # 显示部门总计
                group_col = "dept"
                dim_label = "部门"
                dept_targets = {}
                org_dept_map = mapping_df[['org_name', 'dept']].drop_duplicates()
                for _, row in org_dept_map.iterrows():
                    org = row['org_name']
                    dept = row['dept']
                    target = org_targets.get(org, 0)
                    dept_targets[dept] = dept_targets.get(dept, 0) + target
                if "零售线上" in dept_targets:
                    dept_targets["零售线上"] = 0
                target_dict = dept_targets

            dept_filter = selected_dept
            org_filter = None
            use_shop_detail = False
        else:  # 小店运营组
            group_col = "shop_name"
            dim_label = "店铺"
            target_dict = load_targets("")
            use_shop_detail = True
            org_filter = "小店运营组"
            dept_filter = None
            st.caption("当前选择：小店运营组 → 展示该组织下所有店铺的销售明细，目标取自店铺目标表。")
    else:
        group_col = "shop_name"
        dim_label = "店铺名称"
        target_dict = st.session_state.target_dict
        use_shop_detail = False
        org_filter = None
        dept_filter = None
else:
    group_col = "shop_name"
    dim_label = "店铺名称"
    target_dict = st.session_state.target_dict
    use_shop_detail = False
    org_filter = None
    dept_filter = None

# ---------- 日期初始化（默认本月） ----------
if "range_start" not in st.session_state or st.session_state["range_start"] < min_date or st.session_state["range_start"] > max_date:
    st.session_state["range_start"] = max_date.replace(day=1)
if "range_end" not in st.session_state or st.session_state["range_end"] < min_date or st.session_state["range_end"] > max_date:
    st.session_state["range_end"] = max_date

# ---------- 日期选择控件 ----------
st.markdown("#### 📅 选择日期范围")
col_btns = st.columns(5)
with col_btns[0]:
    if st.button("📆 本月"):
        st.cache_data.clear()
        st.session_state["range_start"] = max_date.replace(day=1)
        st.session_state["range_end"] = max_date
        st.rerun()
with col_btns[1]:
    if st.button("📆 上月"):
        first_day_this_month = max_date.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        st.session_state["range_start"] = first_day_last_month
        st.session_state["range_end"] = last_day_last_month
        st.rerun()
with col_btns[2]:
    if st.button("📅 今日"):
        st.session_state["range_start"] = max_date
        st.session_state["range_end"] = max_date
        st.rerun()
with col_btns[3]:
    if st.button("📆 近7天"):
        st.session_state["range_start"] = max_date - timedelta(days=6)
        st.session_state["range_end"] = max_date
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

# ---------- 查询 ----------
if st.button("🔍 查询", key="range_query"):
    st.rerun()

# ---------- 加载数据 ----------
start = st.session_state["range_start"]
end = st.session_state["range_end"]
if start > end:
    start, end = end, start
    st.session_state["range_start"] = start
    st.session_state["range_end"] = end

def load_aggregated_data(start_date, end_date, suffix):
    return fetch_sales_summary(start_date, end_date, suffix)

with st.spinner(f"加载 {start} 至 {end} 的数据..."):
    df = load_aggregated_data(start, end, suffix)

if df.empty:
    st.warning("所选范围内无销售数据")
    st.stop()

# ---------- 过滤 ----------
if dept_filter:
    df = df[df['dept'] == dept_filter]
    if df.empty:
        st.warning(f"部门 {dept_filter} 无销售数据")
        st.stop()
if org_filter:
    df = df[df['org_name'] == org_filter]
    if df.empty:
        st.warning(f"组织 {org_filter} 无销售数据")
        st.stop()

# ---------- 展示结果 ----------
st.markdown(f"#### 📊 查询结果（{start} ~ {end}）")

# 1. 总体指标卡
total_ship = df["total_ship"].sum()
total_return = df["total_return"].sum()
total_net = df["total_net"].sum()
return_rate = (total_return / total_ship * 100) if total_ship > 0 else 0.0

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("总发货", f"¥{total_ship:,.2f}")
col_m2.metric("总退货", f"¥{total_return:,.2f}")
col_m3.metric("总净额", f"¥{total_net:,.2f}", delta=f"退货率 {return_rate:.2f}%")

# 2. 按维度汇总
if group_col in df.columns:
    dim_agg = df.groupby(group_col).agg(
        发货金额=("total_ship", "sum"),
        退货金额=("total_return", "sum"),
        净销售金额=("total_net", "sum")
    ).reset_index().rename(columns={group_col: dim_label})
    dim_agg["退货率"] = dim_agg.apply(
        lambda r: f"{(r['退货金额'] / r['发货金额'] * 100):.2f}%" if r['发货金额'] != 0 else "-", axis=1
    )
    if use_shop_detail and group_col == "shop_name":
        dim_agg["目标金额"] = dim_agg[dim_label].map(target_dict).fillna(0)
        dim_agg["达成率"] = dim_agg.apply(
            lambda r: (r['净销售金额'] / r['目标金额'] * 100) if r['目标金额'] != 0 else 0.0, axis=1
        ).map(lambda x: f"{x:.2f}%")
        display_cols = [dim_label, "发货金额", "退货金额", "净销售金额", "退货率", "目标金额", "达成率"]
        # 追加"小店运营汇总"总计行
        total_target = sum(target_dict.values()) if target_dict else 0
        total_row = {
            dim_label: "🏪 小店运营汇总",
            "发货金额": total_ship,
            "退货金额": total_return,
            "净销售金额": total_net,
            "退货率": f"{return_rate:.2f}%" if total_ship != 0 else "-",
            "目标金额": total_target,
            "达成率": f"{(total_net / total_target * 100):.2f}%" if total_target != 0 else "0.00%"
        }
        dim_agg = pd.concat([dim_agg, pd.DataFrame([total_row])], ignore_index=True)
    else:
        display_cols = [dim_label, "发货金额", "退货金额", "净销售金额", "退货率"]

    st.markdown(f"#### 按 {dim_label} 汇总")
    st.dataframe(dim_agg[display_cols], use_container_width=True, hide_index=True)

# 3. 每日透视（若区间 >1 天）
if (end - start).days >= 1 and group_col in df.columns:
    daily_dim = df.groupby(["sale_date", group_col]).agg(
        净销售金额=("total_net", "sum")
    ).reset_index()
    pivot = daily_dim.pivot(index="sale_date", columns=group_col, values="净销售金额").fillna(0)
    pivot.index = pd.to_datetime(pivot.index).date
    if use_shop_detail and group_col == "shop_name":
        pivot["🏪 小店运营汇总"] = pivot.sum(axis=1)
    st.markdown("#### 每日净销售金额明细")
    st.dataframe(pivot, use_container_width=True)

# 4. 导出
output = io.BytesIO()
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    if group_col in df.columns:
        dim_agg.to_excel(writer, sheet_name="按维度汇总", index=False)
    if (end - start).days >= 1 and group_col in df.columns and not pivot.empty:
        pivot.reset_index().to_excel(writer, sheet_name="每日明细", index=False)
    df.to_excel(writer, sheet_name="原始数据", index=False)
st.download_button(
    "💾 导出查询结果",
    data=output.getvalue(),
    file_name=f"明细_{start}_{end}.xlsx",
    key="export_detail"
)
