"""
Eligibility with structured scholarship fields. Needs no database.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
from datetime import date

from app.schemas.eligibility import ScholarshipEligibilityResult
from app.services.profile_improvement import build_guidance
from app.services.scholarship_eligibility import evaluate_scholarship
from test_scholarship_eligibility import TODAY, make_profile, make_scholarship, requirement

CLEAR = dict(
    structured_data_version=1, nationality_scope="all", eligible_degree_levels=["Master's"],
    required_previous_degree="Bachelor's", discipline_scope="all", academic_condition="numeric", min_gpa=3.0,
    min_gpa_scale=4.0, english_requirement_type="test_required", accepted_english_tests=["IELTS", "TOEFL"], min_ielts=6.5,
    deadline_type="fixed", application_deadline_date=date(2027, 1, 15), verification_basis="official_source",
    min_academic_requirement="Minimum CGPA 3.0/4.0",
)


def structured(**overrides):
    return make_scholarship(**{**CLEAR, **overrides})


def evaluate(scholarship=None, profile=None):
    return evaluate_scholarship(scholarship or structured(), profile or make_profile(), today=TODAY)


def status(key, scholarship, profile=None):
    return requirement(evaluate(scholarship, profile), key)["status"]


class OutcomeTests(unittest.TestCase):
    def test_all_requirements_met(self):
        result = evaluate()
        self.assertEqual((result["status"], result["outcome"]), ("eligible", "eligible"))

    def test_three_outcomes(self):
        self.assertEqual(evaluate(profile=make_profile(ielts_score=5.0))["outcome"], "not_eligible")
        missing = evaluate(profile=make_profile(ielts_score=None))
        self.assertEqual((missing["status"], missing["outcome"]), ("missing_information", "verify_manually"))
        manual = evaluate(structured(nationality_scope="not_specified"))
        self.assertEqual((manual["status"], manual["outcome"]), ("not_evaluated", "verify_manually"))

    def test_response_schema_accepts_the_result(self):
        result = ScholarshipEligibilityResult(**evaluate(structured(gender_restriction="women", deadline_type="rolling")))
        self.assertEqual(result.deadline.status, "rolling")

    def test_unverified_record_is_never_eligible(self):
        self.assertEqual(evaluate(structured(verification_status="unverified"))["status"], "not_evaluated")

    def test_secondary_sources_stop_a_firm_result(self):
        result = evaluate(structured(verification_basis="mixed_sources"))
        self.assertEqual(result["status"], "not_evaluated")
        self.assertEqual(requirement(result, "source_evidence")["status"], "not_evaluated")

    def test_explicit_no_previous_degree_is_non_applicable_not_satisfied(self):
        result = evaluate(structured(required_previous_degree="No previous degree required"))
        requirement_names = [
            item["requirement"]
            for group in ("satisfied", "not_satisfied", "missing_information", "needs_verification")
            for item in result[group]
        ]
        self.assertNotIn("degree_level", requirement_names)
        self.assertEqual(result["status"], "eligible")


class MissingScholarshipRequirementTests(unittest.TestCase):
    def test_missing_requirement_fields_are_not_treated_as_unrestricted(self):
        cases = (
            ("nationality", structured(nationality_scope=None, eligible_nationalities=None, pakistan_eligible=None)),
            ("degree_level", structured(degree_level=None, eligible_degree_levels=None)),
            ("field", structured(discipline_scope=None, eligible_fields=None)),
            ("academic", structured(academic_condition=None, min_academic_requirement=None)),
            ("english", structured(english_requirement_type=None, english_requirement=None,
                                   min_ielts=None, min_toefl=None, min_duolingo=None)),
            ("age", structured(age_requirement=None, min_age=None, max_age=None)),
            ("work_experience", structured(work_experience=None)),
            ("gender", structured(gender_restriction=None, notes=None)),
            ("residency", structured(residency_requirement=None, notes=None)),
            ("restrictions", structured(applicant_restrictions=None, notes=None)),
        )
        for key, record in cases:
            with self.subTest(requirement=key):
                self.assertEqual(requirement(evaluate(record), key)["status"], "not_evaluated")

    def test_missing_cgpa_requirement_information_needs_verification(self):
        record = structured(
            academic_condition="numeric",
            min_gpa=None,
            min_gpa_scale=None,
            min_percentage=None,
            min_academic_requirement="Not specified",
        )
        result = evaluate(record)
        self.assertEqual(requirement(result, "academic")["status"], "not_evaluated")
        self.assertEqual(result["status"], "not_evaluated")

    def test_multiple_unknown_requirements_accumulate_and_block_eligibility(self):
        record = structured(
            eligible_nationalities="Not specified",
            pakistan_eligible="",
            discipline_scope="all",
            eligible_fields="Not specified",
        )
        result = evaluate(record)
        unknown = {item["requirement"] for item in result["needs_verification"]}
        self.assertTrue({"nationality", "field"} <= unknown)
        self.assertEqual(result["status"], "not_evaluated")
        self.assertFalse(result["eligible"])

    def test_known_unmet_requirement_wins_over_other_unknown_requirements(self):
        record = structured(
            eligible_nationalities="Not specified",
            pakistan_eligible="",
            discipline_scope="all",
            eligible_fields="Not specified",
        )
        result = evaluate(record, make_profile(ielts_score=5.0))
        unknown = {item["requirement"] for item in result["needs_verification"]}
        self.assertTrue({"nationality", "field"} <= unknown)
        self.assertEqual(requirement(result, "english")["status"], "not_satisfied")
        self.assertEqual((result["status"], result["outcome"]), ("not_eligible", "not_eligible"))

    def test_admission_scoped_requirement_does_not_block_scholarship_eligibility(self):
        record = structured(
            academic_condition="set_by_institution",
            min_gpa=None,
            min_gpa_scale=None,
            min_academic_requirement="Per the chosen programme's own requirement",
        )
        result = evaluate(record)
        academic = requirement(result, "academic")
        self.assertEqual((academic["status"], academic["scope"]), ("not_evaluated", "admission"))
        self.assertEqual(result["status"], "eligible")
        self.assertTrue(any("checked during admission" in note for note in result["notes"]))

    def test_financial_need_tag_needs_verification_not_satisfaction(self):
        result = evaluate(structured(applicant_restrictions=["financial_need_required"]))
        restrictions = requirement(result, "restrictions")
        self.assertEqual(restrictions["status"], "not_evaluated")
        self.assertNotIn("restrictions", [item["requirement"] for item in result["satisfied"]])
        self.assertEqual((result["status"], result["not_satisfied"]), ("not_evaluated", []))


class NationalityTests(unittest.TestCase):
    def test_no_nationality_restrictions_are_non_applicable(self):
        result = evaluate(structured(
            nationality_scope=None,
            eligible_nationalities="No nationality restrictions",
            pakistan_eligible="",
        ))
        self.assertNotIn("nationality", [item["requirement"] for item in result["satisfied"]])
        self.assertEqual(result["status"], "eligible")

    def test_structured_all_with_unspecified_text_needs_manual_verification(self):
        record = structured(nationality_scope="all", eligible_nationalities="Not specified", pakistan_eligible="")
        result = evaluate(record)
        self.assertEqual(requirement(result, "nationality")["status"], "not_evaluated")
        self.assertEqual((result["status"], result["outcome"]), ("not_evaluated", "verify_manually"))

    def test_structured_all_conflicts_with_textual_exclusion(self):
        record = structured(
            nationality_scope="all",
            eligible_nationalities="Open to all nationalities except Pakistan",
            pakistan_eligible="",
        )
        item = requirement(evaluate(record), "nationality")
        self.assertEqual((item["status"], item["conflict"]), ("not_evaluated", True))

    def test_structured_and_textual_all_nationalities_are_consistent(self):
        record = structured(
            nationality_scope="all",
            eligible_nationalities="Open to all nationalities",
            pakistan_eligible="",
        )
        self.assertEqual(requirement(evaluate(record), "nationality")["status"], "satisfied")

    def test_all_except(self):
        record = structured(nationality_scope="all_except", excluded_countries=["Turkey"], pakistan_eligible="",
                            eligible_nationalities="Open to citizens of all countries except Türkiye")
        self.assertEqual(status("nationality", record, make_profile(nationality="Türkiye")), "not_satisfied")
        self.assertEqual(status("nationality", record, make_profile(nationality="India")), "satisfied")

    def test_regions(self):
        record = structured(nationality_scope="all_except", excluded_regions=["EU"], pakistan_eligible="",
                            eligible_nationalities="Open to any non-European Union state")
        self.assertEqual(status("nationality", record, make_profile(nationality="Germany")), "not_satisfied")
        self.assertEqual(status("nationality", record, make_profile(nationality="Norway")), "satisfied")

    def test_complete_list_settles_text_that_cant_be_read(self):
        record = structured(nationality_scope="listed", eligible_countries=["India", "Kenya"], pakistan_eligible="",
                            eligible_nationalities="Citizens of a published list of countries")
        self.assertEqual(status("nationality", record, make_profile(nationality="Kenya")), "satisfied")
        self.assertEqual(status("nationality", record, make_profile(nationality="Brazil")), "not_satisfied")

    def test_partial_list_never_rules_a_country_out(self):
        record = structured(nationality_scope="published_list", eligible_countries=["Pakistan"], pakistan_eligible="",
                            eligible_nationalities="Citizens of 160+ countries, including Pakistan")
        self.assertEqual(status("nationality", record), "satisfied")
        self.assertEqual(status("nationality", record, make_profile(nationality="Kenya")), "not_evaluated")

    def test_condition_beside_a_listed_country(self):
        record = structured(nationality_scope="listed", eligible_countries=["Belarus"], pakistan_eligible="",
                            eligible_nationalities="Citizens of Georgia, Belarus (democratic forces)")
        self.assertEqual(status("nationality", record, make_profile(nationality="Belarus")), "not_evaluated")

    def test_outside_wording(self):
        record = structured(nationality_scope="all_except", excluded_countries=["United Kingdom"], pakistan_eligible="",
                            eligible_nationalities="Citizens of any country outside the United Kingdom")
        self.assertEqual(status("nationality", record, make_profile(nationality="United Kingdom")), "not_satisfied")

    def test_pakistan_recheck_outlives_a_structured_answer(self):
        record = structured(nationality_scope="all", pakistan_eligible="Yes - current list should be re-confirmed")
        self.assertEqual(status("nationality", record), "not_evaluated")

    def test_missing_nationality(self):
        self.assertEqual(status("nationality", structured(), make_profile(nationality=None)), "missing_information")

    def test_scope_not_specified_is_not_open(self):
        record = structured(nationality_scope="not_specified", pakistan_eligible="", eligible_nationalities="International students")
        self.assertEqual(status("nationality", record), "not_evaluated")


class DegreeAndFieldTests(unittest.TestCase):
    def test_degree_levels(self):
        self.assertEqual(status("degree_level", structured()), "satisfied")
        self.assertEqual(status("degree_level", structured(), make_profile(degree_level=None)), "missing_information")

    def test_not_for_masters(self):
        record = structured(degree_level="PhD", eligible_degree_levels=["PhD"], required_previous_degree="Master's")
        self.assertEqual(status("degree_level", record), "not_satisfied")

    def test_previous_degree(self):
        record = structured(required_previous_degree="Master's")
        self.assertEqual(status("degree_level", record), "not_satisfied")

    def test_degree_conflict(self):
        item = requirement(evaluate(structured(degree_level="PhD")), "degree_level")
        self.assertEqual((item["status"], item["conflict"]), ("not_evaluated", True))

    def test_all_fields(self):
        self.assertEqual(status("field", structured(eligible_fields="Bachelor's and Master's programmes offered at Lund")), "satisfied")

    def test_no_field_restrictions_are_non_applicable(self):
        result = evaluate(structured(discipline_scope=None, eligible_fields="No field restrictions"))
        self.assertNotIn("field", [item["requirement"] for item in result["satisfied"]])
        self.assertEqual(result["status"], "eligible")

    def test_structured_all_fields_with_unspecified_text_needs_manual_verification(self):
        record = structured(discipline_scope="all", eligible_fields="Not specified")
        result = evaluate(record)
        self.assertEqual(requirement(result, "field")["status"], "not_evaluated")
        self.assertEqual((result["status"], result["outcome"]), ("not_evaluated", "verify_manually"))

    def test_structured_all_fields_conflicts_with_restricted_text(self):
        record = structured(discipline_scope="all", eligible_fields="Only Computer Science")
        item = requirement(evaluate(record), "field")
        self.assertEqual((item["status"], item["conflict"]), ("not_evaluated", True))

    def test_structured_and_textual_all_fields_are_consistent(self):
        record = structured(discipline_scope="all", eligible_fields="All fields")
        self.assertEqual(requirement(evaluate(record), "field")["status"], "satisfied")

    def test_limited_text_is_not_overridden_by_all(self):
        record = structured(eligible_fields="Any field of study offered at the participating university")
        self.assertEqual(status("field", record), "not_evaluated")

    def test_listed_field(self):
        record = structured(discipline_scope="listed", eligible_disciplines=["Accounting"], eligible_fields="Accounting")
        self.assertEqual(status("field", record, make_profile(preferred_fields=["accounting"])), "satisfied")
        other = evaluate(record, make_profile(preferred_fields=["Finance"]))
        self.assertEqual(requirement(other, "field")["status"], "not_evaluated")  # names aren't a shared vocabulary
        self.assertEqual(other["not_satisfied"], [])
        self.assertEqual(status("field", record, make_profile(preferred_fields=[])), "missing_information")

    def test_restricted_list_is_never_a_match(self):
        record = structured(discipline_scope="restricted", eligible_disciplines=["Engineering"], eligible_fields="Primarily engineering")
        self.assertEqual(status("field", record, make_profile(field_of_study="Engineering")), "not_evaluated")

    def test_unspecified_field(self):
        self.assertEqual(status("field", structured(discipline_scope="not_specified", eligible_fields=None)), "not_evaluated")


class AcademicTests(unittest.TestCase):
    def test_same_scale(self):
        self.assertEqual(status("academic", structured()), "satisfied")
        self.assertEqual(status("academic", structured(), make_profile(cgpa=2.9)), "not_satisfied")

    def test_different_scales_are_not_converted(self):
        record = structured(min_gpa=5.0, min_gpa_scale=7.0, min_academic_requirement="GPA of at least 5.0/7.0 (or equivalent)")
        for cgpa in (3.9, 1.0):
            result = evaluate(record, make_profile(cgpa=cgpa))
            self.assertEqual(requirement(result, "academic")["status"], "not_evaluated")
            self.assertEqual(result["not_satisfied"], [])

    def test_unknown_minimum_scale(self):
        record = structured(min_gpa_scale=None, min_academic_requirement=None)
        self.assertEqual(status("academic", record), "not_evaluated")

    def test_unknown_student_scale(self):
        self.assertEqual(status("academic", structured(), make_profile(cgpa_scale=None)), "missing_information")

    def test_percentage(self):
        record = structured(min_gpa=None, min_gpa_scale=None, min_percentage=75.0,
                            min_academic_requirement="Minimum 75% academic achievement")
        self.assertEqual(status("academic", record, make_profile(cgpa=80, cgpa_scale=100)), "satisfied")
        self.assertEqual(status("academic", record, make_profile(cgpa=70, cgpa_scale=100)), "not_satisfied")
        self.assertEqual(status("academic", record), "not_evaluated")      # a CGPA out of 4 isn't a percentage

    def test_health_tier_stays_in_force(self):
        record = structured(min_gpa=None, min_gpa_scale=None, min_percentage=75.0,
                            min_academic_requirement="Minimum 75% academic achievement (minimum 90% for Health Sciences fields)")
        profile = make_profile(cgpa=80, cgpa_scale=100, preferred_fields=["Pharmacy"])
        self.assertEqual(status("academic", record, profile), "not_evaluated")

    def test_number_in_a_class_condition_isnt_compared(self):
        record = structured(academic_condition="degree_class", min_gpa=None, min_gpa_scale=None,
                            min_academic_requirement="CGPA 3.0 or Second Class Upper")
        self.assertEqual(status("academic", record, make_profile(cgpa=2.0)), "not_evaluated")

    def test_conditions_that_need_a_person(self):
        for condition in ("merit_based", "class_rank", "degree_class", "set_by_institution", "not_specified"):
            record = structured(academic_condition=condition, min_gpa=None, min_gpa_scale=None, min_academic_requirement="Excellent results")
            self.assertEqual(status("academic", record), "not_evaluated", condition)

    def test_unspecified_blocks_eligible(self):
        record = structured(academic_condition="not_specified", min_gpa=None, min_gpa_scale=None, min_academic_requirement="Not specified")
        self.assertEqual(evaluate(record)["status"], "not_evaluated")

    def test_conflict_with_text(self):
        result = evaluate(structured(min_academic_requirement="Minimum CGPA 3.5/4.0"))
        item = requirement(result, "academic")
        self.assertEqual((item["status"], item["conflict"]), ("not_evaluated", True))
        self.assertIn("3.5/4.0", item["source_text"])
        self.assertEqual(result["status"], "not_evaluated")

    def test_hedged_text_conflicts(self):
        item = requirement(evaluate(structured(min_academic_requirement="Typically at least 3.0/4.0")), "academic")
        self.assertTrue(item["conflict"])


class EnglishTests(unittest.TestCase):
    def record(self, **overrides):
        return structured(english_requirement="IELTS 6.5 overall", **overrides)

    def test_score(self):
        self.assertEqual(status("english", self.record()), "satisfied")
        self.assertEqual(status("english", self.record(), make_profile(ielts_score=6.0)), "not_satisfied")

    def test_missing_score(self):
        self.assertEqual(status("english", self.record(), make_profile(ielts_score=None)), "missing_information")

    def test_toefl_minimum(self):
        record = self.record(min_toefl=90)
        self.assertEqual(status("english", record, make_profile(ielts_score=None, toefl_score=95)), "satisfied")
        self.assertEqual(status("english", record, make_profile(ielts_score=None, toefl_score=80)), "not_satisfied")

    def test_test_without_a_minimum(self):
        self.assertEqual(status("english", self.record(min_toefl=None), make_profile(ielts_score=None, toefl_score=100)), "not_evaluated")

    def test_only_a_duolingo_minimum(self):
        record = structured(min_ielts=None, min_duolingo=115, accepted_english_tests=["Duolingo", "IELTS"],
                            english_requirement="A valid certificate is required")
        self.assertEqual(status("english", record), "not_evaluated")

    def test_test_not_accepted(self):
        record = self.record(accepted_english_tests=["TOEFL"], min_toefl=90)
        self.assertEqual(status("english", record), "not_evaluated")

    def test_band_rule(self):
        record = structured(english_requirement="IELTS 6.5 overall with no band below 6.0")
        self.assertEqual(status("english", record), "not_evaluated")

    def test_exemption_softens_a_low_score(self):
        record = structured(english_requirement="IELTS 6.5 unless exempt")
        self.assertEqual(status("english", record, make_profile(ielts_score=5.0)), "not_evaluated")

    def test_unspecified_isnt_no_test(self):
        record = structured(english_requirement_type="not_specified", min_ielts=None, english_requirement="Not specified")
        result = evaluate(record)
        self.assertEqual(requirement(result, "english")["status"], "not_evaluated")
        self.assertEqual(result["status"], "not_evaluated")

    def test_set_by_institution_is_an_admission_check(self):
        record = structured(english_requirement_type="set_by_institution", min_ielts=None,
                            english_requirement="Yes - per the chosen programme's own requirement")
        self.assertEqual(requirement(evaluate(record), "english")["scope"], "admission")

    def test_not_required_conflict(self):
        record = structured(english_requirement_type="not_required", min_ielts=None, english_requirement="Yes - IELTS 6.5 overall")
        result = evaluate(record)
        self.assertTrue(requirement(result, "english")["conflict"])
        self.assertEqual(result["status"], "not_evaluated")

    def test_not_required_conflicts_with_unspecified_text(self):
        record = structured(
            english_requirement_type="not_required",
            min_ielts=None,
            english_requirement="Not specified",
        )
        result = evaluate(record)
        english = requirement(result, "english")
        self.assertEqual((english["status"], english["conflict"]), ("not_evaluated", True))
        self.assertEqual((result["status"], result["outcome"]), ("not_evaluated", "verify_manually"))

    def test_score_conflict(self):
        self.assertTrue(requirement(evaluate(structured(english_requirement="IELTS 7.5 overall")), "english")["conflict"])


class AgeGenderResidencyTests(unittest.TestCase):
    def test_age_limits(self):
        record = structured(max_age=29, age_requirement="Yes - under 30 years of age")
        self.assertEqual(status("age", record), "satisfied")
        self.assertEqual(status("age", record, make_profile(date_of_birth=date(1990, 1, 1))), "not_satisfied")
        self.assertEqual(status("age", record, make_profile(date_of_birth=None)), "missing_information")

    def test_minimum_age_without_text(self):
        record = structured(min_age=18, age_requirement=None)
        self.assertEqual(status("age", record), "satisfied")
        self.assertEqual(status("age", record, make_profile(date_of_birth=date(2015, 1, 1))), "not_satisfied")

    def test_stated_limit_with_no_structured_value_conflicts(self):  # Eiffel: 25, some pages cite 29
        record = structured(age_requirement="Up to 25 years old (some institution pages cite up to 29)")
        result = evaluate(record, make_profile(date_of_birth=date(1990, 1, 1)))
        self.assertTrue(requirement(result, "age")["conflict"])
        self.assertEqual(result["not_satisfied"], [])

    def test_different_limit_conflicts(self):
        self.assertTrue(requirement(evaluate(structured(max_age=35, age_requirement="Under 30")), "age")["conflict"])

    def test_gender(self):
        result = evaluate(structured(gender_restriction="women"))
        self.assertEqual(requirement(result, "gender")["status"], "not_evaluated")
        self.assertEqual((result["status"], result["not_satisfied"]), ("not_evaluated", []))

    def test_residency(self):
        result = evaluate(structured(residency_requirement="Currently residing in Pakistan for at least 24 months.",
                                     applicant_restrictions=["residency_required"]))
        self.assertIn("24 months", requirement(result, "residency")["source_text"])
        self.assertEqual(result["status"], "not_evaluated")


class RestrictionTests(unittest.TestCase):
    def test_tags_need_a_manual_check(self):
        for tag in ("second_masters_excluded", "previous_scholarship_excluded", "high_income_study_excluded",
                    "other_funding_excluded", "fee_paying_only", "first_time_applicant"):
            result = evaluate(structured(applicant_restrictions=[tag]))
            self.assertEqual(requirement(result, "restrictions")["status"], "not_evaluated", tag)
            self.assertEqual((result["status"], result["not_satisfied"]), ("not_evaluated", []), tag)

    def test_tag_is_explained(self):
        reason = requirement(evaluate(structured(applicant_restrictions=["second_masters_excluded"])), "restrictions")["reason"]
        self.assertIn("not for a second Master's", reason)

    def test_award_conditions_are_notes(self):
        result = evaluate(structured(applicant_restrictions=["return_home_required", "nationality_cap"]))
        self.assertEqual(result["status"], "eligible")
        self.assertTrue(any("return home" in note for note in result["notes"]))

    def test_restriction_only_in_the_text(self):
        result = evaluate(structured(notes="Open only to women. Cannot be combined with other awards."))
        self.assertEqual(result["status"], "not_evaluated")
        self.assertIn("Open only to women", requirement(result, "restrictions")["source_text"])

    def test_structured_clear_doesnt_hide_a_restriction_in_the_notes(self):
        record = structured(applicant_restrictions=[], gender_restriction=None, notes="Not available to current students.")
        self.assertEqual(evaluate(record)["status"], "not_evaluated")

    def test_structured_doesnt_overrule_a_stated_exclusion(self):
        record = structured(pakistan_eligible="No - Pakistan is not on the eligible list")
        item = requirement(evaluate(record), "nationality")
        self.assertEqual((item["status"], item["conflict"]), ("not_evaluated", True))
        self.assertIn("not on the eligible list", item["source_text"])

    def test_verification_status_is_never_changed(self):
        record = structured(pakistan_eligible="No - excluded")
        self.assertEqual(evaluate(record)["verification_status"], "verified")
        self.assertEqual(record.verification_status, "verified")


class DeadlineTests(unittest.TestCase):
    def deadline(self, **overrides):
        return evaluate(structured(**overrides))["deadline"]

    def test_open(self):
        result = self.deadline(application_open_date=date(2026, 10, 1))
        self.assertEqual((result["status"], result["date"]), ("open", "2027-01-15"))

    def test_closed(self):
        result = self.deadline(application_deadline_date=date(2026, 2, 20), deadline="20 February 2026")
        self.assertEqual(result["status"], "closed")
        self.assertIn("doesn't change", result["message"])

    def test_upcoming(self):
        result = self.deadline(application_open_date=date(2026, 11, 8))
        self.assertEqual((result["status"], result["days_left"], result["opens_on"]), ("upcoming", 10, "2026-11-08"))

    def test_rolling(self):
        self.assertEqual(self.deadline(deadline_type="rolling", application_deadline_date=None)["status"], "rolling")

    def test_no_separate_deadline(self):
        self.assertEqual(self.deadline(deadline_type="no_separate_deadline")["status"], "no_separate_deadline")

    def test_vague_text_gives_no_date(self):
        for kind in ("annual", "varies_by_institution", "not_specified"):
            result = self.deadline(deadline_type=kind, application_deadline_date=None, deadline="Varies (e.g. 31 August 2026)")
            self.assertEqual((result["status"], result["date"]), ("unknown", None), kind)
            self.assertIn("31 August 2026", result["text"])

    def test_later_date_in_the_wording_isnt_closed(self):
        result = self.deadline(application_deadline_date=date(2026, 10, 1), deadline="1 October 2026 or 6 January 2027")
        self.assertEqual(result["status"], "unknown")

    def test_closed_deadline_doesnt_change_eligibility(self):
        result = evaluate(structured(application_deadline_date=date(2026, 2, 20), deadline="20 February 2026"))
        self.assertEqual((result["status"], result["deadline"]["status"]), ("eligible", "closed"))
        self.assertTrue(any("separate from your eligibility" in note for note in result["notes"]))

    def test_open_deadline_doesnt_rescue_a_failed_requirement(self):
        self.assertEqual(evaluate(profile=make_profile(cgpa=1.0))["status"], "not_eligible")


class GuidanceTests(unittest.TestCase):
    def test_new_requirements_reach_profile_improvement(self):
        profile = make_profile(skills=None, research_interests=None, preferred_countries=None,
                               preferred_fields=[], field_of_study=None)
        record = structured(discipline_scope="listed", eligible_disciplines=["Accounting"], gender_restriction="women",
                            residency_requirement="Must live in Pakistan.", official_url="https://example.org")
        ids = [item["id"] for item in build_guidance(profile, [record], today=TODAY)["recommendations"]]
        self.assertIn("missing-information-field", ids)
        self.assertIn("manual-verification-restrictions", ids)


if __name__ == "__main__":
    unittest.main()
