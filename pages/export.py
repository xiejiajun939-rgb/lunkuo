# -*- coding: utf-8 -*-
import io
import math
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

from core.db import init_supabase, load_product_master, load_sold_style_codes
from core.product_tags import normalize_product_tags, product_tags_text
from core.utils import clear_cache_on_page_change
from core.theme import page_header

st.set_page_config(page_title="商品信息管理", layout="wide")
clear_cache_on_page_change("export")

if st.session_state.get("role") != "admin":
    st.error("您没有管理员权限，无法访问此页面。")
    st.stop()

supabase = init_supabase()
EDIT_COLUMNS = ["id", "style_code", "image_url", "category", "tags"]


def _is_missing(series):
    text = series.astype("string").str.strip()
    return series.isna() | text.isin(["", "nan", "None", "<NA>"])


def _to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "有", "参与"}


def _normalize_upload(df):
    aliases = {
        "货号": "style_code", "商品货号": "style_code", "款号": "style_code",
        "图片": "image_url", "图片地址": "image_url", "商品图片": "image_url",
        "品类": "category", "商品品类": "category",
        "商品标签": "tags", "标签": "tags", "tags": "tags",
        "新人礼金": "has_newbie_coupon", "是否新人礼金": "has_newbie_coupon",
    }
    result = df.rename(columns={c: aliases.get(str(c).strip(), str(c).strip()) for c in df.columns}).copy()
    if "style_code" not in result.columns:
        raise ValueError("文件中缺少货号列（style_code／货号／商品货号／款号）。")
    for col in ["image_url", "category"]:
        if col not in result.columns:
            result[col] = ""
    if "tags" not in result.columns:
        result["tags"] = ""
    if "has_newbie_coupon" not in result.columns:
        result["has_newbie_coupon"] = False
    result["tags"] = [
        product_tags_text(tags, _to_bool(coupon))
        for tags, coupon in zip(result["tags"], result["has_newbie_coupon"])
    ]
    result = result[["style_code", "image_url", "category", "tags"]]
    result["style_code"] = result["style_code"].astype("string").str.strip().str.upper()
    result = result[~_is_missing(result["style_code"])].drop_duplicates("style_code", keep="last")
    result["image_url"] = result["image_url"].fillna("").astype(str).str.strip()
    result["category"] = result["category"].fillna("").astype(str).str.strip()
    return result


def _upsert_records(records):
    now = datetime.now(timezone.utc).isoformat()
    existing = []
    incoming = []
    for record in records:
        style_code = str(record.get("style_code", "")).strip().upper()
        if not style_code:
            continue
        payload = {
            "style_code": style_code,
            "image_url": str(record.get("image_url") or "").strip() or None,
            "category": str(record.get("category") or "").strip() or None,
            "tags": normalize_product_tags(record.get("tags")),
            "updated_at": now,
        }
        if pd.notna(record.get("id")):
            payload["id"] = int(record["id"])
            existing.append(payload)
        else:
            incoming.append(payload)
    for start in range(0, len(existing), 500):
        supabase.table("product_master").upsert(
            existing[start:start + 500], on_conflict="id"
        ).execute()
    for start in range(0, len(incoming), 500):
        supabase.table("product_master").upsert(
            incoming[start:start + 500], on_conflict="style_code"
        ).execute()
    return len(existing) + len(incoming)


callbacks = st.session_state.get("_admin_callbacks", {})


def _refresh_sales_style_audit():
    """Only scan sold style codes after an explicit user action."""
    with st.spinner("正在核对销售数据中的商品货号..."):
        st.session_state.product_master_sold_styles = load_sold_style_codes("_all")


page_header("商品信息管理", "维护商品档案、自定义标签与批量导入导出", "PRODUCT MASTER DATA", "管理员")
tab_manage, tab_upload, tab_tags, tab_export = st.tabs([
    "🔎 查询与维护", "📤 批量上传", "🏷️ 商品标签", "📥 数据导出"
])

with st.spinner("正在加载商品库..."):
    master_df = load_product_master()
for col in EDIT_COLUMNS:
    if col not in master_df.columns:
        master_df[col] = [] if col == "tags" else None
master_df["tags"] = [
    product_tags_text(tags, bool(coupon))
    for tags, coupon in zip(
        master_df["tags"],
        master_df.get("has_newbie_coupon", pd.Series(False, index=master_df.index)),
    )
]

sold_styles_df = st.session_state.get("product_master_sold_styles")
audit_loaded = isinstance(sold_styles_df, pd.DataFrame)
if audit_loaded:
    # 仅在用户主动核对后，才把销售货号与商品档案合并。
    catalog_df = sold_styles_df.merge(master_df, on="style_code", how="outer")
else:
    sold_styles_df = pd.DataFrame(columns=["style_code"])
    catalog_df = master_df.copy()
catalog_df["tags"] = catalog_df["tags"].fillna("")

with tab_manage:
    audit_action, audit_note = st.columns([1, 3])
    with audit_action:
        if st.button(
            "🔄 重新核对销售货号" if audit_loaded else "🔍 核对销售未建档商品",
            key="refresh_product_sales_audit",
            width="stretch",
        ):
            _refresh_sales_style_audit()
            st.rerun()
    with audit_note:
        if audit_loaded:
            st.caption(f"本次会话已核对 {len(sold_styles_df):,} 个销售货号；页面操作不会重复扫描。")
        else:
            st.caption("默认只加载商品库，不扫描历史销售。需要检查未建档商品时再点击左侧按钮。")

    total_count = len(catalog_df)
    missing_record_count = int(catalog_df["id"].isna().sum()) if total_count and audit_loaded else 0
    missing_image_count = int(_is_missing(catalog_df["image_url"]).sum()) if total_count else 0
    missing_category_count = int(_is_missing(catalog_df["category"]).sum()) if total_count else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("商品库档案", f"{len(master_df):,}")
    c2.metric("尚未建立档案", f"{missing_record_count:,}" if audit_loaded else "未核对")
    c3.metric("缺少图片", f"{missing_image_count:,}")
    c4.metric("缺少品类", f"{missing_category_count:,}")

    with st.container(border=True):
        col_search, col_category, col_tags, col_missing = st.columns([1.2, 1, 1, 1.3])
        with col_search:
            keyword = st.text_input("搜索货号", placeholder="支持部分货号", key="master_keyword")
        with col_category:
            categories = sorted(v for v in catalog_df["category"].dropna().astype(str).str.strip().unique() if v)
            selected_categories = st.multiselect("筛选品类", categories, key="master_categories")
        with col_tags:
            all_tags = sorted({
                tag for value in catalog_df["tags"]
                for tag in normalize_product_tags(value)
            })
            selected_tags = st.multiselect("筛选标签", all_tags, key="master_tags")
        with col_missing:
            missing_filter_options = ["缺少图片", "缺少品类", "任意资料缺失"]
            if audit_loaded:
                missing_filter_options.insert(0, "尚未建立商品档案")
            missing_filters = st.multiselect(
                "缺失资料筛选", missing_filter_options,
                key="master_missing_filters",
            )

    filtered = catalog_df.copy()
    if keyword.strip():
        filtered = filtered[filtered["style_code"].astype("string").str.contains(
            keyword.strip(), case=False, na=False, regex=False
        )]
    if selected_categories:
        filtered = filtered[filtered["category"].astype(str).isin(selected_categories)]
    if selected_tags:
        filtered = filtered[filtered["tags"].map(
            lambda value: all(tag in normalize_product_tags(value) for tag in selected_tags)
        )]
    missing_image = _is_missing(filtered["image_url"])
    missing_category = _is_missing(filtered["category"])
    missing_record = filtered["id"].isna()
    if "任意资料缺失" in missing_filters:
        filtered = filtered[missing_record | missing_image | missing_category]
    else:
        mask = pd.Series(True, index=filtered.index)
        if "尚未建立商品档案" in missing_filters:
            mask &= missing_record
        if "缺少图片" in missing_filters:
            mask &= missing_image
        if "缺少品类" in missing_filters:
            mask &= missing_category
        filtered = filtered[mask]

    st.caption(f"筛选结果：{len(filtered):,} 条")
    page_col, size_col, _ = st.columns([1, 1, 3])
    with size_col:
        page_size = st.selectbox("每页数量", [50, 100, 200, 500], index=1, key="master_page_size")
    page_count = max(1, math.ceil(len(filtered) / page_size))
    if st.session_state.get("master_page_number", 1) > page_count:
        st.session_state.master_page_number = 1
    with page_col:
        page_number = st.number_input("页码", 1, page_count, 1, key="master_page_number")
    start = (int(page_number) - 1) * page_size
    page_df = filtered.iloc[start:start + page_size][EDIT_COLUMNS].copy().reset_index(drop=True)
    page_df.insert(0, "选择删除", False)

    edited_df = st.data_editor(
        page_df, width="stretch", hide_index=True, num_rows="dynamic",
        column_config={
            "选择删除": st.column_config.CheckboxColumn("删除", default=False),
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "style_code": st.column_config.TextColumn("商品货号", required=True),
            "image_url": st.column_config.LinkColumn("图片地址", display_text="查看图片"),
            "category": st.column_config.TextColumn("品类"),
            "tags": st.column_config.TextColumn("商品标签", help="多个标签用逗号分隔，例如：秋季新品，主推品"),
        }, key="product_master_editor",
    )

    action_save, action_delete, confirm_col = st.columns([1, 1, 2])
    with action_save:
        if st.button("💾 保存本页修改", type="primary", width="stretch"):
            try:
                count = _upsert_records(edited_df[~edited_df["选择删除"]].to_dict("records"))
                st.cache_data.clear()
                st.success(f"已保存 {count} 条商品信息。")
                st.rerun()
            except Exception as exc:
                st.error(f"保存失败：{exc}")
    with confirm_col:
        confirm_delete = st.checkbox("我确认删除勾选的商品（删除后不可恢复）")
    with action_delete:
        if st.button("🗑️ 删除勾选商品", width="stretch"):
            delete_ids = [int(v) for v in edited_df.loc[edited_df["选择删除"], "id"].dropna()]
            if not delete_ids:
                st.warning("请先勾选需要删除的商品。")
            elif not confirm_delete:
                st.warning("请先勾选删除确认。")
            else:
                try:
                    for offset in range(0, len(delete_ids), 200):
                        supabase.table("product_master").delete().in_("id", delete_ids[offset:offset + 200]).execute()
                    st.cache_data.clear()
                    st.success(f"已删除 {len(delete_ids)} 条商品信息。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"删除失败：{exc}")

with tab_upload:
    st.markdown("### 批量上传商品信息")
    st.caption("支持 Excel/CSV；同货号会更新，新货号会新增，并识别常用中英文列名。")
    if audit_loaded:
        unregistered_template = catalog_df[catalog_df["id"].isna()][["style_code"]].copy()
    else:
        unregistered_template = pd.DataFrame(columns=["style_code"])
    unregistered_template["image_url"] = ""
    unregistered_template["category"] = ""
    unregistered_template["tags"] = ""
    unregistered_template = unregistered_template.rename(columns={
        "style_code": "货号",
        "image_url": "图片地址",
        "category": "品类",
        "tags": "商品标签",
    })
    pending_buffer = io.BytesIO()
    with pd.ExcelWriter(pending_buffer, engine="openpyxl") as writer:
        unregistered_template.to_excel(writer, index=False, sheet_name="待维护商品")

    template = pd.DataFrame(columns=["style_code", "image_url", "category", "tags"])
    template_buffer = io.BytesIO()
    with pd.ExcelWriter(template_buffer, engine="openpyxl") as writer:
        template.to_excel(writer, index=False, sheet_name="商品信息")
    download_pending, download_blank = st.columns(2)
    with download_pending:
        if audit_loaded:
            st.download_button(
                f"📋 下载待维护商品模板（{len(unregistered_template):,} 条）",
                pending_buffer.getvalue(),
                file_name=f"待维护商品_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                width="stretch",
            )
        elif st.button("🔍 先核对并生成待维护模板", key="audit_for_template", width="stretch"):
            _refresh_sales_style_audit()
            st.rerun()
    with download_blank:
        st.download_button(
            "📄 下载空白上传模板", template_buffer.getvalue(), file_name="product_master_upload_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch",
        )
    uploaded_file = st.file_uploader("选择商品信息文件", type=["xlsx", "xls", "csv"], key="master_upload")
    if uploaded_file is not None:
        try:
            raw_upload = pd.read_csv(uploaded_file) if uploaded_file.name.lower().endswith(".csv") else pd.read_excel(uploaded_file)
            normalized_upload = _normalize_upload(raw_upload)
            st.info(f"识别到 {len(normalized_upload):,} 个有效货号。")
            st.dataframe(normalized_upload.head(20), width="stretch", hide_index=True)
            if st.button("📤 确认上传并更新商品库", type="primary"):
                count = _upsert_records(normalized_upload.to_dict("records"))
                st.cache_data.clear()
                st.success(f"上传完成，共处理 {count} 条商品信息。")
                st.rerun()
        except Exception as exc:
            st.error(f"文件处理失败：{exc}")

with tab_tags:
    st.markdown("### 🏷️ 自定义商品标签")
    st.caption("标签名称可自由创建；一个商品可同时拥有多个标签，例如：秋季新品、主推品、渠道专属款。")
    tag_flash = st.session_state.pop("product_tag_flash", None)
    if tag_flash:
        st.success(tag_flash)
    current_tags = sorted({
        tag for value in master_df["tags"]
        for tag in normalize_product_tags(value)
    })
    if current_tags:
        st.write("当前标签：" + "　".join(f"`{tag}`" for tag in current_tags))
    tag_name = st.text_input("标签名称", placeholder="例如：秋季新品", key="custom_tag_name").strip()
    operation = st.radio("批量操作", ["添加标签", "移除标签"], horizontal=True, key="custom_tag_operation")
    style_text = st.text_area(
        "商品货号",
        placeholder="每行一个货号，也支持逗号分隔",
        height=180,
        key="custom_tag_styles",
    )
    if st.button("应用标签", type="primary", key="apply_custom_tag"):
        style_codes = sorted({
            code.strip().upper()
            for code in style_text.replace("，", ",").replace("\n", ",").split(",")
            if code.strip()
        })
        if not tag_name or not style_codes:
            st.warning("请输入标签名称和至少一个商品货号。")
        else:
            try:
                lookup = master_df.set_index("style_code")["tags"].to_dict()
                records = []
                for style_code in style_codes:
                    tags = normalize_product_tags(lookup.get(style_code))
                    if operation == "添加标签" and tag_name not in tags:
                        tags.append(tag_name)
                    elif operation == "移除标签":
                        tags = [tag for tag in tags if tag != tag_name]
                    records.append({"style_code": style_code, "tags": tags})
                for offset in range(0, len(records), 500):
                    supabase.table("product_master").upsert(
                        records[offset:offset + 500], on_conflict="style_code"
                    ).execute()
                st.cache_data.clear()
                st.session_state.product_tag_flash = (
                    f"操作成功：已为 {len(records)} 个商品{operation}“{tag_name}”。"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"标签更新失败：{exc}")

with tab_export:
    st.markdown("### 导出商品库")
    st.write(f"当前商品库共有 **{len(master_df):,}** 条记录。")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        master_df.to_excel(writer, index=False, sheet_name="商品库")
    st.download_button(
        "📥 导出全部商品库数据 (Excel)", output.getvalue(),
        file_name=f"product_master_{date.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
    )
