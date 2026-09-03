# -*- coding: utf-8 -*-
"""
数据库操作公共模块（完整版）
包含所有业务函数，并优化了线下数据查询与映射逻辑。
"""

import streamlit as st
import pandas as pd
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from supabase import create_client

# ---------- Supabase 配置 ----------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_supabase():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Supabase 连接失败：{e}")
        return None

supabase = init_supabase()

def get_table_name(base_name, suffix=None):
    if suffix is None:
        suffix = st.session_state.get("table_suffix", "")
    return f"{base_name}{suffix}"


@st.cache_data(ttl=3600, show_spinner=False)
def _table_has_anchor_name(table_name):
    """缓存表结构探测，避免每次查询都额外请求一次 Supabase。"""
    if supabase is None:
        return False
    try:
        supabase.table(table_name).select("anchor_name").limit(1).execute()
        return True
    except Exception:
        return False

# ---------- 辅助：提取主播 ----------
def extract_anchor(remark):
    if not isinstance(remark, str):
        return None
    match = re.search(r'主播[：:]([^_]+)', remark)
    return match.group(1).strip() if match else None

# ---------- 维度映射加载（ttl=300，映射表很少变化） ----------
@st.cache_data(ttl=300, show_spinner=False)
def load_dimension_mapping():
    if supabase is None:
        return pd.DataFrame()
    try:
        resp = supabase.table("mapping").select("*").execute()
        if resp.data:
            df = pd.DataFrame(resp.data)
            df['shop_name'] = df['shop_name'].astype(str).str.strip().str.upper()
            df['anchor_name'] = df['anchor_name'].fillna('NONE').astype(str).str.strip().str.upper()
            df['org_name'] = df['org_name'].fillna('未分配组织').astype(str).str.strip()
            df['dept'] = df['dept'].fillna('未分配部门').astype(str).str.strip()
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"加载维度映射表失败：{e}")
        return pd.DataFrame()


def _normalize_dimension_mapping(mapping_df):
    """返回可直接用于销售数据 merge 的标准化维度映射。"""
    if mapping_df.empty:
        return pd.DataFrame(columns=["shop_name", "anchor", "org_name", "dept"])

    mapping = mapping_df[
        ["shop_name", "anchor_name", "org_name", "dept"]
    ].copy()
    mapping["shop_name"] = (
        mapping["shop_name"].astype("string").str.strip().str.upper()
    )
    mapping["anchor"] = (
        mapping["anchor_name"]
        .astype("string")
        .str.strip()
        .str.upper()
        .fillna("NONE")
    )
    return (
        mapping.drop(columns="anchor_name")
        .drop_duplicates(subset=["shop_name", "anchor"], keep="first")
    )


def _attach_dimensions(df, mapping_df):
    """关联组织/部门：主播精确匹配优先，店铺归属作为兜底。"""
    if df.empty:
        return df

    result = df.copy()
    result["shop_name"] = (
        result["shop_name"].astype("string").str.strip().str.upper()
    )
    result["anchor"] = (
        result["anchor"].astype("string").str.strip().str.upper().fillna("NONE")
    )
    mapping = _normalize_dimension_mapping(mapping_df)
    if mapping.empty:
        result["org_name"] = "未分配组织"
        result["dept"] = "未分配部门"
        missing_anchor = result["anchor"].isin(["", "NONE", "NAN", "<NA>"]) | result["anchor"].isna()
        result["anchor_display"] = result["anchor"]
        result.loc[missing_anchor, "anchor_display"] = (
            "未识别主播｜" + result.loc[missing_anchor, "shop_name"].fillna("未知店铺")
        )
        return result

    result = result.merge(
        mapping,
        on=["shop_name", "anchor"],
        how="left",
        validate="many_to_one",
        sort=False,
    )

    # 没有主播、主播名称尚未维护时，仍可按店铺确定组织和部门。
    # 同一店铺存在多条主播映射时，只要组织/部门一致，就能安全兜底。
    shop_fallback = (
        mapping.groupby("shop_name", as_index=False)
        .agg(
            fallback_org=("org_name", lambda values: values.dropna().iloc[0] if values.dropna().nunique() == 1 else None),
            fallback_dept=("dept", lambda values: values.dropna().iloc[0] if values.dropna().nunique() == 1 else None),
        )
    )
    result = result.merge(shop_fallback, on="shop_name", how="left", sort=False)
    result["org_name"] = result["org_name"].fillna(result["fallback_org"]).fillna("未分配组织")
    result["dept"] = result["dept"].fillna(result["fallback_dept"]).fillna("未分配部门")
    result = result.drop(columns=["fallback_org", "fallback_dept"])

    missing_anchor = result["anchor"].isin(["", "NONE", "NAN", "<NA>"]) | result["anchor"].isna()
    result["anchor_display"] = result["anchor"]
    result.loc[missing_anchor, "anchor_display"] = (
        "未识别主播｜" + result.loc[missing_anchor, "shop_name"].fillna("未知店铺")
    )
    return result

# ---------- 核心聚合函数（TTL=60s，跨页面共享缓存） ----------
@st.cache_data(ttl=60, show_spinner=False)
def _fetch_sales_summary_cached(start_date, end_date, suffix, view_mode, data_version):
    """
    获取销售汇总数据，返回明细（含组织、部门、店铺、主播），用于组织排行、部门排行及线下明细。
    返回字段：sale_date, org_name, dept, shop_name, anchor, source, total_ship, total_return, total_net

    关键逻辑：
    - 线上数据：使用 (shop_name, anchor) 匹配 mapping 表的 (shop_name, anchor_name)
    - 线下数据：直接使用 shop_name 匹配 mapping 表的 shop_name，得到 org_name 和 dept
    - 线下数据不涉及任何 anchor 字段
    """
    required_columns = ["sale_date", "org_name", "dept", "shop_name", "anchor", "source", "total_ship", "total_return", "total_net"]
    
    if supabase is None:
        return pd.DataFrame(columns=required_columns)

    # ---- 加载 mapping 表 ----
    mapping_df = load_dimension_mapping()
    mapping_exists = suffix == "_all" and not mapping_df.empty

    # ---- 线上数据处理（保留原有分页+日期过滤） ----
    product_table = get_table_name("product_sales", suffix)
    use_anchor = _table_has_anchor_name(product_table)

    if use_anchor:
        select_cols = "sale_date, shop_name, remark, ship_amount, return_amount, net_amount, anchor_name"
    else:
        select_cols = "sale_date, shop_name, remark, ship_amount, return_amount, net_amount"
    try:
        online_data = _fetch_rows_parallel(
            product_table, select_cols, start_date=start_date, end_date=end_date
        )
    except Exception as e:
        st.warning(f"查询线上数据出错：{e}")
        online_data = []

    df_online = pd.DataFrame()
    if online_data:
        df_online = pd.DataFrame(online_data)
        df_online["sale_date"] = pd.to_datetime(df_online["sale_date"])
        if use_anchor and "anchor_name" in df_online.columns:
            df_online["anchor"] = df_online["anchor_name"].fillna("NONE")
        else:
            df_online["anchor"] = (
                df_online["remark"]
                .astype("string")
                .str.extract(r"主播[：:]([^_]+)", expand=False)
                .str.strip()
                .fillna("NONE")
            )
        df_online['shop_name'] = df_online['shop_name'].astype(str).str.strip().str.upper()
        df_online['anchor'] = df_online['anchor'].astype(str).str.strip().str.upper()
        df_online = df_online.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
            "ship_amount": "sum",
            "return_amount": "sum",
            "net_amount": "sum"
        })
        # 线上映射：使用 (shop_name, anchor) 匹配
        if mapping_exists:
            df_online = _attach_dimensions(df_online, mapping_df)
        else:
            df_online['org_name'] = '未分配组织'
            df_online['dept'] = '未分配部门'
        df_online['source'] = 'online'

    # ---- 线下数据处理 ----
    df_offline = pd.DataFrame()
    if suffix == "_all":
        try:
            offline_data = _fetch_rows_parallel(
                "offline_sales_all",
                "sale_date,shop_name,ship_amount,return_amount,net_amount",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as e:
            st.warning(f"查询线下数据出错：{e}")
            offline_data = []

        if offline_data:
            df_offline = pd.DataFrame(offline_data)
            df_offline["sale_date"] = pd.to_datetime(df_offline["sale_date"])
            # 因已经做了日期过滤，无需再截取
            if not df_offline.empty:
                df_offline['shop_name'] = df_offline['shop_name'].astype(str).str.strip().str.upper()
                # 按日期、shop_name 聚合
                df_offline = df_offline.groupby(["sale_date", "shop_name"], as_index=False).agg({
                    "ship_amount": "sum",
                    "return_amount": "sum",
                    "net_amount": "sum"
                })
                # 线下映射：直接用 shop_name 匹配 mapping 表（不使用 anchor）
                if mapping_exists:
                    # 按 shop_name 去重，取第一条
                    mapping_unique_offline = mapping_df.drop_duplicates(subset=['shop_name'], keep='first')
                    shop_to_org = mapping_unique_offline.set_index('shop_name')['org_name'].to_dict()
                    shop_to_dept = mapping_unique_offline.set_index('shop_name')['dept'].to_dict()
                    df_offline['org_name'] = df_offline['shop_name'].map(shop_to_org).fillna('未分配组织')
                    df_offline['dept'] = df_offline['shop_name'].map(shop_to_dept).fillna('未分配部门')
                else:
                    df_offline['org_name'] = '未分配组织'
                    df_offline['dept'] = '未分配部门'
                df_offline['anchor'] = 'NONE'
                df_offline['source'] = 'offline'

    # ---- 退差价处理 ----
    # 退差价没有商品货号，因此只进入经营、每日、店铺、组织和部门等金额汇总，
    # 不进入商品/货号分析，避免将差价虚构到某个商品上。
    df_adjustments = pd.DataFrame()
    if suffix == "_all":
        try:
            adjustment_data = _fetch_rows_parallel(
                "price_adjustments",
                "sale_date,amount,allocated_shop_name,allocated_anchor_name,"
                "allocated_org_name,allocated_dept,source_org_name,source_dept",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as e:
            st.warning(f"查询退差价数据出错：{e}")
            adjustment_data = []
        if adjustment_data:
            df_adjustments = pd.DataFrame(adjustment_data)
            df_adjustments["sale_date"] = pd.to_datetime(df_adjustments["sale_date"])
            df_adjustments["amount"] = pd.to_numeric(
                df_adjustments["amount"], errors="coerce"
            ).fillna(0)
            df_adjustments["shop_name"] = (
                df_adjustments["allocated_shop_name"]
                .fillna("退差价（待归属店铺）")
                .astype(str).str.strip().str.upper()
            )
            df_adjustments["anchor"] = (
                df_adjustments["allocated_anchor_name"]
                .fillna("NONE").astype(str).str.strip().str.upper()
            )
            df_adjustments["org_name"] = df_adjustments["allocated_org_name"].fillna(
                df_adjustments["source_org_name"]
            )
            df_adjustments["dept"] = df_adjustments["allocated_dept"].fillna(
                df_adjustments["source_dept"]
            )
            df_adjustments["ship_amount"] = df_adjustments["amount"].clip(lower=0)
            df_adjustments["return_amount"] = (-df_adjustments["amount"]).clip(lower=0)
            df_adjustments["net_amount"] = df_adjustments["amount"]
            df_adjustments["source"] = "online"

    # ---- 合并 ----
    frames = [frame for frame in (df_online, df_offline, df_adjustments) if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=required_columns)
    df = pd.concat(frames, ignore_index=True)

    # ---- 重命名 ----
    df = df.rename(columns={
        "ship_amount": "total_ship",
        "return_amount": "total_return",
        "net_amount": "total_net"
    })

    # ---- 确保列存在 ----
    for col in required_columns:
        if col not in df.columns:
            if col in ["total_ship", "total_return", "total_net"]:
                df[col] = 0
            elif col == "anchor":
                df[col] = "NONE"
            else:
                df[col] = "未知"

    # ---- view_mode 过滤 ----
    view_mode_to_use = view_mode if view_mode is not None else st.session_state.get("view_mode")
    if view_mode_to_use == "shop":
        if 'dept' in df.columns:
            df = df[df['dept'] == '小店运营']
        else:
            df = pd.DataFrame(columns=required_columns)

    return df[required_columns]


def fetch_sales_summary(start_date, end_date, suffix="", view_mode=None):
    """按当前数据版本获取汇总，数据写入后不会复用旧版本缓存。"""
    data_version = st.session_state.get("_data_version", 0)
    return _fetch_sales_summary_cached(
        start_date,
        end_date,
        suffix,
        view_mode,
        data_version,
    )


# ---------- 完整的销售汇总（兼容旧版） ----------
def fetch_complete_sales_summary(start_date, end_date, suffix="_all", view_mode=None):
    return fetch_sales_summary(start_date, end_date, suffix, view_mode=view_mode)

# ---------- 商品销售数据加载（缓存优化版） ----------
# Supabase/PostgREST 当前项目的服务端单次返回上限是 1000。
# 这里必须与服务端上限一致，否则请求 5000 实际只返回 1000 时会被误判为最后一页。
PAGE_SIZE = 1000
PARALLEL_PAGE_WORKERS = 6
_db_thread_local = threading.local()


def _fetch_rows_parallel(table_name, select_cols, start_date=None, end_date=None):
    """并发分页读取 PostgREST，降低大月份数据首次加载的网络等待时间。"""
    def fetch_page(page):
        if not hasattr(_db_thread_local, "client"):
            _db_thread_local.client = create_client(SUPABASE_URL, SUPABASE_KEY)
        query = _db_thread_local.client.table(table_name).select(select_cols)
        if start_date is not None:
            query = query.gte("sale_date", start_date.isoformat())
        if end_date is not None:
            query = query.lte("sale_date", end_date.isoformat())
        # 日期区间查询必须先按 sale_date 排序，再用 id 保证同日记录稳定。
        # 若只按主键 id 排序，Postgres 容易选择主键扫描后再过滤日期，
        # 历史明细增大后即使只查近 7 天也可能触发 statement_timeout。
        if start_date is not None or end_date is not None:
            query = query.order("sale_date").order("id")
        else:
            query = query.order("id")
        response = query.range(
            page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1
        ).execute()
        return page, response.data or []

    all_rows = []
    first_page = 0
    while True:
        pages = range(first_page, first_page + PARALLEL_PAGE_WORKERS)
        batch = {}
        with ThreadPoolExecutor(max_workers=PARALLEL_PAGE_WORKERS) as executor:
            futures = [executor.submit(fetch_page, page) for page in pages]
            for future in as_completed(futures):
                page, rows = future.result()
                batch[page] = rows

        reached_end = False
        for page in pages:
            rows = batch.get(page, [])
            all_rows.extend(rows)
            if len(rows) < PAGE_SIZE:
                reached_end = True
                break
        if reached_end:
            break
        first_page += PARALLEL_PAGE_WORKERS
    return all_rows

@st.cache_data(ttl=600, show_spinner=False)
def _load_product_sales_raw(suffix, include_offline, start_date=None, end_date=None):
    """缓存：分页读取 product_sales + 可选线下数据，返回完整 DataFrame（不含权限/部门过滤）"""
    if supabase is None:
        return pd.DataFrame()
    table_name = get_table_name("product_sales", suffix)

    use_anchor = _table_has_anchor_name(table_name)

    base_cols = "sale_date, shop_name, product_code, style_code, brand, year, season, product_category, style, color_code, size_code, ship_amount, return_amount, net_amount, remark"
    select_cols = base_cols + ", anchor_name" if use_anchor else base_cols

    all_data = _fetch_rows_parallel(
        table_name, select_cols, start_date=start_date, end_date=end_date
    )

    if not all_data:
        return pd.DataFrame()

    df = pd.DataFrame(all_data)
    df["sale_date"] = pd.to_datetime(df["sale_date"])
    if "style_code" not in df.columns or df["style_code"].isnull().all():
        df["style_code"] = df["product_code"].str[:8]
    else:
        df["style_code"] = df["style_code"].fillna(df["product_code"].str[:8])
    for col in ["ship_amount", "return_amount", "net_amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if use_anchor and "anchor_name" in df.columns:
        df["anchor"] = df["anchor_name"].fillna("NONE")
    else:
        df["anchor"] = (
            df["remark"]
            .astype("string")
            .str.extract(r"主播[：:]([^_]+)", expand=False)
            .str.strip()
            .fillna("NONE")
        )

    # 合并线下数据（仅 _all 模式 + 需要线下时）
    if suffix == "_all" and include_offline:
        offline_data = _fetch_rows_parallel(
            "offline_sales_all",
            "sale_date,shop_name,ship_amount,return_amount,net_amount,remark",
            start_date=start_date,
            end_date=end_date,
        )
        if offline_data:
            offline_df = pd.DataFrame(offline_data)
            offline_df["sale_date"] = pd.to_datetime(offline_df["sale_date"])
            for col_name in ["product_code", "style_code", "brand", "year", "season",
                             "product_category", "style", "color_code", "size_code",
                             "image_url", "master_category"]:
                offline_df[col_name] = None
            offline_df["remark"] = offline_df["remark"].fillna("线下收入")
            offline_df["anchor"] = "NONE"
            for col in df.columns:
                if col not in offline_df.columns:
                    offline_df[col] = None
            offline_df = offline_df[df.columns]
            df = pd.concat([df, offline_df], ignore_index=True)

    return df


def load_product_sales(
    suffix=None,
    apply_filter=True,
    include_offline=True,
    view_mode=None,
    start_date=None,
    end_date=None,
):
    """缓存优化的商品销售数据加载（权限过滤 + 部门过滤在缓存外层执行）"""
    suffix = suffix or st.session_state.get("table_suffix", "_all")
    df = _load_product_sales_raw(suffix, include_offline, start_date, end_date)
    if df.empty:
        return df

    # 组织/部门映射（不在缓存内，因为依赖 session_state 的 mapping 表变化）
    mapping_df = load_dimension_mapping()
    if suffix == "_all" and not mapping_df.empty:
        df = _attach_dimensions(df, mapping_df)
    else:
        df["org_name"] = "未分配组织"
        df["dept"] = "未分配部门"

    # view_mode 过滤
    view_mode_to_use = view_mode if view_mode is not None else st.session_state.get("view_mode")
    if view_mode_to_use == "shop":
        df = df[df.get('dept') == '小店运营']

    # 权限过滤
    if apply_filter:
        from core.utils import apply_data_permission
        df = apply_data_permission(df)

    return df


PRODUCT_CUBE_CACHE_VERSION = 2


@st.cache_data(ttl=300, show_spinner=False)
def load_newbie_coupon_candidates(start_date, end_date, data_version=None):
    """读取首单礼金候选所需的双平台货号聚合数据。"""
    if supabase is None:
        return pd.DataFrame()
    rows = []
    page = 0
    while True:
        response = (
            supabase.rpc(
                "get_newbie_coupon_candidates",
                {
                    "p_start_date": start_date.isoformat(),
                    "p_end_date": end_date.isoformat(),
                },
            )
            .order("style_code")
            .range(page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1)
            .execute()
        )
        page_rows = response.data or []
        rows.extend(page_rows)
        if len(page_rows) < PAGE_SIZE:
            break
        page += 1
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    amount_columns = [
        column for column in result.columns
        if column.endswith(("_ship", "_return", "_net"))
    ]
    for column in amount_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
    return result


@st.cache_data(ttl=60, show_spinner=False)
def _load_product_sales_cube_rpc(start_date, end_date, data_version, department=None):
    """从数据库读取日级商品聚合；RPC 未部署时返回 None 触发兼容降级。"""
    if supabase is None:
        return None
    try:
        # PostgREST/Supabase 单次最多返回 1000 行，月份数据必须显式分页，
        # 否则会出现“本月商品反而少于近 7 天”的截断现象。
        rows = []
        page = 0
        while True:
            query = supabase.rpc(
                    "get_product_sales_cube",
                    {
                        "p_start_date": start_date.isoformat(),
                        "p_end_date": end_date.isoformat(),
                    },
                )
            # 显式指定完整且稳定的排序键，确保 PostgREST 对 RPC 结果分页时
            # 不会因为同日期/同货号存在多条维度记录而跨页重复或遗漏。
            for order_column in [
                "sale_date", "style_code", "dept", "org_name", "shop_name", "anchor"
            ]:
                query = query.order(order_column)
            if department:
                query = query.eq("dept", department)
            response = query.range(
                page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1
            ).execute()
            page_rows = response.data or []
            rows.extend(page_rows)
            if len(page_rows) < PAGE_SIZE:
                break
            page += 1
        if not rows:
            return pd.DataFrame()
        cube = pd.DataFrame(rows)
        cube["sale_date"] = pd.to_datetime(cube["sale_date"])
        for column in ["ship_amount", "return_amount", "net_amount", "order_count"]:
            cube[column] = pd.to_numeric(cube[column], errors="coerce").fillna(0)
        return cube
    except Exception as exc:
        # 异常不进入 Streamlit 缓存，SQL 部署后无需等待失败缓存过期。
        raise RuntimeError("商品聚合 RPC 尚不可用") from exc


def load_product_sales_cube(start_date, end_date, apply_filter=True, department=None):
    """商品分析专用数据源：优先使用数据库日级聚合，未部署时自动使用旧明细聚合。"""
    # 常量参与缓存键。查询实现升级或线上残留旧缓存时递增该版本，
    # 可强制所有 Streamlit Cloud 会话重新读取完整数据。
    data_version = (
        PRODUCT_CUBE_CACHE_VERSION,
        st.session_state.get("_data_version", 0),
    )
    try:
        cube = _load_product_sales_cube_rpc(start_date, end_date, data_version, department)
    except RuntimeError:
        cube = None

    if cube is None:
        raw = load_product_sales(
            "_all",
            apply_filter=False,
            include_offline=False,
            start_date=start_date,
            end_date=end_date,
        )
        if raw.empty:
            return raw
        if "anchor_display" not in raw.columns:
            anchor = raw.get("anchor", pd.Series("NONE", index=raw.index)).fillna("NONE").astype(str)
            missing = anchor.str.upper().isin(["", "NONE", "NAN", "<NA>"])
            raw["anchor_display"] = anchor
            raw.loc[missing, "anchor_display"] = (
                "未识别主播｜" + raw.loc[missing, "shop_name"].fillna("未知店铺").astype(str)
            )
        group_columns = [
            "sale_date", "style_code", "brand", "dept", "org_name",
            "shop_name", "anchor", "anchor_display",
        ]
        cube = raw.groupby(group_columns, dropna=False, as_index=False).agg(
            ship_amount=("ship_amount", "sum"),
            return_amount=("return_amount", "sum"),
            net_amount=("net_amount", "sum"),
            order_count=("remark", "nunique"),
        )

    if department and "dept" in cube.columns:
        cube = cube[cube["dept"].fillna("").astype(str).str.strip() == department]

    if cube.empty:
        return cube
    if apply_filter:
        from core.utils import apply_data_permission
        cube = apply_data_permission(cube)
    return cube


@st.cache_data(ttl=600, show_spinner=False)
def load_sold_style_codes(suffix="_all"):
    """读取销售明细中实际出现过的全部货号，作为商品档案完整性检查基准。"""
    if supabase is None:
        return pd.DataFrame(columns=["style_code"])
    if suffix == "_all":
        try:
            rows = []
            page = 0
            while True:
                response = (
                    supabase.table("sales_style_catalog")
                    .select("style_code")
                    .order("style_code")
                    .range(page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1)
                    .execute()
                )
                page_rows = response.data or []
                rows.extend(page_rows)
                if len(page_rows) < PAGE_SIZE:
                    break
                page += 1
            return pd.DataFrame(rows, columns=["style_code"])
        except Exception:
            # 数据库视图尚未创建时兼容旧环境。
            pass
    table_name = get_table_name("product_sales", suffix)
    rows = _fetch_rows_parallel(table_name, "style_code,product_code")
    if not rows:
        return pd.DataFrame(columns=["style_code"])
    result = pd.DataFrame(rows)
    if "style_code" not in result.columns:
        result["style_code"] = None
    if "product_code" in result.columns:
        fallback = result["product_code"].astype("string").str[:8]
        result["style_code"] = result["style_code"].fillna(fallback)
    result["style_code"] = result["style_code"].astype("string").str.strip().str.upper()
    result = result[~result["style_code"].isin(["", "nan", "None", "<NA>"])]
    return result[["style_code"]].drop_duplicates().sort_values("style_code").reset_index(drop=True)

# ---------- 获取日期范围 ----------
@st.cache_data(ttl=120)
def get_sales_date_range(suffix=""):
    if supabase is None:
        return None, None
    for attempt in range(3):
        try:
            table_name = get_table_name("product_sales", suffix)
            min_resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=False).limit(1).execute()
            max_resp = supabase.table(table_name).select("sale_date").order("sale_date", desc=True).limit(1).execute()
            min_date = pd.to_datetime(min_resp.data[0]["sale_date"]).date() if min_resp.data else None
            max_date = pd.to_datetime(max_resp.data[0]["sale_date"]).date() if max_resp.data else None
            if suffix == "_all":
                try:
                    offline_min = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=False).limit(1).execute()
                    offline_max = supabase.table("offline_sales_all").select("sale_date").order("sale_date", desc=True).limit(1).execute()
                    if offline_min.data and offline_max.data:
                        off_min = pd.to_datetime(offline_min.data[0]["sale_date"]).date()
                        off_max = pd.to_datetime(offline_max.data[0]["sale_date"]).date()
                        if min_date is None or off_min < min_date:
                            min_date = off_min
                        if max_date is None or off_max > max_date:
                            max_date = off_max
                except:
                    pass
            return min_date, max_date
        except Exception as e:
            if attempt == 2:
                st.error(f"获取日期范围失败：{e}")
                return None, None
            time.sleep(0.5)
    return None, None

# ---------- 商品主数据加载 ----------
@st.cache_data(ttl=300)
def load_product_master():
    if supabase is None:
        return pd.DataFrame()
    try:
        all_data = []
        page = 0
        page_size = 1000
        while True:
            resp = supabase.table("product_master").select("*").range(page*page_size, (page+1)*page_size-1).execute()
            if not resp.data:
                break
            all_data.extend(resp.data)
            if len(resp.data) < page_size:
                break
            page += 1
        if all_data:
            df = pd.DataFrame(all_data)
            if "has_newbie_coupon" not in df.columns:
                df["has_newbie_coupon"] = False
            if "tags" not in df.columns:
                df["tags"] = df["has_newbie_coupon"].map(
                    lambda flag: ["首单礼金"] if bool(flag) else []
                )
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"加载商品库失败：{e}")
        return pd.DataFrame()

# ---------- 组织目标管理 ----------
@st.cache_data(ttl=300)
def load_org_targets(suffix=None):
    if supabase is None:
        return {}
    try:
        table_name = get_table_name("arg_targets", suffix)
        resp = supabase.table(table_name).select("*").execute()
        if resp.data:
            return {row["org_name"]: row["target_amount"] for row in resp.data}
        else:
            return {}
    except Exception as e:
        st.error(f"加载组织目标失败：{e}")
        return {}

def save_org_targets(target_dict, suffix=None):
    if supabase is None:
        return
    records = [{"org_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        table_name = get_table_name("arg_targets", suffix)
        supabase.table(table_name).upsert(records, on_conflict="org_name").execute()

def clear_org_targets(suffix=None):
    if supabase:
        table_name = get_table_name("arg_targets", suffix)
        supabase.table(table_name).delete().neq("id", 0).execute()

# ---------- 店铺目标管理 ----------
def load_targets(suffix=None):
    if supabase is None:
        return {}
    try:
        table_name = get_table_name("shop_targets", suffix)
        resp = supabase.table(table_name).select("*").execute()
        if resp.data:
            return {row["shop_name"]: row["target_amount"] for row in resp.data}
        else:
            return {}
    except:
        return {}

def save_targets(target_dict, suffix=None):
    if supabase is None:
        return
    records = [{"shop_name": k, "target_amount": v} for k, v in target_dict.items()]
    if records:
        table_name = get_table_name("shop_targets", suffix)
        supabase.table(table_name).upsert(records, on_conflict="shop_name").execute()

def clear_targets(suffix=None):
    if supabase:
        table_name = get_table_name("shop_targets", suffix)
        supabase.table(table_name).delete().neq("id", 0).execute()
    st.session_state.target_dict = {}
    st.rerun()
