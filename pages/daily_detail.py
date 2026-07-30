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

st.set_page_config(page_title="每日明细", layout="wide")

# ---------- 状态初始化 ----------
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""
if "target_dict" not in st.session_state:
    st.session_state.target_dict = {}
if "diagnose" not in st.session_state:
    st.session_state.diagnose = False

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
st.info("展示所选日期范围内的销售数据，按组织/部门/店铺维度汇总。")

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
        group_col = "shop_name"
        dim_label = "店铺名称"
        target_dict = st.session_state.target_dict
        use_shop_detail = False
        org_filter = None
else:
    group_col = "shop_name"
    dim_label = "店铺名称"
    target_dict = st.session_state.target_dict
    use_shop_detail = False
    org_filter = None

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
        st.cache_data.clear()   # 强制清除所有缓存
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

# ---------- 查询和诊断 ----------
col_query, col_diag = st.columns([1, 1])
with col_query:
    if st.button("🔍 查询", key="range_query"):
        st.rerun()
with col_diag:
    if st.button("🔍 诊断商品部", key="diagnose_btn"):
        st.session_state.diagnose = True
        st.rerun()

# ---------- 加载数据 ----------
start = st.session_state["range_start"]
end = st.session_state["range_end"]
if start > end:
    start, end = end, start
    st.session_state["range_start"] = start
    st.session_state["range_end"] = end

@st.cache_data(ttl=60)
def load_aggregated_data(start_date, end_date, suffix):
    return fetch_sales_summary(start_date, end_date, suffix)

with st.spinner(f"加载 {start} 至 {end} 的数据..."):
    df = load_aggregated_data(start, end, suffix)

if df.empty:
    st.warning("所选范围内无销售数据")
    st.stop()

# ---------- 组织过滤 ----------
if use_shop_detail and org_filter:
    df = df[df['org_name'] == org_filter]
    if df.empty:
        st.warning(f"组织 {org_filter} 无销售数据")
        st.stop()

# ---------- 诊断逻辑 ----------
if st.session_state.diagnose:
    st.session_state.diagnose = False  # 重置
    st.markdown("### 🛠️ 诊断信息")
    with st.expander("点击展开调试数据", expanded=True):
        st.write(f"总行数: {len(df)}")
        if 'dept' in df.columns:
            st.write(f"dept 唯一值: {df['dept'].unique().tolist()}")
            dept_count = df[df['dept'] == '商品部'].shape[0]
            st.write(f"商品部记录数: {dept_count}")
            if dept_count > 0:
                st.dataframe(df[df['dept'] == '商品部'].head(5))
            else:
                st.warning("当前查询无商品部")
                st.write("涉及所有店铺（去重后）:", df['shop_name'].unique().tolist())
        if 'shop_name' in df.columns:
            st.write(f"涉及店铺数量: {len(df['shop_name'].unique())}")
        # 检查特定店铺
        target = "商品组"
        if 'shop_name' in df.columns:
            shops = df['shop_name'].astype(str).str.strip().str.upper().unique()
            if target.upper() in shops:
                st.success(f"✅ 数据中包含店铺 '{target}'")
                sample = df[df['shop_name'].str.upper() == target.upper()]
                st.dataframe(sample)
            else:
                st.error(f"❌ 数据中不包含店铺 '{target}'")
        # 显示映射表
        mapping_df = load_dimension_mapping()
        if not mapping_df.empty:
            st.write("映射表中的商品组相关记录:")
            st.dataframe(mapping_df[mapping_df['shop_name'].str.contains('商品组', case=False)])

# ---------- 展示结果 ----------
st.markdown(f"#### 📊 查询结果（{start} ~ {end}）")

# 1. 指标卡
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
