# -*- coding: utf-8 -*-
"""退差价识别、归属匹配与抖音组织汇总。"""

from __future__ import annotations

from datetime import date
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


def load_douyin_org_summary(client, start_date, end_date, amount_type="net", platform="douyin") -> pd.DataFrame:
    start_text, end_text = str(start_date), str(end_date)
    sales = _fetch_all(client.table("product_sales_all").select(
        "sale_date,shop_name,anchor_name,ship_amount,net_amount"
    ).eq("platform", platform).gte("sale_date", start_text).lte("sale_date", end_text).order("id"))
    mapping = client.table("mapping").select("shop_name,anchor_name,org_name,dept").execute().data or []
    adjustments = _fetch_all(client.table("price_adjustments").select(
        "amount,source_org_name,source_dept,allocated_org_name,allocated_dept"
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
        adj_df["shop_name"] = "退差价（待归属店铺）"
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
