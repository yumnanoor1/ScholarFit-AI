from uuid import uuid4

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
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func

from app.database import Base
from app.services.source_url_safety import validate_source_url


_SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES = (
    "scholarship_discovery_publications",
    "scholarship_discovery_publication_versions",
    "scholarship_discovery_publication_sources",
    "scholarship_discovery_publication_events",
)
SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES = frozenset(
    _SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES
)


class ScholarshipDiscoveryPublication(Base):
    __tablename__ = "scholarship_discovery_publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('published', 'expired', 'withdrawn', 'revoked', 'superseded')",
            name="ck_discovery_publication_status",
        ),
        UniqueConstraint(
            "canonical_scholarship_id",
            name="uq_discovery_publication_canonical_scholarship",
        ),
        Index("ix_discovery_publication_status_updated", "status", "updated_at"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    canonical_scholarship_id = Column(
        Integer,
        ForeignKey("scholarships.id", ondelete="RESTRICT"),
        nullable=False,
    )
    current_version_id = Column(
        Integer,
        ForeignKey(
            "scholarship_discovery_publication_versions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_discovery_publication_current_version",
        ),
    )
    status = Column(String(16), nullable=False, default="published", server_default="published")
    published_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))
    revoked_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    revoked_by_email = Column(String(255))
    revocation_reason = Column(Text)
    superseded_by_publication_id = Column(
        String(36),
        ForeignKey("scholarship_discovery_publications.id", ondelete="SET NULL"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    current_version = relationship(
        "ScholarshipDiscoveryPublicationVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )
    versions = relationship(
        "ScholarshipDiscoveryPublicationVersion",
        foreign_keys="ScholarshipDiscoveryPublicationVersion.publication_id",
        back_populates="publication",
        order_by="ScholarshipDiscoveryPublicationVersion.version_number",
    )
    sources = relationship(
        "ScholarshipDiscoveryPublicationSource",
        back_populates="publication",
        order_by="ScholarshipDiscoveryPublicationSource.id",
    )


class ScholarshipDiscoveryPublicationVersion(Base):
    __tablename__ = "scholarship_discovery_publication_versions"
    __table_args__ = (
        CheckConstraint(
            "approval_decision IN ('accepted', 'link_and_publish')",
            name="ck_discovery_publication_version_decision",
        ),
        UniqueConstraint(
            "publication_id",
            "version_number",
            name="uq_discovery_publication_version_number",
        ),
        UniqueConstraint(
            "review_item_id",
            name="uq_discovery_publication_version_review_item",
        ),
        Index("ix_discovery_publication_version_publication", "publication_id", "id"),
    )

    id = Column(Integer, primary_key=True)
    publication_id = Column(
        String(36),
        ForeignKey("scholarship_discovery_publications.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_item_id = Column(
        Integer,
        ForeignKey("scholarship_discovery_review_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number = Column(Integer, nullable=False)
    candidate_name_at_approval = Column(Text)
    host_country_at_approval = Column(Text)
    approved_values = Column(JSON, nullable=False)
    source_evidence = Column(JSON, nullable=False, default=list)
    approval_decision = Column(String(24), nullable=False)
    approved_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_email = Column(String(255), nullable=False)
    approved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    publication = relationship(
        "ScholarshipDiscoveryPublication",
        foreign_keys=[publication_id],
        back_populates="versions",
    )


class ScholarshipDiscoveryPublicationSource(Base):
    __tablename__ = "scholarship_discovery_publication_sources"
    __table_args__ = (
        CheckConstraint(
            "source_classification IN ('official_provider', 'government_authority', 'trusted_listing')",
            name="ck_discovery_publication_source_classification",
        ),
        CheckConstraint(
            "source_check_status IN ('not_checked', 'succeeded', 'failed', 'content_changed')",
            name="ck_discovery_publication_source_check_status",
        ),
        CheckConstraint(
            "observed_content_hash IS NULL OR length(observed_content_hash) = 64",
            name="ck_discovery_publication_source_hash",
        ),
        UniqueConstraint(
            "publication_id",
            "source_id",
            "normalized_url",
            name="uq_discovery_publication_source_url",
        ),
        Index("ix_discovery_publication_source_identity", "source_id", "normalized_url"),
    )

    id = Column(Integer, primary_key=True)
    publication_id = Column(
        String(36),
        ForeignKey("scholarship_discovery_publications.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id = Column(String(100), nullable=False)
    source_name = Column(String(255), nullable=False)
    source_classification = Column(String(32), nullable=False)
    source_trust_basis = Column(Text)
    source_url = Column(Text, nullable=False)
    normalized_url = Column(String(2048), nullable=False)
    last_checked_at = Column(DateTime(timezone=True))
    last_successful_check_at = Column(DateTime(timezone=True))
    observed_content_hash = Column(String(64))
    source_check_status = Column(
        String(24),
        nullable=False,
        default="not_checked",
        server_default="not_checked",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    publication = relationship(
        "ScholarshipDiscoveryPublication",
        back_populates="sources",
    )

    @validates("source_url")
    def _validate_source_url(self, _key, value):
        return validate_source_url(value)


class ScholarshipDiscoveryPublicationEvent(Base):
    __tablename__ = "scholarship_discovery_publication_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('published', 'version_approved', 'version_superseded', "
            "'revoked', 'expired', 'withdrawn', 'superseded', 'republished')",
            name="ck_discovery_publication_event_type",
        ),
        CheckConstraint(
            "new_status IS NULL OR new_status IN "
            "('published', 'expired', 'withdrawn', 'revoked', 'superseded')",
            name="ck_discovery_publication_event_status",
        ),
        Index("ix_discovery_publication_event_history", "publication_id", "created_at", "id"),
    )

    id = Column(Integer, primary_key=True)
    publication_id = Column(
        String(36),
        ForeignKey("scholarship_discovery_publications.id", ondelete="RESTRICT"),
        nullable=False,
    )
    publication_version_id = Column(
        Integer,
        ForeignKey("scholarship_discovery_publication_versions.id", ondelete="RESTRICT"),
    )
    event_type = Column(String(24), nullable=False)
    previous_status = Column(String(16))
    new_status = Column(String(16))
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    actor_email = Column(String(255))
    reason = Column(Text)
    event_data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLES = tuple(
    Base.metadata.tables[name] for name in _SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES
)
