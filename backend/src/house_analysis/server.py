from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import database_url
from .db import create_database_engine, session_scope
from .models import AdministrativeArea, Community, DataSource, MarketArea, MarketObservation
from .quality import build_community_quality_report

app = FastAPI(title="House Analysis API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("HOUSE_WEB_ORIGIN", "http://localhost:4173"), "http://127.0.0.1:4173"], allow_methods=["GET"], allow_headers=["*"])


def _payload(session, community: Community) -> dict[str, Any]:
    area = session.get(AdministrativeArea, community.administrative_area_id)
    market_area = session.get(MarketArea, community.market_area_id) if community.market_area_id else None
    return {"id": community.id, "standard_name": community.standard_name, "address": community.address, "longitude": community.longitude, "latitude": community.latitude, "property_type": community.property_type, "first_completed_year": community.first_completed_year, "verification_status": community.verification_status, "administrative_area_name": area.name if area else None, "market_area_name": market_area.name if market_area else None}


def _observation_payload(session, observation: MarketObservation) -> dict[str, Any]:
    source = session.get(DataSource, observation.source_id)
    payload = observation.payload or {}
    freshness_status = None
    if observation.observation_type == "listing":
        observed_date = observation.observed_at.date() if observation.observed_at else None
        freshness_status = "stale" if observed_date and (datetime.now(timezone.utc).date() - observed_date).days > 30 else payload.get("listing_status", "unknown")
    return {
        "id": observation.id,
        "community_id": observation.community_id,
        "observation_type": observation.observation_type,
        "external_id": observation.external_id,
        "observed_at": observation.observed_at.isoformat() if observation.observed_at else None,
        "event_date": observation.event_date.isoformat() if observation.event_date else None,
        "total_price": float(observation.total_price) if observation.total_price is not None else None,
        "unit_price": float(observation.unit_price) if observation.unit_price is not None else None,
        "area_sqm": float(observation.area_sqm) if observation.area_sqm is not None else None,
        "bedrooms": observation.bedrooms,
        "floor_text": observation.floor_text,
        "source_url": observation.source_url,
        "confidence": observation.confidence,
        "source": {"code": source.code, "name": source.name} if source else None,
        "freshness_status": freshness_status,
        "payload": payload,
    }


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/communities")
@app.get("/api/communities")
def list_communities() -> list[dict[str, Any]]:
    engine = create_database_engine(database_url())
    try:
        with session_scope(engine) as session:
            return [_payload(session, c) for c in session.scalars(select(Community).order_by(Community.standard_name)).all()]
    finally:
        engine.dispose()


@app.get("/api/v1/communities/{community_id}")
@app.get("/api/communities/{community_id}")
def get_community(community_id: str) -> dict[str, Any]:
    engine = create_database_engine(database_url())
    try:
        with session_scope(engine) as session:
            community = session.get(Community, community_id)
            if community is None:
                raise HTTPException(status_code=404, detail="community_not_found")
            return _payload(session, community)
    finally:
        engine.dispose()


@app.get("/api/v1/communities/{community_id}/quality")
@app.get("/api/communities/{community_id}/quality")
def get_community_quality(community_id: str) -> dict[str, Any]:
    engine = create_database_engine(database_url())
    try:
        with session_scope(engine) as session:
            community = session.get(Community, community_id)
            if community is None:
                raise HTTPException(status_code=404, detail="community_not_found")
            return build_community_quality_report(session, community_id=community.id)
    finally:
        engine.dispose()


@app.get("/api/v1/communities/{community_id}/market")
@app.get("/api/communities/{community_id}/market")
def get_community_market(community_id: str) -> dict[str, Any]:
    engine = create_database_engine(database_url())
    try:
        with session_scope(engine) as session:
            community = session.get(Community, community_id)
            if community is None:
                raise HTTPException(status_code=404, detail="community_not_found")
            observations = session.scalars(
                select(MarketObservation)
                .where(MarketObservation.community_id == community.id)
                .order_by(MarketObservation.event_date.asc(), MarketObservation.observed_at.asc())
            ).all()
            history_types = {"deal", "transaction", "sale", "成交", "网签"}
            history = [item for item in observations if item.observation_type in history_types]
            listings = [item for item in observations if item.observation_type == "listing"]
            listings.sort(key=lambda item: (item.observed_at or item.created_at), reverse=True)
            observed_dates = [item.observed_at for item in observations if item.observed_at]
            return {
                "community_id": community.id,
                "community_name": community.standard_name,
                "data_as_of": max(observed_dates).isoformat() if observed_dates else None,
                "history": [_observation_payload(session, item) for item in history],
                "listings": [_observation_payload(session, item) for item in listings],
                "counts": {"history": len(history), "listings": len(listings)},
            }
    finally:
        engine.dispose()


def main() -> None:
    import uvicorn
    uvicorn.run("house_analysis.server:app", host=os.getenv("HOUSE_API_HOST", "127.0.0.1"), port=int(os.getenv("HOUSE_API_PORT", "8787")), reload=os.getenv("HOUSE_API_RELOAD", "0") == "1")


if __name__ == "__main__":
    main()
