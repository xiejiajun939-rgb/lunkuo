@st.cache_data(ttl=60)
def fetch_sales_summary(start_date, end_date, suffix="", view_mode=None):
    """
    获取销售汇总数据
    ★ 线上数据：使用 (shop_name, anchor) 匹配 mapping 表
    ★ 线下数据：使用 shop_name 直接匹配 mapping 表，按部门聚合
    """
    required_columns = ["sale_date", "org_name", "dept", "shop_name", "anchor", "total_ship", "total_return", "total_net"]
    
    if supabase is None:
        return pd.DataFrame(columns=required_columns)

    def clean_shop_names(df):
        if 'shop_name' in df.columns:
            df['shop_name'] = df['shop_name'].astype(str).str.strip().str.upper()
        return df

    # ---- 加载 mapping 表 ----
    mapping_df = load_dimension_mapping()
    mapping_exists = suffix == "_all" and not mapping_df.empty

    # ---- 构建线下映射字典：shop_name -> dept （只取 anchor_name='NONE' 的记录） ----
    offline_dept_map = {}
    if mapping_exists:
        mapping_none = mapping_df[mapping_df['anchor_name'] == 'NONE'].copy()
        mapping_none['shop_name'] = mapping_none['shop_name'].astype(str).str.strip().str.upper()
        mapping_none['dept'] = mapping_none['dept'].astype(str).str.strip().str.upper()
        # 按 shop_name 去重，保留第一个 dept
        mapping_none_unique = mapping_none.drop_duplicates(subset=['shop_name'], keep='first')
        offline_dept_map = mapping_none_unique.set_index('shop_name')['dept'].to_dict()

        # 补充：如果某些 shop_name 在 mapping_none 中找不到，尝试用 org_name 或 dept 映射
        # 构建反向映射：org_name -> dept, dept -> dept
        all_mapping = mapping_df.drop_duplicates(subset=['org_name', 'dept'], keep='first')
        org_to_dept = all_mapping.set_index('org_name')['dept'].to_dict()
        dept_to_dept = all_mapping.set_index('dept')['dept'].to_dict()
        # 合并到 offline_dept_map，优先级：shop_name > org_name > dept
        # 但 offline_dept_map 已包含 shop_name，如果缺失，则尝试 org_name 或 dept
        # 这里我们直接构建一个综合查找字典
        dept_lookup = {}
        # 先添加 shop_name -> dept
        dept_lookup.update(offline_dept_map)
        # 再添加 org_name -> dept（避免覆盖已有的 shop_name）
        for org, dept in org_to_dept.items():
            if org not in dept_lookup:
                dept_lookup[org] = dept
        # 再添加 dept -> dept
        for d, dept in dept_to_dept.items():
            if d not in dept_lookup:
                dept_lookup[d] = dept
    else:
        dept_lookup = {}

    # ---- 1. 线上数据处理 ----
    product_table = get_table_name("product_sales", suffix)
    use_anchor = True
    try:
        supabase.table(product_table).select("anchor_name").limit(1).execute()
    except Exception as e:
        if "does not exist" in str(e).lower() or "column" in str(e).lower():
            use_anchor = False
        else:
            raise

    online_data = []
    page = 0
    page_size = 1000
    while True:
        try:
            if use_anchor:
                select_cols = "sale_date, shop_name, remark, ship_amount, return_amount, net_amount, anchor_name"
            else:
                select_cols = "sale_date, shop_name, remark, ship_amount, return_amount, net_amount"
            resp = supabase.table(product_table)\
                           .select(select_cols)\
                           .gte("sale_date", start_date.isoformat())\
                           .lte("sale_date", end_date.isoformat())\
                           .range(page * page_size, (page + 1) * page_size - 1)\
                           .execute()
            if not resp.data:
                break
            online_data.extend(resp.data)
            if len(resp.data) < page_size:
                break
            page += 1
        except Exception as e:
            st.warning(f"查询线上数据出错：{e}")
            break

    # 线上聚合
    if online_data:
        df_online = pd.DataFrame(online_data)
        df_online["sale_date"] = pd.to_datetime(df_online["sale_date"])
        if use_anchor and "anchor_name" in df_online.columns:
            df_online["anchor"] = df_online["anchor_name"].fillna("NONE")
        else:
            df_online["anchor"] = df_online["remark"].apply(extract_anchor).fillna("NONE")
        df_online = df_online.groupby(["sale_date", "shop_name", "anchor"], as_index=False).agg({
            "ship_amount": "sum",
            "return_amount": "sum",
            "net_amount": "sum"
        })
        df_online = clean_shop_names(df_online)
        # 映射线上 dept
        if mapping_exists:
            mapping_df_clean = mapping_df.copy()
            mapping_df_clean['shop_name'] = mapping_df_clean['shop_name'].astype(str).str.strip().str.upper()
            mapping_df_clean['anchor_name'] = mapping_df_clean['anchor_name'].astype(str).str.strip().str.upper()
            mapping_unique = mapping_df_clean.drop_duplicates(subset=['shop_name', 'anchor_name'], keep='first')
            key_to_dept = mapping_unique.set_index(['shop_name', 'anchor_name'])['dept'].to_dict()
            key_to_org = mapping_unique.set_index(['shop_name', 'anchor_name'])['org_name'].to_dict()
            df_online['dept'] = df_online.apply(lambda row: key_to_dept.get((row['shop_name'], row['anchor']), '未分配部门'), axis=1)
            df_online['org_name'] = df_online.apply(lambda row: key_to_org.get((row['shop_name'], row['anchor']), '未分配组织'), axis=1)
        else:
            df_online['dept'] = '未分配部门'
            df_online['org_name'] = '未分配组织'
        # 按日期和部门聚合线上数据
        df_online_agg = df_online.groupby(['sale_date', 'dept'], as_index=False).agg({
            'ship_amount': 'sum',
            'return_amount': 'sum',
            'net_amount': 'sum'
        })
        df_online_agg['org_name'] = '线上汇总'  # 占位，后续可扩展
        df_online_agg['shop_name'] = '线上汇总'
        df_online_agg['anchor'] = 'NONE'
    else:
        df_online_agg = pd.DataFrame()

    # ---- 2. 线下数据处理 ----
    df_offline_agg = pd.DataFrame()
    if suffix == "_all":
        try:
            offline_resp = supabase.table("offline_sales_all").select("*").execute()
            if offline_resp.data:
                df_offline = pd.DataFrame(offline_resp.data)
                df_offline["sale_date"] = pd.to_datetime(df_offline["sale_date"])
                start_ts = pd.Timestamp(start_date)
                end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                df_offline = df_offline[(df_offline["sale_date"] >= start_ts) & (df_offline["sale_date"] <= end_ts)]
                if not df_offline.empty:
                    # 按 shop_name 汇总
                    df_offline = df_offline.groupby(["sale_date", "shop_name"], as_index=False).agg({
                        "ship_amount": "sum",
                        "return_amount": "sum",
                        "net_amount": "sum"
                    })
                    df_offline = clean_shop_names(df_offline)
                    # 映射到部门
                    df_offline['dept'] = df_offline['shop_name'].map(dept_lookup).fillna('未分配部门')
                    # 按日期和部门聚合线下数据
                    df_offline_agg = df_offline.groupby(['sale_date', 'dept'], as_index=False).agg({
                        'ship_amount': 'sum',
                        'return_amount': 'sum',
                        'net_amount': 'sum'
                    })
                    df_offline_agg['org_name'] = '线下汇总'
                    df_offline_agg['shop_name'] = '线下汇总'
                    df_offline_agg['anchor'] = 'NONE'
        except Exception as e:
            st.warning(f"查询线下数据出错：{e}")

    # ---- 3. 合并线上和线下的部门汇总 ----
    if df_online_agg.empty and df_offline_agg.empty:
        return pd.DataFrame(columns=required_columns)
    elif df_online_agg.empty:
        df = df_offline_agg
    elif df_offline_agg.empty:
        df = df_online_agg
    else:
        df = pd.concat([df_online_agg, df_offline_agg], ignore_index=True)

    # ---- 4. 重命名和确保列存在 ----
    df = df.rename(columns={
        "ship_amount": "total_ship",
        "return_amount": "total_return",
        "net_amount": "total_net"
    })

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
