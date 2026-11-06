"""Display new-site permissions without breaking legacy persisted values."""
NEW_PAGES = {
    'daily': ('每日明细', '📋 每日明细', ('每日明细',)),
    'organization': ('组织分析', '🏢 组织与部门分析', ('组织分析', '组织与部门分析')),
    'products': ('商品分析（含抖店数据，当前联动）', '📦 商品分析',
                 ('商品分析', '商品分析助手', '商品销售对比', '销售分布与品牌')),
    'promotion': ('推广参考', '📣 推广参考', ('推广参考',)),
}
DEFAULT_PAGES = ['daily', 'organization', 'products']


def permission_values(permissions):
    if not isinstance(permissions, dict):
        return []
    value = permissions.get('_all', permissions.get('', []))
    return [p for p in value if isinstance(p, str)] if isinstance(value, list) else []


def recognized(value):
    return any(alias in value for _, _, aliases in NEW_PAGES.values() for alias in aliases)


def selected_pages(permissions):
    values = permission_values(permissions)
    return [key for key, (_, _, aliases) in NEW_PAGES.items()
            if any(alias in value for value in values for alias in aliases)]


def merge_permissions(original, selected):
    result = dict(original) if isinstance(original, dict) else {}
    # Preserve unknown historical grants and all policy metadata, including LK.
    values = [p for p in permission_values(original) if not recognized(p)]
    values.extend(NEW_PAGES[key][1] for key in NEW_PAGES if key in selected)
    result['_all'] = list(dict.fromkeys(values))
    if '' in result:
        result[''] = list(result['_all'])
    return result


def visible_new_pages(permissions, selected):
    names = []
    for key in NEW_PAGES:
        if key in selected:
            names.extend(['商品分析', '抖店数据'] if key == 'products'
                         else [NEW_PAGES[key][0]])
    policy = permissions.get('_ui', {}) if isinstance(permissions, dict) else {}
    allowed = policy.get('pageAllowList') if isinstance(policy, dict) else None
    return [name for name in names if not isinstance(allowed, list) or name in allowed]
