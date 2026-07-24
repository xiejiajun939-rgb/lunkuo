# pages/7_settings.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date
import io

from core.db import init_supabase, load_product_sales

st.set_page_config(page_title="系统设置", layout="wide")

# ---------- 权限检查 ----------
if st.session_state.get("role") != "admin":
    st.error("您没有管理员权限，无法访问系统设置。")
    st.stop()

# ---------- 辅助函数（从主文件复制） ----------
supabase = init_supabase()

def load_sub_accounts_from_db():
    if supabase is None:
        return {}
    try:
        resp = supabase.table("sub_accounts").select("*").execute()
        if resp.data:
            sub_users = {}
            for row in resp.data:
                perms = row.get("permissions", {})
                if not perms and "allowed_tabs" in row:
                    perms = {"": row["allowed_tabs"], "_live": row["allowed_tabs"], "_all": row["allowed_tabs"]}
                sub_users[row["username"]] = {
                    "password": row["password"],
                    "role": row.get("role", "viewer"),
                    "default_suffix": row.get("default_suffix", ""),
                    "permissions": perms,
                    "filter_platform": row.get("filter_platform", "all"),
                    "filter_shop_names": row.get("filter_shop_names", [])
                }
            return sub_users
        else:
            return {}
    except Exception as e:
        st.error(f"加载子账号失败：{e}")
        return {}

def save_sub_account_to_db(username, info):
    if supabase is None:
        return False, "Supabase 未连接"
    try:
        data = {
            "username": username,
            "password": info["password"],
            "role": info["role"],
            "default_suffix": info["default_suffix"],
            "permissions": info.get("permissions", {}),
            "filter_platform": info.get("filter_platform", "all"),
            "filter_shop_names": info.get("filter_shop_names", [])
        }
        resp = supabase.table("sub_accounts").upsert(data, on_conflict="username").execute()
        return True, "保存成功"
    except Exception as e:
        return False, str(e)

def delete_sub_account_from_db(username):
    if supabase is None:
        return False, "Supabase 未连接"
    try:
        resp = supabase.table("sub_accounts").delete().eq("username", username).execute()
        return True, "删除成功"
    except Exception as e:
        return False, str(e)

# ---------- 定义基础选项卡列表（同主文件） ----------
base_tabs = [
    "📊 经营驾驶舱",
    "📋 每日明细",
    "📦 商品分析",
    "🎤 主播分析",
    "📈 销售分布与品牌"
]

# ---------- 页面内容 ----------
st.subheader("👥 账号管理与权限设置（按数据源分别设置）")
st.info("对每个子账号，可分别配置其在“非直播数据”、“直播数据”、“全部数据”下能看到的选项卡。")

if st.button("🔄 重新从数据库加载账号"):
    st.session_state.sub_users = load_sub_accounts_from_db()
    st.success("已重新加载")
    st.rerun()

if st.session_state.get("sub_users"):
    for username, info in list(st.session_state.sub_users.items()):
        with st.expander(f"账号：{username}"):
            st.markdown(f"**{username}** 的权限配置")
            perms = info.get("permissions", {})
            for suf in ["", "_live", "_all"]:
                if suf not in perms:
                    perms[suf] = []
            
            suffix_display = {"": "非直播数据", "_live": "直播数据", "_all": "全部数据"}
            
            # 使用 st.form 包裹配置，防止即时刷新
            with st.form(key=f"form_{username}"):
                new_perms = {}
                for suf, display_name in suffix_display.items():
                    # 构建选项列表：全部数据时额外添加“组织与部门分析”
                    if suf == "_all":
                        all_options = base_tabs + ["🏢 组织与部门分析"]
                    else:
                        all_options = base_tabs
                    # 默认选中当前权限
                    default_val = [tab for tab in perms.get(suf, []) if tab in all_options]
                    selected = st.multiselect(
                        f"{display_name} 允许的选项卡",
                        options=all_options,
                        default=default_val,
                        key=f"perm_{username}_{suf}"
                    )
                    new_perms[suf] = selected
                
                # 默认数据源
                current_default = info.get("default_suffix", "")
                default_options = {"非直播数据": "", "全部数据": "_all"}
                default_display = [k for k, v in default_options.items() if v == current_default]
                default_display = default_display[0] if default_display else "非直播数据"
                new_default_display = st.selectbox(
                    "默认数据源",
                    options=list(default_options.keys()),
                    index=list(default_options.keys()).index(default_display),
                    key=f"default_suffix_{username}"
                )
                new_default = default_options[new_default_display]

                # 数据过滤权限
                st.markdown("**数据过滤权限**")
                platform_options = ["all", "抖音", "视频号"]
                current_platform = info.get("filter_platform", "all")
                new_platform = st.selectbox(
                    "限制平台（all=全部）",
                    options=platform_options,
                    index=platform_options.index(current_platform) if current_platform in platform_options else 0,
                    key=f"platform_{username}"
                )
                
                # 获取所有店铺/主播名称（用于过滤）
                @st.cache_data(ttl=600)
                def get_all_shop_names():
                    df = load_product_sales(apply_filter=False)
                    if df.empty:
                        return []
                    if st.session_state.table_suffix == "_all":
                        if "anchor" in df.columns:
                            return sorted(df["anchor"].dropna().unique().tolist())
                        else:
                            return []
                    else:
                        if "shop_name" in df.columns:
                            return sorted(df["shop_name"].dropna().unique().tolist())
                        else:
                            return []
                all_shop_names = get_all_shop_names()
                current_shop_names = info.get("filter_shop_names", [])
                current_shop_names = [name for name in current_shop_names if name in all_shop_names]
                new_shop_names = st.multiselect(
                    "限制店铺/主播（空表示全部）",
                    options=all_shop_names,
                    default=current_shop_names,
                    key=f"shops_{username}"
                )

                # 提交按钮：保存所有权限
                submitted = st.form_submit_button("💾 保存全部权限")
                if submitted:
                    st.session_state.sub_users[username]["permissions"] = new_perms
                    st.session_state.sub_users[username]["default_suffix"] = new_default
                    st.session_state.sub_users[username]["filter_platform"] = new_platform
                    st.session_state.sub_users[username]["filter_shop_names"] = new_shop_names
                    ok, msg = save_sub_account_to_db(username, st.session_state.sub_users[username])
                    if ok:
                        st.success(f"权限已保存到数据库")
                    else:
                        st.error(f"保存失败：{msg}")
            
            # 删除按钮（放在表单外部，单独操作）
            if st.button(f"删除账号", key=f"del_{username}"):
                ok, msg = delete_sub_account_from_db(username)
                if ok:
                    del st.session_state.sub_users[username]
                    st.success(f"账号 {username} 已删除")
                    st.rerun()
                else:
                    st.error(f"删除失败：{msg}")
else:
    st.info("暂无子账号")

with st.expander("➕ 创建新子账号"):
    col1, col2 = st.columns(2)
    with col1:
        new_username = st.text_input("用户名", key="new_username_sys")
        new_password = st.text_input("密码", type="password", key="new_password_sys")
    with col2:
        default_suffix = st.selectbox("默认数据源", ["非直播数据", "全部数据"], key="new_default_suffix_sys")
        suffix_map = {"非直播数据": "", "全部数据": "_all"}
        default_perms = {}
        for suf in ["", "_live", "_all"]:
            if suf == "_all":
                default_perms[suf] = base_tabs + ["🏢 组织与部门分析"]
            else:
                default_perms[suf] = base_tabs
        default_platform = "all"
    if st.button("创建子账号", key="create_sys"):
        if new_username and new_password:
            if new_username in st.session_state.get("sub_users", {}):
                st.error("用户名已存在")
            else:
                new_info = {
                    "password": new_password,
                    "role": "viewer",
                    "default_suffix": suffix_map[default_suffix],
                    "permissions": default_perms,
                    "filter_platform": default_platform,
                    "filter_shop_names": []
                }
                ok, msg = save_sub_account_to_db(new_username, new_info)
                if ok:
                    st.session_state.sub_users[new_username] = new_info
                    st.success(f"子账号 {new_username} 创建成功（已保存到数据库）")
                    st.rerun()
                else:
                    st.error(f"创建失败：{msg}")
