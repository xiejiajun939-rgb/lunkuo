import json
import re


def normalize_product_tags(value, legacy_coupon=False):
    """Normalize Postgres text[], JSON, or comma-separated tag input."""
    if value is None:
        values = []
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "<na>"}:
            values = []
        else:
            try:
                decoded = json.loads(text)
                values = decoded if isinstance(decoded, list) else [text]
            except (json.JSONDecodeError, TypeError):
                values = re.split(r"[,，;；|\n]+", text)

    result = []
    seen = set()
    for item in values:
        tag = str(item).strip()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    if legacy_coupon and "首单礼金" not in seen:
        result.append("首单礼金")
    return result


def product_tags_text(value, legacy_coupon=False):
    return "，".join(normalize_product_tags(value, legacy_coupon))


def product_has_tag(value, tag):
    return tag in normalize_product_tags(value)
