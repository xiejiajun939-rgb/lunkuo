# pages/6_export.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date
import io

from core.db import load_product_master

st.set_page_config(page_title="商品库导出", layout="wide")

# 仅管理员可访问
if st.session_state.get("role") != "admin":
    st.error("您没有管理员权限，无法访问此页面。")
    st.stop()

st.subheader("📚 导出商品库数据（product_master）")

with st.spinner("正在加载商品库数据..."):
    master_df = load_product_master()

if master_df.empty:
    st.warning("商品库（product_master）为空，无法导出。")
else:
    st.write(f"当前商品库共有 **{len(master_df)}** 条记录。")
    
    with st.expander("点击预览商品库数据（前10条）"):
        st.dataframe(master_df.head(10), use_container_width=True)
    
    # 导出为 Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        master_df.to_excel(writer, index=False, sheet_name="商品库")
    
    st.download_button(
        label="📥 导出全部商品库数据 (Excel)",
        data=output.getvalue(),
        file_name=f"product_master_{date.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
