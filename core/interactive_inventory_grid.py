"""Shared AG Grid table with clickable inventory value cells."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, JsCode

from core.inventory import render_inventory_detail


_CLICK_HANDLER = JsCode("""
function(params) {
  const field = params.column && params.column.getColId();
  if (field !== '总库存' && field !== '总仓库存') return;
  const token = field + '|' + Date.now().toString();
  params.node.setDataValue('__inventory_click', token);
}
""")

_CLICK_COLLECTOR = JsCode("""
function(params) {
  const event = params.eventData || {};
  const row = event.data || (event.node ? event.node.data : null) || null;
  return {eventType: params.streamlitRerunEventTriggerName, row: row};
}
""")

_CLICK_OR_SELECT_HANDLER = JsCode("""
function(params) {
  const field = params.column && params.column.getColId();
  if (field === '总库存' || field === '总仓库存') {
    const token = field + '|' + Date.now().toString();
    params.node.setDataValue('__inventory_click', token);
    return;
  }
  params.node.setDataValue('__row_select', Date.now().toString());
}
""")

_NUMBER_FORMATTER = JsCode("""
function(params) {
  if (params.value === null || params.value === undefined || params.value === '') return '-';
  const value = Number(params.value);
  return Number.isFinite(value) ? value.toLocaleString('zh-CN', {maximumFractionDigits: 0}) : params.value;
}
""")

_MONEY_FORMATTER = JsCode("""
function(params) {
  if (params.value === null || params.value === undefined || params.value === '') return '-';
  const value = Number(params.value);
  return Number.isFinite(value) ? value.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : params.value;
}
""")

_PERCENT_FORMATTER = JsCode("""
function(params) {
  if (params.value === null || params.value === undefined || params.value === '') return '-';
  const value = Number(params.value);
  return Number.isFinite(value) ? (value * 100).toFixed(2) + '%' : params.value;
}
""")

_IMAGE_RENDERER = JsCode("""
function(params) {
  if (!params.value) return '';
  // streamlit-aggrid's React renderer expects a primitive return value here.
  // Returning an HTMLImageElement is interpreted as a React child and raises
  // React invariant #31 once for every visible image cell.
  const safeUrl = String(params.value)
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
  return `<img src="${safeUrl}" alt="商品图片" style="width:44px;height:44px;object-fit:cover;border-radius:6px;margin-top:2px" />`;
}
""")


def _style_column(frame: pd.DataFrame) -> str | None:
    for candidate in ("货号", "style_code", "商品货号"):
        if candidate in frame.columns:
            return candidate
    return None


def render_inventory_grid(
    frame: pd.DataFrame,
    key: str,
    *,
    height: int | None = None,
    pinned_columns: tuple[str, ...] = (),
    selectable: bool = False,
) -> dict | None:
    """Render a sortable/filterable grid whose two inventory cells open details."""
    if frame is None or frame.empty:
        st.info("暂无数据。")
        return None
    style_column = _style_column(frame)
    if not style_column or not {"总库存", "总仓库存"}.issubset(frame.columns):
        st.dataframe(frame, hide_index=True, width="stretch")
        return None

    display = frame.copy()
    display["__inventory_style"] = display[style_column].fillna("").astype(str).str.strip().str.upper()
    display["__inventory_click"] = ""
    display["__row_select"] = ""
    display["__row_id"] = [f"{key}_{index}" for index in range(len(display))]

    builder = GridOptionsBuilder.from_dataframe(display)
    builder.configure_default_column(sortable=True, filter=True, resizable=True, minWidth=92)
    builder.configure_grid_options(
        onCellClicked=_CLICK_OR_SELECT_HANDLER if selectable else _CLICK_HANDLER,
        suppressCellFocus=False,
        suppressRowClickSelection=True,
    )
    builder.configure_column("__inventory_style", hide=True)
    builder.configure_column("__inventory_click", hide=True)
    builder.configure_column("__row_select", hide=True)
    builder.configure_column("__row_id", hide=True)
    for column in pinned_columns:
        if column in display.columns:
            builder.configure_column(column, pinned="left")
    for column in display.columns:
        if column in {"__inventory_style", "__inventory_click", "__row_select", "__row_id"}:
            continue
        if column in {"图片", "商品图片", "image", "image_url"}:
            builder.configure_column(column, cellRenderer=_IMAGE_RENDERER, width=72, sortable=False, filter=False)
        elif column in {"总库存", "总仓库存"}:
            builder.configure_column(
                column,
                type=["numericColumn", "numberColumnFilter"],
                valueFormatter=_NUMBER_FORMATTER,
                cellStyle={"color": "#087EA4", "fontWeight": "700", "cursor": "pointer", "textDecoration": "underline"},
                width=118,
            )
        elif pd.api.types.is_numeric_dtype(display[column]):
            formatter = _PERCENT_FORMATTER if any(word in column for word in ("率", "占比")) else _MONEY_FORMATTER
            builder.configure_column(column, type=["numericColumn", "numberColumnFilter"], valueFormatter=formatter)

    options = builder.build()
    options["getRowId"] = JsCode("function(params) { return params.data.__row_id; }")
    response = AgGrid(
        display,
        gridOptions=options,
        key=key,
        height=height or min(620, max(250, 58 + min(len(display), 15) * 34)),
        theme="streamlit",
        allow_unsafe_jscode=True,
        update_on=["cellValueChanged"],
        data_return_mode=DataReturnMode.CUSTOM,
        custom_jscode_for_grid_return=_CLICK_COLLECTOR,
        enable_enterprise_modules=False,
        show_toolbar=True,
        show_download_button=False,
        show_search=True,
    )
    clicked = getattr(response, "raw_data", None)
    if not isinstance(clicked, dict):
        return None
    row = clicked.get("row") if isinstance(clicked.get("row"), dict) else {}
    token = str(row.get("__inventory_click") or "")
    style_code = str(row.get("__inventory_style") or "").strip().upper()
    if token and style_code:
        scope = "main" if token.startswith("总仓库存|") else "all"

        @st.dialog(f"货号 {style_code} 库存明细", width="large")
        def _show_detail() -> None:
            render_inventory_detail(style_code, f"{key}_{scope}", scope=scope)

        _show_detail()
        return None
    if selectable and row.get("__row_select"):
        return {
            column: value for column, value in row.items()
            if not column.startswith("__")
        }
    return None
