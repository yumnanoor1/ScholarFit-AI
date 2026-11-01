"""
Structured scholarship data tests: the reviewed table, shared validation, the migration and the
consumers that must keep working. The migration runs against in-memory SQLite.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
from datetime import date
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import migrate_scholarship_structure as migration
from app.database import Base
from app.models.opportunity import Scholarship
from app.schemas.opportunity import ScholarshipResponse, ScholarshipStructured, ScholarshipUpdate, is_web_url
from app.services.financial_feasibility import calculate_feasibility
from app.schemas.financial import ExpenseInput, ExpenseInputs, MoneyInput
from app.services.scholarship_eligibility import evaluate_scholarship, scholarship_deadline
from scholarship_structured_data import RECORDS

TODAY = date(2026, 10, 31)
ORIGINAL_COLUMNS = ["country", "name", "tuition_coverage", "living_stipend", "deadline", "official_url", "notes",
                    "verification_status", "last_verified"]


def validated(entry):
    return ScholarshipStructured(**{key: value for key, value in entry.items() if key != "name"})


def source_row(**overrides):
    data = dict(id=1, name="Türkiye Bursları (Türkiye Scholarships) - Master's Programme", country="Turkey",
                verification_status="verified", last_verified="2026-09-30", official_url=(
                    "https://www.turkiyeburslari.gov.tr/ ; https://tbbs.turkiyeburslari.gov.tr/"),
                tuition_coverage="Full", living_stipend="Yes - 6,500 TRY/month", travel_airfare="Yes",
                min_academic_requirement="Minimum 75% academic achievement", english_requirement="Not fixed",
                deadline="2026-2027 cycle: applications accepted 10 January - 20 February 2026", notes="Original notes")
    data.update(overrides)
    return data


class ReviewedDataTests(unittest.TestCase):
    def test_every_record_is_covered_once(self):
        self.assertEqual(sorted(RECORDS), list(range(1, 42)))

    def test_every_entry_passes_the_shared_schema(self):
        for scholarship_id, entry in RECORDS.items():
            with self.subTest(scholarship_id):
                validated(entry)

    def test_structured_requirements(self):
        self.assertEqual(RECORDS[39]["excluded_countries"], ["Australia", "New Zealand"])
        self.assertEqual((RECORDS[39]["min_gpa"], RECORDS[39]["min_gpa_scale"]), (5.0, 7.0))
        self.assertEqual(RECORDS[1]["min_percentage"], 75)
        self.assertEqual(RECORDS[1]["max_age"], 29)   # "under 30"
        self.assertEqual(RECORDS[19]["min_age"], 18)
        self.assertEqual(RECORDS[32]["gender_restriction"], "women")
        self.assertIn("second_masters_excluded", RECORDS[6]["applicant_restrictions"])
        self.assertIn("first_time_applicant", RECORDS[16]["applicant_restrictions"])

    def test_nationality_and_degree_data(self):
        self.assertEqual(len(RECORDS[18]["eligible_countries"]), 36)  # the record says 36
        self.assertEqual(len(RECORDS[19]["eligible_countries"]), 13)  # the record says 13
        self.assertNotIn("Pakistan", RECORDS[18]["eligible_countries"])
        self.assertEqual(RECORDS[37]["eligible_degree_levels"], ["Master's (Research)"])
        self.assertEqual(RECORDS[28]["nationality_scope"], "published_list")

    def test_language_requirements(self):
        self.assertEqual(RECORDS[35]["min_ielts"], 6.5)
        self.assertIn("IELTS", RECORDS[26]["accepted_english_tests"])
        self.assertNotIn("min_ielts", RECORDS[26])  # tests are named, no score is stated

    def test_hedged_amounts_are_not_stored_as_facts(self):
        self.assertNotIn("stipend_amount", RECORDS[2])      # "commonly cited"
        self.assertNotIn("stipend_amount", RECORDS[38])     # one university's example
        self.assertNotIn("min_percentage", RECORDS[8])      # "typically"
        self.assertNotIn("max_age", RECORDS[15])            # sources disagree
        self.assertTrue(RECORDS[8]["stipend_is_approximate"])

    def test_amounts_and_currencies_are_separate(self):
        self.assertEqual((RECORDS[21]["stipend_amount"], RECORDS[21]["stipend_currency"], RECORDS[21]["stipend_period"]),
                         (992, "EUR", "monthly"))
        self.assertEqual((RECORDS[29]["stipend_amount"], RECORDS[29]["stipend_amount_max"]), (1712, 2000))

    def test_unspecified_stipend_is_not_zero_or_none(self):
        self.assertEqual(RECORDS[31]["stipend_status"], "not_specified")
        self.assertNotIn("stipend_amount", RECORDS[31])
        self.assertEqual(RECORDS[12]["stipend_status"], "none")  # the record says so explicitly

    def test_no_stored_benefit_says_not_covered_without_a_statement(self):
        for scholarship_id, entry in RECORDS.items():
            for field in ("accommodation_status", "health_insurance_status", "travel_status"):
                self.assertNotEqual(entry.get(field), "not_covered", (scholarship_id, field))

    def test_full_funding_differs_from_tuition_only(self):
        self.assertEqual((RECORDS[12]["funding_level"], RECORDS[12]["tuition_coverage_type"]), ("tuition_only", "full"))
        self.assertEqual(RECORDS[28]["funding_level"], "full")

    def test_example_dates_are_not_deadlines(self):
        self.assertEqual(RECORDS[24]["deadline_type"], "varies_by_institution")
        self.assertNotIn("application_deadline_date", RECORDS[24])  # Bamberg's window is an example

    def test_recurring_dates_without_a_year_stay_undated(self):
        for scholarship_id in (6, 7, 8, 10):
            self.assertEqual(RECORDS[scholarship_id]["deadline_type"], "annual")
            self.assertNotIn("application_deadline_date", RECORDS[scholarship_id])

    def test_home_pages_are_not_official_scholarship_links(self):
        for scholarship_id in (23, 27, 34, 36, 41):
            self.assertNotIn("official_info_url", RECORDS[scholarship_id])
            self.assertTrue(RECORDS[scholarship_id]["additional_source_urls"])

    def test_verification_is_never_raised(self):
        for scholarship_id in (23, 27, 41):
            self.assertEqual(RECORDS[scholarship_id]["verification_basis"], "secondary_only")
        for entry in RECORDS.values():
            self.assertNotIn("verification_status", entry)

    def test_duplicates_are_flagged_not_removed(self):
        self.assertEqual(RECORDS[4]["duplicate_of_id"], 1)
        self.assertEqual(RECORDS[17]["duplicate_of_id"], 2)


class ValidationTests(unittest.TestCase):
    def test_rejects_unknown_values(self):
        for bad in ({"funding_level": "maybe"}, {"deadline_type": "soon"}, {"stipend_status": "yes"},
                    {"applicant_restrictions": ["made_up"]}, {"gender_restriction": "any"}):
            with self.assertRaises(ValidationError):
                ScholarshipStructured(**bad)

    def test_amount_needs_a_currency(self):
        with self.assertRaises(ValidationError):
            ScholarshipStructured(stipend_amount=100)
        with self.assertRaises(ValidationError):
            ScholarshipStructured(stipend_amount=100, stipend_currency="Euros")

    def test_ranges_run_upward(self):
        with self.assertRaises(ValidationError):
            ScholarshipStructured(stipend_amount=200, stipend_amount_max=100, stipend_currency="EUR")
        with self.assertRaises(ValidationError):
            ScholarshipStructured(application_open_date="2026-02-01", application_deadline_date="2026-01-01")
        with self.assertRaises(ValidationError):
            ScholarshipStructured(min_age=40, max_age=18)

    def test_gpa_needs_its_scale(self):
        with self.assertRaises(ValidationError):
            ScholarshipStructured(min_gpa=3.0)

    def test_score_limits(self):
        with self.assertRaises(ValidationError):
            ScholarshipStructured(min_ielts=10)
        with self.assertRaises(ValidationError):
            ScholarshipStructured(min_percentage=120)

    def test_official_urls(self):
        self.assertTrue(is_web_url("https://www.daad.de/go/en/stipa50026397"))
        for bad in ("www.daad.de", "https://a.org ; https://b.org", "https://a.org | https://b.org",
                    "javascript:alert(1)", "https://www.anu.edu.au/ (general portal)"):
            self.assertFalse(is_web_url(bad), bad)
            with self.assertRaises(ValidationError):
                ScholarshipStructured(official_info_url=bad)

    def test_admin_updates_use_the_same_rules(self):
        with self.assertRaises(ValidationError):
            ScholarshipUpdate(funding_level="maybe")
        self.assertEqual(ScholarshipUpdate(funding_level="full").model_dump(exclude_unset=True), {"funding_level": "full"})

    def test_older_clients_can_send_only_old_fields(self):
        self.assertEqual(ScholarshipUpdate(deadline="1 May").model_dump(exclude_unset=True), {"deadline": "1 May"})


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.row = SimpleNamespace(**{**dict.fromkeys(column.name for column in Scholarship.__table__.columns), **source_row()})

    def test_stated_values_pass(self):
        self.assertEqual(migration.audit_entry(self.row, {
            "stipend_amount": 6500, "min_percentage": 75, "application_open_date": date(2026, 1, 10),
            "application_deadline_date": date(2026, 2, 20), "official_info_url": "https://www.turkiyeburslari.gov.tr/",
        }), [])

    def test_invented_amount_is_caught(self):
        self.assertTrue(migration.audit_entry(self.row, {"stipend_amount": 7000}))

    def test_invented_date_is_caught(self):
        self.assertTrue(migration.audit_entry(self.row, {"application_deadline_date": date(2026, 3, 1)}))
        self.assertTrue(migration.audit_entry(self.row, {"application_deadline_date": date(2027, 2, 20)}))

    def test_invented_url_is_caught(self):
        self.assertTrue(migration.audit_entry(self.row, {"official_info_url": "https://example.org/page"}))


class DuplicateDetectionTests(unittest.TestCase):
    def row(self, id, name, url):
        return SimpleNamespace(id=id, name=name, official_url=url)

    def test_same_scholarship_with_and_without_accents(self):
        rows = [self.row(1, "Türkiye Bursları", "https://a.org/"), self.row(4, "Turkiye Burslari", "https://a.org/ | x")]
        self.assertEqual(migration.find_duplicates(rows), [(1, 4)])

    def test_same_first_url(self):
        rows = [self.row(2, "EMJM A", "https://e.eu/c ; https://x"), self.row(17, "EMJM B", "https://e.eu/c | https://y")]
        self.assertEqual(migration.find_duplicates(rows), [(2, 17)])

    def test_distinct_scholarships_of_one_provider_are_not_paired(self):
        rows = [self.row(29, "Commonwealth Master's", "https://c.uk/m"), self.row(30, "Commonwealth Shared", "https://c.uk/s")]
        self.assertEqual(migration.find_duplicates(rows), [])


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        structured = set(ScholarshipStructured.model_fields) | {"structured_data_version"}
        columns = [column for column in Scholarship.__table__.columns if column.name not in structured]
        definition = ", ".join(
            f"{column.name} {'INTEGER PRIMARY KEY' if column.primary_key else column.type.compile(dialect=self.engine.dialect)}"
            for column in columns)
        with self.engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE scholarships ({definition})"))
            conn.execute(text("INSERT INTO scholarships (id, name, country, tuition_coverage, living_stipend, deadline, "
                              "official_url, notes, verification_status, last_verified, min_academic_requirement) VALUES "
                              "(1, :name, :country, :tuition, :stipend, :deadline, :url, :notes, 'verified', :checked, :academic)"),
                         dict(name=source_row()["name"], country="Turkey", tuition="Full", stipend="Yes - 6,500 TRY/month",
                              deadline=source_row()["deadline"], url=source_row()["official_url"], notes="Original notes",
                              checked="2026-09-30", academic="Minimum 75% academic achievement"))

    def run_backfill(self):
        with Session(self.engine) as session:
            return migration.backfill(session)

    def original(self):
        with self.engine.connect() as conn:
            return dict(conn.execute(text(f"SELECT {', '.join(ORIGINAL_COLUMNS)} FROM scholarships WHERE id = 1")).mappings().one())

    def test_adds_columns_and_keeps_rows(self):
        before = self.original()
        added = migration.add_missing_columns(self.engine)
        self.assertIn("stipend_amount", added)
        self.assertEqual(self.original(), before)

    def test_second_run_adds_nothing(self):
        migration.add_missing_columns(self.engine)
        self.assertEqual(migration.add_missing_columns(self.engine), [])

    def test_backfill_fills_values_without_touching_originals(self):
        migration.add_missing_columns(self.engine)
        before = self.original()
        report = self.run_backfill()
        self.assertEqual(report["updated"], [1])
        self.assertEqual(report["problems"], {})
        self.assertEqual(self.original(), before)
        with Session(self.engine) as session:
            row = session.get(Scholarship, 1)
            self.assertEqual((row.stipend_amount, row.stipend_currency), (6500, "TRY"))
            self.assertEqual(row.application_deadline_date, date(2026, 2, 20))
            self.assertEqual(row.last_verified_date, date(2026, 9, 30))
            self.assertEqual(row.verification_basis, "official_source")
            self.assertEqual(row.structured_data_version, migration.STRUCTURED_DATA_VERSION)

    def test_repeat_run_changes_nothing_and_keeps_later_edits(self):
        migration.add_missing_columns(self.engine)
        self.run_backfill()
        with Session(self.engine) as session:
            session.get(Scholarship, 1).stipend_amount = 7000
            session.commit()
        report = self.run_backfill()
        self.assertEqual((report["updated"], report["already_current"]), ([], [1]))
        with Session(self.engine) as session:
            self.assertEqual(session.get(Scholarship, 1).stipend_amount, 7000)

    def test_row_with_a_different_name_is_skipped(self):
        migration.add_missing_columns(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE scholarships SET name = 'Something else' WHERE id = 1"))
        report = self.run_backfill()
        self.assertIn(1, report["skipped"])
        with Session(self.engine) as session:
            self.assertIsNone(session.get(Scholarship, 1).structured_data_version)

    def test_a_row_failing_the_audit_stays_empty(self):
        migration.add_missing_columns(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE scholarships SET living_stipend = 'Yes - monthly' WHERE id = 1"))
        report = self.run_backfill()
        self.assertIn(1, report["problems"])
        with Session(self.engine) as session:
            self.assertIsNone(session.get(Scholarship, 1).stipend_amount)

    def test_unverified_row_gets_the_matching_basis(self):
        migration.add_missing_columns(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE scholarships SET verification_status = 'unverified' WHERE id = 1"))
        self.run_backfill()
        with Session(self.engine) as session:
            row = session.get(Scholarship, 1)
            self.assertEqual((row.verification_basis, row.verification_status), ("not_verified", "unverified"))

    def test_non_date_last_verified_stays_empty(self):
        migration.add_missing_columns(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE scholarships SET last_verified = 'Not verified' WHERE id = 1"))
        self.run_backfill()
        with Session(self.engine) as session:
            self.assertIsNone(session.get(Scholarship, 1).last_verified_date)

    def test_new_columns_are_nullable(self):
        migration.add_missing_columns(self.engine)
        columns = {column["name"]: column for column in inspect(self.engine).get_columns("scholarships")}
        for name in ScholarshipStructured.model_fields:
            self.assertTrue(columns[name]["nullable"], name)


def make_scholarship(**overrides):
    data = dict.fromkeys(column.name for column in Scholarship.__table__.columns)
    data.update(id=1, name="Test", provider="Test Provider", country="Germany", degree_level="Master's",
                verification_status="verified", eligible_nationalities="Open to students of all nationalities",
                pakistan_eligible="Yes - open to all", eligible_fields="All fields",
                min_academic_requirement="Minimum CGPA 3.0", english_requirement="Yes - IELTS 6.5 overall",
                deadline="Varies; e.g. one university's window closes 31 August 2026", funding_type="Fully Funded",
                tuition_coverage="Full tuition fee waiver", living_stipend="Yes - EUR 900/month")
    data.update(overrides)
    return SimpleNamespace(**data)


class ConsumerCompatibilityTests(unittest.TestCase):
    def profile(self):
        return SimpleNamespace(nationality="Pakistan", date_of_birth=date(2001, 5, 1), degree_level="Bachelor's",
                               field_of_study="Computer Science", cgpa=3.4, cgpa_scale=4.0, ielts_score=7.0, toefl_score=None)

    def test_records_without_structured_data_keep_the_text_deadline(self):
        result = scholarship_deadline(make_scholarship(), TODAY)
        self.assertEqual((result["status"], result["date"]), ("closed", "2026-08-31"))

    def test_example_date_is_ignored_once_structured(self):
        result = scholarship_deadline(make_scholarship(deadline_type="varies_by_institution"), TODAY)
        self.assertEqual((result["status"], result["date"]), ("unknown", None))
        self.assertIn("31 August", result["text"])  # the original wording stays available

    def test_structured_dates(self):
        upcoming = scholarship_deadline(make_scholarship(deadline_type="fixed", application_deadline_date=date(2026, 12, 8)), TODAY)
        self.assertEqual((upcoming["status"], upcoming["days_left"]), ("open", 38))
        past = scholarship_deadline(make_scholarship(deadline_type="fixed", application_deadline_date=date(2026, 2, 20)), TODAY)
        self.assertEqual(past["status"], "closed")
        self.assertEqual(scholarship_deadline(make_scholarship(deadline_type="no_separate_deadline"), TODAY)["status"],
                         "no_separate_deadline")

    def test_deadline_on_the_day_is_open(self):
        result = scholarship_deadline(make_scholarship(deadline_type="fixed", application_deadline_date=TODAY), TODAY)
        self.assertEqual((result["status"], result["days_left"]), ("open", 0))

    def test_eligibility_result_is_the_same_with_structured_fields(self):
        plain = evaluate_scholarship(make_scholarship(), self.profile(), today=TODAY)
        filled = evaluate_scholarship(make_scholarship(deadline_type="not_specified", funding_level="full", min_ielts=6.5),
                                      self.profile(), today=TODAY)
        for key in ("status", "eligible", "satisfied", "not_satisfied", "missing_information", "needs_verification"):
            self.assertEqual(plain[key], filled[key], key)

    def test_structured_deadline_keeps_eligibility_separate(self):
        result = evaluate_scholarship(
            make_scholarship(deadline_type="fixed", application_deadline_date=date(2026, 2, 20)), self.profile(), today=TODAY)
        self.assertEqual((result["status"], result["deadline"]["status"]), ("eligible", "closed"))

    def test_response_works_for_old_and_new_rows(self):
        old = ScholarshipResponse.model_validate(make_scholarship())
        self.assertIsNone(old.stipend_amount)
        self.assertEqual(old.living_stipend, "Yes - EUR 900/month")
        filled = make_scholarship(stipend_amount=900, stipend_currency="EUR", stipend_period="monthly",
                                  application_deadline_date=date(2026, 12, 8))
        body = ScholarshipResponse.model_validate(filled).model_dump(mode="json")
        self.assertEqual((body["stipend_amount"], body["application_deadline_date"]), (900, "2026-12-08"))

    def test_response_tells_the_frontend_a_record_is_structured(self):
        body = ScholarshipResponse.model_validate(make_scholarship(structured_data_version=1)).model_dump()
        self.assertEqual(body["structured_data_version"], 1)

    def test_clients_cannot_set_the_structured_version(self):
        self.assertNotIn("structured_data_version", ScholarshipUpdate(structured_data_version=9).model_dump(exclude_unset=True))

    def test_financial_result_ignores_structured_fields(self):
        program = SimpleNamespace(
            id=1, name="MSc", tuition_amount=0.0, tuition_currency="EUR", tuition_period="yearly", duration_months=24,
            semester_fee_amount=None, semester_fee_currency=None, costs=[], source_url=None, last_verified=None,
            university=SimpleNamespace(name="Test University", country="Germany"))
        expenses = ExpenseInputs(living_costs=ExpenseInput(amount=1000, currency="EUR", period="monthly"))
        budget = MoneyInput(amount=20000, currency="EUR")
        plain = calculate_feasibility(program, make_scholarship(), budget=budget, currency="EUR", expenses=expenses)
        filled = calculate_feasibility(program, make_scholarship(stipend_amount=1, stipend_currency="EUR", funding_level="partial"),
                                       budget=budget, currency="EUR", expenses=expenses)
        self.assertEqual(plain, filled)


class ModelTests(unittest.TestCase):
    def test_full_table_creates_and_links_duplicates(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()
        first = Scholarship(name="A", country="X", eligible_countries=["Pakistan"], application_deadline_date=date(2026, 1, 1))
        db.add(first)
        db.commit()
        second = Scholarship(name="B", country="X", duplicate_of_id=first.id)
        db.add(second)
        db.commit()
        self.assertEqual(db.get(Scholarship, first.id).eligible_countries, ["Pakistan"])
        self.assertEqual(db.get(Scholarship, second.id).duplicate_of_id, first.id)
        db.close()


if __name__ == "__main__":
    unittest.main()
