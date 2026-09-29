from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AdministrativeArea,
    Community,
    CommunityAlias,
    CommunityFact,
    DataSource,
    IngestionRun,
    MarketArea,
    MetricDefinition,
    MarketObservation,
    RawSnapshot,
    SourceRecord,
)


SOURCE_SEEDS = [
    {
        "code": "manual_csv",
        "name": "人工审核 CSV",
        "organization": "项目维护者",
        "source_type": "manual",
        "reliability": "medium",
        "usage_notes": "人工整理或经授权导入；具体记录需保留原始来源。",
    },
    {
        "code": "hangzhou_open_data",
        "name": "杭州市数据开放平台",
        "organization": "杭州市人民政府",
        "base_url": "https://data.hangzhou.gov.cn/",
        "source_type": "government",
        "reliability": "high",
    },
    {
        "code": "xihu_government",
        "name": "杭州市西湖区人民政府",
        "organization": "杭州市西湖区人民政府",
        "base_url": "https://www.hzxh.gov.cn/",
        "source_type": "government",
        "reliability": "high",
    },
    {
        "code": "tmsf_public",
        "name": "透明售房网公开信息",
        "organization": "透明售房网",
        "base_url": "https://www.tmsf.com/",
        "source_type": "market_platform",
        "reliability": "medium",
        "active": True,
        "usage_notes": "仅低频访问公开页面；触发 WAF 后立即停止。允许导入正常浏览器保存的完整 HTML 并保留原始快照，不绕过访问控制，不批量再发布。",
    },
    {
        "code": "hangzhou_secondhand_official",
        "name": "杭州市二手房交易监管服务平台",
        "organization": "杭州市住房保障和房产管理局",
        "base_url": "https://jjhygl.hzfc.gov.cn/",
        "source_type": "government",
        "reliability": "high",
        "active": False,
        "usage_notes": "公开旧域名和 JSON 接口当前不可达；适配器仅做低频探测并在不可用时熔断，不把 TMSF 数据冒充为官方平台直采。",
    },
    {
        "code": "amap_public",
        "name": "高德地图公开地点页",
        "organization": "高德地图",
        "base_url": "https://ditu.amap.com/",
        "source_type": "map_platform",
        "reliability": "medium",
        "usage_notes": "仅用于人工核验公开地点页上的地址与坐标；不执行批量抓取。",
    },
    {
        "code": "lianjia_public",
        "name": "链家杭州公开页面",
        "organization": "链家/贝壳",
        "base_url": "https://hz.lianjia.com/",
        "source_type": "market_platform",
        "reliability": "medium",
        "usage_notes": "P0 第一候选来源。仅访问公开列表和详情页；低频、可追溯快照；不登录、不绕过验证码或访问控制。挂牌与链家成交样本分开保存。",
    },
    {
        "code": "woaiwojia_public",
        "name": "我爱我家杭州公开页面",
        "organization": "我爱我家",
        "base_url": "https://hz.5i5j.com/",
        "source_type": "market_platform",
        "reliability": "medium",
        "usage_notes": "P0 第二候选来源，用于挂牌交叉核验；自动化前需确认站点条款和访问边界。",
    },
    {
        "code": "openstreetmap",
        "name": "OpenStreetMap",
        "organization": "OpenStreetMap contributors",
        "base_url": "https://www.openstreetmap.org/",
        "source_type": "open_data",
        "reliability": "medium",
        "license_name": "Open Data Commons Open Database License (ODbL) 1.0",
        "license_url": "https://www.openstreetmap.org/copyright",
        "attribution": "© OpenStreetMap contributors",
        "usage_notes": "候选小区空间底图；公开使用时必须署名并遵守 ODbL 衍生数据库要求。",
    },
]


METRIC_SEEDS = [
    ("market_transactions_12m", "近12个月市场样本数", "market", "count", "滚动12个月可用成交或网签样本数量", True),
    ("market_median_unit_price_12m", "近12个月单位价格中位数", "market", "CNY/m2", "滚动12个月有效市场样本单位价格中位数", None),
    ("metro_walk_minutes", "最近运营地铁站步行时间", "transport", "minute", "合规地图服务计算的小区到最近运营地铁站步行时间", False),
    ("hospital_travel_minutes", "重点医院出行时间", "medical", "minute", "指定交通方式与时段到最近重点医院的出行时间", False),
    ("amenity_15m_coverage", "15分钟生活圈覆盖率", "amenity", "percent", "目标生活设施类别在15分钟步行圈内的覆盖比例", True),
    ("data_completeness", "核心数据完整率", "quality", "percent", "P0 核心字段非空比例", True),
]


XIHU_MARKET_AREAS = []


def normalize_name(value: str) -> str:
    value = value.strip().lower()
    return re.sub(r"[\s·•・,，.。()（）\-_/\\]+", "", value)


def _get_or_create_source(session: Session, seed: Dict[str, object]) -> DataSource:
    source = session.scalar(select(DataSource).where(DataSource.code == seed["code"]))
    if source is None:
        source = DataSource(**seed)
        session.add(source)
        session.flush()
    else:
        for field, value in seed.items():
            if field != "code":
                setattr(source, field, value)
    return source


def seed_reference_data(session: Session) -> Dict[str, int]:
    sources = {seed["code"]: _get_or_create_source(session, seed) for seed in SOURCE_SEEDS}

    xihu = session.scalar(
        select(AdministrativeArea).where(
            AdministrativeArea.code == "330106",
            AdministrativeArea.valid_from == date(2026, 1, 1),
        )
    )
    if xihu is None:
        xihu = AdministrativeArea(
            code="330106",
            name="杭州市西湖区",
            level="district",
            valid_from=date(2026, 1, 1),
            source_id=sources["xihu_government"].id,
        )
        session.add(xihu)
        session.flush()

    expired_market_areas = 0
    for legacy_area in session.scalars(select(MarketArea).where(MarketArea.code.like("tmsf-xihu-%"), MarketArea.valid_to.is_(None))):
        legacy_area.valid_to = date(2026, 9, 29)
        expired_market_areas += 1

    market_areas_created = 0
    for name in XIHU_MARKET_AREAS:
        code = f"tmsf-xihu-{normalize_name(name)}"
        existing_area = session.scalar(
            select(MarketArea).where(MarketArea.code == code, MarketArea.valid_from == date(2026, 1, 1))
        )
        if existing_area is None:
            session.add(
                MarketArea(
                    code=code,
                    name=name,
                    administrative_area_id=xihu.id,
                    source_id=sources["tmsf_public"].id,
                    valid_from=date(2026, 1, 1),
                    definition="透明售房网公开页面的西湖区商圈筛选口径；属于市场板块，不代表行政边界。",
                )
            )
            market_areas_created += 1

    shenhua = session.scalar(select(MarketArea).where(MarketArea.code == "5i5j-xihu-shenhua", MarketArea.valid_to.is_(None)))
    if shenhua is None:
        session.add(MarketArea(code="5i5j-xihu-shenhua", name="申花", administrative_area_id=xihu.id, source_id=sources["woaiwojia_public"].id, valid_from=date(2026, 9, 29), definition="我爱我家杭州公开页面的小区商圈标签；属于市场板块，不代表行政边界。"))
        market_areas_created += 1

    metric_count = 0
    for code, name, domain, unit, calculation, higher_is_better in METRIC_SEEDS:
        existing = session.scalar(
            select(MetricDefinition).where(MetricDefinition.code == code, MetricDefinition.version == 1)
        )
        if existing is None:
            session.add(
                MetricDefinition(
                    code=code,
                    version=1,
                    name=name,
                    domain=domain,
                    unit=unit,
                    calculation=calculation,
                    higher_is_better=higher_is_better,
                )
            )
            metric_count += 1

    return {
        "sources": len(sources),
        "administrative_areas": 1,
        "market_areas_created": market_areas_created,
        "market_areas_expired": expired_market_areas,
        "metrics_created": metric_count,
    }


def _decimal(value: Optional[str]) -> Optional[Decimal]:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError(f"无效数字: {value}") from exc


def _integer(value: Optional[str]) -> Optional[int]:
    if value is None or not value.strip():
        return None
    return int(value.strip())


def import_communities_csv(
    session: Session,
    csv_path: Path,
    source_code: str = "manual_csv",
) -> Dict[str, int]:
    source = session.scalar(select(DataSource).where(DataSource.code == source_code))
    if source is None:
        raise ValueError(f"未知数据源 {source_code}，请先运行 seed-reference")
    xihu = session.scalar(select(AdministrativeArea).where(AdministrativeArea.code == "330106"))
    if xihu is None:
        raise ValueError("未找到西湖区行政范围，请先运行 seed-reference")

    run = IngestionRun(
        source_id=source.id,
        run_type="community_csv",
        status="running",
        parameters={"path": str(csv_path)},
    )
    session.add(run)
    session.flush()

    created = updated = failed = seen = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"source_record_id", "standard_name"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 缺少必填列: {', '.join(sorted(missing))}")

        for line_number, row in enumerate(reader, start=2):
            seen += 1
            try:
                external_id = row["source_record_id"].strip()
                standard_name = row["standard_name"].strip()
                if not external_id or not standard_name:
                    raise ValueError("source_record_id 和 standard_name 不得为空")

                mapping = session.scalar(
                    select(SourceRecord).where(
                        SourceRecord.source_id == source.id,
                        SourceRecord.entity_type == "community",
                        SourceRecord.external_id == external_id,
                    )
                )
                community = session.get(Community, mapping.internal_id) if mapping else None
                if community is None:
                    normalized = normalize_name(standard_name)
                    address = (row.get("address") or "").strip() or None
                    community = session.scalar(
                        select(Community).where(
                            Community.administrative_area_id == xihu.id,
                            Community.normalized_name == normalized,
                            Community.address == address,
                        )
                    )
                    match_method = "exact_name_address"
                    if community is None:
                        community = Community(
                            standard_name=standard_name,
                            normalized_name=normalized,
                            address=address,
                            administrative_area_id=xihu.id,
                            street_name=(row.get("street_name") or "").strip() or None,
                            property_type=(row.get("property_type") or "residential").strip(),
                            status=(row.get("status") or "completed").strip(),
                            verification_status=(row.get("verification_status") or "pending").strip(),
                            longitude=_decimal(row.get("longitude")),
                            latitude=_decimal(row.get("latitude")),
                            first_completed_year=_integer(row.get("first_completed_year")),
                            data_confidence=(row.get("data_confidence") or "medium").strip(),
                        )
                        session.add(community)
                        session.flush()
                        created += 1
                        match_method = "new_entity"
                    if mapping is None:
                        mapping = SourceRecord(
                            source_id=source.id,
                            entity_type="community",
                            external_id=external_id,
                            internal_id=community.id,
                            source_url=(row.get("source_url") or "").strip() or None,
                            match_method=match_method,
                            match_confidence=Decimal("1.0000"),
                        )
                        session.add(mapping)
                else:
                    community.standard_name = standard_name
                    community.normalized_name = normalize_name(standard_name)
                    for field in (
                        "address", "street_name", "property_type", "status",
                        "verification_status", "data_confidence",
                    ):
                        value = (row.get(field) or "").strip()
                        if value:
                            setattr(community, field, value)
                    if (row.get("longitude") or "").strip():
                        community.longitude = _decimal(row.get("longitude"))
                    if (row.get("latitude") or "").strip():
                        community.latitude = _decimal(row.get("latitude"))
                    if (row.get("first_completed_year") or "").strip():
                        community.first_completed_year = _integer(row.get("first_completed_year"))
                    mapping.last_seen_at = datetime.now(timezone.utc)
                    mapping.source_url = (row.get("source_url") or "").strip() or mapping.source_url
                    updated += 1

                alias_values = [standard_name]
                alias_values.extend(part.strip() for part in (row.get("alias_names") or "").split("|") if part.strip())
                existing_aliases = {
                    alias.normalized_alias
                    for alias in session.scalars(
                        select(CommunityAlias).where(CommunityAlias.community_id == community.id)
                    )
                }
                for alias_name in alias_values:
                    normalized_alias = normalize_name(alias_name)
                    if normalized_alias and normalized_alias not in existing_aliases:
                        session.add(
                            CommunityAlias(
                                community_id=community.id,
                                alias_name=alias_name,
                                normalized_alias=normalized_alias,
                                source_id=source.id,
                            )
                        )
                        existing_aliases.add(normalized_alias)
            except Exception as exc:
                failed += 1
                raise ValueError(f"CSV 第 {line_number} 行导入失败: {exc}") from exc

    run.status = "succeeded"
    run.finished_at = datetime.now(timezone.utc)
    run.records_seen = seen
    run.records_created = created
    run.records_updated = updated
    run.records_failed = failed
    return {"seen": seen, "created": created, "updated": updated, "failed": failed}


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if value is None or not value.strip():
        return None
    return date.fromisoformat(value.strip())


def import_market_observations_csv(
    session: Session,
    csv_path: Path,
    source_code: str = "manual_csv",
) -> Dict[str, int]:
    """Import idempotent deal/listing observations for an existing community."""
    source = session.scalar(select(DataSource).where(DataSource.code == source_code))
    if source is None:
        raise ValueError(f"未知数据源 {source_code}，请先运行 seed-reference")

    required = {"external_id", "observation_type", "observed_at"}
    allowed_types = {"deal", "transaction", "listing", "adjustment", "rent"}
    numeric_fields = ("total_price", "unit_price", "area_sqm")
    created = updated = seen = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 缺少必填列: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, start=2):
            seen += 1
            external_id = (row.get("external_id") or "").strip()
            observation_type = (row.get("observation_type") or "").strip().lower()
            if not external_id or observation_type not in allowed_types:
                raise ValueError(f"CSV 第 {line_number} 行 external_id 或 observation_type 无效")

            community_id = (row.get("community_id") or "").strip() or None
            community_name = (row.get("community_name") or "").strip() or None
            community = session.get(Community, community_id) if community_id else None
            if community is None and community_name:
                matches = session.scalars(
                    select(Community).where(Community.standard_name == community_name)
                ).all()
                if len(matches) != 1:
                    raise ValueError(f"CSV 第 {line_number} 行无法唯一匹配小区: {community_name}")
                community = matches[0]
            if community is None:
                raise ValueError(f"CSV 第 {line_number} 行缺少有效 community_id/community_name")

            observation = session.scalar(
                select(MarketObservation).where(
                    MarketObservation.source_id == source.id,
                    MarketObservation.observation_type == observation_type,
                    MarketObservation.external_id == external_id,
                )
            )
            payload = None
            payload_text = (row.get("payload_json") or "").strip()
            if payload_text:
                payload = json.loads(payload_text)
            values = {
                "community_id": community.id,
                "observed_at": _parse_datetime(row.get("observed_at")),
                "event_date": _parse_date(row.get("event_date")),
                "total_price": _decimal(row.get("total_price")),
                "unit_price": _decimal(row.get("unit_price")),
                "area_sqm": _decimal(row.get("area_sqm")),
                "bedrooms": _integer(row.get("bedrooms")),
                "floor_text": (row.get("floor_text") or "").strip() or None,
                "source_url": (row.get("source_url") or "").strip() or None,
                "payload": payload,
                "confidence": (row.get("confidence") or "medium").strip(),
            }
            if values["observed_at"] is None:
                raise ValueError(f"CSV 第 {line_number} 行 observed_at 无效")
            if observation is None:
                observation = MarketObservation(
                    source_id=source.id,
                    external_id=external_id,
                    observation_type=observation_type,
                    **values,
                )
                session.add(observation)
                created += 1
            else:
                for key, value in values.items():
                    setattr(observation, key, value)
                updated += 1
    return {"seen": seen, "created": created, "updated": updated}


def upsert_market_observation(
    session: Session,
    *,
    community_id: str,
    source_code: str,
    record: dict[str, object],
) -> dict[str, int]:
    """Persist one normalized source-adapter record with source/type/id idempotency."""
    source = session.scalar(select(DataSource).where(DataSource.code == source_code))
    if source is None:
        raise ValueError(f"未知数据源: {source_code}")
    community = session.get(Community, community_id)
    if community is None:
        raise ValueError("未找到小区")
    external_id = str(record.get("external_id") or "").strip()
    observation_type = str(record.get("observation_type") or "").strip().lower()
    observed_at = _parse_datetime(str(record.get("observed_at") or ""))
    if not external_id or observation_type not in {"deal", "transaction", "listing"} or observed_at is None:
        raise ValueError("市场观察缺少 external_id、合法 observation_type 或 observed_at")
    observation = session.scalar(select(MarketObservation).where(MarketObservation.source_id == source.id, MarketObservation.observation_type == observation_type, MarketObservation.external_id == external_id))
    values = {
        "community_id": community.id,
        "observed_at": observed_at,
        "event_date": _parse_date(str(record.get("event_date") or "")) if record.get("event_date") else None,
        "total_price": _decimal(str(record.get("total_price"))) if record.get("total_price") not in (None, "") else None,
        "unit_price": _decimal(str(record.get("unit_price"))) if record.get("unit_price") not in (None, "") else None,
        "area_sqm": _decimal(str(record.get("area_sqm"))) if record.get("area_sqm") not in (None, "") else None,
        "bedrooms": _integer(str(record.get("bedrooms"))) if record.get("bedrooms") not in (None, "") else None,
        "floor_text": str(record.get("floor_text") or "").strip() or None,
        "source_url": str(record.get("source_url") or "").strip() or None,
        "payload": record.get("payload"),
        "confidence": str(record.get("confidence") or "medium"),
    }
    if observation is None:
        session.add(MarketObservation(source_id=source.id, external_id=external_id, observation_type=observation_type, **values))
        return {"created": 1, "updated": 0}
    for key, value in values.items():
        setattr(observation, key, value)
    return {"created": 0, "updated": 1}


def import_market_snapshot_json(session: Session, path: Path, source_code: str) -> dict[str, int]:
    """Import a reviewed JSON snapshot without requiring a user-created CSV."""
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    community_id = payload.get("community_id")
    records = payload.get("records") or []
    if not community_id or not isinstance(records, list):
        raise ValueError("市场快照 JSON 必须包含 community_id 和 records")
    source = session.scalar(select(DataSource).where(DataSource.code == source_code))
    if source is None:
        raise ValueError(f"未知数据源: {source_code}")
    run = IngestionRun(source_id=source.id, run_type="reviewed_market_snapshot", status="running", parameters={"path": str(path)})
    session.add(run)
    session.flush()
    content_hash = hashlib.sha256(raw).hexdigest()
    snapshot = session.scalar(select(RawSnapshot).where(RawSnapshot.source_id == source.id, RawSnapshot.content_hash == content_hash))
    snapshot_created = 0
    if snapshot is None:
        snapshot = RawSnapshot(source_id=source.id, ingestion_run_id=run.id, external_id=path.stem, source_url=payload.get("source_url"), observed_at=_parse_datetime(payload.get("observed_at")) or datetime.now(timezone.utc), content_type="application/json", content_hash=content_hash, storage_path=str(path), payload=payload, parser_version="reviewed-json-v1", parse_status="succeeded")
        session.add(snapshot)
        snapshot_created = 1
    created = updated = 0
    for record in records:
        result = upsert_market_observation(session, community_id=community_id, source_code=source_code, record=record)
        created += result["created"]
        updated += result["updated"]
    run.status = "succeeded"
    run.finished_at = datetime.now(timezone.utc)
    run.records_seen = len(records)
    run.records_created = created
    run.records_updated = updated
    return {"seen": len(records), "created": created, "updated": updated, "snapshot_created": snapshot_created}


def import_lianjia_html_snapshot(
    session: Session,
    path: Path,
    community_id: str,
    source_url: str,
) -> dict[str, int]:
    """Import a Lianjia page explicitly saved by the user in a normal browser."""
    from .collectors.lianjia import parse_saved_html

    raw, records = parse_saved_html(path, source_url)
    source = session.scalar(select(DataSource).where(DataSource.code == "lianjia_public"))
    if source is None:
        raise ValueError("未知数据源: lianjia_public")
    if session.get(Community, community_id) is None:
        raise ValueError("未找到小区")
    run = IngestionRun(
        source_id=source.id,
        run_type="browser_saved_html",
        status="running",
        parameters={"path": str(path), "source_url": source_url},
    )
    session.add(run)
    session.flush()
    content_hash = hashlib.sha256(raw).hexdigest()
    snapshot = session.scalar(
        select(RawSnapshot).where(
            RawSnapshot.source_id == source.id,
            RawSnapshot.content_hash == content_hash,
        )
    )
    snapshot_created = 0
    if snapshot is None:
        snapshot = RawSnapshot(
            source_id=source.id,
            ingestion_run_id=run.id,
            external_id=path.stem,
            source_url=source_url,
            observed_at=datetime.now(timezone.utc),
            content_type="text/html",
            content_hash=content_hash,
            storage_path=str(path),
            payload={"record_count": len(records), "capture_method": "browser_saved_html"},
            parser_version="lianjia_public_v2",
            parse_status="succeeded",
        )
        session.add(snapshot)
        snapshot_created = 1
    created = updated = 0
    for record in records:
        result = upsert_market_observation(
            session,
            community_id=community_id,
            source_code="lianjia_public",
            record=record,
        )
        created += result["created"]
        updated += result["updated"]
    run.status = "succeeded"
    run.finished_at = datetime.now(timezone.utc)
    run.records_seen = len(records)
    run.records_created = created
    run.records_updated = updated
    return {
        "seen": len(records),
        "created": created,
        "updated": updated,
        "snapshot_created": snapshot_created,
    }


def import_tmsf_html_snapshot(
    session: Session,
    path: Path,
    community_id: str,
    source_url: str,
) -> dict[str, int]:
    """Import a complete TMSF community page saved by a normal browser."""
    from .collectors.tmsf import parse_saved_html

    raw, records = parse_saved_html(path, source_url)
    source = session.scalar(select(DataSource).where(DataSource.code == "tmsf_public"))
    if source is None:
        raise ValueError("未知数据源: tmsf_public")
    if session.get(Community, community_id) is None:
        raise ValueError("未找到小区")
    run = IngestionRun(
        source_id=source.id,
        run_type="browser_saved_html",
        status="running",
        parameters={"path": str(path), "source_url": source_url},
    )
    session.add(run)
    session.flush()
    content_hash = hashlib.sha256(raw).hexdigest()
    snapshot = session.scalar(
        select(RawSnapshot).where(
            RawSnapshot.source_id == source.id,
            RawSnapshot.content_hash == content_hash,
        )
    )
    snapshot_created = 0
    if snapshot is None:
        snapshot = RawSnapshot(
            source_id=source.id,
            ingestion_run_id=run.id,
            external_id=path.stem,
            source_url=source_url,
            observed_at=datetime.now(timezone.utc),
            content_type="text/html",
            content_hash=content_hash,
            storage_path=str(path),
            payload={"record_count": len(records), "capture_method": "browser_saved_html"},
            parser_version="tmsf_public_v1",
            parse_status="succeeded",
        )
        session.add(snapshot)
        snapshot_created = 1
    created = updated = 0
    for record in records:
        result = upsert_market_observation(
            session,
            community_id=community_id,
            source_code="tmsf_public",
            record=record,
        )
        created += result["created"]
        updated += result["updated"]
    run.status = "succeeded"
    run.finished_at = datetime.now(timezone.utc)
    run.records_seen = len(records)
    run.records_created = created
    run.records_updated = updated
    return {
        "seen": len(records),
        "created": created,
        "updated": updated,
        "snapshot_created": snapshot_created,
    }


def verify_community(
    session: Session,
    *,
    community_id: str,
    address: str,
    longitude: str,
    latitude: str,
    market_area_name: str,
    source_code: str,
    source_url: str,
    source_external_id: str,
    first_completed_year: Optional[int] = None,
) -> dict[str, object]:
    """Promote one community only after its P0 identity fields are reviewed."""
    community = session.get(Community, community_id)
    if community is None:
        raise ValueError("未找到小区")
    source = session.scalar(select(DataSource).where(DataSource.code == source_code))
    if source is None:
        raise ValueError(f"未知数据源: {source_code}")
    area = session.scalar(
        select(MarketArea).where(
            MarketArea.name == market_area_name,
            MarketArea.administrative_area_id == community.administrative_area_id,
            MarketArea.valid_to.is_(None),
        )
    )
    if area is None:
        raise ValueError(f"未找到市场板块: {market_area_name}")
    community.address = address.strip()
    community.longitude = _decimal(longitude)
    community.latitude = _decimal(latitude)
    community.market_area_id = area.id
    if first_completed_year is not None:
        community.first_completed_year = first_completed_year
    community.verification_status = "verified"
    community.data_confidence = "high"
    mapping = session.scalar(select(SourceRecord).where(SourceRecord.source_id == source.id, SourceRecord.entity_type == "community", SourceRecord.external_id == source_external_id))
    if mapping is None:
        mapping = SourceRecord(source_id=source.id, entity_type="community", external_id=source_external_id, internal_id=community.id, source_url=source_url, match_method="manual_review", match_confidence=Decimal("1.0000"))
        session.add(mapping)
    else:
        mapping.internal_id = community.id
        mapping.source_url = source_url
        mapping.last_seen_at = datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)
    existing_facts = {(fact.fact_key, fact.source_id) for fact in session.scalars(select(CommunityFact).where(CommunityFact.community_id == community.id))}
    facts = [("address", address.strip(), None, None), ("longitude", None, community.longitude, "degree"), ("latitude", None, community.latitude, "degree")]
    if first_completed_year is not None:
        facts.append(("first_completed_year", None, Decimal(first_completed_year), "year"))
    for fact_key, value_text, value_number, unit in facts:
        if (fact_key, source.id) not in existing_facts:
            session.add(CommunityFact(community_id=community.id, fact_key=fact_key, value_text=value_text, value_number=value_number, unit=unit, observed_at=now, source_id=source.id, evidence_url=source_url, confidence="high"))
    return {"community_id": community.id, "verification_status": community.verification_status, "source_code": source.code, "source_url": source_url}


def set_community_completion_year(
    session: Session,
    *,
    community_id: str,
    year: int,
    source_code: str,
    source_url: str,
) -> dict[str, object]:
    if year < 1900 or year > datetime.now().year:
        raise ValueError("竣工年份超出合理范围")
    community = session.get(Community, community_id)
    if community is None:
        raise ValueError("未找到小区")
    source = session.scalar(select(DataSource).where(DataSource.code == source_code))
    if source is None:
        raise ValueError(f"未知数据源: {source_code}")
    community.first_completed_year = year
    fact = session.scalar(select(CommunityFact).where(CommunityFact.community_id == community.id, CommunityFact.fact_key == "first_completed_year", CommunityFact.source_id == source.id))
    if fact is None:
        fact = CommunityFact(community_id=community.id, fact_key="first_completed_year", value_number=Decimal(year), unit="year", observed_at=datetime.now(timezone.utc), source_id=source.id, evidence_url=source_url, confidence="medium")
        session.add(fact)
    else:
        fact.value_number = Decimal(year)
        fact.observed_at = datetime.now(timezone.utc)
        fact.evidence_url = source_url
    return {"community_id": community.id, "first_completed_year": year, "source_code": source.code}
