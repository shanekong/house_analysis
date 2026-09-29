from pathlib import Path
import tempfile
import unittest

from house_analysis.collectors.hangzhou_official import parse_listing_payload
from house_analysis.collectors.tmsf import TmsfAccessBlocked, parse_community_detail, parse_saved_html


DETAIL_HTML = """
<html><body>
<div class="house_guess">
  <div class="rectItem fl">
    <div class="textBox">
      <div class="line1"><a class="houseName" href="/esf/xq_csUpgrade_70314137.htm">测试小区东边套</a></div>
      <div class="houseTag"><span class="lightblueTag">产权核验</span><span>满五年</span></div>
      <a class="line2" href="/esf/xq_csUpgrade_70314137.htm">3室2厅 | 154.95㎡ | 朝南</a>
      <div class="price"><span>1350</span>万<text>87125元/㎡</text></div>
    </div>
  </div>
  <div class="rectItem fl">
    <div class="textBox">
      <a class="houseName" href="/esf/xq_csUpgrade_70192653.htm">测试小区两房</a>
      <a class="line2">2室2厅 | 89.81㎡ | 朝南</a>
      <div class="price"><span>696</span>万<text>77497元/㎡</text></div>
    </div>
  </div>
</div>
<div class="recommend"><a href="/esf/xq_csUpgrade_99999999.htm">不应进入的推荐房源</a></div>
</body></html>
"""


class TmsfCollectorTest(unittest.TestCase):
    def test_parses_only_current_listing_cards(self) -> None:
        records = parse_community_detail(
            "https://www.tmsf.com/esf/xq_index_10003660.htm",
            DETAIL_HTML,
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["external_id"], "70314137")
        self.assertEqual(records[0]["total_price"], "1350")
        self.assertEqual(records[0]["unit_price"], "87125")
        self.assertEqual(records[0]["area_sqm"], "154.95")
        self.assertEqual(records[0]["bedrooms"], 3)
        self.assertTrue(records[0]["payload"]["verified_tag_visible"])

    def test_stops_on_waf_challenge(self) -> None:
        with self.assertRaises(TmsfAccessBlocked):
            parse_community_detail(
                "https://www.tmsf.com/esf/xq_index_10003660.htm",
                '<meta name="aliyun_waf_aa" content="challenge">',
            )

    def test_saved_html_returns_traceable_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tmsf.html"
            path.write_text(DETAIL_HTML, encoding="utf-8")
            raw, records = parse_saved_html(
                path,
                "https://www.tmsf.com/esf/xq_index_10003660.htm",
            )
        self.assertIn(b"house_guess", raw)
        self.assertEqual(len(records), 2)

    def test_parses_legacy_official_json_without_guessing_missing_fields(self) -> None:
        records = parse_listing_payload(
            {"list": [{"fwtybh": "HZ-001", "wtcsjg": "500", "jzmj": "100.5", "hxs": "3室2厅"}]}
        )
        self.assertEqual(records[0]["external_id"], "HZ-001")
        self.assertEqual(records[0]["total_price"], "500")
        self.assertEqual(records[0]["area_sqm"], "100.5")
        self.assertEqual(records[0]["bedrooms"], 3)


if __name__ == "__main__":
    unittest.main()
