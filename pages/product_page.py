# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import io
import re
import numpy as np

from core.db import load_product_sales, load_product_master, get_sales_date_range
from core.product_tags import normalize_product_tags, product_tags_text
try:
    from core.db import load_product_sales_cube
except ImportError:
    # Streamlit Cloud 热更新时可能暂时保留旧版 core.db 模块，兼容到下次进程重启。
    def load_product_sales_cube(start_date, end_date, apply_filter=True):
        return load_product_sales(
            "_all", apply_filter=apply_filter, include_offline=False,
            start_date=start_date, end_date=end_date,
        )
from core.utils import date_quick_buttons, extract_anchor, clear_cache_on_page_change
from core.ai import get_ai_summary
from core.theme import page_header

st.markdown("""
<style>
    /* ========== 全局基础 ========== */
    .stApp {
        background: #f3f6fa;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    /* ========== 标题区 ========== */
    .stMarkdown h1 {
        font-size: 2.4rem !important;
        font-weight: 600 !important;
        background: linear-gradient(135deg, #0b1a33 0%, #2563eb 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.2rem !important;
        letter-spacing: -0.02em;
        border-bottom: 3px solid rgba(37, 99, 235, 0.2);
        padding-bottom: 8px;
        display: inline-block;
    }

    /* ========== 数据源单选按钮（美化） ========== */
    .stRadio > div {
        background: rgba(255,255,255,0.6);
        backdrop-filter: blur(8px);
        border-radius: 12px;
        padding: 6px 12px !important;
        border: 1px solid rgba(255,255,255,0.3);
    }
    .stRadio label {
        font-weight: 500 !important;
        color: #1e293b !important;
    }

    /* ========== 日期选择区（卡片） ========== */
    div[data-testid="stDateInput"] {
        background: rgba(255,255,255,0.7) !important;
        backdrop-filter: blur(8px);
        border-radius: 14px !important;
        padding: 6px 12px !important;
        border: 1px solid rgba(255,255,255,0.4);
        box-shadow: 0 2px 8px rgba(0,20,40,0.04);
    }
    div[data-testid="stDateInput"] input {
        border: none !important;
        background: transparent !important;
        padding: 4px 0 !important;
        font-weight: 400;
    }

    /* 日期快捷按钮（今日/近7天/本月） */
    .stButton button:has(> :contains("📅")),
    .stButton button:has(> :contains("📆")) {
        background: transparent !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 20px !important;
        padding: 2px 14px !important;
        font-size: 0.8rem !important;
        color: #475569 !important;
        transition: all 0.2s;
        box-shadow: none !important;
    }
    .stButton button:has(> :contains("📅")):hover,
    .stButton button:has(> :contains("📆")):hover {
        background: #e2e8f0 !important;
        border-color: #94a3b8 !important;
    }

    /* ========== 筛选条件区（卡片） ========== */
    .stColumns:has(> .stColumn > .stSelectbox) {
        background: rgba(255,255,255,0.6) !important;
        backdrop-filter: blur(8px);
        border-radius: 20px !important;
        padding: 16px 20px !important;
        border: 1px solid rgba(255,255,255,0.3);
        box-shadow: 0 4px 16px rgba(0,20,40,0.04);
        margin-bottom: 16px;
    }

    /* 筛选控件标签（平台、店铺等） */
    .stSelectbox label, .stTextInput label, .stMultiSelect label {
        font-weight: 500 !important;
        color: #0f172a !important;
        font-size: 0.8rem !important;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        margin-bottom: 2px !important;
    }

    /* 筛选输入框、下拉框（透明无框，只保留底部线条） */
    .stSelectbox > div > div > div,
    .stTextInput > div > div > input,
    .stMultiSelect > div > div > div {
        background: transparent !important;
        border: none !important;
        border-bottom: 2px solid #e2e8f0 !important;
        border-radius: 0 !important;
        padding: 4px 0 !important;
        box-shadow: none !important;
        font-weight: 400;
        color: #0f172a;
        transition: border-color 0.2s;
    }
    .stSelectbox > div > div > div:focus-within,
    .stTextInput > div > div > input:focus,
    .stMultiSelect > div > div > div:focus-within {
        border-bottom-color: #2563eb !important;
    }

    /* 多选框标签（已选） */
    .stMultiSelect [data-testid="stMultiSelectTag"] {
        background: rgba(37, 99, 235, 0.08) !important;
        border-radius: 12px !important;
        padding: 2px 10px !important;
        color: #2563eb !important;
        font-weight: 500;
    }

    /* ========== 表格区 ========== */
    .stColumn > div:has(.stDataFrame) {
        background: transparent !important;
        backdrop-filter: none !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
    }

    .stDataFrame {
        background: transparent !important;
        border: none !important;
        border-radius: 0 !important;
        box-shadow: none !important;
    }

    /* 表头 */
    .stDataFrame thead tr th {
        background: #eef2f7 !important;
        color: #0f172a !important;
        font-weight: 600 !important;
        font-size: 0.75rem !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        padding: 10px 12px !important;
        border-bottom: 2px solid #cbd5e1 !important;
        border-top: 1px solid #e2e8f0;
    }

    /* 表格行 */
    .stDataFrame tbody tr td {
        padding: 8px 12px !important;
        border-bottom: 1px solid #e2e8f0 !important;
        background: #ffffff !important;
        font-size: 0.9rem;
        color: #1e293b;
    }
    /* 交替行颜色（浅灰） */
    .stDataFrame tbody tr:nth-child(even) td {
        background: #f8fafc !important;
    }
    /* 悬浮效果 */
    .stDataFrame tbody tr:hover td {
        background: #f1f5f9 !important;
        transition: background 0.15s;
    }

    /* 图片列（商品图片） */
    .stDataFrame tbody tr td:has(img) {
        padding: 4px 6px !important;
        text-align: center;
    }
    .stDataFrame tbody tr td img {
        max-width: 50px !important;
        max-height: 50px !important;
        border-radius: 6px;
        border: 1px solid #e2e8f0;
    }

    /* 新人礼金列（✅ ❌）用颜色表示 */
    .stDataFrame tbody tr td:has(:contains("✅")) {
        color: #22c55e !important;
        font-weight: 600;
    }
    .stDataFrame tbody tr td:has(:contains("❌")) {
        color: #94a3b8 !important;
        font-weight: 400;
    }

    /* 退款率列（根据高低颜色） */
    .stDataFrame tbody tr td:nth-child(7) {
        font-weight: 500;
    }
    .stDataFrame tbody tr td:nth-child(7):contains("%") {
        color: #dc2626; /* 默认红色，但可配合js或简单处理，这里用静态颜色 */
    }

    /* ========== 详情/趋势按钮（图标按钮） ========== */
    .stButton button:has(> :contains("📊")),
    .stButton button:has(> :contains("📈")) {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 4px 8px !important;
        font-size: 1.2rem !important;
        border-radius: 50% !important;
        transition: background 0.2s, transform 0.1s;
        color: #64748b !important;
        width: 32px !important;
        height: 32px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    .stButton button:has(> :contains("📊")):hover,
    .stButton button:has(> :contains("📈")):hover {
        background: rgba(37, 99, 235, 0.08) !important;
        color: #2563eb !important;
        transform: scale(1.1);
    }

    /* ========== 排序与分页区 ========== */
    .stSelectbox:has(label:contains("排序字段")),
    .stSelectbox:has(label:contains("每页行数")) {
        background: transparent !important;
        border: none !important;
    }
    .stSelectbox:has(label:contains("排序字段")) > div > div > div,
    .stSelectbox:has(label:contains("每页行数")) > div > div > div {
        border: none !important;
        border-bottom: 1px dashed #cbd5e1 !important;
        border-radius: 0 !important;
        padding: 4px 0 !important;
        background: transparent !important;
    }

    /* 翻页按钮（上一页/下一页） */
    div[data-testid="stButton"] button:has(> :contains("◀")),
    div[data-testid="stButton"] button:has(> :contains("▶")) {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 4px 8px !important;
        font-weight: 400 !important;
        color: #2563eb !important;
        transition: color 0.2s;
        font-size: 0.9rem;
    }
    div[data-testid="stButton"] button:has(> :contains("◀")):hover,
    div[data-testid="stButton"] button:has(> :contains("▶")):hover {
        color: #1d4ed8 !important;
        text-decoration: underline !important;
        background: transparent !important;
    }

    /* 页码文字 */
    .stMarkdown p:has(+ div[data-testid="stButton"]) {
        margin: 0 8px !important;
        color: #475569 !important;
        font-weight: 400;
        font-size: 0.9rem;
        background: transparent !important;
    }

    /* 导出类型下拉框（只留文字+下划线） */
    .stSelectbox:has(label:contains("导出类型")) > div > div > div {
        border: none !important;
        border-bottom: 1px solid #cbd5e1 !important;
        border-radius: 0 !important;
        padding: 4px 0 !important;
        background: transparent !important;
    }

    /* ========== 对话框（详情/趋势） ========== */
    div[data-testid="stDialog"] {
        background: rgba(255, 255, 255, 0.8) !important;
        backdrop-filter: blur(24px) !important;
        border-radius: 28px !important;
        border: 1px solid rgba(255, 255, 255, 0.5) !important;
        box-shadow: 0 24px 80px rgba(0, 20, 40, 0.12) !important;
        padding: 28px !important;
    }
    div[data-testid="stDialog"] .stDataFrame {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    div[data-testid="stDialog"] .stDataFrame thead tr th {
        background: rgba(241, 245, 249, 0.5) !important;
    }

    /* ========== 侧边栏（保留原有毛玻璃，但更干净） ========== */
    section[data-testid="stSidebar"] {
        background: rgba(255, 255, 255, 0.5) !important;
        backdrop-filter: blur(20px) !important;
        border-right: 1px solid rgba(255, 255, 255, 0.2) !important;
        padding: 20px 14px !important;
    }

    /* ========== 通用微调 ========== */
    hr {
        margin: 20px 0 !important;
        border: none !important;
        height: 1px !important;
        background: linear-gradient(to right, #e2e8f0, transparent) !important;
    }

    /* 货号汇总表标题（保留，但修饰） */
    .stMarkdown h3:contains("货号汇总表") {
        font-size: 1.2rem !important;
        font-weight: 500 !important;
        color: #0f172a !important;
        border-left: 4px solid #2563eb;
        padding-left: 12px;
        margin-bottom: 16px;
    }

    /* 适应小屏幕 */
    @media (max-width: 768px) {
        .stColumns:has(> .stColumn > .stSelectbox) {
            padding: 12px !important;
        }
        .stDataFrame tbody tr td {
            padding: 4px 6px !important;
            font-size: 0.8rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)
st.set_page_config(page_title="商品分析", layout="wide")
clear_cache_on_page_change("product_page")

# ---------- 初始化 session_state ----------
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""
if "detail_clicked" not in st.session_state:
    st.session_state.detail_clicked = False
if "show_dialog" not in st.session_state:
    st.session_state.show_dialog = False
if "dialog_style_code" not in st.session_state:
    st.session_state.dialog_style_code = None
if "cached_detail_data" not in st.session_state:
    st.session_state.cached_detail_data = None
if "trend_clicked" not in st.session_state:
    st.session_state.trend_clicked = False
if "show_trend_dialog" not in st.session_state:
    st.session_state.show_trend_dialog = False
if "trend_style_code" not in st.session_state:
    st.session_state.trend_style_code = None
if "trend_data" not in st.session_state:
    st.session_state.trend_data = None
if "product_page_num" not in st.session_state:
    st.session_state.product_page_num = 1
if "product_page_size" not in st.session_state:
    st.session_state.product_page_size = 10
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "净销售金额"
if "sort_ascending" not in st.session_state:
    st.session_state.sort_ascending = False

page_header("商品分析", "从销售、退货、品类和渠道维度定位商品机会与风险", "PRODUCT INTELLIGENCE", "本月默认")

# ---------- 日期选择（先确定范围，再按需查询数据库） ----------
min_date, max_date = get_sales_date_range("_all")
if min_date is None or max_date is None:
    st.warning("暂无数据，请先上传订单文件。")
    st.stop()
default_start = max(min_date, max_date.replace(day=1))
date_quick_buttons("prod_start_month", "prod_end_month",
                   default_start=default_start,
                   default_end=max_date,
                   min_date=min_date,
                   max_date=max_date)
start_date = st.session_state.get("prod_start_month", default_start)
end_date = st.session_state.get("prod_end_month", max_date)

# ---------- 加载所选日期范围的数据 ----------
with st.spinner("加载商品销售数据..."):
    prod_df = load_product_sales_cube(start_date, end_date)

if prod_df.empty:
    st.warning("暂无数据，请先上传订单文件。")
    st.stop()

# ---------- 预处理 ----------
if "style_code" in prod_df.columns:
    prod_df["style_code"] = prod_df["style_code"].astype(str).str.strip().str.upper()
else:
    prod_df["style_code"] = prod_df["product_code"].str[:8].str.strip().str.upper()

if st.session_state.table_suffix == "_all" and "anchor" not in prod_df.columns:
    prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)

if "anchor_display" not in prod_df.columns:
    raw_anchor = prod_df.get("anchor", pd.Series("NONE", index=prod_df.index)).fillna("NONE").astype(str)
    prod_df["anchor_display"] = raw_anchor
    missing_anchor = raw_anchor.str.upper().isin(["", "NONE", "NAN", "<NA>"])
    prod_df.loc[missing_anchor, "anchor_display"] = (
        "未识别主播｜" + prod_df.loc[missing_anchor, "shop_name"].fillna("未知店铺").astype(str)
    )

dimension_config = {
    "全部": None,
    "部门": "dept",
    "组织": "org_name",
    "店铺": "shop_name",
    "主播": "anchor_display",
}


def _has_recognized_anchor(frame):
    anchor = frame.get("anchor", pd.Series("NONE", index=frame.index)).fillna("NONE").astype(str).str.upper()
    return ~anchor.isin(["", "NONE", "NAN", "<NA>"])


def attach_dynamic_breakdown(frame, level, selected):
    """生成当前分析条件对应的动态明细对象。"""
    result = frame.copy()
    level_field = dimension_config[level]

    # 只选择分析层级、没有指定对象：明细就按当前层级展示。
    if not selected:
        if level == "全部":
            result["_detail_type"] = "店铺"
            result["_detail_value"] = result["shop_name"]
        else:
            result["_detail_type"] = level
            result["_detail_value"] = result[level_field]
        return result

    recognized_anchor = _has_recognized_anchor(result)

    if level == "部门":
        # 常规部门先下探组织；小店运营直接下探店铺。
        shop_department = result["dept"].astype(str).str.contains("小店运营", case=False, na=False)
        result["_detail_type"] = np.where(shop_department, "店铺", "组织")
        result["_detail_value"] = np.where(shop_department, result["shop_name"], result["org_name"])
    elif level == "组织":
        # 组织内存在明确主播时看主播，否则看店铺。
        org_anchor_map = recognized_anchor.groupby(result["org_name"]).any().to_dict()
        use_anchor = result["org_name"].map(org_anchor_map).fillna(False)
        result["_detail_type"] = np.where(use_anchor, "主播", "店铺")
        result["_detail_value"] = np.where(use_anchor, result["anchor_display"], result["shop_name"])
    elif level == "店铺":
        # 店铺内有明确主播则继续下探主播；没有则保持店铺明细。
        shop_anchor_map = recognized_anchor.groupby(result["shop_name"]).any().to_dict()
        use_anchor = result["shop_name"].map(shop_anchor_map).fillna(False)
        result["_detail_type"] = np.where(use_anchor, "主播", "店铺")
        result["_detail_value"] = np.where(use_anchor, result["anchor_display"], result["shop_name"])
    elif level == "主播":
        # 指定主播后，以其销售店铺作为下一层明细。
        result["_detail_type"] = "店铺"
        result["_detail_value"] = result["shop_name"]
    else:
        result["_detail_type"] = "店铺"
        result["_detail_value"] = result["shop_name"]

    return result

# ---------- 筛选条件（一行4列） ----------
st.subheader("🔍 筛选条件")

# 第一行：分析层级、分析对象、货号、品牌
col1, col2, col3, col4 = st.columns(4)
with col1:
    analysis_level = st.selectbox("分析层级", list(dimension_config), key="product_analysis_level")
with col2:
    level_field = dimension_config[analysis_level]
    level_options = sorted(prod_df[level_field].dropna().astype(str).unique()) if level_field else []
    selected_objects = st.multiselect(
        f"选择{analysis_level}", level_options, key="product_analysis_objects",
        disabled=level_field is None,
    )
with col3:
    style_input = st.text_input("货号（逗号分隔）", placeholder="例如: L262Y050", key="sc")
with col4:
    brands = ["全部"] + sorted(prod_df["brand"].dropna().unique())
    selected_brand = st.selectbox("品牌", brands, key="bf")

# 第二行：平台、店铺、商品标签、下钻说明
col5, col6, col7, col8 = st.columns(4)
with col5:
    platform_options = ["全部", "抖音", "视频号", "小红书", "天猫", "唯品会"]
    selected_platform = st.selectbox("平台", platform_options, key="pf")
with col6:
    all_shops = prod_df["shop_name"].dropna().unique()
    shop_opts = [s for s in all_shops if selected_platform == "全部" or selected_platform.lower() in str(s).lower()]
    selected_shops = st.multiselect("店铺", sorted(shop_opts), key="sf")
with col7:
    tag_options = sorted({
        tag for value in load_product_master().get("tags", pd.Series(dtype=object))
        for tag in normalize_product_tags(value)
    })
    selected_tags = st.multiselect("商品标签", tag_options, key="product_tag_filter")
with col8:
    if selected_objects:
        st.info("已指定对象：明细将按业务归属自动下钻")
    else:
        st.info(f"未指定对象：明细按{analysis_level if analysis_level != '全部' else '店铺'}展示")

# ---------- 应用筛选 ----------
mask = (prod_df["sale_date"] >= pd.to_datetime(start_date)) & (prod_df["sale_date"] <= pd.to_datetime(end_date))
filtered = prod_df[mask].copy()

if selected_platform != "全部":
    filtered = filtered[filtered["shop_name"].str.contains(selected_platform, case=False, na=False)]
if selected_shops:
    filtered = filtered[filtered["shop_name"].isin(selected_shops)]
if style_input.strip():
    codes = [c.strip().upper() for c in style_input.split(",") if c.strip()]
    if codes:
        filtered = filtered[filtered["style_code"].isin(codes)]
if selected_brand != "全部":
    filtered = filtered[filtered["brand"] == selected_brand]
if level_field and selected_objects:
    filtered = filtered[filtered[level_field].astype(str).isin(selected_objects)]

# ---------- 过滤线下订单（remark 以 LA、PA、FA 开头） ----------
if "remark" in filtered.columns:
    filtered = filtered[~filtered["remark"].astype(str).str.upper().str.startswith(("LA", "PA", "FA"))]

# 礼金标记
master_df = load_product_master()
tag_map = {}
if not master_df.empty and "style_code" in master_df.columns:
    master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
    tag_map = master_df.set_index("style_code")["tags"].to_dict()
filtered["product_tags"] = filtered["style_code"].map(tag_map).map(normalize_product_tags)
if selected_tags:
    filtered = filtered[filtered["product_tags"].map(
        lambda tags: all(tag in tags for tag in selected_tags)
    )]

if filtered.empty:
    st.warning("无匹配数据")
    st.stop()

filtered = attach_dynamic_breakdown(filtered, analysis_level, selected_objects)
detail_types = sorted(filtered["_detail_type"].dropna().unique())
detail_label = detail_types[0] if len(detail_types) == 1 else "动态归属"

# ---------- 聚合 ----------
grouped = filtered.groupby("style_code").agg(
    发货金额=("ship_amount", "sum"),
    退货金额=("return_amount", "sum"),
    净销售金额=("net_amount", "sum")
).reset_index().rename(columns={"style_code": "货号"})

# 补充图片、分类、礼金信息
if not master_df.empty and "style_code" in master_df.columns:
    # 商品管理/导出页以最后维护的档案为准；前台保持同一口径，避免重复货号
    # 时读取到旧分类。货号和分类同时做纯文本清洗，防止空格/类型差异导致错配。
    master_df["style_code"] = master_df["style_code"].fillna("").astype(str).str.strip().str.upper()
    master_df["category"] = master_df["category"].fillna("").astype(str).str.strip()
    master_df = master_df[master_df["style_code"] != ""].drop_duplicates("style_code", keep="last")
    grouped["货号"] = grouped["货号"].fillna("").astype(str).str.strip().str.upper()
    img_map = master_df.set_index("style_code")["image_url"].to_dict()
    cat_map = master_df.set_index("style_code")["category"].to_dict()
    grouped["image_url"] = grouped["货号"].map(img_map)
    grouped["master_category"] = grouped["货号"].map(cat_map).replace("", None)
    grouped["product_tags"] = grouped["货号"].map(tag_map).map(normalize_product_tags)
else:
    grouped["image_url"] = None
    grouped["master_category"] = None
    grouped["product_tags"] = [[] for _ in range(len(grouped))]

grouped["退款率"] = np.where(
    grouped["发货金额"] != 0,
    (grouped["退货金额"] / grouped["发货金额"] * 100).map("{:.2f}%".format),
    "-"
)

# ---------- 排序与分页 ----------
st.markdown("#### 货号汇总表")
col_s1, col_s2, col_s3 = st.columns([1, 1, 2])
with col_s1:
    sort_opts = ["货号", "发货金额", "退货金额", "净销售金额", "退款率"]
    sort_by = st.selectbox("排序字段", sort_opts, index=sort_opts.index(st.session_state.sort_by), key="sort_sel")
with col_s2:
    asc = st.radio("顺序", ["降序", "升序"], horizontal=True, index=0 if not st.session_state.sort_ascending else 1, key="order")
with col_s3:
    psize = st.selectbox("每页行数", [10, 20, 50, 100], index=[10,20,50,100].index(st.session_state.product_page_size), key="psize")

# 更新排序参数
if sort_by != st.session_state.sort_by or (asc == "升序" and not st.session_state.sort_ascending) or (asc == "降序" and st.session_state.sort_ascending):
    st.session_state.sort_by = sort_by
    st.session_state.sort_ascending = (asc == "升序")
    st.session_state.product_page_num = 1
    st.rerun()

# 排序
if st.session_state.sort_by == "货号":
    grouped = grouped.sort_values("货号", ascending=st.session_state.sort_ascending)
elif st.session_state.sort_by == "发货金额":
    grouped = grouped.sort_values("发货金额", ascending=st.session_state.sort_ascending)
elif st.session_state.sort_by == "退货金额":
    grouped = grouped.sort_values("退货金额", ascending=st.session_state.sort_ascending)
elif st.session_state.sort_by == "净销售金额":
    grouped = grouped.sort_values("净销售金额", ascending=st.session_state.sort_ascending)
elif st.session_state.sort_by == "退款率":
    grouped["退款率_num"] = grouped["退款率"].str.rstrip("%").astype(float)
    grouped = grouped.sort_values("退款率_num", ascending=st.session_state.sort_ascending)
    grouped = grouped.drop(columns=["退款率_num"])

# 分页
total = len(grouped)
pages = (total + psize - 1) // psize if total > 0 else 1
if st.session_state.product_page_num > pages:
    st.session_state.product_page_num = 1
start_idx = (st.session_state.product_page_num - 1) * psize
end_idx = min(start_idx + psize, total)
page_df = grouped.iloc[start_idx:end_idx]

# 分页控制
col_prev, col_page, col_next, col_export = st.columns([1, 2, 1, 2])
with col_prev:
    if st.button("◀ 上一页", key="prev"):
        if st.session_state.product_page_num > 1:
            st.session_state.product_page_num -= 1
            st.rerun()
with col_page:
    st.write(f"第 {st.session_state.product_page_num} / {pages} 页")
with col_next:
    if st.button("下一页 ▶", key="next"):
        if st.session_state.product_page_num < pages:
            st.session_state.product_page_num += 1
            st.rerun()
with col_export:
    export_detail_label = f"明细（货号+{detail_label}）"
    export_type = st.radio("导出类型", ["汇总（货号级别）", export_detail_label], horizontal=True, key="export_type")
    if st.button("📥 下载数据", key="exp"):
        if export_type == "汇总（货号级别）":
            export_df = grouped.copy()
            if "image_url" in export_df.columns:
                export_df = export_df.drop(columns=["image_url"])
            cols_order = ["货号", "master_category", "发货金额", "退货金额", "净销售金额", "退款率", "product_tags"]
            export_cols = [c for c in cols_order if c in export_df.columns]
            export_df = export_df[export_cols]
            export_df.rename(columns={
                "master_category": "商品分类",
                "product_tags": "商品标签"
            }, inplace=True)
            export_df["商品标签"] = export_df["商品标签"].map(product_tags_text)
            sheet_name = "货号汇总"
            file_suffix = "货号汇总"
        else:
            group_col = "_detail_value"
            group_name = "明细对象"
            detail_agg = filtered.groupby(["style_code", "_detail_type", group_col], dropna=False).agg(
                明细发货金额=("ship_amount", "sum"),
                明细退货金额=("return_amount", "sum"),
                明细净销售金额=("net_amount", "sum")
            ).reset_index().rename(columns={"_detail_type": "明细类型"})
            detail_agg["明细退款率"] = np.where(
                detail_agg["明细发货金额"] != 0,
                (detail_agg["明细退货金额"] / detail_agg["明细发货金额"] * 100).map("{:.2f}%".format),
                "-"
            )
            master_cols = grouped[["货号", "master_category", "发货金额", "退货金额", "净销售金额", "退款率", "product_tags"]].copy()
            export_df = pd.merge(
                detail_agg,
                master_cols,
                left_on="style_code",
                right_on="货号",
                how="left"
            )
            export_df.drop(columns=["style_code"], inplace=True)
            export_df.rename(columns={
                group_col: group_name,
                "master_category": "商品分类",
                "product_tags": "商品标签"
            }, inplace=True)
            export_df["商品标签"] = export_df["商品标签"].map(product_tags_text)
            final_cols = [
                "货号", "商品分类", "发货金额", "退货金额", "净销售金额", "退款率", "商品标签",
                "明细类型", group_name, "明细发货金额", "明细退货金额", "明细净销售金额", "明细退款率"
            ]
            export_df = export_df[final_cols]
            sheet_name = f"货号{group_name}明细"
            file_suffix = f"货号{group_name}明细"
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            export_df.to_excel(writer, index=False, sheet_name=sheet_name)
        st.success("导出成功！点击下方按钮下载")
        st.download_button(
            label="💾 点击下载 Excel",
            data=output.getvalue(),
            file_name=f"{file_suffix}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx",
            key="download_export",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ---------- 显示表格 ----------
cols = st.columns([1.7, 0.5, 1.3, 1.1, 1.1, 1.1, 0.9, 0.7, 0.65, 0.65])
headers = ["货号", "图片", "商品分类", "发货金额(¥)", "退货金额(¥)", "净销售金额(¥)", "退款率", "商品标签", "详情", "趋势"]
for c, h in zip(cols, headers):
    c.markdown(f"**{h}**")

for idx, row in page_df.iterrows():
    c1, c2, c3, c4, c5, c6, c7, c8, c9, c10 = st.columns([1.7, 0.5, 1.3, 1.1, 1.1, 1.1, 0.9, 0.7, 0.65, 0.65])
    c1.write(row["货号"])
    if row.get("image_url") and pd.notna(row["image_url"]):
        c2.image(row["image_url"], width=50)
    else:
        c2.write("-")
    # 分类是普通文本，不交给 st.write 做富文本类型推断，避免中文短文本异常渲染。
    category_text = str(row["master_category"]).strip() if pd.notna(row["master_category"]) else "-"
    c3.text(category_text or "-")
    c4.write(f"{row['发货金额']:,.2f}")
    c5.write(f"{row['退货金额']:,.2f}")
    c6.write(f"{row['净销售金额']:,.2f}")
    c7.write(row["退款率"])
    c8.caption(product_tags_text(row.get("product_tags")) or "—")
    if c9.button("📊", key=f"detail_btn_{row['货号']}_{idx}"):
        style_code = row["货号"]
        detail_df = filtered[filtered["style_code"] == style_code].copy()
        if not detail_df.empty:
            shop_detail = detail_df.groupby(["_detail_type", "_detail_value"], dropna=False).agg(
                发货金额=("ship_amount", "sum"),
                退货金额=("return_amount", "sum"),
                净销售金额=("net_amount", "sum")
            ).reset_index().rename(columns={"_detail_type": "明细类型", "_detail_value": "明细对象"})
            shop_detail["退款率"] = shop_detail.apply(
                lambda r: f"{(r['退货金额']/r['发货金额']*100):.2f}%" if r['发货金额'] != 0 else "-", axis=1
            )
            st.session_state.cached_detail_data = {
                "style_code": style_code,
                "shop_detail": shop_detail,
                "detail_label": detail_label,
                "image_url": row.get("image_url"),
                "category": row.get("master_category"),
            }
        else:
            st.session_state.cached_detail_data = None
        st.session_state.show_trend_dialog = False
        st.session_state.trend_style_code = None
        st.session_state.trend_data = None
        st.session_state.trend_clicked = False
        st.session_state.dialog_style_code = style_code
        st.session_state.show_dialog = True
        st.session_state.detail_clicked = True
        st.rerun()
    if c10.button("📈", key=f"trend_btn_{row['货号']}_{idx}"):
        style_code = row["货号"]
        trend_data = filtered[filtered["style_code"] == style_code].copy()
        if not trend_data.empty:
            trend_data["_detail_series"] = trend_data["_detail_type"].astype(str) + "｜" + trend_data["_detail_value"].astype(str)
            daily = trend_data.groupby(["sale_date", "_detail_series"], dropna=False).agg(
                ship_amount=("ship_amount", "sum"),
                return_amount=("return_amount", "sum"),
                net_amount=("net_amount", "sum")
            ).reset_index().sort_values("sale_date")
            st.session_state.trend_data = daily
            st.session_state.trend_dimension = {"field": "_detail_series", "label": detail_label}
        else:
            st.session_state.trend_data = None
        st.session_state.show_dialog = False
        st.session_state.dialog_style_code = None
        st.session_state.cached_detail_data = None
        st.session_state.detail_clicked = False
        st.session_state.trend_style_code = style_code
        st.session_state.show_trend_dialog = True
        st.session_state.trend_clicked = True
        st.rerun()
# ---------- 详情对话框 ----------
if st.session_state.show_dialog and st.session_state.dialog_style_code:
    style_code = st.session_state.dialog_style_code
    cached = st.session_state.cached_detail_data
    @st.dialog(f"📋 货号 {style_code} 销售明细", width="large", dismissible=False)
    def show_style_detail():
        if cached and cached.get("style_code") == style_code:
            shop_detail = cached["shop_detail"]
            image_col, info_col = st.columns([1, 3])
            with image_col:
                if cached.get("image_url") and pd.notna(cached.get("image_url")):
                    st.image(cached["image_url"], use_container_width=True)
                else:
                    st.info("暂无商品图片")
            with info_col:
                st.markdown(f"### {style_code}")
                st.caption(f"商品分类：{cached.get('category') or '未维护'}")
                st.markdown(f"#### 按{cached.get('detail_label')}查看销售明细")
            if not shop_detail.empty:
                st.dataframe(shop_detail, column_config={
                    "明细类型": st.column_config.TextColumn("明细类型"),
                    "明细对象": st.column_config.TextColumn("明细对象"),
                    "发货金额": st.column_config.NumberColumn("发货金额(¥)", format="%.2f"),
                    "退货金额": st.column_config.NumberColumn("退货金额(¥)", format="%.2f"),
                    "净销售金额": st.column_config.NumberColumn("净销售金额(¥)", format="%.2f"),
                    "退款率": st.column_config.TextColumn("退款率")
                }, hide_index=True, use_container_width=True)
            else:
                st.info("无有效数据")
        else:
            st.info("该货号无销售数据")
        if st.button("关闭", key="close_dialog"):
            st.session_state.show_dialog = False
            st.session_state.dialog_style_code = None
            st.session_state.cached_detail_data = None
            st.session_state.detail_clicked = False
            st.rerun()
    show_style_detail()

# ---------- 趋势对话框 ----------
if st.session_state.show_trend_dialog and st.session_state.trend_style_code:
    style_code = st.session_state.trend_style_code
    @st.dialog(f"📈 货号 {style_code} 销售趋势", width="large", dismissible=False)
    def show_trend():
        st.subheader(f"货号：{style_code}")
        daily = st.session_state.trend_data
        if daily is None or daily.empty:
            st.info("当前筛选条件下该货号无销售数据")
        else:
            show_ship = st.checkbox("显示发货金额", value=True, key="trend_ship")
            show_return = st.checkbox("显示退货金额", value=True, key="trend_return")
            show_net = st.checkbox("显示净销售金额", value=True, key="trend_net")
            trend_dimension = st.session_state.get("trend_dimension", {"field": None, "label": "明细"})
            dimension_field = trend_dimension.get("field")
            split_lines = st.checkbox(f"按{trend_dimension.get('label')}拆分趋势", value=True, key="trend_split")
            lines = []
            if split_lines and dimension_field in daily.columns:
                for dimension_value, dimension_df in daily.groupby(dimension_field, dropna=False):
                    if show_net:
                        lines.append(go.Scatter(x=dimension_df["sale_date"], y=dimension_df["net_amount"], name=f"{dimension_value}·净销售", mode="lines+markers"))
            else:
                total_daily = daily.groupby("sale_date", as_index=False)[["ship_amount", "return_amount", "net_amount"]].sum()
                if show_ship:
                    lines.append(go.Scatter(x=total_daily["sale_date"], y=total_daily["ship_amount"], name="发货金额", mode="lines+markers"))
                if show_return:
                    lines.append(go.Scatter(x=total_daily["sale_date"], y=total_daily["return_amount"], name="退货金额", mode="lines+markers"))
                if show_net:
                    lines.append(go.Scatter(x=total_daily["sale_date"], y=total_daily["net_amount"], name="净销售金额", mode="lines+markers"))
            if not lines:
                st.info("请至少勾选一项")
            else:
                fig = go.Figure(data=lines)
                fig.update_layout(title="每日销售趋势", xaxis_title="日期", yaxis_title="金额(¥)", legend_title="指标", hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)
        if st.button("关闭", key="close_trend"):
            st.session_state.show_trend_dialog = False
            st.session_state.trend_style_code = None
            st.session_state.trend_data = None
            st.session_state.trend_clicked = False
            st.rerun()
    show_trend()
