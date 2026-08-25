# -*- coding: utf-8 -*-
import json
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "carousel.json"
DEFAULT_CONFIG = {
    "interval_seconds": 5,
    "slides": [
        {
            "image_url": "",
            "title": "欢迎使用数据罗盘",
            "subtitle": "经营数据、商品分析与运营决策集中在一个工作台",
            "link_url": "",
        }
    ],
}


def load_carousel_config():
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        slides = data.get("slides") or DEFAULT_CONFIG["slides"]
        return {
            "interval_seconds": max(2, min(int(data.get("interval_seconds", 5)), 20)),
            "slides": slides,
        }
    except (OSError, ValueError, TypeError):
        return DEFAULT_CONFIG.copy()


def save_carousel_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

