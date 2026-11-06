import copy
import unittest
from core.account_permissions import (
    NEW_PAGES, DEFAULT_PAGES, merge_permissions, selected_pages,
    permission_values, visible_new_pages,
)


class AccountPermissionTests(unittest.TestCase):
    def test_old_aliases_are_recognized(self):
        original = {'_all': ['📋 每日明细', '🏢 组织与部门分析', '🔀 商品销售对比', '📣 推广参考']}
        self.assertEqual(selected_pages(original), list(NEW_PAGES))

    def test_defaults_do_not_grant_admin(self):
        result = merge_permissions({}, DEFAULT_PAGES)
        self.assertEqual(visible_new_pages(result, DEFAULT_PAGES), ['每日明细', '组织分析', '商品分析', '抖店数据'])
        self.assertNotIn('role', result)
        self.assertNotIn('⚙️ 系统设置', result['_all'])
        self.assertNotIn('📚 商品信息管理', result['_all'])
        self.assertNotIn('访问统计', visible_new_pages(result, list(NEW_PAGES)))

    def test_clearing_new_pages_preserves_unknown_grants_and_policy(self):
        original = {'_all': ['📊 经营驾驶舱', '📋 每日明细', '📦 商品分析'],
                    '_ui': {'pageAllowList': ['每日明细'], 'defaultDailyScope': 'department'},
                    'other_scope': ['untouched']}
        snapshot = copy.deepcopy(original)
        result = merge_permissions(original, [])
        self.assertEqual(result['_all'], ['📊 经营驾驶舱'])
        self.assertEqual(result['_ui'], original['_ui'])
        self.assertEqual(result['other_scope'], ['untouched'])
        self.assertEqual(original, snapshot)

    def test_legacy_empty_key_does_not_restore_revoked_permissions(self):
        result = merge_permissions({'': ['📦 商品分析']}, [])
        self.assertEqual(result['_all'], [])
        self.assertEqual(result[''], [])

    def test_removing_product_access_removes_every_alias(self):
        result = merge_permissions({'_all': ['商品分析助手', '商品销售对比', '销售分布与品牌', '每日明细']}, ['daily'])
        self.assertEqual(result['_all'], ['📋 每日明细'])
        self.assertEqual(selected_pages(result), ['daily'])

    def test_specific_lk_page_policy_is_preserved_and_applied(self):
        original = {'_all': ['📦 商品分析'], '_ui': {
            'pageAllowList': ['每日明细', '组织分析', '商品分析'],
            'organizationDimensions': ['department', 'organization'],
            'defaultOrganizationDimension': 'department'}}
        result = merge_permissions(original, list(NEW_PAGES))
        self.assertEqual(result['_ui'], original['_ui'])
        self.assertEqual(visible_new_pages(result, list(NEW_PAGES)), ['每日明细', '组织分析', '商品分析'])

    def test_empty_all_overrides_legacy_key(self):
        self.assertEqual(permission_values({'_all': [], '': ['商品分析']}), [])


if __name__ == '__main__':
    unittest.main()
