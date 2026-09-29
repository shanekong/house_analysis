from __future__ import annotations

import unittest

from house_analysis.collectors.lianjia import (
    LianjiaAccessBlocked,
    parse_public_listing_page,
)


LISTING_PAGE = """
<html><body><ul class="sellListContent">
  <li class="clear LOGVIEWDATA LOGCLICKDATA">
    <div class="title"><a href="https://hz.lianjia.com/ershoufang/103141592653.html">耀江文鼎苑两房</a></div>
    <div class="houseInfo"><a>耀江文鼎苑</a> | 2室2厅 | 92.97平米 | 南</div>
    <div class="positionInfo">高楼层(共24层) - 申花</div>
    <div class="totalPrice totalPrice2"><span>410</span><i>万</i></div>
    <div class="unitPrice"><span>单价44101元/平米</span></div>
  </li>
</ul></body></html>
"""


class LianjiaCollectorTest(unittest.TestCase):
    def test_saved_listing_page_is_normalized(self) -> None:
        records = parse_public_listing_page(
            "https://hz.lianjia.com/ershoufang/c1811043641525/",
            LISTING_PAGE,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_id"], "103141592653")
        self.assertEqual(records[0]["total_price"], "410")
        self.assertEqual(records[0]["unit_price"], "44101")
        self.assertEqual(records[0]["area_sqm"], "92.97")
        self.assertEqual(records[0]["bedrooms"], 2)
        self.assertEqual(records[0]["payload"]["listing_status"], "observed")

    def test_forbidden_page_is_reported_explicitly(self) -> None:
        with self.assertRaises(LianjiaAccessBlocked):
            parse_public_listing_page(
                "https://hz.lianjia.com/ershoufang/c1811043641525/",
                "<html><body>访问已被拦截 · 贝壳信息安全中心</body></html>",
            )


if __name__ == "__main__":
    unittest.main()
