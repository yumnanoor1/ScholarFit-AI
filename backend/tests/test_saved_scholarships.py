"""
Saved scholarship tests. Handlers run against in-memory SQLite with foreign keys on.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import inspect
import unittest
from datetime import datetime, timedelta, timezone
from datetime import date

from fastapi import HTTPException, Response
from fastapi.dependencies.utils import get_dependant
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import issue_session_token
from app.database import Base
from app.models.opportunity import Scholarship
from app.models.user import SavedScholarship, User
from app.routers import saved_scholarships as api
from app.routers import scholarships as scholarships_api
from app.core.permissions import require_complete_profile
from app.routers.auth import get_current_user
from app.schemas.opportunity import SavedScholarshipResponse


class SavedScholarshipTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.first = Scholarship(
            name="First", country="Germany", verification_status="verified", verification_basis="official_source",
            official_info_url="https://example.org/first", last_verified_date=date.today(),
        )
        self.second = Scholarship(
            name="Second", country="Sweden", verification_status="verified", verification_basis="official_source",
            official_info_url="https://example.org/second", last_verified_date=date.today(),
        )
        self.alice = User(email="alice@example.com", hashed_password="x", full_name="Alice")
        self.bob = User(email="bob@example.com", hashed_password="x", full_name="Bob")
        self.db.add_all([self.first, self.second, self.alice, self.bob])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def save(self, user, scholarship):
        response = Response()
        response.status_code = None  # as FastAPI injects it: unset means the route's declared 201
        record = api.save_scholarship(response=response, scholarship_id=scholarship.id, db=self.db, current_user=user)
        return record, response

    def remove(self, user, scholarship):
        api.remove_saved_scholarship(scholarship_id=scholarship.id, db=self.db, current_user=user)

    def saved_names(self, user):
        return [item.scholarship.name for item in api.list_saved_scholarships(db=self.db, current_user=user)]

    def test_save_and_retrieve(self):
        record, _ = self.save(self.alice, self.first)
        self.assertEqual(self.saved_names(self.alice), ["First"])
        body = SavedScholarshipResponse.model_validate(record)
        self.assertEqual(body.scholarship_id, self.first.id)
        self.assertEqual(body.scholarship.name, "First")
        self.assertIsNotNone(body.saved_at)

    def test_save_returns_201_by_declaration(self):
        route = next(r for r in api.router.routes if "POST" in r.methods)
        self.assertEqual(route.status_code, 201)

    def test_saved_records_survive_a_new_session(self):
        self.save(self.alice, self.first)
        fresh = sessionmaker(bind=self.db.get_bind())()
        rows = api.list_saved_scholarships(db=fresh, current_user=fresh.get(User, self.alice.id))
        self.assertEqual([row.scholarship.name for row in rows], ["First"])
        fresh.close()

    def test_oldest_first(self):
        self.save(self.alice, self.first)
        self.save(self.alice, self.second)
        self.db.query(SavedScholarship).filter(SavedScholarship.scholarship_id == self.first.id).update(
            {"saved_at": datetime.now(timezone.utc) + timedelta(days=1)})
        self.db.commit()
        self.assertEqual(self.saved_names(self.alice), ["Second", "First"])

    def test_remove(self):
        self.save(self.alice, self.first)
        self.save(self.alice, self.second)
        self.remove(self.alice, self.first)
        self.assertEqual(self.saved_names(self.alice), ["Second"])

    def test_removing_something_not_saved_changes_nothing(self):
        self.remove(self.alice, self.first)
        self.assertEqual(self.saved_names(self.alice), [])

    def test_duplicate_save_returns_the_same_record(self):
        record, created = self.save(self.alice, self.first)
        again, repeat = self.save(self.alice, self.first)
        self.assertEqual(again.id, record.id)
        self.assertEqual(repeat.status_code, 200)
        self.assertIsNone(created.status_code)
        self.assertEqual(self.db.query(SavedScholarship).count(), 1)

    def test_database_rejects_duplicates(self):
        self.save(self.alice, self.first)
        self.db.add(SavedScholarship(user_id=self.alice.id, scholarship_id=self.first.id))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_simultaneous_save_is_treated_as_a_duplicate(self):
        record, _ = self.save(self.alice, self.first)
        real = api._find_saved
        calls = []

        def miss_once(db, user, scholarship_id):  # the first lookup runs before the other request commits
            calls.append(1)
            return None if len(calls) == 1 else real(db, user, scholarship_id)

        api._find_saved = miss_once
        try:
            again, response = self.save(self.alice, self.first)
        finally:
            api._find_saved = real
        self.assertEqual(again.id, record.id)
        self.assertEqual(response.status_code, 200)

    def test_archived_scholarship_cannot_be_newly_saved(self):
        self.save(self.alice, self.first)
        self.first.archived_at = datetime.now(timezone.utc)
        self.db.commit()
        with self.assertRaises(HTTPException) as refused:
            self.save(self.bob, self.first)
        self.assertEqual(refused.exception.status_code, 409)
        self.assertEqual(self.saved_names(self.bob), [])
        # The student who already saved it keeps it, and saving again stays harmless
        record, response = self.save(self.alice, self.first)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(record.scholarship_id, self.first.id)

    def test_two_students_have_separate_lists(self):
        self.save(self.alice, self.first)
        self.save(self.bob, self.second)
        self.assertEqual(self.saved_names(self.alice), ["First"])
        self.assertEqual(self.saved_names(self.bob), ["Second"])

    def test_same_scholarship_can_be_saved_by_both(self):
        self.save(self.alice, self.first)
        self.save(self.bob, self.first)
        self.remove(self.bob, self.first)
        self.assertEqual(self.saved_names(self.alice), ["First"])
        self.assertEqual(self.saved_names(self.bob), [])

    def test_student_cannot_delete_anothers_record(self):
        self.save(self.alice, self.first)
        self.remove(self.bob, self.first)
        self.assertEqual(self.saved_names(self.alice), ["First"])

    def test_no_handler_accepts_a_user_id(self):
        for route in api.router.routes:
            names = set(inspect.signature(route.endpoint).parameters)
            self.assertFalse(names & {"user_id", "student_id", "user"}, route.path)

    def test_every_route_requires_the_signed_in_user(self):
        self.assertEqual(len(api.router.routes), 3)
        for route in api.router.routes:
            self.assertIn(require_complete_profile, [dependency.call for dependency in route.dependant.dependencies], route.path)
        self.assertIn(get_current_user, [dependency.call for dependency in get_dependant(path="", call=require_complete_profile).dependencies])

    def test_invalid_token_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            get_current_user(token="not-a-real-token", db=self.db)
        self.assertEqual(error.exception.status_code, 401)

    def test_token_identifies_the_student(self):
        token = issue_session_token(self.bob)
        self.assertEqual(get_current_user(token=token, db=self.db).id, self.bob.id)

    def test_unknown_scholarship(self):
        with self.assertRaises(HTTPException) as error:
            api.save_scholarship(response=Response(), scholarship_id=99999, db=self.db, current_user=self.alice)
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(self.db.query(SavedScholarship).count(), 0)

    def test_deleting_a_scholarship_removes_its_saves(self):
        self.save(self.alice, self.first)
        self.db.delete(self.first)
        self.db.commit()
        self.assertEqual(self.db.query(SavedScholarship).count(), 0)

    def test_scholarship_turning_unverified_stays_in_the_list(self):
        self.save(self.alice, self.first)
        self.first.verification_status = "unverified"
        self.db.commit()
        items = api.list_saved_scholarships(db=self.db, current_user=self.alice)
        body = SavedScholarshipResponse.model_validate(items[0])
        self.assertEqual((body.scholarship.name, body.scholarship.verification_status), ("First", "unverified"))

    def test_verified_scholarship_reports_its_status(self):
        self.save(self.alice, self.first)
        items = api.list_saved_scholarships(db=self.db, current_user=self.alice)
        self.assertEqual(SavedScholarshipResponse.model_validate(items[0]).scholarship.verification_status, "verified")

    def test_public_listing_still_hides_what_the_saved_list_keeps(self):
        self.save(self.alice, self.first)
        self.first.verification_status = "unverified"
        self.db.commit()
        listed = scholarships_api.list_scholarships(
            country=None, funding_type=None, degree_level=None, pakistan_eligible_only=False,
            include_unverified=False, search=None, skip=0, limit=50, db=self.db)
        self.assertEqual([item.name for item in listed], ["Second"])
        self.assertEqual(self.saved_names(self.alice), ["First"])

    def test_unverified_scholarship_can_be_removed(self):
        self.save(self.alice, self.first)
        self.first.verification_status = "unverified"
        self.db.commit()
        self.remove(self.alice, self.first)
        self.assertEqual(self.saved_names(self.alice), [])

    def test_unverified_save_stays_private(self):
        self.save(self.alice, self.first)
        self.first.verification_status = "unverified"
        self.db.commit()
        self.assertEqual(self.saved_names(self.bob), [])

    def test_deleted_scholarship_answers_404_for_the_notice(self):
        scholarship_id = self.first.id
        self.save(self.alice, self.first)
        self.db.delete(self.first)
        self.db.commit()
        self.assertEqual(self.saved_names(self.alice), [])
        with self.assertRaises(HTTPException) as error:
            scholarships_api.get_scholarship(scholarship_id, db=self.db)
        self.assertEqual(error.exception.status_code, 404)

    def test_deleting_a_user_removes_their_saves_only(self):
        self.save(self.alice, self.first)
        self.save(self.bob, self.first)
        self.db.delete(self.alice)
        self.db.commit()
        self.assertEqual(self.saved_names(self.bob), ["First"])
        self.assertEqual(self.db.query(SavedScholarship).count(), 1)


if __name__ == "__main__":
    unittest.main()
