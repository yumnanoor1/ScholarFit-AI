import contextlib
import io
import re
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, create_application_schema
from app.models.opportunity import Scholarship
from app.models.scholarship_knowledge import (
    EMBEDDING_DIMENSIONS,
    SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES,
    SCHOLARSHIP_KNOWLEDGE_TABLES,
    ScholarshipChunkEmbedding,
    ScholarshipDocumentChunk,
    ScholarshipDocumentVersion,
    ScholarshipDocumentVersionApproval,
    ScholarshipSourceDocument,
)
from app.models import scholarship_knowledge as knowledge_model
from app.models.user import User
from app.services.scholarship_quality import delete_record, reference_counts
from app.services import scholarship_knowledge_schema as schema_check
import migrate_scholarship_knowledge as migration


def _sqlite_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


class ScholarshipKnowledgeModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = _sqlite_engine()
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.scholarship = Scholarship(
            country="Finland",
            name="Test Scholarship",
            verification_status="verified",
            verification_basis="official_source",
            record_version=1,
        )
        self.db.add(self.scholarship)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _source_document(self, suffix=""):
        url = f"https://official.example/scholarship{suffix}"
        document = ScholarshipSourceDocument(
            scholarship_id=self.scholarship.id,
            source_url=url,
            normalized_url=url,
            source_role="official_information",
        )
        self.db.add(document)
        self.db.flush()
        return document

    def _version(
        self,
        document,
        content_hash="a" * 64,
        review_status="approved",
        verification_status="verified",
        verification_basis="official_source",
        indexing_status="pending",
    ):
        version = ScholarshipDocumentVersion(
            source_document_id=document.id,
            content_hash=content_hash,
            retrieved_at=datetime.now(timezone.utc),
            mime_type="text/html",
            extractor_version="test-parser-1",
            extracted_text="Official scholarship information.",
            verification_status_snapshot=verification_status,
            verification_basis_snapshot=verification_basis,
            last_verified_date_snapshot=date.today(),
            scholarship_record_version_snapshot=1,
            review_status=review_status,
            indexing_status=indexing_status,
        )
        self.db.add(version)
        self.db.flush()
        return version

    def _chunk(self, version, ordinal=0):
        chunk = ScholarshipDocumentChunk(
            document_version_id=version.id,
            chunk_ordinal=ordinal,
            chunk_text="Official scholarship information.",
            chunk_hash="b" * 64,
        )
        self.db.add(chunk)
        self.db.flush()
        return chunk

    def _approval_event(self, version, decision, source_active=None):
        scholarship = self.db.get(Scholarship, self.scholarship.id)
        source_document = self.db.get(ScholarshipSourceDocument, version.source_document_id)
        approval = ScholarshipDocumentVersionApproval(
            document_version_id=version.id,
            decision=decision,
            verification_status_snapshot=version.verification_status_snapshot,
            verification_basis_snapshot=version.verification_basis_snapshot,
            review_status_snapshot=version.review_status,
            indexing_status_snapshot=version.indexing_status,
            document_record_version_snapshot=version.scholarship_record_version_snapshot,
            source_active_at_decision=(
                source_document.is_active if source_active is None else source_active
            ),
            scholarship_record_version_at_decision=scholarship.record_version,
            scholarship_verification_status_at_decision=scholarship.verification_status,
            scholarship_verification_basis_at_decision=scholarship.verification_basis,
            scholarship_archived_at_decision=scholarship.archived_at,
            actor="test",
            reason="Focused test approval event",
        )
        self.db.add(approval)
        self.db.flush()
        return approval

    def _approve_indexing(self, version):
        version.indexing_status = "approved"
        self.db.flush()
        return self._approval_event(version, "approved")

    def _embedding(self, chunk, approval, model_revision="test-revision"):
        return ScholarshipChunkEmbedding(
            chunk_id=chunk.id,
            document_version_id=chunk.document_version_id,
            approval_id=approval.id,
            embedding=[0.0] * EMBEDDING_DIMENSIONS,
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_revision=model_revision,
            dimensions=EMBEDDING_DIMENSIONS,
        )

    def test_registered_tables_and_foreign_key_relationships(self):
        self.assertTrue(SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES.issubset(Base.metadata.tables))
        self.assertIs(models.ScholarshipSourceDocument, ScholarshipSourceDocument)
        foreign_keys = {
            constraint.name: constraint
            for table in SCHOLARSHIP_KNOWLEDGE_TABLES
            for constraint in table.foreign_key_constraints
        }
        self.assertEqual(len(foreign_keys), 6)
        self.assertTrue(all(constraint.ondelete == "RESTRICT" for constraint in foreign_keys.values()))
        self.assertEqual(
            set(foreign_keys),
            {
                "fk_scholarship_source_documents_scholarship",
                "fk_scholarship_document_versions_source_document",
                "fk_scholarship_document_chunks_document_version",
                "fk_scholarship_document_version_approvals_version",
                "fk_scholarship_chunk_embeddings_chunk_version",
                "fk_scholarship_chunk_embeddings_approval",
            },
        )
        self.assertIs(self._source_document().scholarship, self.scholarship)

    def test_source_url_is_unique_per_scholarship(self):
        self._source_document()
        self.db.add(ScholarshipSourceDocument(
            scholarship_id=self.scholarship.id,
            source_url="https://official.example/scholarship/",
            normalized_url="https://official.example/scholarship",
            source_role="official_information",
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_source_identity_and_creation_provenance_are_immutable(self):
        document = self._source_document()
        version = self._version(document)
        approval = self._approve_indexing(version)
        chunk = self._chunk(version)
        embedding = self._embedding(chunk, approval)
        self.db.add(embedding)
        self.db.commit()

        identity_updates = (
            "UPDATE scholarship_source_documents SET id = id + 100 WHERE id = :id",
            "UPDATE scholarship_source_documents SET scholarship_id = scholarship_id + 1 WHERE id = :id",
            "UPDATE scholarship_source_documents SET source_url = 'https://changed.example/' WHERE id = :id",
            "UPDATE scholarship_source_documents SET normalized_url = 'https://changed.example/' WHERE id = :id",
            "UPDATE scholarship_source_documents SET source_role = 'additional_official' WHERE id = :id",
            "UPDATE scholarship_source_documents SET created_at = '2000-01-01 00:00:00' WHERE id = :id",
        )
        for statement in identity_updates:
            with self.subTest(statement=statement):
                with self.assertRaises(IntegrityError) as error:
                    self.db.execute(text(statement), {"id": document.id})
                    self.db.commit()
                self.assertIn("identity and creation provenance are immutable", str(error.exception.orig))
                self.db.rollback()

        self.assertTrue(self.db.get(ScholarshipSourceDocument, document.id).is_active)
        self.assertIsNotNone(self.db.get(ScholarshipChunkEmbedding, embedding.id))
        with self.assertRaises(IntegrityError) as error:
            self.db.execute(
                text("DELETE FROM scholarship_source_documents WHERE id = :id"),
                {"id": document.id},
            )
            self.db.commit()
        self.assertIn("source documents are immutable history", str(error.exception.orig))
        self.db.rollback()
        replacement_embedding = self._embedding(
            chunk, approval, model_revision="after-rejected-identity-change"
        )
        self.db.add(replacement_embedding)
        self.db.commit()

    def test_replacement_source_requires_deactivation_and_preserves_old_history(self):
        previous = self._source_document()
        version = self._version(previous)
        approval = self._approve_indexing(version)
        chunk = self._chunk(version)
        embedding = self._embedding(chunk, approval)
        self.db.add(embedding)
        self.db.commit()

        previous.is_active = False
        self.db.commit()
        replacement = ScholarshipSourceDocument(
            scholarship_id=previous.scholarship_id,
            source_url=previous.source_url,
            normalized_url=previous.normalized_url,
            source_role="additional_official",
        )
        self.db.add(replacement)
        self.db.commit()
        self.assertNotEqual(previous.id, replacement.id)

        self.db.add(self._embedding(
            chunk, approval, model_revision="old-source-after-replacement"
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()
        self.assertIsNotNone(self.db.get(ScholarshipChunkEmbedding, embedding.id))

        replacement_version = self._version(replacement, content_hash="d" * 64)
        replacement_approval = self._approve_indexing(replacement_version)
        replacement_chunk = self._chunk(replacement_version)
        self.db.add(self._embedding(
            replacement_chunk, replacement_approval, model_revision="replacement-source"
        ))
        self.db.commit()

    def test_document_version_hash_is_unique_per_source(self):
        document = self._source_document()
        self._version(document)
        self.db.add(ScholarshipDocumentVersion(
            source_document_id=document.id,
            content_hash="a" * 64,
            retrieved_at=datetime.now(timezone.utc),
            mime_type="text/html",
            extractor_version="test-parser-1",
            extracted_text="A duplicate version.",
            verification_status_snapshot="verified",
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_chunk_ordinal_is_unique_per_version(self):
        version = self._version(self._source_document())
        self._chunk(version)
        self.db.add(ScholarshipDocumentChunk(
            document_version_id=version.id,
            chunk_ordinal=0,
            chunk_text="Duplicate ordinal.",
            chunk_hash="c" * 64,
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_embedding_is_unique_per_chunk_and_model_revision(self):
        version = self._version(self._source_document())
        approval = self._approve_indexing(version)
        chunk = self._chunk(version)
        self.db.add(self._embedding(chunk, approval))
        self.db.commit()
        self.db.add(self._embedding(chunk, approval))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_vector_dimension_and_model_revision_are_stored(self):
        vector_type = ScholarshipChunkEmbedding.__table__.c.embedding.type
        self.assertEqual(vector_type.dim, 384)
        self.assertEqual(EMBEDDING_DIMENSIONS, 384)

        version = self._version(self._source_document())
        approval = self._approve_indexing(version)
        chunk = self._chunk(version)
        embedding = self._embedding(chunk, approval)
        self.db.add(embedding)
        self.db.commit()
        stored = self.db.get(ScholarshipChunkEmbedding, embedding.id)
        self.assertEqual(stored.model_name, "sentence-transformers/all-MiniLM-L6-v2")
        self.assertEqual(stored.model_revision, "test-revision")

    def test_pending_and_failed_indexing_cannot_have_embeddings(self):
        pending = self._version(self._source_document())
        pending_chunk = self._chunk(pending)
        pending_approval = ScholarshipDocumentVersionApproval(
            document_version_id=pending.id,
            decision="revoked",
            verification_status_snapshot=pending.verification_status_snapshot,
            verification_basis_snapshot=pending.verification_basis_snapshot,
            review_status_snapshot=pending.review_status,
            indexing_status_snapshot=pending.indexing_status,
            document_record_version_snapshot=pending.scholarship_record_version_snapshot,
            source_active_at_decision=True,
            scholarship_record_version_at_decision=self.scholarship.record_version,
            scholarship_verification_status_at_decision=self.scholarship.verification_status,
            scholarship_verification_basis_at_decision=self.scholarship.verification_basis,
            scholarship_archived_at_decision=self.scholarship.archived_at,
            actor="test",
        )
        self.db.add(pending_approval)
        self.db.flush()
        self.db.add(self._embedding(pending_chunk, pending_approval))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        failed = self._version(self._source_document())
        approval = self._approve_indexing(failed)
        failed_chunk = self._chunk(failed)
        self.db.add(self._embedding(failed_chunk, approval))
        self.db.flush()
        failed.indexing_status = "failed"
        self.db.commit()
        self.db.add(self._embedding(failed_chunk, approval, model_revision="retry"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_indexing_approval_requires_all_source_and_review_gates(self):
        for index, kwargs in enumerate((
            {"verification_status": "unverified"},
            {"verification_basis": "manual"},
            {"review_status": "pending"},
            {"review_status": "rejected"},
        )):
            with self.subTest(**kwargs):
                version = self._version(
                    self._source_document(str(index)),
                    indexing_status="approved",
                    **kwargs,
                )
                self.db.commit()
                approval = ScholarshipDocumentVersionApproval(
                    document_version_id=version.id,
                    decision="approved",
                    verification_status_snapshot=version.verification_status_snapshot,
                    verification_basis_snapshot=version.verification_basis_snapshot,
                    review_status_snapshot=version.review_status,
                    indexing_status_snapshot=version.indexing_status,
                    document_record_version_snapshot=version.scholarship_record_version_snapshot,
                    source_active_at_decision=True,
                    scholarship_record_version_at_decision=self.scholarship.record_version,
                    scholarship_verification_status_at_decision=self.scholarship.verification_status,
                    scholarship_verification_basis_at_decision=self.scholarship.verification_basis,
                    scholarship_archived_at_decision=self.scholarship.archived_at,
                    actor="test",
                )
                self.db.add(approval)
                with self.assertRaises(IntegrityError):
                    self.db.flush()
                self.db.rollback()

                revoked_approval = ScholarshipDocumentVersionApproval(
                    document_version_id=version.id,
                    decision="revoked",
                    verification_status_snapshot=version.verification_status_snapshot,
                    verification_basis_snapshot=version.verification_basis_snapshot,
                    review_status_snapshot=version.review_status,
                    indexing_status_snapshot=version.indexing_status,
                    document_record_version_snapshot=version.scholarship_record_version_snapshot,
                    source_active_at_decision=True,
                    scholarship_record_version_at_decision=self.scholarship.record_version,
                    scholarship_verification_status_at_decision=self.scholarship.verification_status,
                    scholarship_verification_basis_at_decision=self.scholarship.verification_basis,
                    scholarship_archived_at_decision=self.scholarship.archived_at,
                    actor="test",
                )
                self.db.add(revoked_approval)
                self.db.flush()
                chunk = self._chunk(version)
                self.db.add(self._embedding(chunk, revoked_approval))
                with self.assertRaises(IntegrityError):
                    self.db.commit()
                self.db.rollback()

    def test_stale_and_rejected_versions_preserve_history_and_block_new_embeddings(self):
        version = self._version(self._source_document())
        approval = self._approve_indexing(version)
        chunk = self._chunk(version)
        original_embedding = self._embedding(chunk, approval)
        self.db.add(original_embedding)
        self.db.commit()

        version.review_status = "stale"
        self.db.commit()
        self.assertIsNotNone(self.db.get(ScholarshipChunkEmbedding, original_embedding.id))
        latest_approval = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        self.assertEqual(latest_approval.decision, "revoked")

        stale_chunk = self._chunk(version, ordinal=1)
        self.db.add(self._embedding(stale_chunk, approval, model_revision="stale-retry"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        version = self.db.get(ScholarshipDocumentVersion, version.id)
        version.review_status = "rejected"
        self.db.commit()
        rejected_chunk = self._chunk(version, ordinal=2)
        self.db.add(self._embedding(rejected_chunk, approval, model_revision="rejected-retry"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        self.db.delete(original_embedding)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()
        self.assertIsNotNone(self.db.get(ScholarshipChunkEmbedding, original_embedding.id))

    def test_document_version_source_content_and_history_are_immutable(self):
        version = self._version(self._source_document())
        self.db.commit()
        version_id = version.id
        version.extracted_text = "Changed source content."
        with self.assertRaises(IntegrityError):
            self.db.flush()
        self.db.rollback()

        version = self.db.get(ScholarshipDocumentVersion, version_id)
        self.db.delete(version)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_document_chunks_cannot_be_updated_or_deleted(self):
        version = self._version(self._source_document())
        chunk = self._chunk(version)
        self.db.commit()
        chunk_id = chunk.id
        chunk.chunk_text = "Changed chunk content."
        with self.assertRaises(IntegrityError):
            self.db.flush()
        self.db.rollback()

        chunk = self.db.get(ScholarshipDocumentChunk, chunk_id)
        self.db.delete(chunk)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_document_record_version_snapshot_change_revokes_approval(self):
        version = self._version(self._source_document())
        approval = self._approve_indexing(version)
        chunk = self._chunk(version)
        embedding = self._embedding(chunk, approval)
        self.db.add(embedding)
        self.db.commit()

        version.scholarship_record_version_snapshot = 2
        self.db.commit()

        self.assertIsNotNone(self.db.get(ScholarshipChunkEmbedding, embedding.id))
        latest = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        self.assertEqual(latest.decision, "revoked")
        self.assertEqual(latest.document_record_version_snapshot, 2)

    def test_inactive_source_cannot_be_approved(self):
        document = self._source_document()
        version = self._version(document, indexing_status="approved")
        document.is_active = False
        self.db.commit()

        with self.assertRaises(IntegrityError):
            self._approval_event(version, "approved", source_active=True)
            self.db.commit()
        self.db.rollback()

    def test_inactive_source_cannot_receive_embeddings(self):
        document = self._source_document()
        version = self._version(document)
        approval = self._approve_indexing(version)
        self.db.commit()

        self.db.execute(text("DROP TRIGGER trg_scholarship_source_documents_revoke_approval"))
        document = self.db.get(ScholarshipSourceDocument, document.id)
        document.is_active = False
        self.db.commit()

        chunk = self._chunk(version)
        self.db.add(self._embedding(chunk, approval))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_source_deactivation_revokes_approval_and_preserves_embeddings(self):
        document = self._source_document()
        version = self._version(document)
        approval = self._approve_indexing(version)
        chunk = self._chunk(version)
        embedding = self._embedding(chunk, approval)
        self.db.add(embedding)
        self.db.commit()

        document.is_active = False
        self.db.commit()

        self.assertIsNotNone(self.db.get(ScholarshipChunkEmbedding, embedding.id))
        latest = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        self.assertEqual(latest.decision, "revoked")
        self.assertFalse(latest.source_active_at_decision)
        self.assertEqual(latest.reason, "Scholarship source document deactivated")

    def _assert_scholarship_change_revokes_approval(self, update):
        version = self._version(self._source_document())
        approval = self._approve_indexing(version)
        original_chunk = self._chunk(version)
        embedding = self._embedding(original_chunk, approval)
        self.db.add(embedding)
        self.db.commit()

        update(self.scholarship)
        self.db.commit()
        self.assertIsNotNone(self.db.get(ScholarshipChunkEmbedding, embedding.id))
        latest = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        self.assertEqual(latest.decision, "revoked")
        self.assertEqual(latest.document_record_version_snapshot, 1)
        current_scholarship = self.db.get(Scholarship, self.scholarship.id)
        self.assertEqual(
            latest.scholarship_record_version_at_decision,
            current_scholarship.record_version,
        )
        self.assertEqual(
            latest.scholarship_verification_status_at_decision,
            current_scholarship.verification_status,
        )
        self.assertEqual(
            latest.scholarship_verification_basis_at_decision,
            current_scholarship.verification_basis,
        )
        self.assertEqual(
            latest.scholarship_archived_at_decision,
            current_scholarship.archived_at,
        )

        next_chunk = self._chunk(version, ordinal=1)
        self.db.add(self._embedding(next_chunk, approval, model_revision="after-revocation"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()
        self.assertIsNotNone(self.db.get(ScholarshipChunkEmbedding, embedding.id))

    def test_scholarship_becoming_unverified_revokes_approval(self):
        self._assert_scholarship_change_revokes_approval(
            lambda scholarship: setattr(scholarship, "verification_status", "unverified")
        )

    def test_archiving_scholarship_revokes_approval(self):
        self._assert_scholarship_change_revokes_approval(
            lambda scholarship: setattr(scholarship, "archived_at", datetime.now(timezone.utc))
        )

    def test_scholarship_record_version_change_revokes_approval(self):
        self._assert_scholarship_change_revokes_approval(
            lambda scholarship: setattr(scholarship, "record_version", 2)
        )

    def test_current_scholarship_state_blocks_approval_and_embedding(self):
        invalid_states = (
            {"verification_status": "unverified"},
            {"verification_status": None},
            {"verification_basis": "manual"},
            {"verification_basis": None},
            {"archived_at": datetime.now(timezone.utc)},
            {"record_version": 2},
        )
        for index, invalid_state in enumerate(invalid_states):
            with self.subTest(invalid_state=invalid_state):
                version = self._version(self._source_document(f"-invalid-{index}"))
                self.db.commit()
                for field, value in invalid_state.items():
                    setattr(self.scholarship, field, value)
                self.db.commit()

                version = self.db.get(ScholarshipDocumentVersion, version.id)
                version.indexing_status = "approved"
                self.db.commit()
                with self.assertRaises(IntegrityError):
                    self._approval_event(version, "approved")
                    self.db.commit()
                self.db.rollback()

                version = self.db.get(ScholarshipDocumentVersion, version.id)
                self._approval_event(version, "revoked")
                self.db.commit()
                chunk = self._chunk(version)
                with self.assertRaises(IntegrityError):
                    self.db.add(self._embedding(chunk, self.db.query(
                        ScholarshipDocumentVersionApproval
                    ).filter_by(document_version_id=version.id).order_by(
                        ScholarshipDocumentVersionApproval.id.desc()
                    ).first(), model_revision="invalid-scholarship"))
                    self.db.commit()
                self.db.rollback()

                scholarship = self.db.get(Scholarship, self.scholarship.id)
                scholarship.verification_status = "verified"
                scholarship.verification_basis = "official_source"
                scholarship.archived_at = None
                scholarship.record_version = 1
                self.db.commit()

    def test_embedding_rechecks_current_scholarship_after_approval(self):
        version = self._version(self._source_document())
        approval = self._approve_indexing(version)
        self.db.commit()

        self.db.execute(text("DROP TRIGGER trg_scholarships_revoke_approval"))
        invalid_states = (
            {"verification_status": "unverified"},
            {"verification_basis": "manual"},
            {"archived_at": datetime.now(timezone.utc)},
            {"record_version": 2},
        )
        for index, invalid_state in enumerate(invalid_states):
            scholarship = self.db.get(Scholarship, self.scholarship.id)
            scholarship.verification_status = "verified"
            scholarship.verification_basis = "official_source"
            scholarship.archived_at = None
            scholarship.record_version = 1
            for field, value in invalid_state.items():
                setattr(scholarship, field, value)
            self.db.commit()

            chunk = self._chunk(version, ordinal=index)
            self.db.add(self._embedding(
                chunk,
                approval,
                model_revision=f"current-scholarship-invalid-{index}",
            ))
            with self.assertRaises(IntegrityError):
                self.db.commit()
            self.db.rollback()

    def test_knowledge_source_prevents_hard_deleting_scholarship(self):
        self._source_document()
        admin = User(email="admin@example.test", hashed_password="x", full_name="Admin", role="admin")
        self.db.add(admin)
        self.db.commit()

        counts = reference_counts(self.db, self.scholarship.id)
        self.assertEqual(counts["program_links"], 0)
        self.assertEqual(counts["knowledge_documents"], 1)
        self.assertIn("saved_by_students", counts)
        self.assertEqual(counts["internal_links"], 0)
        with self.assertRaises(HTTPException) as error:
            delete_record(self.db, self.scholarship, admin)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIsNotNone(self.db.get(Scholarship, self.scholarship.id))

    def test_document_history_cannot_be_deleted_while_versions_exist(self):
        document = self._source_document()
        self._version(document)
        self.db.delete(document)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()


def _expected_trigger_rows():
    return [
        (
            name,
            spec["table"],
            "O",
            _expected_trigger_type(spec),
            spec["function"],
            "public",
        )
        for name, spec in schema_check.EXPECTED_TRIGGER_SPECS.items()
    ]


def _expected_trigger_type(spec):
    timing_bit = 2 if spec["timing"] == "BEFORE" else 0
    event_bits = {"INSERT": 4, "DELETE": 8, "UPDATE": 16, "TRUNCATE": 32}
    row_bit = 1 if spec.get("row_level", True) else 0
    return row_bit | timing_bit | sum(event_bits[event] for event in spec["events"])


def _postgres_function_sources():
    sources = {}
    for statement in (
        knowledge_model._APPROVAL_POSTGRES_DDL
        + knowledge_model._EMBEDDING_POSTGRES_DDL
    ):
        match = re.search(
            r"CREATE FUNCTION ([a-zA-Z0-9_]+)\(\) RETURNS trigger\s+"
            r"LANGUAGE plpgsql AS \$\$(.*?)\$\$;",
            statement,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            sources[match.group(1)] = match.group(2).strip()
    return sources


def _expected_function_rows():
    sources = _postgres_function_sources()
    return [
        (name, 0, "trigger", "f", sources[name])
        for name in schema_check.EXPECTED_FUNCTIONS
    ]


class _SchemaResult:
    def __init__(self, rows=(), scalar=None):
        self.rows = rows
        self.scalar = scalar

    def all(self):
        return self.rows

    def one_or_none(self):
        return self.scalar

    def scalar_one_or_none(self):
        return self.scalar


class _SchemaFakeConnection:
    def __init__(self):
        self.dialect = type("Dialect", (), {"name": "postgresql"})()
        self.trigger_rows = _expected_trigger_rows()
        self.function_rows = _expected_function_rows()

    def execute(self, statement, _params=None):
        sql = str(statement)
        if "pg_catalog.pg_trigger" in sql:
            return _SchemaResult(rows=self.trigger_rows)
        if "pg_catalog.pg_proc" in sql:
            return _SchemaResult(rows=self.function_rows)
        if "pg_catalog.pg_extension" in sql:
            return _SchemaResult(scalar=("0.8.7", True))
        if "format_type" in sql:
            return _SchemaResult(scalar="vector(384)")
        if "pg_catalog.pg_indexes" in sql:
            return _SchemaResult(scalar="CREATE INDEX USING hnsw (embedding vector_cosine_ops)")
        raise AssertionError(f"Unexpected readiness query: {sql}")


class _SchemaInspector:
    def __init__(self):
        self.bad_partial_source_index = False

    def get_table_names(self, schema=None):
        return list(SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES)

    def _table(self, table_name):
        return Base.metadata.tables[table_name]

    def get_unique_constraints(self, table_name, schema=None):
        return [
            {"name": constraint.name}
            for constraint in self._table(table_name).constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]

    def get_pk_constraint(self, table_name, schema=None):
        return {"name": self._table(table_name).primary_key.name}

    def get_foreign_keys(self, table_name, schema=None):
        return [
            {
                "name": constraint.name,
                "options": {"ondelete": constraint.ondelete},
            }
            for constraint in self._table(table_name).constraints
            if constraint.__class__.__name__ == "ForeignKeyConstraint"
        ]

    def get_check_constraints(self, table_name, schema=None):
        return [
            {"name": constraint.name}
            for constraint in self._table(table_name).constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        ]

    def get_indexes(self, table_name, schema=None):
        indexes = []
        for index in self._table(table_name).indexes:
            where = index.dialect_options["postgresql"].get("where")
            indexes.append({
                "name": index.name,
                "column_names": [column.name for column in index.columns],
                "unique": index.unique,
                "dialect_options": {
                    "postgresql_where": str(where) if where is not None else None,
                },
            })
        if table_name == "scholarship_source_documents" and self.bad_partial_source_index:
            target = next(
                index for index in indexes
                if index["name"] == "uq_scholarship_source_normalized_url"
            )
            target["unique"] = False
        return indexes


class StartupSchemaTests(unittest.TestCase):
    def test_application_startup_schema_excludes_rag_tables(self):
        engine = _sqlite_engine()
        self.addCleanup(engine.dispose)
        create_application_schema(bind=engine)
        table_names = set(inspect(engine).get_table_names())
        self.assertIn("scholarships", table_names)
        self.assertIn("users", table_names)
        self.assertTrue(SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES.isdisjoint(table_names))

    def test_sqlite_schema_is_not_reported_as_pgvector_ready(self):
        engine = _sqlite_engine()
        self.addCleanup(engine.dispose)
        with engine.connect() as connection:
            self.assertFalse(migration.schema_is_ready(connection))

    def test_postgresql_readiness_rejects_misattached_or_disabled_triggers(self):
        connection = _SchemaFakeConnection()
        with patch.object(schema_check, "inspect", return_value=_SchemaInspector()):
            self.assertTrue(schema_check.schema_is_ready(connection, "public"))

            wrong_table = list(connection.trigger_rows)
            wrong_table[0] = (
                wrong_table[0][0],
                "scholarships",
                *wrong_table[0][2:],
            )
            connection.trigger_rows = wrong_table
            self.assertFalse(schema_check.schema_is_ready(connection, "public"))

            connection.trigger_rows = _expected_trigger_rows()
            wrong_function = list(connection.trigger_rows)
            wrong_function[0] = (
                wrong_function[0][0],
                wrong_function[0][1],
                wrong_function[0][2],
                wrong_function[0][3],
                "scholarship_knowledge_revoke_approval",
                wrong_function[0][5],
            )
            connection.trigger_rows = wrong_function
            self.assertFalse(schema_check.schema_is_ready(connection, "public"))

            connection.trigger_rows = _expected_trigger_rows()
            connection.trigger_rows[0] = (
                connection.trigger_rows[0][0],
                connection.trigger_rows[0][1],
                "D",
                *connection.trigger_rows[0][3:],
            )
            self.assertFalse(schema_check.schema_is_ready(connection, "public"))

    def test_postgresql_readiness_rejects_wrong_trigger_timing_or_events(self):
        connection = _SchemaFakeConnection()
        with patch.object(schema_check, "inspect", return_value=_SchemaInspector()):
            self.assertTrue(schema_check.schema_is_ready(connection, "public"))
            trigger_index = next(
                index for index, row in enumerate(connection.trigger_rows)
                if row[0] == "trg_scholarship_document_versions_revoke_approval"
            )
            row = connection.trigger_rows[trigger_index]
            connection.trigger_rows[trigger_index] = (*row[:3], 7, *row[4:])
            self.assertFalse(schema_check.schema_is_ready(connection, "public"))

    def test_postgresql_trigger_definitions_are_unique(self):
        postgres_ddl = (
            knowledge_model._APPROVAL_POSTGRES_DDL
            + knowledge_model._EMBEDDING_POSTGRES_DDL
        )
        trigger_names = re.findall(
            r"CREATE\s+TRIGGER\s+([a-zA-Z0-9_]+)",
            "\n".join(postgres_ddl),
            flags=re.IGNORECASE,
        )
        self.assertCountEqual(trigger_names, schema_check.EXPECTED_TRIGGER_SPECS)
        self.assertTrue(all(trigger_names.count(name) == 1 for name in trigger_names))

    def test_postgresql_trigger_definitions_match_readiness_metadata(self):
        postgres_ddl = (
            knowledge_model._APPROVAL_POSTGRES_DDL
            + knowledge_model._EMBEDDING_POSTGRES_DDL
        )
        trigger_pattern = re.compile(
            r"CREATE TRIGGER ([a-zA-Z0-9_]+)\s+(BEFORE|AFTER)\s+"
            r"(.*?)\s+ON\s+([a-zA-Z0-9_]+).*?FOR EACH (ROW|STATEMENT)\s+"
            r"EXECUTE FUNCTION ([a-zA-Z0-9_]+)\(\)",
            flags=re.IGNORECASE | re.DOTALL,
        )
        observed = {}
        for statement in postgres_ddl:
            for match in trigger_pattern.finditer(statement):
                name, timing, event_clause, table, granularity, function = match.groups()
                event = re.match(r"(INSERT|UPDATE|DELETE|TRUNCATE)", event_clause, re.IGNORECASE)
                self.assertIsNotNone(event)
                observed[name] = (
                    timing.upper(),
                    frozenset({event.group(1).upper()}),
                    table,
                    function,
                    granularity.upper() == "ROW",
                )

        self.assertEqual(set(observed), set(schema_check.EXPECTED_TRIGGER_SPECS))
        for name, spec in schema_check.EXPECTED_TRIGGER_SPECS.items():
            self.assertEqual(
                observed[name],
                (
                    spec["timing"],
                    spec["events"],
                    spec["table"],
                    spec["function"],
                    spec.get("row_level", True),
                ),
            )

    def test_postgresql_readiness_rejects_non_unique_source_identity_index(self):
        connection = _SchemaFakeConnection()
        inspector = _SchemaInspector()
        inspector.bad_partial_source_index = True
        with patch.object(schema_check, "inspect", return_value=inspector):
            self.assertFalse(schema_check.schema_is_ready(connection, "public"))

    def test_postgresql_integrity_writes_share_a_statement_lock(self):
        approval_ddl = "\n".join(knowledge_model._APPROVAL_POSTGRES_DDL)
        embedding_ddl = "\n".join(knowledge_model._EMBEDDING_POSTGRES_DDL)
        combined = approval_ddl + embedding_ddl
        self.assertIn("pg_advisory_xact_lock(728341901270418)", combined)
        guard_specs = {
            name: spec
            for name, spec in schema_check.EXPECTED_TRIGGER_SPECS.items()
            if spec["function"] == "scholarship_knowledge_serialize_integrity_writes"
        }
        self.assertEqual(
            {spec["table"] for spec in guard_specs.values()},
            {
                "scholarship_document_version_approvals",
                "scholarship_document_versions",
                "scholarship_source_documents",
                "scholarships",
                "scholarship_chunk_embeddings",
            },
        )
        self.assertTrue(all(spec["timing"] == "BEFORE" for spec in guard_specs.values()))
        self.assertTrue(all(spec["row_level"] is False for spec in guard_specs.values()))

    def test_postgresql_truncate_guards_cover_history_tables(self):
        expected_tables = {
            "scholarship_source_documents",
            "scholarship_document_versions",
            "scholarship_document_chunks",
            "scholarship_document_version_approvals",
            "scholarship_chunk_embeddings",
        }
        truncate_specs = {
            spec["table"]
            for spec in schema_check.EXPECTED_TRIGGER_SPECS.values()
            if spec["events"] == frozenset({"TRUNCATE"})
        }
        self.assertEqual(truncate_specs, expected_tables)
        postgres_ddl = "\n".join(
            knowledge_model._APPROVAL_POSTGRES_DDL
            + knowledge_model._EMBEDDING_POSTGRES_DDL
        )
        for table_name in expected_tables:
            self.assertRegex(
                postgres_ddl,
                rf"BEFORE TRUNCATE ON {table_name}\s+FOR EACH STATEMENT",
            )

    def test_chunk_truncate_trigger_runs_after_chunk_table_creation(self):
        approval_ddl = "\n".join(knowledge_model._APPROVAL_POSTGRES_DDL)
        embedding_ddl = "\n".join(knowledge_model._EMBEDDING_POSTGRES_DDL)
        trigger = "CREATE TRIGGER trg_scholarship_document_chunks_reject_truncate"

        self.assertIn("CREATE FUNCTION scholarship_knowledge_reject_history_truncate()", approval_ddl)
        self.assertNotIn(trigger, approval_ddl)
        self.assertIn(trigger, embedding_ddl)

        table_names = [table.name for table in SCHOLARSHIP_KNOWLEDGE_TABLES]
        self.assertLess(
            table_names.index("scholarship_document_chunks"),
            table_names.index("scholarship_chunk_embeddings"),
        )
        self.assertLess(
            table_names.index("scholarship_document_version_approvals"),
            table_names.index("scholarship_chunk_embeddings"),
        )
        embedding_foreign_tables = {
            element.column.table.name
            for constraint in ScholarshipChunkEmbedding.__table__.foreign_key_constraints
            for element in constraint.elements
        }
        self.assertIn("scholarship_document_chunks", embedding_foreign_tables)
        self.assertIn("scholarship_document_version_approvals", embedding_foreign_tables)

    def test_postgresql_ddl_groups_wait_for_trigger_tables_and_functions(self):
        groups = (
            (
                knowledge_model._APPROVAL_POSTGRES_DDL,
                ScholarshipDocumentVersionApproval.__table__,
            ),
            (
                knowledge_model._EMBEDDING_POSTGRES_DDL,
                ScholarshipChunkEmbedding.__table__,
            ),
        )
        available_functions = set()

        def dependency_tables(table, found=None):
            found = set() if found is None else found
            for foreign_key in table.foreign_keys:
                target = foreign_key.column.table
                if target.name not in found:
                    found.add(target.name)
                    dependency_tables(target, found)
            return found

        for statements, listener_table in groups:
            available_tables = dependency_tables(listener_table) | {listener_table.name}
            for statement in statements:
                function = re.search(
                    r"CREATE FUNCTION\s+([a-zA-Z0-9_]+)\(",
                    statement,
                    re.IGNORECASE,
                )
                if function:
                    available_functions.add(function.group(1))

                trigger = re.search(
                    r"CREATE TRIGGER\s+\w+.*?\sON\s+([a-zA-Z0-9_]+).*?"
                    r"EXECUTE FUNCTION\s+([a-zA-Z0-9_]+)\(",
                    statement,
                    re.IGNORECASE | re.DOTALL,
                )
                if trigger:
                    target_table, function_name = trigger.groups()
                    self.assertIn(target_table, available_tables | {"scholarships"})
                    self.assertIn(function_name, available_functions)

    def test_postgresql_readiness_rejects_altered_function_body_or_signature(self):
        connection = _SchemaFakeConnection()
        with patch.object(schema_check, "inspect", return_value=_SchemaInspector()):
            self.assertTrue(schema_check.schema_is_ready(connection, "public"))
            index = next(
                index for index, row in enumerate(connection.function_rows)
                if row[0] == "scholarship_knowledge_validate_embedding"
            )
            row = connection.function_rows[index]
            connection.function_rows[index] = (*row[:4], "BEGIN RETURN NEW; END;")
            self.assertFalse(schema_check.schema_is_ready(connection, "public"))

            connection.function_rows = _expected_function_rows()
            row = connection.function_rows[index]
            connection.function_rows[index] = (row[0], 1, *row[2:])
            self.assertFalse(schema_check.schema_is_ready(connection, "public"))

            connection.function_rows = _expected_function_rows()
            row = connection.function_rows[index]
            connection.function_rows[index] = (row[0], row[1], "void", *row[3:])
            self.assertFalse(schema_check.schema_is_ready(connection, "public"))

    def test_postgresql_readiness_requires_expected_functions_in_target_schema(self):
        connection = _SchemaFakeConnection()
        connection.function_rows = [
            row for row in connection.function_rows
            if row[0] != "scholarship_knowledge_validate_embedding"
        ]
        with patch.object(schema_check, "inspect", return_value=_SchemaInspector()):
            self.assertFalse(schema_check.schema_is_ready(connection, "public"))


class _FakeResult:
    def __init__(self, row):
        self.row = row

    def one(self):
        if self.row is None:
            raise AssertionError("Expected a query result")
        return self.row

    def one_or_none(self):
        return self.row


class _FakeConnection:
    def __init__(self, database="fitscholar_db", schema="public", extension=("0.8.7", True), version_num=170011):
        self.dialect = type("Dialect", (), {"name": "postgresql"})()
        self.engine = type("Engine", (), {"url": type("URL", (), {"database": database})()})()
        self.database = database
        self.schema = schema
        self.extension = extension
        self.version_num = version_num
        self.statements = []

    def execute(self, statement, _params=None):
        sql = str(statement)
        self.statements.append(sql)
        if "current_database()" in sql:
            return _FakeResult((self.database, self.schema, self.version_num))
        if "pg_catalog.pg_extension" in sql:
            return _FakeResult(self.extension)
        raise AssertionError(f"Unexpected preflight query: {sql}")


class _FakeEngine:
    def __init__(self, database="fitscholar_db", connection=None):
        self.url = type("URL", (), {"database": database})()
        self.connection = connection or _FakeConnection(database=database)
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        raise AssertionError("This test must not open a database connection")


class _FakeCheckEngine(_FakeEngine):
    @contextlib.contextmanager
    def connect(self):
        self.connect_calls += 1
        yield self.connection


class MigrationPreflightTests(unittest.TestCase):
    def test_preflight_accepts_explicit_postgresql_and_pgvector_target(self):
        connection = _FakeConnection()
        details = migration.preflight_connection(connection, "fitscholar_db", "public")
        self.assertEqual(details["postgres_major"], 17)
        self.assertEqual(details["pgvector_version"], "0.8.7")
        self.assertEqual(details["dimensions"], 384)

    def test_preflight_refuses_missing_pgvector(self):
        connection = _FakeConnection(extension=None)
        with self.assertRaisesRegex(migration.MigrationRefused, "not enabled"):
            migration.preflight_connection(connection, "fitscholar_db", "public")

    def test_preflight_refuses_incompatible_pgvector_version(self):
        connection = _FakeConnection(extension=("0.8.6", True))
        with self.assertRaisesRegex(migration.MigrationRefused, "0.8.7"):
            migration.preflight_connection(connection, "fitscholar_db", "public")

    def test_preflight_refuses_incompatible_vector_dimensions(self):
        connection = _FakeConnection()
        with patch.object(migration, "EMBEDDING_DIMENSIONS", 256):
            with self.assertRaisesRegex(migration.MigrationRefused, "384 dimensions"):
                migration.preflight_connection(connection, "fitscholar_db", "public")
        self.assertEqual(connection.statements, [])

    def test_preflight_never_creates_the_extension(self):
        connection = _FakeConnection()
        migration.preflight_connection(connection, "fitscholar_db", "public")
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in connection.statements))
        self.assertFalse(any("CREATE EXTENSION" in statement.upper() for statement in connection.statements))

    def test_preflight_refuses_unsafe_database_or_schema(self):
        with self.assertRaisesRegex(migration.MigrationRefused, "does not match DATABASE_URL"):
            migration.validate_configured_target(_FakeEngine(), "another_database")
        with self.assertRaisesRegex(migration.MigrationRefused, "does not match the explicit target"):
            migration.preflight_connection(_FakeConnection(schema="other"), "fitscholar_db", "public")

    def test_default_migration_mode_does_not_connect(self):
        engine = _FakeEngine()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = migration.main([], target_engine=engine)
        self.assertEqual(result, 0)
        self.assertEqual(engine.connect_calls, 0)
        self.assertIn("No database connection opened", output.getvalue())

    def test_check_reports_absent_and_valid_schemas_distinctly(self):
        full_schema = set(SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES)
        for existing, ready, expected_message in (
            (set(), False, "schema is absent"),
            (full_schema, True, "schema is installed and ready"),
        ):
            with self.subTest(expected_message=expected_message):
                engine = _FakeCheckEngine()
                output = io.StringIO()
                with patch.object(
                    migration, "preflight_connection", return_value={"schema": "public"}
                ):
                    with patch.object(migration, "_existing_rag_tables", return_value=existing):
                        with patch.object(migration, "schema_is_ready", return_value=ready):
                            with contextlib.redirect_stdout(output):
                                result = migration.main(
                                    ["--check", "--database", "fitscholar_db", "--schema", "public"],
                                    target_engine=engine,
                                )
                self.assertEqual(result, 0)
                self.assertIn(expected_message, output.getvalue())

    def test_check_fails_for_partial_or_incompatible_schemas(self):
        cases = (
            ({"scholarship_source_documents"}, False, "partial"),
            (set(SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES), False, "incompatible or incomplete"),
        )
        for existing, ready, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                engine = _FakeCheckEngine()
                output = io.StringIO()
                with patch.object(
                    migration, "preflight_connection", return_value={"schema": "public"}
                ):
                    with patch.object(migration, "_existing_rag_tables", return_value=existing):
                        with patch.object(migration, "schema_is_ready", return_value=ready):
                            with contextlib.redirect_stdout(output):
                                with self.assertRaises(SystemExit) as error:
                                    migration.main(
                                        ["--check", "--database", "fitscholar_db", "--schema", "public"],
                                        target_engine=engine,
                                    )
                self.assertTrue(error.exception.code)
                self.assertIn(expected_message, str(error.exception.code))
                self.assertNotIn("--apply", str(error.exception.code))

    def test_apply_requires_explicit_mode_and_targets(self):
        engine = _FakeEngine()
        with patch.object(migration, "apply_migration", return_value=False) as apply:
            result = migration.main(
                ["--apply", "--database", "fitscholar_db", "--schema", "public"],
                target_engine=engine,
            )
        self.assertEqual(result, 0)
        apply.assert_called_once_with(engine, "fitscholar_db", "public")

    def test_apply_only_passes_new_knowledge_tables_to_create_all(self):
        connection = _FakeConnection()

        class FakeTransactionEngine(_FakeEngine):
            @contextlib.contextmanager
            def begin(self):
                yield connection

        engine = FakeTransactionEngine(connection=connection)
        inspector = type("Inspector", (), {"get_table_names": lambda _self, schema: []})()
        with patch.object(migration, "inspect", return_value=inspector):
            with patch.object(migration, "schema_is_ready", return_value=True):
                with patch.object(Base.metadata, "create_all") as create_all:
                    already_ready = migration.apply_migration(engine, "fitscholar_db", "public")

        self.assertFalse(already_ready)
        created_tables = create_all.call_args.kwargs["tables"]
        self.assertEqual(set(created_tables), set(SCHOLARSHIP_KNOWLEDGE_TABLES))
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in connection.statements))


if __name__ == "__main__":
    unittest.main()
