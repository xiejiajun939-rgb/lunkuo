# -*- coding: utf-8 -*-
"""
订单业绩统计工具 - Streamlit 网页版
支持上传订单文件，自动汇总每日及累计业绩、发货退货明细，对接目标达成率
运行：streamlit run this_script.py
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
import io
import os

# ========== 页面配置 ==========
st.set_page_config(page_title="业绩统计工具", layout="wide", page_icon="📊")
st.title("📊 店铺业绩汇总分析")
st.markdown("---")

# ========== 初始化 session_state ==========
if "df_all_daily" not in st.session_state:
    st.session_state.df_all_daily = None          # 所有日期的明细（日期、店铺、当日金额、月累计）
if "df_ship_refund" not in st.session_state:
    st.session_state.df_ship_refund = None        # 发货退货明细
if "target_dict" not in st.session_state:
    st.session_state.target_dict = {}             # 店铺名称 -> 目标金额
if "target_file_name" not in st.session_state:
    st.session_state.target_file_name = None
if "order_file_name" not in st.session_state:
    st.session_state.order_file_name = None

# ========== 数据处理函数（复用桌面版逻辑） ==========
def process_order_file(uploaded_file):
    """处理上传的订单文件，返回业绩数据、发货退货数据及状态"""
    try:
        df = pd.read_excel(uploaded_file, header=1)
        required = ["日期", "金额/时间", "备注"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"表格缺少列: {col}")

        df["日期"] = pd.to_datetime(df["日期"])
        # 从备注中提取店铺名称（以下划线分隔的最后一部分）
        df["店铺名称"] = df["备注"].astype(str).str.split("_").str[-1]

        # 清洗店铺名称：去除首尾空格 + 删除“商店:”或“商店：”（中英文冒号）
        df["店铺名称"] = df["店铺名称"].str.strip()
        df["店铺名称"] = df["店铺名称"].str.replace(r'^\s*商店[：:]', '', regex=True).str.strip()

        # 过滤无效店铺名称
        df = df[df["店铺名称"].notna() & (df["店铺名称"] != "")].copy()
        if df.empty:
            raise ValueError("未提取到有效的店铺名称")

        df["金额/时间"] = pd.to_numeric(df["金额/时间"], errors="coerce")
        df = df.dropna(subset=["金额/时间"])

        # 每日汇总（按日期+店铺）
        daily = df.groupby(["日期", "店铺名称"])["金额/时间"].sum().reset_index()
        daily = daily.sort_values(["店铺名称", "日期"])
        daily["月累计金额"] = daily.groupby("店铺名称")["金额/时间"].cumsum().round(2)
        daily["当日金额"] = daily["金额/时间"].round(2)

        # 存储所有日期的明细（用于日期查询和范围累计）
        df_all = daily[["日期", "店铺名称", "当日金额", "月累计金额"]].copy()

        latest_date = daily["日期"].max()
        # 获取所有店铺的最新月累计（取每个店铺最后一条记录的月累计）
        latest_cumulative = daily.groupby("店铺名称").last().reset_index()[["店铺名称", "月累计金额"]]
        # 获取最新日有业绩的店铺
        daily_latest = daily[daily["日期"] == latest_date][["日期", "店铺名称", "当日金额"]]
        # 合并：所有店铺都有记录，无日业绩的显示当日金额=0
        daily_latest = pd.merge(latest_cumulative, daily_latest, on='店铺名称', how='left')
        daily_latest['当日金额'] = daily_latest['当日金额'].fillna(0).round(2)
        daily_latest['日期'] = daily_latest['日期'].fillna(latest_date)
        daily_latest = daily_latest[["日期", "店铺名称", "当日金额", "月累计金额"]]

        # 全月累计（按店铺汇总）
        monthly_actual = df.groupby("店铺名称")["金额/时间"].sum().reset_index()
        monthly_actual["月累计金额"] = monthly_actual["金额/时间"].round(2)
        monthly_actual = monthly_actual.sort_values("店铺名称")
        monthly_actual = monthly_actual[["店铺名称", "月累计金额"]]

        # === 处理发货退货金额（正数=发货，负数=退货取绝对值） ===
        df['发货金额'] = df['金额/时间'].clip(lower=0)
        df['退货金额'] = df['金额/时间'].clip(upper=0).abs()

        ship_refund_daily = df.groupby(["日期", "店铺名称"])[["发货金额", "退货金额"]].sum().reset_index()
        ship_refund_daily = ship_refund_daily.sort_values(["店铺名称", "日期"])
        ship_refund_daily["月累计发货"] = ship_refund_daily.groupby("店铺名称")["发货金额"].cumsum().round(2)
        ship_refund_daily["月累计退货"] = ship_refund_daily.groupby("店铺名称")["退货金额"].cumsum().round(2)
        ship_refund_daily["当日发货"] = ship_refund_daily["发货金额"].round(2)
        ship_refund_daily["当日退货"] = ship_refund_daily["退货金额"].round(2)

        # 最新日发货退货
        latest_ship_cum = ship_refund_daily.groupby("店铺名称").last().reset_index()[["店铺名称", "月累计发货", "月累计退货"]]
        latest_ship = ship_refund_daily[ship_refund_daily["日期"] == latest_date][["日期", "店铺名称", "当日发货", "当日退货"]]
        latest_ship_refund = pd.merge(latest_ship_cum, latest_ship, on='店铺名称', how='left')
        latest_ship_refund['当日发货'] = latest_ship_refund['当日发货'].fillna(0).round(2)
        latest_ship_refund['当日退货'] = latest_ship_refund['当日退货'].fillna(0).round(2)
        latest_ship_refund['日期'] = latest_ship_refund['日期'].fillna(latest_date)
        df_ship = latest_ship_refund[["日期", "店铺名称", "当日发货", "月累计发货", "当日退货", "月累计退货"]]

        return {
            "df_all": df_all,
            "daily_latest": daily_latest,
            "monthly_actual": monthly_actual,
            "df_ship": df_ship,
            "latest_date": latest_date,
            "success": True,
            "message": f"处理完成！最新日期：{latest_date.strftime('%Y-%m-%d')}，共 {len(daily_latest)} 个店铺"
        }
    except Exception as e:
        return {"success": False, "message": f"处理失败：{str(e)}"}

def load_target_file(uploaded_file):
    """加载目标文件，返回店铺-目标字典"""
    try:
        df_target = pd.read_excel(uploaded_file, header=None)
        first_cell = str(df_target.iloc[0, 0]) if len(df_target) > 0 else ""
        if "月目标" in first_cell or "目标" in first_cell:
            df_target = df_target.iloc[1:].reset_index(drop=True)
        if df_target.shape[1] < 2:
            raise ValueError("目标文件需要两列：店铺名称、目标金额")

        shop_names = df_target.iloc[:, 0].astype(str).str.strip()
        target_vals = pd.to_numeric(df_target.iloc[:, 1], errors='coerce')
        target_dict = {}
        for name, val in zip(shop_names, target_vals):
            if pd.notna(val) and name not in ["", "nan", "None"]:
                target_dict[name] = val
        return {"success": True, "target_dict": target_dict, "count": len(target_dict), "message": f"成功加载 {len(target_dict)} 个店铺目标"}
    except Exception as e:
        return {"success": False, "message": f"加载目标文件失败：{str(e)}"}

def add_target_and_rate(df, target_dict):
    """给 DataFrame 添加目标金额和达成率列（df 必须包含店铺名称和月累计金额）"""
    if df is None or df.empty:
        return df
    result = df.copy()
    result["目标金额"] = result["店铺名称"].map(target_dict).fillna(0).round(2)
    def calc_rate(row):
        actual = row["月累计金额"]
        target = row["目标金额"]
        if target == 0 or pd.isna(target):
            return "-"
        return f"{(actual / target) * 100:.2f}%"
    result["达成率"] = result.apply(calc_rate, axis=1)
    return result

def to_excel_download(df, filename="export.xlsx"):
    """将 DataFrame 转换为 Excel 字节流，用于下载按钮"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

def download_target_template():
    """生成目标模板的 Excel 字节流"""
    template = pd.DataFrame({
        "店铺名称": ["示例店铺A", "示例店铺B"],
        "目标金额": [100000, 200000]
    })
    return to_excel_download(template, "目标模板.xlsx")

# ========== 侧边栏：文件上传与功能 ==========
with st.sidebar:
    st.header("📂 数据加载")
    # 订单文件上传
    order_file = st.file_uploader("选择订单文件 (Excel)", type=["xlsx", "xls"], key="order_upload")
    if order_file is not None:
        if st.session_state.order_file_name != order_file.name:
            with st.spinner("正在处理订单文件..."):
                result = process_order_file(order_file)
                if result["success"]:
                    st.session_state.df_all_daily = result["df_all"]
                    st.session_state.daily_latest = result["daily_latest"]
                    st.session_state.monthly_actual = result["monthly_actual"]
                    st.session_state.df_ship_refund = result["df_ship"]
                    st.session_state.latest_date = result["latest_date"]
                    st.session_state.order_file_name = order_file.name
                    st.success(result["message"])
                else:
                    st.error(result["message"])
        else:
            st.info(f"已加载：{order_file.name}")

    # 目标文件上传
    target_file = st.file_uploader("选择目标文件 (Excel)", type=["xlsx", "xls"], key="target_upload")
    if target_file is not None:
        if st.session_state.target_file_name != target_file.name:
            with st.spinner("正在加载目标..."):
                result = load_target_file(target_file)
                if result["success"]:
                    st.session_state.target_dict = result["target_dict"]
                    st.session_state.target_file_name = target_file.name
                    st.success(result["message"])
                else:
                    st.error(result["message"])
        else:
            st.info(f"已加载：{target_file.name}")

    st.markdown("---")
    st.header("⚙️ 工具")
    # 下载目标模板
    template_data = download_target_template()
    st.download_button("📄 下载目标模板", data=template_data, file_name="目标模板.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    # 清除目标记忆
    if st.button("🗑️ 清除目标记忆"):
        st.session_state.target_dict = {}
        st.session_state.target_file_name = None
        st.success("目标已清除")
        st.rerun()

# ========== 主区域：多标签页 ==========
tab1, tab2, tab3, tab4 = st.tabs(["📅 最新日明细", "🏪 日期范围累计", "🔍 日期查询", "📦 发货退货明细"])

# ---------- 最新日明细（含目标达成率） ----------
with tab1:
    if st.session_state.get("daily_latest") is not None and not st.session_state.daily_latest.empty:
        # 添加目标金额和达成率
        df_display = add_target_and_rate(st.session_state.daily_latest, st.session_state.target_dict)
        # 调整列顺序
        cols = ["日期", "店铺名称", "当日金额", "月累计金额", "目标金额", "达成率"]
        df_display = df_display[cols]
        st.subheader(f"最新日：{st.session_state.latest_date.strftime('%Y-%m-%d')}")
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        # 导出按钮
        excel_data = to_excel_download(df_display, "最新日明细.xlsx")
        st.download_button("💾 导出为 Excel", data=excel_data, file_name="最新日明细.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("请先在侧边栏上传订单文件")

# ---------- 日期范围累计 ----------
with tab2:
    if st.session_state.get("df_all_daily") is not None and not st.session_state.df_all_daily.empty:
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("开始日期", value=date.today().replace(day=1), key="range_start")
        with col2:
            end_date = st.date_input("结束日期", value=date.today(), key="range_end")
        if st.button("🔍 计算累计", key="calc_range"):
            if start_date > end_date:
                st.error("开始日期不能晚于结束日期")
            else:
                mask = (st.session_state.df_all_daily["日期"] >= pd.to_datetime(start_date)) & (st.session_state.df_all_daily["日期"] <= pd.to_datetime(end_date))
                range_data = st.session_state.df_all_daily[mask].copy()
                if range_data.empty:
                    st.warning(f"{start_date} 至 {end_date} 没有业绩数据")
                else:
                    range_summary = range_data.groupby("店铺名称")["当日金额"].sum().reset_index()
                    range_summary["累计金额"] = range_summary["当日金额"].round(2)
                    range_summary = range_summary.sort_values("店铺名称")[["店铺名称", "累计金额"]]
                    st.success(f"共 {len(range_summary)} 个店铺")
                    st.dataframe(range_summary, use_container_width=True, hide_index=True)
                    # 导出
                    excel_data = to_excel_download(range_summary, f"累计_{start_date}_{end_date}.xlsx")
                    st.download_button("💾 导出此结果", data=excel_data, file_name=f"累计_{start_date}_{end_date}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("请先在侧边栏上传订单文件")

# ---------- 日期查询 ----------
with tab3:
    if st.session_state.get("df_all_daily") is not None and not st.session_state.df_all_daily.empty:
        query_date = st.date_input("查询日期", value=date.today(), key="query_date")
        if st.button("🔍 查询", key="query_btn"):
            query_date_ts = pd.to_datetime(query_date)
            result = st.session_state.df_all_daily[st.session_state.df_all_daily["日期"] == query_date_ts].copy()
            if result.empty:
                st.warning(f"{query_date} 没有业绩数据")
            else:
                result = result.sort_values("店铺名称")
                result["当日金额"] = result["当日金额"].round(2)
                result["月累计金额"] = result["月累计金额"].round(2)
                cols = ["日期", "店铺名称", "当日金额", "月累计金额"]
                st.dataframe(result[cols], use_container_width=True, hide_index=True)
                excel_data = to_excel_download(result[cols], f"查询_{query_date}.xlsx")
                st.download_button("💾 导出查询结果", data=excel_data, file_name=f"查询_{query_date}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("请先在侧边栏上传订单文件")

# ---------- 发货退货明细 ----------
with tab4:
    if st.session_state.get("df_ship_refund") is not None and not st.session_state.df_ship_refund.empty:
        df_ship = st.session_state.df_ship_refund.copy()
        # 可选：加入目标达成率（发货退货明细一般不涉及目标，但为保持一致可加）
        cols = ["日期", "店铺名称", "当日发货", "月累计发货", "当日退货", "月累计退货"]
        st.subheader(f"最新日发货退货明细 - {st.session_state.latest_date.strftime('%Y-%m-%d')}")
        st.dataframe(df_ship[cols], use_container_width=True, hide_index=True)
        # 导出
        excel_data = to_excel_download(df_ship[cols], "发货退货明细.xlsx")
        st.download_button("💾 导出发货退货明细", data=excel_data, file_name="发货退货明细.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("请先在侧边栏上传订单文件")