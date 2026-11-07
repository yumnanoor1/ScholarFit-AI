"""
Financial feasibility tests. The service tests need no database; the API tests use an in-memory
SQLite database, so they never touch the real PostgreSQL data.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
from datetime import date
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.opportunity import Program, ProgramCost, Scholarship, ScholarshipProgramLink, University
from app.models.user import StudentProfile, User
from app.routers import programs as programs_api
from app.routers import financial_feasibility as api
from app.routers.auth import get_current_user
from app.schemas.financial import (
    BudgetUpdate, ExpenseInput, ExpenseInputs, MoneyInput, ScholarshipFeasibilityRequest,
)
from app.schemas.opportunity import ProgramCostUpdate
from app.services import exchange_rates
from app.services.exchange_rates import convert
from app.services.financial_feasibility import calculate_feasibility


def make_program(**overrides):
    data = dict(
        id=1, name="MSc Test", duration_months=24, tuition_amount=10000.0, tuition_currency="EUR",
        tuition_usd_per_year=None, living_cost_usd_per_year=None, source_url="https://example.edu",
        last_verified=date(2026, 10, 25),
        university=SimpleNamespace(name="Test University", country="Germany"),
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def make_scholarship(**overrides):
    data = dict(
        id=7, name="Test Scholarship", country="Germany", provider="German Academic Exchange Service", funding_type="Fully Funded",
        verification_status="verified", last_verified="2026-09-30", official_url="https://example.org",
        official_info_url="https://example.org", verification_basis="official_source",
        last_verified_date=date(2026, 10, 30), source_checks=[], data_flags=[],
        tuition_coverage=None, living_stipend=None, duration="Duration of the Master's programme",
        accommodation=None, health_insurance=None, travel_airfare=None, visa_support=None, other_benefits=None,
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def living(amount=1000, period="monthly", currency="EUR", source="student_input"):
    return ExpenseInput(amount=amount, currency=currency, period=period, source=source)


def all_expenses(**overrides):
    """Every expense category filled in, so nothing is unknown."""
    data = dict(
        living_costs=living(),
        university_fees=ExpenseInput(amount=0, currency="EUR", period="total"),
        health_insurance=living(100),
        visa=ExpenseInput(amount=100, currency="EUR", period="total"),
        travel=ExpenseInput(amount=800, currency="EUR", period="total"),
        application_fees=ExpenseInput(amount=0, currency="EUR", period="total"),
        other=ExpenseInput(amount=0, currency="EUR", period="total"),
    )
    data.update(overrides)
    return ExpenseInputs(**data)


def eur(amount):
    return MoneyInput(amount=amount, currency="EUR")


def funding_line(result, category):
    return next(line for line in result["funding"] if line["category"] == category)


def make_database_scholarship():
    return Scholarship(
        country="Germany",
        name="Test Scholarship",
        provider="Test Provider",
        verification_status="verified",
        official_info_url="https://example.org/scholarship",
        verification_basis="official_source",
        last_verified_date=date.today(),
        source_checks=[],
        data_flags=[],
        tuition_coverage="Full tuition fee waiver",
        duration="Duration of the Master's programme",
    )


def make_confirmed_program_link(scholarship, program):
    return ScholarshipProgramLink(
        scholarship_id=scholarship.id,
        program_id=program.id,
        outcome="confirmed",
        relationship_type="named_program",
        evidence="The official scholarship page lists this Master's programme.",
        source_url="https://example.org/program-scholarships",
        verification_status="verified",
        last_verified=date.today(),
    )


class BudgetOutcomeTests(unittest.TestCase):
    # Totals for all_expenses(): tuition 20,000 + living 24,000 + insurance 2,400 + visa 100 + travel 800 = 47,300

    def test_feasible_budget(self):
        result = calculate_feasibility(make_program(), budget=eur(50000), expenses=all_expenses())
        self.assertEqual(result["total_estimated_cost"], 47300)
        self.assertEqual(result["status"], "feasible")
        self.assertEqual(result["surplus"], 2700)
        self.assertEqual(result["funding_gap"], 0)

    def test_not_feasible_budget(self):
        result = calculate_feasibility(make_program(), budget=eur(20000), expenses=all_expenses())
        self.assertEqual(result["status"], "not_feasible")
        self.assertEqual(result["funding_gap"], 27300)

    def test_small_shortfall_is_partially_feasible(self):
        result = calculate_feasibility(make_program(), budget=eur(40000), expenses=all_expenses())
        self.assertEqual(result["funding_gap"], 7300)  # 15% of 47,300
        self.assertEqual(result["status"], "partially_feasible")

    def test_unknown_optional_expense_never_gives_feasible(self):
        expenses = all_expenses(travel=None)
        result = calculate_feasibility(make_program(), budget=eur(1_000_000), expenses=expenses)
        self.assertEqual(result["status"], "partially_feasible")
        self.assertTrue(any("Travel is unknown" in note for note in result["uncertainties"]))
        travel = next(line for line in result["costs"] if line["category"] == "travel")
        self.assertIsNone(travel["amount"])  # unknown, not zero

    def test_planning_estimate_never_gives_feasible(self):
        expenses = all_expenses(living_costs=living(source="planning_estimate"))
        result = calculate_feasibility(make_program(), budget=eur(1_000_000), expenses=expenses)
        self.assertEqual(result["status"], "partially_feasible")
        living_line = next(line for line in result["costs"] if line["category"] == "living_costs")
        self.assertTrue(living_line["is_estimate"])

    def test_profile_budget_used_when_none_sent(self):
        result = calculate_feasibility(make_program(), profile_budget_usd=55965, expenses=all_expenses())
        self.assertEqual(result["budget"]["source"], "profile")
        self.assertAlmostEqual(result["budget"]["amount"], 50000, places=0)  # 55,965 USD = 50,000 EUR


class MissingDataTests(unittest.TestCase):
    def test_missing_living_costs(self):
        result = calculate_feasibility(make_program(), budget=eur(100000), expenses=all_expenses(living_costs=None))
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["total_estimated_cost"])
        self.assertTrue(any("never assumed to be zero" in note for note in result["missing_data"]))

    def test_missing_duration(self):
        result = calculate_feasibility(make_program(duration_months=None), budget=eur(100000), expenses=all_expenses())
        self.assertEqual(result["status"], "insufficient_data")
        self.assertTrue(any("no duration" in note for note in result["missing_data"]))

    def test_missing_tuition(self):
        result = calculate_feasibility(make_program(tuition_amount=None, tuition_currency=None),
                                       budget=eur(100000), expenses=all_expenses())
        self.assertEqual(result["status"], "insufficient_data")

    def test_missing_budget(self):
        result = calculate_feasibility(make_program(), expenses=all_expenses())
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["budget"]["source"], "not_provided")

    def test_living_cost_from_program_record(self):
        result = calculate_feasibility(make_program(living_cost_usd_per_year=11193), budget=eur(100000),
                                       expenses=all_expenses(living_costs=None))
        living_line = next(line for line in result["costs"] if line["category"] == "living_costs")
        self.assertEqual(living_line["source"], "program_record")
        self.assertAlmostEqual(living_line["amount"], 20000, places=0)  # 10,000 EUR/yr x 2 yrs


class CurrencyTests(unittest.TestCase):
    def test_annual_fee_in_sek_converted(self):
        program = make_program(tuition_amount=192500.0, tuition_currency="SEK")
        result = calculate_feasibility(program, budget=eur(100000), currency="EUR", expenses=all_expenses())
        tuition = result["costs"][0]
        expected = convert(192500, "SEK", "EUR") * 2
        self.assertAlmostEqual(tuition["amount"], round(expected, 2))
        self.assertTrue(result["exchange_rates"]["used"])

    def test_defaults_to_tuition_currency(self):
        program = make_program(tuition_amount=4380.0, tuition_currency="CHF")
        result = calculate_feasibility(program, budget=MoneyInput(amount=1000, currency="CHF"))
        self.assertEqual(result["currency"], "CHF")

    def test_unavailable_rate_for_budget(self):
        result = calculate_feasibility(make_program(), budget=MoneyInput(amount=5_000_000, currency="PKR"),
                                       expenses=all_expenses())
        self.assertEqual(result["status"], "insufficient_data")
        self.assertTrue(any("PKR" in note for note in result["missing_data"]))

    def test_unavailable_rate_for_living_costs(self):
        expenses = all_expenses(living_costs=living(currency="GBP"))
        result = calculate_feasibility(make_program(), budget=eur(100000), expenses=expenses)
        self.assertEqual(result["status"], "insufficient_data")


class ScholarshipTests(unittest.TestCase):
    def setUp(self):
        self.program = make_program()
        self.expenses = all_expenses()

    def run_with(self, budget=30000, **scholarship):
        return calculate_feasibility(self.program, make_scholarship(**scholarship), budget=eur(budget),
                                     expenses=self.expenses)

    def test_no_scholarship(self):
        result = calculate_feasibility(self.program, budget=eur(30000), expenses=self.expenses)
        self.assertEqual(result["confirmed_funding"], 0)
        self.assertIsNone(result["scholarship"])

    def test_tuition_only_is_not_full_funding(self):
        result = self.run_with(tuition_coverage="Full tuition fee waiver",
                               living_stipend="No / Not specified - living costs not covered")
        self.assertEqual(result["confirmed_funding"], 20000)  # tuition only
        self.assertEqual(result["remaining_cost"], 27300)
        self.assertFalse(any(line["counted"] for line in result["funding"] if line["category"] == "living_costs"))
        self.assertEqual(result["status"], "feasible")  # 30,000 budget covers the 27,300 left, all costs known

    def test_partial_percentage(self):
        result = self.run_with(tuition_coverage="75% reduction of tuition fees for the 2-year programme")
        self.assertEqual(funding_line(result, "tuition")["amount"], 15000)

    def test_ambiguous_percentages_not_counted(self):
        result = self.run_with(tuition_coverage="15% or 30% reduction of international tuition fees")
        self.assertFalse(funding_line(result, "tuition")["counted"])
        self.assertEqual(result["confirmed_funding"], 0)

    def test_fully_funded(self):
        result = self.run_with(budget=10000, tuition_coverage="Full tuition fee waiver",
                               living_stipend="Yes - monthly stipend of currently €992")
        self.assertEqual(funding_line(result, "tuition")["amount"], 20000)
        self.assertEqual(funding_line(result, "living_costs")["amount"], 23808)  # 992 x 24
        self.assertEqual(result["remaining_cost"], 47300 - 20000 - 23808)
        self.assertEqual(result["status"], "feasible")

    def test_unverified_scholarship_not_counted(self):
        result = self.run_with(verification_status="unverified", tuition_coverage="Full tuition fee waiver")
        self.assertEqual(result["confirmed_funding"], 0)
        self.assertFalse(result["scholarship"]["counted"])

    def test_verified_status_without_current_official_evidence_is_not_counted(self):
        result = self.run_with(verification_basis="provider_submitted", tuition_coverage="Full tuition fee waiver")
        self.assertEqual(result["confirmed_funding"], 0)
        self.assertFalse(result["scholarship"]["counted"])
        self.assertIn("official source", result["scholarship"]["verification_issue"])

    def test_scholarship_for_other_country_not_counted(self):
        result = self.run_with(country="Netherlands", tuition_coverage="Full tuition fee waiver")
        self.assertEqual(result["confirmed_funding"], 0)
        self.assertFalse(result["scholarship"]["applicable"])

    def test_other_universitys_scholarship_not_counted(self):
        self.program = make_program(university=SimpleNamespace(name="KTH Royal Institute of Technology", country="Sweden"))
        result = self.run_with(country="Sweden", provider="Chalmers University of Technology (funded by the Chalmers Foundation)",
                               tuition_coverage="Full tuition fee waiver")
        self.assertFalse(result["scholarship"]["applicable"])
        self.assertEqual(result["confirmed_funding"], 0)

    def test_own_universitys_scholarship_counted(self):
        self.program = make_program(university=SimpleNamespace(name="KTH Royal Institute of Technology", country="Sweden"))
        result = self.run_with(country="Sweden", provider="KTH Royal Institute of Technology",
                               tuition_coverage="Full tuition fee waiver")
        self.assertTrue(result["scholarship"]["applicable"])

    def test_government_scholarship_not_tied_to_one_university(self):
        result = self.run_with(provider="German Academic Exchange Service (DAAD), funded by the Federal Foreign Office",
                               tuition_coverage="Full tuition fee waiver")
        self.assertTrue(result["scholarship"]["applicable"])

    def test_multi_country_programme_scholarship_not_counted(self):
        result = self.run_with(country="European Union (multi-country, hosted across consortium institutions)",
                               tuition_coverage="Yes - full participation/tuition costs of the joint programme covered")
        self.assertFalse(result["scholarship"]["applicable"])

    def test_bracketed_fee_is_not_the_award(self):
        result = self.run_with(tuition_coverage="Full tuition-fee waiver (candidates pay only a small non-refundable "
                                                "administrative fee of about €170)")
        self.assertEqual(funding_line(result, "tuition")["amount"], 20000)

    def test_bracketed_breakdown_is_not_a_lower_rate(self):
        result = self.run_with(living_stipend="Yes - €300 per month (€150 from the Federal Government, €150 from a private sponsor)")
        self.assertEqual(funding_line(result, "living_costs")["amount"], 7200)  # 300 x 24

    def test_hyphenated_duration(self):
        result = self.run_with(tuition_coverage="Full tuition fee waiver", duration="2-year MSc programme")
        self.assertEqual(funding_line(result, "tuition")["amount"], 20000)

    def test_stipend_in_currency_without_rate_not_counted(self):
        result = self.run_with(tuition_coverage="Full tuition exemption", living_stipend="Yes - 6,500 TRY/month")
        line = funding_line(result, "living_costs")
        self.assertFalse(line["counted"])
        self.assertIn("TRY", line["reason"])

    def test_package_counted_once(self):
        # A package covering tuition AND living must not be added again as a separate stipend
        result = self.run_with(
            tuition_coverage="EUR 25,000 full scholarship (covering tuition and living expenses) for one academic year, "
                             "extendable for a second year",
            living_stipend="Included within the EUR 25,000 package (not itemised separately)",
            duration="1 year, extendable to 2 years for two-year Master's programmes",
        )
        package = funding_line(result, "tuition_and_living")
        self.assertEqual(package["amount"], 25000)  # first, guaranteed year only
        self.assertFalse(funding_line(result, "living_costs")["counted"])
        self.assertEqual(result["confirmed_funding"], 25000)

    def test_benefits_capped_at_cost(self):
        # Stipend larger than living costs, tuition waiver on a cheap program: never more than the cost
        self.expenses = all_expenses(living_costs=living(500))
        result = self.run_with(tuition_coverage="Full tuition fee waiver",
                               living_stipend="Yes - EUR 3,000 per month")
        self.assertEqual(funding_line(result, "living_costs")["amount"], 12000)  # capped at 500 x 24
        self.assertLessEqual(result["confirmed_funding"], result["total_estimated_cost"])

    def test_conditional_later_years_not_counted(self):
        result = self.run_with(tuition_coverage="Full tuition fee waiver for the 2-year programme (second-year "
                                                "waiver typically conditional on satisfactory first-year results)",
                               duration="1-2 years, matching the Master's programme")
        line = funding_line(result, "tuition")
        self.assertEqual(line["amount"], 10000)  # first year only
        self.assertIn("conditional", line["reason"])

    def test_first_year_only_grant(self):
        result = self.run_with(tuition_coverage="One-time grant of EUR 5,000 in the first year",
                               duration="One-time grant for the first year only")
        self.assertEqual(funding_line(result, "tuition")["amount"], 5000)


# ---------------------------------------------------------------------------
# API handlers against an in-memory database
# ---------------------------------------------------------------------------

class ApiTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        uni = University(name="Test University", country="Germany")
        self.db.add(uni)
        self.db.flush()
        today = date.today()
        self.program = Program(university_id=uni.id, name="MSc Test", degree_level="Master's",
                               field_of_study="Computer Science", duration_months=24,
                               tuition_amount=10000, tuition_currency="EUR",
                               source_url="https://example.edu/program", last_verified=today)
        self.scholarship = make_database_scholarship()
        self.alice = User(email="alice@example.com", hashed_password="x", full_name="Alice")
        self.bob = User(email="bob@example.com", hashed_password="x", full_name="Bob")
        self.db.add_all([self.program, self.scholarship, self.alice, self.bob])
        self.db.flush()
        self.db.add(make_confirmed_program_link(self.scholarship, self.program))
        self.db.add_all([
            StudentProfile(user_id=self.alice.id, budget_usd=11193),   # 10,000 EUR
            StudentProfile(user_id=self.bob.id, budget_usd=1119300),   # 1,000,000 EUR
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_calculate_uses_database_records(self):
        request = ScholarshipFeasibilityRequest(scholarship_id=self.scholarship.id,
                                                budget=eur(30000), expenses=all_expenses())
        result = api.calculate(request, db=self.db, current_user=self.alice)
        self.assertIsNone(result["program"])
        self.assertEqual(result["total_estimated_cost"], 47300)
        self.assertEqual(result["confirmed_funding"], 20000)

    def test_unknown_scholarship(self):
        with self.assertRaises(HTTPException) as error:
            api.calculate(ScholarshipFeasibilityRequest(scholarship_id=9999),
                          db=self.db, current_user=self.alice)
        self.assertEqual(error.exception.status_code, 404)

    def test_budget_comes_from_the_signed_in_students_profile(self):
        # A user_id in the body is ignored; Alice only ever gets her own budget
        request = ScholarshipFeasibilityRequest.model_validate({"scholarship_id": self.scholarship.id,
                                                     "user_id": self.bob.id, "currency": "EUR",
                                                     "expenses": all_expenses().model_dump()})
        result = api.calculate(request, db=self.db, current_user=self.alice)
        self.assertEqual(result["budget"]["source"], "profile")
        self.assertAlmostEqual(result["budget"]["amount"], 10000, places=0)

    def test_profile_budget_preserves_its_saved_currency(self):
        profile = self.db.query(StudentProfile).filter_by(user_id=self.alice.id).one()
        profile.budget_usd = None
        profile.tuition_budget_amount = 111310
        profile.tuition_budget_currency = "SEK"
        self.db.commit()
        result = api.calculate(
            ScholarshipFeasibilityRequest(scholarship_id=self.scholarship.id, expenses=all_expenses()),
            db=self.db,
            current_user=self.alice,
        )
        self.assertEqual(result["budget"]["source"], "not_provided")
        self.assertIsNone(result["budget"]["amount"])
        self.assertTrue(any("total study budget" in item for item in result["missing_data"]))

    def test_calculate_reports_missing_living_costs(self):
        result = api.calculate(
            ScholarshipFeasibilityRequest(scholarship_id=self.scholarship.id),
            db=self.db,
            current_user=self.alice,
        )
        self.assertEqual(result["status"], "insufficient_data")

    def test_invalid_token_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            get_current_user(token="not-a-real-token", db=self.db)
        self.assertEqual(error.exception.status_code, 401)


class ProgramCostTests(unittest.TestCase):
    def cost(self, **overrides):
        data = dict(category="living_costs", amount=1000.0, currency="EUR", period="monthly", is_estimate=False,
                    source_name="Official page", source_url="https://example.edu/costs", last_verified=date(2026, 10, 30))
        data.update(overrides)
        return SimpleNamespace(**data)

    def test_stored_living_cost_is_used_with_its_source(self):
        program = make_program(costs=[self.cost()])
        result = calculate_feasibility(program, budget=eur(100000), expenses=all_expenses(living_costs=None))
        line = next(item for item in result["costs"] if item["category"] == "living_costs")
        self.assertEqual((line["amount"], line["source"]), (24000, "program_record"))
        self.assertEqual(line["source_url"], "https://example.edu/costs")
        self.assertEqual(result["living_cost"], 24000)

    def test_semester_fee_is_not_treated_as_annual(self):
        program = make_program(costs=[self.cost(category="university_fees", amount=97.0, period="semester")])
        result = calculate_feasibility(program, budget=eur(100000), expenses=ExpenseInputs(living_costs=living()))
        line = next(item for item in result["costs"] if item["category"] == "university_fees")
        self.assertEqual(line["amount"], 388)  # 4 semesters in 24 months

    def test_student_figure_wins_over_record(self):
        program = make_program(costs=[self.cost()])
        result = calculate_feasibility(program, budget=eur(100000), expenses=all_expenses(living_costs=living(800)))
        self.assertEqual(result["living_cost"], 19200)

    def test_source_estimate_is_flagged(self):
        program = make_program(costs=[self.cost(is_estimate=True)])
        result = calculate_feasibility(program, budget=eur(100000), expenses=all_expenses(living_costs=None))
        self.assertTrue(any("estimate published by the source" in note for note in result["uncertainties"]))

    def test_stale_tuition_source_prevents_definitive_result(self):
        result = calculate_feasibility(
            make_program(last_verified=date(2025, 1, 1)), budget=eur(100000), expenses=all_expenses(),
            today=date(2026, 11, 2),
        )
        self.assertEqual(result["status"], "insufficient_data")
        self.assertTrue(any("tuition source needs verification" in item for item in result["missing_data"]))

    def test_stale_living_cost_source_prevents_definitive_result(self):
        program = make_program(costs=[self.cost(last_verified=date(2025, 1, 1))])
        result = calculate_feasibility(
            program, budget=eur(100000), expenses=all_expenses(living_costs=None), today=date(2026, 11, 2)
        )
        self.assertEqual(result["status"], "insufficient_data")
        self.assertTrue(any("Living costs" in item and "source needs verification" in item
                            for item in result["missing_data"]))

    def test_cost_in_currency_without_rate_is_not_zero(self):
        program = make_program(costs=[self.cost(currency="GBP")])
        result = calculate_feasibility(program, budget=eur(100000), expenses=all_expenses(living_costs=None))
        self.assertEqual(result["status"], "insufficient_data")

    def test_range_uses_the_upper_end(self):
        program = make_program(costs=[self.cost(amount_max=1500.0, is_estimate=True)])
        result = calculate_feasibility(program, budget=eur(100000), expenses=all_expenses(living_costs=None))
        self.assertEqual(result["living_cost"], 36000)
        self.assertTrue(any("upper end" in note for note in result["uncertainties"]))

    def test_cost_included_in_living_figure_counts_once(self):
        program = make_program(costs=[self.cost(includes="health_insurance")])
        with_insurance = all_expenses(living_costs=None)  # includes EUR 100/month of insurance
        result = calculate_feasibility(program, budget=eur(100000), expenses=with_insurance)
        line = next(item for item in result["costs"] if item["category"] == "health_insurance")
        self.assertEqual((line["amount"], line["source"]), (0, "included"))
        self.assertEqual(result["total_estimated_cost"], 20000 + 24000 + 900)

    def test_own_living_figure_doesnt_inherit_the_inclusion(self):
        program = make_program(costs=[self.cost(includes="health_insurance")])
        result = calculate_feasibility(program, budget=eur(100000), expenses=all_expenses())
        line = next(item for item in result["costs"] if item["category"] == "health_insurance")
        self.assertEqual(line["amount"], 2400)

    def test_breakdown_totals(self):
        result = calculate_feasibility(make_program(), budget=eur(50000), expenses=all_expenses())
        self.assertEqual((result["tuition_cost"], result["living_cost"], result["other_costs"]), (20000, 24000, 3300))


class ScholarshipBenefitTests(unittest.TestCase):
    def run_with(self, **scholarship):
        return calculate_feasibility(make_program(), make_scholarship(**scholarship), budget=eur(30000),
                                     expenses=all_expenses())

    def test_annual_stipend(self):
        result = self.run_with(living_stipend="Yes - AUD $39,500 per year".replace("AUD $", "EUR "))
        self.assertEqual(funding_line(result, "living_costs")["amount"], 24000)  # capped at living costs

    def test_in_kind_benefit_counts_against_its_expense(self):
        result = self.run_with(visa_support="Yes - visa costs covered", travel_airfare="Yes - return economy class ticket")
        self.assertEqual(funding_line(result, "visa")["amount"], 100)
        self.assertEqual(funding_line(result, "travel")["amount"], 800)
        self.assertEqual(result["scholarship_coverage"]["other"], 900)

    def test_allowance_without_amount_not_counted(self):
        result = self.run_with(travel_airfare="Yes - a travel allowance/contribution is included")
        self.assertFalse(funding_line(result, "travel")["counted"])

    def test_benefit_for_unknown_expense_not_counted(self):
        result = calculate_feasibility(make_program(), make_scholarship(visa_support="Yes - visa costs covered"),
                                       budget=eur(30000), expenses=all_expenses(visa=None))
        self.assertFalse(funding_line(result, "visa")["counted"])

    def test_coverage_breakdown(self):
        result = self.run_with(tuition_coverage="Full tuition fee waiver", living_stipend="Yes - EUR 500 per month")
        coverage = result["scholarship_coverage"]
        self.assertEqual((coverage["tuition"], coverage["living"], coverage["total"]), (20000, 12000, 32000))


class ExchangeRateTests(unittest.TestCase):
    def test_rates_come_from_the_config_file(self):
        self.assertEqual(exchange_rates.EUR_RATES["EUR"], 1.0)
        self.assertEqual(exchange_rates.RATES_DATE, "2026-10-23")

    def test_fresh_rates(self):
        self.assertFalse(exchange_rates.rates_info(date(2026, 10, 31))["stale"])

    def test_outdated_rates_warn_when_used(self):
        program = make_program(tuition_amount=192500.0, tuition_currency="SEK")
        result = calculate_feasibility(program, budget=eur(100000), currency="EUR", expenses=all_expenses(),
                                       today=date(2027, 3, 1))
        self.assertTrue(result["exchange_rates"]["stale"])
        self.assertTrue(any("Exchange rates are from" in note for note in result["uncertainties"]))
        self.assertEqual(result["status"], "insufficient_data")

    def test_stale_rates_used_only_for_scholarship_benefit_block_definitive_result(self):
        scholarship = make_scholarship(
            living_stipend="Yes - USD 500 per month", tuition_coverage=None
        )
        result = calculate_feasibility(
            make_program(), scholarship=scholarship, budget=eur(100000), expenses=all_expenses(),
            today=date(2027, 3, 1),
        )
        self.assertTrue(result["exchange_rates"]["used"])
        self.assertEqual(result["status"], "insufficient_data")


class PlanApiTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        uni = University(name="Test University", country="Germany")
        self.db.add(uni)
        self.db.flush()
        today = date.today()
        self.program = Program(university_id=uni.id, name="MSc Test", degree_level="Master's",
                               field_of_study="Computer Science", duration_months=24,
                               tuition_amount=10000, tuition_currency="EUR",
                               source_url="https://example.edu/program", last_verified=today)
        self.scholarship = make_database_scholarship()
        self.alice = User(email="alice@example.com", hashed_password="x", full_name="Alice")
        self.bob = User(email="bob@example.com", hashed_password="x", full_name="Bob")
        self.db.add_all([self.program, self.scholarship, self.alice, self.bob])
        self.db.flush()
        self.db.add(make_confirmed_program_link(self.scholarship, self.program))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_empty_plan(self):
        plan = api.get_plan(db=self.db, current_user=self.alice)
        self.assertIsNone(plan["budget"])
        self.assertIn("SEK", plan["supported_currencies"])

    def test_budget_create_read_update(self):
        api.save_budget(BudgetUpdate(amount=30000, currency="EUR"), db=self.db, current_user=self.alice)
        self.assertEqual(api.get_plan(db=self.db, current_user=self.alice)["budget"], {"amount": 30000, "currency": "EUR"})
        api.save_budget(BudgetUpdate(amount=45000, currency="usd"), db=self.db, current_user=self.alice)
        self.assertEqual(api.get_plan(db=self.db, current_user=self.alice)["budget"], {"amount": 45000, "currency": "USD"})
        self.assertEqual(self.db.query(api.StudentFinancialPlan).count(), 1)

    def test_budget_in_unsupported_currency(self):
        with self.assertRaises(HTTPException) as error:
            api.save_budget(BudgetUpdate(amount=1, currency="PKR"), db=self.db, current_user=self.alice)
        self.assertEqual(error.exception.status_code, 422)

    def test_plans_are_private(self):
        api.save_budget(BudgetUpdate(amount=30000, currency="EUR"), db=self.db, current_user=self.alice)
        self.assertIsNone(api.get_plan(db=self.db, current_user=self.bob)["budget"])

    def test_calculation_uses_saved_budget_and_expenses(self):
        api.save_budget(BudgetUpdate(amount=30000, currency="EUR"), db=self.db, current_user=self.alice)
        api.save_expenses(self.scholarship.id, ExpenseInputs(living_costs=living()), db=self.db, current_user=self.alice)
        result = api.calculate(
            ScholarshipFeasibilityRequest(scholarship_id=self.scholarship.id),
            db=self.db,
            current_user=self.alice,
        )
        self.assertEqual(result["budget"]["source"], "saved")
        self.assertEqual(result["total_estimated_cost"], 44000)

    def test_sent_budget_overrides_saved(self):
        api.save_budget(BudgetUpdate(amount=30000, currency="EUR"), db=self.db, current_user=self.alice)
        result = api.calculate(
            ScholarshipFeasibilityRequest(scholarship_id=self.scholarship.id, budget=eur(5)),
            db=self.db,
            current_user=self.alice,
        )
        self.assertEqual(result["budget"]["amount"], 5)

    def test_expenses_for_unknown_scholarship(self):
        with self.assertRaises(HTTPException) as error:
            api.save_expenses(9999, ExpenseInputs(), db=self.db, current_user=self.alice)
        self.assertEqual(error.exception.status_code, 404)

    def test_program_cost_store_read_replace(self):
        data = ProgramCostUpdate(amount=1000, currency="eur", period="monthly", source_url="https://example.edu/c",
                                 last_verified=date(2026, 10, 30))
        programs_api.set_program_cost(self.program.id, "living_costs", data, db=self.db, admin=None)
        programs_api.set_program_cost(self.program.id, "living_costs", data.model_copy(update={"amount": 1200}), db=self.db, admin=None)
        costs = programs_api.list_program_costs(self.program.id, db=self.db)
        self.assertEqual([(c.amount, c.currency) for c in costs], [(1200, "EUR")])
        self.assertEqual(self.db.query(ProgramCost).count(), 1)


class ValidationTests(unittest.TestCase):
    def test_budget_must_be_finite(self):
        with self.assertRaises(ValidationError):
            MoneyInput(amount=float("inf"), currency="EUR")

    def test_cost_needs_a_source(self):
        with self.assertRaises(ValidationError):
            ProgramCostUpdate(amount=1, currency="EUR", period="yearly", source_url="not-a-url", last_verified=date(2026, 1, 1))

    def test_negative_budget(self):
        with self.assertRaises(ValidationError):
            MoneyInput(amount=-1, currency="EUR")

    def test_bad_currency(self):
        with self.assertRaises(ValidationError):
            MoneyInput(amount=1, currency="EURO")

    def test_bad_period(self):
        with self.assertRaises(ValidationError):
            ExpenseInput(amount=1, currency="EUR", period="weekly")

    def test_bad_scholarship_id(self):
        with self.assertRaises(ValidationError):
            ScholarshipFeasibilityRequest(scholarship_id=0)


if __name__ == "__main__":
    unittest.main()
