# pages/7_settings.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date
import io

from core.db import init_supabase, load_dimension_mapping
from core.utils import clear_cache_on_page_change

st.set_page_config(page_title="系统设置", layout="wide")
clear_cache_on_page_change("settings")

# ---------- 权限检查 ----------
if st.session_state.get("role") != "admin":
    st.error("您没有管理员权限，无法访问系统设置。")
    st.stop()

# ---------- 从主文件导入页面定义 ----------
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from websale_main import all_pages

# ---------- 辅助函数 ----------
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
                    perms = {"": row["allowed_tabs"], "_all": row["allowed_tabs"]}
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

# ---------- 获取所有店铺/主播名称（从 mapping 表，轻量快速） ----------
@st.cache_data(ttl=600)
def get_all_shop_names():
    """从 mapping 表获取所有 shop_name 和 anchor_name，用于过滤选项"""
    mapping_df = load_dimension_mapping()
    if mapping_df.empty:
        return []
    names = set()
    names.update(mapping_df['shop_name'].dropna().unique())
    names.update(mapping_df['anchor_name'].dropna().unique())
    return sorted(names)

# ---------- 默认页面权限（新子账号只拥有这些页面） ----------
DEFAULT_TABS = [
    "📊 经营驾驶舱",
    "📋 每日明细",
    "📦 商品分析",
    "📈 销售分布与品牌"
]

# ---------- 页面内容 ----------
st.subheader("👥 账号管理与权限设置（按数据源分别设置）")
st.info("对每个子账号，配置其在“全部数据”下能看到的选项卡。")
st.caption("默认权限仅包含核心四个页面，如需增加“主播分析”、“商品库导出”、“组织与部门分析”等，请手动勾选。")

if st.button("🔄 重新从数据库加载账号"):
    st.session_state.sub_users = load_sub_accounts_from_db()
    st.success("已重新加载")
    st.rerun()

if st.session_state.get("sub_users"):
    for username, info in list(st.session_state.sub_users.items()):
        with st.expander(f"账号：{username}"):
            st.markdown(f"**{username}** 的权限配置")
            perms = info.get("permissions", {})
            for suf in ["_all"]:
                if suf not in perms:
                    perms[suf] = []
            
            suffix_display = {"_all": "全部数据"}
            
            with st.form(key=f"form_{username}"):
                new_perms = {}
                for suf, display_name in suffix_display.items():
                    if suf == "_all":
                        all_options = [label for label in all_pages.keys() if label != "⚙️ 系统设置"]
                    else:
                        all_options = [label for label in all_pages.keys() if label not in ["⚙️ 系统设置", "🏢 组织与部门分析"]]
                    
                    default_val = [tab for tab in perms.get(suf, []) if tab in all_options]
                    selected = st.multiselect(
                        f"{display_name} 允许的选项卡",
                        options=all_options,
                        default=default_val,
                        key=f"perm_{username}_{suf}"
                    )
                    new_perms[suf] = selected
                
                # 数据源已固定为"全部数据"
                new_default = "_all"

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
                
                all_shop_names = get_all_shop_names()
                current_shop_names = info.get("filter_shop_names", [])
                current_shop_names = [name for name in current_shop_names if name in all_shop_names]
                new_shop_names = st.multiselect(
                    "限制店铺/主播（空表示全部）",
                    options=all_shop_names,
                    default=current_shop_names,
                    key=f"shops_{username}"
                )

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
        # 数据源已固定为"全部数据"
        default_suffix = "_all"
        
        # 默认权限：全部数据源使用 DEFAULT_TABS（核心四个页面）
        default_perms = {}
        for suf in ["_all"]:
            default_perms[suf] = DEFAULT_TABS.copy()
        
        default_platform = "all"
    if st.button("创建子账号", key="create_sys"):
        if new_username and new_password:
            if new_username in st.session_state.get("sub_users", {}):
                st.error("用户名已存在")
            else:
                new_info = {
                    "password": new_password,
                    "role": "viewer",
                    "default_suffix": default_suffix,
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

st.markdown("---")
st.caption("💡 提示：子账号默认只拥有“经营驾驶舱”、“每日明细”、“商品分析”、“销售分布与品牌”四个核心页面。其他页面（如主播分析、商品库导出、组织与部门分析等）需要管理员在此手动为对应数据源勾选添加。")


# ========== 映射关系管理 ==========
st.markdown("---")
st.subheader("🗂️ 映射关系管理")
st.caption("维护映射表：决定每个「店铺 + 主播账号」的订单归属到哪个组织、哪个部门。表格内可直接编辑、加行、删行，改完点「保存映射变更」。")
st.caption("常见部门：自媒体、零售线上、零售线下、阿里、数字营销、小店运营、项目策划、会员运营组、唯品会、分销加盟部、商品部")


def load_mapping_raw():
    """加载 mapping 表原始数据（含 id，不做大小写/fillna 处理，便于精确编辑）"""
    if supabase is None:
        return pd.DataFrame()
    try:
        resp = supabase.table("mapping").select("id,shop_name,anchor_name,org_name,dept").order("id").execute()
        if resp.data:
            return pd.DataFrame(resp.data)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"加载映射表失败：{e}")
        return pd.DataFrame()


def _cell(v):
    return "" if pd.isna(v) else str(v).strip()


if "mapping_raw_df" not in st.session_state:
    st.session_state.mapping_raw_df = load_mapping_raw()

raw_df = st.session_state.mapping_raw_df

if raw_df.empty:
    st.info("映射表为空")
else:
    edited_df = st.data_editor(
        raw_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "shop_name": st.column_config.TextColumn("店铺", required=True),
            "anchor_name": st.column_config.TextColumn("主播账号", required=True),
            "org_name": st.column_config.TextColumn("组织", required=True),
            "dept": st.column_config.TextColumn("部门", required=True),
        },
        key="mapping_editor",
    )

    if st.button("💾 保存映射变更", type="primary", key="save_mapping_btn"):
        # 差异对比：删除 = 原始有而编辑后没有；修改 = id 相同但字段变化；新增 = id 为空的行
        raw_ids = {int(r) for r in raw_df["id"].dropna()}
        edit_ids = {int(r) for r in edited_df["id"].dropna()}
        to_delete_ids = raw_ids - edit_ids

        raw_by_id = {int(row["id"]): row for _, row in raw_df.iterrows()}
        to_update = []
        for _, row in edited_df.iterrows():
            if pd.isna(row["id"]):
                continue
            rid = int(row["id"])
            orig = raw_by_id.get(rid)
            if orig is None:
                continue
            changed = any(
                _cell(row[c]) != _cell(orig[c])
                for c in ["shop_name", "anchor_name", "org_name", "dept"]
            )
            if changed:
                to_update.append((rid, row))

        new_rows = edited_df[edited_df["id"].isna()]

        n_changes = 0
        # 删除
        for rid in to_delete_ids:
            supabase.table("mapping").delete().eq("id", rid).execute()
            n_changes += 1
        # 修改
        for rid, row in to_update:
            supabase.table("mapping").update({
                "shop_name": _cell(row["shop_name"]),
                "anchor_name": _cell(row["anchor_name"]),
                "org_name": _cell(row["org_name"]),
                "dept": _cell(row["dept"]),
            }).eq("id", rid).execute()
            n_changes += 1
        # 新增（跳过全空行）
        if not new_rows.empty:
            recs = []
            for _, row in new_rows.iterrows():
                rec = {
                    "shop_name": _cell(row["shop_name"]),
                    "anchor_name": _cell(row["anchor_name"]),
                    "org_name": _cell(row["org_name"]),
                    "dept": _cell(row["dept"]),
                }
                if any(rec.values()):
                    recs.append(rec)
            if recs:
                supabase.table("mapping").insert(recs).execute()
                n_changes += len(recs)

        # 清缓存并刷新（mapping 变了，所有依赖映射的页面都要重算）
        st.cache_data.clear()
        st.session_state.pop("mapping_raw_df", None)
        if n_changes > 0:
            st.success(f"已保存 {n_changes} 处变更")
        else:
            st.info("未检测到任何变更")
        st.rerun()

if st.button("🔄 重新加载映射表", key="reload_mapping_btn"):
    st.session_state.mapping_raw_df = load_mapping_raw()
    st.cache_data.clear()
    st.rerun()
