from datetime import date
import io
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core.inventory as inventory


class Uploaded:
    name = "inventory.xlsx"

    def __init__(self, value: bytes):
        self._value = value

    def getvalue(self):
        return self._value


def main():
    source = pd.DataFrame([
        {"仓库代码": "000", "仓库名称": "总仓", "SKU": "A001REDM", "商品代码": "A001", "颜色代码": "01", "颜色名称": "红", "尺码代码": "02", "尺码名称": "M", "可用数": 3},
        {"仓库代码": "000", "仓库名称": "总仓", "SKU": "A001REDM", "商品代码": "A001", "颜色代码": "01", "颜色名称": "红", "尺码代码": "02", "尺码名称": "M", "可用数": 2},
        {"仓库代码": "100", "仓库名称": "门店仓", "SKU": "A001REDM", "商品代码": "A001", "颜色代码": "01", "颜色名称": "红", "尺码代码": "02", "尺码名称": "M", "可用数": -1},
        {"仓库代码": "000", "仓库名称": "总仓", "SKU": "B001BLKS", "商品代码": "B001", "颜色代码": "02", "颜色名称": "黑", "尺码代码": "01", "尺码名称": "S", "可用数": 9},
    ])
    output = io.BytesIO()
    source.to_excel(output, index=False)
    original = inventory.load_product_master
    inventory.load_product_master = lambda: pd.DataFrame({"style_code": ["A001"]})
    try:
        frame, stats = inventory.parse_inventory_workbook(Uploaded(output.getvalue()), date(2026, 9, 22))
    finally:
        inventory.load_product_master = original
    assert stats["matched_styles"] == 1
    assert stats["skipped_styles"] == 1
    assert stats["saved_rows"] == 2
    assert stats["negative_rows"] == 1
    assert frame.loc[frame["warehouse_name"] == "总仓", "available_qty"].iloc[0] == 5
    assert set(frame["style_code"]) == {"A001"}
    print("inventory parser checks passed")


if __name__ == "__main__":
    main()
