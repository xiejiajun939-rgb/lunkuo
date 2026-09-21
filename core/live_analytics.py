# -*- coding: utf-8 -*-
"""直播分析的数据读取、货号识别和导入公共逻辑。"""

from __future__ import annotations

import re
import json
import hashlib
import io
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


def _duration_seconds(value):
    """解析“2小时3分17秒”及 pandas 时间差为秒。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0
    if isinstance(value, pd.Timedelta):
        return int(value.total_seconds())
    text = str(value).strip()
    match = re.search(r"(?:(\d+)小时)?(?:(\d+)分)?(?:(\d+)秒)?", text)
    if not match or not any(match.groups()):
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _read_workbook(source):
    """读取上传对象、字节或本地路径，不改变调用方文件指针。"""
    if isinstance(source, (str, Path)):
        return pd.ExcelFile(source), Path(source).name, Path(source).read_bytes()
    if isinstance(source, bytes):
        payload = source
        name = "直播罗盘.xlsx"
    else:
        if hasattr(source, "getvalue"):
            payload = source.getvalue()
        else:
            position = source.tell() if hasattr(source, "tell") else None
            payload = source.read()
            if position is not None and hasattr(source, "seek"):
                source.seek(position)
        name = getattr(source, "name", "直播罗盘.xlsx")
    buffer = io.BytesIO(payload)
    return pd.ExcelFile(buffer), name, payload


def _overview_values(book):
    frame = pd.read_excel(book, sheet_name="场次概览", header=None)
    values = {}
    for row in frame.iloc[:, :2].fillna("").itertuples(index=False, name=None):
        key = str(row[0]).strip()
        if key and not key.startswith("【"):
            values[key] = row[1]
    return values


def _normalize_live_account_name(value):
    """统一平台店铺／直播账号名称，兼容空格及“直播间”后缀。"""
    text = re.sub(r"\s+", "", str(value or "")).strip().upper()
    return re.sub(r"直播间$", "", text)


def _mapping_context(account_name):
    """优先按平台店铺反查实销店铺，旧数据再兼容主播名称精确匹配。"""
    try:
        rows = (
            supabase.table("mapping")
            .select("shop_name,platform_shop_name,anchor_name")
            .execute().data or []
        )
    except Exception:
        # 数据库字段部署前的短暂兼容窗口。
        rows = supabase.table("mapping").select("shop_name,anchor_name").execute().data or []

    target = _normalize_live_account_name(account_name)
    platform_matches = []
    for row in rows:
        platform_name = _normalize_live_account_name(row.get("platform_shop_name"))
        shop_name = str(row.get("shop_name") or "").strip()
        if platform_name and shop_name and (target == platform_name or target.startswith(platform_name)):
            platform_matches.append((len(platform_name), shop_name))
    if platform_matches:
        longest = max(length for length, _ in platform_matches)
        shops = {shop for length, shop in platform_matches if length == longest}
        if len(shops) == 1:
            return next(iter(shops))

    shops = {
        str(row.get("shop_name") or "").strip()
        for row in rows
        if _normalize_live_account_name(row.get("anchor_name")) == target
        and str(row.get("shop_name") or "").strip()
    }
    return next(iter(shops)) if len(shops) == 1 else "待维护店铺"


def parse_douyin_live_workbook(source):
    """解析抖音店铺后台导出的单场直播工作簿，不写数据库。"""
    book, source_name, payload = _read_workbook(source)
    required_sheets = {"场次概览", "核心指标", "渠道流量", "货品明细", "商品讲解"}
    missing = sorted(required_sheets.difference(book.sheet_names))
    if missing:
        raise ValueError(f"不是支持的抖音直播工作簿，缺少工作表：{', '.join(missing)}")

    overview = _overview_values(book)
    room_id = str(overview.get("房间号（room_id）") or overview.get("房间号") or "").split(".")[0].strip()
    if not room_id:
        filename_match = re.search(r"_(\d{16,})\.xlsx$", source_name, re.IGNORECASE)
        room_id = filename_match.group(1) if filename_match else ""
    if not room_id:
        raise ValueError("工作簿中未找到房间号")

    anchor_name = str(overview.get("达人昵称") or overview.get("店铺/账号") or "").strip()
    platform_account_name = str(overview.get("店铺/账号") or anchor_name).strip()
    shop_name = _mapping_context(platform_account_name)
    start_time = overview.get("开播时间")
    end_time = overview.get("关播时间")
    session = {
        "live_room_id": room_id,
        "shop_name": shop_name,
        "anchor_name": anchor_name or "未维护主播",
        "live_title": _text_or_none(overview.get("直播间标题")),
        "start_time": _iso_shanghai(start_time),
        "end_time": _iso_shanghai(end_time),
        "duration_seconds": _duration_seconds(overview.get("直播时长")),
        "source_url": None,
        "source_collected_at": _iso_shanghai(overview.get("数据抓取时间")),
        "source_format": "douyin_shop_workbook",
        "source_file_name": source_name,
        "source_file_hash": hashlib.sha256(payload).hexdigest(),
    }

    metric_records = []
    overview_metric_names = {
        "直播间成交金额", "直播间用户支付金额", "退款金额",
        "投放消耗（店铺绑定）", "投放消耗（店铺被投）",
        "千次观看用户支付金额", "指示器用户支付金额",
    }
    for name in overview_metric_names:
        if name in overview:
            metric_records.append({
                "live_room_id": room_id, "module": "场次概览", "metric_name": name,
                "metric_value": _number(overview.get(name)), "raw_value": _text_or_none(overview.get(name)),
                "unit": "元", "benchmark_value": None, "benchmark_raw": None,
                "comparison_display": None,
            })
    core = pd.read_excel(book, sheet_name="核心指标")
    # 导出表用合并单元格表示分组，pandas 只会在分组首行读到值。
    # 向下继承后，“互动/新增粉丝数”和“人群/新增粉丝数”会作为两项独立指标保留。
    if "分组" in core.columns:
        core["分组"] = core["分组"].ffill()
    for row in core.fillna("").to_dict("records"):
        name = str(row.get("指标") or "").strip()
        if not name:
            continue
        metric_records.append({
            "live_room_id": room_id,
            "module": str(row.get("分组") or "核心指标").strip() or "核心指标",
            "metric_name": name,
            "metric_value": _number(row.get("本期值")),
            "raw_value": _text_or_none(row.get("本期值")),
            "unit": None,
            "benchmark_value": _number(row.get("上期值")),
            "benchmark_raw": _text_or_none(row.get("上期值")),
            "comparison_display": _text_or_none(row.get("较上期")),
        })
    # 店铺后台导出会偶尔重复同一分组下的同名指标；唯一键写库前只保留最后一条。
    metric_records = list({
        (record["live_room_id"], record["module"], record["metric_name"]): record
        for record in metric_records
    }.values())

    master = load_product_master()
    known_styles = set(master.get("style_code", pd.Series(dtype=str)).astype(str).str.strip().str.upper())
    products_frame = pd.read_excel(book, sheet_name="货品明细")
    product_records, mapping_records = product_records_from_frame(
        products_frame, room_id, shop_name, known_styles
    )
    image_by_product = {
        str(row.get("商品ID") or "").split(".")[0].strip(): _text_or_none(row.get("商品主图"))
        for row in products_frame.fillna("").to_dict("records")
    }
    for record in product_records:
        record["product_image_url"] = image_by_product.get(record["product_id"])

    channels = []
    channel_frame = pd.read_excel(book, sheet_name="渠道流量")
    for row in channel_frame.fillna("").to_dict("records"):
        channel_name = str(row.get("渠道名称") or "").strip()
        if not channel_name:
            continue
        channels.append({
            "live_room_id": room_id,
            "channel_name": channel_name,
            "avg_watch_duration": _text_or_none(row.get("人均观看时长")),
            "watch_count": int(_number(row.get("观看次数")) or 0),
            "watch_users": int(_number(row.get("观看人数")) or 0),
            "paid_amount": _number(row.get("用户支付金额")) or 0,
            "order_count": int(_number(row.get("成交订单数")) or 0),
            "avg_order_amount": _number(row.get("笔单价")) or 0,
            "watch_conversion_rate": _number(row.get("观看-成交率(次数)"), True),
            "shop_bound_spend": _number(row.get("投放消耗(店铺绑定)")) or 0,
            "shop_promoted_spend": _number(row.get("投放消耗(店铺被投)")) or 0,
        })

    talks = []
    talk_frame = pd.read_excel(book, sheet_name="商品讲解")
    for row in talk_frame.fillna("").to_dict("records"):
        product_id = str(row.get("商品ID") or "").split(".")[0].strip()
        start_epoch = int(_number(row.get("讲解开始时间戳")) or 0)
        end_epoch = int(_number(row.get("讲解结束时间戳")) or 0)
        if not product_id or not start_epoch:
            continue
        name = str(row.get("商品名称") or "").strip()
        talks.append({
            "live_room_id": room_id, "product_id": product_id,
            "product_name": name, "style_code": extract_style_code(name),
            "product_image_url": _text_or_none(row.get("商品主图")),
            "talk_start_epoch": start_epoch, "talk_end_epoch": end_epoch,
            "talk_duration_seconds": max(0, end_epoch - start_epoch),
            "paid_amount": _number(row.get("用户支付金额(元)")) or 0,
            "sold_units": int(_number(row.get("成交件数")) or 0),
            "viewer_change": int(_number(row.get("起止人数变化")) or 0),
            "avg_online_users": int(_number(row.get("分均在线人数")) or 0),
        })

    return {
        "session": session, "metrics": metric_records, "products": product_records,
        "mappings": mapping_records, "channels": channels, "talks": talks,
        "platform_account_name": platform_account_name,
    }


def preview_douyin_live_workbook(source):
    parsed = parse_douyin_live_workbook(source)
    return _parsed_workbook_summary(parsed)


def _parsed_workbook_summary(parsed):
    session = parsed["session"]
    return {
        "room_id": session["live_room_id"], "shop_name": session["shop_name"],
        "platform_account_name": parsed.get("platform_account_name"),
        "anchor_name": session["anchor_name"], "start_time": session["start_time"],
        "end_time": session["end_time"], "metrics": len(parsed["metrics"]),
        "products": len(parsed["products"]), "channels": len(parsed["channels"]),
        "talks": len(parsed["talks"]),
        "matched": sum(record.get("style_code") is not None for record in parsed["products"]),
        "unmatched": sum(record.get("style_code") is None for record in parsed["products"]),
    }


def import_douyin_live_workbook(source):
    """导入抖音店铺后台单场工作簿；同一房间号重复上传时安全更新。"""
    parsed = parse_douyin_live_workbook(source)
    session = parsed["session"]
    existing = (
        supabase.table("live_sessions").select("source_file_hash")
        .eq("live_room_id", session["live_room_id"]).limit(1).execute().data or []
    )
    if existing and existing[0].get("source_file_hash") == session["source_file_hash"]:
        return {**_parsed_workbook_summary(parsed), "skipped": True}
    mappings = list({
        (record["shop_name"], record["product_id"]): record
        for record in parsed["mappings"]
    }.values())
    try:
        upsert_batches("live_sessions", [session], "live_room_id")
        # 同一房间号上传了内容更新后的文件时，按整场替换，避免旧商品或旧指标残留。
        for table_name in ["live_metrics", "live_products", "live_channels", "live_product_talks"]:
            supabase.table(table_name).delete().eq("live_room_id", session["live_room_id"]).execute()
        upsert_batches("live_products", parsed["products"], "live_room_id,product_id")
        upsert_batches("live_metrics", parsed["metrics"], "live_room_id,module,metric_name")
        upsert_batches("live_channels", parsed["channels"], "live_room_id,channel_name")
        upsert_batches("live_product_talks", parsed["talks"], "live_room_id,product_id,talk_start_epoch")
        upsert_batches("live_product_mappings", mappings, "shop_name,product_id")
    except Exception:
        # PostgREST 多表写入不是一个事务；任一步失败都删除该场，避免半导入数据污染分析。
        supabase.table("live_sessions").delete().eq("live_room_id", session["live_room_id"]).execute()
        raise
    return {**_parsed_workbook_summary(parsed), "skipped": False}


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
            "first_listed_at": _iso_shanghai(row.get("首次上架时间") or row.get("挂载时间")),
            "live_price": _number(row.get("直播间价格") or row.get("商品价格")) or 0,
            "paid_amount": _number(row.get("用户支付金额")) or 0,
            "sold_units": int(_number(row.get("成交件数")) or 0),
            "presale_orders": int(_number(row.get("预售订单数")) or 0),
            "click_users": int(_number(row.get("商品点击人数")) or 0),
            "exposure_click_rate": _number(
                row.get("商品曝光-点击率（人数）") or row.get("商品曝光-点击率(人数)"), True
            ),
            "click_conversion_rate": _number(
                row.get("商品点击-成交转化率（人数）") or row.get("商品点击-成交转化率(人数)"), True
            ),
            "gmv_per_1000_exposure": _number(
                row.get("千次曝光用户支付金额") or row.get("千次观看成交额")
            ) or 0,
            "pre_ship_refund_orders": int(_number(
                row.get("发货前退款订单数") or row.get("售中退款件数")
            ) or 0),
            "pre_ship_refund_amount": _number(
                row.get("发货前退款金额") or row.get("售中退款金额")
            ) or 0,
            "pre_ship_refund_users": int(_number(row.get("发货前退款人数")) or 0),
            "pre_ship_refund_rate": _number(row.get("发货前订单退款率"), True),
            "post_ship_refund_orders": int(_number(
                row.get("发货后退款订单数") or row.get("售后退款件数")
            ) or 0),
            "post_ship_refund_amount": _number(
                row.get("发货后退款金额") or row.get("售后退款金额")
            ) or 0,
            "post_ship_refund_users": int(_number(row.get("发货后退款人数")) or 0),
            "post_ship_refund_rate": _number(row.get("发货后订单退款率"), True),
        })
    # 抖音导出偶尔会重复同一商品 ID；场次内同商品只保留一条，避免双算。
    records = list({record["product_id"]: record for record in records}.values())
    mappings = list({record["product_id"]: record for record in mappings}.values())
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


@st.cache_data(ttl=300, show_spinner=False)
def load_live_sessions(start_date: date, end_date: date):
    start_boundary = pd.Timestamp(start_date).tz_localize("Asia/Shanghai").isoformat()
    end_boundary = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize("Asia/Shanghai").isoformat()
    sessions = _fetch_all(
        "live_sessions", "live_room_id,shop_name,anchor_name,start_time,end_time,duration_seconds,source_collected_at,imported_at",
        lambda q: q.gte("start_time", start_boundary).lt("start_time", end_boundary).order("start_time"),
    )
    session_df = pd.DataFrame(sessions)
    if not session_df.empty:
        for column in ["start_time", "end_time", "source_collected_at", "imported_at"]:
            if column in session_df.columns:
                session_df[column] = pd.to_datetime(session_df[column], utc=True, errors="coerce").dt.tz_convert("Asia/Shanghai")
    return session_df


@st.cache_data(ttl=300, show_spinner=False)
def load_live_room_data(room_ids_key):
    """只读取当前选中场次的商品与指标，避免先加载所有店铺的明细。"""
    room_ids = [str(value) for value in room_ids_key if str(value).strip()]
    if not room_ids:
        return pd.DataFrame(), pd.DataFrame()
    products, metrics = [], []
    for start in range(0, len(room_ids), 50):
        room_batch = room_ids[start:start + 50]
        products.extend(_fetch_all("live_products", "*", lambda q, ids=room_batch: q.in_("live_room_id", ids)))
        metrics.extend(_fetch_all("live_metrics", "*", lambda q, ids=room_batch: q.in_("live_room_id", ids)))
    return pd.DataFrame(products), pd.DataFrame(metrics)


@st.cache_data(ttl=300, show_spinner=False)
def load_live_dataset(start_date: date, end_date: date):
    """兼容旧调用；新页面优先先读场次，再按筛选加载明细。"""
    session_df = load_live_sessions(start_date, end_date)
    if session_df.empty:
        return session_df, pd.DataFrame(), pd.DataFrame()
    products, metrics = load_live_room_data(tuple(session_df["live_room_id"].astype(str)))
    return session_df, products, metrics


@st.cache_data(ttl=300, show_spinner=False)
def load_live_auxiliary(room_ids_key):
    """读取新抖音工作簿提供的渠道和商品讲解数据。"""
    room_ids = [str(value) for value in room_ids_key if str(value).strip()]
    if not room_ids:
        return pd.DataFrame(), pd.DataFrame()
    channels, talks = [], []
    for start in range(0, len(room_ids), 50):
        room_batch = room_ids[start:start + 50]
        try:
            channels.extend(_fetch_all(
                "live_channels", "*", lambda q, ids=room_batch: q.in_("live_room_id", ids)
            ))
            talks.extend(_fetch_all(
                "live_product_talks", "*", lambda q, ids=room_batch: q.in_("live_room_id", ids)
            ))
        except Exception:
            # 数据库迁移部署前保持旧直播页面可用。
            return pd.DataFrame(), pd.DataFrame()
    return pd.DataFrame(channels), pd.DataFrame(talks)


@st.cache_data(ttl=120, show_spinner=False)
def load_live_actuals(start_date: date, end_date: date):
    """直播页面使用的数据罗盘同周期商品实销；仅作同货号关联观察。"""
    return load_product_sales_cube(start_date, end_date, apply_filter=True)
