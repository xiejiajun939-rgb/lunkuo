# -*- coding: utf-8 -*-
import streamlit as st
from core.theme import page_header

page_header("数据罗盘管理后台", "数据维护与经营分析分工协作", "ADMINISTRATION", "管理后台")
st.link_button("打开新版经营分析", "https://xiaodian-data-compass.app.workbuddy.host/")
if st.session_state.get("role") == "admin":
    st.info("数据上传、库存维护、账号权限和组织映射，请进入「系统设置」；商品资料与标签，请进入「商品信息管理」。")
    col_product, col_settings = st.columns(2)
    with col_product:
        with st.container(border=True):
            st.subheader("📚 商品资料与标签")
            st.write("维护商品图片、品类、上新日期、商品标签及有效期。")
            st.page_link("pages/export.py", label="进入商品信息管理")
    with col_settings:
        with st.container(border=True):
            st.subheader("⚙️ 数据与系统管理")
            st.write("导入销售、库存、直播和推广数据，维护目标、账号权限与组织映射。")
            st.page_link("pages/settings.py", label="进入系统设置")
else:
    st.info("此站已调整为管理后台。经营分析请使用上方新版入口；后台维护需使用管理员账号。")
