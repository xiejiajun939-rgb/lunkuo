# -*- coding: utf-8 -*-
from datetime import date
import io

import pandas as pd
import streamlit as st

from core.db import init_supabase
from core.price_adjustments import load_douyin_org_summary
from core.utils import clear_cache_on_page_change


st.set_page_config(page_title="平台部门与阿米巴", layout="wide")
clear_cache_on_page_change("douyin_amoeba")
st.title("平台部门与阿米巴销售")
st.caption("可切换抖音、视频号；实销为发货－退货，并包含退差价。")

today = date.today()
default_start = today.replace(day=1)
col1, col2 = st.columns(2)
start_date = col1.date_input("开始日期", value=default_start, key="douyin_amoeba_start")
end_date = col2.date_input("结束日期", value=today, key="douyin_amoeba_end")
amount_label = st.radio("销售口径", ["实销", "发货金额"], horizontal=True, key="douyin_amoeba_amount_type")
platform_label = st.radio("平台", ["抖音", "视频号"], horizontal=True, key="douyin_amoeba_platform")
platform = "douyin" if platform_label == "抖音" else "wechat_channels"
if start_date > end_date:
    st.error("开始日期不能晚于结束日期")
    st.stop()

try:
    result = load_douyin_org_summary(
        init_supabase(), start_date, end_date,
        amount_type="ship" if amount_label == "发货金额" else "net",
        platform=platform,
    )
except Exception as exc:
    st.error(f"查询失败：{exc}")
    st.stop()

if result.empty:
    st.info(f"所选时间内没有{platform_label}数据")
else:
    shop_options = sorted(result["店铺"].dropna().unique().tolist())
    selected_shop = st.selectbox("店铺", ["全部店铺"] + shop_options, key="douyin_amoeba_shop")
    filtered = result if selected_shop == "全部店铺" else result[result["店铺"] == selected_shop].copy()
    total = filtered["销售额"].sum()
    st.metric(f"{platform_label}{amount_label}", f"¥{total:,.2f}")
    display = filtered.copy()
    display["销售额"] = display["销售额"].map(lambda value: f"¥{value:,.2f}")
    display["店铺内销售占比"] = display["店铺内销售占比"].map(lambda value: f"{value:.2%}")
    st.dataframe(display, use_container_width=True, hide_index=True)

    dept = filtered.groupby("部门", as_index=False)["销售额"].sum().sort_values("销售额", ascending=False)
    dept["销售占比"] = dept["销售额"] / total if total else 0
    dept["销售额"] = dept["销售额"].map(lambda value: f"¥{value:,.2f}")
    dept["销售占比"] = dept["销售占比"].map(lambda value: f"{value:.2%}")
    st.subheader("部门汇总")
    st.dataframe(dept, use_container_width=True, hide_index=True)

    export_detail = filtered.copy()
    export_dept = filtered.groupby("部门", as_index=False)["销售额"].sum().sort_values("销售额", ascending=False)
    export_dept["销售占比"] = export_dept["销售额"] / total if total else 0
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_detail.to_excel(writer, sheet_name="组织明细", index=False)
        export_dept.to_excel(writer, sheet_name="部门汇总", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = cell.font.copy(bold=True)
            for column in sheet.columns:
                width = min(max(len(str(cell.value or "")) for cell in column) + 2, 36)
                sheet.column_dimensions[column[0].column_letter].width = width
        detail_sheet = writer.book["组织明细"]
        for cell in detail_sheet["D"][1:]:
            cell.number_format = '#,##0.00'
        for cell in detail_sheet["E"][1:]:
            cell.number_format = '0.00%'
        dept_sheet = writer.book["部门汇总"]
        for cell in dept_sheet["B"][1:]:
            cell.number_format = '#,##0.00'
        for cell in dept_sheet["C"][1:]:
            cell.number_format = '0.00%'
    filename = f"{platform_label}_{amount_label}_{start_date}_{end_date}.xlsx"
    st.download_button(
        "下载当前报表（Excel）", data=output.getvalue(), file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_platform_amoeba_report",
    )
