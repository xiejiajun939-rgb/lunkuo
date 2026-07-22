# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import io
import re
import numpy as np

# ========== 导入公共模块 ==========
from core.db import load_product_sales, load_product_master, init_supabase
from core.utils import date_quick_buttons, parse_product_code, extract_anchor
from core.ai import get_ai_summary

# ========== 页面配置 ==========
st.set_page_config(page_title="商品分析", layout="wide")

# ========== 初始化 session_state（仅本页面需要的） ==========
if "table_suffix" not in st.session_state:
    st.session_state.table_suffix = ""   # 默认非直播
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

# ========== 侧边栏：数据源切换 ==========
with st.sidebar:
    st.header("数据源")
    source = st.radio(
        "选择数据源",
        ["非直播数据", "全部数据"],
        index=0 if st.session_state.table_suffix == "" else 1,
        key="source_radio"
    )
    new_suffix = "" if source == "非直播数据" else "_all"
    if new_suffix != st.session_state.table_suffix:
        st.session_state.table_suffix = new_suffix
        st.cache_data.clear()
        st.rerun()
    
    st.markdown("---")
    if st.button("🔄 刷新数据", key="refresh_analysis"):
        st.session_state.show_dialog = False
        st.session_state.dialog_style_code = None
        st.session_state.cached_detail_data = None
        st.session_state.detail_clicked = False
        st.session_state.show_trend_dialog = False
        st.session_state.trend_style_code = None
        st.session_state.trend_data = None
        st.session_state.trend_clicked = False
        st.cache_data.clear()
        st.rerun()

# ========== 主体 ==========
st.title("📦 商品分析")
st.markdown("---")

# ---------- 加载数据 ----------
with st.spinner("正在加载商品销售数据，请稍候..."):
    prod_df = load_product_sales(st.session_state.table_suffix)

if prod_df.empty:
    st.warning("暂无商品销售数据，请先上传订单文件。")
    st.stop()

# ---------- 预处理 ----------
if "style_code" in prod_df.columns:
    prod_df["style_code"] = prod_df["style_code"].astype(str).str.strip().str.upper()
else:
    prod_df["style_code"] = prod_df["product_code"].str[:8].str.strip().str.upper()

if st.session_state.table_suffix in ["_live", "_all"]:
    if "anchor" not in prod_df.columns:
        prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)

min_date = prod_df["sale_date"].min().date()
max_date = prod_df["sale_date"].max().date()

# ---------- 日期选择 ----------
date_quick_buttons("prod_start_final", "prod_end_final",
                   default_start=min_date,
                   default_end=max_date,
                   min_date=min_date,
                   max_date=max_date)
start_date = st.session_state.get("prod_start_final", min_date)
end_date = st.session_state.get("prod_end_final", max_date)

# ---------- 筛选条件 ----------
st.subheader("🔍 筛选条件")
col_platform, col_shop = st.columns(2)
with col_platform:
    platform_options = ["全部", "抖音", "视频号"]
    selected_platform = st.selectbox("平台", platform_options, key="platform_filter_final")
with col_shop:
    all_shops_all = prod_df["shop_name"].unique()
    if selected_platform == "抖音":
        shop_options = [shop for shop in all_shops_all if "抖音" in shop]
    elif selected_platform == "视频号":
        shop_options = [shop for shop in all_shops_all if "视频号" in shop]
    else:
        shop_options = list(all_shops_all)
    selected_shops = st.multiselect("店铺（可多选）", options=sorted(shop_options), default=[], key="shop_filter_final")

col_code, col_brand = st.columns(2)
with col_code:
    style_codes_input = st.text_input("货号筛选（多个用英文逗号分隔）", placeholder="例如: L262Y050, G262Y030", key="style_code_filter_final")
with col_brand:
    brands_all = ["全部"] + sorted(prod_df["brand"].dropna().unique())
    selected_brand = st.selectbox("品牌", brands_all, key="brand_filter_final")

coupon_filter_options = ["全部", "仅首单礼金", "非首单礼金"]
selected_coupon_filter = st.selectbox("是否首单礼金款式", coupon_filter_options, key="coupon_filter_final")

selected_anchors = []
if st.session_state.table_suffix in ["_live", "_all"]:
    if "anchor" not in prod_df.columns:
        prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)
    all_anchors = prod_df["anchor"].dropna().unique().tolist()
    if all_anchors:
        selected_anchors = st.multiselect("主播（可多选）", options=sorted(all_anchors), default=[], key="anchor_filter_final")
    else:
        st.info("当前数据中未识别到任何主播信息，请检查备注字段是否包含“主播：xxx”格式。")

# ---------- 应用筛选 ----------
mask_date = (prod_df["sale_date"] >= pd.to_datetime(start_date)) & (prod_df["sale_date"] <= pd.to_datetime(end_date))
filtered = prod_df[mask_date].copy()

if selected_platform == "抖音":
    filtered = filtered[filtered["shop_name"].str.contains("抖音", case=False, na=False)]
elif selected_platform == "视频号":
    filtered = filtered[filtered["shop_name"].str.contains("视频号", case=False, na=False)]
if selected_shops:
    filtered = filtered[filtered["shop_name"].isin(selected_shops)]
if style_codes_input.strip():
    target_codes = [code.strip().upper() for code in style_codes_input.split(",") if code.strip()]
    if target_codes:
        filtered = filtered[filtered["style_code"].isin(target_codes)]
if selected_brand != "全部":
    filtered = filtered[filtered["brand"] == selected_brand]
if selected_anchors:
    filtered = filtered[filtered["anchor"].isin(selected_anchors)]

master_df = load_product_master()
coupon_map = {}
if not master_df.empty and "style_code" in master_df.columns:
    master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
    coupon_map = master_df.set_index("style_code")["has_newbie_coupon"].to_dict()
filtered["has_newbie_coupon"] = filtered["style_code"].map(coupon_map).fillna(False)
if selected_coupon_filter == "仅首单礼金":
    filtered = filtered[filtered["has_newbie_coupon"] == True]
elif selected_coupon_filter == "非首单礼金":
    filtered = filtered[filtered["has_newbie_coupon"] == False]

if filtered.empty:
    st.warning("所选条件下无销售数据")
    st.stop()

# ---------- 聚合 ----------
grouped = filtered.groupby("style_code").agg(
    发货金额=("ship_amount", "sum"),
    退货金额=("return_amount", "sum"),
    净销售金额=("net_amount", "sum")
).reset_index().rename(columns={"style_code": "货号"})

if not master_df.empty and "style_code" in master_df.columns:
    master_df = master_df.drop_duplicates(subset="style_code", keep="first")
    img_map = master_df.set_index("style_code")["image_url"].to_dict()
    cat_map = master_df.set_index("style_code")["category"].to_dict()
    coupon_map = master_df.set_index("style_code")["has_newbie_coupon"].to_dict()
    grouped["image_url"] = grouped["货号"].map(img_map).fillna(None)
    grouped["has_newbie_coupon"] = grouped["货号"].map(coupon_map).fillna(False)
    if "master_category" not in filtered.columns:
        filtered["master_category"] = None
    cat_series = filtered.groupby("style_code")["master_category"].first()
    grouped["master_category"] = grouped["货号"].map(cat_series).fillna(grouped["货号"].map(cat_map))
else:
    grouped["master_category"] = None
    grouped["image_url"] = None
    grouped["has_newbie_coupon"] = False

grouped["退款率"] = np.where(
    grouped["发货金额"] != 0,
    ((grouped["退货金额"] / grouped["发货金额"].replace(0, np.nan)) * 100).map("{:.2f}%".format),
    "-"
)

# ---------- 排序与分页 ----------
st.markdown("#### 货号汇总表")
col_sort1, col_sort2, col_sort3 = st.columns([1, 1, 2])
with col_sort1:
    sort_options = ["货号", "发货金额", "退货金额", "净销售金额", "退款率"]
    selected_sort = st.selectbox("排序字段", sort_options, index=sort_options.index(st.session_state.sort_by) if st.session_state.sort_by in sort_options else 3, key="sort_by_selector")
with col_sort2:
    sort_order = st.radio("排序顺序", ["降序", "升序"], horizontal=True, index=0 if not st.session_state.sort_ascending else 1, key="sort_order_radio")
with col_sort3:
    page_size_options = [10, 20, 50, 100]
    selected_page_size = st.selectbox(
        "每页显示行数",
        options=page_size_options,
        index=page_size_options.index(st.session_state.product_page_size),
        key="page_size_selector"
    )
    if selected_page_size != st.session_state.product_page_size:
        st.session_state.product_page_size = selected_page_size
        st.session_state.product_page_num = 1
        st.rerun()

if selected_sort != st.session_state.sort_by or (sort_order == "降序" and st.session_state.sort_ascending) or (sort_order == "升序" and not st.session_state.sort_ascending):
    st.session_state.show_dialog = False
    st.session_state.dialog_style_code = None
    st.session_state.cached_detail_data = None
    st.session_state.detail_clicked = False
    st.session_state.show_trend_dialog = False
    st.session_state.trend_style_code = None
    st.session_state.trend_data = None
    st.session_state.trend_clicked = False
    st.session_state.sort_by = selected_sort
    st.session_state.sort_ascending = (sort_order == "升序")
    st.session_state.product_page_num = 1
    st.rerun()

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

page_size = st.session_state.product_page_size
total_rows = len(grouped)
total_pages = (total_rows + page_size - 1) // page_size if total_rows > 0 else 1
if st.session_state.product_page_num > total_pages:
    st.session_state.product_page_num = 1

col_prev, col_page, col_next, col_export = st.columns([1, 2, 1, 1.5])
with col_prev:
    if st.button("◀ 上一页", key="product_prev_page"):
        st.session_state.show_dialog = False
        st.session_state.dialog_style_code = None
        st.session_state.cached_detail_data = None
        st.session_state.detail_clicked = False
        st.session_state.show_trend_dialog = False
        st.session_state.trend_style_code = None
        st.session_state.trend_data = None
        st.session_state.trend_clicked = False
        if st.session_state.product_page_num > 1:
            st.session_state.product_page_num -= 1
            st.rerun()
with col_page:
    st.write(f"第 {st.session_state.product_page_num} / {total_pages} 页")
with col_next:
    if st.button("下一页 ▶", key="product_next_page"):
        st.session_state.show_dialog = False
        st.session_state.dialog_style_code = None
        st.session_state.cached_detail_data = None
        st.session_state.detail_clicked = False
        st.session_state.show_trend_dialog = False
        st.session_state.trend_style_code = None
        st.session_state.trend_data = None
        st.session_state.trend_clicked = False
        if st.session_state.product_page_num < total_pages:
            st.session_state.product_page_num += 1
            st.rerun()
with col_export:
    is_live_or_all = st.session_state.table_suffix in ["_live", "_all"]
    if is_live_or_all:
        detail_type_name = "明细（货号+主播）"
    else:
        detail_type_name = "明细（货号+店铺）"
    
    export_type = st.radio(
        "导出类型",
        ["汇总（货号级别）", detail_type_name],
        horizontal=True,
        key="export_type_radio"
    )
    
    if st.button("📥 下载数据", key="export_filtered_data"):
        if export_type == "汇总（货号级别）":
            export_df = grouped.copy()
            if "image_url" in export_df.columns:
                export_df = export_df.drop(columns=["image_url"])
            cols_order = ["货号", "master_category", "发货金额", "退货金额", "净销售金额", "退款率", "has_newbie_coupon"]
            export_cols = [c for c in cols_order if c in export_df.columns]
            export_df = export_df[export_cols]
            export_df.rename(columns={
                "master_category": "商品分类",
                "has_newbie_coupon": "是否新人礼金"
            }, inplace=True)
            export_df["是否新人礼金"] = export_df["是否新人礼金"].map({True: "是", False: "否"})
            sheet_name = "货号汇总"
            file_suffix = "货号汇总"
        else:
            if is_live_or_all:
                group_col = "anchor"
                group_name = "主播"
            else:
                group_col = "shop_name"
                group_name = "店铺"
            
            if group_col not in filtered.columns:
                st.error(f"数据中缺少 {group_name} 信息，无法导出明细。")
                st.stop()
            
            detail_agg = filtered.groupby(["style_code", group_col]).agg(
                明细发货金额=("ship_amount", "sum"),
                明细退货金额=("return_amount", "sum"),
                明细净销售金额=("net_amount", "sum")
            ).reset_index()
            
            detail_agg["明细退款率"] = np.where(
                detail_agg["明细发货金额"] != 0,
                (detail_agg["明细退货金额"] / detail_agg["明细发货金额"] * 100).map("{:.2f}%".format),
                "-"
            )
            
            master_cols = grouped[["货号", "master_category", "发货金额", "退货金额", "净销售金额", "退款率", "has_newbie_coupon"]].copy()
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
                "has_newbie_coupon": "是否新人礼金"
            }, inplace=True)
            export_df["是否新人礼金"] = export_df["是否新人礼金"].map({True: "是", False: "否"})
            
            final_cols = [
                "货号", "商品分类", "发货金额", "退货金额", "净销售金额", "退款率", "是否新人礼金",
                group_name, "明细发货金额", "明细退货金额", "明细净销售金额", "明细退款率"
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
start_idx = (st.session_state.product_page_num - 1) * page_size
end_idx = min(start_idx + page_size, total_rows)
page_df = grouped.iloc[start_idx:end_idx]

cols = st.columns([2, 0.5, 1.5, 1.2, 1.2, 1.2, 1, 0.8, 0.8, 0.8])
headers = ["货号", "图片", "商品分类", "发货金额(¥)", "退货金额(¥)", "净销售金额(¥)", "退款率", "新人礼金", "详情", "趋势"]
for col, header in zip(cols, headers):
    col.markdown(f"**{header}**")

for idx, row in page_df.iterrows():
    col1, col2, col3, col4, col5, col6, col7, col8, col9, col10 = st.columns([2, 0.5, 1.5, 1.2, 1.2, 1.2, 1, 0.8, 0.8, 0.8])
    col1.write(row["货号"])
    if row.get("image_url") and pd.notna(row["image_url"]):
        col2.image(row["image_url"], width=50)
    else:
        col2.write("-")
    col3.write(row["master_category"] if pd.notna(row["master_category"]) else "-")
    col4.write(f"{row['发货金额']:,.2f}")
    col5.write(f"{row['退货金额']:,.2f}")
    col6.write(f"{row['净销售金额']:,.2f}")
    col7.write(row["退款率"])
    col8.write("✅" if row.get("has_newbie_coupon") else "❌")
    if col9.button("📊", key=f"detail_btn_{row['货号']}_{idx}"):
        style_code = row["货号"]
        detail_df = filtered[filtered["style_code"] == style_code].copy()
        if not detail_df.empty:
            suffix = st.session_state.table_suffix
            def extract_anchor_fn(remark):
                match = re.search(r'主播[：:]([^_]+)', remark)
                return match.group(1).strip() if match else None
            if suffix in ["_live", "_all"]:
                detail_df["anchor"] = detail_df["remark"].apply(extract_anchor_fn)
                detail_df = detail_df[detail_df["anchor"].notna()]
                if not detail_df.empty:
                    shop_detail = detail_df.groupby("anchor").agg(
                        发货金额=("ship_amount", "sum"),
                        退货金额=("return_amount", "sum"),
                        净销售金额=("net_amount", "sum")
                    ).reset_index().rename(columns={"anchor": "主播"})
                    shop_detail["退款率"] = shop_detail.apply(
                        lambda r: f"{(r['退货金额']/r['发货金额']*100):.2f}%" if r['发货金额']!=0 else "-", axis=1
                    )
                    detail_type = "anchor"
                else:
                    shop_detail = pd.DataFrame()
                    detail_type = "anchor"
            else:
                shop_detail = detail_df.groupby("shop_name").agg(
                    发货金额=("ship_amount", "sum"),
                    退货金额=("return_amount", "sum"),
                    净销售金额=("net_amount", "sum")
                ).reset_index()
                shop_detail["退款率"] = shop_detail.apply(
                    lambda r: f"{(r['退货金额']/r['发货金额']*100):.2f}%" if r['发货金额']!=0 else "-", axis=1
                )
                detail_type = "shop"
            st.session_state.cached_detail_data = {"style_code": style_code, "shop_detail": shop_detail, "type": detail_type}
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
    if col10.button("📈", key=f"trend_btn_{row['货号']}_{idx}"):
        style_code = row["货号"]
        trend_data = filtered[filtered["style_code"] == style_code].copy()
        if not trend_data.empty:
            daily = trend_data.groupby("sale_date").agg(
                ship_amount=("ship_amount", "sum"),
                return_amount=("return_amount", "sum"),
                net_amount=("net_amount", "sum")
            ).reset_index().sort_values("sale_date")
            st.session_state.trend_data = daily
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
    @st.dialog(f"📋 货号 {style_code} 销售明细", width="large")
    def show_style_detail():
        if cached and cached.get("style_code") == style_code:
            shop_detail = cached["shop_detail"]
            if cached.get("type") == "anchor":
                st.markdown("#### 主播销售汇总")
            else:
                st.markdown("#### 店铺销售汇总")
            if not shop_detail.empty:
                st.dataframe(shop_detail, column_config={
                    "主播" if cached.get("type") == "anchor" else "shop_name": st.column_config.TextColumn("主播" if cached.get("type") == "anchor" else "店铺"),
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
    @st.dialog(f"📈 货号 {style_code} 销售趋势", width="large")
    def show_trend():
        st.subheader(f"货号：{style_code}")
        daily = st.session_state.trend_data
        if daily is None or daily.empty:
            st.info("当前筛选条件下该货号无销售数据")
        else:
            show_ship = st.checkbox("显示发货金额", value=True, key="trend_ship")
            show_return = st.checkbox("显示退货金额", value=True, key="trend_return")
            show_net = st.checkbox("显示净销售金额", value=True, key="trend_net")
            lines = []
            if show_ship and "ship_amount" in daily.columns:
                lines.append(go.Scatter(x=daily["sale_date"], y=daily["ship_amount"], name="发货金额", mode="lines+markers"))
            if show_return and "return_amount" in daily.columns:
                lines.append(go.Scatter(x=daily["sale_date"], y=daily["return_amount"], name="退货金额", mode="lines+markers"))
            if show_net and "net_amount" in daily.columns:
                lines.append(go.Scatter(x=daily["sale_date"], y=daily["net_amount"], name="净销售金额", mode="lines+markers"))
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
