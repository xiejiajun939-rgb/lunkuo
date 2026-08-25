# pages/7_settings.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date
import io
import time
import base64

from core.db import init_supabase, load_dimension_mapping
from core.utils import clear_cache_on_page_change
from core.app_config import load_carousel_config, save_carousel_config
from core.settings_panels import render_account_management, render_mapping_management

st.set_page_config(page_title="系统设置", layout="wide")
clear_cache_on_page_change("settings")

# ---------- 权限检查 ----------
if st.session_state.get("role") != "admin":
    st.error("您没有管理员权限，无法访问系统设置。")
    st.stop()

all_pages = {
    "🏠 主页": "pages/home.py",
    "📊 经营驾驶舱": "pages/dashboard.py",
    "📋 每日明细": "pages/daily_detail.py",
    "📦 商品分析": "pages/product_page.py",
    "📊 商品分析助手": "pages/product_assistant.py",
    "🎤 主播分析": "pages/anchor.py",
    "📈 销售分布与品牌": "pages/distribution.py",
    "🏢 组织与部门分析": "pages/org_dept.py",
    "📚 商品信息管理": "pages/export.py",
    "⚙️ 系统设置": "pages/settings.py",
}

# ---------- 辅助函数 ----------
supabase = init_supabase()
callbacks = st.session_state.get("_admin_callbacks", {})

st.markdown("""
<style>
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 16px; }
.settings-title {font-size:30px;font-weight:750;color:#0f172a;margin-bottom:4px}
.settings-subtitle {color:#64748b;margin-bottom:18px}
</style>
""", unsafe_allow_html=True)
st.markdown('<div class="settings-title">⚙️ 系统设置</div><div class="settings-subtitle">集中管理首页、数据文件、账号权限和业务配置</div>', unsafe_allow_html=True)

tab_home, tab_upload, tab_tools, tab_accounts, tab_mapping = st.tabs([
    "🖼️ 首页与轮播", "📤 文件与目标", "🧰 数据工具", "👥 账号与权限", "🗂️ 映射关系"
])

with tab_home:
    st.markdown("### 首页轮播广告位")
    st.caption("可直接上传图片，也可填写公开图片 URL；留空时显示默认渐变背景。")
    uploaded_banners = st.file_uploader(
        "上传轮播图片（建议 1600×1200）",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="carousel_images",
    )
    carousel_config = load_carousel_config()
    slides_df = pd.DataFrame(carousel_config.get("slides", []))
    for col in ["image_url", "title", "subtitle", "link_url"]:
        if col not in slides_df.columns:
            slides_df[col] = ""
    edited_slides = st.data_editor(
        slides_df[["image_url", "title", "subtitle", "link_url"]],
        num_rows="dynamic",
        width="stretch",
        column_config={
            "image_url": st.column_config.TextColumn("图片 URL / 已上传图片", help="建议使用 4:3 图片，例如 1600×1200"),
            "title": st.column_config.TextColumn("主标题"),
            "subtitle": st.column_config.TextColumn("副标题"),
            "link_url": st.column_config.LinkColumn("点击跳转 URL"),
        },
        key="carousel_editor",
    )
    interval = st.slider("自动切换间隔（秒）", 2, 20, int(carousel_config.get("interval_seconds", 5)))
    if st.button("💾 保存轮播设置", type="primary", key="save_carousel"):
        records = []
        for record in edited_slides.fillna("").to_dict(orient="records"):
            if any(str(v).strip() for v in record.values()):
                records.append({k: str(v).strip() for k, v in record.items()})
        for uploaded in uploaded_banners or []:
            mime = uploaded.type or "image/jpeg"
            encoded = base64.b64encode(uploaded.getvalue()).decode("ascii")
            records.append({
                "image_url": f"data:{mime};base64,{encoded}",
                "title": uploaded.name.rsplit(".", 1)[0],
                "subtitle": "",
                "link_url": "",
            })
        if not records:
            records = [{"image_url": "", "title": "欢迎使用数据罗盘", "subtitle": "经营数据与运营决策工作台", "link_url": ""}]
        save_carousel_config({"interval_seconds": interval, "slides": records})
        st.success("轮播设置已保存，返回主页即可查看。")

with tab_upload:
    st.markdown("### 销售数据")
    col_online, col_offline = st.columns(2)
    with col_online:
        with st.container(border=True):
            st.markdown("#### 线上订单")
            order_files = st.file_uploader("订单 Excel", type=["xlsx", "xls"], accept_multiple_files=True, key="settings_orders")
            if st.button("上传线上订单", type="primary", key="settings_upload_orders"):
                if not order_files:
                    st.warning("请先选择文件。")
                elif not callbacks:
                    st.error("管理工具尚未初始化，请刷新页面。")
                else:
                    successes = 0
                    for uploaded in order_files:
                        ok, msg = callbacks["process_uploaded_file"](io.BytesIO(uploaded.getvalue()), "_all")
                        st.write(f"{'✅' if ok else '❌'} {uploaded.name}：{msg}")
                        successes += int(ok)
                    if successes:
                        callbacks["mark_data_changed"]()
    with col_offline:
        with st.container(border=True):
            st.markdown("#### 线下收入")
            offline_files = st.file_uploader("线下收入 Excel", type=["xlsx", "xls"], accept_multiple_files=True, key="settings_offline")
            if st.button("上传线下收入", type="primary", key="settings_upload_offline"):
                if not offline_files:
                    st.warning("请先选择文件。")
                else:
                    total = 0
                    for uploaded in offline_files:
                        df = pd.read_excel(uploaded, header=1)
                        required = ["日期", "金额/时间", "备注", "组织名称"]
                        if not all(col in df.columns for col in required):
                            st.error(f"{uploaded.name} 缺少必要列。")
                            continue
                        count = callbacks["save_offline_sales"](df)
                        total += count
                        st.write(f"✅ {uploaded.name}：{count} 条")
                    if total:
                        callbacks["mark_data_changed"]()

    st.markdown("### 目标文件")
    col_shop, col_org = st.columns(2)
    with col_shop:
        with st.container(border=True):
            st.markdown("#### 店铺目标")
            target_files = st.file_uploader("店铺目标 Excel", type=["xlsx", "xls"], accept_multiple_files=True, key="settings_targets")
            if st.button("上传店铺目标", key="settings_upload_targets"):
                for uploaded in target_files or []:
                    ok, msg = callbacks["load_target_file"](io.BytesIO(uploaded.getvalue()), "_all")
                    st.write(f"{'✅' if ok else '❌'} {uploaded.name}：{msg}")
                if target_files:
                    callbacks["mark_data_changed"]()
    with col_org:
        with st.container(border=True):
            st.markdown("#### 组织目标")
            org_files = st.file_uploader("组织目标 Excel", type=["xlsx", "xls"], accept_multiple_files=True, key="settings_org_targets")
            if st.button("上传组织目标", key="settings_upload_org_targets"):
                total = 0
                for uploaded in org_files or []:
                    df = pd.read_excel(uploaded, header=None)
                    names = df.iloc[:, 0].astype(str).str.strip()
                    values = pd.to_numeric(df.iloc[:, 1], errors="coerce")
                    targets = {name: value for name, value in zip(names, values) if pd.notna(value) and name not in ["", "nan", "None"]}
                    callbacks["save_org_targets"](targets, "_all")
                    total += len(targets)
                if total:
                    callbacks["mark_data_changed"]()
                    st.success(f"已保存 {total} 个组织目标。")

with tab_tools:
    st.markdown("### 缓存与数据维护")
    col_refresh, col_clear = st.columns(2)
    with col_refresh:
        with st.container(border=True):
            st.markdown("#### 刷新缓存")
            st.caption("数据展示异常时重新生成所有汇总缓存。")
            if st.button("🔄 强制刷新所有数据", type="primary", key="settings_force_refresh"):
                callbacks["mark_data_changed"]()
                st.success("缓存已刷新。")
    with col_clear:
        with st.container(border=True):
            st.markdown("#### 清除店铺目标")
            st.caption("此操作会删除当前全部店铺目标。")
            if st.button("🗑️ 清除店铺目标", key="settings_clear_targets"):
                callbacks["clear_targets"]("_all")
with tab_accounts:
    render_account_management(supabase, all_pages)

with tab_mapping:
    render_mapping_management(supabase)

# 新版系统设置到此结束；下方保留的旧版实现不再执行。
st.stop()

st.markdown("---")

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
            "default_suffix": "_all",  # 兼容数据库现有字段
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
st.subheader("👥 账号管理与权限设置")
st.caption("默认权限仅包含核心四个页面，如需增加“主播分析”、“商品信息管理”、“组织与部门分析”等，请手动勾选。")

if st.button("🔄 重新从数据库加载账号"):
    st.session_state.sub_users = load_sub_accounts_from_db()
    st.success("已重新加载")
    st.rerun()

if st.session_state.get("sub_users"):
    for username, info in list(st.session_state.sub_users.items()):
        with st.expander(f"账号：{username}"):
            st.markdown(f"**{username}** 的权限配置")
            perms = info.get("permissions", {})
            current_permissions = perms.get("_all", perms.get("", []))
            
            with st.form(key=f"form_{username}"):
                all_options = [label for label in all_pages.keys() if label != "⚙️ 系统设置"]
                default_val = [tab for tab in current_permissions if tab in all_options]
                selected = st.multiselect(
                    "允许访问的页面",
                    options=all_options,
                    default=default_val,
                    key=f"perm_{username}"
                )
                new_perms = {"_all": selected}

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
        default_perms = {"_all": DEFAULT_TABS.copy()}
        default_platform = "all"
    if st.button("创建子账号", key="create_sys"):
        if new_username and new_password:
            if new_username in st.session_state.get("sub_users", {}):
                st.error("用户名已存在")
            else:
                new_info = {
                    "password": new_password,
                    "role": "viewer",
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
st.caption("💡 提示：子账号默认只拥有四个核心页面，其他页面需要管理员手动勾选。")


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
