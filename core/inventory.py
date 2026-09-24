"""Inventory workbook parsing, atomic current-snapshot replacement and UI helpers."""
from __future__ import annotations

from datetime import date
import io

import pandas as pd
import streamlit as st

from core.db import init_supabase, load_product_master


INVENTORY_COLUMNS = {
    "仓库代码": "warehouse_code",
    "仓库名称": "warehouse_name",
    "SKU": "sku",
    "商品代码": "style_code",
    "颜色代码": "color_code",
    "颜色名称": "color_name",
    "尺码代码": "size_code",
    "尺码名称": "size_name",
    "可用数": "available_qty",
}


def _text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype("string").str.strip()


def parse_inventory_workbook(file_value, inventory_date: date) -> tuple[pd.DataFrame, dict]:
    """Parse one full inventory workbook and keep only product_master styles."""
    raw = pd.read_excel(io.BytesIO(file_value.getvalue()), sheet_name=0, dtype=object)
    missing = [column for column in INVENTORY_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(f"库存表缺少必要列：{'、'.join(missing)}")

    source_rows = len(raw)
    frame = raw[list(INVENTORY_COLUMNS)].rename(columns=INVENTORY_COLUMNS).copy()
    for column in [
        "warehouse_code", "warehouse_name", "sku", "style_code",
        "color_code", "color_name", "size_code", "size_name",
    ]:
        frame[column] = _text(frame[column])
    frame["style_code"] = frame["style_code"].str.upper()
    frame["sku"] = frame["sku"].str.upper()
    frame["available_qty"] = pd.to_numeric(frame["available_qty"], errors="coerce")
    invalid_qty_rows = int(frame["available_qty"].isna().sum())
    frame = frame[
        (frame["style_code"] != "")
        & (frame["sku"] != "")
        & (frame["warehouse_name"] != "")
        & frame["available_qty"].notna()
    ].copy()

    source_styles = set(frame["style_code"].unique())
    master = load_product_master()
    known_styles = set(
        master.get("style_code", pd.Series(dtype="string"))
        .fillna("").astype("string").str.strip().str.upper()
    )
    known_styles.discard("")
    matched_styles = source_styles & known_styles
    skipped_styles = source_styles - known_styles
    frame = frame[frame["style_code"].isin(matched_styles)].copy()

    group_columns = [
        "warehouse_code", "warehouse_name", "sku", "style_code",
        "color_code", "color_name", "size_code", "size_name",
    ]
    frame = frame.groupby(group_columns, dropna=False, as_index=False).agg(
        available_qty=("available_qty", "sum")
    )
    frame["inventory_date"] = inventory_date.isoformat()
    frame = frame[[
        "inventory_date", "style_code", "sku", "warehouse_code", "warehouse_name",
        "color_code", "color_name", "size_code", "size_name", "available_qty",
    ]]
    stats = {
        "source_rows": source_rows,
        "source_styles": len(source_styles),
        "matched_styles": len(matched_styles),
        "skipped_styles": len(skipped_styles),
        "saved_rows": len(frame),
        "negative_rows": int((frame["available_qty"] < 0).sum()),
        "invalid_qty_rows": invalid_qty_rows,
        "matched_style_codes": sorted(matched_styles),
        "skipped_style_codes": sorted(skipped_styles),
    }
    return frame, stats


def save_inventory_snapshot(
    frame: pd.DataFrame,
    inventory_date: date,
    source_file_name: str,
    stats: dict,
) -> dict:
    """Stage the full file, then atomically replace the current inventory."""
    if frame.empty:
        raise ValueError("没有匹配到罗盘商品库中的库存记录，未执行替换。")
    client = init_supabase()
    batch_payload = {
        "inventory_date": inventory_date.isoformat(),
        "source_file_name": source_file_name,
        "status": "importing",
        "source_rows": stats["source_rows"],
        "source_styles": stats["source_styles"],
        "matched_styles": stats["matched_styles"],
        "skipped_styles": stats["skipped_styles"],
        "saved_rows": stats["saved_rows"],
        "negative_rows": stats["negative_rows"],
    }
    response = client.table("inventory_import_batches").insert(batch_payload).execute()
    batch_id = response.data[0]["id"]
    try:
        records = frame.to_dict("records")
        for record in records:
            record["batch_id"] = batch_id
            record["available_qty"] = float(record["available_qty"])
        for offset in range(0, len(records), 500):
            client.table("inventory_stock_staging").insert(records[offset:offset + 500]).execute()
        client.rpc("finalize_inventory_batch", {"p_batch_id": batch_id}).execute()
    except Exception:
        # RPC may have completed although the HTTP response was interrupted.
        # Never mark a completed replacement as failed or attempt a second cutover.
        try:
            state = (
                client.table("inventory_import_batches")
                .select("status").eq("id", batch_id).limit(1).execute().data or []
            )
            if state and state[0].get("status") == "completed":
                load_inventory_summary.clear()
                load_inventory_details.clear()
                return {"batch_id": batch_id, **stats}
        except Exception:
            pass
        try:
            client.table("inventory_stock_staging").delete().eq("batch_id", batch_id).execute()
            client.table("inventory_import_batches").update({"status": "failed"}).eq("id", batch_id).execute()
        finally:
            raise
    load_inventory_summary.clear()
    load_inventory_details.clear()
    return {"batch_id": batch_id, **stats}


@st.cache_data(ttl=300, show_spinner=False)
def load_inventory_summary() -> pd.DataFrame:
    columns = ["style_code", "inventory_date", "total_inventory", "main_warehouse_inventory", "warehouse_count"]
    try:
        rows = []
        page = 0
        while True:
            response = (
                init_supabase().table("inventory_style_summary")
                .select(",".join(columns)).order("style_code")
                .range(page * 1000, (page + 1) * 1000 - 1).execute()
            )
            page_rows = response.data or []
            rows.extend(page_rows)
            if len(page_rows) < 1000:
                break
            page += 1
        result = pd.DataFrame(rows, columns=columns)
        if result.empty:
            return result
        result["style_code"] = _text(result["style_code"]).str.upper()
        for column in ["total_inventory", "main_warehouse_inventory", "warehouse_count"]:
            result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
        return result
    except Exception:
        return pd.DataFrame(columns=columns)


def attach_inventory_summary(frame: pd.DataFrame, style_column: str | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame
    candidates = [style_column, "style_code", "货号", "商品货号"]
    style_column = next((column for column in candidates if column and column in frame.columns), None)
    if not style_column:
        return frame
    result = frame.copy()
    normalized = result[style_column].fillna("").astype("string").str.strip().str.upper()
    summary = load_inventory_summary()
    if summary.empty:
        result["总库存"] = 0.0
        result["总仓库存"] = 0.0
        return result
    lookup = summary.set_index("style_code")
    result["总库存"] = normalized.map(lookup["total_inventory"]).fillna(0)
    result["总仓库存"] = normalized.map(lookup["main_warehouse_inventory"]).fillna(0)
    return result


@st.cache_data(ttl=300, show_spinner=False)
def load_inventory_details(style_code: str) -> pd.DataFrame:
    columns = [
        "inventory_date", "style_code", "sku", "warehouse_name",
        "color_name", "size_name", "available_qty",
    ]
    try:
        response = (
            init_supabase().table("inventory_stock_current")
            .select(",".join(columns))
            .eq("style_code", str(style_code).strip().upper())
            .order("warehouse_name").order("color_name").order("size_name")
            .execute()
        )
        result = pd.DataFrame(response.data or [], columns=columns)
        if not result.empty:
            result["available_qty"] = pd.to_numeric(result["available_qty"], errors="coerce").fillna(0)
        return result
    except Exception:
        return pd.DataFrame(columns=columns)


def render_inventory_detail(style_code: str, key: str, scope: str = "all") -> None:
    """Render a colour-by-size matrix for all warehouses or the main warehouse."""
    detail = load_inventory_details(style_code)
    if detail.empty:
        st.info("该货号暂无库存数据。")
        return
    if scope == "main":
        detail = detail[detail["warehouse_name"].astype(str).str.strip() == "总仓"].copy()
        scope_label = "总仓库存"
    else:
        scope_label = "总库存"
    if detail.empty:
        st.info(f"该货号暂无{scope_label}数据。")
        return
    as_of = detail["inventory_date"].max()
    total = detail["available_qty"].sum()
    c1, c2 = st.columns(2)
    c1.metric(scope_label, f"{total:,.0f}")
    c2.metric("库存截至", str(as_of))
    matrix = detail.pivot_table(
        index="color_name", columns="size_name", values="available_qty", aggfunc="sum", fill_value=0,
    )
    matrix["合计"] = matrix.sum(axis=1)
    matrix.loc["合计"] = matrix.sum(axis=0)
    st.dataframe(matrix, width="stretch")


def render_inventory_buttons(
    style_code: str,
    total_inventory: float,
    main_warehouse_inventory: float,
    key: str,
) -> None:
    """Show total and main-warehouse values as colour-size detail controls."""
    style_code = str(style_code).strip().upper()

    @st.dialog(f"货号 {style_code} 库存明细", width="large")
    def _show(scope: str) -> None:
        render_inventory_detail(style_code, f"{key}_{scope}", scope=scope)

    all_col, main_col = st.columns(2)
    if all_col.button(
        f"总库存 {float(total_inventory or 0):,.0f}",
        key=f"{key}_all",
        help="查看所有仓库合并后的颜色 × 尺码库存",
        width="stretch",
    ):
        _show("all")
    if main_col.button(
        f"总仓库存 {float(main_warehouse_inventory or 0):,.0f}",
        key=f"{key}_main",
        help="查看总仓的颜色 × 尺码库存",
        width="stretch",
    ):
        _show("main")
