# -*- coding: utf-8 -*-
import json
import uuid
from pathlib import Path

import streamlit as st
from supabase import create_client

from core.db import SUPABASE_URL, init_supabase

CONFIG_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "carousel.json"
BUCKET_NAME = "carousel"
DEFAULT_CONFIG = {
    "interval_seconds": 5,
    "slides": [{
        "image_url": "",
        "title": "欢迎使用数据罗盘",
        "subtitle": "经营数据、商品分析与运营决策集中在一个工作台",
        "link_url": "",
    }],
}


def _admin_client():
    secret_key = st.secrets.get("SUPABASE_SECRET_KEY") or st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")
    if not secret_key:
        raise RuntimeError("未配置 SUPABASE_SECRET_KEY（或 SUPABASE_SERVICE_ROLE_KEY）。")
    return create_client(SUPABASE_URL, secret_key)


def _normalize_config(data):
    return {
        "interval_seconds": max(2, min(int(data.get("interval_seconds", 5)), 20)),
        "slides": data.get("slides") or DEFAULT_CONFIG["slides"],
    }


def load_carousel_config():
    """优先读取 Supabase 持久化配置，旧环境回退本地 JSON。"""
    try:
        response = init_supabase().table("carousel_settings").select("interval_seconds,slides").eq("id", 1).limit(1).execute()
        if response.data:
            return _normalize_config(response.data[0])
    except Exception:
        pass
    if CONFIG_PATH.exists():
        try:
            return _normalize_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass
    return _normalize_config(DEFAULT_CONFIG)


def save_carousel_config(config):
    """使用服务器 Secret Key 保存配置；本地文件仅作为开发环境备份。"""
    normalized = _normalize_config(config)
    _admin_client().table("carousel_settings").upsert({
        "id": 1,
        "interval_seconds": normalized["interval_seconds"],
        "slides": normalized["slides"],
    }, on_conflict="id").execute()
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def upload_carousel_image(uploaded_file):
    """上传轮播图片到 Supabase Storage，并返回永久公开 URL。"""
    extension = uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else "jpg"
    object_path = f"{uuid.uuid4().hex}.{extension}"
    client = _admin_client()
    client.storage.from_(BUCKET_NAME).upload(
        object_path,
        uploaded_file.getvalue(),
        file_options={"content-type": uploaded_file.type or "image/jpeg", "upsert": "false"},
    )
    public_url = client.storage.from_(BUCKET_NAME).get_public_url(object_path)
    return public_url if isinstance(public_url, str) else public_url.get("publicUrl")
