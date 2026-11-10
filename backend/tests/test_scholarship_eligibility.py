"""
Scholarship eligibility tests. Service tests need no database; API tests use in-memory SQLite.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.opportunity import Scholarship
from app.models.user import StudentProfile, User
from app.routers import eligibility as api
from app.routers.auth import get_current_user
from app.services.scholarship_eligibility import deadline_status, evaluate_scholarship

TODAY = date(2026, 10, 29)


def make_profile(**overrides):
    data = dict(nationality="Pakistan", date_of_birth=date(2001, 5, 1), degree_level="Bachelor's",
                field_of_study="Computer Science", preferred_fields=["Computer Science"], cgpa=3.4,
                cgpa_scale=4.0, ielts_score=7.0, toefl_score=None)
    data.update(overrides)
    return SimpleNamespace(**data)


def make_scholarship(**overrides):
    data = dict(
        id=1, name="Test Scholarship", provider="Test Provider", country="Germany", degree_level="Master's",
        verification_status="verified", eligible_nationalities="Open to students of all nationalities",
        pakistan_eligible="Yes - open to all nationalities", eligible_fields="All fields",
        required_previous_degree="Bachelor's",
        min_academic_requirement="Minimum CGPA 3.0/4.0",
        bachelors_requirement="No additional Bachelor's degree conditions",
        english_requirement="Yes - IELTS 6.5 overall", work_experience="No work experience required",
        age_requirement="No age limit", residency_requirement="No residency requirement",
        notes="No gender restrictions. No additional applicant restrictions.",
        deadline="2027-01-15", funding_type="Fully Funded", tuition_coverage="Full tuition fee waiver",
        living_stipend="No", other_benefits=None, last_verified="2026-09-30", official_url="https://example.org",
        source_name="Official page", official_info_url="https://example.org/scholarship",
        verification_basis="official_source", last_verified_date=TODAY - timedelta(days=30),
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def evaluate(scholarship=None, profile=None):
    return evaluate_scholarship(scholarship or make_scholarship(), profile or make_profile(), today=TODAY)


def requirement(result, key):
    groups = result["satisfied"] + result["not_satisfied"] + result["missing_information"] + result["needs_verification"]
    return next(item for item in groups if item["requirement"] == key)


class OverallStatusTests(unittest.TestCase):
    def test_eligible(self):
        result = evaluate()
        self.assertEqual(result["status"], "eligible")
        self.assertTrue(result["eligible"])
        self.assertNotIn("age", [item["requirement"] for item in result["satisfied"]])
        self.assertNotIn("work_experience", [item["requirement"] for item in result["satisfied"]])
        self.assertIsNone(result["match_score"])
        self.assertTrue(any("does not mean you will be selected" in note for note in result["notes"]))

    def test_explicit_no_english_requirement_does_not_block_eligibility(self):
        result = evaluate(make_scholarship(
            english_requirement="No IELTS requirement",
            english_requirement_type=None,
            min_ielts=None,
        ))
        self.assertEqual(result["status"], "eligible")
        self.assertNotIn("english", [item["requirement"] for item in result["needs_verification"]])

    def test_english_requirement_not_stated_needs_verification(self):
        result = evaluate(make_scholarship(
            english_requirement="Not specified",
            english_requirement_type=None,
            min_ielts=None,
        ))
        self.assertEqual(requirement(result, "english")["status"], "not_evaluated")
        self.assertEqual((result["status"], result["outcome"]), ("not_evaluated", "verify_manually"))

    def test_explicit_no_age_restriction_does_not_block_eligibility(self):
        result = evaluate(make_scholarship(age_requirement="No age restriction"))
        self.assertEqual(result["status"], "eligible")
        self.assertNotIn("age", [item["requirement"] for item in result["needs_verification"]])

    def test_age_requirement_not_stated_needs_verification(self):
        result = evaluate(make_scholarship(age_requirement="Not specified"))
        self.assertEqual(requirement(result, "age")["status"], "not_evaluated")
        self.assertEqual((result["status"], result["outcome"]), ("not_evaluated", "verify_manually"))

    def test_unknown_material_requirement_is_not_eligible_or_rejected(self):
        result = evaluate(make_scholarship(work_experience="Not stated"))
        self.assertEqual(requirement(result, "work_experience")["status"], "not_evaluated")
        self.assertEqual((result["status"], result["outcome"], result["eligible"]),
                         ("not_evaluated", "verify_manually", False))

    def test_bare_bachelors_requirement_is_not_treated_as_no_extra_condition(self):
        result = evaluate(make_scholarship(bachelors_requirement="Yes"))
        self.assertEqual(requirement(result, "bachelors_conditions")["status"], "not_evaluated")
        self.assertEqual(result["status"], "not_evaluated")

    def test_conflicting_english_requirement_needs_verification(self):
        result = evaluate(make_scholarship(
            english_requirement_type="not_required",
            english_requirement="IELTS 6.5 overall",
        ))
        english = requirement(result, "english")
        self.assertEqual((english["status"], english["conflict"]), ("not_evaluated", True))
        self.assertEqual(result["status"], "not_evaluated")

    def test_ambiguous_english_requirement_blocks_definitive_eligibility(self):
        result = evaluate(make_scholarship(
            english_requirement="An English test may be required",
            english_requirement_type=None,
            min_ielts=None,
        ))
        english = requirement(result, "english")
        self.assertEqual((english["status"], english["scope"]), ("not_evaluated", "scholarship"))
        self.assertEqual(result["status"], "not_evaluated")

    def test_unmet_nationality(self):
        result = evaluate(make_scholarship(pakistan_eligible="No - Pakistan is not on the eligible list"))
        self.assertEqual(result["status"], "not_eligible")
        self.assertEqual(requirement(result, "nationality")["status"], "not_satisfied")

    def test_nationality_excluded_by_rule(self):
        scholarship = make_scholarship(eligible_nationalities="Open to candidates of all nationalities except French nationals")
        result = evaluate(scholarship, make_profile(nationality="France"))
        self.assertEqual(requirement(result, "nationality")["status"], "not_satisfied")

    def test_structured_nationality_scope_without_its_required_list_needs_review(self):
        for scholarship in (
            make_scholarship(nationality_scope="listed", eligible_countries=None, eligible_regions=None,
                             eligible_nationalities=None, pakistan_eligible=None),
            make_scholarship(nationality_scope="all_except", excluded_countries=None, excluded_regions=None,
                             eligible_nationalities=None, pakistan_eligible=None),
        ):
            result = evaluate(scholarship)
            self.assertEqual(requirement(result, "nationality")["status"], "not_evaluated")

    def test_conflicting_all_nationalities_scope_needs_review(self):
        scholarship = make_scholarship(
            nationality_scope="all", excluded_countries=["Pakistan"],
            eligible_nationalities=None, pakistan_eligible=None,
        )
        result = evaluate(scholarship)
        self.assertEqual(requirement(result, "nationality")["status"], "not_evaluated")

    def test_non_eu_rule(self):
        scholarship = make_scholarship(eligible_nationalities="Open to all non-EU/EEA nationalities")
        self.assertEqual(requirement(evaluate(scholarship, make_profile(nationality="Germany")), "nationality")["status"],
                         "not_satisfied")
        self.assertEqual(requirement(evaluate(scholarship, make_profile(nationality="India")), "nationality")["status"],
                         "satisfied")

    def test_unmet_degree_level(self):
        result = evaluate(make_scholarship(degree_level="PhD", required_previous_degree="Master's"))
        self.assertEqual(result["status"], "not_eligible")
        self.assertEqual(requirement(result, "degree_level")["status"], "not_satisfied")

    def test_phd_is_eligible_for_a_student_with_a_masters_degree(self):
        result = evaluate(make_scholarship(degree_level="PhD", required_previous_degree="Master's"),
                         make_profile(degree_level="Master's"))
        self.assertEqual(requirement(result, "degree_level")["status"], "satisfied")

    def test_multiple_offered_degree_levels_are_supported(self):
        result = evaluate(
            make_scholarship(degree_level="Master's", eligible_degree_levels=["Master's", "PhD"]),
            make_profile(),
        )
        self.assertEqual(requirement(result, "degree_level")["status"], "satisfied")

    def test_missing_previous_degree_requirement_needs_review(self):
        result = evaluate(make_scholarship(required_previous_degree=None))
        self.assertEqual(requirement(result, "degree_level")["status"], "not_evaluated")

    def test_zero_cgpa_is_compared_as_a_real_value(self):
        result = evaluate(profile=make_profile(cgpa=0.0))
        self.assertEqual(result["status"], "not_eligible")
        self.assertEqual(requirement(result, "academic")["status"], "not_satisfied")

    def test_missing_english_score_is_not_a_failure(self):
        result = evaluate(profile=make_profile(ielts_score=None))
        self.assertEqual(requirement(result, "english")["status"], "missing_information")
        self.assertEqual(result["status"], "missing_information")
        self.assertEqual(result["outcome"], "verify_manually")

    def test_low_english_score(self):
        result = evaluate(profile=make_profile(ielts_score=6.0))
        self.assertEqual(result["status"], "not_eligible")

    def test_other_language_test_is_not_reported_as_missing_or_assumed_equivalent(self):
        result = evaluate(profile=make_profile(
            ielts_score=None,
            language_test={"test_type": "PTE", "overall_score": 70},
        ))
        english = requirement(result, "english")
        self.assertEqual(english["status"], "not_evaluated")
        self.assertIn("cannot be compared directly", english["reason"])

    def test_missing_nationality(self):
        result = evaluate(profile=make_profile(nationality=None))
        self.assertEqual(requirement(result, "nationality")["status"], "missing_information")

    def test_unverified_record_is_never_eligible(self):
        result = evaluate(make_scholarship(verification_status="unverified"))
        self.assertEqual(result["status"], "not_evaluated")
        self.assertFalse(result["eligible"])
        self.assertTrue(result["satisfied"])  # requirements are still shown

    def test_stale_official_evidence_needs_verification(self):
        result = evaluate(make_scholarship(
            last_verified_date=TODAY - timedelta(days=181),
            deadline="15 January 2026",
        ))
        self.assertEqual(result["status"], "not_evaluated")
        self.assertFalse(result["eligible"])
        self.assertIn("over 180 days old", requirement(result, "source_evidence")["reason"])
        self.assertEqual(result["deadline"]["status"], "closed")

    def test_missing_official_source_or_verification_date_needs_verification(self):
        missing_url = evaluate(make_scholarship(official_info_url=None))
        missing_date = evaluate(make_scholarship(last_verified_date=None))
        self.assertEqual(missing_url["status"], "not_evaluated")
        self.assertIn("No valid official information page", requirement(missing_url, "source_evidence")["reason"])
        self.assertEqual(missing_date["status"], "not_evaluated")
        self.assertIn("No official-source verification date", requirement(missing_date, "source_evidence")["reason"])

    def test_insufficient_requirements(self):
        bare = make_scholarship(eligible_nationalities=None, pakistan_eligible=None, eligible_fields=None,
                                min_academic_requirement=None, english_requirement=None, bachelors_requirement=None)
        result = evaluate(bare)
        self.assertEqual(result["status"], "not_evaluated")
        self.assertFalse(result["eligible"])


class FreeTextTests(unittest.TestCase):
    def test_keyword_in_field_list_is_not_proof(self):
        scholarship = make_scholarship(eligible_fields="STEM (Science, Technology, Engineering, Computer Science) courses")
        result = evaluate(scholarship)
        field = requirement(result, "field")
        self.assertEqual(field["status"], "not_evaluated")
        self.assertIn("STEM", field["source_text"])
        self.assertEqual(result["status"], "not_evaluated")

    def test_rank_based_grades_need_manual_check(self):
        result = evaluate(make_scholarship(min_academic_requirement="Top 10% of graduating class"))
        self.assertEqual(requirement(result, "academic")["status"], "not_evaluated")

    def test_grade_on_other_scale(self):
        scholarship = make_scholarship(min_academic_requirement="GPA of at least 5.0/7.0 for 15%; 6.0/7.0 for 30%")
        self.assertEqual(requirement(evaluate(scholarship), "academic")["status"], "not_evaluated")
        same_scale = make_profile(cgpa=5.5, cgpa_scale=7.0)
        low = make_profile(cgpa=4.9, cgpa_scale=7.0)
        self.assertEqual(requirement(evaluate(scholarship, same_scale), "academic")["status"], "satisfied")
        self.assertEqual(requirement(evaluate(scholarship, low), "academic")["status"], "not_satisfied")

    def test_percentage_requirement(self):
        scholarship = make_scholarship(min_academic_requirement="Minimum 75% academic achievement")
        self.assertEqual(requirement(evaluate(scholarship), "academic")["status"], "not_evaluated")
        self.assertEqual(requirement(evaluate(scholarship, make_profile(cgpa=80, cgpa_scale=100)), "academic")["status"],
                         "satisfied")
        self.assertEqual(requirement(evaluate(scholarship, make_profile(cgpa=70, cgpa_scale=100)), "academic")["status"],
                         "not_satisfied")

    def test_cgpa_without_a_published_scale_needs_review(self):
        result = evaluate(make_scholarship(min_academic_requirement="Minimum CGPA 3.0"))
        self.assertEqual(requirement(result, "academic")["status"], "not_evaluated")

    def test_structured_gpa_compares_only_on_the_same_scale(self):
        scholarship = make_scholarship(
            academic_condition="numeric", min_gpa=3.0, min_gpa_scale=4.0,
            min_academic_requirement="Minimum CGPA 3.0/4.0",
        )
        result = evaluate(scholarship, make_profile(cgpa=8.0, cgpa_scale=10.0))
        self.assertEqual(requirement(result, "academic")["status"], "not_evaluated")

    def test_restricted_fields_use_target_preferences_not_current_field(self):
        scholarship = make_scholarship(
            discipline_scope="listed", eligible_disciplines=["Computer Science"],
            eligible_fields="Computer Science",
        )
        result = evaluate(scholarship, make_profile(field_of_study="Biology",
                                                     preferred_fields=["Computer Science"]))
        self.assertEqual(requirement(result, "field")["status"], "satisfied")

    def test_missing_target_field_does_not_fall_back_to_current_field(self):
        scholarship = make_scholarship(
            discipline_scope="listed", eligible_disciplines=["Computer Science"],
            eligible_fields="Computer Science",
        )
        result = evaluate(scholarship, make_profile(preferred_fields=[]))
        self.assertEqual(requirement(result, "field")["status"], "missing_information")

    def test_target_field_mismatch_needs_manual_review(self):
        scholarship = make_scholarship(
            discipline_scope="listed", eligible_disciplines=["Computer Science"],
            eligible_fields="Computer Science",
        )
        result = evaluate(scholarship, make_profile(preferred_fields=["Biology"]))
        self.assertEqual(requirement(result, "field")["status"], "not_evaluated")

    def test_duolingo_minimum_is_compared(self):
        scholarship = make_scholarship(
            english_requirement_type="test_required",
            english_requirement="Duolingo English Test 120",
            accepted_english_tests=["Duolingo English Test"],
            min_duolingo=120, min_ielts=None, min_toefl=None,
        )
        profile = make_profile(ielts_score=None, language_test={
            "test_type": "Duolingo English Test", "overall_score": 125,
        })
        self.assertEqual(requirement(evaluate(scholarship, profile), "english")["status"], "satisfied")
        profile.language_test["overall_score"] = 110
        self.assertEqual(requirement(evaluate(scholarship, profile), "english")["status"], "not_satisfied")

    def test_new_toefl_scale_needs_manual_review(self):
        scholarship = make_scholarship(
            english_requirement_type="test_required", english_requirement="TOEFL iBT 90",
            min_ielts=None, min_toefl=90,
        )
        profile = make_profile(ielts_score=None, language_test={
            "test_type": "TOEFL iBT", "overall_score": 5,
        })
        self.assertEqual(requirement(evaluate(scholarship, profile), "english")["status"], "not_evaluated")

    def test_moi_is_not_automatically_treated_as_an_exemption(self):
        scholarship = make_scholarship(
            english_requirement_type="test_required",
            english_requirement="IELTS 6.5 overall; MOI may be accepted",
            min_ielts=6.5,
        )
        profile = make_profile(ielts_score=None, language_test={
            "test_type": "No Test / Not Taken", "medium_of_instruction": "Yes",
        })
        english = requirement(evaluate(scholarship, profile), "english")
        self.assertEqual(english["status"], "not_evaluated")
        self.assertIn("not treated as a waiver", english["reason"])

    def test_section_score_requirements_are_not_inferred_from_overall_score(self):
        scholarship = make_scholarship(
            english_requirement_type="test_required",
            english_requirement="IELTS 6.5 overall and no band below 6.0",
            min_ielts=6.5,
        )
        english = requirement(evaluate(scholarship), "english")
        self.assertEqual(english["status"], "not_evaluated")

    def test_university_set_english_is_admission_scope(self):
        result = evaluate(make_scholarship(english_requirement="Yes - per the chosen programme's own requirement"))
        english = requirement(result, "english")
        self.assertEqual((english["status"], english["scope"]), ("not_evaluated", "admission"))
        self.assertEqual(result["status"], "eligible")  # admission checks don't block the scholarship result

    def test_country_list_needs_manual_check(self):
        scholarship = make_scholarship(pakistan_eligible="", eligible_nationalities="Citizens of a published list of 36 countries")
        result = evaluate(scholarship, make_profile(nationality="Kenya"))
        self.assertEqual(requirement(result, "nationality")["status"], "not_evaluated")

    def test_age_limit(self):
        scholarship = make_scholarship(age_requirement="Yes - under 30 years of age")
        self.assertEqual(requirement(evaluate(scholarship), "age")["status"], "satisfied")
        old = make_profile(date_of_birth=date(1990, 1, 1))
        self.assertEqual(requirement(evaluate(scholarship, old), "age")["status"], "not_satisfied")
        self.assertEqual(requirement(evaluate(scholarship, make_profile(date_of_birth=None)), "age")["status"],
                         "missing_information")

    def test_original_text_preserved(self):
        result = evaluate()
        self.assertEqual(requirement(result, "english")["source_text"], "Yes - IELTS 6.5 overall")


class StatedRestrictionTests(unittest.TestCase):
    """Wording below is copied from the scholarship records named in each test."""

    def assert_verify_manually(self, result):
        self.assertEqual(result["status"], "not_evaluated")
        self.assertFalse(result["eligible"])
        self.assertEqual(result["not_satisfied"], [])  # an unchecked rule never makes a student ineligible

    def adelaide(self, **overrides):  # scholarship 39
        data = dict(
            eligible_nationalities="Open to citizens of any country except Australia and New Zealand",
            pakistan_eligible="Yes - open to all nationalities except Australia/New Zealand",
            eligible_fields="Any discipline, with some program exclusions (e.g. Masters by Research, PhD, and certain professional programs are excluded)",
            min_academic_requirement="GPA of at least 5.0/7.0 (or equivalent) for a 15% scholarship; GPA of at least 6.0/7.0 (or equivalent) for a 30% scholarship",
            english_requirement="Yes - must meet the University of Adelaide's standard international-student English requirement",
            notes="Not available to students already receiving another scholarship covering more than 50% of tuition fees, or to Masters by Research/PhD applicants. "
                  "Because the benefit is a fixed 15-30% fee reduction (not full cost), classified as Partially Funded.",
        )
        data.update(overrides)
        return make_scholarship(**data)

    def test_adelaide_is_verify_manually(self):
        result = evaluate(self.adelaide())
        self.assert_verify_manually(result)
        self.assertEqual(requirement(result, "field")["status"], "not_evaluated")
        restriction = requirement(result, "restrictions")
        self.assertEqual((restriction["status"], restriction["scope"]), ("not_evaluated", "scholarship"))
        self.assertIn("more than 50% of tuition", restriction["source_text"])
        self.assertNotIn("Partially Funded", restriction["source_text"])

    def test_adelaide_real_requirements_still_decide(self):
        self.assertEqual(evaluate(self.adelaide(), make_profile(nationality="Australia"))["status"], "not_eligible")
        self.assertEqual(evaluate(self.adelaide(), make_profile(cgpa=4.9, cgpa_scale=7.0))["status"], "not_eligible")

    def test_any_field_without_a_limit_stays_satisfied(self):
        for text in ("All fields of study", "Any subject available as a postgraduate course at the University of Cambridge",
                     "All fields (applicants select from Turkish universities' full range of Master's programmes)"):
            self.assertEqual(requirement(evaluate(make_scholarship(eligible_fields=text)), "field")["status"], "satisfied", text)

    def test_limited_all_or_any_field_statements(self):
        for text in ("Any Master's programme offered at Sciences Po, subject to the exclusions listed in Notes",   # 16
                     "All English-taught Radboud Master's programmes (with stated exceptions)",                    # 10
                     "Any TU Delft MSc programme (2-year regular programmes only)",                                # 8
                     "Any field aligned to one of the six CSC development themes",                                 # 29
                     "Any field of study offered at the participating university"):                                # 24
            result = evaluate(make_scholarship(eligible_fields=text))
            self.assertEqual(requirement(result, "field")["status"], "not_evaluated", text)
            self.assert_verify_manually(result)

    def test_restrictions_in_notes(self):
        for text in ("Not awarded for a second Master's programme at UvA.",                                          # 6
                     "Cannot be combined with the Fulbright-Radboud Scholarship, Orange Tulip Scholarship, or Holland/NL Scholarship.",  # 10
                     "Only open to first-year Master's applicants, not current students.",                           # 14
                     "Excludes: 1-year Master's programmes, most dual-degree Master's (except specific listed ones).",  # 16
                     "Not eligible if holding British/dual British citizenship, UK residency at time of application.",  # 28
                     "CSC will not normally fund a second master's degree; those who already hold a UK master's are not eligible.",  # 29
                     "Applicants must not have studied/worked a year or more in a high-income country.",             # 30
                     "Must be self-funded/not already receiving another sponsorship at several participating universities.",  # 31
                     "Open only to women/those who identify as women. Requires demonstrated financial need via a means test.",  # 32
                     "This record covers Research Master's only; taught/coursework master's degrees are not RTP-eligible.",  # 38
                     "Not every German university participates, and the number of scholarships varies by institution."):  # 24
            result = evaluate(make_scholarship(notes=text))
            self.assert_verify_manually(result)
            self.assertTrue(requirement(result, "restrictions")["source_text"], text)

    def test_abbreviation_does_not_cut_the_quote(self):
        text = "Cannot be combined with other major scholarships (e.g. Eiffel). Benefit figures varied."
        self.assertEqual(requirement(evaluate(make_scholarship(notes=text)), "restrictions")["source_text"],
                         "Cannot be combined with other major scholarships (e.g. Eiffel).")

    def test_quotes_from_two_fields_stay_separate(self):
        scholarship = make_scholarship(eligible_nationalities="Passport holders and permanent residents of Pakistan (country-specific scheme; other cohorts exist)",
                                       notes="Only open to first-year Master's applicants.")  # 31, 14
        self.assertEqual(requirement(evaluate(scholarship), "restrictions")["source_text"],
                         "Passport holders and permanent residents of Pakistan (country-specific scheme; other cohorts exist). "
                         "Only open to first-year Master's applicants.")

    def test_condition_beside_a_nationality_rule(self):
        for text in ("Open to citizens of all countries except Türkiye (current or previous Turkish citizens are not eligible)",  # 1
                     "Open to first-time applicants from any non-European Union state whose household does not file taxes within the EU",  # 16
                     "Passport holders and permanent residents of Pakistan",                                          # 31
                     "Women who are passport holders and permanent residents of a defined list of countries"):        # 32
            self.assert_verify_manually(evaluate(make_scholarship(eligible_nationalities=text)))

    def test_information_in_notes_is_not_a_restriction(self):
        for text in (None, "",
                     "Highly competitive - around 25 awards made each year against 1,000+ applications.",             # 7
                     "Only around 8% of scholarship applicants admitted to a programme were nominated.",              # 12
                     "Does not cover living costs - applicants must fund those separately.",                          # 10
                     "Monthly stipend figure in TRY changes most years and must be re-verified.",                     # 4
                     "2026-2027 window already closed relative to current date; next cycle not yet announced.",       # 4
                     "Scholars must commit to returning to Pakistan for at least 2 years after the award.",           # 28
                     "The Orange Tulip Scholarship was found NOT to include Pakistan - correctly excluded from this dataset."):  # 5
            notes = f"{text or ''} No additional applicant restrictions."
            self.assertEqual(evaluate(make_scholarship(notes=notes))["status"], "eligible", text)

    def test_general_no_restrictions_declaration_resolves_unset_gender(self):
        result = evaluate(make_scholarship(
            gender_restriction=None,
            notes="Awards are announced annually. No additional applicant restrictions.",
        ))
        self.assertEqual(result["status"], "eligible")
        self.assertNotIn("gender", [item["requirement"] for item in result["needs_verification"]])

    def test_unset_gender_without_general_declaration_needs_verification(self):
        result = evaluate(make_scholarship(gender_restriction=None, notes=None))
        self.assertEqual(requirement(result, "gender")["status"], "not_evaluated")
        self.assertEqual(result["status"], "not_evaluated")

    def test_general_declaration_does_not_override_explicit_gender_restriction(self):
        result = evaluate(make_scholarship(
            gender_restriction="women",
            notes="No additional applicant restrictions.",
        ))
        self.assertEqual(requirement(result, "gender")["status"], "not_evaluated")
        self.assertEqual(result["status"], "not_evaluated")

    def test_general_declaration_does_not_hide_gender_restriction_in_notes(self):
        result = evaluate(make_scholarship(
            gender_restriction=None,
            notes="Open only to women. No additional applicant restrictions.",
        ))
        restriction = requirement(result, "restrictions")
        self.assertEqual(restriction["status"], "not_evaluated")
        self.assertIn("Open only to women", restriction["source_text"])
        self.assertEqual(result["status"], "not_evaluated")

    def test_general_declaration_does_not_clear_financial_need_tag(self):
        result = evaluate(make_scholarship(
            gender_restriction=None,
            applicant_restrictions=["financial_need_required"],
            notes="No additional applicant restrictions.",
        ))
        restrictions = requirement(result, "restrictions")
        self.assertEqual(restrictions["status"], "not_evaluated")
        self.assertIn("financial need must be shown", restrictions["reason"])
        self.assertEqual(result["status"], "not_evaluated")

    def test_general_declaration_does_not_override_unverified_status(self):
        result = evaluate(make_scholarship(
            gender_restriction=None,
            verification_status="unverified",
            notes="No additional applicant restrictions.",
        ))
        self.assertEqual(result["status"], "not_evaluated")
        self.assertEqual(result["outcome"], "verify_manually")

    def test_annual_country_list(self):
        malaysia = make_scholarship(pakistan_eligible="Yes - explicitly confirmed on the official MIS 2022 recipient-country list; "
                                                      "current-year recipient-country list should be re-confirmed on mohe.gov.my")  # 20
        result = evaluate(malaysia)
        self.assertEqual(requirement(result, "nationality")["status"], "not_evaluated")
        self.assert_verify_manually(result)
        italy = make_scholarship(notes="The eligible-countries list, exact deadline, and grant duration are republished annually.")  # 25
        self.assert_verify_manually(evaluate(italy))

    def test_field_specific_grade_tier(self):
        turkey = make_scholarship(min_academic_requirement="Minimum 75% academic achievement (minimum 90% for Health Sciences fields: Medicine, Dentistry, Pharmacy)")  # 1
        self.assertEqual(requirement(evaluate(turkey, make_profile(cgpa=80, cgpa_scale=100)), "academic")["status"], "satisfied")
        result = evaluate(turkey, make_profile(field_of_study="Biology", preferred_fields=["Pharmacy"],
                                                cgpa=80, cgpa_scale=100))
        self.assertEqual(requirement(result, "academic")["status"], "not_evaluated")
        self.assert_verify_manually(result)
        self.assertEqual(evaluate(turkey, make_profile(field_of_study="Pharmacy", preferred_fields=["Pharmacy"],
                                                        cgpa=70, cgpa_scale=100))["status"], "not_eligible")

    def test_missing_profile_data_comes_before_manual_checks(self):
        self.assertEqual(evaluate(self.adelaide(), make_profile(cgpa=0.0, cgpa_scale=7.0))["status"], "not_eligible")

    def test_restriction_never_overrides_an_unverified_record(self):
        self.assert_verify_manually(evaluate(self.adelaide(verification_status="unverified")))

    def test_deadline_is_independent_of_restrictions(self):
        closed = evaluate(self.adelaide(deadline="15 January 2026"))
        self.assertEqual((closed["status"], closed["deadline"]["status"]), ("not_evaluated", "closed"))
        upcoming = evaluate(self.adelaide(deadline="15 January 2027"))
        self.assertEqual((upcoming["status"], upcoming["deadline"]["status"]), ("not_evaluated", "open"))


class DeadlineTests(unittest.TestCase):
    def test_open(self):
        result = deadline_status("2027-28 entry: 8 December 2026 or 6 January 2027", TODAY)
        self.assertEqual((result["status"], result["date"], result["days_left"]), ("open", "2026-12-08", 40))

    def test_expired(self):
        self.assertEqual(deadline_status("10 January - 20 February 2026", TODAY)["status"], "closed")

    def test_unknown(self):
        self.assertEqual(deadline_status("Typically 1 February (varies)", TODAY)["status"], "unknown")
        self.assertEqual(deadline_status(None, TODAY)["status"], "unknown")

    def test_no_separate_deadline(self):
        self.assertEqual(deadline_status("No separate deadline - awarded with the offer", TODAY)["status"],
                         "no_separate_deadline")

    def test_closed_deadline_noted_but_not_eligibility(self):
        result = evaluate(make_scholarship(deadline="15 January 2026"))
        self.assertEqual(result["deadline"]["status"], "closed")
        self.assertEqual(result["status"], "eligible")
        self.assertTrue(any("deadline has passed" in note for note in result["notes"]))


class ApiTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        fields = {k: v for k, v in vars(make_scholarship()).items() if k != "id"}
        self.verified = Scholarship(**fields)
        self.unverified = Scholarship(**{**fields, "name": "Unverified", "verification_status": "unverified"})
        self.blocked = Scholarship(**{**fields, "name": "Blocked", "pakistan_eligible": "No - excluded"})
        self.alice = User(email="alice@example.com", hashed_password="x", full_name="Alice")
        self.bob = User(email="bob@example.com", hashed_password="x", full_name="Bob")
        self.carol = User(email="carol@example.com", hashed_password="x", full_name="Carol")  # no profile
        self.db.add_all([self.verified, self.unverified, self.blocked, self.alice, self.bob, self.carol])
        self.db.flush()
        self.db.add_all([
            StudentProfile(user_id=self.alice.id, nationality="Pakistan", degree_level="Bachelor's", cgpa=3.4,
                           cgpa_scale=4.0, ielts_score=7.0, field_of_study="Computer Science"),
            StudentProfile(user_id=self.bob.id, nationality="Germany", degree_level="Bachelor's", cgpa=1.0,
                           cgpa_scale=4.0, ielts_score=5.0, field_of_study="Law"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def list_for(self, user, **kwargs):
        options = {"eligible_only": False, "include_unverified": False, **kwargs}
        return api.check_all_scholarships(db=self.db, current_user=user, **options)

    def test_list_hides_unverified_by_default(self):
        names = [r["scholarship_name"] for r in self.list_for(self.alice)]
        self.assertNotIn("Unverified", names)
        self.assertEqual(names[0], "Test Scholarship")  # eligible sorts first

    def test_include_unverified(self):
        results = {r["scholarship_name"]: r for r in self.list_for(self.alice, include_unverified=True)}
        self.assertEqual(results["Unverified"]["status"], "not_evaluated")

    def test_eligible_only_filter(self):
        results = self.list_for(self.alice, eligible_only=True)
        self.assertEqual([r["scholarship_name"] for r in results], ["Test Scholarship"])

    def test_one_scholarship(self):
        result = api.check_one_scholarship(self.blocked.id, db=self.db, current_user=self.alice)
        self.assertEqual(result["status"], "not_eligible")

    def test_unknown_scholarship(self):
        with self.assertRaises(HTTPException) as error:
            api.check_one_scholarship(99999, db=self.db, current_user=self.alice)
        self.assertEqual(error.exception.status_code, 404)

    def test_missing_profile(self):
        with self.assertRaises(HTTPException) as error:
            self.list_for(self.carol)
        self.assertEqual(error.exception.status_code, 404)
        self.assertIn("Profile", error.exception.detail)

    def test_results_use_only_the_signed_in_students_profile(self):
        alice = api.check_one_scholarship(self.verified.id, db=self.db, current_user=self.alice)
        bob = api.check_one_scholarship(self.verified.id, db=self.db, current_user=self.bob)
        self.assertEqual(alice["status"], "eligible")
        self.assertEqual(bob["status"], "not_eligible")  # Bob's low CGPA and IELTS, never Alice's

    def test_invalid_token(self):
        with self.assertRaises(HTTPException) as error:
            get_current_user(token="not-a-real-token", db=self.db)
        self.assertEqual(error.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
