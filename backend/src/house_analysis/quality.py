from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AdministrativeArea,
    Community,
    CommunityAlias,
    DataSource,
    MarketArea,
    MetricDefinition,
    ReviewTask,
    CommunityFact,
    MarketObservation,
    CommunitySchoolMapping,
)


def build_quality_report(session: Session) -> Dict[str, object]:
    total = session.scalar(select(func.count()).select_from(Community)) or 0
    with_coordinates = session.scalar(
        select(func.count()).select_from(Community).where(
            Community.longitude.is_not(None), Community.latitude.is_not(None)
        )
    ) or 0
    with_address = session.scalar(
        select(func.count()).select_from(Community).where(Community.address.is_not(None), Community.address != "")
    ) or 0
    aliases = session.scalar(select(func.count()).select_from(CommunityAlias)) or 0
    sources = session.scalar(select(func.count()).select_from(DataSource)) or 0
    administrative_areas = session.scalar(select(func.count()).select_from(AdministrativeArea)) or 0
    market_areas = session.scalar(select(func.count()).select_from(MarketArea).where(MarketArea.valid_to.is_(None))) or 0
    metric_definitions = session.scalar(select(func.count()).select_from(MetricDefinition)) or 0
    open_reviews = session.scalar(
        select(func.count()).select_from(ReviewTask).where(ReviewTask.status == "open")
    ) or 0

    def coverage(value: int) -> float:
        return round(value / total * 100, 2) if total else 0.0

    return {
        "communities": total,
        "sources": sources,
        "administrative_areas": administrative_areas,
        "market_areas": market_areas,
        "metric_definitions": metric_definitions,
        "aliases": aliases,
        "open_review_tasks": open_reviews,
        "coverage": {
            "address_percent": coverage(with_address),
            "coordinates_percent": coverage(with_coordinates),
        },
    }


def build_community_quality_report(
    session: Session, *, name: Optional[str] = None, community_id: Optional[str] = None
) -> Dict[str, object]:
    """Return an actionable completeness audit for one community.

    This deliberately reports missing values instead of inventing defaults.  A
    name lookup is restricted to an exact normalized name by the caller/query,
    so ambiguous records are surfaced as an error rather than silently merged.
    """
    if not name and not community_id:
        raise ValueError("name 或 community_id 至少提供一个")
    query = select(Community)
    if community_id:
        query = query.where(Community.id == community_id)
    else:
        query = query.where(Community.standard_name == name)
    matches = session.scalars(query).all()
    if not matches:
        raise ValueError("未找到小区")
    if len(matches) > 1:
        raise ValueError("小区名称不唯一，请改用 community_id")
    community = matches[0]

    fields = {
        "address": bool(community.address),
        "longitude": community.longitude is not None,
        "latitude": community.latitude is not None,
        "administrative_area": community.administrative_area_id is not None,
        "market_area": community.market_area_id is not None,
        "verification_status": community.verification_status == "verified",
    }
    related = {
        "aliases": session.scalar(select(func.count()).select_from(CommunityAlias).where(CommunityAlias.community_id == community.id)) or 0,
        "facts": session.scalar(select(func.count()).select_from(CommunityFact).where(CommunityFact.community_id == community.id)) or 0,
        "market_observations": session.scalar(select(func.count()).select_from(MarketObservation).where(MarketObservation.community_id == community.id)) or 0,
        "school_mappings": session.scalar(select(func.count()).select_from(CommunitySchoolMapping).where(CommunitySchoolMapping.community_id == community.id)) or 0,
    }
    missing = [key for key, present in fields.items() if not present]
    return {
        "community": {"id": community.id, "standard_name": community.standard_name},
        "status": "complete" if not missing else "incomplete",
        "fields": fields,
        "missing_fields": missing,
        "related_counts": related,
    }
