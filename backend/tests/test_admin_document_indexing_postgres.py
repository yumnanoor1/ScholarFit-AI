import hashlib
import math
import os
import unittest
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timezone
from threading import Barrier, Event
import time
from uuid import uuid4
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.database import Base, DATABASE_URL
from app.models.opportunity import Scholarship, ScholarshipAuditLog, University
from app.models.scholarship_knowledge import (
    EMBEDDING_DIMENSIONS,
    SCHOLARSHIP_KNOWLEDGE_TABLES,
    ScholarshipChunkEmbedding,
    ScholarshipDocumentChunk,
    ScholarshipDocumentVersion,
    ScholarshipDocumentVersionApproval,
    ScholarshipSourceDocument,
)
from app.models.user import User
from app.routers import admin_scholarships as admin_api
from app.services.scholarship_document_indexing import DocumentChunk

POSTGRES_TEST_URL = os.getenv("SCHOLARSHIP_INDEXING_POSTGRES_TEST_URL")
MODEL_REVISION = "0123456789abcdef0123456789abcdef01234567"
LOCK_ID = 728341901270418
VECTOR = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


def _database_identity(url_value):
    url = make_url(url_value)
    if url.query.get("service") or url.query.get("dsn") or not url.database:
        return None
    backend = url.get_backend_name().lower()
    host = url.query.get("host") or url.host or ""
    hostaddr = url.query.get("hostaddr") or ""
    if isinstance(host, (tuple, list)):
        host = host[0] if host else ""
    if isinstance(hostaddr, (tuple, list)):
        hostaddr = hostaddr[0] if hostaddr else ""
    host = str(host).strip().lower()
    if host in {"", "localhost", "127.0.0.1", "::1"}:
        host = "<local>"
    hostaddr = str(hostaddr).strip().lower()
    port = url.query.get("port") or url.port
    if isinstance(port, (tuple, list)):
        port = port[0] if port else None
    if port is None and backend == "postgresql":
        port = 5432
    return backend, host, hostaddr, str(port or ""), url.database


class DatabaseIdentityTests(unittest.TestCase):
    def test_identity_ignores_driver_credentials_and_localhost_alias(self):
        first = _database_identity("postgresql+psycopg://user_a@localhost:5432/scholarships")
        second = _database_identity("postgresql://user_b@127.0.0.1/scholarships")

        self.assertEqual(first, second)

    def test_identity_distinguishes_database_names(self):
        first = _database_identity("postgresql://user@localhost/scholarships")
        second = _database_identity("postgresql://user@localhost/application")

        self.assertNotEqual(first, second)


@unittest.skipUnless(POSTGRES_TEST_URL, "set SCHOLARSHIP_INDEXING_POSTGRES_TEST_URL to a disposable PostgreSQL database")
class PostgresDocumentIndexingIntegrationTests(unittest.TestCase):
    """Uses an isolated temporary schema to exercise PostgreSQL locks, triggers and pgvector writes."""

    def setUp(self):
        try:
            test_identity = _database_identity(POSTGRES_TEST_URL)
            application_identity = _database_identity(DATABASE_URL)
        except (ArgumentError, TypeError, ValueError):
            self.fail("PostgreSQL test and application database identities cannot be safely compared")
        if test_identity is None or application_identity is None:
            self.fail("PostgreSQL test and application database identities cannot be safely compared")
        if test_identity[-1] != "fitscholar_phase3b_test":
            self.fail("SCHOLARSHIP_INDEXING_POSTGRES_TEST_URL must identify fitscholar_phase3b_test")
        if test_identity == application_identity:
            self.fail("SCHOLARSHIP_INDEXING_POSTGRES_TEST_URL must identify a different database")

        self.admin_engine = create_engine(POSTGRES_TEST_URL)
        self.addCleanup(self.admin_engine.dispose)
        if self.admin_engine.dialect.name != "postgresql":
            self.skipTest("SCHOLARSHIP_INDEXING_POSTGRES_TEST_URL must use PostgreSQL")
        with self.admin_engine.connect() as connection:
            has_vector = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            ).scalar_one()
        if not has_vector:
            self.skipTest("PostgreSQL test database must already have pgvector installed")

        self.schema = f"scholarship_indexing_test_{uuid4().hex}"
        with self.admin_engine.begin() as connection:
            connection.execute(CreateSchema(self.schema))
        self.addCleanup(self._drop_test_schema)

        self.engine = create_engine(
            POSTGRES_TEST_URL,
            connect_args={"options": f"-csearch_path={self.schema},public"},
        )
        self.addCleanup(self.engine.dispose)
        required_tables = [
            University.__table__,
            User.__table__,
            Scholarship.__table__,
            ScholarshipAuditLog.__table__,
            *SCHOLARSHIP_KNOWLEDGE_TABLES,
        ]
        Base.metadata.create_all(bind=self.engine, tables=required_tables)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        with self.Session() as db:
            self.admin = User(
                email=f"index-admin-{uuid4().hex}@example.test",
                hashed_password="not-used",
                full_name="Index Admin",
                role="admin",
            )
            scholarship = Scholarship(
                country="Finland",
                name=f"Indexing Integration {uuid4().hex}",
                official_url="https://official.example/scholarship",
                official_info_url="https://official.example/scholarship",
                verification_status="verified",
                verification_basis="official_source",
                last_verified_date=date.today(),
                source_checks=[{
                    "url": "https://official.example/scholarship",
                    "status": "ok",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }],
                data_flags=[],
                record_version=1,
            )
            db.add_all([self.admin, scholarship])
            db.flush()
            self.scholarship_id = scholarship.id
            source = ScholarshipSourceDocument(
                scholarship_id=scholarship.id,
                source_url="https://official.example/scholarship",
                normalized_url="https://official.example/scholarship",
                source_role="official_information",
            )
            db.add(source)
            db.flush()
            self.source_id = source.id
            version = ScholarshipDocumentVersion(
                source_document_id=source.id,
                content_hash="a" * 64,
                retrieved_at=datetime.now(timezone.utc),
                mime_type="text/html",
                extractor_version="integration-test",
                extracted_text="A fully funded scholarship for tuition and living costs.",
                verification_status_snapshot=scholarship.verification_status,
                verification_basis_snapshot=scholarship.verification_basis,
                last_verified_date_snapshot=scholarship.last_verified_date,
                scholarship_record_version_snapshot=scholarship.record_version,
                review_status="approved",
                indexing_status="approved",
            )
            db.add(version)
            db.flush()
            self.version_id = version.id
            db.add(ScholarshipDocumentVersionApproval(
                document_version_id=version.id,
                decision="approved",
                verification_status_snapshot=version.verification_status_snapshot,
                verification_basis_snapshot=version.verification_basis_snapshot,
                review_status_snapshot=version.review_status,
                indexing_status_snapshot=version.indexing_status,
                document_record_version_snapshot=version.scholarship_record_version_snapshot,
                source_active_at_decision=source.is_active,
                scholarship_record_version_at_decision=scholarship.record_version,
                scholarship_verification_status_at_decision=scholarship.verification_status,
                scholarship_verification_basis_at_decision=scholarship.verification_basis,
                scholarship_archived_at_decision=scholarship.archived_at,
                actor=self.admin.email,
                reason="Integration fixture approval.",
            ))
            db.commit()
            self.content_hash = version.content_hash
            self.record_version = scholarship.record_version

        self.app = FastAPI()
        self.app.include_router(admin_api.router)
        self.app.dependency_overrides[admin_api.require_admin] = lambda: self.admin
        self.app.dependency_overrides[admin_api.get_db] = self._get_db

    def _drop_test_schema(self):
        if not self.schema.startswith("scholarship_indexing_test_"):
            raise RuntimeError("Refusing to drop an unexpected PostgreSQL test schema")
        with self.admin_engine.begin() as connection:
            connection.execute(DropSchema(self.schema, cascade=True))

    def _get_db(self):
        db = self.Session()
        try:
            yield db
        finally:
            db.close()

    def _chunk(self, text_value):
        return [
            DocumentChunk(
                ordinal=0,
                chunk_text=text_value,
                chunk_hash=hashlib.sha256(text_value.encode("utf-8")).hexdigest(),
                start_offset=0,
                end_offset=len(text_value),
            )
        ]

    @contextmanager
    def _mock_indexing(self, *, chunker=None, embedding=VECTOR):
        with patch.object(admin_api.rag_service, "get_model_revision", return_value=MODEL_REVISION), \
                patch.object(
                    admin_api.document_indexing,
                    "chunk_document_text",
                    side_effect=lambda text_value, *, model_revision: (
                        (chunker or self._chunk)(text_value)
                    ),
                ), \
                patch.object(
                    admin_api.document_indexing,
                    "generate_document_embeddings",
                    side_effect=lambda chunks, *, model_revision: [list(embedding) for _ in chunks],
                ):
            yield

    def _post_index(self):
        body = {
            "expected_content_hash": self.content_hash,
            "expected_scholarship_record_version": self.record_version,
        }
        with TestClient(self.app, raise_server_exceptions=False) as client:
            return client.post(
                f"/admin/scholarships/{self.scholarship_id}/documents/{self.version_id}/index",
                json=body,
            )

    def test_embedding_persistence_failure_rolls_back_indexing_transaction(self):
        with self.Session() as db:
            version = db.get(ScholarshipDocumentVersion, self.version_id)
            self.assertEqual(version.indexing_status, "approved")
            self.assertEqual(
                db.query(ScholarshipDocumentChunk).filter_by(document_version_id=self.version_id).count(),
                0,
            )
            self.assertEqual(
                db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=self.version_id).count(),
                0,
            )
            self.assertEqual(
                db.query(ScholarshipAuditLog)
                .filter_by(scholarship_id=self.scholarship_id, action="document_indexed")
                .count(),
                0,
            )

        observed = {"chunks_persisted": False, "embedding_failure_injected": False}
        chunk_table = ScholarshipDocumentChunk.__tablename__.lower()
        embedding_table = ScholarshipChunkEmbedding.__tablename__.lower()

        def inject_embedding_failure(connection, cursor, statement, parameters, context, executemany):
            normalized_statement = statement.lstrip().lower()
            if normalized_statement.startswith("insert") and chunk_table in normalized_statement:
                observed["chunks_persisted"] = True
            elif normalized_statement.startswith("insert") and embedding_table in normalized_statement:
                if not observed["chunks_persisted"]:
                    raise AssertionError("Embedding persistence began before chunk persistence")
                observed["embedding_failure_injected"] = True
                raise RuntimeError("controlled embedding persistence failure")

        event.listen(self.engine, "after_cursor_execute", inject_embedding_failure)
        try:
            with self._mock_indexing():
                response = self._post_index()
        finally:
            event.remove(self.engine, "after_cursor_execute", inject_embedding_failure)

        self.assertTrue(observed["chunks_persisted"], "Document chunk INSERT was not observed")
        self.assertTrue(observed["embedding_failure_injected"], "Embedding INSERT failure was not injected")
        self.assertEqual(response.status_code, 500, response.text)

        with self.Session() as db:
            version = db.get(ScholarshipDocumentVersion, self.version_id)
            self.assertEqual(version.indexing_status, "approved")
            self.assertEqual(
                db.query(ScholarshipDocumentChunk).filter_by(document_version_id=self.version_id).count(),
                0,
            )
            self.assertEqual(
                db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=self.version_id).count(),
                0,
            )
            self.assertEqual(
                db.query(ScholarshipAuditLog)
                .filter_by(scholarship_id=self.scholarship_id, action="document_indexed")
                .count(),
                0,
            )

    def test_reindexing_is_idempotent_without_mutating_persisted_records(self):
        def persisted_index_state():
            with self.Session() as db:
                version = db.get(ScholarshipDocumentVersion, self.version_id)
                chunks = (
                    db.query(ScholarshipDocumentChunk)
                    .filter_by(document_version_id=self.version_id)
                    .order_by(ScholarshipDocumentChunk.chunk_ordinal)
                    .all()
                )
                embeddings = (
                    db.query(ScholarshipChunkEmbedding)
                    .filter_by(document_version_id=self.version_id)
                    .order_by(ScholarshipChunkEmbedding.id)
                    .all()
                )
                audit_rows = (
                    db.query(ScholarshipAuditLog)
                    .filter_by(scholarship_id=self.scholarship_id, action="document_indexed")
                    .order_by(ScholarshipAuditLog.id)
                    .all()
                )
                return {
                    "indexing_status": version.indexing_status,
                    "chunks": [
                        (
                            row.id,
                            row.chunk_ordinal,
                            row.chunk_text,
                            row.chunk_hash,
                            row.start_offset,
                            row.end_offset,
                        )
                        for row in chunks
                    ],
                    "embeddings": [
                        (
                            row.id,
                            row.chunk_id,
                            row.approval_id,
                            tuple(row.embedding),
                            row.model_name,
                            row.model_revision,
                            row.dimensions,
                        )
                        for row in embeddings
                    ],
                    "audit_records": [
                        (
                            row.id,
                            row.action,
                            row.changes,
                            row.note,
                            row.actor_id,
                            row.actor_email,
                            row.created_at,
                        )
                        for row in audit_rows
                    ],
                }

        with self._mock_indexing():
            first_response = self._post_index()

        self.assertEqual(first_response.status_code, 200, first_response.text)
        first_result = first_response.json()
        self.assertFalse(first_result["idempotent"])
        self.assertEqual(first_result["chunks_created"], 1)
        self.assertEqual(first_result["embeddings_created"], 1)
        first_state = persisted_index_state()
        self.assertEqual(first_state["indexing_status"], "indexed")
        self.assertEqual(len(first_state["chunks"]), first_result["chunk_count"])
        self.assertEqual(len({row[0] for row in first_state["chunks"]}), len(first_state["chunks"]))
        self.assertEqual(len(first_state["embeddings"]), first_result["embedding_count"])
        self.assertEqual(len({row[0] for row in first_state["embeddings"]}), len(first_state["embeddings"]))
        self.assertEqual(len(first_state["audit_records"]), 1)

        with self._mock_indexing():
            second_response = self._post_index()

        self.assertEqual(second_response.status_code, 200, second_response.text)
        second_result = second_response.json()
        self.assertTrue(second_result["idempotent"])
        self.assertEqual(second_result["chunks_created"], 0)
        self.assertEqual(second_result["embeddings_created"], 0)
        second_state = persisted_index_state()
        self.assertEqual(second_state, first_state)
        self.assertEqual(second_state["indexing_status"], "indexed")
        self.assertEqual(len(second_state["audit_records"]), 1)

    def test_rag_excludes_historical_version_before_ranking_and_context(self):
        historical_version_id = self.version_id
        with self.Session() as db:
            historical_text = db.get(ScholarshipDocumentVersion, historical_version_id).extracted_text

        with self._mock_indexing(embedding=VECTOR):
            historical_response = self._post_index()
        self.assertEqual(historical_response.status_code, 200, historical_response.text)

        def persisted_version_state(version_id):
            with self.Session() as db:
                version = db.get(ScholarshipDocumentVersion, version_id)
                chunks = (
                    db.query(ScholarshipDocumentChunk)
                    .filter_by(document_version_id=version_id)
                    .order_by(ScholarshipDocumentChunk.chunk_ordinal)
                    .all()
                )
                embeddings = (
                    db.query(ScholarshipChunkEmbedding)
                    .filter_by(document_version_id=version_id)
                    .order_by(ScholarshipChunkEmbedding.id)
                    .all()
                )
                return (
                    version.indexing_status,
                    tuple(
                        (
                            row.id,
                            row.chunk_ordinal,
                            row.chunk_text,
                            row.chunk_hash,
                            row.start_offset,
                            row.end_offset,
                        )
                        for row in chunks
                    ),
                    tuple(
                        (
                            row.id,
                            row.chunk_id,
                            row.approval_id,
                            tuple(row.embedding),
                            row.model_name,
                            row.model_revision,
                            row.dimensions,
                        )
                        for row in embeddings
                    ),
                )

        historical_state = persisted_version_state(historical_version_id)
        self.assertEqual(historical_state[0], "indexed")
        self.assertEqual(len(historical_state[1]), 1)
        self.assertEqual(len(historical_state[2]), 1)
        self.assertEqual(historical_state[2][0][3], tuple(VECTOR))

        current_text = "CURRENT VERSION: current tuition and stipend terms."
        current_content_hash = "b" * 64
        with self.Session() as db:
            scholarship = db.get(Scholarship, self.scholarship_id)
            source = db.get(ScholarshipSourceDocument, self.source_id)
            current_version = ScholarshipDocumentVersion(
                source_document_id=source.id,
                content_hash=current_content_hash,
                retrieved_at=datetime.now(timezone.utc),
                mime_type="text/html",
                extractor_version="integration-test",
                extracted_text=current_text,
                verification_status_snapshot=scholarship.verification_status,
                verification_basis_snapshot=scholarship.verification_basis,
                last_verified_date_snapshot=scholarship.last_verified_date,
                scholarship_record_version_snapshot=scholarship.record_version,
                review_status="approved",
                indexing_status="approved",
            )
            db.add(current_version)
            db.flush()
            db.add(ScholarshipDocumentVersionApproval(
                document_version_id=current_version.id,
                decision="approved",
                verification_status_snapshot=current_version.verification_status_snapshot,
                verification_basis_snapshot=current_version.verification_basis_snapshot,
                review_status_snapshot=current_version.review_status,
                indexing_status_snapshot=current_version.indexing_status,
                document_record_version_snapshot=current_version.scholarship_record_version_snapshot,
                source_active_at_decision=source.is_active,
                scholarship_record_version_at_decision=scholarship.record_version,
                scholarship_verification_status_at_decision=scholarship.verification_status,
                scholarship_verification_basis_at_decision=scholarship.verification_basis,
                scholarship_archived_at_decision=scholarship.archived_at,
                actor=self.admin.email,
                reason="Current-version RAG integration fixture approval.",
            ))
            db.commit()
            current_version_id = current_version.id
            current_record_version = scholarship.record_version

        self.assertGreater(current_version_id, historical_version_id)
        current_vector = [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
        self.version_id = current_version_id
        self.content_hash = current_content_hash
        self.record_version = current_record_version
        with self._mock_indexing(embedding=current_vector):
            current_response = self._post_index()
        self.assertEqual(current_response.status_code, 200, current_response.text)
        current_state = persisted_version_state(current_version_id)
        self.assertEqual(current_state[0], "indexed")
        self.assertEqual(current_state[2][0][3], tuple(current_vector))
        self.assertEqual(persisted_version_state(historical_version_id), historical_state)

        with self.Session() as db, \
                patch.object(admin_api.rag_service, "get_model_revision", return_value=MODEL_REVISION), \
                patch.object(admin_api.rag_service, "embed_query", return_value=VECTOR), \
                patch.object(admin_api.rag_service, "_generate", return_value="Current-version answer") as generate:
            result = admin_api.rag_service.retrieve(
                db,
                "query favoring the historical embedding",
                scholarship_id=self.scholarship_id,
                top_k=1,
            )
            self.assertEqual(result.status, admin_api.rag_service.STATUS_OK)
            self.assertEqual([chunk.text for chunk in result.chunks], [current_text])
            self.assertLess(result.chunks[0].score, 0.01)

            answer = admin_api.rag_service.answer_question(
                db,
                "query favoring the historical embedding",
                scholarship_id=self.scholarship_id,
            )
            self.assertEqual(answer.status, admin_api.rag_service.STATUS_OK)
            self.assertEqual([chunk.text for chunk in answer.chunks], [current_text])
            source_block = admin_api.rag_service._source_block(generate.call_args.args[1])
            self.assertIn(current_text, source_block)
            self.assertNotIn(historical_text, source_block)

        self.assertEqual(persisted_version_state(historical_version_id), historical_state)

    def test_rag_retrieval_isolated_between_scholarships_before_ranking_and_context(self):
        scholarship_a_id = self.scholarship_id
        scholarship_a_version_id = self.version_id
        scholarship_a_text = "A fully funded scholarship for tuition and living costs."
        scholarship_b_text = "Scholarship B exclusive living stipend details."
        vector_a = [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
        vector_b = VECTOR
        self.assertNotEqual(vector_a, vector_b)
        self.assertTrue(math.isclose(math.hypot(*vector_a), 1.0, rel_tol=1e-12, abs_tol=1e-12))
        self.assertTrue(math.isclose(math.hypot(*vector_b), 1.0, rel_tol=1e-12, abs_tol=1e-12))

        with self._mock_indexing(embedding=vector_a):
            response_a = self._post_index()
        self.assertEqual(response_a.status_code, 200, response_a.text)

        with self.Session() as db:
            scholarship_b = Scholarship(
                country="Finland",
                name=f"Isolation Integration {uuid4().hex}",
                official_url=f"https://official.example/isolation/{uuid4().hex}",
                verification_status="verified",
                verification_basis="official_source",
                last_verified_date=date.today(),
                source_checks=[],
                data_flags=[],
                record_version=1,
            )
            scholarship_b.official_info_url = scholarship_b.official_url
            db.add(scholarship_b)
            db.flush()
            source_b = ScholarshipSourceDocument(
                scholarship_id=scholarship_b.id,
                source_url=f"{scholarship_b.official_url}/document",
                normalized_url=f"{scholarship_b.official_url}/document",
                source_role="official_information",
            )
            db.add(source_b)
            db.flush()
            scholarship_b.source_checks = [{
                "url": source_b.source_url,
                "status": "ok",
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }]
            version_b = ScholarshipDocumentVersion(
                source_document_id=source_b.id,
                content_hash="b" * 64,
                retrieved_at=datetime.now(timezone.utc),
                mime_type="text/html",
                extractor_version="integration-test",
                extracted_text=scholarship_b_text,
                verification_status_snapshot=scholarship_b.verification_status,
                verification_basis_snapshot=scholarship_b.verification_basis,
                last_verified_date_snapshot=scholarship_b.last_verified_date,
                scholarship_record_version_snapshot=scholarship_b.record_version,
                review_status="approved",
                indexing_status="approved",
            )
            db.add(version_b)
            db.flush()
            db.add(ScholarshipDocumentVersionApproval(
                document_version_id=version_b.id,
                decision="approved",
                verification_status_snapshot=version_b.verification_status_snapshot,
                verification_basis_snapshot=version_b.verification_basis_snapshot,
                review_status_snapshot=version_b.review_status,
                indexing_status_snapshot=version_b.indexing_status,
                document_record_version_snapshot=version_b.scholarship_record_version_snapshot,
                source_active_at_decision=source_b.is_active,
                scholarship_record_version_at_decision=scholarship_b.record_version,
                scholarship_verification_status_at_decision=scholarship_b.verification_status,
                scholarship_verification_basis_at_decision=scholarship_b.verification_basis,
                scholarship_archived_at_decision=scholarship_b.archived_at,
                actor=self.admin.email,
                reason="Scholarship isolation integration fixture approval.",
            ))
            db.commit()
            scholarship_b_id = scholarship_b.id
            scholarship_b_version_id = version_b.id
            scholarship_b_content_hash = version_b.content_hash
            scholarship_b_record_version = scholarship_b.record_version

        def post_index(scholarship_id, version_id, content_hash, record_version):
            body = {
                "expected_content_hash": content_hash,
                "expected_scholarship_record_version": record_version,
            }
            with TestClient(self.app, raise_server_exceptions=False) as client:
                return client.post(
                    f"/admin/scholarships/{scholarship_id}/documents/{version_id}/index",
                    json=body,
                )

        with self._mock_indexing(embedding=vector_b):
            response_b = post_index(
                scholarship_b_id,
                scholarship_b_version_id,
                scholarship_b_content_hash,
                scholarship_b_record_version,
            )
        self.assertEqual(response_b.status_code, 200, response_b.text)

        for scholarship_id, version_id, expected_vector, expected_text in (
            (scholarship_a_id, scholarship_a_version_id, vector_a, scholarship_a_text),
            (scholarship_b_id, scholarship_b_version_id, vector_b, scholarship_b_text),
        ):
            with self.Session() as db:
                version = db.get(ScholarshipDocumentVersion, version_id)
                source = db.get(ScholarshipSourceDocument, version.source_document_id)
                chunk = db.query(ScholarshipDocumentChunk).filter_by(
                    document_version_id=version_id
                ).one()
                embedding = db.query(ScholarshipChunkEmbedding).filter_by(
                    document_version_id=version_id
                ).one()
                self.assertEqual(source.scholarship_id, scholarship_id)
                self.assertEqual(version.indexing_status, "indexed")
                self.assertEqual(chunk.chunk_text, expected_text)
                self.assertEqual(chunk.chunk_text, version.extracted_text)
                self.assertEqual(list(embedding.embedding), expected_vector)

        directions = (
            (
                scholarship_a_id, scholarship_b_id, vector_a, vector_b, vector_b,
                scholarship_a_text, scholarship_b_text,
            ),
            (
                scholarship_b_id, scholarship_a_id, vector_b, vector_a, vector_a,
                scholarship_b_text, scholarship_a_text,
            ),
        )
        for requested_id, other_id, requested_vector, other_vector, query_vector, own_text, other_text in directions:
            with self.subTest(requested_scholarship=requested_id):
                self.assertEqual(query_vector, other_vector)
                client = MagicMock()
                client.models.generate_content.return_value.text = "Scholarship-scoped answer."
                with self.Session() as db, \
                        patch.object(admin_api.rag_service, "get_model_revision", return_value=MODEL_REVISION), \
                        patch.object(admin_api.rag_service, "embed_query", return_value=query_vector), \
                        patch.object(admin_api.rag_service, "_gemini_client", return_value=client):
                    result = admin_api.rag_service.retrieve(
                        db,
                        "query favoring the other scholarship",
                        scholarship_id=requested_id,
                        top_k=1,
                    )
                    self.assertEqual(result.status, admin_api.rag_service.STATUS_OK)
                    self.assertEqual([chunk.scholarship_id for chunk in result.chunks], [requested_id])
                    self.assertEqual([chunk.text for chunk in result.chunks], [own_text])
                    self.assertLess(result.chunks[0].score, 0.01)
                    self.assertGreater(
                        admin_api.rag_service._cosine_similarity(query_vector, other_vector),
                        admin_api.rag_service._cosine_similarity(query_vector, requested_vector),
                    )

                    answer = admin_api.rag_service.answer_question(
                        db,
                        "query favoring the other scholarship",
                        scholarship_id=requested_id,
                    )
                    self.assertEqual(answer.status, admin_api.rag_service.STATUS_OK)
                    self.assertEqual([chunk.scholarship_id for chunk in answer.chunks], [requested_id])
                    self.assertEqual([chunk.text for chunk in answer.chunks], [own_text])
                    contents = client.models.generate_content.call_args.kwargs["contents"]
                    self.assertIn(own_text, contents)
                    self.assertNotIn(other_text, contents)
                    self.assertNotEqual(requested_id, other_id)

    def test_rag_detects_conflict_outside_final_top_k(self):
        def create_approved_document(label, content, content_hash):
            with self.Session() as db:
                source_url = f"https://official.example/{label}/{uuid4().hex}"
                source = ScholarshipSourceDocument(
                    scholarship_id=self.scholarship_id,
                    source_url=source_url,
                    normalized_url=source_url,
                    source_role="official_information",
                )
                db.add(source)
                db.flush()
                scholarship = db.get(Scholarship, self.scholarship_id)
                checks = list(scholarship.source_checks or [])
                checks.append({
                    "url": source_url,
                    "status": "ok",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                })
                scholarship.source_checks = checks
                version = ScholarshipDocumentVersion(
                    source_document_id=source.id,
                    content_hash=content_hash,
                    retrieved_at=datetime.now(timezone.utc),
                    mime_type="text/html",
                    extractor_version="integration-test",
                    extracted_text=content,
                    verification_status_snapshot="verified",
                    verification_basis_snapshot="official_source",
                    last_verified_date_snapshot=date.today(),
                    scholarship_record_version_snapshot=self.record_version,
                    review_status="approved",
                    indexing_status="approved",
                )
                db.add(version)
                db.flush()
                db.add(ScholarshipDocumentVersionApproval(
                    document_version_id=version.id,
                    decision="approved",
                    verification_status_snapshot=version.verification_status_snapshot,
                    verification_basis_snapshot=version.verification_basis_snapshot,
                    review_status_snapshot=version.review_status,
                    indexing_status_snapshot=version.indexing_status,
                    document_record_version_snapshot=version.scholarship_record_version_snapshot,
                    source_active_at_decision=source.is_active,
                    scholarship_record_version_at_decision=self.record_version,
                    scholarship_verification_status_at_decision="verified",
                    scholarship_verification_basis_at_decision="official_source",
                    scholarship_archived_at_decision=None,
                    actor=self.admin.email,
                    reason="Conflict-evidence integration fixture approval.",
                ))
                db.commit()
                return version.id

        def post_index(version_id, content_hash, embedding):
            body = {
                "expected_content_hash": content_hash,
                "expected_scholarship_record_version": self.record_version,
            }
            with self._mock_indexing(embedding=embedding), \
                    TestClient(self.app, raise_server_exceptions=False) as client:
                return client.post(
                    f"/admin/scholarships/{self.scholarship_id}/documents/{version_id}/index",
                    json=body,
                )

        first_text = "Application deadline is 31 March 2027."
        second_text = "Applications close on 30 April 2027."
        first_hash = "c" * 64
        second_hash = "d" * 64
        first_version_id = create_approved_document("deadline-a", first_text, first_hash)
        second_version_id = create_approved_document("deadline-b", second_text, second_hash)
        first_response = post_index(first_version_id, first_hash, VECTOR)
        second_vector = [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
        second_response = post_index(second_version_id, second_hash, second_vector)
        self.assertEqual(first_response.status_code, 200, first_response.text)
        self.assertEqual(second_response.status_code, 200, second_response.text)

        with self.Session() as db, \
                patch.object(admin_api.rag_service, "get_model_revision", return_value=MODEL_REVISION), \
                patch.object(admin_api.rag_service, "embed_query", return_value=VECTOR):
            result = admin_api.rag_service.retrieve(
                db,
                "application deadline",
                scholarship_id=self.scholarship_id,
                top_k=1,
            )

        self.assertEqual(result.status, admin_api.rag_service.STATUS_OK)
        self.assertEqual([chunk.text for chunk in result.chunks], [first_text])
        self.assertEqual(len(result.conflicts), 1)
        self.assertEqual(
            {statement.value for statement in result.conflicts[0].statements},
            {"2027-03-31", "2027-04-30"},
        )

    def test_float32_stored_embedding_is_reused_when_expected_vector_matches(self):
        expected_vector = [math.sqrt(0.5), math.sqrt(0.5)] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
        self.assertTrue(math.isclose(math.hypot(*expected_vector), 1.0, rel_tol=1e-12, abs_tol=1e-12))

        with self._mock_indexing(embedding=expected_vector):
            first_response = self._post_index()

        self.assertEqual(first_response.status_code, 200, first_response.text)
        with self.Session() as db:
            stored_embedding = db.query(ScholarshipChunkEmbedding).filter_by(
                document_version_id=self.version_id
            ).one()
            stored_vector = list(stored_embedding.embedding)

        self.assertTrue(any(stored != expected for stored, expected in zip(stored_vector, expected_vector)))
        self.assertTrue(
            all(
                math.isclose(stored, expected, rel_tol=1e-6, abs_tol=1e-12)
                for stored, expected in zip(stored_vector, expected_vector)
            )
        )

        with self._mock_indexing(embedding=expected_vector):
            second_response = self._post_index()

        self.assertEqual(second_response.status_code, 200, second_response.text)
        self.assertTrue(second_response.json()["idempotent"])
        with self.Session() as db:
            self.assertEqual(
                db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=self.version_id).count(),
                1,
            )

    def test_different_normalized_embedding_is_rejected_without_overwriting(self):
        original_vector = [math.sqrt(0.5), math.sqrt(0.5)] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
        different_vector = [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
        self.assertTrue(math.isclose(math.hypot(*original_vector), 1.0, rel_tol=1e-12, abs_tol=1e-12))
        self.assertTrue(math.isclose(math.hypot(*different_vector), 1.0, rel_tol=1e-12, abs_tol=1e-12))

        with self._mock_indexing(embedding=original_vector):
            first_response = self._post_index()

        self.assertEqual(first_response.status_code, 200, first_response.text)
        with self.Session() as db:
            original_embedding = db.query(ScholarshipChunkEmbedding).filter_by(
                document_version_id=self.version_id
            ).one()
            original_embedding_id = original_embedding.id
            stored_vector = list(original_embedding.embedding)

        with self._mock_indexing(embedding=different_vector):
            mismatch_response = self._post_index()

        self.assertEqual(mismatch_response.status_code, 409, mismatch_response.text)
        with self.Session() as db:
            embeddings = db.query(ScholarshipChunkEmbedding).filter_by(
                document_version_id=self.version_id
            ).all()
            self.assertEqual(len(embeddings), 1)
            self.assertEqual(embeddings[0].id, original_embedding_id)
            self.assertEqual(list(embeddings[0].embedding), stored_vector)
            self.assertEqual(
                db.query(ScholarshipAuditLog)
                .filter_by(scholarship_id=self.scholarship_id, action="document_indexed")
                .count(),
                1,
            )

    def _post_index_with_lock_timeout(self, preprocessing_done, request_pids=None):
        def get_request_db():
            with self.engine.connect() as connection:
                connection.execute(text("SET lock_timeout = '15s'"))
                connection.commit()
                try:
                    with self.Session(bind=connection) as db:
                        if request_pids is not None:
                            request_pids.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
                        yield db
                finally:
                    connection.execute(text("RESET lock_timeout"))
                    connection.commit()

        # The worker owns these patches so a cleanup timeout cannot remove them mid-request.
        with patch.dict(self.app.dependency_overrides, {admin_api.get_db: get_request_db}), \
                self._mock_indexing(chunker=lambda text_value: (
                    preprocessing_done.set() or self._chunk(text_value)
                )):
            return self._post_index()

    def _cleanup_lock_worker(self, lock_session, pool, future):
        try:
            lock_session.rollback()
        finally:
            try:
                lock_session.close()
            finally:
                try:
                    if future is not None:
                        _, unfinished = wait([future], timeout=30)
                        if unfinished:
                            self.fail("Indexing worker did not finish within 30 seconds during cleanup")
                        future.result()
                finally:
                    pool.shutdown(wait=False)

    def _wait_for_lock_wait(self, query_filter):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with self.admin_engine.connect() as connection:
                waiting = connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE pid <> pg_backend_pid() AND wait_event_type = 'Lock' AND "
                        + query_filter
                        + ")"
                    )
                ).scalar_one()
            if waiting:
                return
            time.sleep(0.05)
        self.fail(f"PostgreSQL request did not reach expected lock wait: {query_filter}")

    def _wait_for_row_lock_wait(self, request_pid, holder_pid):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with self.admin_engine.connect() as connection:
                waiting = connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE pid = :request_pid AND pid <> :holder_pid "
                        "AND wait_event_type = 'Lock' "
                        "AND :holder_pid = ANY(pg_blocking_pids(pid)))"
                    ),
                    {"request_pid": request_pid, "holder_pid": holder_pid},
                ).scalar_one()
            if waiting:
                return
            time.sleep(0.05)
        self.fail(f"PostgreSQL request {request_pid} was not blocked by row-lock holder {holder_pid}")

    def test_advisory_and_row_locks_gate_triggered_pgvector_persistence(self):
        blocker = self.Session()
        preprocessing_done = Event()
        pool = ThreadPoolExecutor(max_workers=1)
        future = None
        try:
            blocker.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": LOCK_ID},
            )
            future = pool.submit(self._post_index_with_lock_timeout, preprocessing_done)
            self.assertTrue(preprocessing_done.wait(timeout=10))
            self._wait_for_lock_wait("query LIKE '%pg_advisory_xact_lock%'")
            blocker.rollback()
            response = future.result(timeout=30)
        finally:
            self._cleanup_lock_worker(blocker, pool, future)

        self.assertEqual(response.status_code, 200, response.text)
        with self.Session() as db:
            version = db.get(ScholarshipDocumentVersion, self.version_id)
            chunk = db.query(ScholarshipDocumentChunk).filter_by(document_version_id=self.version_id).one()
            embedding = db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=self.version_id).one()
            approval = (
                db.query(ScholarshipDocumentVersionApproval)
                .filter_by(document_version_id=self.version_id)
                .order_by(ScholarshipDocumentVersionApproval.id.desc())
                .one()
            )
            self.assertEqual(version.indexing_status, "indexed")
            self.assertEqual(embedding.chunk_id, chunk.id)
            self.assertEqual(embedding.approval_id, approval.id)
            self.assertEqual(embedding.dimensions, EMBEDDING_DIMENSIONS)
            self.assertEqual(len(embedding.embedding), EMBEDDING_DIMENSIONS)
            self.assertEqual(
                db.query(ScholarshipAuditLog)
                .filter_by(scholarship_id=self.scholarship_id, action="document_indexed")
                .count(),
                1,
            )

        row_lock = self.Session()
        preprocessing_done = Event()
        request_pids = []
        pool = ThreadPoolExecutor(max_workers=1)
        future = None
        try:
            row_lock.query(Scholarship).filter_by(id=self.scholarship_id).with_for_update().one()
            holder_pid = row_lock.execute(text("SELECT pg_backend_pid()")).scalar_one()
            future = pool.submit(self._post_index_with_lock_timeout, preprocessing_done, request_pids)
            self.assertTrue(preprocessing_done.wait(timeout=10))
            self.assertEqual(len(request_pids), 1)
            self.assertNotEqual(request_pids[0], holder_pid)
            self._wait_for_row_lock_wait(request_pids[0], holder_pid)
            self.assertFalse(future.done(), "Indexing request completed while the row lock was held")
            row_lock.rollback()
            response = future.result(timeout=30)
        finally:
            self._cleanup_lock_worker(row_lock, pool, future)
        self.assertEqual(response.status_code, 200, response.text)

    def test_concurrent_requests_are_serialized_and_idempotent(self):
        barrier = Barrier(2)

        def synchronized_chunker(text_value):
            barrier.wait(timeout=15)
            return self._chunk(text_value)

        with self._mock_indexing(chunker=synchronized_chunker):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self._post_index) for _ in range(2)]
                responses = [future.result(timeout=45) for future in futures]

        self.assertEqual([response.status_code for response in responses], [200, 200])
        with self.Session() as db:
            self.assertEqual(
                db.query(ScholarshipDocumentChunk).filter_by(document_version_id=self.version_id).count(),
                1,
            )
            self.assertEqual(
                db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=self.version_id).count(),
                1,
            )
            self.assertEqual(
                db.query(ScholarshipAuditLog)
                .filter_by(scholarship_id=self.scholarship_id, action="document_indexed")
                .count(),
                1,
            )
