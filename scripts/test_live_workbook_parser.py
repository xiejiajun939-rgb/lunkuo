"""本地回归：验证抖音店铺后台直播工作簿的关键口径。"""

from pathlib import Path

from core.live_analytics import parse_douyin_live_workbook


SAMPLE = Path(
    r"C:\Users\Administrator\Documents\罗盘直播间数据"
) / (
    "罗盘_轮廓官方旗舰店_2026-09-18074930_7686655427714616107.xlsx"
)


def main():
    parsed = parse_douyin_live_workbook(SAMPLE)
    session = parsed["session"]
    metrics = {row["metric_name"]: row["metric_value"] for row in parsed["metrics"]}
    products = parsed["products"]

    assert session["live_room_id"] == "7686655427714616107"
    assert session["anchor_name"] == "轮廓官方旗舰店"
    assert session["duration_seconds"] == 2 * 3600 + 3 * 60 + 17
    assert metrics["直播间用户支付金额"] == 25822
    assert metrics["退款金额"] == 7827
    assert metrics["商品点击人数"] == 275
    assert len(products) == len({row["product_id"] for row in products})
    assert sum(row["paid_amount"] for row in products) == 25822
    assert sum(row["pre_ship_refund_amount"] for row in products) == 7827
    assert len(parsed["channels"]) == 13
    assert len(parsed["talks"]) == 10
    assert all(row["style_code"] for row in products)
    print(
        "PASS",
        {
            "room_id": session["live_room_id"],
            "shop_name": session["shop_name"],
            "products": len(products),
            "channels": len(parsed["channels"]),
            "talks": len(parsed["talks"]),
            "paid_amount": sum(row["paid_amount"] for row in products),
            "refund_amount": sum(row["pre_ship_refund_amount"] for row in products),
        },
    )


if __name__ == "__main__":
    main()
