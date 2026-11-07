"""
Admin scholarship management and data quality. Uses in-memory SQLite.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
import http.client
import ipaddress
import os
import socket
import ssl
import urllib.error
import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import dns.exception
import dns.rdatatype
import dns.resolver
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.permissions import require_admin
from app.database import Base
from app.models.opportunity import Program, Scholarship, ScholarshipAuditLog, ScholarshipProgramLink, University
from app.models import scholarship_knowledge as knowledge_model
from app.models.scholarship_knowledge import (
    ScholarshipChunkEmbedding,
    ScholarshipDocumentChunk,
    ScholarshipDocumentVersion,
    ScholarshipDocumentVersionApproval,
    ScholarshipSourceDocument,
)
from app.models.user import SavedScholarship, StudentProfile, User
from app.routers import admin_scholarships as admin_api
from app.routers import eligibility as eligibility_api
from app.routers import recommendations as recommendations_api
from app.routers import saved_scholarships as saved_api
from app.routers import scholarships as api
from app.services.scholarship_document_indexing import DocumentChunk
from app.routers.auth import get_current_user, get_optional_user
from app.schemas.admin import AdminDetail, ArchiveWrite, DuplicateWrite, FlagWrite, VerificationWrite
from app.schemas.opportunity import ScholarshipCreate, ScholarshipUpdate
from app.services.scholarship_eligibility import evaluate_scholarship
from app.services.scholarship_quality import duplicate_pairs, find_conflicts, find_issues, update_record
from app.services.scholarship_search import search_scholarships
from app.services.source_check import (
    DNS_TIMEOUT_SECONDS,
    MAX_CONTENT_HASH_BYTES,
    TIMEOUT_SECONDS,
    _request,
    _resolve_public_addresses,
    check_url,
    is_public_host,
)
from app.services.source_url_safety import safe_source_urls_in_text
from test_scholarship_eligibility import make_profile, make_scholarship
from test_scholarship_recommendations import CLEAR

FIELDS = {key: value for key, value in vars(make_scholarship(**CLEAR)).items() if key != "id"}
GOOD_INFO = "https://example.org/official"


def verification(**overrides):
    data = dict(status="verified", basis="official_source", source_url=GOOD_INFO, verified_on=date(2026, 10, 1),
                notes="Read the official call for this cycle.", evidence_reviewed=True)
    return VerificationWrite(**{**data, **overrides})


class Base_(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.university = University(name="TU Example", country="Germany")
        self.db.add(self.university)
        self.db.flush()
        self.program = Program(name="MSc CS", university_id=self.university.id, degree_level="Master", field_of_study="Computer Science",
                               duration_months=24, tuition_amount=10000, tuition_currency="EUR")
        self.record = Scholarship(**{**FIELDS, "name": "Alpha Award", "official_info_url": GOOD_INFO,
                                     "official_application_url": GOOD_INFO, "last_verified_date": date(2026, 10, 1), "record_version": 1})
        self.other = Scholarship(**{**FIELDS, "name": "Beta Award", "country": "Italy", "official_info_url": GOOD_INFO})
        self.admin = User(email="admin@example.com", hashed_password="x", full_name="Admin", role="admin")
        self.student = User(email="student@example.com", hashed_password="x", full_name="Student")
        self.db.add_all([self.program, self.record, self.other, self.admin, self.student])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def edit(self, **fields):
        return api.update_scholarship(self.record.id, ScholarshipUpdate(**fields), db=self.db, admin=self.admin)

    def detail(self, record=None):
        return AdminDetail.model_validate(admin_api.record_detail((record or self.record).id, db=self.db)).model_dump()

    def assert_refused(self, code, call):
        with self.assertRaises(HTTPException) as error:
            call()
        self.assertEqual(error.exception.status_code, code, error.exception.detail)
        return error.exception


class AuthorizationTests(Base_):
    def test_student_is_refused(self):
        self.assert_refused(403, lambda: require_admin(current_user=self.student))
        self.assertEqual(require_admin(current_user=self.admin), self.admin)

    def test_every_admin_route_needs_admin(self):
        for route in admin_api.router.routes:
            self.assertIn(require_admin, [item.call for item in route.dependant.dependencies], route.path)

    def test_every_write_route_needs_admin(self):
        for route in api.router.routes:
            if route.methods & {"POST", "PUT", "DELETE"}:
                self.assertIn(require_admin, [item.call for item in route.dependant.dependencies], route.path)

    def test_no_token_gets_nothing(self):
        self.assertIsNone(get_optional_user(None, self.db))
        self.assert_refused(401, lambda: get_optional_user("not-a-real-token", self.db))

    def test_role_comes_from_the_database_only(self):
        for route in admin_api.router.routes:
            names = [item.name for item in route.dependant.query_params + route.dependant.path_params]
            self.assertFalse({"role", "user_id"} & set(names), route.path)


class AdminDocumentTests(Base_):
    def add_document(
        self,
        scholarship=None,
        source_url="https://example.org/call",
        extracted_text="Stored evidence",
        content_hash="a" * 64,
        retrieved_at=None,
        source_document=None,
    ):
        scholarship = scholarship or self.record
        if source_document is None:
            source_document = ScholarshipSourceDocument(
                scholarship_id=scholarship.id,
                source_url=source_url,
                normalized_url=source_url,
                source_role="official_information",
            )
            self.db.add(source_document)
            self.db.flush()
        version = ScholarshipDocumentVersion(
            source_document_id=source_document.id,
            content_hash=content_hash,
            retrieved_at=retrieved_at or datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc),
            mime_type="text/html",
            extractor_version="test-extractor",
            extracted_text=extracted_text,
            page_count=1,
            verification_status_snapshot=scholarship.verification_status,
            verification_basis_snapshot=scholarship.verification_basis,
            last_verified_date_snapshot=scholarship.last_verified_date,
            scholarship_record_version_snapshot=scholarship.record_version,
        )
        self.db.add(version)
        checks = list(scholarship.source_checks or [])
        checks = [check for check in checks if check.get("url") != source_document.source_url]
        checks.append({
            "url": source_document.source_url,
            "status": "ok",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": version.content_hash,
        })
        scholarship.source_checks = checks
        self.db.commit()
        return source_document, version

    def http_client(self, user):
        app = FastAPI()
        app.include_router(admin_api.router)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[admin_api.get_db] = lambda: self.db
        return TestClient(app)

    def review_payload(self, version, decision="approve", **overrides):
        return {
            "decision": decision,
            "reason": "Reviewed the official scholarship evidence.",
            "expected_content_hash": version.content_hash,
            "expected_scholarship_record_version": self.record.record_version,
            **overrides,
        }

    def post_review(self, version, decision="approve", user=None, **overrides):
        with self.http_client(user or self.admin) as client:
            return client.post(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}/review",
                json=self.review_payload(version, decision, **overrides),
            )

    def index_payload(self, version, **overrides):
        return {
            "expected_content_hash": version.content_hash,
            "expected_scholarship_record_version": self.record.record_version,
            **overrides,
        }

    def post_index(
        self,
        version,
        user=None,
        model_revision="0123456789abcdef0123456789abcdef01234567",
        embedding_vectors=None,
        **overrides,
    ):
        def generate_embeddings(chunks, *, model_revision):
            if embedding_vectors is None:
                return [self.unit_vector() for _ in chunks]
            return [list(vector) for vector in embedding_vectors]

        with patch.object(admin_api.rag_service, "get_model_revision", return_value=model_revision), \
                patch.object(
                    admin_api.document_indexing,
                    "chunk_document_text",
                    side_effect=self.mock_chunks,
                ), \
                patch.object(
                    admin_api.document_indexing,
                    "generate_document_embeddings",
                    side_effect=generate_embeddings,
                ):
            with self.http_client(user or self.admin) as client:
                return client.post(
                    f"/admin/scholarships/{self.record.id}/documents/{version.id}/index",
                    json=self.index_payload(version, **overrides),
                )

    def unit_vector(self, index=0):
        vector = [0.0] * 384
        vector[index] = 1.0
        return vector

    def mock_chunks(self, extracted_text, *, model_revision=None):
        midpoint = len(extracted_text) // 2
        overlap_start = max(0, midpoint - 2)
        texts = (
            (0, midpoint, extracted_text[:midpoint]),
            (overlap_start, len(extracted_text), extracted_text[overlap_start:]),
        )
        return [
            DocumentChunk(
                ordinal=ordinal,
                chunk_text=chunk_text,
                chunk_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                start_offset=start,
                end_offset=end,
            )
            for ordinal, (start, end, chunk_text) in enumerate(texts)
        ]

    def add_approved_document(self, **overrides):
        source, version = self.add_document(**overrides)
        response = self.post_review(version)
        self.assertEqual(response.status_code, 200, response.text)
        return source, version

    def add_approval_event(self, version, decision):
        source = self.db.get(ScholarshipSourceDocument, version.source_document_id)
        approval = ScholarshipDocumentVersionApproval(
            document_version_id=version.id,
            decision=decision,
            verification_status_snapshot=version.verification_status_snapshot,
            verification_basis_snapshot=version.verification_basis_snapshot,
            review_status_snapshot=version.review_status,
            indexing_status_snapshot=version.indexing_status,
            document_record_version_snapshot=version.scholarship_record_version_snapshot,
            source_active_at_decision=source.is_active,
            scholarship_record_version_at_decision=self.record.record_version,
            scholarship_verification_status_at_decision=self.record.verification_status,
            scholarship_verification_basis_at_decision=self.record.verification_basis,
            scholarship_archived_at_decision=self.record.archived_at,
            actor=self.admin.email,
            reason="Test approval history event.",
        )
        self.db.add(approval)
        self.db.commit()
        return approval

    def add_existing_chunks(self, version, chunks):
        rows = [
            ScholarshipDocumentChunk(
                document_version_id=version.id,
                chunk_ordinal=chunk.ordinal,
                chunk_text=chunk.chunk_text,
                chunk_hash=chunk.chunk_hash,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
            )
            for chunk in chunks
        ]
        self.db.add_all(rows)
        self.db.commit()
        return rows

    def test_admin_can_list_documents_and_versions(self):
        source, version = self.add_document()
        result = admin_api.list_documents(
            self.record.id, skip=0, limit=25, version_skip=0, version_limit=25, db=self.db
        )
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], source.id)
        self.assertEqual(result["items"][0]["scholarship_name"], self.record.name)
        self.assertEqual(result["items"][0]["versions"][0]["id"], version.id)
        self.assertEqual(result["items"][0]["versions"][0]["content_hash"], "a" * 64)

    def test_admin_can_inspect_a_version(self):
        source, version = self.add_document()
        result = admin_api.inspect_document_version(
            self.record.id, version.id, text_offset=0, text_limit=100, db=self.db
        )
        self.assertEqual(result["source_document_id"], source.id)
        self.assertEqual(result["document_version_id"], version.id)
        self.assertEqual(result["content_hash"], version.content_hash)
        self.assertEqual(result["source_url"], source.source_url)
        self.assertEqual(result["extracted_text"], "Stored evidence")
        self.assertEqual(result["review_status"], "pending")
        self.assertEqual(result["indexing_status"], "pending")
        self.assertEqual(result["scholarship_record_version_snapshot"], self.record.record_version)
        self.assertNotIn("embedding", result)

    def test_document_endpoints_reject_non_admin(self):
        _, version = self.add_document()
        with self.http_client(self.student) as client:
            listing = client.get(f"/admin/scholarships/{self.record.id}/documents")
            inspection = client.get(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}"
            )
        self.assertEqual(listing.status_code, 403)
        self.assertEqual(inspection.status_code, 403)

    def test_admin_http_responses_validate_for_list_and_inspection(self):
        _, version = self.add_document()
        with self.http_client(self.admin) as client:
            listing = client.get(
                f"/admin/scholarships/{self.record.id}/documents"
                "?skip=0&limit=1&version_skip=0&version_limit=1"
            )
            inspection = client.get(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}?text_limit=100"
            )
            oversized_text = client.get(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}?text_limit=10001"
            )
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(listing.json()["items"][0]["versions"][0]["id"], version.id)
        self.assertEqual(inspection.status_code, 200, inspection.text)
        self.assertEqual(inspection.json()["document_version_id"], version.id)
        self.assertEqual(inspection.json()["extracted_text"], "Stored evidence")
        self.assertNotIn("embedding", inspection.json())
        self.assertEqual(oversized_text.status_code, 422)

    def test_invalid_pagination_returns_http_422(self):
        _, version = self.add_document(extracted_text="0123456789" * 100)
        list_path = f"/admin/scholarships/{self.record.id}/documents"
        detail_path = f"{list_path}/{version.id}"
        invalid_queries = (
            (list_path, "skip=-1"),
            (list_path, f"skip={admin_api.MAX_DOCUMENT_OFFSET + 1}"),
            (list_path, "version_skip=-1"),
            (list_path, f"version_skip={admin_api.MAX_DOCUMENT_OFFSET + 1}"),
            (list_path, "limit=101"),
            (list_path, "version_limit=101"),
            (detail_path, "text_offset=-1"),
            (detail_path, f"text_offset={admin_api.MAX_TEXT_OFFSET + 1}"),
        )
        with self.http_client(self.admin) as client:
            responses = [client.get(f"{path}?{query}") for path, query in invalid_queries]
        self.assertEqual([response.status_code for response in responses], [422] * len(invalid_queries))

    def test_missing_scholarship_and_version_return_404(self):
        _, version = self.add_document(scholarship=self.other)
        with self.http_client(self.admin) as client:
            missing_scholarship = client.get("/admin/scholarships/99999/documents")
            missing_version = client.get(
                f"/admin/scholarships/{self.record.id}/documents/99999"
            )
            out_of_scope_version = client.get(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}"
            )
        self.assertEqual(missing_scholarship.status_code, 404)
        self.assertEqual(missing_version.status_code, 404)
        self.assertEqual(out_of_scope_version.status_code, 404)

    def test_extracted_text_is_paged_and_sensitive_source_url_parts_are_redacted(self):
        source_url = "https://example.org/call?token=secret&lang=en#access_token=fragmentsecret"
        source, version = self.add_document(
            source_url=source_url,
            extracted_text="0123456789" * 1200,
        )
        first_page = admin_api.inspect_document_version(
            self.record.id, version.id, text_offset=0, text_limit=10000, db=self.db
        )
        second_page = admin_api.inspect_document_version(
            self.record.id, version.id, text_offset=10000, text_limit=4000, db=self.db
        )
        self.assertEqual(len(first_page["extracted_text"]), 10000)
        self.assertTrue(first_page["has_more_text"])
        self.assertEqual(len(second_page["extracted_text"]), 2000)
        self.assertFalse(second_page["has_more_text"])
        self.assertEqual(first_page["text_total_chars"], 12000)
        self.assertEqual(first_page["source_url"], "https://example.org/call?lang=en")
        self.assertEqual(self.db.get(ScholarshipSourceDocument, source.id).source_url, source_url)

    def test_document_inspection_redacts_embedded_urls_without_changing_pagination_shape(self):
        text = (
            "Start. https://student:secret@example.org/?token=hidden. "
            "ftp://files.example/private. //private.example/path. "
            "Safe https://example.org/info?lang=en. Contact awards@example.org. "
            + ("More evidence. " * 20)
        )
        source, version = self.add_document(extracted_text=text)
        with self.http_client(self.admin) as client:
            response = client.get(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}?text_offset=0&text_limit=400"
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        sanitized_text = safe_source_urls_in_text(text)
        self.assertEqual(body["text_offset"], 0)
        self.assertEqual(body["text_limit"], 400)
        self.assertEqual(body["text_total_chars"], len(sanitized_text))
        self.assertEqual(body["extracted_text"], sanitized_text[:400])
        self.assertEqual(body["has_more_text"], len(sanitized_text) > 400)
        self.assertIn("https://example.org/info?lang=en", body["extracted_text"])
        self.assertIn("awards@example.org", body["extracted_text"])
        for secret in ("student", "secret@", "token=hidden", "ftp://", "private.example"):
            self.assertNotIn(secret, response.text)
        self.assertEqual(self.db.get(ScholarshipDocumentVersion, version.id).extracted_text, text)
        self.assertEqual(body["source_document_id"], source.id)

    def test_signed_and_generic_query_credentials_are_removed_from_urls(self):
        test_urls = (
            (
                "https://[2001:db8::1]:8443/call"
                "?X-Amz-Credential=credential&X-Amz-Signature=signature"
                "&X-Amz-Security-Token=token#fragment",
                "https://[2001:db8::1]:8443/call",
            ),
            (
                "http://example.org/path?token=token-value&api_key=key-value#fragment",
                "http://example.org/path",
            ),
        )
        with self.http_client(self.admin) as client:
            for index, (original_url, expected_url) in enumerate(test_urls):
                source, version = self.add_document(
                    source_url=original_url,
                    extracted_text=f"Document {index}",
                )
                response = client.get(
                    f"/admin/scholarships/{self.record.id}/documents/{version.id}"
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["source_url"], expected_url)
                self.assertEqual(self.db.get(ScholarshipSourceDocument, source.id).source_url, original_url)

    def test_admin_can_approve_pending_version_and_records_snapshots_and_audit(self):
        source, version = self.add_document()
        reason = "Reviewed the current official call."
        response = self.post_review(version, reason=reason)
        self.assertEqual(response.status_code, 200, response.text)

        self.db.expire_all()
        stored_version = self.db.get(ScholarshipDocumentVersion, version.id)
        approval = self.db.query(ScholarshipDocumentVersionApproval).filter_by(
            document_version_id=version.id
        ).one()
        audit = self.db.query(ScholarshipAuditLog).filter_by(
            scholarship_id=self.record.id, action="document_approved"
        ).one()
        self.assertEqual((stored_version.review_status, stored_version.indexing_status), ("approved", "approved"))
        self.assertEqual(approval.decision, "approved")
        self.assertEqual(approval.actor, self.admin.email)
        self.assertEqual(approval.reason, reason)
        self.assertEqual(approval.verification_status_snapshot, "verified")
        self.assertEqual(approval.verification_basis_snapshot, "official_source")
        self.assertEqual(approval.review_status_snapshot, "approved")
        self.assertEqual(approval.indexing_status_snapshot, "approved")
        self.assertEqual(approval.document_record_version_snapshot, self.record.record_version)
        self.assertTrue(approval.source_active_at_decision)
        self.assertEqual(approval.scholarship_record_version_at_decision, self.record.record_version)
        self.assertEqual(approval.scholarship_verification_status_at_decision, "verified")
        self.assertEqual(approval.scholarship_verification_basis_at_decision, "official_source")
        self.assertIsNone(approval.scholarship_archived_at_decision)
        self.assertEqual(audit.actor_email, self.admin.email)
        self.assertEqual(audit.note, reason)
        self.assertEqual(audit.changes["document_version_id"], [None, version.id])
        self.assertEqual(response.json()["approval_event_id"], approval.id)
        self.assertEqual(source.is_active, approval.source_active_at_decision)

    def test_admin_can_reject_pending_version_without_an_approval_event(self):
        _, version = self.add_document()
        reason = "The submitted content does not support this award."
        response = self.post_review(version, decision="reject", reason=reason)
        self.assertEqual(response.status_code, 200, response.text)

        self.db.expire_all()
        stored_version = self.db.get(ScholarshipDocumentVersion, version.id)
        self.assertEqual(stored_version.review_status, "rejected")
        self.assertEqual(stored_version.indexing_status, "pending")
        self.assertEqual(
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .count(),
            0,
        )
        audit = self.db.query(ScholarshipAuditLog).filter_by(
            scholarship_id=self.record.id, action="document_rejected"
        ).one()
        self.assertEqual(audit.actor_email, self.admin.email)
        self.assertEqual(audit.note, reason)
        self.assertEqual(audit.changes["document_version_id"], [None, version.id])
        self.assertEqual(audit.changes["review_status"], ["pending", "rejected"])

    def test_non_admin_cannot_review_document_version(self):
        _, version = self.add_document()
        response = self.post_review(version, user=self.student)
        self.assertEqual(response.status_code, 403)

    def test_review_returns_404_for_missing_or_out_of_scope_records(self):
        _, other_version = self.add_document(scholarship=self.other)
        payload = self.review_payload(other_version)
        with self.http_client(self.admin) as client:
            missing_scholarship = client.post(
                f"/admin/scholarships/99999/documents/{other_version.id}/review",
                json=payload,
            )
            missing_version = client.post(
                f"/admin/scholarships/{self.record.id}/documents/99999/review",
                json=payload,
            )
            out_of_scope = client.post(
                f"/admin/scholarships/{self.record.id}/documents/{other_version.id}/review",
                json=payload,
            )
        self.assertEqual(missing_scholarship.status_code, 404)
        self.assertEqual(missing_version.status_code, 404)
        self.assertEqual(out_of_scope.status_code, 404)

    def test_review_rejects_blank_reason(self):
        _, version = self.add_document()
        with self.http_client(self.admin) as client:
            blank_reason = client.post(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}/review",
                json=self.review_payload(version, reason="  \t "),
            )
            extra_field = client.post(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}/review",
                json={**self.review_payload(version), "unexpected": True},
            )
            malformed_hash = client.post(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}/review",
                json=self.review_payload(version, expected_content_hash="not-a-sha256"),
            )
        self.assertEqual(blank_reason.status_code, 422)
        self.assertEqual(extra_field.status_code, 422)
        self.assertEqual(malformed_hash.status_code, 422)

    def test_review_rejects_stale_content_hash(self):
        _, version = self.add_document()
        response = self.post_review(version, expected_content_hash="b" * 64)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.review_status, "pending")
        self.assertEqual(self.db.query(ScholarshipDocumentVersionApproval).count(), 0)

    def test_review_rejects_changed_scholarship_record_version(self):
        _, version = self.add_document()
        expected_record_version = self.record.record_version
        self.record.record_version += 1
        self.db.commit()
        response = self.post_review(
            version,
            expected_scholarship_record_version=expected_record_version,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.db.query(ScholarshipDocumentVersionApproval).count(), 0)

    def test_unverified_scholarship_cannot_be_approved(self):
        self.record.verification_status = "unverified"
        self.record.verification_basis = "not_verified"
        self.record.record_version += 1
        self.db.commit()
        _, version = self.add_document()
        response = self.post_review(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.review_status, "pending")

    def test_inactive_source_cannot_be_approved(self):
        source, version = self.add_document()
        source.is_active = False
        self.db.commit()
        response = self.post_review(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.review_status, "pending")

    def test_document_without_its_own_source_check_cannot_be_approved(self):
        _, version = self.add_document()
        self.record.source_checks = []
        self.db.commit()

        response = self.post_review(version)

        self.assertEqual(response.status_code, 409)
        self.assertIn("Document source URL", response.json()["detail"])
        self.assertEqual(version.review_status, "pending")

    def test_stale_source_cannot_be_approved(self):
        self.record.last_verified_date = date.today() - timedelta(days=181)
        self.record.record_version += 1
        self.db.commit()
        _, version = self.add_document()
        response = self.post_review(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.review_status, "pending")

    def test_broken_source_check_cannot_be_approved(self):
        self.record.source_checks = [{"url": GOOD_INFO, "status": "broken"}]
        self.db.commit()
        _, version = self.add_document()
        response = self.post_review(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.review_status, "pending")

    def test_open_review_flag_cannot_be_approved(self):
        self.record.data_flags = ["review:deadline"]
        self.db.commit()
        _, version = self.add_document()
        response = self.post_review(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.review_status, "pending")

    def test_missing_official_source_cannot_be_approved(self):
        self.record.official_info_url = None
        self.record.record_version += 1
        self.db.commit()
        _, version = self.add_document()
        response = self.post_review(version)
        self.assertEqual(response.status_code, 409)

    def test_archived_scholarship_cannot_be_approved(self):
        self.record.archived_at = datetime.now(timezone.utc)
        self.record.record_version += 1
        self.db.commit()
        _, version = self.add_document()
        response = self.post_review(version)
        self.assertEqual(response.status_code, 409)

    def test_superseded_version_cannot_be_approved(self):
        source, version = self.add_document()
        self.add_document(
            source_document=source,
            content_hash="b" * 64,
            retrieved_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        )
        response = self.post_review(version)
        self.assertEqual(response.status_code, 409)

    def test_lower_id_cannot_be_approved_when_retrieved_at_is_newer(self):
        source, lower_id_version = self.add_document(
            retrieved_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )
        _, higher_id_version = self.add_document(
            source_document=source,
            content_hash="b" * 64,
            retrieved_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        )

        self.assertLess(lower_id_version.id, higher_id_version.id)
        self.assertGreater(lower_id_version.retrieved_at, higher_id_version.retrieved_at)
        response = self.post_review(lower_id_version)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(lower_id_version.review_status, "pending")
        self.assertEqual(self.db.query(ScholarshipDocumentVersionApproval).count(), 0)

    def test_higher_id_is_latest_when_retrieved_at_is_earlier(self):
        source, lower_id_version = self.add_document(
            retrieved_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )
        _, higher_id_version = self.add_document(
            source_document=source,
            content_hash="b" * 64,
            retrieved_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        )

        self.assertLess(lower_id_version.id, higher_id_version.id)
        self.assertGreater(lower_id_version.retrieved_at, higher_id_version.retrieved_at)
        response = self.post_review(higher_id_version)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(higher_id_version.review_status, "approved")

    def test_indexing_requires_strict_request_and_admin(self):
        _, version = self.add_approved_document()
        with self.http_client(self.student) as client:
            unauthorized = client.post(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}/index",
                json=self.index_payload(version),
            )
        with self.http_client(self.admin) as client:
            extra_field = client.post(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}/index",
                json={**self.index_payload(version), "embedding": [1.0]},
            )
            bad_hash = client.post(
                f"/admin/scholarships/{self.record.id}/documents/{version.id}/index",
                json=self.index_payload(version, expected_content_hash="bad"),
            )
        self.assertEqual(unauthorized.status_code, 403)
        self.assertEqual(extra_field.status_code, 422)
        self.assertEqual(bad_hash.status_code, 422)

    def test_indexing_returns_404_for_missing_or_out_of_scope_records(self):
        _, other_version = self.add_document(scholarship=self.other)
        with self.http_client(self.admin) as client:
            missing_scholarship = client.post(
                f"/admin/scholarships/99999/documents/{other_version.id}/index",
                json=self.index_payload(other_version),
            )
            missing_version = client.post(
                f"/admin/scholarships/{self.record.id}/documents/99999/index",
                json=self.index_payload(other_version),
            )
            out_of_scope = client.post(
                f"/admin/scholarships/{self.record.id}/documents/{other_version.id}/index",
                json=self.index_payload(other_version),
            )
        self.assertEqual(missing_scholarship.status_code, 404)
        self.assertEqual(missing_version.status_code, 404)
        self.assertEqual(out_of_scope.status_code, 404)

    def test_successful_indexing_persists_atomically_and_is_retrievable_by_rag(self):
        _, version = self.add_approved_document(
            extracted_text="The scholarship covers tuition and related costs. Tuition and living support are provided."
        )
        response = self.post_index(version)

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["status"], "indexed")
        self.assertEqual(data["chunk_count"], 2)
        self.assertEqual(data["embedding_count"], 2)
        self.assertEqual(data["chunks_created"], 2)
        self.assertEqual(data["embeddings_created"], 2)
        self.assertFalse(data["idempotent"])
        self.assertNotIn("embedding", data)
        self.assertEqual(version.indexing_status, "indexed")
        self.assertEqual(self.db.query(ScholarshipDocumentChunk).filter_by(document_version_id=version.id).count(), 2)
        self.assertEqual(
            self.db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=version.id).count(),
            2,
        )
        audit = self.db.query(ScholarshipAuditLog).filter_by(
            scholarship_id=self.record.id, action="document_indexed"
        ).one()
        self.assertEqual(audit.actor_email, self.admin.email)
        self.assertEqual(audit.changes["document_version_id"], [None, version.id])
        self.assertEqual(audit.changes["indexing_status"], ["approved", "indexed"])

        from app.services import rag_service
        with patch.object(rag_service, "embed_query", return_value=self.unit_vector()), patch.dict(
            "os.environ", {"MINILM_MODEL_REVISION": data["model_revision"]}
        ):
            result = rag_service.retrieve(self.db, "What does this scholarship cover?")
        self.assertEqual(result.status, rag_service.STATUS_OK)
        self.assertEqual({chunk.text for chunk in result.chunks}, {
            chunk.chunk_text for chunk in self.mock_chunks(version.extracted_text)
        })

    def test_oversized_document_is_rejected_before_preprocessing_or_writes(self):
        maximum = admin_api.document_indexing.MAX_DOCUMENT_INPUT_CHARS
        _, version = self.add_approved_document(extracted_text="x" * (maximum + 1))

        with patch.object(admin_api.rag_service, "get_model_revision") as get_revision, \
                patch.object(admin_api.document_indexing, "chunk_document_text") as chunker, \
                patch.object(
                    admin_api.document_indexing,
                    "generate_document_embeddings",
                ) as embedder:
            with self.http_client(self.admin) as client:
                response = client.post(
                    f"/admin/scholarships/{self.record.id}/documents/{version.id}/index",
                    json=self.index_payload(version),
                )

        self.assertEqual(response.status_code, 413)
        self.assertIn(str(maximum), response.json()["detail"])
        get_revision.assert_not_called()
        chunker.assert_not_called()
        embedder.assert_not_called()
        self.assertEqual(version.indexing_status, "approved")
        self.assertEqual(
            self.db.query(ScholarshipDocumentChunk)
            .filter_by(document_version_id=version.id)
            .count(),
            0,
        )
        self.assertEqual(
            self.db.query(ScholarshipChunkEmbedding)
            .filter_by(document_version_id=version.id)
            .count(),
            0,
        )
        self.assertEqual(
            self.db.query(ScholarshipAuditLog)
            .filter_by(scholarship_id=self.record.id, action="document_indexed")
            .count(),
            0,
        )

    def test_indexing_rejects_unverified_scholarship(self):
        _, version = self.add_approved_document()
        self.record.verification_status = "unverified"
        self.db.commit()
        response = self.post_index(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.indexing_status, "approved")

    def test_indexing_rejects_inactive_source(self):
        source, version = self.add_approved_document()
        source.is_active = False
        self.db.commit()
        response = self.post_index(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.indexing_status, "approved")

    def test_indexing_rejects_stale_verification(self):
        _, version = self.add_approved_document()
        self.record.last_verified_date = date.today() - timedelta(days=181)
        self.db.commit()
        response = self.post_index(version)
        self.assertEqual(response.status_code, 409)
        self.assertIn("currently verified", response.json()["detail"])

    def test_indexing_rejects_broken_source_check(self):
        _, version = self.add_approved_document()
        self.record.source_checks = [{"url": GOOD_INFO, "status": "broken"}]
        self.db.commit()
        response = self.post_index(version)
        self.assertEqual(response.status_code, 409)
        self.assertIn("currently verified", response.json()["detail"])

    def test_indexing_rejects_missing_document_source_check(self):
        source, version = self.add_approved_document()
        self.record.source_checks = []
        self.db.commit()

        response = self.post_index(version)

        self.assertEqual(response.status_code, 409)
        self.assertIn("Document source URL", response.json()["detail"])
        self.assertEqual(
            self.db.query(ScholarshipChunkEmbedding)
            .filter_by(document_version_id=version.id)
            .count(),
            0,
        )

    def test_indexing_rejects_open_review_flag(self):
        _, version = self.add_approved_document()
        self.record.data_flags = ["review:deadline"]
        self.db.commit()
        response = self.post_index(version)
        self.assertEqual(response.status_code, 409)
        self.assertIn("currently verified", response.json()["detail"])

    def test_indexing_passes_captured_revision_and_rejects_configuration_drift(self):
        _, version = self.add_approved_document()
        captured_revision = "0123456789abcdef0123456789abcdef01234567"
        changed_revision = "fedcba9876543210fedcba9876543210fedcba98"
        chunked_revisions = []
        used_revisions = []

        def chunk_document(extracted_text, *, model_revision):
            chunked_revisions.append(model_revision)
            return self.mock_chunks(extracted_text)

        def generate_embeddings(chunks, *, model_revision):
            used_revisions.append(model_revision)
            return [self.unit_vector() for _ in chunks]

        with patch.object(
            admin_api.rag_service,
            "get_model_revision",
            side_effect=[captured_revision, changed_revision],
        ) as get_model_revision, patch.object(
            admin_api.document_indexing,
            "chunk_document_text",
            side_effect=chunk_document,
        ), patch.object(
            admin_api.document_indexing,
            "generate_document_embeddings",
            side_effect=generate_embeddings,
        ):
            with self.http_client(self.admin) as client:
                response = client.post(
                    f"/admin/scholarships/{self.record.id}/documents/{version.id}/index",
                    json=self.index_payload(version),
                )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(chunked_revisions, [captured_revision])
        self.assertEqual(used_revisions, [captured_revision])
        self.assertEqual(get_model_revision.call_count, 2)
        self.assertEqual(version.indexing_status, "approved")

    def test_indexing_rejects_rejected_version(self):
        _, version = self.add_document()
        rejected = self.post_review(version, decision="reject")
        self.assertEqual(rejected.status_code, 200, rejected.text)
        response = self.post_index(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.indexing_status, "pending")

    def test_indexing_rejects_latest_revoked_approval(self):
        _, version = self.add_approved_document()
        revoked = self.add_approval_event(version, "revoked")
        self.assertEqual(revoked.decision, "revoked")
        response = self.post_index(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.indexing_status, "approved")

    def test_indexing_rejects_superseded_version(self):
        source, version = self.add_approved_document()
        self.add_document(
            source_document=source,
            content_hash="b" * 64,
            retrieved_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        )
        response = self.post_index(version)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.indexing_status, "approved")

    def test_indexing_rejects_stale_content_hash(self):
        _, version = self.add_approved_document()
        response = self.post_index(version, expected_content_hash="b" * 64)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.indexing_status, "approved")

    def test_indexing_rejects_stale_scholarship_record_version(self):
        _, version = self.add_approved_document()
        response = self.post_index(
            version,
            expected_scholarship_record_version=self.record.record_version + 1,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(version.indexing_status, "approved")

    def test_repeated_indexing_is_idempotent(self):
        _, version = self.add_approved_document()
        first = self.post_index(version)
        second = self.post_index(version)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertFalse(first.json()["idempotent"])
        self.assertTrue(second.json()["idempotent"])
        self.assertEqual(second.json()["chunks_created"], 0)
        self.assertEqual(second.json()["embeddings_created"], 0)
        self.assertEqual(self.db.query(ScholarshipDocumentChunk).filter_by(document_version_id=version.id).count(), 2)
        self.assertEqual(
            self.db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=version.id).count(),
            2,
        )
        self.assertEqual(
            self.db.query(ScholarshipAuditLog)
            .filter_by(scholarship_id=self.record.id, action="document_indexed")
            .count(),
            1,
        )

    def test_exact_existing_embedding_vectors_are_reused(self):
        _, version = self.add_approved_document()
        chunks = self.mock_chunks(version.extracted_text)
        stored_chunks = self.add_existing_chunks(version, chunks)
        approval = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        expected_vectors = [self.unit_vector(0), self.unit_vector(1)]
        model_revision = "0123456789abcdef0123456789abcdef01234567"
        self.db.add_all([
            ScholarshipChunkEmbedding(
                chunk_id=chunk.id,
                document_version_id=version.id,
                approval_id=approval.id,
                embedding=expected_vectors[ordinal],
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                model_revision=model_revision,
                dimensions=384,
            )
            for ordinal, chunk in enumerate(stored_chunks)
        ])
        self.db.commit()

        response = self.post_index(version, embedding_vectors=expected_vectors)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["embeddings_created"], 0)
        self.assertEqual(version.indexing_status, "indexed")
        persisted = (
            self.db.query(ScholarshipChunkEmbedding)
            .join(ScholarshipDocumentChunk)
            .filter(ScholarshipDocumentChunk.document_version_id == version.id)
            .order_by(ScholarshipDocumentChunk.chunk_ordinal)
            .all()
        )
        self.assertEqual([row.embedding for row in persisted], expected_vectors)

    def test_different_valid_existing_embedding_vector_is_rejected(self):
        _, version = self.add_approved_document()
        chunks = self.add_existing_chunks(version, self.mock_chunks(version.extracted_text))
        approval = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        expected_vectors = [self.unit_vector(0), self.unit_vector(1)]
        stored_vectors = [self.unit_vector(0), self.unit_vector(2)]
        model_revision = "0123456789abcdef0123456789abcdef01234567"
        self.db.add_all([
            ScholarshipChunkEmbedding(
                chunk_id=chunk.id,
                document_version_id=version.id,
                approval_id=approval.id,
                embedding=stored_vectors[ordinal],
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                model_revision=model_revision,
                dimensions=384,
            )
            for ordinal, chunk in enumerate(chunks)
        ])
        self.db.commit()

        response = self.post_index(version, embedding_vectors=expected_vectors)

        self.assertEqual(response.status_code, 409)
        self.assertIn("conflicts with the generated vector", response.json()["detail"])
        self.assertEqual(version.indexing_status, "approved")
        self.assertEqual(
            self.db.query(ScholarshipChunkEmbedding)
            .filter_by(document_version_id=version.id)
            .count(),
            2,
        )

    def test_exact_existing_chunks_are_reused(self):
        _, version = self.add_approved_document()
        chunks = self.mock_chunks(version.extracted_text)
        existing = self.add_existing_chunks(version, chunks)

        response = self.post_index(version)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["chunks_created"], 0)
        self.assertEqual(
            [row.id for row in self.db.query(ScholarshipDocumentChunk)
             .filter_by(document_version_id=version.id).order_by(ScholarshipDocumentChunk.chunk_ordinal)],
            [row.id for row in existing],
        )

    def test_incomplete_matching_chunks_are_completed_without_overwrite(self):
        _, version = self.add_approved_document()
        first_chunk = self.mock_chunks(version.extracted_text)[0]
        existing = self.add_existing_chunks(version, [first_chunk])[0]

        response = self.post_index(version)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["chunks_created"], 1)
        self.assertEqual(
            self.db.query(ScholarshipDocumentChunk).filter_by(document_version_id=version.id).count(),
            2,
        )
        self.assertEqual(self.db.get(ScholarshipDocumentChunk, existing.id).chunk_text, first_chunk.chunk_text)

    def test_inconsistent_immutable_chunk_is_rejected(self):
        _, version = self.add_approved_document()
        self.db.add(ScholarshipDocumentChunk(
            document_version_id=version.id,
            chunk_ordinal=0,
            chunk_text="Conflicting immutable text",
            chunk_hash=hashlib.sha256(b"Conflicting immutable text").hexdigest(),
            start_offset=0,
            end_offset=len("Conflicting immutable text"),
        ))
        self.db.commit()

        response = self.post_index(version)

        self.assertEqual(response.status_code, 409)
        self.assertIn("Existing document chunks conflict", response.json()["detail"])
        self.assertEqual(self.db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=version.id).count(), 0)
        self.assertEqual(version.indexing_status, "approved")

    def test_embedding_tied_to_obsolete_approval_is_rejected(self):
        _, version = self.add_approved_document()
        chunk = self.add_existing_chunks(version, self.mock_chunks(version.extracted_text)[:1])[0]
        old_approval = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        self.db.add(ScholarshipChunkEmbedding(
            chunk_id=chunk.id,
            document_version_id=version.id,
            approval_id=old_approval.id,
            embedding=self.unit_vector(),
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_revision="0123456789abcdef0123456789abcdef01234567",
            dimensions=384,
        ))
        self.db.commit()
        self.add_approval_event(version, "approved")

        response = self.post_index(version)

        self.assertEqual(response.status_code, 409)
        self.assertIn("obsolete approval", response.json()["detail"])
        self.assertEqual(version.indexing_status, "approved")

    def test_invalid_existing_embedding_vector_is_rejected(self):
        _, version = self.add_approved_document()
        chunk = self.add_existing_chunks(version, self.mock_chunks(version.extracted_text)[:1])[0]
        approval = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        self.db.add(ScholarshipChunkEmbedding(
            chunk_id=chunk.id,
            document_version_id=version.id,
            approval_id=approval.id,
            embedding=[0.0] * 384,
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_revision="0123456789abcdef0123456789abcdef01234567",
            dimensions=384,
        ))
        self.db.commit()

        response = self.post_index(version)

        self.assertEqual(response.status_code, 409)
        self.assertIn("vector is invalid", response.json()["detail"])

    def test_existing_embedding_dimension_and_value_validation_remains_strict(self):
        expected_vector = self.unit_vector()
        invalid_rows = (
            ("wrong dimensions metadata", 383, expected_vector),
            ("wrong vector length", 384, expected_vector[:-1]),
            ("non-finite value", 384, [float("nan")] + [0.0] * 383),
            ("non-normalized value", 384, [2.0] + [0.0] * 383),
        )
        for label, dimensions, vector in invalid_rows:
            with self.subTest(label=label):
                row = SimpleNamespace(
                    chunk_id=1,
                    approval_id=2,
                    model_name="sentence-transformers/all-MiniLM-L6-v2",
                    dimensions=dimensions,
                    embedding=vector,
                )
                with self.assertRaises(HTTPException):
                    admin_api._validate_stored_embedding(
                        row,
                        {1},
                        2,
                        "sentence-transformers/all-MiniLM-L6-v2",
                        expected_vector,
                    )

    def test_mismatched_embedding_rolls_back_new_chunks_and_status(self):
        _, version = self.add_approved_document()
        expected_chunks = self.mock_chunks(version.extracted_text)
        stored_chunk = self.add_existing_chunks(version, expected_chunks[:1])[0]
        approval = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        self.db.add(ScholarshipChunkEmbedding(
            chunk_id=stored_chunk.id,
            document_version_id=version.id,
            approval_id=approval.id,
            embedding=self.unit_vector(1),
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_revision="0123456789abcdef0123456789abcdef01234567",
            dimensions=384,
        ))
        self.db.commit()

        response = self.post_index(version)

        self.assertEqual(response.status_code, 409)
        self.assertIn("conflicts with the generated vector", response.json()["detail"])
        self.assertEqual(version.indexing_status, "approved")
        self.assertEqual(
            self.db.query(ScholarshipDocumentChunk)
            .filter_by(document_version_id=version.id)
            .count(),
            1,
        )
        self.assertEqual(
            self.db.query(ScholarshipChunkEmbedding)
            .filter_by(document_version_id=version.id)
            .count(),
            1,
        )
        self.assertEqual(
            self.db.query(ScholarshipAuditLog)
            .filter_by(scholarship_id=self.record.id, action="document_indexed")
            .count(),
            0,
        )

    def test_existing_embedding_with_unexpected_model_name_is_rejected(self):
        _, version = self.add_approved_document()
        chunk = self.add_existing_chunks(version, self.mock_chunks(version.extracted_text)[:1])[0]
        approval = (
            self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id.desc())
            .first()
        )
        existing = ScholarshipChunkEmbedding(
            chunk_id=chunk.id,
            document_version_id=version.id,
            approval_id=approval.id,
            embedding=self.unit_vector(),
            model_name="sentence-transformers/unexpected-model",
            model_revision="0123456789abcdef0123456789abcdef01234567",
            dimensions=384,
        )
        self.db.add(existing)
        self.db.commit()

        response = self.post_index(version)

        self.assertEqual(response.status_code, 409)
        self.assertIn("unsupported model", response.json()["detail"])
        self.assertEqual(
            self.db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=version.id).count(),
            1,
        )
        self.assertEqual(existing.model_name, "sentence-transformers/unexpected-model")
        self.assertEqual(version.indexing_status, "approved")

    def test_different_model_revision_gets_distinct_immutable_embeddings(self):
        _, version = self.add_approved_document()
        first_revision = "0123456789abcdef0123456789abcdef01234567"
        second_revision = "fedcba9876543210fedcba9876543210fedcba98"
        first = self.post_index(version, model_revision=first_revision)
        second = self.post_index(version, model_revision=second_revision)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["chunks_created"], 0)
        self.assertEqual(second.json()["embeddings_created"], 2)
        self.assertEqual(
            self.db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=version.id).count(),
            4,
        )

    def test_failure_after_partial_persistence_rolls_back_everything(self):
        _, version = self.add_approved_document()
        with patch.object(admin_api, "record_audit", side_effect=RuntimeError("audit failure")):
            with self.assertRaisesRegex(RuntimeError, "audit failure"):
                self.post_index(version)

        self.assertEqual(version.indexing_status, "approved")
        self.assertEqual(self.db.query(ScholarshipDocumentChunk).filter_by(document_version_id=version.id).count(), 0)
        self.assertEqual(self.db.query(ScholarshipChunkEmbedding).filter_by(document_version_id=version.id).count(), 0)
        self.assertEqual(
            self.db.query(ScholarshipAuditLog)
            .filter_by(scholarship_id=self.record.id, action="document_indexed")
            .count(),
            0,
        )

    def test_rejected_version_cannot_be_approved_later(self):
        _, version = self.add_document()
        rejected = self.post_review(version, decision="reject")
        approved = self.post_review(version, decision="approve")
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(approved.status_code, 409)
        self.assertEqual(version.review_status, "rejected")
        self.assertEqual(self.db.query(ScholarshipDocumentVersionApproval).count(), 0)

    def test_existing_approval_is_not_overwritten_or_duplicated(self):
        _, version = self.add_document()
        first = self.post_review(version)
        approval_id = first.json()["approval_event_id"]
        second = self.post_review(version)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(self.db.query(ScholarshipDocumentVersionApproval).count(), 1)
        self.assertIsNotNone(self.db.get(ScholarshipDocumentVersionApproval, approval_id))

    def test_rejecting_an_approved_version_uses_trigger_revocation(self):
        _, version = self.add_document()
        approved = self.post_review(version)
        rejected = self.post_review(version, decision="reject")
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(version.review_status, "rejected")
        decisions = [
            event.decision
            for event in self.db.query(ScholarshipDocumentVersionApproval)
            .filter_by(document_version_id=version.id)
            .order_by(ScholarshipDocumentVersionApproval.id)
        ]
        self.assertEqual(decisions, ["approved", "revoked"])

    def test_database_trigger_rejects_mismatched_approval_snapshots(self):
        approval_ddl = "\n".join(knowledge_model._APPROVAL_POSTGRES_DDL)
        self.assertIn(
            f"pg_advisory_xact_lock({admin_api.SCHOLARSHIP_KNOWLEDGE_WRITE_LOCK_ID})",
            approval_ddl,
        )
        _, version = self.add_document()
        version.review_status = "approved"
        version.indexing_status = "approved"
        self.db.flush()
        self.db.add(ScholarshipDocumentVersionApproval(
            document_version_id=version.id,
            decision="approved",
            verification_status_snapshot=version.verification_status_snapshot,
            verification_basis_snapshot=version.verification_basis_snapshot,
            review_status_snapshot="pending",
            indexing_status_snapshot=version.indexing_status,
            document_record_version_snapshot=version.scholarship_record_version_snapshot,
            source_active_at_decision=True,
            scholarship_record_version_at_decision=self.record.record_version,
            scholarship_verification_status_at_decision=self.record.verification_status,
            scholarship_verification_basis_at_decision=self.record.verification_basis,
            scholarship_archived_at_decision=self.record.archived_at,
            actor=self.admin.email,
            reason="Deliberately mismatched test snapshot",
        ))
        with self.assertRaises(IntegrityError):
            self.db.flush()
        self.db.rollback()
        self.assertEqual(self.db.query(ScholarshipDocumentVersionApproval).count(), 0)

    def test_source_checks_include_bounded_document_urls_and_redact_sensitive_parts(self):
        sensitive_url = "https://example.org/call?token=secret&lang=en#access_token=fragmentsecret"
        self.add_document(source_url=sensitive_url, content_hash="b" * 64)
        for index in range(20):
            self.add_document(
                source_url=f"https://example.org/document/{index}",
                content_hash=f"{index + 1:064x}",
            )
        self.record.source_checks = []
        self.db.commit()

        def healthy_check(url):
            return {
                "url": url,
                "status": "ok",
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }

        with patch("app.routers.admin_scholarships.check_url", side_effect=healthy_check) as check:
            with self.http_client(self.admin) as client:
                response = client.post(f"/admin/scholarships/{self.record.id}/source-check")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertLessEqual(check.call_count, admin_api.MAX_SOURCE_CHECKS_PER_REQUEST)
                self.assertEqual(
                    sum("source_document_id" in entry for entry in self.record.source_checks),
                    admin_api.MAX_DOCUMENT_SOURCE_CHECKS_PER_REQUEST,
                )
                check.reset_mock()
                response = client.post(f"/admin/scholarships/{self.record.id}/source-check")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertLessEqual(check.call_count, admin_api.MAX_SOURCE_CHECKS_PER_REQUEST)
        self.assertEqual(
            sum("source_document_id" in entry for entry in self.record.source_checks),
            admin_api.MAX_DOCUMENT_SOURCE_CHECKS_PER_REQUEST * 2,
        )
        returned_checks = response.json()["scholarship"]["source_checks"]
        returned_urls = {entry["url"] for entry in returned_checks}
        self.assertIn("https://example.org/call?lang=en", returned_urls)
        self.assertNotIn("secret", response.text)
        self.assertNotIn("fragmentsecret", response.text)
        self.assertNotIn("source_document_id", response.text)
        self.assertNotIn("content_hash", response.text)


class CreateTests(Base_):
    def create(self, **fields):
        return api.create_scholarship(ScholarshipCreate(**{"name": "New", "country": "France", **fields}), db=self.db, admin=self.admin)

    def test_new_records_are_never_verified(self):
        row = self.create()
        self.assertEqual(row["verification_status"], "unverified")
        self.assertEqual(row["record_version"], 1)

    def test_a_body_cant_verify(self):
        self.assertEqual(self.create(verification_status="verified", verification_basis="official_source")["verification_status"], "unverified")

    def test_unknown_stays_null(self):
        row = self.db.get(Scholarship, self.create()["id"])
        self.assertIsNone(row.min_age)
        self.assertIsNone(row.stipend_amount)
        self.assertIsNone(row.stipend_is_approximate)
        self.assertIsNone(row.gender_restriction)

    def test_creation_is_audited(self):
        row = self.create()
        entry = self.db.query(ScholarshipAuditLog).filter_by(scholarship_id=row["id"]).one()
        self.assertEqual((entry.action, entry.actor_email), ("created", "admin@example.com"))

    def test_validation(self):
        for bad in (dict(funding_level="maybe"), dict(official_info_url="not a url"), dict(min_gpa=3.0), dict(stipend_amount=100),
                    dict(min_age=30, max_age=20), dict(tuition_currency="XXX"), dict(min_percentage=140)):
            with self.assertRaises(ValidationError, msg=str(bad)):
                ScholarshipCreate(name="X", country="Y", **bad)
        with self.assertRaises(ValidationError):
            ScholarshipCreate(name="X")

    def test_host_university_must_exist(self):
        self.assert_refused(422, lambda: self.create(host_university_id=99999))

    def test_single_institution_needs_its_name(self):
        self.assert_refused(422, lambda: self.create(institution_scope="single_institution"))


class UpdateTests(Base_):
    def test_edit_reaches_eligibility(self):
        self.edit(min_gpa=3.5, min_gpa_scale=4.0, min_academic_requirement="Minimum CGPA 3.5/4.0")
        result = evaluate_scholarship(self.record, make_profile(cgpa=3.4), today=date(2026, 10, 29))
        self.assertEqual(result["status"], "not_eligible")

    def test_both_sides_changed_is_consistent(self):
        result = self.edit(min_gpa=3.5, min_gpa_scale=4.0, min_academic_requirement="Minimum CGPA 3.5/4.0")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(self.record.data_flags, [])

    def test_text_alone_is_held_for_review(self):
        result = self.edit(english_requirement="IELTS 7.5 overall")
        self.assertIn("review:english", self.record.data_flags)
        self.assertTrue(any("held for review" in item for item in result["warnings"]))
        self.assertEqual(self.record.min_ielts, 6.5)                # nothing is guessed from the text

    def test_structured_alone_is_held_for_review(self):
        self.edit(funding_level="partial")
        self.assertIn("review:funding", self.record.data_flags)

    def test_review_stops_a_firm_result_for_students(self):
        self.assertEqual(evaluate_scholarship(self.record, make_profile(), today=date(2026, 10, 29))["status"], "eligible")
        self.edit(age_requirement="Under 30")
        result = evaluate_scholarship(self.record, make_profile(), today=date(2026, 10, 29))
        self.assertEqual(result["status"], "not_evaluated")
        self.assertTrue(any(item["requirement"] == "record_review" for item in result["needs_verification"]))

    def test_admin_can_confirm_a_group(self):
        self.edit(age_requirement="Under 30")
        self.edit(reviewed_groups=["age"])
        self.assertNotIn("review:age", self.record.data_flags)

    def test_unknown_group(self):
        self.assert_refused(422, lambda: self.edit(reviewed_groups=["nonsense"]))

    def test_contradiction_is_reported(self):
        result = self.edit(min_academic_requirement="Minimum CGPA 3.5/4.0", min_percentage=None)
        self.assertTrue(any("Still conflicting" in item for item in result["warnings"]))

    def test_stale_form_is_refused(self):
        self.edit(provider="First", expected_version=1)
        self.assertEqual(self.record.record_version, 2)
        self.assert_refused(409, lambda: self.edit(provider="Second", expected_version=1))
        self.assertEqual(self.record.provider, "First")

    def test_two_loaded_forms_cannot_overwrite_each_other(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        engine = create_engine(f"sqlite:///{Path(directory.name) / 'versions.db'}")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(bind=engine)
        sessions = sessionmaker(bind=engine)
        first, second = sessions(), sessions()
        self.addCleanup(second.close)
        self.addCleanup(first.close)
        record = Scholarship(name="Concurrent Award", country="Germany", record_version=1)
        first.add(record)
        first.commit()
        stale_record = second.get(Scholarship, record.id)
        current_record = first.get(Scholarship, record.id)

        update_record(first, current_record, ScholarshipUpdate(provider="First", expected_version=1), self.admin)
        with self.assertRaises(HTTPException) as error:
            update_record(second, stale_record, ScholarshipUpdate(provider="Second", expected_version=1), self.admin)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(first.get(Scholarship, record.id).provider, "First")

    def test_unsent_fields_are_kept(self):
        self.edit(provider="New")
        self.assertEqual(self.record.min_ielts, 6.5)
        self.assertEqual(self.record.name, "Alpha Award")

    def test_no_change_isnt_recorded(self):
        version = self.record.record_version
        self.edit(provider=self.record.provider)
        self.assertEqual(self.record.record_version, version)
        self.assertEqual(self.db.query(ScholarshipAuditLog).count(), 0)

    def test_old_values_stay_in_the_audit(self):
        old = self.record.provider
        self.edit(provider="New", audit_note="Renamed")
        entry = self.db.query(ScholarshipAuditLog).one()
        self.assertEqual(entry.changes, {"provider": [old, "New"]})
        self.assertEqual(entry.note, "Renamed")

    def test_edit_cant_verify_or_change_evidence(self):
        self.record.verification_status = "unverified"
        self.db.commit()
        self.assert_refused(422, lambda: self.edit(verification_status="verified"))
        self.assert_refused(422, lambda: self.edit(verification_basis="mixed_sources"))
        self.assert_refused(422, lambda: self.edit(duplicate_of_id=self.other.id))

    def test_name_cant_be_emptied(self):
        self.assert_refused(422, lambda: self.edit(name=" "))

    def test_ids_never_change(self):
        record_id = self.record.id
        self.edit(provider="New")
        self.assertEqual(self.db.get(Scholarship, record_id).provider, "New")


class VerificationTests(Base_):
    def setUp(self):
        super().setUp()
        self.record.verification_status = "unverified"
        self.db.commit()

    def verify(self, **overrides):
        return admin_api.set_verification(verification(**overrides), scholarship_id=self.record.id, db=self.db, admin=self.admin)

    def test_verify(self):
        version = self.record.record_version
        self.verify()
        self.assertEqual((self.record.verification_status, self.record.verification_basis), ("verified", "official_source"))
        self.assertEqual(self.record.last_verified_date, date(2026, 10, 1))
        self.assertEqual(self.record.last_verified, "2026-10-01")
        self.assertEqual(self.record.record_version, version + 1)

    def test_repeating_the_same_verification_does_not_increment(self):
        self.verify()
        version = self.record.record_version
        audit_count = self.db.query(ScholarshipAuditLog).count()
        self.verify()
        self.assertEqual(self.record.record_version, version)
        self.assertEqual(self.db.query(ScholarshipAuditLog).count(), audit_count)

    def test_a_url_alone_doesnt_verify(self):
        self.assert_refused(422, lambda: self.verify(evidence_reviewed=False))
        self.assertEqual(self.record.verification_status, "unverified")

    def test_secondary_source_cant_verify(self):
        for basis in ("mixed_sources", "secondary_only", "not_verified"):
            self.assert_refused(422, lambda b=basis: self.verify(basis=b))

    def test_needs_source_and_date(self):
        self.assert_refused(422, lambda: self.verify(source_url=None))
        self.assert_refused(422, lambda: self.verify(verified_on=None))
        self.assert_refused(422, lambda: self.verify(verified_on=date.today() + timedelta(days=1)))

    def test_needs_notes_and_a_real_url(self):
        with self.assertRaises(ValidationError):
            verification(notes="ok")
        with self.assertRaises(ValidationError):
            verification(source_url="ftp://example.org")

    def test_conflict_must_be_acknowledged(self):
        self.record.min_academic_requirement = "Minimum CGPA 3.5/4.0"
        self.db.commit()
        self.assert_refused(409, self.verify)
        self.verify(acknowledge_conflicts=True)
        self.assertEqual(self.record.verification_status, "verified")

    def test_unverifying_keeps_the_history(self):
        self.verify()
        admin_api.set_verification(verification(status="unverified", basis="not_verified", source_url=None, verified_on=None, notes="The page has changed a lot."),
                                   scholarship_id=self.record.id, db=self.db, admin=self.admin)
        self.assertEqual(self.record.verification_status, "unverified")
        self.assertEqual(self.record.last_verified_date, date(2026, 10, 1))
        self.assertEqual(self.record.official_info_url, GOOD_INFO)
        self.assertEqual(self.db.query(ScholarshipAuditLog).filter_by(action="verification").count(), 2)

    def test_relationship_verification_is_separate(self):
        link = ScholarshipProgramLink(scholarship_id=self.record.id, program_id=self.program.id, outcome="potential", relationship_type="unconfirmed", verification_status="unverified")
        self.db.add(link)
        self.db.commit()
        self.verify()
        self.assertEqual(link.verification_status, "unverified")
        self.assertEqual(link.outcome, "potential")
        detail = self.detail()
        self.assertNotIn("relationships", detail)
        self.assertEqual(detail["references"]["internal_links"], 1)

    def test_flags(self):
        call = lambda **body: admin_api.set_flag(FlagWrite(**body), scholarship_id=self.record.id, db=self.db, admin=self.admin)  # noqa: E731
        original_version = self.record.record_version
        call(flag="outdated_source", active=True)
        self.assertEqual(self.record.record_version, original_version + 1)
        self.assertIn("outdated_source", self.record.data_flags)
        self.assertEqual(self.record.verification_status, "unverified")
        self.assertIn("outdated_source", [item["code"] for item in find_issues(self.record)])
        version = self.record.record_version
        audit_count = self.db.query(ScholarshipAuditLog).count()
        call(flag="outdated_source", active=True)
        self.assertEqual(self.record.record_version, version)
        self.assertEqual(self.db.query(ScholarshipAuditLog).count(), audit_count)
        call(flag="outdated_source", active=False)
        self.assertEqual(self.record.data_flags, [])
        self.assertEqual(self.record.record_version, version + 1)

    def test_source_checks_do_not_advance_the_content_version(self):
        version = self.record.record_version
        with patch(
            "app.routers.admin_scholarships.check_url",
            side_effect=lambda url: {
                "url": url,
                "status": "ok",
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        ):
            admin_api.check_sources(self.record.id, db=self.db, admin=self.admin)
        self.assertEqual(self.record.record_version, version)

class DuplicateTests(Base_):
    def setUp(self):
        super().setUp()
        self.copy = Scholarship(**{**FIELDS, "name": "Alpha Award", "country": self.record.country, "stipend_amount": 2000.0})
        self.far = Scholarship(**{**FIELDS, "name": "Alpha Award", "country": "Italy"})
        self.db.add_all([self.copy, self.far])
        self.db.commit()

    def mark(self, target, record=None):
        return admin_api.set_duplicate(DuplicateWrite(duplicate_of_id=target, note="Same call on both."), scholarship_id=(record or self.copy).id, db=self.db, admin=self.admin)

    def pairs(self):
        return duplicate_pairs(self.db.query(Scholarship).order_by(Scholarship.id).all())

    def test_suspected_needs_the_same_country(self):
        kinds = [(pair["first_id"], pair["second_id"], pair["kind"]) for pair in self.pairs()]
        self.assertEqual(kinds, [(self.record.id, self.copy.id, "suspected")])

    def test_flagged_pairs_are_listed(self):
        self.mark(self.record.id)
        self.assertEqual(self.pairs()[0]["kind"], "flagged")

    def test_compare_keeps_differences(self):
        result = admin_api.compare_duplicates(self.record.id, self.copy.id, db=self.db)
        fields = {item["field"]: item for item in result["differences"]}
        self.assertEqual(fields["stipend_amount"]["second"], 2000.0)
        self.assertNotIn("id", fields)

    def test_marking_changes_nothing_else(self):
        self.mark(self.record.id)
        self.assertIsNotNone(self.db.get(Scholarship, self.copy.id))
        self.assertEqual(self.copy.stipend_amount, 2000.0)

    def test_duplicate_change_versions_once_and_repeating_it_is_a_noop(self):
        original_version = self.copy.record_version
        self.mark(self.record.id)
        self.assertEqual(self.copy.record_version, original_version + 1)
        audit_count = self.db.query(ScholarshipAuditLog).count()
        self.mark(self.record.id)
        self.assertEqual(self.copy.record_version, original_version + 1)
        self.assertEqual(self.db.query(ScholarshipAuditLog).count(), audit_count)

    def test_bad_targets(self):
        self.assert_refused(422, lambda: self.mark(self.copy.id))
        self.assert_refused(404, lambda: self.mark(99999))
        self.mark(self.record.id)
        self.assert_refused(422, lambda: self.mark(self.copy.id, self.far))

    def test_same_record_cant_be_compared(self):
        self.assert_refused(422, lambda: admin_api.compare_duplicates(self.record.id, self.record.id, db=self.db))


class QualityTests(Base_):
    def codes(self, **overrides):
        record = self.record
        for key, value in overrides.items():
            setattr(record, key, value)
        return [item["code"] for item in find_issues(record, today=date(2026, 11, 1))]

    def test_clean_record(self):
        self.assertEqual(self.codes(), [])

    def test_checks(self):
        cases = (("missing_official_source", dict(official_info_url=None)), ("missing_application_url", dict(official_application_url=None)),
                 ("missing_deadline", dict(deadline_type="not_specified")), ("missing_funding", dict(stipend_status="not_specified")),
                 ("missing_eligibility", dict(english_requirement_type=None)), ("unverified", dict(verification_status="unverified")),
                 ("stale_verification", dict(last_verified_date=date(2025, 1, 1))), ("never_verified", dict(last_verified_date=None)),
                 ("no_structured_data", dict(structured_data_version=None)), ("duplicate", dict(duplicate_of_id=self.other.id)),
                 ("weak_evidence", dict(verification_basis="mixed_sources")))
        for code, change in cases:
            saved = {key: getattr(self.record, key) for key in change}
            self.assertIn(code, self.codes(**change), code)
            for key, value in saved.items():
                setattr(self.record, key, value)

    def test_url_is_broken_only_when_checked(self):
        self.assertNotIn("broken_url", self.codes())
        self.assertIn("broken_url", self.codes(source_checks=[{"url": GOOD_INFO, "status": "broken", "http_status": 404}]))
        self.assertNotIn("broken_url", self.codes(source_checks=[{"url": GOOD_INFO, "status": "inconclusive", "http_status": 403}]))

    def test_funding_contradiction(self):
        self.record.funding_type = "Partially Funded"
        self.assertTrue(any("Funding" in item for item in find_conflicts(self.record)))

    def test_deadline_contradiction(self):
        self.record.deadline = "1 March 2027"
        self.assertTrue(any("Deadline" in item for item in find_conflicts(self.record)))

    def test_summary(self):
        result = admin_api.summary(db=self.db)
        self.assertEqual((result["total"], result["verified"], result["archived"]), (2, 2, 0))
        self.assertEqual(result["sources_checked"], 0)

    def test_list_filters(self):
        self.other.last_verified_date = None
        self.db.commit()
        self.assertEqual(admin_api.list_records(q="beta", verification=None, issue=None, archived=False, skip=0, limit=25, db=self.db)["total"], 1)
        self.assertEqual(admin_api.list_records(q=None, verification="unverified", issue=None, archived=False, skip=0, limit=25, db=self.db)["total"], 0)
        self.assertEqual(admin_api.list_records(q=None, verification=None, issue="never_verified", archived=False, skip=0, limit=25, db=self.db)["items"][0]["name"], "Beta Award")


class SourceCheckTests(unittest.TestCase):
    class FakeSocket:
        def __init__(self, peer):
            self.peer = peer
            self.closed = False

        def getpeername(self):
            return self.peer

        def close(self):
            self.closed = True

    class Response:
        def __init__(self, status=200, location=None, body=b"", content_length=None, fail_read=False):
            from io import BytesIO

            self.status = status
            self.location = location
            self.content_length = content_length
            self.body = BytesIO(body)
            self.fail_read = fail_read

        def getheader(self, name):
            if name.casefold() == "location":
                return self.location
            if name.casefold() == "content-length":
                return self.content_length
            return None

        def read(self, limit):
            if self.fail_read:
                raise AssertionError("response body should not be read")
            return self.body.read(limit)

    class FakeDNSResolver:
        def __init__(self, records=None, errors=None, on_resolve=None):
            self.records = records or {}
            self.errors = errors or {}
            self.on_resolve = on_resolve
            self.calls = []

        def resolve(self, host, rdtype, *, lifetime, search):
            record_type = dns.rdatatype.to_text(rdtype)
            self.calls.append((host, record_type, lifetime, search))
            if self.on_resolve is not None:
                self.on_resolve(host, record_type, lifetime, search)
            error = self.errors.get((host, record_type), self.errors.get(record_type))
            if error is not None:
                raise error
            records = self.records.get((host, record_type), self.records.get(record_type, ()))
            if not records:
                raise dns.resolver.NoAnswer()
            return [SimpleNamespace(address=address) for address in records]

    def run_check(self, fetch, allowed=lambda host: True, url="https://example.org/a"):
        return check_url(url, fetch=fetch, host_allowed=allowed)

    @staticmethod
    def address_info(ip_text, port, scope_id=0):
        ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
        if ip.version == 4:
            sockaddr = (ip_text, port)
            family = socket.AF_INET
        else:
            sockaddr = (ip_text, port, 0, scope_id)
            family = socket.AF_INET6
        return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr

    def perform_request(self, url, resolver, connector, responses):
        with (
            patch.object(http.client.HTTPConnection, "putrequest"),
            patch.object(http.client.HTTPConnection, "putheader") as putheader,
            patch.object(http.client.HTTPConnection, "endheaders"),
            patch.object(http.client.HTTPConnection, "getresponse", side_effect=responses),
        ):
            result = _request(url, resolver=resolver, connector=connector)
        return result, putheader.call_args_list

    def test_results(self):
        self.assertEqual(self.run_check(lambda url: (200, None))["status"], "ok")
        self.assertEqual(self.run_check(lambda url: (404, None))["status"], "broken")
        self.assertEqual(self.run_check(lambda url: (410, None))["status"], "broken")

    def test_a_and_aaaa_answers_are_both_resolved_and_validated(self):
        resolver = self.FakeDNSResolver({
            "A": ["93.184.216.34"],
            "AAAA": ["2001:4860:4860::8888"],
        })

        addresses = _resolve_public_addresses("example.org", 443, resolver=resolver)

        self.assertEqual(
            addresses,
            [
                self.address_info("93.184.216.34", 443),
                self.address_info("2001:4860:4860::8888", 443),
            ],
        )
        self.assertEqual(
            [(record_type, search) for _host, record_type, _lifetime, search in resolver.calls],
            [("A", True), ("AAAA", True)],
        )

    def test_public_ip_literal_is_validated_without_dns(self):
        resolver = self.FakeDNSResolver()

        addresses = _resolve_public_addresses("93.184.216.34", 80, resolver=resolver)

        self.assertEqual(addresses, [self.address_info("93.184.216.34", 80)])
        self.assertEqual(resolver.calls, [])

    def test_a_and_aaaa_use_one_shared_monotonic_deadline(self):
        now = [100.0]

        def clock():
            return now[0]

        def advance_after_a(_host, record_type, _lifetime, _search):
            if record_type == "A":
                now[0] += 2

        resolver = self.FakeDNSResolver(
            {"A": ["93.184.216.34"]},
            on_resolve=advance_after_a,
        )

        _resolve_public_addresses("example.org", 443, resolver=resolver, clock=clock)

        lifetimes = [lifetime for _host, _type, lifetime, _search in resolver.calls]
        self.assertEqual(lifetimes, [DNS_TIMEOUT_SECONDS, DNS_TIMEOUT_SECONDS - 2])

    def test_timeout_prevents_connection(self):
        resolver = self.FakeDNSResolver(
            errors={"A": dns.exception.Timeout("DNS query timed out")}
        )
        connector = Mock()
        result = check_url(
            "https://example.org/a",
            fetch=lambda url: _request(url, resolver=resolver, connector=connector),
            host_allowed=lambda _host: True,
        )

        self.assertEqual(result["status"], "inconclusive")
        connector.assert_not_called()

    def test_unsupported_system_resolver_configuration_is_inconclusive_without_connecting(self):
        with (
            patch("app.services.source_check.dns.resolver.Resolver",
                  side_effect=NotImplementedError("unsupported resolver configuration")) as resolver_factory,
            patch("app.services.source_check._connect_validated_address") as connector,
            patch.object(http.client, "HTTPConnection") as http_connection,
            patch("app.services.source_check.socket.getaddrinfo") as getaddrinfo,
        ):
            result = check_url("http://example.org/a")

        resolver_factory.assert_called_once_with(configure=True)
        connector.assert_not_called()
        http_connection.assert_not_called()
        getaddrinfo.assert_not_called()
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["detail"], "No answer: OSError")
        self.assertIsNone(result["http_status"])
        self.assertIsNone(result["content_hash"])

    def test_unsupported_system_resolver_configuration_is_not_a_public_host(self):
        with patch("app.services.source_check.dns.resolver.Resolver", side_effect=NotImplementedError):
            self.assertFalse(is_public_host("example.org"))

    def test_not_implemented_during_dns_query_is_not_hidden(self):
        resolver = self.FakeDNSResolver(errors={"A": NotImplementedError("unexpected query failure")})
        with self.assertRaises(NotImplementedError):
            _resolve_public_addresses("example.org", 443, resolver=resolver)

    def test_resolution_errors_and_empty_answers_fail_closed(self):
        failed_resolver = self.FakeDNSResolver(
            errors={"A": dns.exception.DNSException("resolver failed")}
        )
        empty_resolver = self.FakeDNSResolver()

        for resolver in (failed_resolver, empty_resolver):
            with self.subTest(resolver=resolver):
                with self.assertRaises(OSError):
                    _resolve_public_addresses("example.org", 443, resolver=resolver)

    def test_malformed_dns_answer_fails_closed(self):
        resolver = self.FakeDNSResolver({"A": ["not-an-ip-address"]})

        with self.assertRaises(OSError):
            _resolve_public_addresses("example.org", 443, resolver=resolver)

    def test_default_resolution_never_falls_back_to_getaddrinfo(self):
        resolver = self.FakeDNSResolver({"A": ["93.184.216.34"]})
        connector = Mock(side_effect=lambda _family, _type, _proto, sockaddr, _timeout: self.FakeSocket(sockaddr))
        with (
            patch("app.services.source_check.dns.resolver.Resolver", return_value=resolver) as resolver_factory,
            patch("app.services.source_check.socket.getaddrinfo", side_effect=AssertionError("unbounded resolver called")),
        ):
            self.perform_request("http://example.org/a", None, connector, [self.Response()])

        resolver_factory.assert_called_once_with(configure=True)

    def test_response_body_hash_is_available_for_version_comparison(self):
        body = b"current source bytes"
        resolver = self.FakeDNSResolver({"A": ["93.184.216.34"]})
        connector = Mock(side_effect=lambda _family, _type, _proto, sockaddr, _timeout: self.FakeSocket(sockaddr))
        with (
            patch.object(http.client.HTTPConnection, "putrequest"),
            patch.object(http.client.HTTPConnection, "putheader"),
            patch.object(http.client.HTTPConnection, "endheaders"),
            patch.object(
                http.client.HTTPConnection,
                "getresponse",
                return_value=self.Response(body=body, content_length=str(len(body))),
            ),
        ):
            result = check_url(
                "http://example.org/a",
                fetch=lambda url: _request(url, resolver=resolver, connector=connector),
                host_allowed=lambda _host: True,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["content_hash"], hashlib.sha256(body).hexdigest())

    def test_oversized_response_has_no_content_hash(self):
        resolver = self.FakeDNSResolver({"A": ["93.184.216.34"]})
        with (
            patch.object(http.client.HTTPConnection, "putrequest"),
            patch.object(http.client.HTTPConnection, "putheader"),
            patch.object(http.client.HTTPConnection, "endheaders"),
            patch.object(
                http.client.HTTPConnection,
                "getresponse",
                return_value=self.Response(content_length=str(MAX_CONTENT_HASH_BYTES + 1), fail_read=True),
            ),
        ):
            result = check_url(
                "http://example.org/a",
                fetch=lambda url: _request(
                    url,
                    resolver=resolver,
                    connector=lambda _family, _type, _proto, sockaddr, _timeout: self.FakeSocket(sockaddr),
                ),
                host_allowed=lambda _host: True,
            )

        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["content_hash"])

    def test_refusals_arent_called_broken(self):
        for code in (403, 429, 500, 503):
            self.assertEqual(self.run_check(lambda url, c=code: (c, None))["status"], "inconclusive", code)

    def test_no_answer_isnt_broken(self):
        def fail(url):
            raise urllib.error.URLError("timed out")
        self.assertEqual(self.run_check(fail)["status"], "inconclusive")

    def test_private_addresses_are_never_requested(self):
        called = []
        result = self.run_check(lambda url: called.append(url) or (200, None), allowed=lambda host: False, url="http://localhost/")
        self.assertEqual((result["status"], called), ("inconclusive", []))

    def test_credential_bearing_and_malformed_urls_are_never_requested(self):
        called = []
        for url in (
            "https://user:password@example.org/document",
            "https://[malformed",
        ):
            result = self.run_check(lambda value: called.append(value) or (200, None), url=url)
            self.assertEqual(result["status"], "invalid")
        self.assertEqual(called, [])

    def test_redirect_to_credential_bearing_url_is_not_followed(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return 302, "https://user:password@example.org/document"

        result = self.run_check(fetch)

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(len(calls), 1)

    def test_redirect_to_a_private_address_stops(self):
        result = self.run_check(lambda url: (302, "http://10.0.0.1/"), allowed=lambda host: host != "10.0.0.1")
        self.assertEqual(result["status"], "inconclusive")

    def test_redirect_loop_stops(self):
        self.assertEqual(self.run_check(lambda url: (302, "/again"))["status"], "inconclusive")

    def test_other_schemes(self):
        self.assertEqual(self.run_check(lambda url: (200, None), url="file:///etc/passwd")["status"], "invalid")

    def test_pinned_public_answer_is_the_connected_peer(self):
        resolver = self.FakeDNSResolver({"A": ["93.184.216.34"]})
        connector = Mock(side_effect=lambda _family, _type, _proto, sockaddr, _timeout: self.FakeSocket(sockaddr))

        self.perform_request("http://example.org/a", resolver, connector, [self.Response()])

        self.assertEqual(
            [(host, record_type) for host, record_type, _lifetime, _search in resolver.calls],
            [("example.org", "A"), ("example.org", "AAAA")],
        )
        connector.assert_called_once_with(
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            ("93.184.216.34", 80),
            TIMEOUT_SECONDS,
        )

    def test_request_does_not_resolve_the_hostname_again_during_connection(self):
        resolver = self.FakeDNSResolver({"A": ["93.184.216.34"]})
        connector = Mock(side_effect=lambda _family, _type, _proto, sockaddr, _timeout: self.FakeSocket(sockaddr))

        self.perform_request("http://example.org/a", resolver, connector, [self.Response()])

        self.assertEqual([host for host, *_ in resolver.calls], ["example.org", "example.org"])

    def test_mismatched_connected_peer_is_rejected(self):
        address = self.address_info("93.184.216.34", 443)
        resolver = self.FakeDNSResolver({"A": ["93.184.216.34"]})
        wrong_peer = self.FakeSocket(("1.1.1.1", 443))
        connector = Mock(return_value=wrong_peer)

        with self.assertRaises(OSError):
            self.perform_request(
                "https://example.org/a",
                resolver,
                connector,
                [self.Response()],
            )
        self.assertTrue(wrong_peer.closed)

    def test_https_uses_hostname_for_tls_and_default_verification(self):
        address = self.address_info("93.184.216.34", 443)
        resolver = self.FakeDNSResolver({"A": ["93.184.216.34"]})
        raw_socket = self.FakeSocket(address[4])
        tls_socket = self.FakeSocket(address[4])
        context = Mock()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.wrap_socket.return_value = tls_socket
        with (
            patch("app.services.source_check.ssl.create_default_context", return_value=context) as context_factory,
            patch.object(http.client.HTTPConnection, "putrequest"),
            patch.object(http.client.HTTPConnection, "putheader") as putheader,
            patch.object(http.client.HTTPConnection, "endheaders"),
            patch.object(http.client.HTTPConnection, "getresponse", return_value=self.Response()),
        ):
            _request(
                "https://example.org/a",
                resolver=resolver,
                connector=lambda _family, _type, _proto, _sockaddr, _timeout: raw_socket,
            )

        context_factory.assert_called_once_with()
        context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="example.org")
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertIn(unittest.mock.call("Host", "example.org"), putheader.call_args_list)

    def test_each_redirect_is_resolved_and_pinned_independently(self):
        first = self.address_info("93.184.216.34", 80)
        second = self.address_info("1.1.1.1", 80)
        resolver = self.FakeDNSResolver({
            ("example.org", "A"): ["93.184.216.34"],
            ("next.example", "A"): ["1.1.1.1"],
        })
        connected_addresses = []

        def connector(_family, _type, _proto, sockaddr, _timeout):
            connected_addresses.append(sockaddr)
            return self.FakeSocket(sockaddr)

        with (
            patch.object(http.client.HTTPConnection, "putrequest"),
            patch.object(http.client.HTTPConnection, "putheader"),
            patch.object(http.client.HTTPConnection, "endheaders"),
            patch.object(
                http.client.HTTPConnection,
                "getresponse",
                side_effect=[
                    self.Response(status=302, location="http://next.example/b"),
                    self.Response(status=200),
                ],
            ),
        ):
            result = check_url(
                "http://example.org/a",
                fetch=lambda url: _request(url, resolver=resolver, connector=connector),
                host_allowed=lambda _host: True,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [(host, record_type) for host, record_type, _lifetime, _search in resolver.calls],
            [
                ("example.org", "A"),
                ("example.org", "AAAA"),
                ("next.example", "A"),
                ("next.example", "AAAA"),
            ],
        )
        self.assertEqual(connected_addresses, [first[4], second[4]])

    def test_environment_proxy_settings_are_not_used(self):
        address = self.address_info("93.184.216.34", 80)
        resolver = self.FakeDNSResolver({"A": ["93.184.216.34"]})
        connector = Mock(side_effect=lambda _family, _type, _proto, sockaddr, _timeout: self.FakeSocket(sockaddr))
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://127.0.0.1:8123",
                "HTTPS_PROXY": "http://127.0.0.1:8123",
                "http_proxy": "http://127.0.0.1:8123",
                "https_proxy": "http://127.0.0.1:8123",
            },
        ):
            self.perform_request(
                "http://example.org/a",
                resolver,
                connector,
                [self.Response()],
            )

        connector.assert_called_once_with(
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            address[4],
            TIMEOUT_SECONDS,
        )

    def test_standard_ports_are_accepted(self):
        fetch = Mock(return_value=(200, None))
        for url in (
            "http://example.org/a",
            "http://example.org:80/a",
            "https://example.org/a",
            "https://example.org:443/a",
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    check_url(url, fetch=fetch, host_allowed=lambda _host: True)["status"],
                    "ok",
                )
        self.assertEqual(fetch.call_count, 4)

    def test_nonstandard_and_scheme_mismatched_ports_are_rejected(self):
        fetch = Mock(return_value=(200, None))
        for url in (
            "http://example.org:8080/a",
            "http://example.org:443/a",
            "https://example.org:80/a",
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    check_url(url, fetch=fetch, host_allowed=lambda _host: True)["status"],
                    "invalid",
                )
        fetch.assert_not_called()

    def test_special_ipv4_and_ipv6_addresses_are_rejected(self):
        unsafe_addresses = (
            "10.0.0.1",
            "127.0.0.1",
            "169.254.1.1",
            "192.0.2.1",
            "224.0.0.1",
            "0.0.0.0",
            "::",
            "::1",
            "fe80::1",
            "ff02::1",
            "2001:db8::1",
        )
        for ip_text in unsafe_addresses:
            with self.subTest(address=ip_text):
                ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
                record_type = "A" if ip.version == 4 else "AAAA"
                resolver = self.FakeDNSResolver({record_type: [ip_text]})
                self.assertFalse(is_public_host("example.org", resolver=resolver))

    def test_ipv4_mapped_ipv6_is_rejected(self):
        resolver = self.FakeDNSResolver({"AAAA": ["::ffff:8.8.8.8"]})
        self.assertFalse(is_public_host("example.org", resolver=resolver))

    def test_scoped_ipv6_is_rejected(self):
        resolver = self.FakeDNSResolver({"AAAA": ["2001:4860:4860::8888%3"]})
        self.assertFalse(is_public_host("example.org", resolver=resolver))

    def test_mixed_public_and_private_answers_are_rejected(self):
        resolver = self.FakeDNSResolver({
            "A": ["93.184.216.34"],
            "AAAA": ["fd00::1"],
        })
        self.assertFalse(is_public_host("example.org", resolver=resolver))
        connector = Mock()
        with self.assertRaises(OSError):
            self.perform_request(
                "https://example.org/a",
                resolver,
                connector,
                [self.Response()],
            )
        connector.assert_not_called()

    def test_source_check_response_shape_remains_compatible(self):
        result = self.run_check(lambda url: (200, None))

        self.assertEqual(
            set(result),
            {"url", "status", "http_status", "detail", "checked_at", "content_hash"},
        )
        self.assertEqual(result["url"], "https://example.org/a")
        self.assertEqual(result["http_status"], 200)


class ArchiveAndDeleteTests(Base_):
    def setUp(self):
        super().setUp()
        self.db.add(StudentProfile(user_id=self.student.id, nationality="Pakistan", degree_level="Bachelor's", cgpa=3.4, cgpa_scale=4.0, ielts_score=7.0))
        self.db.commit()

    def archive(self):
        return admin_api.archive(ArchiveWrite(reason="Programme has ended."), scholarship_id=self.record.id, db=self.db, admin=self.admin)

    def save(self):
        self.db.add(SavedScholarship(user_id=self.student.id, scholarship_id=self.record.id))
        self.db.commit()

    def listed(self):
        rows = api.list_scholarships(country=None, funding_type=None, degree_level=None, pakistan_eligible_only=False, include_unverified=True,
                                     search=None, skip=0, limit=100, db=self.db)
        return [row.name for row in rows]

    def test_archived_leaves_every_listing(self):
        self.archive()
        self.assertNotIn("Alpha Award", self.listed())
        self.assertNotIn("Alpha Award", [r["scholarship_name"] for r in eligibility_api.check_all_scholarships(eligible_only=False, include_unverified=True, db=self.db, current_user=self.student)])
        names = recommendations_api.scholarship_recommendations(include_unverified=True, db=self.db, current_user=self.student)
        self.assertNotIn("Alpha Award", [r["scholarship_name"] for r in names["recommendations"] + names["excluded"]])
        self.assertNotIn("Alpha Award", [i["scholarship"].name for i in search_scholarships(self.db, {}, None, False)["items"]])

    def test_archive_keeps_references(self):
        self.save()
        self.archive()
        saved = saved_api.list_saved_scholarships(db=self.db, current_user=self.student)
        self.assertEqual([row.scholarship.name for row in saved], ["Alpha Award"])
        self.assertTrue(saved[0].scholarship.archived)

    def test_single_record_stays_readable(self):
        self.archive()
        self.assertEqual(api.get_scholarship(self.record.id, db=self.db).name, "Alpha Award")

    def test_restore(self):
        original_version = self.record.record_version
        self.archive()
        self.assertEqual(self.record.record_version, original_version + 1)
        admin_api.restore(scholarship_id=self.record.id, db=self.db, admin=self.admin)
        self.assertEqual(self.record.record_version, original_version + 2)
        self.assertIn("Alpha Award", self.listed())
        self.assertEqual([item.action for item in self.db.query(ScholarshipAuditLog)], ["archived", "restored"])

    def test_double_archive(self):
        self.archive()
        self.assert_refused(409, self.archive)
        self.assert_refused(409, lambda: admin_api.restore(scholarship_id=self.other.id, db=self.db, admin=self.admin))

    def test_delete_is_refused_while_in_use(self):
        self.save()
        self.assert_refused(409, lambda: api.delete_scholarship(self.record.id, db=self.db, admin=self.admin))
        self.assertIsNotNone(self.db.get(Scholarship, self.record.id))
        self.assertEqual(self.db.query(SavedScholarship).count(), 1)

    def test_link_blocks_delete(self):
        self.db.add(ScholarshipProgramLink(scholarship_id=self.record.id, program_id=self.program.id, outcome="potential", relationship_type="unconfirmed", verification_status="unverified"))
        self.db.commit()
        self.assert_refused(409, lambda: api.delete_scholarship(self.record.id, db=self.db, admin=self.admin))

    def test_unused_record_can_go_and_leaves_a_trace(self):
        record_id = self.other.id
        api.delete_scholarship(record_id, db=self.db, admin=self.admin)
        self.assertIsNone(self.db.get(Scholarship, record_id))
        self.assertEqual(self.db.query(ScholarshipAuditLog).filter_by(scholarship_id=record_id).one().action, "deleted")

    def test_admin_sees_counts_not_students(self):
        self.save()
        detail = self.detail()
        self.assertEqual(detail["references"]["saved_by_students"], 1)
        self.assertNotIn("student@example.com", str(detail))

    def test_audit_never_names_students(self):
        self.save()
        self.archive()
        self.assertEqual({item.actor_email for item in self.db.query(ScholarshipAuditLog)}, {"admin@example.com"})


if __name__ == "__main__":
    unittest.main()
