import pandas as pd
import sys
import types

inventory_stub = types.ModuleType("core.inventory")
inventory_stub.render_inventory_detail = lambda *args, **kwargs: None
sys.modules["core.inventory"] = inventory_stub
from core.interactive_inventory_grid import _style_column


def main() -> None:
    assert _style_column(pd.DataFrame({"货号": ["A1"]})) == "货号"
    assert _style_column(pd.DataFrame({"style_code": ["A1"]})) == "style_code"
    assert _style_column(pd.DataFrame({"商品货号": ["A1"]})) == "商品货号"
    assert _style_column(pd.DataFrame({"其他": ["A1"]})) is None
    print("interactive inventory grid checks passed")


if __name__ == "__main__":
    main()
