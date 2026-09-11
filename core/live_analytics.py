# -*- coding: utf-8 -*-
"""直播分析的数据读取、货号识别和导入公共逻辑。"""

from __future__ import annotations

import re
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.db import PAGE_SIZE, load_product_sales_cube, load_product_master, supabase


STYLE_CODE_PATTERN = re.compile(
    r"(?<![A-Z0-9])([A-Z]\d{3}[A-Z]\d{3}(?:-\d+)?)(?![A-Z0-9])",
    re.IGNORECASE,
)


def _load_capture_frames(root):
    """兼容采集工具原始目录和旧版 SQLite 导出目录。"""
    import sqlite3

    root = Path(root)
    db_candidates = list(root.rglob("直播数据.db"))
    if db_candidates:
        with sqlite3.connect(db_candidates[0]) as connection:
            sessions = pd.read_sql_query("select * from live_sessions", connection)
            metrics = pd.read_sql_query("select * from live_metrics", connection)
        return sessions, metrics, db_candidates[0]

    basic_files = [
        path for path in root.rglob("场次*.json")
        if path.parent.name == "直播基础数据"
    ]
    if not basic_files:
        raise FileNotFoundError("未找到 直播基础数据/场次*.json")

    session_rows = []
    session_by_index = {}
    for path in sorted(basic_files):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        index = int(payload.get("session_index") or re.search(r"\d+", path.stem).group())
        payload["session_index"] = index
        session_by_index[index] = payload
        session_rows.append(payload)

    metric_records = {}
    metric_dirs = {"流量转化", "互动", "人群", "完整页面数据"}
    for path in root.rglob("场次*.json"):
        if path.parent.name not in metric_dirs:
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        session = payload.get("session") or {}
        room_id = str(session.get("live_room_id") or "")
        if not room_id:
            index_match = re.search(r"\d+", path.stem)
            session_row = session_by_index.get(int(index_match.group())) if index_match else None
            room_id = str((session_row or {}).get("live_room_id") or "")
        for metric in payload.get("metrics") or []:
            record = dict(metric)
            record["live_room_id"] = room_id
            module = str(record.get("module") or payload.get("module") or path.parent.name)
            record["module"] = module
            key = (room_id, module, str(record.get("metric_name") or ""))
            metric_records[key] = record

    for row in session_rows:
        index = int(row["session_index"])
        candidates = [
            path for path in root.rglob(f"场次{index}.xlsx")
            if path.parent.name == "商品数据"
        ]
        row["product_file_path"] = str(candidates[0]) if candidates else ""

    return pd.DataFrame(session_rows), pd.DataFrame(metric_records.values()), None


def extract_style_code(product_name):
    """从直播商品名称中提取货号，未识别时返回 None。"""
    match = STYLE_CODE_PATTERN.search(str(product_name or "").upper())
    return match.group(1).upper() if match else None


def _number(value, percent=False):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None if percent else 0
    text = str(value).strip().replace("¥", "").replace(",", "")
    if text in {"", "-", "nan", "None"}:
        return None if percent else 0
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None if percent else 0


def _text_or_none(value):
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    text = str(value).strip()
    return None if text in {"", "nan", "None", "<NA>"} else text


def _iso_shanghai(value):
    if value is None or str(value).strip() in {"", "None", "nan"}:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("Asia/Shanghai")
    return parsed.isoformat()


def product_records_from_frame(frame, live_room_id, shop_name, known_styles):
    records = []
    mappings = []
    for row in frame.fillna("").to_dict("records"):
        product_id = str(row.get("商品ID", "")).split(".")[0].strip()
        product_name = str(row.get("商品名称", "")).strip()
        if not product_id or not product_name:
            continue
        style_code = extract_style_code(product_name)
        if style_code and style_code in known_styles:
            match_status = "master_verified"
        elif style_code:
            match_status = "catalog_missing"
        else:
            match_status = "unmatched"
        mappings.append({
            "shop_name": shop_name,
            "product_id": product_id,
            "product_name": product_name,
            "style_code": style_code,
            "match_method": "name_regex" if style_code else "none",
            "match_status": match_status,
            "confirmed": False,
            "updated_at": datetime.now().astimezone().isoformat(),
        })
        records.append({
            "live_room_id": str(live_room_id), "product_id": product_id,
            "product_name": product_name, "style_code": style_code,
            "match_status": match_status,
            "talk_count": int(_number(row.get("讲解次数")) or 0),
            "first_listed_at": _iso_shanghai(row.get("首次上架时间")),
            "live_price": _number(row.get("直播间价格")) or 0,
            "paid_amount": _number(row.get("用户支付金额")) or 0,
            "sold_units": int(_number(row.get("成交件数")) or 0),
            "presale_orders": int(_number(row.get("预售订单数")) or 0),
            "click_users": int(_number(row.get("商品点击人数")) or 0),
            "exposure_click_rate": _number(row.get("商品曝光-点击率（人数）"), True),
            "click_conversion_rate": _number(row.get("商品点击-成交转化率（人数）"), True),
            "gmv_per_1000_exposure": _number(row.get("千次曝光用户支付金额")) or 0,
            "pre_ship_refund_orders": int(_number(row.get("发货前退款订单数")) or 0),
            "pre_ship_refund_amount": _number(row.get("发货前退款金额")) or 0,
            "pre_ship_refund_users": int(_number(row.get("发货前退款人数")) or 0),
            "pre_ship_refund_rate": _number(row.get("发货前订单退款率"), True),
            "post_ship_refund_orders": int(_number(row.get("发货后退款订单数")) or 0),
            "post_ship_refund_amount": _number(row.get("发货后退款金额")) or 0,
            "post_ship_refund_users": int(_number(row.get("发货后退款人数")) or 0),
            "post_ship_refund_rate": _number(row.get("发货后订单退款率"), True),
        })
    return records, mappings


def upsert_batches(table_name, records, on_conflict, batch_size=300):
    for start in range(0, len(records), batch_size):
        supabase.table(table_name).upsert(
            records[start:start + batch_size], on_conflict=on_conflict
        ).execute()


def import_live_folder(root_path, anchor_name=None):
    """从采集工具原始目录或旧版 SQLite 目录导入。"""
    root = Path(root_path)
    sessions, metrics, _ = _load_capture_frames(root)
    master = load_product_master()
    known_styles = set(master.get("style_code", pd.Series(dtype=str)).astype(str).str.strip().str.upper())
    mapping_rows = supabase.table("mapping").select("shop_name,anchor_name").execute().data or []
    shops_by_anchor = {}
    for mapping in mapping_rows:
        anchor_key = str(mapping.get("anchor_name") or "").strip().upper()
        shop_value = str(mapping.get("shop_name") or "").strip()
        if anchor_key and shop_value:
            shops_by_anchor.setdefault(anchor_key, set()).add(shop_value)
    session_records = []
    product_records = []
    mapping_records = []
    for row in sessions.to_dict("records"):
        room_id = str(row["live_room_id"])
        source_anchor = str(row.get("account_name") or "").strip()
        effective_anchor = str(anchor_name or source_anchor or "未维护主播").strip()
        mapped_shops = shops_by_anchor.get(effective_anchor.upper(), set())
        shop_name = next(iter(mapped_shops)) if len(mapped_shops) == 1 else "待维护店铺"
        session_records.append({
            "live_room_id": room_id, "shop_name": shop_name,
            "anchor_name": effective_anchor,
            "live_title": _text_or_none(row.get("live_title")),
            "start_time": _iso_shanghai(row.get("start_time")),
            "end_time": _iso_shanghai(row.get("end_time")),
            "duration_seconds": int(row.get("duration_seconds") or 0),
            "source_url": _text_or_none(row.get("source_url")),
            "source_collected_at": _iso_shanghai(row.get("collected_at")),
        })
        product_path = Path(str(row.get("product_file_path") or ""))
        if not product_path.exists():
            fallback = list(root.rglob(f"{room_id}_商品明细.xlsx"))
            if fallback:
                product_path = fallback[0]
        if product_path.exists():
            frame = pd.read_excel(product_path)
            products, mappings = product_records_from_frame(
                frame, room_id, shop_name, known_styles
            )
            product_records.extend(products)
            mapping_records.extend(mappings)
    metric_records = []
    for row in metrics.to_dict("records"):
        metric_records.append({
            "live_room_id": str(row["live_room_id"]), "module": row["module"],
            "metric_name": row["metric_name"], "metric_value": _number(row.get("metric_value")),
            "raw_value": _text_or_none(row.get("raw_value")), "unit": _text_or_none(row.get("unit")),
            "benchmark_value": _number(row.get("benchmark_value")),
            "benchmark_raw": _text_or_none(row.get("benchmark_raw")),
            "comparison_display": _text_or_none(row.get("comparison_display")),
        })
    # 同一商品会在多场直播重复出现，映射表按店铺+商品ID只保留一行，
    # 避免同一批 upsert 内命中同一个唯一键两次。
    mapping_records = list({
        (record["shop_name"], record["product_id"]): record
        for record in mapping_records
    }.values())
    upsert_batches("live_sessions", session_records, "live_room_id")
    upsert_batches("live_product_mappings", mapping_records, "shop_name,product_id")
    upsert_batches("live_products", product_records, "live_room_id,product_id")
    upsert_batches("live_metrics", metric_records, "live_room_id,module,metric_name")
    return {
        "sessions": len(session_records), "metrics": len(metric_records),
        "products": len(product_records),
        "unique_products": len({r["product_id"] for r in product_records}),
        "matched": sum(r["style_code"] is not None for r in product_records),
        "unmatched": sum(r["style_code"] is None for r in product_records),
    }


def preview_live_folder(root_path):
    """只读取采集目录并返回导入预检结果，不写入数据库。"""
    root = Path(root_path)
    sessions, metrics, db_path = _load_capture_frames(root)
    if sessions.empty:
        raise ValueError("直播数据库中没有场次数据")

    room_ids = sessions["live_room_id"].astype(str).unique().tolist()
    product_files = []
    product_rows = 0
    missing_rooms = []
    for room_id in room_ids:
        session_row = sessions[sessions["live_room_id"].astype(str) == room_id].iloc[0]
        configured_path = Path(str(session_row.get("product_file_path") or ""))
        candidates = [configured_path] if configured_path.exists() else list(root.rglob(f"{room_id}_商品明细.xlsx"))
        if not candidates or not candidates[0].exists():
            missing_rooms.append(room_id)
            continue
        product_files.append(candidates[0])
        product_rows += len(pd.read_excel(candidates[0]))

    start_times = pd.to_datetime(sessions.get("start_time"), errors="coerce")
    end_times = pd.to_datetime(sessions.get("end_time"), errors="coerce")
    return {
        "sessions": len(room_ids),
        "metrics": len(metrics),
        "product_files": len(product_files),
        "product_rows": product_rows,
        "missing_rooms": missing_rooms,
        "anchors": sorted(sessions.get("account_name", pd.Series(dtype=str)).dropna().astype(str).str.strip().unique().tolist()),
        "start_time": start_times.min(),
        "end_time": end_times.max(),
        "source_type": "SQLite 数据库" if db_path else "原始采集目录",
        "database_path": str(db_path.relative_to(root)) if db_path else None,
    }


def _fetch_all(table_name, columns="*", query_builder=None):
    rows, page = [], 0
    while True:
        query = supabase.table(table_name).select(columns)
        if query_builder:
            query = query_builder(query)
        batch = query.range(page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    return rows


@st.cache_data(ttl=120, show_spinner=False)
def load_live_dataset(start_date: date, end_date: date):
    start_boundary = pd.Timestamp(start_date).tz_localize("Asia/Shanghai").isoformat()
    end_boundary = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize("Asia/Shanghai").isoformat()
    sessions = _fetch_all(
        "live_sessions", "*",
        lambda q: q.gte("start_time", start_boundary).lt("start_time", end_boundary).order("start_time"),
    )
    session_df = pd.DataFrame(sessions)
    if session_df.empty:
        return session_df, pd.DataFrame(), pd.DataFrame()
    room_ids = session_df["live_room_id"].astype(str).tolist()
    products, metrics = [], []
    for start in range(0, len(room_ids), 50):
        room_batch = room_ids[start:start + 50]
        products.extend(_fetch_all("live_products", "*", lambda q, ids=room_batch: q.in_("live_room_id", ids)))
        metrics.extend(_fetch_all("live_metrics", "*", lambda q, ids=room_batch: q.in_("live_room_id", ids)))
    for column in ["start_time", "end_time", "source_collected_at", "imported_at"]:
        if column in session_df.columns:
            session_df[column] = pd.to_datetime(session_df[column], utc=True, errors="coerce").dt.tz_convert("Asia/Shanghai")
    return session_df, pd.DataFrame(products), pd.DataFrame(metrics)


@st.cache_data(ttl=120, show_spinner=False)
def load_live_actuals(start_date: date, end_date: date):
    """直播页面使用的数据罗盘同周期商品实销；仅作同货号关联观察。"""
    return load_product_sales_cube(start_date, end_date, apply_filter=True)
