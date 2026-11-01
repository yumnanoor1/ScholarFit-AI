"""
Scholarship-program relationships. Service tests need no database; API tests use in-memory SQLite.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
from datetime import date
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import migrate_scholarship_program_links as migration
from app.core.permissions import require_admin
from app.database import Base
from app.models.opportunity import Program, ProgramCost, Scholarship, ScholarshipProgramLink, University
from app.models.user import User
from app.routers import financial_feasibility as financial_api
from app.routers import programs as programs_api
from app.routers import scholarships as api
from app.schemas.financial import FeasibilityRequest, MoneyInput
from app.schemas.matching import ScholarshipProgramLinkWrite
from app.services.financial_feasibility import calculate_feasibility
from app.services.scholarship_eligibility import evaluate_scholarship
from app.services.scholarship_matching import evaluate_match, match_for_financial
from scholarship_program_link_data import INSTITUTIONS, LINKS
from test_scholarship_eligibility import make_profile
from test_scholarship_eligibility import make_scholarship as eligibility_scholarship

EVIDENCE = dict(evidence="The official page covers this program.", source_url="https://example.org/official",
                verification_status="verified", last_verified=date(2026, 10, 31))


def scholarship(**overrides):
    data = dict(id=1, name="Award", country="Germany", funding_type="Fully Funded", verification_status="verified",
                eligible_degree_levels=["Master's"], discipline_scope="all", eligible_disciplines=None,
                institution_scope="national", host_institution=None, host_university_id=None)
    return SimpleNamespace(**{**data, **overrides})


def program(**overrides):
    university = overrides.pop("university", SimpleNamespace(name="TU Example", country="Germany"))
    data = dict(id=7, name="MSc Computer Science", university_id=3, degree_level="Master",
                field_of_study="Computer Science", university=university)
    return SimpleNamespace(**{**data, **overrides})


def link(**overrides):
    data = dict(outcome="potential", relationship_type="unconfirmed", evidence=None, source_url=None,
                verification_status="unverified", last_verified=None, notes=None)
    return SimpleNamespace(**{**data, **overrides})


def confirmed_link():
    return link(outcome="confirmed", relationship_type="named_program", **EVIDENCE)


class CountryTests(unittest.TestCase):
    def test_same_country_is_only_potential(self):
        self.assertEqual(evaluate_match(scholarship(), program())["outcome"], "potential")

    def test_other_country(self):
        result = evaluate_match(scholarship(country="Turkey"), program())
        self.assertEqual((result["outcome"], result["blocking_criterion"]), ("not_a_match", "country"))

    def test_multi_country_award_needs_checking(self):
        self.assertEqual(evaluate_match(scholarship(country="European Union (multi-country)"), program())["outcome"], "needs_verification")

    def test_missing_country(self):
        self.assertEqual(evaluate_match(scholarship(country=None), program())["outcome"], "needs_verification")

    def test_student_nationality_rules_dont_decide_a_program(self):
        record = scholarship(eligible_countries=["Pakistan"], excluded_countries=["Germany"], nationality_scope="listed")
        self.assertEqual(evaluate_match(record, program())["outcome"], "potential")


class DegreeTests(unittest.TestCase):
    def test_not_a_masters_program(self):
        result = evaluate_match(scholarship(), program(degree_level="PhD"))
        self.assertEqual((result["outcome"], result["blocking_criterion"]), ("not_a_match", "degree"))

    def test_scholarship_for_another_level(self):
        self.assertEqual(evaluate_match(scholarship(eligible_degree_levels=["PhD"]), program())["outcome"], "not_a_match")

    def test_research_masters_only_is_unclear(self):
        self.assertEqual(evaluate_match(scholarship(eligible_degree_levels=["Master's (Research)"]), program())["outcome"], "needs_verification")

    def test_unknown_levels(self):
        self.assertEqual(evaluate_match(scholarship(eligible_degree_levels=None), program())["outcome"], "needs_verification")


class DisciplineTests(unittest.TestCase):
    def test_listed_field_that_fits(self):
        record = scholarship(discipline_scope="listed", eligible_disciplines=["Mathematics and Digital Science", "Law"])
        self.assertEqual(evaluate_match(record, program())["outcome"], "potential")

    def test_listed_fields_that_exclude_the_program(self):
        record = scholarship(discipline_scope="listed", eligible_disciplines=["Public Policy", "Architecture"])
        result = evaluate_match(record, program())
        self.assertEqual((result["outcome"], result["blocking_criterion"]), ("not_a_match", "discipline"))

    def test_restricted_list_doesnt_rule_out(self):
        record = scholarship(discipline_scope="restricted", eligible_disciplines=["Law"])
        self.assertEqual(evaluate_match(record, program())["outcome"], "needs_verification")

    def test_no_list_on_record(self):
        for scope in ("restricted", "varies", "not_specified", None):
            self.assertEqual(evaluate_match(scholarship(discipline_scope=scope), program())["outcome"], "needs_verification", scope)

    def test_field_we_cant_place(self):
        record = scholarship(discipline_scope="listed", eligible_disciplines=["Engineering"])
        self.assertEqual(evaluate_match(record, program(field_of_study="Marine Biology"))["outcome"], "needs_verification")


class UniversityTests(unittest.TestCase):
    def test_own_university(self):
        record = scholarship(institution_scope="single_institution", host_institution="TU Example", host_university_id=3)
        self.assertEqual(evaluate_match(record, program())["outcome"], "potential")

    def test_other_university_in_the_same_country(self):
        record = scholarship(institution_scope="single_institution", host_institution="Other University", host_university_id=None)
        result = evaluate_match(record, program())
        self.assertEqual((result["outcome"], result["blocking_criterion"]), ("not_a_match", "university"))

    def test_similar_name_is_not_a_match(self):
        record = scholarship(institution_scope="single_institution", host_institution="TU Example", host_university_id=99)
        self.assertEqual(evaluate_match(record, program())["outcome"], "not_a_match")

    def test_participating_list_is_never_assumed(self):
        self.assertEqual(evaluate_match(scholarship(institution_scope="participating_list"), program())["outcome"], "needs_verification")

    def test_unreviewed_scope(self):
        self.assertEqual(evaluate_match(scholarship(institution_scope=None), program())["outcome"], "needs_verification")


class EvidenceTests(unittest.TestCase):
    def test_rules_alone_never_confirm(self):
        record = scholarship(institution_scope="single_institution", host_university_id=3)
        self.assertNotEqual(evaluate_match(record, program())["outcome"], "confirmed")

    def test_confirmed_with_evidence(self):
        result = evaluate_match(scholarship(), program(), confirmed_link())
        self.assertEqual((result["outcome"], result["label"]), ("confirmed", "Confirmed Match"))
        self.assertEqual(result["source_url"], "https://example.org/official")
        self.assertEqual(result["relationship_verification_status"], "verified")

    def test_potential_link_stays_potential(self):
        self.assertEqual(evaluate_match(scholarship(), program(), link())["outcome"], "potential")

    def test_stored_non_match(self):
        self.assertEqual(evaluate_match(scholarship(), program(), link(outcome="not_a_match"))["outcome"], "not_a_match")

    def test_confirmed_link_against_a_stated_condition_is_a_conflict(self):
        result = evaluate_match(scholarship(country="Turkey"), program(), confirmed_link())
        self.assertEqual(result["outcome"], "needs_verification")
        self.assertIn("conflicts", result["explanation"])

    def test_unverified_scholarship_cant_be_confirmed(self):
        result = evaluate_match(scholarship(verification_status="unverified"), program(), confirmed_link())
        self.assertEqual(result["outcome"], "needs_verification")
        self.assertEqual(result["scholarship_verification_status"], "unverified")
        self.assertEqual(result["relationship_verification_status"], "verified")  # kept separate

    def test_unverified_scholarship_without_link(self):
        self.assertEqual(evaluate_match(scholarship(verification_status="unverified"), program())["outcome"], "needs_verification")

    def test_outcome_ignores_student_eligibility(self):
        record = eligibility_scholarship(pakistan_eligible="No - excluded")
        self.assertEqual(evaluate_scholarship(record, make_profile())["status"], "not_eligible")
        self.assertEqual(evaluate_match(scholarship(), program(), confirmed_link())["outcome"], "confirmed")


class WriteValidationTests(unittest.TestCase):
    def test_confirmed_needs_every_piece_of_evidence(self):
        base = dict(outcome="confirmed", relationship_type="named_program", **EVIDENCE)
        ScholarshipProgramLinkWrite(**base)
        for change in (dict(evidence=" "), dict(source_url=None), dict(last_verified=None), dict(verification_status="unverified")):
            with self.assertRaises(ValidationError):
                ScholarshipProgramLinkWrite(**{**base, **change})

    def test_bad_values(self):
        for change in (dict(outcome="maybe"), dict(source_url="http://example.org"), dict(last_verified=date(2999, 1, 1)), dict(extra=1)):
            with self.assertRaises(ValidationError):
                ScholarshipProgramLinkWrite(**{**dict(outcome="potential", relationship_type="unconfirmed"), **change})


class ReviewedDataTests(unittest.TestCase):
    def test_every_scholarship_has_a_scope(self):
        self.assertEqual(sorted(INSTITUTIONS), list(range(1, 42)))

    def test_confirmed_rows_carry_evidence(self):
        for row in LINKS:
            if row["outcome"] == "confirmed":
                self.assertTrue(row["evidence"] and row["source_url"].startswith("https://") and row["last_verified"], row)
            else:
                self.assertEqual(row["verification_status"], "unverified", row)
                self.assertIsNone(row["last_verified"], row)

    def test_no_duplicate_pairs(self):
        pairs = [(row["scholarship_id"], row["program_id"]) for row in LINKS]
        self.assertEqual(len(pairs), len(set(pairs)))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(self.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.university = University(name="TU Example", country="Germany")
        self.other_university = University(name="Other University", country="Germany")
        self.db.add_all([self.university, self.other_university])
        self.db.flush()
        common = dict(degree_level="Master", field_of_study="Computer Science", duration_months=24,
                      tuition_amount=10000, tuition_currency="EUR")
        self.first = Program(name="First", university_id=self.university.id, **common)
        self.second = Program(name="Second", university_id=self.university.id, **common)
        self.elsewhere = Program(name="Elsewhere", university_id=self.other_university.id, **common)
        fields = dict(country="Germany", eligible_degree_levels=["Master's"], discipline_scope="all",
                      verification_status="verified", funding_type="Fully Funded", duration="2 years")
        self.national = Scholarship(name="National", institution_scope="national", tuition_coverage="Full tuition fee waiver", **fields)
        self.own = Scholarship(name="Own", institution_scope="single_institution", host_institution="TU Example",
                               host_university_id=self.university.id, tuition_coverage="Full tuition fee waiver", **fields)
        self.hidden = Scholarship(name="Hidden", institution_scope="national", **{**fields, "verification_status": "unverified"})
        self.alice = User(email="alice@example.com", hashed_password="x", full_name="Alice")
        self.admin = User(email="admin@example.com", hashed_password="x", full_name="Admin", role="admin")
        self.db.add_all([self.first, self.second, self.elsewhere, self.national, self.own, self.hidden, self.alice, self.admin])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def put(self, scholarship_row, program_row, **fields):
        body = {**dict(outcome="potential", relationship_type="unconfirmed"), **fields}
        return api.set_scholarship_program_link(ScholarshipProgramLinkWrite(**body), scholarship_id=scholarship_row.id,
                                                program_id=program_row.id, db=self.db, admin=self.admin)

    def stored(self):
        return self.db.query(ScholarshipProgramLink).count()

    def test_one_scholarship_many_programs(self):
        self.put(self.national, self.first, outcome="confirmed", relationship_type="named_program", **EVIDENCE)
        self.put(self.national, self.second)
        names = {r["program_name"]: r["outcome"] for r in api.scholarship_programs(self.national.id, include_not_matches=False, db=self.db)}
        self.assertEqual(names, {"First": "confirmed", "Second": "potential", "Elsewhere": "potential"})

    def test_results_are_sorted_with_confirmed_first(self):
        self.put(self.national, self.second, outcome="confirmed", relationship_type="named_program", **EVIDENCE)
        rows = api.scholarship_programs(self.national.id, include_not_matches=False, db=self.db)
        self.assertEqual(rows[0]["program_name"], "Second")

    def test_one_program_many_scholarships(self):
        names = [r["scholarship_name"] for r in programs_api.program_scholarships(self.first.id, include_not_matches=False, include_unverified=False, db=self.db)]
        self.assertEqual(names, ["National", "Own"])

    def test_unverified_scholarships_stay_hidden_by_default(self):
        rows = programs_api.program_scholarships(self.first.id, include_not_matches=False, include_unverified=True, db=self.db)
        self.assertIn("Hidden", [r["scholarship_name"] for r in rows])

    def test_not_matches_are_optional(self):
        kept = api.scholarship_programs(self.own.id, include_not_matches=False, db=self.db)
        self.assertNotIn("Elsewhere", [r["program_name"] for r in kept])
        everything = api.scholarship_programs(self.own.id, include_not_matches=True, db=self.db)
        self.assertEqual(next(r for r in everything if r["program_name"] == "Elsewhere")["outcome"], "not_a_match")

    def test_pair(self):
        result = api.scholarship_program_match(self.own.id, self.elsewhere.id, db=self.db)
        self.assertEqual(result["blocking_criterion"], "university")

    def test_coverage_counts(self):
        self.put(self.own, self.first, outcome="confirmed", relationship_type="named_program", **EVIDENCE)
        rows = {r["scholarship_id"]: r for r in api.program_coverage(include_unverified=False, db=self.db)}
        self.assertEqual((rows[self.own.id]["confirmed"], rows[self.own.id]["potential"]), (1, 1))
        self.assertNotIn(self.hidden.id, rows)

    def test_put_twice_keeps_one_row(self):
        self.put(self.national, self.first)
        self.put(self.national, self.first, outcome="needs_verification")
        self.assertEqual(self.stored(), 1)
        self.assertEqual(self.db.query(ScholarshipProgramLink).one().outcome, "needs_verification")

    def test_database_refuses_a_duplicate(self):
        for _ in range(2):
            self.db.add(ScholarshipProgramLink(scholarship_id=self.national.id, program_id=self.first.id,
                                               outcome="potential", relationship_type="unconfirmed", verification_status="unverified"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_database_refuses_a_confirmed_row_without_evidence(self):
        self.db.add(ScholarshipProgramLink(scholarship_id=self.national.id, program_id=self.first.id, outcome="confirmed",
                                           relationship_type="named_program", verification_status="unverified"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_invalid_ids(self):
        calls = [lambda: api.scholarship_programs(99999, include_not_matches=False, db=self.db),
                 lambda: api.scholarship_program_match(99999, self.first.id, db=self.db),
                 lambda: api.scholarship_program_match(self.own.id, 99999, db=self.db),
                 lambda: programs_api.program_scholarships(99999, include_not_matches=False, include_unverified=False, db=self.db),
                 lambda: api.delete_scholarship_program_link(self.own.id, 99999, db=self.db, admin=self.admin)]
        for call in calls:
            with self.assertRaises(HTTPException) as error:
                call()
            self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(self.stored(), 0)

    def test_delete_keeps_the_records(self):
        self.put(self.national, self.first)
        api.delete_scholarship_program_link(self.national.id, self.first.id, db=self.db, admin=self.admin)
        self.assertEqual(self.stored(), 0)
        self.assertIsNotNone(self.db.get(Program, self.first.id))
        self.assertIsNotNone(self.db.get(Scholarship, self.national.id))
        with self.assertRaises(HTTPException):
            api.delete_scholarship_program_link(self.national.id, self.first.id, db=self.db, admin=self.admin)

    def test_deleting_a_program_removes_its_links_only(self):
        self.put(self.national, self.first)
        self.db.delete(self.first)
        self.db.commit()
        self.assertEqual(self.stored(), 0)
        self.assertIsNotNone(self.db.get(Scholarship, self.national.id))

    def test_student_cant_use_admin_operations(self):
        with self.assertRaises(HTTPException) as error:
            require_admin(current_user=self.alice)
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(require_admin(current_user=self.admin), self.admin)

    def test_write_routes_require_admin(self):
        for route in api.router.routes:
            if route.path.endswith("/programs/{program_id}") and route.methods & {"PUT", "DELETE"}:
                self.assertIn(require_admin, [item.call for item in route.dependant.dependencies])

    def test_write_body_cant_choose_ids(self):
        with self.assertRaises(ValidationError):
            ScholarshipProgramLinkWrite(outcome="potential", relationship_type="unconfirmed", scholarship_id=2)

    def test_read_routes_take_no_user_input(self):
        for route in api.router.routes:
            if "programs" in route.path and "GET" in route.methods:
                self.assertNotIn("user_id", [item.name for item in route.dependant.query_params])

    def test_migration_fill_is_repeatable(self):
        self.db.add(University(id=4, name="Politecnico di Milano", country="Italy"))
        self.db.add(University(id=5, name="KTH Royal Institute of Technology", country="Sweden"))
        self.db.add(University(id=7, name="Delft University of Technology", country="Netherlands"))
        self.db.commit()
        migration.fill(self.db)
        before = self.stored()
        self.national.institution_scope = "participating_list"  # an admin's later edit
        self.db.commit()
        self.assertEqual(migration.fill(self.db), (0, 0))
        self.assertEqual(self.stored(), before)
        self.assertEqual(self.national.institution_scope, "participating_list")

    # ---- Financial Feasibility ----

    def financial(self, scholarship_row, program_row):
        request = FeasibilityRequest(program_id=program_row.id, scholarship_id=scholarship_row.id,
                                     budget=MoneyInput(amount=50000, currency="EUR"), currency="EUR")
        return financial_api._run(self.db, self.alice, request)

    def test_no_relationship_keeps_the_calculation(self):
        self.assertIsNone(match_for_financial(self.db, self.national, self.first))
        plain = calculate_feasibility(self.first, scholarship=self.national, budget=MoneyInput(amount=50000, currency="EUR"), currency="EUR")
        result = self.financial(self.national, self.first)
        self.assertEqual(result["confirmed_funding"], plain["confirmed_funding"])
        self.assertGreater(result["confirmed_funding"], 0)
        self.assertIsNone(result["scholarship"]["match_outcome"])

    def test_confirmed_is_counted(self):
        self.put(self.national, self.first, outcome="confirmed", relationship_type="named_program", **EVIDENCE)
        result = self.financial(self.national, self.first)
        self.assertGreater(result["confirmed_funding"], 0)
        self.assertEqual(result["potential_funding"], 0)
        self.assertEqual(result["scholarship"]["match_label"], "Confirmed Match")

    def test_potential_is_shown_but_not_counted(self):
        self.put(self.national, self.first)
        result = self.financial(self.national, self.first)
        self.assertEqual(result["confirmed_funding"], 0)
        self.assertGreater(result["potential_funding"], 0)
        self.assertFalse(result["scholarship"]["counted"])
        self.assertTrue(result["funding"][0]["potential"])
        self.assertEqual(result["remaining_cost"], result["total_estimated_cost"])

    def test_needs_verification_isnt_counted(self):
        self.put(self.national, self.first, outcome="needs_verification")
        self.assertEqual(self.financial(self.national, self.first)["confirmed_funding"], 0)

    def test_not_a_match_gets_no_coverage(self):
        result = self.financial(self.own, self.elsewhere)
        self.assertFalse(result["scholarship"]["applicable"])
        self.assertEqual((result["confirmed_funding"], result["potential_funding"]), (0, 0))
        self.assertEqual(result["scholarship"]["match_outcome"], "not_a_match")

    def test_stored_not_a_match_gets_no_coverage(self):
        self.put(self.national, self.first, outcome="not_a_match")
        self.assertEqual(self.financial(self.national, self.first)["confirmed_funding"], 0)

    def test_saved_costs_are_untouched_by_links(self):
        self.db.add(ProgramCost(program_id=self.first.id, category="visa", amount=100, currency="EUR", period="total",
                                source_url="https://example.org", last_verified=date(2026, 10, 31)))
        self.db.commit()
        self.put(self.national, self.first)
        self.assertEqual(self.db.query(ProgramCost).count(), 1)


if __name__ == "__main__":
    unittest.main()
