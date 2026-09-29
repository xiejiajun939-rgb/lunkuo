"""Account-scoped table layout memory and named templates."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
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


@st.fragment
def layout_controls(page_key: str, table_key: str, columns: list[str]) -> tuple[list[str], list[dict]]:
    """Render metric/template controls and return visible columns plus AG Grid state."""
    username = _username()
    state_key = f"__table_layout_{page_key}_{table_key}_{username}"
    pending_key = f"__table_layout_pending_{page_key}_{table_key}_{username}"
    checkbox_prefix = f"layout_metric_{page_key}_{table_key}_{username}_"

    def checkbox_key(column: str) -> str:
        digest = hashlib.md5(str(column).encode("utf-8")).hexdigest()[:12]
        return f"{checkbox_prefix}{digest}"

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
        pending_visible = [
            column for column in pending.get("visible_columns", columns) if column in columns
        ] or list(columns)
        for column in columns:
            st.session_state[checkbox_key(column)] = column in pending_visible
    current = dict(st.session_state.get(state_key) or {})
    visible = [column for column in current.get("visible_columns", columns) if column in columns]
    if not visible:
        visible = list(columns)
    for column in columns:
        key = checkbox_key(column)
        if key not in st.session_state:
            st.session_state[key] = column in visible

    with st.expander("⚙️ 指标显示与布局模板", expanded=False):
        st.caption("勾选指标、输入名称和选择模板都不会刷新直播数据；只有应用到表格时才更新表格。")
        with st.form(f"layout_metrics_form_{page_key}_{table_key}_{username}"):
            checkbox_columns = st.columns(3)
            for index, column in enumerate(columns):
                with checkbox_columns[index % len(checkbox_columns)]:
                    st.checkbox(str(column), key=checkbox_key(column))
            batch_mode = st.radio(
                "批量设置（应用时生效）",
                ["按上方勾选", "全选", "恢复系统默认"],
                horizontal=True,
                key=f"layout_batch_{page_key}_{table_key}_{username}",
            )
            named = [name for name in lookup if name != AUTO_TEMPLATE]
            template_cols = st.columns([1.4, 1])
            selected_template = template_cols[0].selectbox(
                "已有模板", named, index=None, placeholder="选择模板",
                key=f"layout_template_{page_key}_{table_key}_{username}",
            )
            template_name = template_cols[1].text_input(
                "新模板名称", placeholder="例如：主播周复盘",
                key=f"layout_name_{page_key}_{table_key}_{username}",
            ).strip()
            action_cols = st.columns([1.35, 1.2, 1, 1, 1])
            apply_visibility = action_cols[0].form_submit_button(
                "应用到表格", type="primary", width="stretch"
            )
            save_template = action_cols[1].form_submit_button("保存为模板", width="stretch")
            apply_template = action_cols[2].form_submit_button("应用模板", width="stretch")
            set_default = action_cols[3].form_submit_button("设为默认", width="stretch")
            delete_template = action_cols[4].form_submit_button("删除模板", width="stretch")

        checked = [column for column in columns if st.session_state.get(checkbox_key(column), False)]
        chosen = list(columns) if batch_mode in {"全选", "恢复系统默认"} else checked
        draft = dict(current)
        draft["visible_columns"] = chosen

        if apply_visibility:
            if not chosen:
                st.warning("请至少保留一个指标；不能把表格全部隐藏。")
            else:
                if batch_mode == "恢复系统默认":
                    delete_table_layout(page_key, table_key, AUTO_TEMPLATE)
                else:
                    save_table_layout(page_key, table_key, AUTO_TEMPLATE, draft)
                st.session_state[pending_key] = draft
                st.rerun(scope="app")
        elif save_template:
            if not template_name:
                st.warning("请先填写新模板名称。")
            elif not chosen:
                st.warning("请至少保留一个指标后再保存模板。")
            else:
                save_table_layout(page_key, table_key, template_name, draft)
                st.success(f"已保存模板“{template_name}”，直播数据未重新加载。")
        elif apply_template:
            if not selected_template:
                st.warning("请先选择已有模板。")
            else:
                applied = dict(lookup[selected_template])
                save_table_layout(page_key, table_key, AUTO_TEMPLATE, applied)
                st.session_state[pending_key] = applied
                st.rerun(scope="app")
        elif set_default:
            if not selected_template:
                st.warning("请先选择已有模板。")
            else:
                save_table_layout(
                    page_key, table_key, selected_template, lookup[selected_template], is_default=True
                )
                st.success(f"已将“{selected_template}”设为默认，直播数据未重新加载。")
        elif delete_template:
            if not selected_template:
                st.warning("请先选择已有模板。")
            else:
                delete_table_layout(page_key, table_key, selected_template)
                st.success(f"已删除模板“{selected_template}”，直播数据未重新加载。")

        st.caption(f"当前表格显示 {len(visible)}/{len(columns)} 项；未点击应用前，表格保持不变。")

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
