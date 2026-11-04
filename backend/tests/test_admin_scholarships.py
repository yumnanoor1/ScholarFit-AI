"""
Admin scholarship management and data quality. Uses in-memory SQLite.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.permissions import require_admin
from app.database import Base
from app.models.opportunity import Program, Scholarship, ScholarshipAuditLog, ScholarshipProgramLink, University
from app.models.user import SavedScholarship, StudentProfile, User
from app.routers import admin_scholarships as admin_api
from app.routers import eligibility as eligibility_api
from app.routers import recommendations as recommendations_api
from app.routers import saved_scholarships as saved_api
from app.routers import scholarships as api
from app.routers.auth import get_optional_user
from app.schemas.admin import AdminDetail, ArchiveWrite, DuplicateWrite, FlagWrite, VerificationWrite
from app.schemas.opportunity import ScholarshipCreate, ScholarshipUpdate
from app.services.scholarship_eligibility import evaluate_scholarship
from app.services.scholarship_quality import duplicate_pairs, find_conflicts, find_issues, update_record
from app.services.scholarship_search import search_scholarships
from app.services.source_check import check_url
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
        with patch("app.routers.admin_scholarships.check_url", return_value={"status": "ok"}):
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
    def run_check(self, fetch, allowed=lambda host: True, url="https://example.org/a"):
        return check_url(url, fetch=fetch, host_allowed=allowed)

    def test_results(self):
        self.assertEqual(self.run_check(lambda url: (200, None))["status"], "ok")
        self.assertEqual(self.run_check(lambda url: (404, None))["status"], "broken")
        self.assertEqual(self.run_check(lambda url: (410, None))["status"], "broken")

    def test_refusals_arent_called_broken(self):
        for code in (403, 429, 500, 503):
            self.assertEqual(self.run_check(lambda url, c=code: (c, None))["status"], "inconclusive", code)

    def test_no_answer_isnt_broken(self):
        def fail(url):
            raise urllib.error.URLError("timed out")
        self.assertEqual(self.run_check(fail)["status"], "inconclusive")

    def test_private_addresses_are_never_requested(self):
        called = []
        result = self.run_check(lambda url: called.append(url) or (200, None), allowed=lambda host: False, url="http://localhost:5432/")
        self.assertEqual((result["status"], called), ("inconclusive", []))

    def test_redirect_to_a_private_address_stops(self):
        result = self.run_check(lambda url: (302, "http://10.0.0.1/"), allowed=lambda host: host != "10.0.0.1")
        self.assertEqual(result["status"], "inconclusive")

    def test_redirect_loop_stops(self):
        self.assertEqual(self.run_check(lambda url: (302, "/again"))["status"], "inconclusive")

    def test_other_schemes(self):
        self.assertEqual(self.run_check(lambda url: (200, None), url="file:///etc/passwd")["status"], "invalid")


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
