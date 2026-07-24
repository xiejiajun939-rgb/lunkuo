# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import io
import re
import numpy as np

from core.db import load_product_sales, load_product_master
from core.utils import date_quick_buttons, extract_anchor
from core.ai import get_ai_summary

st.set_page_config(page_title="商品分析", layout="wide")

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

st.title("📦 商品分析")

# ---------- 数据源选择（主体顶部） ----------
col1, col2 = st.columns([1, 4])
with col1:
    source = st.radio("数据源", ["非直播", "全部"], index=0 if st.session_state.table_suffix == "" else 1, key="src_radio")
    new_suffix = "" if source == "非直播" else "_all"
    if new_suffix != st.session_state.table_suffix:
        st.session_state.table_suffix = new_suffix
        st.cache_data.clear()
        st.rerun()

# ---------- 加载数据 ----------
with st.spinner("加载商品销售数据..."):
    prod_df = load_product_sales(st.session_state.table_suffix)

if prod_df.empty:
    st.warning("暂无数据，请先上传订单文件。")
    st.stop()

# ---------- 预处理 ----------
if "style_code" in prod_df.columns:
    prod_df["style_code"] = prod_df["style_code"].astype(str).str.strip().str.upper()
else:
    prod_df["style_code"] = prod_df["product_code"].str[:8].str.strip().str.upper()

if st.session_state.table_suffix in ["_live", "_all"] and "anchor" not in prod_df.columns:
    prod_df["anchor"] = prod_df["remark"].astype(str).apply(extract_anchor)

min_date = prod_df["sale_date"].min().date()
max_date = prod_df["sale_date"].max().date()

# ---------- 日期选择 ----------
date_quick_buttons("prod_start", "prod_end",
                   default_start=min_date,
                   default_end=max_date,
                   min_date=min_date,
                   max_date=max_date)
start_date = st.session_state.get("prod_start", min_date)
end_date = st.session_state.get("prod_end", max_date)

# ---------- 筛选条件 ----------
st.subheader("🔍 筛选条件")
col_platform, col_shop = st.columns(2)
with col_platform:
    platform_options = ["全部", "抖音", "视频号"]
    selected_platform = st.selectbox("平台", platform_options, key="pf")
with col_shop:
    all_shops = prod_df["shop_name"].unique()
    if selected_platform == "抖音":
        shop_opts = [s for s in all_shops if "抖音" in s]
    elif selected_platform == "视频号":
        shop_opts = [s for s in all_shops if "视频号" in s]
    else:
        shop_opts = list(all_shops)
    selected_shops = st.multiselect("店铺", sorted(shop_opts), key="sf")

col_code, col_brand = st.columns(2)
with col_code:
    style_input = st.text_input("货号（逗号分隔）", placeholder="例如: L262Y050", key="sc")
with col_brand:
    brands = ["全部"] + sorted(prod_df["brand"].dropna().unique())
    selected_brand = st.selectbox("品牌", brands, key="bf")

coupon_filter = st.selectbox("是否首单礼金", ["全部", "仅首单礼金", "非首单礼金"], key="cf")

# 主播筛选（仅直播/全部数据）
selected_anchors = []
if st.session_state.table_suffix in ["_live", "_all"]:
    if "anchor" in prod_df.columns:
        anchors = sorted(prod_df["anchor"].dropna().unique())
        if anchors:
            selected_anchors = st.multiselect("主播", anchors, key="af")
        else:
            st.info("未识别到主播信息，请检查备注字段。")

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
if selected_anchors:
    filtered = filtered[filtered["anchor"].isin(selected_anchors)]

# 礼金标记
master_df = load_product_master()
coupon_map = {}
if not master_df.empty and "style_code" in master_df.columns:
    master_df["style_code"] = master_df["style_code"].astype(str).str.strip().str.upper()
    coupon_map = master_df.set_index("style_code")["has_newbie_coupon"].to_dict()
filtered["has_newbie_coupon"] = filtered["style_code"].map(coupon_map).fillna(False)
if coupon_filter == "仅首单礼金":
    filtered = filtered[filtered["has_newbie_coupon"]]
elif coupon_filter == "非首单礼金":
    filtered = filtered[~filtered["has_newbie_coupon"]]

if filtered.empty:
    st.warning("无匹配数据")
    st.stop()

# ---------- 聚合 ----------
grouped = filtered.groupby("style_code").agg(
    发货金额=("ship_amount", "sum"),
    退货金额=("return_amount", "sum"),
    净销售金额=("net_amount", "sum")
).reset_index().rename(columns={"style_code": "货号"})

# 补充图片、分类、礼金信息
if not master_df.empty and "style_code" in master_df.columns:
    master_df = master_df.drop_duplicates("style_code", keep="first")
    img_map = master_df.set_index("style_code")["image_url"].to_dict()
    cat_map = master_df.set_index("style_code")["category"].to_dict()
    grouped["image_url"] = grouped["货号"].map(img_map)
    grouped["master_category"] = grouped["货号"].map(cat_map)
    grouped["has_newbie_coupon"] = grouped["货号"].map(coupon_map).fillna(False)
else:
    grouped["image_url"] = None
    grouped["master_category"] = None
    grouped["has_newbie_coupon"] = False

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
    is_live_or_all = st.session_state.table_suffix in ["_live", "_all"]
    detail_label = "明细（货号+主播）" if is_live_or_all else "明细（货号+店铺）"
    export_type = st.radio("导出类型", ["汇总（货号级别）", detail_label], horizontal=True, key="export_type")
    if st.button("📥 下载数据", key="exp"):
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
cols = st.columns([2, 0.5, 1.5, 1.2, 1.2, 1.2, 1, 0.8, 0.8, 0.8])
headers = ["货号", "图片", "商品分类", "发货金额(¥)", "退货金额(¥)", "净销售金额(¥)", "退款率", "新人礼金", "详情", "趋势"]
for c, h in zip(cols, headers):
    c.markdown(f"**{h}**")

for idx, row in page_df.iterrows():
    c1, c2, c3, c4, c5, c6, c7, c8, c9, c10 = st.columns([2, 0.5, 1.5, 1.2, 1.2, 1.2, 1, 0.8, 0.8, 0.8])
    c1.write(row["货号"])
    if row.get("image_url") and pd.notna(row["image_url"]):
        c2.image(row["image_url"], width=50)
    else:
        c2.write("-")
    c3.write(row["master_category"] if pd.notna(row["master_category"]) else "-")
    c4.write(f"{row['发货金额']:,.2f}")
    c5.write(f"{row['退货金额']:,.2f}")
    c6.write(f"{row['净销售金额']:,.2f}")
    c7.write(row["退款率"])
    c8.write("✅" if row.get("has_newbie_coupon") else "❌")
    if c9.button("📊", key=f"detail_btn_{row['货号']}_{idx}"):
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
    if c10.button("📈", key=f"trend_btn_{row['货号']}_{idx}"):
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
    @st.dialog(f"📋 货号 {style_code} 销售明细", width="large", dismissible=False)
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
