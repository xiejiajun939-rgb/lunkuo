"""Account-scoped table layout memory and named templates."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import streamlit as st

from core.db import init_supabase


AUTO_TEMPLATE = "__auto__"


def _username() -> str:
    return str(st.session_state.get("username") or "anonymous").strip()


@st.cache_data(ttl=30, show_spinner=False)
def load_table_layouts(username: str, page_key: str, table_key: str) -> list[dict]:
    rows = (
        init_supabase().table("user_table_layouts")
        .select("template_name,config,is_default,updated_at")
        .eq("username", username).eq("page_key", page_key).eq("table_key", table_key)
        .order("updated_at", desc=True).execute().data or []
    )
    return rows


def save_table_layout(page_key: str, table_key: str, template_name: str, config: dict, *, is_default=False) -> None:
    client = init_supabase()
    username = _username()
    if is_default:
        client.table("user_table_layouts").update({"is_default": False}).eq(
            "username", username
        ).eq("page_key", page_key).eq("table_key", table_key).execute()
    client.table("user_table_layouts").upsert({
        "username": username,
        "page_key": page_key,
        "table_key": table_key,
        "template_name": template_name,
        "config": config,
        "is_default": bool(is_default),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="username,page_key,table_key,template_name").execute()
    load_table_layouts.clear()


def delete_table_layout(page_key: str, table_key: str, template_name: str) -> None:
    (
        init_supabase().table("user_table_layouts").delete()
        .eq("username", _username()).eq("page_key", page_key).eq("table_key", table_key)
        .eq("template_name", template_name).execute()
    )
    load_table_layouts.clear()


def _clean_column_state(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    allowed = {"colId", "hide", "pinned", "sort", "sortIndex", "width", "flex"}
    return [
        {key: item.get(key) for key in allowed if key in item}
        for item in value if isinstance(item, dict) and item.get("colId")
    ]


def layout_controls(page_key: str, table_key: str, columns: list[str]) -> tuple[list[str], list[dict]]:
    """Render metric/template controls and return visible columns plus AG Grid state."""
    username = _username()
    state_key = f"__table_layout_{page_key}_{table_key}_{username}"
    visible_widget_key = f"layout_visible_{page_key}_{table_key}_{username}"
    pending_key = f"__table_layout_pending_{page_key}_{table_key}_{username}"
    rows = load_table_layouts(username, page_key, table_key)
    lookup = {row["template_name"]: row.get("config") or {} for row in rows}
    if state_key not in st.session_state:
        default_row = next((row for row in rows if row.get("is_default")), None)
        st.session_state[state_key] = lookup.get(AUTO_TEMPLATE) or (
            (default_row or {}).get("config") or {}
        )
    pending = st.session_state.pop(pending_key, None)
    if isinstance(pending, dict):
        st.session_state[state_key] = pending
        st.session_state[visible_widget_key] = [
            column for column in pending.get("visible_columns", columns) if column in columns
        ] or list(columns)
    current = dict(st.session_state.get(state_key) or {})
    visible = [column for column in current.get("visible_columns", columns) if column in columns]
    if not visible:
        visible = list(columns)

    with st.expander("⚙️ 指标显示与布局模板", expanded=False):
        chosen = st.multiselect(
            "选择显示指标",
            columns,
            default=visible,
            key=visible_widget_key,
        )
        action_cols = st.columns([1, 1, 1])
        if action_cols[0].button("全选指标", key=f"layout_all_{table_key}"):
            current["visible_columns"] = list(columns)
            save_table_layout(page_key, table_key, AUTO_TEMPLATE, current)
            st.session_state[pending_key] = current
            st.rerun()
        if action_cols[1].button("恢复系统默认", key=f"layout_reset_{table_key}"):
            delete_table_layout(page_key, table_key, AUTO_TEMPLATE)
            st.session_state[pending_key] = {"visible_columns": list(columns)}
            st.rerun()
        action_cols[2].caption(f"已显示 {len(chosen)}/{len(columns)} 项")

        named = [name for name in lookup if name != AUTO_TEMPLATE]
        template_cols = st.columns([1.5, 1, 1, 1])
        selected_template = template_cols[0].selectbox(
            "已有模板", named, index=None, placeholder="选择模板",
            key=f"layout_template_{table_key}",
        )
        if template_cols[1].button("应用", disabled=not selected_template, key=f"layout_apply_{table_key}"):
            applied = dict(lookup.get(selected_template) or {})
            save_table_layout(page_key, table_key, AUTO_TEMPLATE, applied)
            st.session_state[pending_key] = applied
            st.rerun()
        if template_cols[2].button("设为默认", disabled=not selected_template, key=f"layout_default_{table_key}"):
            save_table_layout(
                page_key, table_key, selected_template, lookup[selected_template], is_default=True
            )
            save_table_layout(page_key, table_key, AUTO_TEMPLATE, lookup[selected_template])
            st.session_state[pending_key] = dict(lookup[selected_template])
            st.rerun()
        if template_cols[3].button("删除", disabled=not selected_template, key=f"layout_delete_{table_key}"):
            delete_table_layout(page_key, table_key, selected_template)
            st.rerun()

        save_cols = st.columns([2, 1])
        template_name = save_cols[0].text_input(
            "新模板名称", placeholder="例如：主播周复盘", key=f"layout_name_{table_key}"
        ).strip()
        if save_cols[1].button("保存为模板", disabled=not template_name, key=f"layout_save_{table_key}"):
            save_table_layout(page_key, table_key, template_name, current)
            st.success(f"已保存模板“{template_name}”。")

    if chosen != visible:
        current["visible_columns"] = chosen or visible
        st.session_state[state_key] = current
        save_table_layout(page_key, table_key, AUTO_TEMPLATE, current)
        visible = current["visible_columns"]
    return visible, _clean_column_state(current.get("columns_state"))


def remember_column_state(page_key: str, table_key: str, column_state) -> None:
    cleaned = _clean_column_state(column_state)
    if not cleaned:
        return
    username = _username()
    state_key = f"__table_layout_{page_key}_{table_key}_{username}"
    current = dict(st.session_state.get(state_key) or {})
    if json.dumps(current.get("columns_state", []), sort_keys=True) == json.dumps(cleaned, sort_keys=True):
        return
    current["columns_state"] = cleaned
    st.session_state[state_key] = current
    save_table_layout(page_key, table_key, AUTO_TEMPLATE, current)
