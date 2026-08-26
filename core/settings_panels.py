# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st

from core.db import load_dimension_mapping


def render_account_management(supabase, all_pages):
    st.markdown("### 👥 账号管理与权限设置")
    st.caption("创建子账号并设置可访问页面及店铺、主播数据范围。")
    try:
        rows = supabase.table("sub_accounts").select("*").order("username").execute().data or []
    except Exception as exc:
        st.error(f"加载子账号失败：{exc}")
        return

    with st.expander("➕ 创建新子账号"):
        username = st.text_input("用户名", key="account_new_username")
        password = st.text_input("密码", type="password", key="account_new_password")
        if st.button("创建子账号", type="primary", key="account_create"):
            if not username.strip() or not password:
                st.warning("请输入用户名和密码。")
            else:
                try:
                    supabase.table("sub_accounts").insert({
                        "username": username.strip(), "password": password, "role": "viewer",
                        "default_suffix": "_all", "permissions": {"_all": [
                            "📊 经营驾驶舱", "📋 每日明细", "📦 商品分析", "🔀 商品销售对比", "📈 销售分布与品牌"
                        ]}, "filter_platform": "all", "filter_shop_names": [],
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
    page_options = [label for label in all_pages if label != "⚙️ 系统设置"]

    for row in rows:
        username = row["username"]
        with st.expander(f"账号：{username}"):
            permissions = row.get("permissions") or {}
            current_pages = permissions.get("_all", permissions.get("", []))
            selected_pages = st.multiselect(
                "允许访问的页面", page_options,
                default=[p for p in current_pages if p in page_options], key=f"account_pages_{username}",
            )
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
                            "permissions": {"_all": selected_pages},
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
    st.caption("维护店铺与主播所属组织、部门；支持直接编辑、增加和删除。")
    if "settings_mapping_df" not in st.session_state:
        try:
            rows = supabase.table("mapping").select("id,shop_name,anchor_name,org_name,dept").order("id").execute().data or []
            st.session_state.settings_mapping_df = pd.DataFrame(rows)
        except Exception as exc:
            st.error(f"加载映射关系失败：{exc}")
            return
    raw = st.session_state.settings_mapping_df
    edited = st.data_editor(
        raw, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "shop_name": st.column_config.TextColumn("店铺", required=True),
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
                    payload = {k: str(row.get(k) or "").strip() for k in ["shop_name", "anchor_name", "org_name", "dept"]}
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
