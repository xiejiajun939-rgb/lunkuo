# -*- coding: utf-8 -*-
"""手动导入采集工具生成的直播数据目录。重复运行会按唯一键更新。"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.live_analytics import import_live_folder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="包含database/直播数据.db的目录")
    parser.add_argument("--anchor", default=None, help="主播姓名；默认读取JSON中的account_name")
    args = parser.parse_args()
    result = import_live_folder(args.folder, anchor_name=args.anchor)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
