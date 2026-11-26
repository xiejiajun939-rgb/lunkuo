import unittest
from streamlit.testing.v1 import AppTest

APP = '''
import os
from types import SimpleNamespace
from unittest.mock import patch
import streamlit as st
from core.platform_products import render_platform_import
class Client:
    def rpc(self, name, params):
        st.session_state['calls'] = st.session_state.get('calls', 0) + 1
        if st.session_state.get('fail', False):
            raise RuntimeError('test transport failure')
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[
            dict(report_date='2026-11-25', shop_name='test shop', scope='全部', row_count=10)]))
with patch.dict(os.environ, {'SUPABASE_URL':'https://example.invalid', 'SUPABASE_SECRET_KEY':'test-not-a-real-key'}):
    with patch('supabase.create_client', return_value=Client()):
        render_platform_import()
'''

class DatesUiTests(unittest.TestCase):
    def test_refresh_cache_and_stale_error(self):
        app = AppTest.from_string(APP).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state['calls'], 1)
        self.assertEqual(len(app.dataframe), 1)
        app.run()
        self.assertEqual(app.session_state['calls'], 1)
        app.button(key='platform_products_refresh_dates').click().run()
        self.assertEqual(app.session_state['calls'], 2)
        app.session_state['fail'] = True
        app.button(key='platform_products_refresh_dates').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.dataframe), 1)
        self.assertIn('核查编号', app.warning[0].value)
        self.assertTrue(any('上次成功' in c.value for c in app.caption))

if __name__ == '__main__':
    unittest.main()
