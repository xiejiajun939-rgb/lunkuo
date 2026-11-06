# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st

from core.db import load_dimension_mapping
from core.passwords import hash_password
from core.account_permissions import (
    NEW_PAGES, DEFAULT_PAGES, permission_values, recognized,
    selected_pages, merge_permissions, visible_new_pages,
)


def _new_site_permissions(key, defaults):
    if key not in st.session_state:
        st.session_state[key] = list(defaults)
    all_col, clear_col = st.columns(2)
    with all_col:
        if st.button("全选新版普通页面", key=f"{key}_all"):
            st.session_state[key] = list(NEW_PAGES)
    with clear_col:
        if st.button("清空新版页面", key=f"{key}_clear"):
            st.session_state[key] = []
    return st.multiselect(
        "新版小店罗盘页面", list(NEW_PAGES),
        format_func=lambda value: f"新版｜{NEW_PAGES[value][0]}", key=key,
    )


def render_account_management(supabase, all_pages):
    st.markdown("### 👥 账号管理与权限设置")
    st.markdown("#### 管理员密码更改")
    st.caption("管理员为各站通用账号。改密必须验证旧密码与安全口令；修改后各站重新登录，子账号及权限不变。")
    st.link_button("打开统一管理员密码更改", "https://zhibo-data-compass.zhibo-data-compass.workers.dev/account-security")
    st.caption("创建子账号并设置可访问页面及店铺、主播数据范围。")
    st.markdown("#### 新版小店罗盘：普通页面权限")
    st.caption("适用于国内站和 Cloudflare 新版。商品分析与抖店数据目前联动授权；访问统计仅管理员可用，不包含在普通页面全选中。")
    st.markdown("#### 旧版管理后台：仅管理员可用")
    st.caption("系统设置、商品信息管理属于本后台。普通子账号不能通过勾选页面获得管理员权限；此处不会更改账号角色。")
    try:
        rows = supabase.table("sub_accounts").select("*").order("username").execute().data or []
    except Exception as exc:
        st.error(f"加载子账号失败：{exc}")
        return

    with st.expander("➕ 创建新子账号"):
        username = st.text_input("用户名", key="account_new_username")
        password = st.text_input("密码", type="password", key="account_new_password")
        new_pages = _new_site_permissions("account_new_site_pages", DEFAULT_PAGES)
        st.caption("创建后可查看：" + ("、".join(visible_new_pages({}, new_pages)) or "未选择新版页面"))
        if st.button("创建子账号", type="primary", key="account_create"):
            if username.strip().lower() == "admin":
                st.warning("管理员为保留账号，请使用统一密码更改入口。")
            elif not username.strip() or not password:
                st.warning("请输入用户名和密码。")
            else:
                try:
                    supabase.table("sub_accounts").insert({
                        "username": username.strip(), "password": hash_password(password), "role": "viewer",
                        "default_suffix": "_all", "permissions": merge_permissions({}, new_pages),
                        "filter_platform": "all", "filter_shop_names": [],
                    }).execute()
                    st.success("子账号创建成功。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"创建失败：{exc}")

    if not rows:
        st.info("暂无子账号。")
        return

    mapping = load_dimension_mapping()
    shop_names = []
    if not mapping.empty:
        shop_names = sorted(set(mapping["shop_name"].dropna()) | set(mapping["anchor_name"].dropna()))

    for row in rows:
        username = row["username"]
        if username == "admin":
            continue
        with st.expander(f"账号：{username}"):
            permissions = row.get("permissions") if isinstance(row.get("permissions"), dict) else {}
            chosen = _new_site_permissions(f"account_new_site_pages_{username}", selected_pages(permissions))
            effective = visible_new_pages(permissions, chosen)
            st.info("新版可进入页面（保存后生效）：" + ("、".join(effective) or "无"))
            policy = permissions.get("_ui", {})
            if isinstance(policy, dict) and isinstance(policy.get("pageAllowList"), list):
                st.caption("该账号另有专属页面范围限制，以上预览已考虑该限制；原有部门维度等专属设置会保留。")
            st.caption("旧版后台：" + ("该账号已有管理员角色，可使用系统设置和商品信息管理。" if row.get("role") == "admin" else "普通子账号，无管理员权限。"))
            legacy = [value for value in permission_values(permissions) if not recognized(value)]
            if legacy:
                with st.expander("历史／其他站点兼容权限（原样保留）"):
                    st.write("、".join(legacy))
                    st.caption("这些是历史权限值，不代表新版菜单；保存新版权限时不会自动删除。")
            platform_options = ["all", "抖音", "视频号"]
            platform = row.get("filter_platform", "all")
            selected_platform = st.selectbox(
                "限制平台", platform_options,
                index=platform_options.index(platform) if platform in platform_options else 0,
                key=f"account_platform_{username}",
            )
            current_shops = [s for s in (row.get("filter_shop_names") or []) if s in shop_names]
            selected_shops = st.multiselect(
                "限制店铺/主播（空表示全部）", shop_names, default=current_shops,
                key=f"account_shops_{username}",
            )
            save_col, delete_col, confirm_col = st.columns([1, 1, 2])
            with save_col:
                if st.button("💾 保存权限", type="primary", key=f"account_save_{username}"):
                    try:
                        supabase.table("sub_accounts").update({
                            "permissions": merge_permissions(permissions, chosen),
                            "filter_platform": selected_platform,
                            "filter_shop_names": selected_shops,
                        }).eq("username", username).execute()
                        st.success("权限已保存。")
                    except Exception as exc:
                        st.error(f"保存失败：{exc}")
            with confirm_col:
                confirm = st.checkbox("确认删除该账号", key=f"account_confirm_{username}")
            with delete_col:
                if st.button("🗑️ 删除账号", key=f"account_delete_{username}"):
                    if not confirm:
                        st.warning("请先确认删除。")
                    else:
                        supabase.table("sub_accounts").delete().eq("username", username).execute()
                        st.success("账号已删除。")
                        st.rerun()


def render_mapping_management(supabase):
    st.markdown("### 🗂️ 映射关系管理")
    st.caption("维护实销店铺、平台店铺与主播所属组织、部门；直播导入优先按平台店铺匹配实销店铺。")
    if "settings_mapping_df" not in st.session_state:
        try:
            rows = supabase.table("mapping").select("id,shop_name,platform_shop_name,anchor_name,org_name,dept").order("id").execute().data or []
            st.session_state.settings_mapping_df = pd.DataFrame(rows)
        except Exception as exc:
            st.error(f"加载映射关系失败：{exc}")
            return
    raw = st.session_state.settings_mapping_df
    edited = st.data_editor(
        raw, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "shop_name": st.column_config.TextColumn("实销店铺", required=True),
            "platform_shop_name": st.column_config.TextColumn("平台店铺"),
            "anchor_name": st.column_config.TextColumn("主播账号", required=True),
            "org_name": st.column_config.TextColumn("组织", required=True),
            "dept": st.column_config.TextColumn("部门", required=True),
        }, key="settings_mapping_editor",
    )
    save_col, reload_col = st.columns([1, 1])
    with save_col:
        if st.button("💾 保存映射变更", type="primary", key="settings_mapping_save"):
            try:
                raw_ids = {int(v) for v in raw.get("id", pd.Series(dtype=float)).dropna()}
                edited_ids = {int(v) for v in edited.get("id", pd.Series(dtype=float)).dropna()}
                for mapping_id in raw_ids - edited_ids:
                    supabase.table("mapping").delete().eq("id", mapping_id).execute()
                records = []
                for row in edited.to_dict("records"):
                    payload = {k: str(row.get(k) or "").strip() for k in ["shop_name", "platform_shop_name", "anchor_name", "org_name", "dept"]}
                    if not any(payload.values()):
                        continue
                    if pd.notna(row.get("id")):
                        payload["id"] = int(row["id"])
                    records.append(payload)
                if records:
                    supabase.table("mapping").upsert(records, on_conflict="id").execute()
                st.cache_data.clear()
                st.session_state.pop("settings_mapping_df", None)
                st.success("映射关系已保存。")
                st.rerun()
            except Exception as exc:
                st.error(f"保存失败：{exc}")
    with reload_col:
        if st.button("🔄 重新加载", key="settings_mapping_reload"):
            st.session_state.pop("settings_mapping_df", None)
            st.rerun()
