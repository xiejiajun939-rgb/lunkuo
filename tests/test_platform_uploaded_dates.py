import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from core.platform_products import (
    uploaded_platform_dates, uploaded_dates_snapshot, log_dates_error,
)


class DatesTests(unittest.TestCase):
    def client(self, rows):
        client = Mock()
        client.rpc.return_value.execute.return_value = SimpleNamespace(data=rows)
        return client

    def test_single_rpc_and_no_product_scan(self):
        rows = [dict(report_date='2026-11-25', shop_name='shop', scope='全部', row_count=80)]
        client = self.client(rows)
        result = uploaded_platform_dates(client)
        client.rpc.assert_called_once_with('get_douyin_platform_uploaded_dates', {})
        client.table.assert_not_called()
        self.assertEqual(result[0]['数据库记录数'], 80)

    def test_over_api_row_limit(self):
        client = self.client([dict(report_date='2026-11-25', shop_name=str(i),
                                   scope='全部', row_count=1) for i in range(1501)])
        self.assertEqual(len(uploaded_platform_dates(client)), 1501)
        client.rpc.assert_called_once()

    def test_empty_is_valid_but_null_is_failure(self):
        self.assertEqual(uploaded_platform_dates(self.client([])), [])
        with self.assertRaises(ValueError):
            uploaded_platform_dates(self.client(None))

    def test_cache_and_force(self):
        cached = dict(entries=[], checked_at=100, elapsed=.1)
        client = self.client([])
        result, hit = uploaded_dates_snapshot(client, cached, now=110)
        self.assertIs(result, cached)
        self.assertTrue(hit)
        client.rpc.assert_not_called()
        _, hit = uploaded_dates_snapshot(client, cached, force=True, now=110)
        self.assertFalse(hit)
        client.rpc.assert_called_once()

    def test_expiry(self):
        client = self.client([])
        _, hit = uploaded_dates_snapshot(client, dict(entries=[], checked_at=100), now=401)
        self.assertFalse(hit)

    def test_failure_does_not_replace_previous_success(self):
        cached = dict(entries=[{'数据日期': '2026-11-25'}], checked_at=100)
        client = Mock()
        client.rpc.side_effect = RuntimeError('network failed')
        with self.assertRaises(RuntimeError):
            uploaded_dates_snapshot(client, cached, force=True, now=110)
        self.assertEqual(cached['entries'], [{'数据日期': '2026-11-25'}])

    def test_logs_never_include_raw_error_or_credentials(self):
        class Failure(Exception):
            code = '57014'
        with self.assertLogs('core.platform_products', level='ERROR') as logs:
            incident = log_dates_error(Failure('SECRET URL TOKEN'), 1.5)
        output = ''.join(logs.output)
        self.assertIn('code=57014', output)
        self.assertIn(incident, output)
        self.assertNotIn('SECRET', output)


if __name__ == '__main__':
    unittest.main()
