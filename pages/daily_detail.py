# pages/daily_detail.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import io

from core.db import load_product_sales, load_org_targets, load_dimension_mapping
from core.utils import extract_anchor, date_quick_buttons

st.set_page_config(page_title="每日明细", layout="wide")

# 确保全局状态
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""
if "target_dict" not in st.session_state:
    st.session_state.target_dict = {}

# ---------- 页面样式（与商品分析页统一） ----------
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
st.info("此处展示最新日销售明细，并支持按日期查询任意一天的销售情况。")

# ---------- 加载商品数据 ----------
with st.spinner("加载数据..."):
    prod_df = load_product_sales(st.session_state.table_suffix, apply_filter=False)

if prod_df.empty:
    st.warning("暂无商品销售数据，请先上传订单文件。")
    st.stop()

# ---------- 映射表合并（仅全部数据） ----------
is_all = st.session_state.table_suffix == "_all"

# 默认维度（非全部数据为店铺）
group_col = "shop_name"
dim_label = "店铺名称"
target_dict = st.session_state.target_dict

def apply_dimension_mapping(df, mapping_df):
    """
    对 df 应用维度映射，与 fetch_sales_summary 中的逻辑一致。
    返回添加了 org_name 和 dept 列的 DataFrame。
    """
    if mapping_df.empty:
        df["org_name"] = "未分配组织"
        df["dept"] = "未分配部门"
        return df

    # 1. 清洗字段
    df["shop_name_clean"] = df["shop_name"].astype(str).str.strip().str.upper()
    mapping_df["shop_name_clean"] = mapping_df["shop_name"].astype(str).str.strip().str.upper()
    mapping_df["anchor_name_clean"] = mapping_df["anchor_name"].fillna("NONE").astype(str).str.strip().str.upper()

    # 2. 如果有 anchor，提取并清洗
    if "anchor" not in df.columns:
        df["anchor"] = "NONE"
    df["anchor_clean"] = df["anchor"].fillna("NONE").astype(str).str.strip().str.upper()

    # 3. 按 (shop_name_clean, anchor_clean) 精确匹配
    merged = df.merge(
        mapping_df[["shop_name_clean", "anchor_name_clean", "org_name", "dept"]],
        left_on=["shop_name_clean", "anchor_clean"],
        right_on=["shop_name_clean", "anchor_name_clean"],
        how="left"
    )

    # 4. 对于未匹配的行，回退到仅按 shop_name 匹配（取第一条）
    null_mask = merged["org_name"].isna()
    if null_mask.any():
        fallback = mapping_df.drop_duplicates(subset=["shop_name_clean"], keep="first")[["shop_name_clean", "org_name", "dept"]]
        fallback = fallback.rename(columns={"org_name": "org_fallback", "dept": "dept_fallback"})
        merged = merged.merge(fallback, on="shop_name_clean", how="left")
        merged.loc[null_mask, "org_name"] = merged.loc[null_mask, "org_fallback"]
        merged.loc[null_mask, "dept"] = merged.loc[null_mask, "dept_fallback"]
        merged = merged.drop(columns=["org_fallback", "dept_fallback"])

    # 5. 填充缺失值
    merged["org_name"] = merged["org_name"].fillna("未分配组织")
    merged["dept"] = merged["dept"].fillna("未分配部门")

    # 6. 删除临时列
    df_out = merged.drop(columns=["shop_name_clean", "anchor_clean"])
    return df_out

if is_all:
    mapping_df = load_dimension_mapping()
    prod_df = apply_dimension_mapping(prod_df, mapping_df)

    # 检查合并后是否有 org_name 和 dept（应该总是有）
    if 'org_name' in prod_df.columns and 'dept' in prod_df.columns:
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
            org_dept_map = prod_df[['org_name', 'dept']].drop_duplicates()
            dept_targets = {}
            for _, row in org_dept_map.iterrows():
                org = row['org_name']
                dept = row['dept']
                target = org_targets.get(org, 0)
                dept_targets[dept] = dept_targets.get(dept, 0) + target
            target_dict = dept_targets
    else:
        # 若仍未出现，回退到店铺
        st.warning("未获取到组织/部门信息，将按店铺维度展示。")
        group_col = "shop_name"
        dim_label = "店铺名称"
        target_dict = st.session_state.target_dict

# 最终检查 group_col 是否存在
if group_col not in prod_df.columns or prod_df[group_col].isna().all():
    st.warning(f"当前数据中无 {dim_label} 信息，已切换为店铺维度。")
    group_col = "shop_name"
    dim_label = "店铺名称"
    target_dict = st.session_state.target_dict

# ---------- 聚合辅助函数 ----------
def aggregate_dim(df, group_col, dim_label):
    agg = df.groupby(group_col).agg(
        发货金额=("ship_amount", "sum"),
        退货金额=("return_amount", "sum"),
        净销售金额=("net_amount", "sum")
    ).reset_index().rename(columns={group_col: dim_label})
    return agg

# ---------- 第一部分：最新日明细 ----------
st.markdown("#### 📅 最新日明细")
source_names = {"": "非直播数据", "_all": "全部数据"}
current_source = source_names.get(st.session_state.table_suffix, "未知")
st.caption(f"当前数据源：**{current_source}**")

latest_date = prod_df["sale_date"].max().date()
month_start = latest_date.replace(day=1)

mask_today = prod_df["sale_date"].dt.date == latest_date
today_data = prod_df[mask_today]
today_agg = aggregate_dim(today_data, group_col, dim_label)

mask_month = (prod_df["sale_date"].dt.date >= month_start) & (prod_df["sale_date"].dt.date <= latest_date)
month_data = prod_df[mask_month]
month_agg = aggregate_dim(month_data, group_col, dim_label)

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

if not df_latest.empty:
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
    st.info("无数据")

st.markdown("---")

# ---------- 第二部分：日期查询 ----------
st.markdown("#### 🔍 日期查询")
if st.button("📅 今日", key="query_today_daily"):
    st.session_state["query_date_daily"] = date.today()
    st.rerun()
query_date = st.date_input(
    "查询日期",
    value=st.session_state.get("query_date_daily", date.today()),
    key="query_date_daily"
)
if st.button("查询", key="query_btn_daily"):
    mask_query = prod_df["sale_date"].dt.date == query_date
    query_data = prod_df[mask_query]
    if query_data.empty:
        st.warning("该日期无数据")
    else:
        query_agg = aggregate_dim(query_data, group_col, dim_label)
        month_start_q = query_date.replace(day=1)
        mask_month_q = (prod_df["sale_date"].dt.date >= month_start_q) & (prod_df["sale_date"].dt.date <= query_date)
        month_data_q = prod_df[mask_month_q]
        month_agg_q = aggregate_dim(month_data_q, group_col, dim_label)

        df_query = pd.merge(query_agg, month_agg_q, on=dim_label, suffixes=("_日", "_月"), how="outer").fillna(0)
        df_query["日退货率_数值"] = df_query.apply(
            lambda r: (r['退货金额_日'] / r['发货金额_日'] * 100) if r['发货金额_日'] != 0 else 0.0, axis=1
        )
        df_query["月累计退货率_数值"] = df_query.apply(
            lambda r: (r['退货金额_月'] / r['发货金额_月'] * 100) if r['发货金额_月'] != 0 else 0.0, axis=1
        )
        df_query = df_query.sort_values(dim_label)

        display_cols_q = [
            dim_label,
            "发货金额_日", "退货金额_日", "净销售金额_日", "日退货率_数值",
            "发货金额_月", "退货金额_月", "净销售金额_月", "月累计退货率_数值"
        ]
        rename_map_q = {
            dim_label: dim_label,
            "发货金额_日": "当日发货",
            "退货金额_日": "当日退货",
            "净销售金额_日": "当日净额",
            "日退货率_数值": "日退货率",
            "发货金额_月": "月累计发货",
            "退货金额_月": "月累计退货",
            "净销售金额_月": "月累计净额",
            "月累计退货率_数值": "月累计退货率"
        }
        display_q = df_query[display_cols_q].rename(columns=rename_map_q)

        column_config_q = {
            dim_label: st.column_config.TextColumn(dim_label),
            "当日发货": st.column_config.NumberColumn("当日发货", format="%.2f"),
            "当日退货": st.column_config.NumberColumn("当日退货", format="%.2f"),
            "当日净额": st.column_config.NumberColumn("当日净额", format="%.2f"),
            "日退货率": st.column_config.NumberColumn("日退货率", format="%.2f%%"),
            "月累计发货": st.column_config.NumberColumn("月累计发货", format="%.2f"),
            "月累计退货": st.column_config.NumberColumn("月累计退货", format="%.2f"),
            "月累计净额": st.column_config.NumberColumn("月累计净额", format="%.2f"),
            "月累计退货率": st.column_config.NumberColumn("月累计退货率", format="%.2f%%")
        }
        st.dataframe(display_q, column_config=column_config_q, use_container_width=True, hide_index=True)

        total_q_ship = df_query["发货金额_日"].sum()
        total_q_return = df_query["退货金额_日"].sum()
        total_q_net = df_query["净销售金额_日"].sum()
        total_q_month_ship = df_query["发货金额_月"].sum()
        total_q_month_return = df_query["退货金额_月"].sum()
        total_q_month_net = df_query["净销售金额_月"].sum()
        col1, col2 = st.columns(2)
        with col1:
            st.metric("📊 当日合计", f"净额: ¥{total_q_net:,.2f}", delta=f"发货 ¥{total_q_ship:,.2f} / 退货 ¥{total_q_return:,.2f}")
        with col2:
            st.metric("📆 截止当日月累计", f"净额: ¥{total_q_month_net:,.2f}", delta=f"发货 ¥{total_q_month_ship:,.2f} / 退货 ¥{total_q_month_return:,.2f}")

        output_q = io.BytesIO()
        with pd.ExcelWriter(output_q, engine='openpyxl') as writer:
            export_q = display_q.copy()
            for col in ['日退货率', '月累计退货率']:
                if col in export_q.columns:
                    export_q[col] = export_q[col].apply(lambda x: f"{x:.2f}%")
            export_q.to_excel(writer, index=False)
        st.download_button(
            "💾 导出查询结果",
            data=output_q.getvalue(),
            file_name=f"查询_{query_date}.xlsx",
            key="export_query_result_daily"
        )
