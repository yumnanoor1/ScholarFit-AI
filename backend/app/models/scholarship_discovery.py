from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import validates
from sqlalchemy.sql import func

from app.database import Base
from app.services.source_url_safety import validate_source_url


SCHOLARSHIP_DISCOVERY_TABLE_NAMES = frozenset({
    "scholarship_discovery_runs",
    "scholarship_discovery_review_items",
})


class ScholarshipDiscoveryRun(Base):
    __tablename__ = "scholarship_discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_scholarship_discovery_run_status",
        ),
        CheckConstraint(
            "trigger_type IN ('scheduled', 'catch_up', 'manual')",
            name="ck_scholarship_discovery_run_trigger_type",
        ),
        Index(
            "uq_scholarship_discovery_run_scheduled_for",
            "scheduled_for",
            unique=True,
        ),
    )

    id = Column(String(36), primary_key=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    trigger_type = Column(String(16), nullable=False, default="manual", server_default="manual")
    scheduled_for = Column(DateTime(timezone=True))
    status = Column(String(16), nullable=False, default="running", server_default="running")
    summary = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    source_results = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))


class ScholarshipDiscoveryReviewItem(Base):
    __tablename__ = "scholarship_discovery_review_items"
    __table_args__ = (
        CheckConstraint(
            "source_classification IN ('official_provider', 'government_authority', 'trusted_listing')",
            name="ck_scholarship_discovery_review_source_classification",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'reviewed', 'accepted', 'rejected', 'duplicate')",
            name="ck_scholarship_discovery_review_status",
        ),
        CheckConstraint(
            "length(candidate_fingerprint) = 64",
            name="ck_scholarship_discovery_review_fingerprint",
        ),
        UniqueConstraint("candidate_fingerprint", name="uq_scholarship_discovery_review_fingerprint"),
        Index("ix_scholarship_discovery_review_status", "review_status", "id"),
        Index("ix_scholarship_discovery_review_identity", "candidate_name", "host_country"),
    )

    id = Column(Integer, primary_key=True)
    candidate_fingerprint = Column(String(64), nullable=False)
    candidate_name = Column(Text)
    host_country = Column(Text)
    source_id = Column(String(100), nullable=False)
    source_name = Column(String(255), nullable=False)
    source_classification = Column(String(32), nullable=False)
    source_trust_basis = Column(Text)
    source_url = Column(Text, nullable=False)
    page_count = Column(Integer)
    extracted_values = Column(JSON, nullable=False, default=dict)
    field_sources = Column(JSON, nullable=False, default=dict)
    evidence_excerpts = Column(JSON, nullable=False, default=list)
    missing_required_fields = Column(JSON, nullable=False, default=list)
    conflicting_values = Column(JSON, nullable=False, default=list)
    review_reason = Column(Text, nullable=False)
    discovery_run_id = Column(
        String(36),
        ForeignKey("scholarship_discovery_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_status = Column(String(20), nullable=False, default="pending", server_default="pending")
    accepted_scholarship_id = Column(
        Integer,
        ForeignKey("scholarships.id", ondelete="SET NULL"),
    )
    duplicate_of_scholarship_id = Column(
        Integer,
        ForeignKey("scholarships.id", ondelete="SET NULL"),
    )
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at = Column(DateTime(timezone=True))
    review_note = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    @validates("source_url")
    def _validate_source_url(self, _key, value):
        return validate_source_url(value)
