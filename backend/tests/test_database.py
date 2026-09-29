from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import func, select

from house_analysis.db import create_database_engine, session_scope, upgrade_database
from house_analysis.collectors.osm import ingest_osm_payload
from house_analysis.models import (
    Community,
    CommunityAlias,
    MarketArea,
    MarketObservation,
    MetricDefinition,
    RawSnapshot,
    SourceRecord,
)
from house_analysis.collectors.lianjia import LianjiaAccessBlocked
from house_analysis.market_pipeline import run_market_update
from house_analysis.quality import build_community_quality_report, build_quality_report
from house_analysis.seed import import_communities_csv, import_lianjia_html_snapshot, import_market_observations_csv, import_market_snapshot_json, import_tmsf_html_snapshot, seed_reference_data, set_community_completion_year, verify_community


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.database_url = f"sqlite:///{self.database_path}"
        upgrade_database(self.database_url)
        self.engine = create_database_engine(self.database_url)
        with session_scope(self.engine) as session:
            seed_reference_data(session)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _write_csv(self) -> Path:
        path = Path(self.temp_dir.name) / "communities.csv"
        columns = [
            "source_record_id", "standard_name", "alias_names", "address", "street_name",
            "property_type", "status", "longitude", "latitude", "first_completed_year",
            "data_confidence",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerow({
                "source_record_id": "example-001",
                "standard_name": "测试小区",
                "alias_names": "测试花园|测试家园",
                "address": "测试路1号",
                "street_name": "测试街道",
                "property_type": "residential",
                "status": "completed",
                "longitude": "120.1234567",
                "latitude": "30.1234567",
                "first_completed_year": "2008",
                "data_confidence": "medium",
            })
        return path

    def test_import_is_idempotent_and_quality_is_reported(self) -> None:
        csv_path = self._write_csv()
        with session_scope(self.engine) as session:
            first = import_communities_csv(session, csv_path)
        with session_scope(self.engine) as session:
            second = import_communities_csv(session, csv_path)
        with session_scope(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Community)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(CommunityAlias)), 3)
            report = build_quality_report(session)

        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(report["market_areas"], 1)
        self.assertEqual(report["metric_definitions"], 6)
        self.assertEqual(report["coverage"]["coordinates_percent"], 100.0)

    def test_reference_seed_is_idempotent(self) -> None:
        with session_scope(self.engine) as session:
            result = seed_reference_data(session)
        with session_scope(self.engine) as session:
            market_area_count = session.scalar(select(func.count()).select_from(MarketArea))
            metric_count = session.scalar(select(func.count()).select_from(MetricDefinition))

        self.assertEqual(result["market_areas_created"], 0)
        self.assertEqual(result["metrics_created"], 0)
        self.assertEqual(market_area_count, 1)
        self.assertEqual(metric_count, 6)

    def test_verify_community_requires_identity_fields_and_promotes_status(self) -> None:
        csv_path = self._write_csv()
        with session_scope(self.engine) as session:
            import_communities_csv(session, csv_path)
            community = session.scalar(select(Community).where(Community.standard_name == "测试小区"))
            result = verify_community(
                session,
                community_id=community.id,
                address="测试路1号",
                longitude="120.1234567",
                latitude="30.1234567",
                market_area_name="申花",
                source_code="manual_csv",
                source_url="https://example.test/community/1",
                source_external_id="review-1",
                first_completed_year=2008,
            )
            self.assertEqual(result["verification_status"], "verified")
            year_result = set_community_completion_year(session, community_id=community.id, year=2007, source_code="woaiwojia_public", source_url="https://example.test/community/year")
            self.assertEqual(year_result["first_completed_year"], 2007)
        with session_scope(self.engine) as session:
            community = session.get(Community, community.id)
            self.assertEqual(community.verification_status, "verified")
            self.assertIsNotNone(community.market_area_id)
            self.assertEqual(community.first_completed_year, 2007)

    def test_market_observation_import_is_idempotent_and_separates_listing(self) -> None:
        community_csv = self._write_csv()
        market_csv = Path(self.temp_dir.name) / "market.csv"
        columns = ["community_name", "external_id", "observation_type", "observed_at", "event_date", "total_price", "unit_price", "area_sqm", "bedrooms", "floor_text", "source_url", "confidence"]
        with market_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerow({"community_name": "测试小区", "external_id": "lj-1", "observation_type": "listing", "observed_at": "2026-09-29T10:00:00+08:00", "event_date": "2026-09-28", "total_price": "350", "unit_price": "42000", "area_sqm": "83.33", "bedrooms": "2", "floor_text": "中楼层", "source_url": "https://hz.lianjia.com/ershoufang/lj-1.html", "confidence": "medium"})
        with session_scope(self.engine) as session:
            import_communities_csv(session, community_csv)
            community = session.scalar(select(Community).where(Community.standard_name == "测试小区"))
            first = import_market_observations_csv(session, market_csv, "lianjia_public")
            second = import_market_observations_csv(session, market_csv, "lianjia_public")
            self.assertEqual(first["created"], 1)
            self.assertEqual(second["updated"], 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(MarketObservation)), 1)
        from house_analysis import server
        original_database_url = server.database_url
        server.database_url = lambda: self.database_url
        try:
            payload = server.get_community_market(community.id)
        finally:
            server.database_url = original_database_url
        self.assertEqual(payload["counts"], {"history": 0, "listings": 1})
        self.assertEqual(payload["listings"][0]["source"]["code"], "lianjia_public")
        self.assertIsNotNone(payload["data_as_of"])

    def test_reviewed_market_snapshot_preserves_raw_payload_idempotently(self) -> None:
        community_csv = self._write_csv()
        snapshot_path = Path(self.temp_dir.name) / "snapshot.json"
        with session_scope(self.engine) as session:
            import_communities_csv(session, community_csv)
            community = session.scalar(select(Community).where(Community.standard_name == "测试小区"))
        snapshot_path.write_text(json.dumps({"community_id": community.id, "source_url": "https://example.test/listings", "observed_at": "2026-09-29T10:00:00+08:00", "records": [{"external_id": "listing-1", "observation_type": "listing", "observed_at": "2026-09-29T10:00:00+08:00", "total_price": "300", "source_url": "https://example.test/listing-1"}]}), encoding="utf-8")
        with session_scope(self.engine) as session:
            first = import_market_snapshot_json(session, snapshot_path, "woaiwojia_public")
        with session_scope(self.engine) as session:
            second = import_market_snapshot_json(session, snapshot_path, "woaiwojia_public")
            self.assertEqual(session.scalar(select(func.count()).select_from(RawSnapshot)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(MarketObservation)), 1)
        self.assertEqual(first["snapshot_created"], 1)
        self.assertEqual(second["snapshot_created"], 0)
        self.assertEqual(second["updated"], 1)

    def test_browser_saved_lianjia_html_is_traceable_and_idempotent(self) -> None:
        community_csv = self._write_csv()
        html_path = Path(self.temp_dir.name) / "lianjia.html"
        html_path.write_text(
            '<li class="clear LOGVIEWDATA LOGCLICKDATA">'
            '<div class="title"><a href="https://hz.lianjia.com/ershoufang/103141592653.html">测试小区两房</a></div>'
            '<div class="houseInfo">测试小区 | 2室1厅 | 80.5平米 | 南</div>'
            '<div class="positionInfo">中楼层(共18层)</div>'
            '<div class="totalPrice totalPrice2"><span>300</span></div>'
            '<div class="unitPrice"><span>单价37267元/平米</span></div>'
            '</li>',
            encoding="utf-8",
        )
        with session_scope(self.engine) as session:
            import_communities_csv(session, community_csv)
            community = session.scalar(select(Community).where(Community.standard_name == "测试小区"))
            first = import_lianjia_html_snapshot(
                session,
                html_path,
                community.id,
                "https://hz.lianjia.com/ershoufang/c1811043641525/",
            )
        with session_scope(self.engine) as session:
            second = import_lianjia_html_snapshot(
                session,
                html_path,
                community.id,
                "https://hz.lianjia.com/ershoufang/c1811043641525/",
            )
            self.assertEqual(session.scalar(select(func.count()).select_from(RawSnapshot)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(MarketObservation)), 1)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(second["snapshot_created"], 0)

    def test_market_update_continues_after_lianjia_is_blocked(self) -> None:
        community_csv = self._write_csv()
        snapshot_path = Path(self.temp_dir.name) / "5i5j.json"
        with session_scope(self.engine) as session:
            import_communities_csv(session, community_csv)
            community = session.scalar(select(Community).where(Community.standard_name == "测试小区"))
        snapshot_path.write_text(
            json.dumps({
                "community_id": community.id,
                "source_url": "https://hz.5i5j.com/example",
                "observed_at": "2026-09-29T10:00:00+08:00",
                "records": [{
                    "external_id": "5i5j-listing-1",
                    "observation_type": "listing",
                    "observed_at": "2026-09-29T10:00:00+08:00",
                    "total_price": "320",
                    "source_url": "https://hz.5i5j.com/example/1",
                }],
            }),
            encoding="utf-8",
        )

        def blocked_fetcher(_url: str) -> dict[str, object]:
            raise LianjiaAccessBlocked("blocked for test")

        with session_scope(self.engine) as session:
            result = run_market_update(
                session,
                community_id=community.id,
                lianjia_url="https://hz.lianjia.com/ershoufang/1.html",
                woaiwojia_snapshot=snapshot_path,
                lianjia_fetcher=blocked_fetcher,
            )
            self.assertEqual(session.scalar(select(func.count()).select_from(MarketObservation)), 1)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["summary"], {"succeeded": 1, "blocked": 1, "failed": 0})
        self.assertEqual(result["attempts"][0]["circuit_open"], True)
        self.assertEqual(result["attempts"][1]["status"], "succeeded")

    def test_browser_saved_tmsf_html_is_traceable_and_idempotent(self) -> None:
        community_csv = self._write_csv()
        html_path = Path(self.temp_dir.name) / "tmsf.html"
        html_path.write_text(
            '<div class="house_guess"><div class="rectItem fl"><div class="textBox">'
            '<a class="houseName" href="/esf/xq_csUpgrade_70314137.htm">测试小区东边套</a>'
            '<div class="houseTag"><span>产权核验</span></div>'
            '<a class="line2">3室2厅 | 100.5㎡ | 朝南</a>'
            '<div class="price"><span>500</span>万<text>49751元/㎡</text></div>'
            '</div></div></div>',
            encoding="utf-8",
        )
        with session_scope(self.engine) as session:
            import_communities_csv(session, community_csv)
            community = session.scalar(select(Community).where(Community.standard_name == "测试小区"))
            first = import_tmsf_html_snapshot(
                session,
                html_path,
                community.id,
                "https://www.tmsf.com/esf/xq_index_10003660.htm",
            )
        with session_scope(self.engine) as session:
            second = import_tmsf_html_snapshot(
                session,
                html_path,
                community.id,
                "https://www.tmsf.com/esf/xq_index_10003660.htm",
            )
            self.assertEqual(session.scalar(select(func.count()).select_from(MarketObservation)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(RawSnapshot)), 1)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(second["snapshot_created"], 0)

    def test_community_quality_report_exposes_missing_fields(self) -> None:
        csv_path = self._write_csv()
        with session_scope(self.engine) as session:
            import_communities_csv(session, csv_path)
        with session_scope(self.engine) as session:
            report = build_community_quality_report(session, name="测试小区")

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["missing_fields"], ["market_area", "verification_status"])
        self.assertEqual(report["related_counts"]["aliases"], 3)

    def test_osm_candidates_are_deduplicated_and_traceable(self) -> None:
        payload = {
            "version": 0.6,
            "elements": [
                {
                    "type": "way",
                    "id": 101,
                    "center": {"lon": 120.1000000, "lat": 30.2000000},
                    "tags": {"name": "开放花园", "landuse": "residential"},
                },
                {
                    "type": "node",
                    "id": 102,
                    "lon": 120.1002000,
                    "lat": 30.2001000,
                    "tags": {"name": "开放花园", "place": "neighbourhood"},
                },
                {
                    "type": "relation",
                    "id": 103,
                    "center": {"lon": 120.1200000, "lat": 30.2200000},
                    "tags": {
                        "name": "许可家园",
                        "name:zh": "许可家园",
                        "landuse": "residential",
                    },
                },
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        with session_scope(self.engine) as session:
            first = ingest_osm_payload(session, raw, payload)
        with session_scope(self.engine) as session:
            second = ingest_osm_payload(session, raw, payload)
        with session_scope(self.engine) as session:
            community_count = session.scalar(select(func.count()).select_from(Community))
            mapping_count = session.scalar(select(func.count()).select_from(SourceRecord))
            snapshot_count = session.scalar(select(func.count()).select_from(RawSnapshot))
            candidates = session.scalars(select(Community)).all()

        self.assertEqual(first["created"], 2)
        self.assertEqual(first["linked_to_existing"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 3)
        self.assertEqual(community_count, 2)
        self.assertEqual(mapping_count, 3)
        self.assertEqual(snapshot_count, 1)
        self.assertTrue(all(item.verification_status == "pending" for item in candidates))


if __name__ == "__main__":
    unittest.main()
