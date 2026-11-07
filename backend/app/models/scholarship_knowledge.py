from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    event,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.database import Base
from app.services.source_url_safety import validate_source_url

EMBEDDING_DIMENSIONS = 384


class ScholarshipSourceDocument(Base):
    __tablename__ = "scholarship_source_documents"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_scholarship_source_documents"),
        ForeignKeyConstraint(
            ["scholarship_id"], ["scholarships.id"],
            name="fk_scholarship_source_documents_scholarship",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_scholarship_source_normalized_url",
            "scholarship_id",
            "normalized_url",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
        CheckConstraint(
            "source_role IN ('official_information', 'official_application', 'additional_official')",
            name="ck_scholarship_source_role",
        ),
    )

    id = Column(Integer, primary_key=True)
    scholarship_id = Column(Integer, nullable=False, index=True)
    source_url = Column(Text, nullable=False)
    normalized_url = Column(String(2048), nullable=False)
    source_role = Column(String(32), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    scholarship = relationship("Scholarship")
    versions = relationship("ScholarshipDocumentVersion", back_populates="source_document", passive_deletes=True)

    @validates("source_url", "normalized_url")
    def _validate_source_url(self, _key, value):
        return validate_source_url(value)


class ScholarshipDocumentVersion(Base):
    __tablename__ = "scholarship_document_versions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_scholarship_document_versions"),
        ForeignKeyConstraint(
            ["source_document_id"], ["scholarship_source_documents.id"],
            name="fk_scholarship_document_versions_source_document",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "source_document_id", "content_hash", name="uq_scholarship_document_version_content_hash",
        ),
        CheckConstraint("length(content_hash) = 64", name="ck_scholarship_document_version_sha256"),
        CheckConstraint(
            "verification_status_snapshot IN ('verified', 'unverified')",
            name="ck_scholarship_document_version_verification_status",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected', 'stale')",
            name="ck_scholarship_document_version_review_status",
        ),
        CheckConstraint(
            "indexing_status IN ('pending', 'approved', 'indexed', 'failed', 'stale')",
            name="ck_scholarship_document_version_indexing_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    source_document_id = Column(Integer, nullable=False, index=True)
    content_hash = Column(String(64), nullable=False)
    retrieved_at = Column(DateTime(timezone=True), nullable=False)
    mime_type = Column(String(255), nullable=False)
    extractor_version = Column(String(100), nullable=False)
    extracted_text = Column(Text, nullable=False)
    page_count = Column(Integer)
    verification_status_snapshot = Column(String(20), nullable=False)
    verification_basis_snapshot = Column(String(32))
    last_verified_date_snapshot = Column(Date)
    scholarship_record_version_snapshot = Column(Integer)
    review_status = Column(String(20), nullable=False, default="pending", server_default="pending")
    indexing_status = Column(String(20), nullable=False, default="pending", server_default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    source_document = relationship("ScholarshipSourceDocument", back_populates="versions")
    chunks = relationship("ScholarshipDocumentChunk", back_populates="document_version", passive_deletes=True)
    approvals = relationship("ScholarshipDocumentVersionApproval", back_populates="document_version", passive_deletes=True)


class ScholarshipDocumentVersionApproval(Base):
    __tablename__ = "scholarship_document_version_approvals"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_scholarship_document_version_approvals"),
        ForeignKeyConstraint(
            ["document_version_id"], ["scholarship_document_versions.id"],
            name="fk_scholarship_document_version_approvals_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "document_version_id",
            name="uq_scholarship_document_version_approval_version",
        ),
        CheckConstraint(
            "decision IN ('approved', 'revoked')",
            name="ck_scholarship_document_version_approval_decision",
        ),
        CheckConstraint(
            "verification_status_snapshot IN ('verified', 'unverified')",
            name="ck_scholarship_document_version_approval_verification",
        ),
        CheckConstraint(
            "review_status_snapshot IN ('pending', 'approved', 'rejected', 'stale')",
            name="ck_scholarship_document_version_approval_review",
        ),
        CheckConstraint(
            "indexing_status_snapshot IN ('pending', 'approved', 'indexed', 'failed', 'stale')",
            name="ck_scholarship_document_version_approval_indexing",
        ),
        CheckConstraint(
            "decision <> 'approved' OR (document_record_version_snapshot IS NOT NULL "
            "AND scholarship_record_version_at_decision IS NOT NULL "
            "AND document_record_version_snapshot = scholarship_record_version_at_decision "
            "AND source_active_at_decision IS TRUE "
            "AND scholarship_verification_status_at_decision IS NOT NULL "
            "AND scholarship_verification_basis_at_decision IS NOT NULL "
            "AND scholarship_verification_status_at_decision = 'verified' "
            "AND scholarship_verification_basis_at_decision = 'official_source' "
            "AND scholarship_archived_at_decision IS NULL)",
            name="ck_scholarship_document_version_approval_scholarship",
        ),
    )

    id = Column(Integer, primary_key=True)
    document_version_id = Column(Integer, nullable=False, index=True)
    decision = Column(String(16), nullable=False)
    verification_status_snapshot = Column(String(20), nullable=False)
    verification_basis_snapshot = Column(String(32))
    review_status_snapshot = Column(String(20), nullable=False)
    indexing_status_snapshot = Column(String(20), nullable=False)
    document_record_version_snapshot = Column(Integer)
    source_active_at_decision = Column(Boolean, nullable=False)
    scholarship_record_version_at_decision = Column(Integer)
    scholarship_verification_status_at_decision = Column(String(32))
    scholarship_verification_basis_at_decision = Column(String(32))
    scholarship_archived_at_decision = Column(DateTime(timezone=True))
    actor = Column(String(255), nullable=False)
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document_version = relationship("ScholarshipDocumentVersion", back_populates="approvals")


class ScholarshipDocumentChunk(Base):
    __tablename__ = "scholarship_document_chunks"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_scholarship_document_chunks"),
        ForeignKeyConstraint(
            ["document_version_id"], ["scholarship_document_versions.id"],
            name="fk_scholarship_document_chunks_document_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "document_version_id", "chunk_ordinal", name="uq_scholarship_document_chunk_ordinal",
        ),
        UniqueConstraint(
            "id", "document_version_id", name="uq_scholarship_document_chunk_version",
        ),
        CheckConstraint("length(chunk_hash) = 64", name="ck_scholarship_document_chunk_sha256"),
        CheckConstraint("chunk_ordinal >= 0", name="ck_scholarship_document_chunk_ordinal"),
        CheckConstraint(
            "page_start IS NULL OR page_start > 0",
            name="ck_scholarship_document_chunk_page_start",
        ),
        CheckConstraint(
            "page_end IS NULL OR page_end >= page_start",
            name="ck_scholarship_document_chunk_page_end",
        ),
        CheckConstraint(
            "start_offset IS NULL OR start_offset >= 0",
            name="ck_scholarship_document_chunk_start_offset",
        ),
        CheckConstraint(
            "end_offset IS NULL OR end_offset >= start_offset",
            name="ck_scholarship_document_chunk_end_offset",
        ),
    )

    id = Column(Integer, primary_key=True)
    document_version_id = Column(Integer, nullable=False, index=True)
    chunk_ordinal = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_hash = Column(String(64), nullable=False)
    page_start = Column(Integer)
    page_end = Column(Integer)
    section_heading = Column(Text)
    section_path = Column(Text)
    start_offset = Column(Integer)
    end_offset = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document_version = relationship("ScholarshipDocumentVersion", back_populates="chunks")
    embeddings = relationship("ScholarshipChunkEmbedding", back_populates="chunk", passive_deletes=True)


class ScholarshipChunkEmbedding(Base):
    __tablename__ = "scholarship_chunk_embeddings"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_scholarship_chunk_embeddings"),
        ForeignKeyConstraint(
            ["chunk_id", "document_version_id"],
            ["scholarship_document_chunks.id", "scholarship_document_chunks.document_version_id"],
            name="fk_scholarship_chunk_embeddings_chunk_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["approval_id", "document_version_id"],
            [
                "scholarship_document_version_approvals.id",
                "scholarship_document_version_approvals.document_version_id",
            ],
            name="fk_scholarship_chunk_embeddings_approval",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "chunk_id", "model_name", "model_revision",
            name="uq_scholarship_chunk_embedding_model_revision",
        ),
        CheckConstraint(
            f"dimensions = {EMBEDDING_DIMENSIONS}",
            name="ck_scholarship_chunk_embedding_dimensions",
        ),
        Index(
            "ix_scholarship_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id = Column(Integer, primary_key=True)
    chunk_id = Column(Integer, nullable=False, index=True)
    document_version_id = Column(Integer, nullable=False)
    approval_id = Column(Integer, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    model_name = Column(String(255), nullable=False)
    model_revision = Column(String(100), nullable=False)
    dimensions = Column(Integer, nullable=False, default=EMBEDDING_DIMENSIONS, server_default="384")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    chunk = relationship("ScholarshipDocumentChunk", back_populates="embeddings")
    approval = relationship(
        "ScholarshipDocumentVersionApproval",
        overlaps="chunk,embeddings",
    )


def _trigger_ddl(statements, dialect):
    def create_triggers(_target, connection, **_kwargs):
        if connection.dialect.name == dialect:
            for statement in statements:
                connection.exec_driver_sql(statement.replace("%", "%%"))

    return create_triggers


_APPROVAL_POSTGRES_DDL = (
    """
    CREATE FUNCTION scholarship_knowledge_validate_approval() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        version_row scholarship_document_versions%ROWTYPE;
        source_row scholarship_source_documents%ROWTYPE;
        scholarship_row scholarships%ROWTYPE;
        source_document_id INTEGER;
        scholarship_id INTEGER;
    BEGIN
        SELECT v.source_document_id INTO source_document_id
        FROM scholarship_document_versions v
        WHERE v.id = NEW.document_version_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Scholarship document version does not exist';
        END IF;
        SELECT d.scholarship_id INTO scholarship_id
        FROM scholarship_source_documents d
        WHERE d.id = source_document_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Scholarship source document does not exist';
        END IF;
        SELECT * INTO scholarship_row FROM scholarships s
        WHERE s.id = scholarship_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Current scholarship does not exist';
        END IF;
        SELECT * INTO source_row FROM scholarship_source_documents d
        WHERE d.id = source_document_id FOR UPDATE;
        SELECT * INTO version_row FROM scholarship_document_versions v
        WHERE v.id = NEW.document_version_id FOR UPDATE;
        IF NEW.verification_status_snapshot IS DISTINCT FROM version_row.verification_status_snapshot
           OR NEW.verification_basis_snapshot IS DISTINCT FROM version_row.verification_basis_snapshot
           OR NEW.review_status_snapshot IS DISTINCT FROM version_row.review_status
           OR NEW.indexing_status_snapshot IS DISTINCT FROM version_row.indexing_status
           OR NEW.document_record_version_snapshot IS DISTINCT FROM version_row.scholarship_record_version_snapshot
           OR NEW.source_active_at_decision IS DISTINCT FROM source_row.is_active
           OR NEW.scholarship_record_version_at_decision IS DISTINCT FROM scholarship_row.record_version
           OR NEW.scholarship_verification_status_at_decision IS DISTINCT FROM scholarship_row.verification_status
           OR NEW.scholarship_verification_basis_at_decision IS DISTINCT FROM scholarship_row.verification_basis
           OR NEW.scholarship_archived_at_decision IS DISTINCT FROM scholarship_row.archived_at THEN
            RAISE EXCEPTION 'Approval snapshots must match the current document version';
        END IF;
        IF NEW.decision = 'approved'
           AND (version_row.verification_status_snapshot IS DISTINCT FROM 'verified'
                OR version_row.verification_basis_snapshot IS DISTINCT FROM 'official_source'
                OR version_row.review_status IS DISTINCT FROM 'approved'
                OR version_row.indexing_status IS DISTINCT FROM 'approved'
                OR source_row.is_active IS NOT TRUE
                OR scholarship_row.verification_status IS DISTINCT FROM 'verified'
                OR scholarship_row.verification_basis IS DISTINCT FROM 'official_source'
                OR scholarship_row.archived_at IS NOT NULL
                OR scholarship_row.record_version IS NULL
                OR scholarship_row.record_version IS DISTINCT FROM version_row.scholarship_record_version_snapshot) THEN
            RAISE EXCEPTION 'Document version or current scholarship does not meet approval requirements';
        END IF;
        RETURN NEW;
    END;
    $$;
    """,
    """
    CREATE FUNCTION scholarship_knowledge_reject_history_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'Scholarship knowledge history is immutable';
        RETURN OLD;
    END;
    $$;
    """,
    """
    CREATE FUNCTION scholarship_knowledge_protect_source_identity() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Scholarship source documents are immutable history';
        END IF;
        IF ROW(
            NEW.id, NEW.scholarship_id, NEW.source_url, NEW.normalized_url,
            NEW.source_role, NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.scholarship_id, OLD.source_url, OLD.normalized_url,
            OLD.source_role, OLD.created_at
        ) THEN
            RAISE EXCEPTION 'Scholarship source identity and creation provenance are immutable';
        END IF;
        RETURN NEW;
    END;
    $$;
    """,
    """
    CREATE FUNCTION scholarship_knowledge_serialize_integrity_writes() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        -- Acquire the shared transaction lock before row triggers to serialize eligibility writes.
        PERFORM pg_advisory_xact_lock(728341901270418);
        RETURN NULL;
    END;
    $$;
    """,
    """
    CREATE FUNCTION scholarship_knowledge_reject_history_truncate() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'Scholarship knowledge history cannot be truncated';
        RETURN NULL;
    END;
    $$;
    """,
    """
    CREATE FUNCTION scholarship_knowledge_revoke_approval() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.verification_status_snapshot = 'verified'
           AND OLD.verification_basis_snapshot = 'official_source'
           AND OLD.review_status = 'approved'
           AND OLD.indexing_status IN ('approved', 'indexed')
           AND (
                NEW.scholarship_record_version_snapshot IS DISTINCT FROM OLD.scholarship_record_version_snapshot
                OR NOT (NEW.verification_status_snapshot = 'verified'
                        AND NEW.verification_basis_snapshot = 'official_source'
                        AND NEW.review_status = 'approved'
                        AND NEW.indexing_status IN ('approved', 'indexed'))
           ) THEN
            INSERT INTO scholarship_document_version_approvals (
                document_version_id, decision, verification_status_snapshot,
                verification_basis_snapshot, review_status_snapshot,
                indexing_status_snapshot, document_record_version_snapshot,
                source_active_at_decision,
                scholarship_record_version_at_decision,
                scholarship_verification_status_at_decision,
                scholarship_verification_basis_at_decision,
                scholarship_archived_at_decision, actor, reason
            )
            SELECT NEW.id, 'revoked', NEW.verification_status_snapshot,
                NEW.verification_basis_snapshot, NEW.review_status, NEW.indexing_status,
                NEW.scholarship_record_version_snapshot, d.is_active, s.record_version,
                s.verification_status, s.verification_basis, s.archived_at,
                'database-trigger', 'Document version eligibility changed'
            FROM scholarship_source_documents d
            JOIN scholarships s ON s.id = d.scholarship_id
            WHERE d.id = NEW.source_document_id;
        END IF;
        RETURN NEW;
    END;
    $$;
    """,
    """
    CREATE FUNCTION scholarship_knowledge_revoke_scholarship_approval() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO scholarship_document_version_approvals (
            document_version_id, decision, verification_status_snapshot,
            verification_basis_snapshot, review_status_snapshot, indexing_status_snapshot,
            document_record_version_snapshot, source_active_at_decision,
            scholarship_record_version_at_decision,
            scholarship_verification_status_at_decision,
            scholarship_verification_basis_at_decision,
            scholarship_archived_at_decision, actor, reason
        )
        SELECT v.id, 'revoked', v.verification_status_snapshot,
            v.verification_basis_snapshot, v.review_status, v.indexing_status,
            v.scholarship_record_version_snapshot, d.is_active, NEW.record_version,
            NEW.verification_status, NEW.verification_basis, NEW.archived_at,
            'database-trigger', 'Current scholarship eligibility changed'
        FROM scholarship_source_documents d
        JOIN scholarship_document_versions v ON v.source_document_id = d.id
        WHERE d.scholarship_id = NEW.id
          AND (
            NEW.verification_status IS DISTINCT FROM 'verified'
            OR NEW.verification_basis IS DISTINCT FROM 'official_source'
            OR NEW.archived_at IS NOT NULL
            OR NEW.record_version IS NULL
            OR NEW.record_version IS DISTINCT FROM v.scholarship_record_version_snapshot
          )
          AND EXISTS (
            SELECT 1 FROM scholarship_document_version_approvals a
            WHERE a.document_version_id = v.id
              AND a.id = (
                SELECT MAX(latest.id) FROM scholarship_document_version_approvals latest
                WHERE latest.document_version_id = v.id
              )
              AND a.decision = 'approved'
          );
        RETURN NEW;
    END;
    $$;
    """,
    """
    CREATE FUNCTION scholarship_knowledge_revoke_source_approval() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.is_active IS TRUE AND NEW.is_active IS FALSE THEN
            INSERT INTO scholarship_document_version_approvals (
                document_version_id, decision, verification_status_snapshot,
                verification_basis_snapshot, review_status_snapshot, indexing_status_snapshot,
                document_record_version_snapshot, source_active_at_decision,
                scholarship_record_version_at_decision,
                scholarship_verification_status_at_decision,
                scholarship_verification_basis_at_decision,
                scholarship_archived_at_decision, actor, reason
            )
            SELECT v.id, 'revoked', v.verification_status_snapshot,
                v.verification_basis_snapshot, v.review_status, v.indexing_status,
                v.scholarship_record_version_snapshot, NEW.is_active, s.record_version,
                s.verification_status, s.verification_basis, s.archived_at,
                'database-trigger', 'Scholarship source document deactivated'
            FROM scholarship_document_versions v
            JOIN scholarships s ON s.id = NEW.scholarship_id
            WHERE v.source_document_id = NEW.id
              AND EXISTS (
                SELECT 1 FROM scholarship_document_version_approvals a
                WHERE a.document_version_id = v.id
                  AND a.id = (
                    SELECT MAX(latest.id) FROM scholarship_document_version_approvals latest
                    WHERE latest.document_version_id = v.id
                  )
                  AND a.decision = 'approved'
              );
        END IF;
        RETURN NEW;
    END;
    $$;
    """,
    """
    CREATE TRIGGER trg_scholarship_document_version_approvals_validate
    BEFORE INSERT ON scholarship_document_version_approvals
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_validate_approval();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_version_approvals_serialize
    BEFORE INSERT ON scholarship_document_version_approvals
    FOR EACH STATEMENT
    EXECUTE FUNCTION scholarship_knowledge_serialize_integrity_writes();
    """,
    """
    CREATE TRIGGER trg_scholarship_source_documents_serialize
    BEFORE UPDATE OF is_active ON scholarship_source_documents
    FOR EACH STATEMENT
    EXECUTE FUNCTION scholarship_knowledge_serialize_integrity_writes();
    """,
    """
    CREATE TRIGGER trg_scholarships_serialize
    BEFORE UPDATE OF verification_status, verification_basis, archived_at, record_version
    ON scholarships FOR EACH STATEMENT
    EXECUTE FUNCTION scholarship_knowledge_serialize_integrity_writes();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_versions_serialize
    BEFORE UPDATE OF verification_status_snapshot, verification_basis_snapshot,
        review_status, indexing_status, scholarship_record_version_snapshot
    ON scholarship_document_versions FOR EACH STATEMENT
    EXECUTE FUNCTION scholarship_knowledge_serialize_integrity_writes();
    """,
    """
    CREATE TRIGGER trg_scholarship_source_documents_protect_identity
    BEFORE UPDATE ON scholarship_source_documents
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_protect_source_identity();
    """,
    """
    CREATE TRIGGER trg_scholarship_source_documents_protect_delete
    BEFORE DELETE ON scholarship_source_documents
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_protect_source_identity();
    """,
    """
    CREATE TRIGGER trg_scholarship_source_documents_reject_truncate
    BEFORE TRUNCATE ON scholarship_source_documents
    FOR EACH STATEMENT EXECUTE FUNCTION scholarship_knowledge_reject_history_truncate();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_version_approvals_immutable_update
    BEFORE UPDATE ON scholarship_document_version_approvals
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_reject_history_mutation();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_version_approvals_immutable_delete
    BEFORE DELETE ON scholarship_document_version_approvals
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_reject_history_mutation();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_version_approvals_reject_truncate
    BEFORE TRUNCATE ON scholarship_document_version_approvals
    FOR EACH STATEMENT EXECUTE FUNCTION scholarship_knowledge_reject_history_truncate();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_versions_reject_truncate
    BEFORE TRUNCATE ON scholarship_document_versions
    FOR EACH STATEMENT EXECUTE FUNCTION scholarship_knowledge_reject_history_truncate();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_versions_revoke_approval
    AFTER UPDATE OF verification_status_snapshot, verification_basis_snapshot,
        review_status, indexing_status, scholarship_record_version_snapshot
        ON scholarship_document_versions
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_revoke_approval();
    """,
    """
    CREATE TRIGGER trg_scholarships_revoke_approval
    AFTER UPDATE OF verification_status, verification_basis, archived_at, record_version
    ON scholarships FOR EACH ROW
    EXECUTE FUNCTION scholarship_knowledge_revoke_scholarship_approval();
    """,
    """
    CREATE TRIGGER trg_scholarship_source_documents_revoke_approval
    AFTER UPDATE OF is_active ON scholarship_source_documents
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_revoke_source_approval();
    """,
)

_APPROVAL_SQLITE_DDL = (
    """
    CREATE TRIGGER trg_scholarship_source_documents_protect_identity
    BEFORE UPDATE ON scholarship_source_documents
    WHEN NEW.id IS NOT OLD.id
      OR NEW.scholarship_id IS NOT OLD.scholarship_id
      OR NEW.source_url IS NOT OLD.source_url
      OR NEW.normalized_url IS NOT OLD.normalized_url
      OR NEW.source_role IS NOT OLD.source_role
      OR NEW.created_at IS NOT OLD.created_at
    BEGIN
        SELECT RAISE(ABORT, 'Scholarship source identity and creation provenance are immutable');
    END
    """,
    """
    CREATE TRIGGER trg_scholarship_source_documents_protect_delete
    BEFORE DELETE ON scholarship_source_documents
    BEGIN
        SELECT RAISE(ABORT, 'Scholarship source documents are immutable history');
    END
    """,
    """
    CREATE TRIGGER trg_scholarship_document_version_approvals_validate
    BEFORE INSERT ON scholarship_document_version_approvals
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
              SELECT 1
              FROM scholarship_document_versions v
              JOIN scholarship_source_documents d ON d.id = v.source_document_id
              JOIN scholarships s ON s.id = d.scholarship_id
              WHERE v.id = NEW.document_version_id
                AND v.verification_status_snapshot = NEW.verification_status_snapshot
                AND v.verification_basis_snapshot IS NEW.verification_basis_snapshot
                AND v.review_status = NEW.review_status_snapshot
                AND v.indexing_status = NEW.indexing_status_snapshot
                AND v.scholarship_record_version_snapshot IS NEW.document_record_version_snapshot
                AND d.is_active IS NEW.source_active_at_decision
                AND s.record_version IS NEW.scholarship_record_version_at_decision
                AND s.verification_status IS NEW.scholarship_verification_status_at_decision
                AND s.verification_basis IS NEW.scholarship_verification_basis_at_decision
                AND s.archived_at IS NEW.scholarship_archived_at_decision
                AND (
                  NEW.decision <> 'approved'
                  OR (v.verification_status_snapshot = 'verified'
                      AND v.verification_basis_snapshot = 'official_source'
                      AND v.review_status = 'approved'
                      AND v.indexing_status = 'approved'
                      AND d.is_active = 1
                      AND s.verification_status = 'verified'
                      AND s.verification_basis = 'official_source'
                      AND s.archived_at IS NULL
                      AND s.record_version IS NOT NULL
                      AND s.record_version = v.scholarship_record_version_snapshot)
              )
        ) THEN RAISE(ABORT, 'Invalid scholarship document version approval') END;
    END
    """,
    """
    CREATE TRIGGER trg_scholarship_document_version_approvals_immutable_update
    BEFORE UPDATE ON scholarship_document_version_approvals
    BEGIN SELECT RAISE(ABORT, 'Scholarship approval history is immutable'); END
    """,
    """
    CREATE TRIGGER trg_scholarship_document_version_approvals_immutable_delete
    BEFORE DELETE ON scholarship_document_version_approvals
    BEGIN SELECT RAISE(ABORT, 'Scholarship approval history is immutable'); END
    """,
    """
    CREATE TRIGGER trg_scholarship_document_versions_revoke_approval
    AFTER UPDATE OF verification_status_snapshot, verification_basis_snapshot,
        review_status, indexing_status, scholarship_record_version_snapshot
        ON scholarship_document_versions
    WHEN OLD.verification_status_snapshot = 'verified'
      AND OLD.verification_basis_snapshot = 'official_source'
      AND OLD.review_status = 'approved'
      AND OLD.indexing_status IN ('approved', 'indexed')
      AND (
        NEW.scholarship_record_version_snapshot IS NOT OLD.scholarship_record_version_snapshot
        OR NOT (NEW.verification_status_snapshot = 'verified'
                AND NEW.verification_basis_snapshot = 'official_source'
                AND NEW.review_status = 'approved'
                AND NEW.indexing_status IN ('approved', 'indexed'))
      )
    BEGIN
        INSERT INTO scholarship_document_version_approvals (
            document_version_id, decision, verification_status_snapshot,
            verification_basis_snapshot, review_status_snapshot,
            indexing_status_snapshot, document_record_version_snapshot,
            source_active_at_decision,
            scholarship_record_version_at_decision,
            scholarship_verification_status_at_decision,
            scholarship_verification_basis_at_decision,
            scholarship_archived_at_decision, actor, reason
        )
        SELECT NEW.id, 'revoked', NEW.verification_status_snapshot,
            NEW.verification_basis_snapshot, NEW.review_status, NEW.indexing_status,
            NEW.scholarship_record_version_snapshot, d.is_active, s.record_version,
            s.verification_status, s.verification_basis, s.archived_at,
            'database-trigger', 'Document version eligibility changed'
        FROM scholarship_source_documents d
        JOIN scholarships s ON s.id = d.scholarship_id
        WHERE d.id = NEW.source_document_id;
    END
    """,
    """
    CREATE TRIGGER trg_scholarships_revoke_approval
    AFTER UPDATE OF verification_status, verification_basis, archived_at, record_version
    ON scholarships
    BEGIN
        INSERT INTO scholarship_document_version_approvals (
            document_version_id, decision, verification_status_snapshot,
            verification_basis_snapshot, review_status_snapshot, indexing_status_snapshot,
            document_record_version_snapshot, source_active_at_decision,
            scholarship_record_version_at_decision,
            scholarship_verification_status_at_decision,
            scholarship_verification_basis_at_decision,
            scholarship_archived_at_decision, actor, reason
        )
        SELECT v.id, 'revoked', v.verification_status_snapshot,
            v.verification_basis_snapshot, v.review_status, v.indexing_status,
            v.scholarship_record_version_snapshot, d.is_active, NEW.record_version,
            NEW.verification_status, NEW.verification_basis, NEW.archived_at,
            'database-trigger', 'Current scholarship eligibility changed'
        FROM scholarship_source_documents d
        JOIN scholarship_document_versions v ON v.source_document_id = d.id
        WHERE d.scholarship_id = NEW.id
          AND (
            NEW.verification_status IS NOT 'verified'
            OR NEW.verification_basis IS NOT 'official_source'
            OR NEW.archived_at IS NOT NULL
            OR NEW.record_version IS NULL
            OR NEW.record_version IS NOT v.scholarship_record_version_snapshot
          )
          AND EXISTS (
            SELECT 1 FROM scholarship_document_version_approvals a
            WHERE a.document_version_id = v.id
              AND a.id = (
                SELECT MAX(latest.id) FROM scholarship_document_version_approvals latest
                WHERE latest.document_version_id = v.id
              )
              AND a.decision = 'approved'
          );
    END
    """,
    """
    CREATE TRIGGER trg_scholarship_source_documents_revoke_approval
    AFTER UPDATE OF is_active ON scholarship_source_documents
    WHEN OLD.is_active = 1 AND NEW.is_active = 0
    BEGIN
        INSERT INTO scholarship_document_version_approvals (
            document_version_id, decision, verification_status_snapshot,
            verification_basis_snapshot, review_status_snapshot, indexing_status_snapshot,
            document_record_version_snapshot, source_active_at_decision,
            scholarship_record_version_at_decision,
            scholarship_verification_status_at_decision,
            scholarship_verification_basis_at_decision,
            scholarship_archived_at_decision, actor, reason
        )
        SELECT v.id, 'revoked', v.verification_status_snapshot,
            v.verification_basis_snapshot, v.review_status, v.indexing_status,
            v.scholarship_record_version_snapshot, NEW.is_active, s.record_version,
            s.verification_status, s.verification_basis, s.archived_at,
            'database-trigger', 'Scholarship source document deactivated'
        FROM scholarship_document_versions v
        JOIN scholarships s ON s.id = NEW.scholarship_id
        WHERE v.source_document_id = NEW.id
          AND EXISTS (
            SELECT 1 FROM scholarship_document_version_approvals a
            WHERE a.document_version_id = v.id
              AND a.id = (
                SELECT MAX(latest.id) FROM scholarship_document_version_approvals latest
                WHERE latest.document_version_id = v.id
              )
              AND a.decision = 'approved'
          );
    END
    """,
)

event.listen(
    ScholarshipDocumentVersionApproval.__table__,
    "after_create",
    _trigger_ddl(_APPROVAL_POSTGRES_DDL, "postgresql"),
)
event.listen(
    ScholarshipDocumentVersionApproval.__table__,
    "after_create",
    _trigger_ddl(_APPROVAL_SQLITE_DDL, "sqlite"),
)

_EMBEDDING_POSTGRES_DDL = (
    """
    CREATE FUNCTION scholarship_knowledge_protect_document_version() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Scholarship document versions are immutable history';
        END IF;
        IF ROW(
            NEW.source_document_id, NEW.content_hash, NEW.retrieved_at, NEW.mime_type,
            NEW.extractor_version, NEW.extracted_text, NEW.page_count,
            NEW.verification_status_snapshot, NEW.verification_basis_snapshot,
            NEW.last_verified_date_snapshot, NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.source_document_id, OLD.content_hash, OLD.retrieved_at, OLD.mime_type,
            OLD.extractor_version, OLD.extracted_text, OLD.page_count,
            OLD.verification_status_snapshot, OLD.verification_basis_snapshot,
            OLD.last_verified_date_snapshot, OLD.created_at
        ) THEN
            RAISE EXCEPTION 'Scholarship document version content and provenance are immutable';
        END IF;
        RETURN NEW;
    END;
    $$;
    """,
    """
    CREATE FUNCTION scholarship_knowledge_validate_embedding() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        latest_approval scholarship_document_version_approvals%ROWTYPE;
        document_version_id INTEGER;
        source_document_id INTEGER;
        scholarship_id INTEGER;
    BEGIN
        SELECT c.document_version_id INTO document_version_id
        FROM scholarship_document_chunks c
        WHERE c.id = NEW.chunk_id;
        SELECT v.source_document_id INTO source_document_id
        FROM scholarship_document_versions v
        WHERE v.id = document_version_id;
        SELECT d.scholarship_id INTO scholarship_id
        FROM scholarship_source_documents d
        WHERE d.id = source_document_id;
        PERFORM 1 FROM scholarships s WHERE s.id = scholarship_id FOR UPDATE;
        PERFORM 1 FROM scholarship_source_documents d
        WHERE d.id = source_document_id FOR UPDATE;
        PERFORM 1 FROM scholarship_document_versions v
        WHERE v.id = document_version_id FOR UPDATE;

        IF NOT EXISTS (
            SELECT 1 FROM scholarship_document_chunks c
            JOIN scholarship_document_versions v ON v.id = c.document_version_id
            JOIN scholarship_source_documents d ON d.id = v.source_document_id
            JOIN scholarships s ON s.id = d.scholarship_id
            WHERE c.id = NEW.chunk_id AND c.document_version_id = NEW.document_version_id
              AND v.verification_status_snapshot = 'verified'
              AND v.verification_basis_snapshot = 'official_source'
              AND v.review_status = 'approved'
              AND v.indexing_status IN ('approved', 'indexed')
              AND d.is_active IS TRUE
              AND s.verification_status = 'verified'
              AND s.verification_basis = 'official_source'
              AND s.archived_at IS NULL
              AND s.record_version IS NOT NULL
              AND s.record_version = v.scholarship_record_version_snapshot
        ) THEN
            RAISE EXCEPTION 'Embedding requires a current, verified, unarchived scholarship and approved version';
        END IF;
        SELECT a.* INTO latest_approval
        FROM scholarship_document_version_approvals AS a
        WHERE a.document_version_id = NEW.document_version_id
        ORDER BY a.id DESC
        LIMIT 1;
        IF NOT FOUND OR latest_approval.id <> NEW.approval_id
           OR latest_approval.decision <> 'approved'
           OR latest_approval.source_active_at_decision IS NOT TRUE THEN
            RAISE EXCEPTION 'Embedding requires the current approved indexing event';
        END IF;
        RETURN NEW;
    END;
    $$;
    """,
    """
    CREATE TRIGGER trg_scholarship_document_chunks_reject_truncate
    BEFORE TRUNCATE ON scholarship_document_chunks
    FOR EACH STATEMENT EXECUTE FUNCTION scholarship_knowledge_reject_history_truncate();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_versions_immutable_update
    BEFORE UPDATE ON scholarship_document_versions
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_protect_document_version();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_versions_immutable_delete
    BEFORE DELETE ON scholarship_document_versions
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_protect_document_version();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_chunks_immutable_update
    BEFORE UPDATE ON scholarship_document_chunks
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_reject_history_mutation();
    """,
    """
    CREATE TRIGGER trg_scholarship_document_chunks_immutable_delete
    BEFORE DELETE ON scholarship_document_chunks
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_reject_history_mutation();
    """,
    """
    CREATE TRIGGER trg_scholarship_chunk_embeddings_validate_approval
    BEFORE INSERT ON scholarship_chunk_embeddings
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_validate_embedding();
    """,
    """
    CREATE TRIGGER trg_scholarship_chunk_embeddings_serialize
    BEFORE INSERT ON scholarship_chunk_embeddings
    FOR EACH STATEMENT
    EXECUTE FUNCTION scholarship_knowledge_serialize_integrity_writes();
    """,
    """
    CREATE TRIGGER trg_scholarship_chunk_embeddings_reject_truncate
    BEFORE TRUNCATE ON scholarship_chunk_embeddings
    FOR EACH STATEMENT EXECUTE FUNCTION scholarship_knowledge_reject_history_truncate();
    """,
    """
    CREATE TRIGGER trg_scholarship_chunk_embeddings_immutable_update
    BEFORE UPDATE ON scholarship_chunk_embeddings
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_reject_history_mutation();
    """,
    """
    CREATE TRIGGER trg_scholarship_chunk_embeddings_immutable_delete
    BEFORE DELETE ON scholarship_chunk_embeddings
    FOR EACH ROW EXECUTE FUNCTION scholarship_knowledge_reject_history_mutation();
    """,
)
_EMBEDDING_SQLITE_DDL = (
    """
    CREATE TRIGGER trg_scholarship_chunk_embeddings_validate_approval
    BEFORE INSERT ON scholarship_chunk_embeddings
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM scholarship_document_chunks c
            JOIN scholarship_document_versions v ON v.id = c.document_version_id
            JOIN scholarship_source_documents d ON d.id = v.source_document_id
            JOIN scholarships s ON s.id = d.scholarship_id
            JOIN scholarship_document_version_approvals a
              ON a.document_version_id = v.id AND a.id = NEW.approval_id
            WHERE c.id = NEW.chunk_id AND c.document_version_id = NEW.document_version_id
              AND v.verification_status_snapshot = 'verified'
              AND v.verification_basis_snapshot = 'official_source'
              AND v.review_status = 'approved'
              AND v.indexing_status IN ('approved', 'indexed')
              AND d.is_active = 1
              AND s.verification_status = 'verified'
              AND s.verification_basis = 'official_source'
              AND s.archived_at IS NULL
              AND s.record_version IS NOT NULL
              AND s.record_version = v.scholarship_record_version_snapshot
              AND a.decision = 'approved'
              AND a.source_active_at_decision = 1
              AND a.scholarship_record_version_at_decision = s.record_version
              AND a.scholarship_verification_status_at_decision = s.verification_status
              AND a.scholarship_verification_basis_at_decision = s.verification_basis
              AND a.scholarship_archived_at_decision IS s.archived_at
              AND a.id = (
                SELECT MAX(latest.id) FROM scholarship_document_version_approvals latest
                WHERE latest.document_version_id = v.id
              )
        ) THEN RAISE(ABORT, 'Embedding requires current indexing approval') END;
    END
    """,
    """
    CREATE TRIGGER trg_scholarship_document_versions_immutable_update
    BEFORE UPDATE ON scholarship_document_versions
    WHEN NEW.source_document_id IS NOT OLD.source_document_id
      OR NEW.content_hash IS NOT OLD.content_hash
      OR NEW.retrieved_at IS NOT OLD.retrieved_at
      OR NEW.mime_type IS NOT OLD.mime_type
      OR NEW.extractor_version IS NOT OLD.extractor_version
      OR NEW.extracted_text IS NOT OLD.extracted_text
      OR NEW.page_count IS NOT OLD.page_count
      OR NEW.verification_status_snapshot IS NOT OLD.verification_status_snapshot
      OR NEW.verification_basis_snapshot IS NOT OLD.verification_basis_snapshot
      OR NEW.last_verified_date_snapshot IS NOT OLD.last_verified_date_snapshot
      OR NEW.created_at IS NOT OLD.created_at
    BEGIN SELECT RAISE(ABORT, 'Scholarship document version content and provenance are immutable'); END
    """,
    """
    CREATE TRIGGER trg_scholarship_document_versions_immutable_delete
    BEFORE DELETE ON scholarship_document_versions
    BEGIN SELECT RAISE(ABORT, 'Scholarship document versions are immutable history'); END
    """,
    """
    CREATE TRIGGER trg_scholarship_document_chunks_immutable_update
    BEFORE UPDATE ON scholarship_document_chunks
    BEGIN SELECT RAISE(ABORT, 'Scholarship document chunks are immutable history'); END
    """,
    """
    CREATE TRIGGER trg_scholarship_document_chunks_immutable_delete
    BEFORE DELETE ON scholarship_document_chunks
    BEGIN SELECT RAISE(ABORT, 'Scholarship document chunks are immutable history'); END
    """,
    """
    CREATE TRIGGER trg_scholarship_chunk_embeddings_immutable_update
    BEFORE UPDATE ON scholarship_chunk_embeddings
    BEGIN SELECT RAISE(ABORT, 'Scholarship embeddings are immutable history'); END
    """,
    """
    CREATE TRIGGER trg_scholarship_chunk_embeddings_immutable_delete
    BEFORE DELETE ON scholarship_chunk_embeddings
    BEGIN SELECT RAISE(ABORT, 'Scholarship embeddings are immutable history'); END
    """,
)
event.listen(
    ScholarshipChunkEmbedding.__table__,
    "after_create",
    _trigger_ddl(_EMBEDDING_POSTGRES_DDL, "postgresql"),
)
event.listen(
    ScholarshipChunkEmbedding.__table__,
    "after_create",
    _trigger_ddl(_EMBEDDING_SQLITE_DDL, "sqlite"),
)


SCHOLARSHIP_KNOWLEDGE_TABLES = (
    ScholarshipSourceDocument.__table__,
    ScholarshipDocumentVersion.__table__,
    ScholarshipDocumentVersionApproval.__table__,
    ScholarshipDocumentChunk.__table__,
    ScholarshipChunkEmbedding.__table__,
)
SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES = frozenset(table.name for table in SCHOLARSHIP_KNOWLEDGE_TABLES)
