# 在“数据概览”展开面板中
unassigned = df_period_main[df_period_main['org_name'] == '未分配组织']
if not unassigned.empty:
    st.markdown("---")
    st.markdown("##### ⚠️ 未分配组织明细")
    st.warning("以下记录因 (shop_name, anchor) 组合在 mapping 表中无匹配，被归入'未分配组织'，请检查 mapping 表。")
    unassigned_detail = unassigned.groupby(['shop_name', 'anchor']).agg({
        'total_net': 'sum',
        'total_ship': 'sum',
        'total_return': 'sum'
    }).reset_index()
    unassigned_detail.columns = ['店铺名称', '主播', '净额', '发货额', '退货额']
    unassigned_detail['净额'] = unassigned_detail['净额'].apply(lambda x: f"¥{x:,.2f}")
    unassigned_detail['发货额'] = unassigned_detail['发货额'].apply(lambda x: f"¥{x:,.2f}")
    unassigned_detail['退货额'] = unassigned_detail['退货额'].apply(lambda x: f"¥{x:,.2f}")
    st.dataframe(unassigned_detail, hide_index=True, use_container_width=True)

# 在组织排行下方的独立展开面板中（如果存在）
unassigned_org = org_agg[org_agg['org_name'] == '未分配组织']
if not unassigned_org.empty and unassigned_org.iloc[0]['total_net'] != 0:
    with st.expander("🔍 查看“未分配组织”明细"):
        unassigned = df_period_main[df_period_main['org_name'] == '未分配组织']
        if not unassigned.empty:
            detail = unassigned.groupby(['shop_name', 'anchor']).agg({
                'total_net': 'sum',
                'total_ship': 'sum',
                'total_return': 'sum'
            }).reset_index()
            detail.columns = ['店铺', '主播', '净额', '发货额', '退货额']
            detail['净额'] = detail['净额'].apply(lambda x: f"¥{x:,.2f}")
            detail['发货额'] = detail['发货额'].apply(lambda x: f"¥{x:,.2f}")
            detail['退货额'] = detail['退货额'].apply(lambda x: f"¥{x:,.2f}")
            st.dataframe(detail, hide_index=True, use_container_width=True)
            st.caption(f"以上 {len(detail)} 条记录因 (shop_name, anchor) 无匹配，被归为'未分配组织'，请检查 mapping 表。")
