from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .config import database_url
from .collectors.osm import DEFAULT_OVERPASS_URL, collect_xihu_communities
from .collectors.lianjia import LianjiaAccessBlocked, fetch_and_parse_listing
from .collectors.hangzhou_official import OfficialPlatformUnavailable, fetch_public_listings
from .collectors.tmsf import TmsfAccessBlocked, fetch_and_parse_community
from .db import create_database_engine, session_scope, upgrade_database
from .market_pipeline import run_market_update
from .quality import build_community_quality_report, build_quality_report
from .seed import import_communities_csv, import_lianjia_html_snapshot, import_market_observations_csv, import_market_snapshot_json, import_tmsf_html_snapshot, seed_reference_data, set_community_completion_year, upsert_market_observation, verify_community


def _print(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="杭州住宅分析数据库工具")
    parser.add_argument("--database-url", default=database_url(), help="SQLAlchemy 数据库连接地址")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="执行数据库迁移")
    subparsers.add_parser("seed-reference", help="写入西湖区范围、来源和指标定义")
    subparsers.add_parser("quality-report", help="输出数据库质量概览")
    community_quality = subparsers.add_parser("community-quality", help="输出单个小区完整性审计")
    community_quality.add_argument("name", nargs="?", help="小区标准名称")
    community_quality.add_argument("--community-id")

    verify = subparsers.add_parser("verify-community", help="写入已人工复核的小区身份字段并标记 verified")
    verify.add_argument("community_id")
    verify.add_argument("--address", required=True)
    verify.add_argument("--longitude", required=True)
    verify.add_argument("--latitude", required=True)
    verify.add_argument("--market-area", required=True, dest="market_area")
    verify.add_argument("--source-code", default="manual_csv")
    verify.add_argument("--source-url", required=True)
    verify.add_argument("--source-external-id", required=True)
    verify.add_argument("--first-completed-year", type=int)

    completion_year = subparsers.add_parser("set-community-completion-year", help="写入有独立来源证据的小区首期竣工年份")
    completion_year.add_argument("community_id")
    completion_year.add_argument("year", type=int)
    completion_year.add_argument("--source-code", required=True)
    completion_year.add_argument("--source-url", required=True)

    importer = subparsers.add_parser("import-communities", help="从 CSV 幂等导入小区主数据")
    importer.add_argument("csv_path", type=Path)
    importer.add_argument("--source-code", default="manual_csv")

    market_importer = subparsers.add_parser(
        "import-market-observations", help="从 CSV 幂等导入成交或挂牌观察"
    )
    market_importer.add_argument("csv_path", type=Path)
    market_importer.add_argument("--source-code", default="manual_csv")

    snapshot = subparsers.add_parser("import-market-snapshot", help="导入经审核的公开市场 JSON 快照")
    snapshot.add_argument("json_path", type=Path)
    snapshot.add_argument("--source-code", required=True)

    lianjia = subparsers.add_parser("collect-lianjia-listing", help="抓取一个链家公开房源详情并幂等写入挂牌观察")
    lianjia.add_argument("community_id")
    lianjia.add_argument("url")

    lianjia_html = subparsers.add_parser(
        "import-lianjia-html",
        help="导入在正常浏览器中保存的链家二手房列表 HTML",
    )
    lianjia_html.add_argument("community_id")
    lianjia_html.add_argument("html_path", type=Path)
    lianjia_html.add_argument("--source-url", required=True)

    tmsf = subparsers.add_parser(
        "collect-tmsf-community",
        help="低频抓取一个透明售房网公开小区详情页；触发 WAF 后立即停止",
    )
    tmsf.add_argument("community_id")
    tmsf.add_argument("url")

    tmsf_html = subparsers.add_parser(
        "import-tmsf-html",
        help="导入在正常浏览器中保存的透明售房网小区详情完整 HTML",
    )
    tmsf_html.add_argument("community_id")
    tmsf_html.add_argument("html_path", type=Path)
    tmsf_html.add_argument("--source-url", required=True)

    official = subparsers.add_parser(
        "collect-hangzhou-official",
        help="低频探测并抓取杭州二手房交易监管服务平台公开旧接口",
    )
    official.add_argument("community_id")
    official.add_argument("keyword")
    official.add_argument("--page", type=int, default=1)

    market_update = subparsers.add_parser(
        "update-community-market",
        help="按链家、我爱我家、透明售房网策略执行一次小区市场更新",
    )
    market_update.add_argument("community_id")
    market_update.add_argument("--lianjia-url")
    market_update.add_argument("--woaiwojia-snapshot", type=Path)
    market_update.add_argument("--tmsf-snapshot", type=Path)
    market_update.add_argument("--tmsf-url")
    market_update.add_argument("--official-keyword")

    osm = subparsers.add_parser("collect-osm-xihu", help="从 Overpass 获取西湖区开放住宅候选对象")
    osm.add_argument("--endpoint", default=DEFAULT_OVERPASS_URL)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init-db":
        upgrade_database(args.database_url)
        _print({"status": "ok", "database_url": args.database_url})
        return 0

    engine = create_database_engine(args.database_url)
    with session_scope(engine) as session:
        if args.command == "seed-reference":
            _print(seed_reference_data(session))
        elif args.command == "import-communities":
            _print(import_communities_csv(session, args.csv_path, args.source_code))
        elif args.command == "import-market-observations":
            _print(import_market_observations_csv(session, args.csv_path, args.source_code))
        elif args.command == "import-market-snapshot":
            _print(import_market_snapshot_json(session, args.json_path, args.source_code))
        elif args.command == "collect-lianjia-listing":
            try:
                record = fetch_and_parse_listing(args.url)
            except LianjiaAccessBlocked as exc:
                _print({
                    "status": "blocked",
                    "source": "lianjia_public",
                    "message": str(exc),
                    "fallback": "import-lianjia-html",
                })
                return 3
            _print(upsert_market_observation(session, community_id=args.community_id, source_code="lianjia_public", record=record))
        elif args.command == "import-lianjia-html":
            _print(import_lianjia_html_snapshot(session, args.html_path, args.community_id, args.source_url))
        elif args.command == "collect-tmsf-community":
            try:
                _raw, records = fetch_and_parse_community(args.url)
            except TmsfAccessBlocked as exc:
                _print({
                    "status": "blocked",
                    "source": "tmsf_public",
                    "message": str(exc),
                    "circuit_open": True,
                    "fallback": "import-tmsf-html",
                })
                return 3
            created = updated = 0
            for record in records:
                result = upsert_market_observation(
                    session,
                    community_id=args.community_id,
                    source_code="tmsf_public",
                    record=record,
                )
                created += result["created"]
                updated += result["updated"]
            _print({"status": "succeeded", "seen": len(records), "created": created, "updated": updated})
        elif args.command == "import-tmsf-html":
            _print(import_tmsf_html_snapshot(session, args.html_path, args.community_id, args.source_url))
        elif args.command == "collect-hangzhou-official":
            try:
                _raw, records = fetch_public_listings(args.keyword, args.page)
            except OfficialPlatformUnavailable as exc:
                _print({
                    "status": "unavailable",
                    "source": "hangzhou_secondhand_official",
                    "message": str(exc),
                    "circuit_open": True,
                })
                return 4
            created = updated = 0
            for record in records:
                result = upsert_market_observation(
                    session,
                    community_id=args.community_id,
                    source_code="hangzhou_secondhand_official",
                    record=record,
                )
                created += result["created"]
                updated += result["updated"]
            _print({"status": "succeeded", "seen": len(records), "created": created, "updated": updated})
        elif args.command == "update-community-market":
            _print(run_market_update(
                session,
                community_id=args.community_id,
                lianjia_url=args.lianjia_url,
                woaiwojia_snapshot=args.woaiwojia_snapshot,
                tmsf_snapshot=args.tmsf_snapshot,
                tmsf_url=args.tmsf_url,
                official_keyword=args.official_keyword,
            ))
        elif args.command == "quality-report":
            _print(build_quality_report(session))
        elif args.command == "community-quality":
            _print(build_community_quality_report(session, name=args.name, community_id=args.community_id))
        elif args.command == "verify-community":
            _print(verify_community(session, community_id=args.community_id, address=args.address, longitude=args.longitude, latitude=args.latitude, market_area_name=args.market_area, source_code=args.source_code, source_url=args.source_url, source_external_id=args.source_external_id, first_completed_year=args.first_completed_year))
        elif args.command == "set-community-completion-year":
            _print(set_community_completion_year(session, community_id=args.community_id, year=args.year, source_code=args.source_code, source_url=args.source_url))
        elif args.command == "collect-osm-xihu":
            _print(collect_xihu_communities(session, args.endpoint))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
