import ast
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
import pandas as pd
from openpyxl import load_workbook
from core.admin_downloads import adjustment_template_bytes, excel_bytes

ROOT = Path(__file__).resolve().parents[1]


def tree(name):
    return ast.parse((ROOT / name).read_text(encoding='utf-8'))


class AdminLoadingTests(unittest.TestCase):
    def test_every_tab_body_is_guarded(self):
        for page, expected in [('pages/settings.py', 6), ('pages/export.py', 4)]:
            module = tree(page)
            parents = {child: node for node in ast.walk(module) for child in ast.iter_child_nodes(node)}
            tabs = [node for node in ast.walk(module) if isinstance(node, ast.With)
                    and isinstance(node.items[0].context_expr, ast.Name)
                    and node.items[0].context_expr.id.startswith('tab_')]
            self.assertEqual(len(tabs), expected)
            for node in tabs:
                name = node.items[0].context_expr.id
                guard = parents[node]
                self.assertIsInstance(guard, ast.If)
                self.assertEqual(ast.unparse(guard.test), name + '.open')
                # Inactive panels must not execute even one line of their body.
                isolated = ast.Module(body=[guard], type_ignores=[])
                exec(compile(isolated, page, 'exec'), {name: SimpleNamespace(open=False)})

    def test_tabs_enable_state_tracking(self):
        for page in ('pages/settings.py', 'pages/export.py'):
            calls = [node for node in ast.walk(tree(page)) if isinstance(node, ast.Call)
                     and ast.unparse(node.func) == 'st.tabs']
            self.assertEqual(len(calls), 1)
            keywords = {item.arg: ast.literal_eval(item.value) for item in calls[0].keywords}
            self.assertEqual(keywords['on_change'], 'rerun')
            self.assertTrue(keywords['key'])

    def test_get_account_is_one_filtered_query(self):
        fn = next(node for node in tree('websale_main.py').body
                  if isinstance(node, ast.FunctionDef) and node.name == 'get_account')
        client = MagicMock()
        query = client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value
        query.execute.return_value = SimpleNamespace(data={'username': 'admin', 'password': 'synthetic-hash'})
        env = {'supabase': client}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'get_account', 'exec'), env)
        self.assertEqual(env['get_account']('admin')['role'], 'admin')
        client.table.return_value.select.return_value.eq.assert_called_once_with('username', 'admin')
        query.execute.assert_called_once()
        query.execute.return_value = None
        self.assertIsNone(env['get_account']('missing'))

    def test_no_eager_account_or_target_reads(self):
        module = tree('websale_main.py')
        functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
        for name in ('login', 'verify_auth_token'):
            calls = [ast.unparse(node.func) for node in ast.walk(functions[name]) if isinstance(node, ast.Call)]
            self.assertNotIn('get_all_users', calls)
            self.assertIn('get_account', calls)
        initial = next(node for node in module.body if isinstance(node, ast.If)
                       and ast.unparse(node.test) == "'sub_users' not in st.session_state")
        self.assertFalse(any(isinstance(node, ast.Call) for node in ast.walk(initial)))
        nav_line = next(node.lineno for node in module.body if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'nav' for t in node.targets))
        top = ast.Module(body=[node for node in module.body if not isinstance(node, ast.FunctionDef)
                              and node.lineno < nav_line], type_ignores=[])
        self.assertNotIn('load_targets', [ast.unparse(node.func) for node in ast.walk(top) if isinstance(node, ast.Call)])

    def test_inventory_only_loads_for_manage_tab(self):
        module = tree('pages/export.py')
        parents = {child: node for node in ast.walk(module) for child in ast.iter_child_nodes(node)}
        call = next(node for node in ast.walk(module) if isinstance(node, ast.Call)
                    and ast.unparse(node.func) == 'attach_inventory_summary')
        self.assertEqual(ast.unparse(parents[parents[call]].test), 'tab_manage.open')

    def test_upload_tab_does_not_require_catalogue_by_default(self):
        assignment = next(node for node in tree('pages/export.py').body if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'needs_master' for t in node.targets))
        tabs = {name: SimpleNamespace(open=False) for name in ('tab_manage', 'tab_tags', 'tab_export')}
        for has_audit in (False, True):
            state = {'product_master_sold_styles': pd.DataFrame()} if has_audit else {}
            env = {**tabs, 'pd': pd, 'st': SimpleNamespace(session_state=state)}
            exec(compile(ast.Module(body=[assignment], type_ignores=[]), 'needs_master', 'exec'), env)
            self.assertEqual(env['needs_master'], has_audit)

    def test_adjustment_template_preserves_format(self):
        book = load_workbook(io.BytesIO(adjustment_template_bytes()))
        self.assertEqual(book.sheetnames, ['退差价匹配', '填写说明'])
        self.assertEqual(book.worksheets[0]['B2'].value, -100)
        self.assertEqual(book.worksheets[0].freeze_panes, 'A2')
        self.assertTrue(book.worksheets[0]['A1'].font.bold)

    def test_export_is_real_excel(self):
        frame = pd.DataFrame({'style_code': ['TEST0001'], 'category': ['test']})
        decoded = pd.read_excel(io.BytesIO(excel_bytes(frame, '商品库')))
        self.assertEqual(decoded.to_dict('records'), frame.to_dict('records'))


if __name__ == '__main__':
    unittest.main()
