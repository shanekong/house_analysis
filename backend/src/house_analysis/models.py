from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.orm import mapped_column


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.current_timestamp())
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.current_timestamp())


class DataSource(TimestampMixin, Base):
    __tablename__ = "data_source"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    code = mapped_column(String(64), nullable=False, unique=True)
    name = mapped_column(String(200), nullable=False)
    organization = mapped_column(String(200))
    base_url = mapped_column(String(1000))
    source_type = mapped_column(String(32), nullable=False)
    reliability = mapped_column(String(16), nullable=False, default="medium")
    license_name = mapped_column(String(100))
    license_url = mapped_column(String(1000))
    attribution = mapped_column(String(500))
    usage_notes = mapped_column(Text)
    active = mapped_column(Boolean, nullable=False, default=True)


class IngestionRun(TimestampMixin, Base):
    __tablename__ = "ingestion_run"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    source_id = mapped_column(String(32), ForeignKey("data_source.id"), nullable=False)
    run_type = mapped_column(String(32), nullable=False)
    status = mapped_column(String(16), nullable=False, default="running")
    started_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.current_timestamp())
    finished_at = mapped_column(DateTime(timezone=True))
    records_seen = mapped_column(Integer, nullable=False, default=0)
    records_created = mapped_column(Integer, nullable=False, default=0)
    records_updated = mapped_column(Integer, nullable=False, default=0)
    records_failed = mapped_column(Integer, nullable=False, default=0)
    error_message = mapped_column(Text)
    parameters = mapped_column(JSON)


class RawSnapshot(TimestampMixin, Base):
    __tablename__ = "raw_snapshot"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    source_id = mapped_column(String(32), ForeignKey("data_source.id"), nullable=False)
    ingestion_run_id = mapped_column(String(32), ForeignKey("ingestion_run.id"))
    external_id = mapped_column(String(255))
    source_url = mapped_column(String(1500))
    observed_at = mapped_column(DateTime(timezone=True), nullable=False)
    content_type = mapped_column(String(100))
    content_hash = mapped_column(String(64), nullable=False)
    storage_path = mapped_column(String(1000))
    payload = mapped_column(JSON)
    parser_version = mapped_column(String(64))
    parse_status = mapped_column(String(16), nullable=False, default="pending")

    __table_args__ = (
        UniqueConstraint("source_id", "content_hash", name="uq_raw_snapshot_source_hash"),
        Index("ix_raw_snapshot_observed_at", "observed_at"),
    )


class AdministrativeArea(TimestampMixin, Base):
    __tablename__ = "administrative_area"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    code = mapped_column(String(32), nullable=False)
    name = mapped_column(String(200), nullable=False)
    level = mapped_column(String(32), nullable=False)
    parent_id = mapped_column(String(32), ForeignKey("administrative_area.id"))
    valid_from = mapped_column(Date)
    valid_to = mapped_column(Date)
    boundary_geojson = mapped_column(JSON)
    source_id = mapped_column(String(32), ForeignKey("data_source.id"))

    __table_args__ = (
        UniqueConstraint("code", "valid_from", name="uq_administrative_area_version"),
        Index("ix_administrative_area_parent", "parent_id"),
    )


class MarketArea(TimestampMixin, Base):
    __tablename__ = "market_area"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    code = mapped_column(String(64), nullable=False)
    name = mapped_column(String(200), nullable=False)
    administrative_area_id = mapped_column(String(32), ForeignKey("administrative_area.id"))
    source_id = mapped_column(String(32), ForeignKey("data_source.id"), nullable=False)
    valid_from = mapped_column(Date)
    valid_to = mapped_column(Date)
    boundary_geojson = mapped_column(JSON)
    definition = mapped_column(Text)

    __table_args__ = (UniqueConstraint("code", "valid_from", name="uq_market_area_version"),)


class Community(TimestampMixin, Base):
    __tablename__ = "community"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    standard_name = mapped_column(String(255), nullable=False)
    normalized_name = mapped_column(String(255), nullable=False)
    address = mapped_column(String(500))
    administrative_area_id = mapped_column(String(32), ForeignKey("administrative_area.id"), nullable=False)
    market_area_id = mapped_column(String(32), ForeignKey("market_area.id"))
    street_name = mapped_column(String(200))
    community_name = mapped_column(String(200))
    property_type = mapped_column(String(32), nullable=False, default="residential")
    status = mapped_column(String(32), nullable=False, default="completed")
    verification_status = mapped_column(String(32), nullable=False, default="pending")
    longitude = mapped_column(Numeric(10, 7))
    latitude = mapped_column(Numeric(10, 7))
    geohash = mapped_column(String(16))
    min_longitude = mapped_column(Numeric(10, 7))
    min_latitude = mapped_column(Numeric(10, 7))
    max_longitude = mapped_column(Numeric(10, 7))
    max_latitude = mapped_column(Numeric(10, 7))
    boundary_geojson = mapped_column(JSON)
    first_completed_year = mapped_column(Integer)
    data_confidence = mapped_column(String(16), nullable=False, default="low")
    active = mapped_column(Boolean, nullable=False, default=True)

    aliases = relationship("CommunityAlias", back_populates="community", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_community_name", "normalized_name"),
        Index("ix_community_area", "administrative_area_id"),
        Index("ix_community_market_area", "market_area_id"),
        Index("ix_community_verification", "verification_status"),
        Index("ix_community_coordinates", "longitude", "latitude"),
        CheckConstraint("latitude IS NULL OR (latitude >= -90 AND latitude <= 90)", name="ck_community_latitude"),
        CheckConstraint("longitude IS NULL OR (longitude >= -180 AND longitude <= 180)", name="ck_community_longitude"),
    )


class CommunityAlias(TimestampMixin, Base):
    __tablename__ = "community_alias"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    community_id = mapped_column(String(32), ForeignKey("community.id", ondelete="CASCADE"), nullable=False)
    alias_name = mapped_column(String(255), nullable=False)
    normalized_alias = mapped_column(String(255), nullable=False)
    alias_type = mapped_column(String(32), nullable=False, default="source_name")
    source_id = mapped_column(String(32), ForeignKey("data_source.id"))
    community = relationship("Community", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("community_id", "normalized_alias", name="uq_community_alias"),
        Index("ix_community_alias_normalized", "normalized_alias"),
    )


class SourceRecord(TimestampMixin, Base):
    __tablename__ = "source_record"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    source_id = mapped_column(String(32), ForeignKey("data_source.id"), nullable=False)
    entity_type = mapped_column(String(32), nullable=False)
    external_id = mapped_column(String(255), nullable=False)
    internal_id = mapped_column(String(32), nullable=False)
    source_url = mapped_column(String(1500))
    first_seen_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.current_timestamp())
    last_seen_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.current_timestamp())
    match_method = mapped_column(String(32), nullable=False)
    match_confidence = mapped_column(Numeric(5, 4), nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("source_id", "entity_type", "external_id", name="uq_source_record_external"),
        Index("ix_source_record_internal", "entity_type", "internal_id"),
    )


class CommunityFact(TimestampMixin, Base):
    __tablename__ = "community_fact"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    community_id = mapped_column(String(32), ForeignKey("community.id", ondelete="CASCADE"), nullable=False)
    fact_key = mapped_column(String(64), nullable=False)
    value_text = mapped_column(Text)
    value_number = mapped_column(Numeric(20, 6))
    unit = mapped_column(String(32))
    valid_from = mapped_column(Date)
    valid_to = mapped_column(Date)
    observed_at = mapped_column(DateTime(timezone=True), nullable=False)
    source_id = mapped_column(String(32), ForeignKey("data_source.id"), nullable=False)
    evidence_url = mapped_column(String(1500))
    confidence = mapped_column(String(16), nullable=False, default="medium")

    __table_args__ = (
        Index("ix_community_fact_lookup", "community_id", "fact_key", "valid_from"),
        CheckConstraint("value_text IS NOT NULL OR value_number IS NOT NULL", name="ck_community_fact_has_value"),
    )


class MarketObservation(TimestampMixin, Base):
    __tablename__ = "market_observation"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    community_id = mapped_column(String(32), ForeignKey("community.id"), nullable=False)
    source_id = mapped_column(String(32), ForeignKey("data_source.id"), nullable=False)
    external_id = mapped_column(String(255))
    observation_type = mapped_column(String(32), nullable=False)
    observed_at = mapped_column(DateTime(timezone=True), nullable=False)
    event_date = mapped_column(Date)
    total_price = mapped_column(Numeric(16, 2))
    unit_price = mapped_column(Numeric(14, 2))
    area_sqm = mapped_column(Numeric(10, 2))
    bedrooms = mapped_column(Integer)
    floor_text = mapped_column(String(64))
    source_url = mapped_column(String(1500))
    payload = mapped_column(JSON)
    confidence = mapped_column(String(16), nullable=False, default="medium")

    __table_args__ = (
        UniqueConstraint("source_id", "observation_type", "external_id", name="uq_market_observation_external"),
        Index("ix_market_observation_community_date", "community_id", "event_date"),
        Index("ix_market_observation_type_date", "observation_type", "event_date"),
    )


class CommunityMarketMonthly(TimestampMixin, Base):
    __tablename__ = "community_market_monthly"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    community_id = mapped_column(String(32), ForeignKey("community.id"), nullable=False)
    month = mapped_column(Date, nullable=False)
    metric_scope = mapped_column(String(32), nullable=False)
    sample_count = mapped_column(Integer, nullable=False, default=0)
    median_unit_price = mapped_column(Numeric(14, 2))
    average_unit_price = mapped_column(Numeric(14, 2))
    p25_unit_price = mapped_column(Numeric(14, 2))
    p75_unit_price = mapped_column(Numeric(14, 2))
    listing_count = mapped_column(Integer)
    median_days_on_market = mapped_column(Numeric(10, 2))
    source_coverage = mapped_column(JSON)
    confidence = mapped_column(String(16), nullable=False, default="low")

    __table_args__ = (
        UniqueConstraint("community_id", "month", "metric_scope", name="uq_community_market_month"),
        CheckConstraint("sample_count >= 0", name="ck_market_monthly_sample_count"),
    )


class School(TimestampMixin, Base):
    __tablename__ = "school"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    name = mapped_column(String(255), nullable=False)
    campus_name = mapped_column(String(255))
    school_stage = mapped_column(String(32), nullable=False)
    school_group = mapped_column(String(255))
    status = mapped_column(String(32), nullable=False, default="operating")
    address = mapped_column(String(500))
    longitude = mapped_column(Numeric(10, 7))
    latitude = mapped_column(Numeric(10, 7))
    administrative_area_id = mapped_column(String(32), ForeignKey("administrative_area.id"), nullable=False)

    __table_args__ = (Index("ix_school_area_stage", "administrative_area_id", "school_stage"),)


class SchoolCatchmentRule(TimestampMixin, Base):
    __tablename__ = "school_catchment_rule"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    school_id = mapped_column(String(32), ForeignKey("school.id"), nullable=False)
    school_year = mapped_column(String(16), nullable=False)
    official_description = mapped_column(Text, nullable=False)
    effective_from = mapped_column(Date)
    effective_to = mapped_column(Date)
    source_id = mapped_column(String(32), ForeignKey("data_source.id"), nullable=False)
    source_url = mapped_column(String(1500), nullable=False)
    boundary_geojson = mapped_column(JSON)

    __table_args__ = (Index("ix_catchment_school_year", "school_id", "school_year"),)


class CommunitySchoolMapping(TimestampMixin, Base):
    __tablename__ = "community_school_mapping"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    community_id = mapped_column(String(32), ForeignKey("community.id"), nullable=False)
    school_id = mapped_column(String(32), ForeignKey("school.id"), nullable=False)
    catchment_rule_id = mapped_column(String(32), ForeignKey("school_catchment_rule.id"), nullable=False)
    school_year = mapped_column(String(16), nullable=False)
    mapping_status = mapped_column(String(32), nullable=False, default="candidate")
    match_method = mapped_column(String(32), nullable=False)
    confidence = mapped_column(Numeric(5, 4), nullable=False)
    review_notes = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("community_id", "school_id", "school_year", name="uq_community_school_year"),
        Index("ix_community_school_lookup", "community_id", "school_year"),
    )


class Poi(TimestampMixin, Base):
    __tablename__ = "poi"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    source_id = mapped_column(String(32), ForeignKey("data_source.id"), nullable=False)
    external_id = mapped_column(String(255), nullable=False)
    name = mapped_column(String(255), nullable=False)
    category = mapped_column(String(64), nullable=False)
    subcategory = mapped_column(String(64))
    address = mapped_column(String(500))
    longitude = mapped_column(Numeric(10, 7), nullable=False)
    latitude = mapped_column(Numeric(10, 7), nullable=False)
    status = mapped_column(String(32), nullable=False, default="operating")
    observed_at = mapped_column(DateTime(timezone=True), nullable=False)
    payload = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_poi_source_external"),
        Index("ix_poi_category_coordinates", "category", "longitude", "latitude"),
    )


class MetricDefinition(TimestampMixin, Base):
    __tablename__ = "metric_definition"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    code = mapped_column(String(64), nullable=False)
    version = mapped_column(Integer, nullable=False, default=1)
    name = mapped_column(String(200), nullable=False)
    domain = mapped_column(String(64), nullable=False)
    unit = mapped_column(String(32))
    calculation = mapped_column(Text, nullable=False)
    higher_is_better = mapped_column(Boolean)
    active = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("code", "version", name="uq_metric_definition_version"),)


class CommunityMetricSnapshot(TimestampMixin, Base):
    __tablename__ = "community_metric_snapshot"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    community_id = mapped_column(String(32), ForeignKey("community.id"), nullable=False)
    metric_definition_id = mapped_column(String(32), ForeignKey("metric_definition.id"), nullable=False)
    as_of_date = mapped_column(Date, nullable=False)
    value = mapped_column(Numeric(20, 6))
    value_text = mapped_column(Text)
    confidence = mapped_column(String(16), nullable=False, default="low")
    sample_count = mapped_column(Integer)
    inputs = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("community_id", "metric_definition_id", "as_of_date", name="uq_community_metric_date"),
        Index("ix_community_metric_lookup", "community_id", "as_of_date"),
    )


class ReviewTask(TimestampMixin, Base):
    __tablename__ = "review_task"

    id = mapped_column(String(32), primary_key=True, default=new_id)
    task_type = mapped_column(String(64), nullable=False)
    entity_type = mapped_column(String(32), nullable=False)
    entity_id = mapped_column(String(32))
    status = mapped_column(String(16), nullable=False, default="open")
    priority = mapped_column(Integer, nullable=False, default=2)
    title = mapped_column(String(255), nullable=False)
    details = mapped_column(JSON)
    assigned_to = mapped_column(String(100))
    resolved_at = mapped_column(DateTime(timezone=True))
    resolution = mapped_column(Text)

    __table_args__ = (
        Index("ix_review_task_queue", "status", "priority", "created_at"),
        CheckConstraint("priority >= 0 AND priority <= 3", name="ck_review_task_priority"),
    )
