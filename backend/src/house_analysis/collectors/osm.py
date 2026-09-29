from __future__ import annotations

import hashlib
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AdministrativeArea,
    Community,
    CommunityAlias,
    DataSource,
    IngestionRun,
    RawSnapshot,
    SourceRecord,
)
from ..seed import normalize_name


DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
XIHU_OSM_AREA_ID = 3_604_591_410
XIHU_QUERY = """[out:json][timeout:90];
area(3604591410)->.searchArea;
(
  nwr["landuse"="residential"]["name"](area.searchArea);
  nwr["place"~"^(neighbourhood|quarter)$"]["name"](area.searchArea);
);
out center tags;
"""


def fetch_overpass_json(
    endpoint: str = DEFAULT_OVERPASS_URL,
    timeout_seconds: int = 120,
) -> Tuple[bytes, Dict[str, object]]:
    body = urllib.parse.urlencode({"data": XIHU_QUERY}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "User-Agent": "house-analysis/0.1 (local personal housing research)",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read()
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict) or not isinstance(decoded.get("elements"), list):
        raise ValueError("Overpass 响应缺少 elements 数组")
    return payload, decoded


def _coordinates(element: Dict[str, object]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    if element.get("type") == "node":
        lat, lon = element.get("lat"), element.get("lon")
    else:
        center = element.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
    if lat is None or lon is None:
        return None, None
    return Decimal(str(lon)), Decimal(str(lat))


def _distance_meters(
    lon1: Optional[Decimal], lat1: Optional[Decimal], lon2: Optional[Decimal], lat2: Optional[Decimal]
) -> Optional[float]:
    if None in (lon1, lat1, lon2, lat2):
        return None
    radius = 6_371_000.0
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    delta_phi = math.radians(float(lat2 - lat1))
    delta_lambda = math.radians(float(lon2 - lon1))
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _preferred_name(tags: Dict[str, object]) -> Optional[str]:
    for key in ("name:zh-Hans", "name:zh", "name"):
        value = tags.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _address(tags: Dict[str, object]) -> Optional[str]:
    full = tags.get("addr:full")
    if isinstance(full, str) and full.strip():
        return full.strip()
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    parts = [part.strip() for part in (street, number) if isinstance(part, str) and part.strip()]
    return "".join(parts) or None


def _confidence(tags: Dict[str, object], element_type: str) -> str:
    if tags.get("landuse") == "residential" and element_type in {"way", "relation"}:
        return "medium"
    return "low"


def _find_nearby_duplicate(
    session: Session,
    area_id: str,
    normalized_name: str,
    longitude: Optional[Decimal],
    latitude: Optional[Decimal],
) -> Optional[Community]:
    candidates = session.scalars(
        select(Community).where(
            Community.administrative_area_id == area_id,
            Community.normalized_name == normalized_name,
        )
    ).all()
    if len(candidates) == 1 and (longitude is None or latitude is None):
        return candidates[0]
    for candidate in candidates:
        distance = _distance_meters(longitude, latitude, candidate.longitude, candidate.latitude)
        if distance is not None and distance <= 200:
            return candidate
    return None


def ingest_osm_payload(
    session: Session,
    raw_payload: bytes,
    payload: Dict[str, object],
    endpoint: str = DEFAULT_OVERPASS_URL,
) -> Dict[str, int]:
    source = session.scalar(select(DataSource).where(DataSource.code == "openstreetmap"))
    area = session.scalar(select(AdministrativeArea).where(AdministrativeArea.code == "330106"))
    if source is None or area is None:
        raise ValueError("请先运行 seed-reference 初始化西湖区和 OpenStreetMap 数据源")

    observed_at = datetime.now(timezone.utc)
    run = IngestionRun(
        source_id=source.id,
        run_type="osm_xihu_community_candidates",
        status="running",
        parameters={"endpoint": endpoint, "osm_area_id": XIHU_OSM_AREA_ID},
    )
    session.add(run)
    session.flush()

    content_hash = hashlib.sha256(raw_payload).hexdigest()
    snapshot = session.scalar(
        select(RawSnapshot).where(RawSnapshot.source_id == source.id, RawSnapshot.content_hash == content_hash)
    )
    if snapshot is None:
        snapshot = RawSnapshot(
            source_id=source.id,
            ingestion_run_id=run.id,
            external_id=f"overpass-xihu-{observed_at.date().isoformat()}",
            source_url=endpoint,
            observed_at=observed_at,
            content_type="application/json",
            content_hash=content_hash,
            payload=payload,
            parser_version="osm-community-v1",
            parse_status="parsed",
        )
        session.add(snapshot)

    created = updated = linked = skipped = 0
    elements = payload.get("elements", [])
    for element in elements:
        if not isinstance(element, dict):
            skipped += 1
            continue
        tags = element.get("tags") or {}
        element_type = str(element.get("type") or "")
        element_id = element.get("id")
        name = _preferred_name(tags)
        if not name or element_type not in {"node", "way", "relation"} or element_id is None:
            skipped += 1
            continue

        external_id = f"{element_type}/{element_id}"
        longitude, latitude = _coordinates(element)
        mapping = session.scalar(
            select(SourceRecord).where(
                SourceRecord.source_id == source.id,
                SourceRecord.entity_type == "community",
                SourceRecord.external_id == external_id,
            )
        )
        community = session.get(Community, mapping.internal_id) if mapping else None
        if community is None:
            normalized = normalize_name(name)
            community = _find_nearby_duplicate(session, area.id, normalized, longitude, latitude)
            match_method = "name_within_200m" if community else "new_osm_candidate"
            match_confidence = Decimal("0.8500") if community else Decimal("0.7000")
            if community is None:
                community = Community(
                    standard_name=name,
                    normalized_name=normalized,
                    address=_address(tags),
                    administrative_area_id=area.id,
                    property_type="residential",
                    status="completed",
                    verification_status="pending",
                    longitude=longitude,
                    latitude=latitude,
                    data_confidence=_confidence(tags, element_type),
                )
                session.add(community)
                session.flush()
                created += 1
            else:
                linked += 1
            mapping = SourceRecord(
                source_id=source.id,
                entity_type="community",
                external_id=external_id,
                internal_id=community.id,
                source_url=f"https://www.openstreetmap.org/{element_type}/{element_id}",
                match_method=match_method,
                match_confidence=match_confidence,
            )
            session.add(mapping)
        else:
            if longitude is not None and latitude is not None:
                community.longitude = longitude
                community.latitude = latitude
            address = _address(tags)
            if address:
                community.address = address
            community.updated_at = observed_at
            mapping.last_seen_at = observed_at
            updated += 1

        alias_names = {name}
        for key in ("name", "name:zh", "name:zh-Hans", "alt_name", "old_name"):
            value = tags.get(key)
            if isinstance(value, str):
                alias_names.update(part.strip() for part in value.split(";") if part.strip())
        existing_aliases = {
            alias.normalized_alias
            for alias in session.scalars(
                select(CommunityAlias).where(CommunityAlias.community_id == community.id)
            )
        }
        for alias_name in sorted(alias_names):
            normalized_alias = normalize_name(alias_name)
            if normalized_alias and normalized_alias not in existing_aliases:
                session.add(
                    CommunityAlias(
                        community_id=community.id,
                        alias_name=alias_name,
                        normalized_alias=normalized_alias,
                        alias_type="osm_name",
                        source_id=source.id,
                    )
                )
                existing_aliases.add(normalized_alias)

    run.status = "succeeded"
    run.finished_at = observed_at
    run.records_seen = len(elements)
    run.records_created = created
    run.records_updated = updated
    run.records_failed = skipped
    return {
        "seen": len(elements),
        "created": created,
        "updated": updated,
        "linked_to_existing": linked,
        "skipped": skipped,
    }


def collect_xihu_communities(
    session: Session,
    endpoint: str = DEFAULT_OVERPASS_URL,
) -> Dict[str, int]:
    raw_payload, payload = fetch_overpass_json(endpoint=endpoint)
    return ingest_osm_payload(session, raw_payload, payload, endpoint=endpoint)

