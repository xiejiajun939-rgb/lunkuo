"""账号登录与页面访问审计。日志失败不得影响主业务。"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pandas as pd
import streamlit as st


PAGE_SIZE = 1000


def ensure_audit_session_id() -> str:
    if "_audit_session_id" not in st.session_state:
        st.session_state["_audit_session_id"] = str(uuid.uuid4())
    return st.session_state["_audit_session_id"]


def _request_metadata() -> tuple[str | None, str | None]:
    try:
        headers = st.context.headers
        forwarded = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for") or ""
        ip_address = forwarded.split(",", 1)[0].strip() or None
        user_agent = headers.get("User-Agent") or headers.get("user-agent") or None
        return ip_address, user_agent
    except Exception:
        return None, None


def record_access_event(
    client,
    event_type: str,
    username: str,
    *,
    success: bool = True,
    page_key: str | None = None,
    page_title: str | None = None,
    details: dict | None = None,
) -> bool:
    if client is None:
        return False
    ip_address, user_agent = _request_metadata()
    payload = {
        "username": str(username or "").strip() or "未知账号",
        "event_type": event_type,
        "success": bool(success),
        "page_key": page_key,
        "page_title": page_title,
        "session_id": ensure_audit_session_id(),
        "ip_address": ip_address,
        "user_agent": user_agent,
        "details": details or {},
    }
    try:
        client.table("access_logs").insert(payload).execute()
        return True
    except Exception:
        return False


def record_page_visit(client, page_key: str, page_title: str) -> bool:
    username = st.session_state.get("username")
    if not username:
        return False
    signature = f"{page_key}|{page_title}"
    if st.session_state.get("_last_audit_page") == signature:
        return False
    recorded = record_access_event(
        client,
        "page_view",
        username,
        page_key=page_key,
        page_title=page_title,
    )
    if recorded:
        st.session_state["_last_audit_page"] = signature
    return recorded


@st.cache_data(ttl=30, show_spinner=False)
def load_access_logs(_client, start_date: date, end_date: date) -> pd.DataFrame:
    columns = [
        "id", "created_at", "username", "event_type", "success", "page_key",
        "page_title", "session_id", "ip_address", "user_agent", "details",
    ]
    if _client is None:
        return pd.DataFrame(columns=columns)
    start_at = pd.Timestamp(start_date).tz_localize("Asia/Shanghai").tz_convert("UTC").isoformat()
    end_at = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize("Asia/Shanghai").tz_convert("UTC").isoformat()
    rows, page = [], 0
    while True:
        response = (
            _client.table("access_logs")
            .select(",".join(columns))
            .gte("created_at", start_at)
            .lt("created_at", end_at)
            .order("created_at", desc=True)
            .range(page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    result = pd.DataFrame(rows, columns=columns)
    if not result.empty:
        result["created_at"] = pd.to_datetime(result["created_at"], utc=True, errors="coerce").dt.tz_convert("Asia/Shanghai")
    return result


def default_audit_dates() -> tuple[date, date]:
    end_date = date.today()
    return end_date - timedelta(days=29), end_date
