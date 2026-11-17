"""Student scholarship visibility across canonical records and published discoveries."""
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.opportunity import Scholarship, ScholarshipAuditLog
from app.models.scholarship_discovery_publication import (
    ScholarshipDiscoveryPublication,
    ScholarshipDiscoveryPublicationSource,
)
from app.models.user import StudentProfile, User
from app.routers import eligibility, recommendations, scholarships
from app.services.scholarship_search import search_scholarships
from app.services.student_scholarship_visibility import (
    PUBLICATION_TABLES,
    get_student_scholarships,
)
from app.services import student_scholarship_visibility
from test_scholarship_eligibility import make_scholarship


DISCOVERY_ACTOR = "system:scholarship-discovery"


class StudentScholarshipVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(
            email="student@example.com",
            hashed_password="test-hash",
            full_name="Student",
        )
        self.db.add(self.user)
        self.db.flush()
        self.profile = StudentProfile(
            user_id=self.user.id,
            nationality="Pakistan",
            degree_level="Bachelor's",
            cgpa=3.4,
            cgpa_scale=4.0,
            ielts_score=7.0,
            field_of_study="Computer Science",
            preferred_countries="Germany",
        )
        self.db.add(self.profile)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_scholarship(self, name, verification_status="unverified", discovery_created=False):
        fields = vars(make_scholarship()).copy()
        fields.pop("id")
        fields.update(
            name=name,
            verification_status=verification_status,
            last_verified_date=date.today() if verification_status == "verified" else None,
            last_verified=date.today().isoformat() if verification_status == "verified" else None,
        )
        scholarship = Scholarship(**fields)
        self.db.add(scholarship)
        self.db.flush()
        if discovery_created:
            self.db.add(ScholarshipAuditLog(
                scholarship_id=scholarship.id,
                action="discovery_created",
                actor_email=DISCOVERY_ACTOR,
            ))
        self.db.commit()
        return scholarship

    def add_publication(self, scholarship, status="published", add_source=True):
        publication = ScholarshipDiscoveryPublication(
            canonical_scholarship_id=scholarship.id,
            status=status,
        )
        self.db.add(publication)
        self.db.flush()
        if add_source:
            self.db.add(ScholarshipDiscoveryPublicationSource(
                publication_id=publication.id,
                source_id="test-source",
                source_name="Official Test Source",
                source_classification="official_provider",
                source_url="https://example.org/scholarship",
                normalized_url="https://example.org/scholarship",
                last_checked_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                last_successful_check_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                source_check_status="succeeded",
            ))
        self.db.commit()
        return publication

    @staticmethod
    def list_records(db, include_unverified=False):
        return scholarships.list_scholarships(
            country=None,
            funding_type=None,
            degree_level=None,
            pakistan_eligible_only=False,
            include_unverified=include_unverified,
            search=None,
            skip=0,
            limit=100,
            db=db,
        )

    def test_published_discovery_is_in_default_list_and_has_source_provenance(self):
        candidate = self.add_scholarship("Published", discovery_created=True)
        self.add_publication(candidate)

        result = next(item for item in self.list_records(self.db) if item["id"] == candidate.id)

        self.assertEqual(result["verification_status"], "unverified")
        self.assertEqual(result["source_provenance"]["sources"], ["database", "live_discovery"])
        self.assertEqual(
            result["source_provenance"]["discovery_sources"][0]["source_url"],
            "https://example.org/scholarship",
        )
        self.assertEqual(
            result["source_provenance"]["publication_last_checked_at"],
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

    def test_unpublished_discovery_stays_hidden_even_with_unverified_opt_in(self):
        candidate = self.add_scholarship("Pending", discovery_created=True)

        self.assertNotIn(candidate.id, {item["id"] for item in self.list_records(self.db)})
        self.assertNotIn(
            candidate.id,
            {item["id"] for item in self.list_records(self.db, include_unverified=True)},
        )
        self.assertNotIn(
            candidate.id,
            {record.scholarship.id for record in get_student_scholarships(
                self.db,
                include_unverified=True,
            )},
        )

    def test_non_published_lifecycle_states_hide_unverified_discovery(self):
        for status in ("expired", "withdrawn", "revoked", "superseded"):
            with self.subTest(status=status):
                candidate = self.add_scholarship(status, discovery_created=True)
                self.add_publication(candidate, status=status)
                visible_ids = {
                    item["id"] for item in self.list_records(self.db, include_unverified=True)
                }
                self.assertNotIn(candidate.id, visible_ids)

    def test_independently_verified_discovery_remains_visible_after_publication_revocation(self):
        candidate = self.add_scholarship("Verified", "verified", discovery_created=True)
        self.add_publication(candidate, status="revoked")

        result = next(item for item in self.list_records(self.db) if item["id"] == candidate.id)
        self.assertEqual(result["verification_status"], "verified")
        self.assertEqual(result["source_provenance"]["sources"], ["database"])

    def test_revoked_linked_unverified_scholarship_stays_hidden_with_opt_in(self):
        linked = self.add_scholarship("Revoked Linked")
        self.add_publication(linked, status="revoked")

        self.assertNotIn(
            linked.id,
            {item["id"] for item in self.list_records(self.db, include_unverified=True)},
        )

    def test_ordinary_unverified_records_keep_the_existing_opt_in(self):
        ordinary = self.add_scholarship("Ordinary")

        self.assertNotIn(ordinary.id, {item["id"] for item in self.list_records(self.db)})
        self.assertIn(
            ordinary.id,
            {item["id"] for item in self.list_records(self.db, include_unverified=True)},
        )

    def test_publication_is_in_default_search_but_not_the_verified_filter(self):
        candidate = self.add_scholarship("Published Search", discovery_created=True)
        self.add_publication(candidate)

        default = search_scholarships(
            self.db, {}, None, False, today=date.today(),
        )
        verified = search_scholarships(
            self.db, {"verification": ["verified"]}, None, False, today=date.today(),
        )
        unverified = search_scholarships(
            self.db, {"verification": ["unverified"]}, None, False, today=date.today(),
        )

        self.assertEqual(default["items"][0]["scholarship"]["verification_status"], "unverified")
        self.assertEqual(default["items"][0]["scholarship"]["source_provenance"]["sources"],
                         ["database", "live_discovery"])
        self.assertEqual(verified["items"], [])
        self.assertEqual(unverified["total"], 1)

    def test_recommendations_include_publications_as_needs_verification(self):
        candidate = self.add_scholarship("Published Recommendation", discovery_created=True)
        self.add_publication(candidate)

        result = recommendations.scholarship_recommendations(
            include_unverified=False,
            db=self.db,
            current_user=self.user,
        )

        item = next(item for item in result["recommendations"] if item["scholarship_id"] == candidate.id)
        self.assertFalse(item["recommended"])
        self.assertEqual(item["category"], "needs_verification")
        self.assertEqual(item["verification_status"], "unverified")
        self.assertEqual(item["source_provenance"]["sources"], ["database", "live_discovery"])

    def test_direct_student_endpoints_hide_unpublished_discoveries(self):
        candidate = self.add_scholarship("Hidden Detail", discovery_created=True)

        for endpoint in (
            lambda: scholarships.get_scholarship(candidate.id, db=self.db),
            lambda: recommendations.scholarship_recommendation(
                candidate.id, db=self.db, current_user=self.user,
            ),
            lambda: eligibility.check_one_scholarship(
                candidate.id, db=self.db, current_user=self.user,
            ),
            lambda: eligibility.profile_improvements(
                scholarship_id=candidate.id, db=self.db, current_user=self.user,
            ),
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(HTTPException) as error:
                    endpoint()
                self.assertEqual(error.exception.status_code, 404)

    def test_direct_ids_reject_ordinary_unverified_scholarships(self):
        candidate = self.add_scholarship("Ordinary Unverified")

        endpoints = (
            lambda: scholarships.get_scholarship(candidate.id, db=self.db),
            lambda: recommendations.scholarship_recommendation(
                candidate.id, db=self.db, current_user=self.user,
            ),
            lambda: eligibility.check_one_scholarship(
                candidate.id, db=self.db, current_user=self.user,
            ),
            lambda: eligibility.profile_improvements(
                scholarship_id=candidate.id, db=self.db, current_user=self.user,
            ),
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(HTTPException) as error:
                    endpoint()
                self.assertEqual(error.exception.status_code, 404)

    def test_direct_ids_allow_verified_and_published_discoveries(self):
        verified = self.add_scholarship("Verified Detail", "verified")
        published = self.add_scholarship("Published Detail", discovery_created=True)
        self.add_publication(published)

        for scholarship in (verified, published):
            with self.subTest(scholarship=scholarship.name):
                self.assertEqual(
                    scholarships.get_scholarship(scholarship.id, db=self.db)["id"],
                    scholarship.id,
                )
                self.assertEqual(
                    recommendations.scholarship_recommendation(
                        scholarship.id, db=self.db, current_user=self.user,
                    )["scholarship_id"],
                    scholarship.id,
                )
                self.assertEqual(
                    eligibility.check_one_scholarship(
                        scholarship.id, db=self.db, current_user=self.user,
                    )["scholarship_id"],
                    scholarship.id,
                )
                self.assertEqual(
                    eligibility.profile_improvements(
                        scholarship_id=scholarship.id,
                        db=self.db,
                        current_user=self.user,
                    )["opportunities"][0]["id"],
                    scholarship.id,
                )

    def test_revoked_discovery_is_hidden_from_all_direct_id_paths(self):
        candidate = self.add_scholarship("Revoked Detail", discovery_created=True)
        self.add_publication(candidate, status="revoked")
        endpoints = (
            lambda: scholarships.get_scholarship(candidate.id, db=self.db),
            lambda: recommendations.scholarship_recommendation(
                candidate.id, db=self.db, current_user=self.user,
            ),
            lambda: eligibility.check_one_scholarship(
                candidate.id, db=self.db, current_user=self.user,
            ),
            lambda: eligibility.profile_improvements(
                scholarship_id=candidate.id, db=self.db, current_user=self.user,
            ),
        )

        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(HTTPException) as error:
                    endpoint()
                self.assertEqual(error.exception.status_code, 404)

    def test_eligibility_includes_published_discovery_as_unverified(self):
        candidate = self.add_scholarship("Published Eligibility", discovery_created=True)
        self.add_publication(candidate)

        result = eligibility.check_all_scholarships(
            eligible_only=False,
            include_unverified=False,
            db=self.db,
            current_user=self.user,
        )

        item = next(item for item in result if item["scholarship_id"] == candidate.id)
        self.assertEqual(item["verification_status"], "unverified")
        self.assertEqual(item["source_provenance"]["sources"], ["database", "live_discovery"])

    def test_discovery_source_urls_are_not_returned_for_revoked_publications(self):
        candidate = self.add_scholarship("Revoked Verified", "verified", discovery_created=True)
        self.add_publication(candidate, status="revoked")

        result = next(item for item in self.list_records(self.db) if item["id"] == candidate.id)
        self.assertEqual(result["source_provenance"]["discovery_sources"], [])

    def test_published_discoveries_are_stably_ordered_across_search_pages(self):
        first = self.add_scholarship("Equal Name", discovery_created=True)
        self.add_publication(first)
        second = self.add_scholarship("Equal Name", discovery_created=True)
        self.add_publication(second)

        page_one = search_scholarships(
            self.db, {}, None, False, sort="name", skip=0, limit=1, today=date.today(),
        )
        page_two = search_scholarships(
            self.db, {}, None, False, sort="name", skip=1, limit=1, today=date.today(),
        )

        self.assertEqual(page_one["total"], 2)
        self.assertEqual(page_two["total"], 2)
        self.assertEqual(page_one["items"][0]["scholarship"]["id"], first.id)
        self.assertEqual(page_two["items"][0]["scholarship"]["id"], second.id)

    def test_profile_improvement_fallback_scope_names_both_visible_sources(self):
        candidate = self.add_scholarship("Published Guidance", discovery_created=True)
        self.add_publication(candidate)
        self.profile.preferred_countries = ""
        self.db.commit()

        result = eligibility.profile_improvements(
            scholarship_id=None,
            db=self.db,
            current_user=self.user,
        )

        self.assertEqual(
            result["scope"]["description"],
            "All verified canonical scholarships and published discoveries",
        )

    def test_missing_publication_tables_fall_back_to_canonical_visibility(self):
        self.db.close()
        self.engine.dispose()
        tables = [
            table for table in Base.metadata.sorted_tables
            if table.name not in PUBLICATION_TABLES
        ]
        fallback_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=fallback_engine, tables=tables)
        self.db = sessionmaker(bind=fallback_engine)()
        self.engine = fallback_engine
        candidate = self.add_scholarship("Canonical Fallback", "verified")

        records = get_student_scholarships(self.db)

        self.assertEqual([record.scholarship.id for record in records], [candidate.id])
        self.assertEqual(records[0].source_provenance()["sources"], ["database"])

    def test_unrelated_missing_table_errors_are_reraised_after_rollback(self):
        self.add_scholarship("Rollback Probe", "verified")
        error = OperationalError(
            "SELECT ...",
            {},
            Exception("no such table: scholarship_discovery_publications_archive"),
        )

        with mock.patch.object(
            student_scholarship_visibility,
            "_publication_rows",
            side_effect=error,
        ):
            with self.assertRaises(OperationalError):
                get_student_scholarships(self.db)

        self.assertEqual(self.db.query(Scholarship).count(), 1)


if __name__ == "__main__":
    unittest.main()
