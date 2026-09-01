# -*- coding: utf-8 -*-
"""退差价识别、归属匹配与抖音组织汇总。"""

from __future__ import annotations

from datetime import date, timedelta
import math
import re

import pandas as pd


ADJUSTMENT_RE = re.compile(r"^C[A-Z0-9-]+$", re.IGNORECASE)
SOURCE_ORG = "自媒体综合"
SOURCE_DEPT = "自媒体部"


def _fetch_all(query, page_size: int = 1000) -> list[dict]:
    """读取 PostgREST 全部分页，避免默认 1000 行上限截断汇总。"""
    rows = []
    start = 0
    while True:
        batch = query.range(start, start + page_size - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return rows


def infer_platform(filename: str) -> str:
    name = str(filename or "").strip().lower()
    if "抖音" in name or "douyin" in name:
        return "douyin"
    if "视频号" in name or "微信" in name or "wechat" in name:
        return "wechat_channels"
    return "unknown"


def is_price_adjustment(value) -> bool:
    return bool(ADJUSTMENT_RE.fullmatch(str(value or "").strip()))


def normalize_order_no(value) -> str:
    """保留订单号文本，并清理由 Excel 数值单元格产生的末尾 .0。"""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)) and float(value).is_integer():
        return str(int(value))
    text = str(value).strip()
    match = re.fullmatch(r"(\d+)\.0+", text)
    return match.group(1) if match else text


def adjustment_records(df: pd.DataFrame, platform: str) -> list[dict]:
    records = {}
    for row in df.to_dict(orient="records"):
        document_no = str(row.get("备注") or "").strip().upper()
        if not is_price_adjustment(document_no):
            continue
        amount = pd.to_numeric(row.get("金额/时间"), errors="coerce")
        sale_date = pd.to_datetime(row.get("日期"), errors="coerce")
        if pd.isna(amount) or not math.isfinite(float(amount)) or pd.isna(sale_date):
            continue
        records[document_no] = {
            "document_no": document_no,
            "sale_date": sale_date.strftime("%Y-%m-%d"),
            "platform": platform,
            "amount": float(amount),
            "source_org_code": str(row.get("组织编码") or "").strip() or None,
            "source_org_name": SOURCE_ORG,
            "source_dept": SOURCE_DEPT,
        }
    return list(records.values())


def save_adjustments(client, df: pd.DataFrame, platform: str) -> int:
    records = adjustment_records(df, platform)
    if records:
        client.table("price_adjustments").upsert(
            records, on_conflict="document_no"
        ).execute()
    return len(records)


def _find_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    normalized = {str(col).strip(): col for col in df.columns}
    return next((normalized[name] for name in aliases if name in normalized), None)


def apply_adjustment_mapping(client, df: pd.DataFrame) -> dict:
    """逐行校验并更新；错误行不会影响其他正确行。"""
    doc_col = _find_column(df, ("订单号", "单据号", "退差价单号", "C单号"))
    amount_col = _find_column(df, ("金额", "退差价金额", "差价金额"))
    org_col = _find_column(df, ("阿米巴组织", "组织", "组织名称"))
    missing = [name for name, col in (("订单号", doc_col), ("金额", amount_col), ("阿米巴组织", org_col)) if col is None]
    if missing:
        return {"updated": 0, "errors": [f"缺少列：{'、'.join(missing)}"]}

    org_rows = client.table("mapping").select("org_name,dept").execute().data or []
    org_depts = {}
    for row in org_rows:
        org = str(row.get("org_name") or "").strip()
        dept = str(row.get("dept") or "").strip()
        if org and dept:
            org_depts.setdefault(org, set()).add(dept)
    org_depts.setdefault(SOURCE_ORG, set()).add(SOURCE_DEPT)

    input_rows = []
    errors = []
    seen = set()
    for idx, row in df.iterrows():
        doc = str(row.get(doc_col) or "").strip().upper()
        org = str(row.get(org_col) or "").strip()
        amount = pd.to_numeric(row.get(amount_col), errors="coerce")
        excel_row = idx + 2
        if not doc and not org and pd.isna(amount):
            continue
        if not is_price_adjustment(doc):
            errors.append(f"第 {excel_row} 行：订单号不是有效 C 单号")
            continue
        if doc in seen:
            errors.append(f"第 {excel_row} 行：订单号重复 {doc}")
            continue
        seen.add(doc)
        if pd.isna(amount) or not math.isfinite(float(amount)):
            errors.append(f"第 {excel_row} 行：金额无效")
            continue
        departments = org_depts.get(org, set())
        if len(departments) != 1:
            reason = "未在映射关系中找到" if not departments else "对应多个部门"
            errors.append(f"第 {excel_row} 行：阿米巴组织“{org}”{reason}")
            continue
        input_rows.append((excel_row, doc, float(amount), org, next(iter(departments))))

    docs = [row[1] for row in input_rows]
    existing = {}
    for start in range(0, len(docs), 200):
        data = client.table("price_adjustments").select("document_no,amount").in_("document_no", docs[start:start + 200]).execute().data or []
        existing.update({row["document_no"]: row for row in data})

    updated = 0
    today = date.today().isoformat()
    for excel_row, doc, amount, org, dept in input_rows:
        source = existing.get(doc)
        if not source:
            errors.append(f"第 {excel_row} 行：系统中尚无退差价单 {doc}")
            continue
        if abs(abs(float(source["amount"])) - abs(amount)) > 0.01:
            errors.append(f"第 {excel_row} 行：金额与原单不一致（系统 {source['amount']}）")
            continue
        client.table("price_adjustments").update({
            "allocated_org_name": org,
            "allocated_dept": dept,
            "allocation_status": "allocated",
            "mapping_batch_date": today,
        }).eq("document_no", doc).execute()
        updated += 1
    return {"updated": updated, "errors": errors}


def apply_order_adjustments(client, df: pd.DataFrame) -> dict:
    """用订单号反查店铺/组织，平账后替换上月自媒体综合 C 单。"""
    order_col = _find_column(df, ("订单号", "业务订单号"))
    amount_col = _find_column(df, ("金额", "退差价金额", "差价金额"))
    missing = [name for name, col in (("订单号", order_col), ("金额", amount_col)) if col is None]
    if missing:
        return {"updated": 0, "deleted": 0, "errors": [f"缺少列：{'、'.join(missing)}"]}

    current_month_start = date.today().replace(day=1)
    month_end = current_month_start - timedelta(days=1)
    month_start = month_end.replace(day=1)
    errors = []
    input_amounts = {}
    input_first_rows = {}
    for idx, row in df.iterrows():
        order_no = normalize_order_no(row.get(order_col))
        amount = pd.to_numeric(row.get(amount_col), errors="coerce")
        excel_row = idx + 2
        if not order_no and pd.isna(amount):
            continue
        if not order_no:
            errors.append(f"第 {excel_row} 行：订单号为空")
            continue
        if pd.isna(amount) or not math.isfinite(float(amount)) or float(amount) >= 0:
            errors.append(f"第 {excel_row} 行：金额必须是有效负数")
            continue
        input_amounts[order_no] = input_amounts.get(order_no, 0.0) + float(amount)
        input_first_rows.setdefault(order_no, excel_row)
    inputs = [
        (input_first_rows[order_no], order_no, amount)
        for order_no, amount in input_amounts.items()
    ]
    if not inputs:
        errors.append("没有可处理的数据")
        return {"updated": 0, "deleted": 0, "errors": errors}

    mapping_rows = client.table("mapping").select("shop_name,anchor_name,org_name,dept").execute().data or []
    mapping = {}
    for row in mapping_rows:
        key = (str(row.get("shop_name") or "").strip().upper(), str(row.get("anchor_name") or "NONE").strip().upper())
        value = (str(row.get("org_name") or "").strip(), str(row.get("dept") or "").strip())
        if all(value):
            mapping.setdefault(key, set()).add(value)

    resolved = []
    for excel_row, order_no, amount in inputs:
        candidates = client.table("product_sales_all").select(
            "order_no,shop_name,anchor_name,platform"
        ).eq("order_no", order_no).limit(100).execute().data or []
        identities = {
            (
                str(row.get("shop_name") or "").strip(),
                str(row.get("anchor_name") or "NONE").strip() or "NONE",
                str(row.get("platform") or "unknown").strip(),
            )
            for row in candidates
        }
        if not identities:
            errors.append(f"第 {excel_row} 行：数据库中找不到订单 {order_no}")
            continue
        resolved_identities = set()
        unresolved_identity = False
        for shop, anchor, platform in identities:
            if platform not in ("douyin", "wechat_channels"):
                unresolved_identity = True
                continue
            org_matches = mapping.get((shop.upper(), anchor.upper()), set())
            if len(org_matches) != 1:
                unresolved_identity = True
                continue
            org, dept = next(iter(org_matches))
            resolved_identities.add((shop, platform, org, dept, anchor))
        business_identities = {(shop, platform, org, dept) for shop, platform, org, dept, _ in resolved_identities}
        if unresolved_identity or not business_identities:
            errors.append(f"第 {excel_row} 行：订单 {order_no} 存在无法识别的平台或组织映射")
            continue
        if len(business_identities) != 1:
            errors.append(f"第 {excel_row} 行：订单 {order_no} 跨越多个店铺或阿米巴组织")
            continue
        shop, platform, org, dept = next(iter(business_identities))
        anchors = {anchor for s, p, o, d, anchor in resolved_identities if (s, p, o, d) == (shop, platform, org, dept)}
        anchor = next(iter(anchors)) if len(anchors) == 1 else "MULTIPLE"
        resolved.append((order_no, amount, shop, anchor, platform, org, dept))

    raw_rows = _fetch_all(client.table("price_adjustments").select(
        "id,document_no,platform,amount"
    ).gte("sale_date", month_start.isoformat()).lte("sale_date", month_end.isoformat()).eq(
        "allocation_status", "unallocated"
    ).like("document_no", "C%").order("id"))
    raw_totals = {}
    for row in raw_rows:
        raw_totals[row["platform"]] = raw_totals.get(row["platform"], 0.0) + float(row["amount"])
    upload_totals = {}
    for _, amount, _, _, platform, _, _ in resolved:
        upload_totals[platform] = upload_totals.get(platform, 0.0) + amount

    # 临时兼容 2026 年 8 月：历史上传时 C 单尚未入库，因此没有原单可平账。
    # 只在整个月完全没有 C 单时允许订单差价直录；一旦存在任意 C 单，仍强制逐平台平账。
    direct_entry_without_c = not raw_rows and month_end == date(2026, 8, 31)
    if not direct_entry_without_c:
        for platform in sorted(set(raw_totals) | set(upload_totals)):
            raw_total = raw_totals.get(platform, 0.0)
            upload_total = upload_totals.get(platform, 0.0)
            if abs(raw_total - upload_total) > 0.01:
                label = "抖音" if platform == "douyin" else "视频号"
                errors.append(f"{label}金额不平：自媒体综合 C 单 {raw_total:.2f}，上传订单 {upload_total:.2f}，差额 {upload_total - raw_total:.2f}")
    if errors:
        return {"updated": 0, "deleted": 0, "errors": errors}

    records = []
    for order_no, amount, shop, anchor, platform, org, dept in resolved:
        records.append({
            "document_no": f"ORDER-{month_end.isoformat()}-{order_no}",
            "business_order_no": order_no,
            "sale_date": month_end.isoformat(),
            "platform": platform,
            "amount": amount,
            "source_org_name": SOURCE_ORG,
            "source_dept": SOURCE_DEPT,
            "allocated_org_name": org,
            "allocated_dept": dept,
            "allocated_shop_name": shop,
            "allocated_anchor_name": anchor,
            "allocation_status": "allocated",
            "mapping_batch_date": date.today().isoformat(),
        })
    client.table("price_adjustments").upsert(records, on_conflict="document_no").execute()
    raw_ids = [row["id"] for row in raw_rows]
    for start in range(0, len(raw_ids), 200):
        client.table("price_adjustments").delete().in_("id", raw_ids[start:start + 200]).execute()
    return {
        "updated": len(records), "deleted": len(raw_ids), "errors": [],
        "direct_entry_without_c": direct_entry_without_c,
    }


def load_douyin_org_summary(client, start_date, end_date, amount_type="net", platform="douyin") -> pd.DataFrame:
    start_text, end_text = str(start_date), str(end_date)
    sales = _fetch_all(client.table("product_sales_all").select(
        "sale_date,shop_name,anchor_name,ship_amount,net_amount"
    ).eq("platform", platform).gte("sale_date", start_text).lte("sale_date", end_text).order("id"))
    mapping = client.table("mapping").select("shop_name,anchor_name,org_name,dept").execute().data or []
    adjustments = _fetch_all(client.table("price_adjustments").select(
        "amount,source_org_name,source_dept,allocated_org_name,allocated_dept,allocated_shop_name"
    ).eq("platform", platform).gte("sale_date", start_text).lte("sale_date", end_text).order("id"))

    map_df = pd.DataFrame(mapping)
    totals = []
    if sales:
        sales_df = pd.DataFrame(sales)
        sales_df["anchor_name"] = sales_df["anchor_name"].fillna("NONE")
        if not map_df.empty:
            map_df["anchor_name"] = map_df["anchor_name"].fillna("NONE")
            map_df = map_df.drop_duplicates(["shop_name", "anchor_name"], keep="last")
            sales_df = sales_df.merge(map_df, how="left", on=["shop_name", "anchor_name"])
        sales_df["org_name"] = sales_df.get("org_name", pd.Series(index=sales_df.index)).fillna("未匹配组织")
        sales_df["dept"] = sales_df.get("dept", pd.Series(index=sales_df.index)).fillna("未匹配部门")
        amount_column = "ship_amount" if amount_type == "ship" else "net_amount"
        sales_df["sales_amount"] = pd.to_numeric(sales_df[amount_column], errors="coerce").fillna(0)
        totals.append(sales_df[["shop_name", "dept", "org_name", "sales_amount"]])
    # 退差价是实销调整，不属于发货金额。
    if adjustments and amount_type == "net":
        adj_df = pd.DataFrame(adjustments)
        adj_df["dept"] = adj_df["allocated_dept"].fillna(adj_df["source_dept"])
        adj_df["org_name"] = adj_df["allocated_org_name"].fillna(adj_df["source_org_name"])
        adj_df["shop_name"] = adj_df["allocated_shop_name"].fillna("退差价（待归属店铺）")
        adj_df["sales_amount"] = pd.to_numeric(adj_df["amount"], errors="coerce").fillna(0)
        totals.append(adj_df[["shop_name", "dept", "org_name", "sales_amount"]])
    if not totals:
        return pd.DataFrame(columns=["店铺", "部门", "阿米巴组织", "销售额", "店铺内销售占比"])
    result = pd.concat(totals, ignore_index=True).groupby(
        ["shop_name", "dept", "org_name"], as_index=False
    )["sales_amount"].sum()
    shop_totals = result.groupby("shop_name")["sales_amount"].transform("sum")
    result["店铺内销售占比"] = result["sales_amount"].div(shop_totals.mask(shop_totals == 0)).fillna(0)
    return result.rename(columns={
        "shop_name": "店铺", "dept": "部门", "org_name": "阿米巴组织", "sales_amount": "销售额"
    }).sort_values(["店铺", "销售额"], ascending=[True, False])
