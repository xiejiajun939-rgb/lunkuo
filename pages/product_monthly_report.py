import io
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from core.db import get_sales_date_range, load_product_master, load_product_sales_cube
from core.theme import page_header
from core.utils import clear_cache_on_page_change


st.set_page_config(page_title="商品月度复盘", layout="wide")
clear_cache_on_page_change("product_monthly_report")
page_header("商品月度复盘", "从经营结果下钻到商品、店铺与下月动作", "MONTHLY PRODUCT REVIEW", "小店运营")

st.markdown("""
<style>
.report-note {padding:12px 16px;background:#fff7ed;border-left:4px solid #f97316;border-radius:8px;color:#9a3412}
.report-conclusion {padding:12px 16px;background:#f8fafc;border-left:4px solid #0f766e;border-radius:8px;margin:6px 0}
</style>
""", unsafe_allow_html=True)


def _prepare(frame):
    if frame.empty:
        return frame
    result = frame.copy()
    result["style_code"] = result["style_code"].fillna("").astype(str).str.strip().str.upper()
    for column in ["ship_amount", "return_amount", "net_amount"]:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
    result["platform_name"] = np.where(
        result["shop_name"].fillna("").astype(str).str.startswith("视频号"), "视频号", "抖音"
    )
    master = load_product_master().copy()
    if not master.empty and "style_code" in master.columns:
        master["style_code"] = master["style_code"].fillna("").astype(str).str.strip().str.upper()
        attribute_sources = {
            "category": ["category", "product_category"],
            "product_year": ["product_year", "year"],
            "season": ["season"],
            "master_brand": ["brand"],
        }
        for target, candidates in attribute_sources.items():
            source = next((name for name in candidates if name in master.columns), None)
            master[target] = (
                master[source].fillna("").astype(str).str.strip()
                if source else ""
            )
        master = master[master["style_code"] != ""].drop_duplicates("style_code", keep="last")
        attributes = master[["style_code", "category", "product_year", "season", "master_brand"]]
        result = result.merge(attributes, on="style_code", how="left")
        for column in ["category", "product_year", "season"]:
            result[column] = result[column].replace("", np.nan).fillna("未维护")
        result["brand"] = result["master_brand"].replace("", np.nan).combine_first(
            result.get("brand", pd.Series(index=result.index, dtype="object"))
        ).fillna("未维护")
        result = result.drop(columns=["master_brand"])
    else:
        result["category"] = "未维护"
        result["product_year"] = "未维护"
        result["season"] = "未维护"
        if "brand" not in result.columns:
            result["brand"] = "未维护"
    return result


def _summary(frame):
    ship = frame["ship_amount"].sum() if not frame.empty else 0
    returned = frame["return_amount"].sum() if not frame.empty else 0
    net = frame["net_amount"].sum() if not frame.empty else 0
    return {
        "ship": ship,
        "return": returned,
        "net": net,
        "sell_through": net / ship if ship else 0,
        "styles": frame["style_code"].nunique() if not frame.empty else 0,
        "shops": frame["shop_name"].nunique() if not frame.empty else 0,
    }


min_date, max_date = get_sales_date_range("_all")
if min_date is None or max_date is None:
    st.warning("暂无销售数据。")
    st.stop()

default_start = max(min_date, max_date.replace(day=1))
date_col1, date_col2, date_col3 = st.columns([1, 1, 2])
with date_col1:
    start_date = st.date_input("开始日期", default_start, min_value=min_date, max_value=max_date)
with date_col2:
    end_date = st.date_input("结束日期", max_date, min_value=min_date, max_value=max_date)
with date_col3:
    st.info("选择日期后自动生成；上期对比采用紧邻当前区间、天数相同的上一周期。")
if start_date > end_date:
    st.error("开始日期不能晚于结束日期。")
    st.stop()

period_days = (end_date - start_date).days + 1
previous_end = start_date - timedelta(days=1)
previous_start = max(min_date, previous_end - timedelta(days=period_days - 1))

with st.spinner("正在生成商品经营复盘..."):
    current = _prepare(load_product_sales_cube(start_date, end_date, department="小店运营"))
    previous = _prepare(load_product_sales_cube(previous_start, previous_end, department="小店运营"))
if current.empty:
    st.warning("当前日期范围没有小店运营商品数据。")
    st.stop()

cur = _summary(current)
prev = _summary(previous)

def delta(current_value, previous_value):
    return (current_value / previous_value - 1) if previous_value else None

kpis = st.columns(5)
kpis[0].metric("实销金额", f"¥{cur['net']:,.2f}", f"{delta(cur['net'], prev['net']):+.1%}" if prev["net"] else None)
kpis[1].metric("发货金额", f"¥{cur['ship']:,.2f}", f"{delta(cur['ship'], prev['ship']):+.1%}" if prev["ship"] else None)
kpis[2].metric("退货金额", f"¥{cur['return']:,.2f}", f"{delta(cur['return'], prev['return']):+.1%}" if prev["return"] else None, delta_color="inverse")
kpis[3].metric("实销率", f"{cur['sell_through']:.1%}", f"{cur['sell_through']-prev['sell_through']:+.1%}" if prev["ship"] else None)
kpis[4].metric("动销货号", f"{cur['styles']:,}", f"{cur['styles']-prev['styles']:+,}" if not previous.empty else None)

daily = current.groupby("sale_date", as_index=False)[["ship_amount", "return_amount", "net_amount"]].sum()
daily = daily.rename(columns={"sale_date": "日期", "ship_amount": "发货金额", "return_amount": "退货金额", "net_amount": "实销金额"})
fig_daily = px.line(daily, x="日期", y=["发货金额", "退货金额", "实销金额"], markers=True, title="每日发货、退货与实销趋势")
fig_daily.update_layout(height=380, yaxis_title="金额（元）", legend_title="指标", hovermode="x unified")
st.plotly_chart(fig_daily, use_container_width=True)

tab_overview, tab_shops, tab_products, tab_structure, tab_actions = st.tabs([
    "经营结论", "平台与店铺", "商品表现", "商品结构", "风险与行动"
])

with tab_overview:
    net_change = delta(cur["net"], prev["net"])
    return_change = delta(cur["return"], prev["return"])
    platform = current.groupby("platform_name", as_index=False)[["ship_amount", "return_amount", "net_amount"]].sum().sort_values("net_amount", ascending=False)
    top_platform = platform.iloc[0]
    conclusions = [
        f"当前实销 ¥{cur['net']:,.2f}" + (f"，较上期{'增长' if net_change >= 0 else '下降'} {abs(net_change):.1%}" if net_change is not None else ""),
        f"退货金额 ¥{cur['return']:,.2f}" + (f"，较上期{'增长' if return_change >= 0 else '下降'} {abs(return_change):.1%}" if return_change is not None else ""),
        f"{top_platform['platform_name']}贡献实销 ¥{top_platform['net_amount']:,.2f}，占团队实销 {top_platform['net_amount']/cur['net']:.1%}" if cur["net"] else "当前实销为0",
        f"共 {cur['shops']} 家店铺、{cur['styles']} 个动销货号，当前实销率 {cur['sell_through']:.1%}",
    ]
    for text in conclusions:
        st.markdown(f"<div class='report-conclusion'>{text}</div>", unsafe_allow_html=True)

with tab_shops:
    platform = current.groupby("platform_name", as_index=False)[["ship_amount", "return_amount", "net_amount"]].sum()
    platform["实销占比"] = platform["net_amount"] / cur["net"] if cur["net"] else 0
    c1, c2 = st.columns([1, 2])
    with c1:
        fig_platform = px.pie(platform, names="platform_name", values="net_amount", hole=.55, title="平台实销结构")
        st.plotly_chart(fig_platform, use_container_width=True)
    shop = current.groupby(["platform_name", "shop_name"], as_index=False)[["ship_amount", "return_amount", "net_amount"]].sum()
    shop["退货率"] = np.where(shop["ship_amount"] != 0, shop["return_amount"] / shop["ship_amount"], 0)
    shop["实销贡献"] = shop["net_amount"] / cur["net"] if cur["net"] else 0
    shop = shop.sort_values("net_amount", ascending=False)
    with c2:
        fig_shop = px.bar(shop.head(12), x="shop_name", y="net_amount", color="platform_name", title="店铺实销贡献")
        fig_shop.update_layout(height=360, xaxis_title="店铺", yaxis_title="实销金额（元）")
        st.plotly_chart(fig_shop, use_container_width=True)
    st.dataframe(shop.rename(columns={"platform_name":"平台","shop_name":"店铺","ship_amount":"发货金额","return_amount":"退货金额","net_amount":"实销金额"}), hide_index=True, use_container_width=True,
        column_config={"发货金额":st.column_config.NumberColumn(format="¥%.2f"),"退货金额":st.column_config.NumberColumn(format="¥%.2f"),"实销金额":st.column_config.NumberColumn(format="¥%.2f"),"退货率":st.column_config.NumberColumn(format="percent"),"实销贡献":st.column_config.NumberColumn(format="percent")})

product = current.groupby("style_code", as_index=False).agg(
    品牌=("brand", "last"), 年份=("product_year", "last"), 季节=("season", "last"), 品类=("category", "last"),
    发货金额=("ship_amount", "sum"), 退货金额=("return_amount", "sum"), 实销金额=("net_amount", "sum")
)
product["退货率"] = np.where(product["发货金额"] != 0, product["退货金额"] / product["发货金额"], 0)
product["实销占比"] = product["实销金额"] / cur["net"] if cur["net"] else 0
product = product.sort_values("实销金额", ascending=False)

with tab_products:
    fig_top = px.bar(product.head(15), x="style_code", y="实销金额", color="季节", hover_data=["品类", "发货金额", "退货率"], title="实销金额 TOP15 货号")
    fig_top.update_layout(height=380, xaxis_title="货号", yaxis_title="实销金额（元）")
    st.plotly_chart(fig_top, use_container_width=True)
    st.dataframe(product, hide_index=True, use_container_width=True, column_config={"发货金额":st.column_config.NumberColumn(format="¥%.2f"),"退货金额":st.column_config.NumberColumn(format="¥%.2f"),"实销金额":st.column_config.NumberColumn(format="¥%.2f"),"退货率":st.column_config.NumberColumn(format="percent"),"实销占比":st.column_config.NumberColumn(format="percent")})

with tab_structure:
    dimension = st.radio("结构维度", ["品类", "年份", "季节", "品牌"], horizontal=True)
    structure = product.groupby(dimension, dropna=False, as_index=False).agg(商品数=("style_code", "nunique"), 发货金额=("发货金额", "sum"), 退货金额=("退货金额", "sum"), 实销金额=("实销金额", "sum"))
    structure["退货率"] = np.where(structure["发货金额"] != 0, structure["退货金额"] / structure["发货金额"], 0)
    structure = structure.sort_values("实销金额", ascending=False)
    fig_structure = px.bar(structure.head(15), x=dimension, y="实销金额", color="退货率", color_continuous_scale="RdYlGn_r", title=f"{dimension}实销结构")
    st.plotly_chart(fig_structure, use_container_width=True)
    st.dataframe(structure, hide_index=True, use_container_width=True, column_config={"发货金额":st.column_config.NumberColumn(format="¥%.2f"),"退货金额":st.column_config.NumberColumn(format="¥%.2f"),"实销金额":st.column_config.NumberColumn(format="¥%.2f"),"退货率":st.column_config.NumberColumn(format="percent")})

with tab_actions:
    risk = product[(product["发货金额"] >= 10000) & (product["退货率"] >= .7)].sort_values("发货金额", ascending=False)
    negative = product[product["实销金额"] < 0].sort_values("实销金额")
    opportunity = product[(product["季节"] == "秋") & (product["实销金额"] > 0)].sort_values("实销金额", ascending=False)
    r1, r2, r3 = st.columns(3)
    r1.metric("高发货高退货货号", len(risk))
    r2.metric("负实销货号", len(negative))
    r3.metric("秋款正实销货号", len(opportunity))
    st.markdown("#### 重点风险商品")
    st.dataframe(risk.head(30), hide_index=True, use_container_width=True)
    st.markdown("#### 秋款机会商品")
    st.dataframe(opportunity.head(30), hide_index=True, use_container_width=True)
    st.markdown("<div class='report-note'>建议动作：先复核高发货高退货商品的尺码、版型和面料描述；再从秋款高实销、高实销率货号中筛选主推及首单礼金候选。</div>", unsafe_allow_html=True)

output = io.BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    product.to_excel(writer, index=False, sheet_name="商品表现")
    shop.to_excel(writer, index=False, sheet_name="店铺经营")
    daily.to_excel(writer, index=False, sheet_name="每日趋势")
st.download_button("📥 下载当前日期范围分析数据", output.getvalue(), f"小店运营商品月度复盘_{start_date}_{end_date}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
