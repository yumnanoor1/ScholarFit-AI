"""
Eligibility engine unit tests (database ki zaroorat nahi).
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
from types import SimpleNamespace

from app.services.eligibility_engine import check_program_eligibility


def make_profile(**overrides):
    data = {
        "degree_level": "Bachelor's",
        "field_of_study": "Computer Science",
        "cgpa": 3.5,
        "cgpa_scale": 4.0,
        "ielts_score": 7.0,
        "toefl_score": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_program(**overrides):
    data = {
        "id": 1,
        "name": "Computer Science (M.Sc.)",
        "degree_level": "Master",
        "field_of_study": "Computer Science",
        "min_cgpa": 3.0,
        "min_ielts": 6.5,
        "min_toefl": 88,
        "required_degree": "Bachelor's in computer science",
        "university": SimpleNamespace(name="Test University"),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def statuses(result):
    reqs = result["matched_requirements"] + result["missing_requirements"]
    return {r["requirement"]: r["status"] for r in reqs}


class DegreeLevelTests(unittest.TestCase):
    def test_bachelors_qualifies_for_masters(self):
        result = check_program_eligibility(make_profile(), make_program())
        self.assertEqual(statuses(result)["degree_level"], "satisfied")
        self.assertEqual(result["status"], "eligible")
        self.assertTrue(result["eligible"])

    def test_masters_qualifies_for_phd(self):
        result = check_program_eligibility(
            make_profile(degree_level="Master's"), make_program(degree_level="PhD"))
        self.assertEqual(statuses(result)["degree_level"], "satisfied")

    def test_bachelors_does_not_qualify_for_phd(self):
        result = check_program_eligibility(make_profile(), make_program(degree_level="PhD"))
        self.assertEqual(statuses(result)["degree_level"], "not-satisfied")
        self.assertEqual(result["status"], "not-eligible")

    def test_degree_abbreviations(self):
        result = check_program_eligibility(make_profile(degree_level="BS Computer Science"), make_program())
        self.assertEqual(statuses(result)["degree_level"], "satisfied")

    def test_unknown_profile_degree_is_missing_information(self):
        result = check_program_eligibility(make_profile(degree_level=""), make_program())
        self.assertEqual(statuses(result)["degree_level"], "missing-information")
        self.assertEqual(result["status"], "missing-information")


class RequirementTests(unittest.TestCase):
    def test_all_satisfied(self):
        result = check_program_eligibility(make_profile(), make_program())
        self.assertEqual(statuses(result), {
            "cgpa": "satisfied", "english": "satisfied", "degree_level": "satisfied"})
        self.assertIn("Meeting these minimums does not guarantee admission", result["notes"])

    def test_cgpa_below_minimum(self):
        result = check_program_eligibility(make_profile(cgpa=2.5), make_program())
        self.assertEqual(statuses(result)["cgpa"], "not-satisfied")
        self.assertEqual(result["status"], "not-eligible")
        self.assertFalse(result["eligible"])

    def test_cgpa_scale_is_normalized(self):
        # 8.0 / 10 -> 3.2 / 4.0
        result = check_program_eligibility(make_profile(cgpa=8.0, cgpa_scale=10), make_program())
        self.assertEqual(statuses(result)["cgpa"], "satisfied")

    def test_zero_cgpa_is_missing_information(self):
        result = check_program_eligibility(make_profile(cgpa=0.0), make_program())
        self.assertEqual(statuses(result)["cgpa"], "missing-information")

    def test_ielts_below_minimum(self):
        result = check_program_eligibility(make_profile(ielts_score=6.0), make_program())
        self.assertEqual(statuses(result)["english"], "not-satisfied")
        self.assertEqual(result["status"], "not-eligible")

    def test_toefl_satisfies_when_ielts_absent(self):
        result = check_program_eligibility(
            make_profile(ielts_score=None, toefl_score=95), make_program())
        self.assertEqual(statuses(result)["english"], "satisfied")

    def test_not_satisfied_wins_over_missing_information(self):
        result = check_program_eligibility(
            make_profile(cgpa=2.0, ielts_score=None), make_program())
        self.assertEqual(result["status"], "not-eligible")


class MissingEnglishTests(unittest.TestCase):
    def test_no_english_score_is_missing_information(self):
        result = check_program_eligibility(make_profile(ielts_score=None), make_program())
        self.assertEqual(statuses(result)["english"], "missing-information")
        self.assertEqual(result["status"], "missing-information")
        self.assertFalse(result["eligible"])

    def test_score_for_unlisted_test_is_missing_information(self):
        # Program publishes only IELTS (like KTH), student has only TOEFL
        result = check_program_eligibility(
            make_profile(ielts_score=None, toefl_score=100), make_program(min_toefl=None))
        self.assertEqual(statuses(result)["english"], "missing-information")

    def test_new_toefl_scale_is_not_compared(self):
        result = check_program_eligibility(
            make_profile(ielts_score=None, toefl_score=5), make_program())
        self.assertEqual(statuses(result)["english"], "missing-information")


class NotEvaluatedTests(unittest.TestCase):
    def test_no_published_requirements_is_not_evaluated(self):
        # Like ETH / IP Paris / ELTE: no CGPA or test minimum in the data
        program = make_program(min_cgpa=None, min_ielts=None, min_toefl=None)
        result = check_program_eligibility(make_profile(), program)
        self.assertEqual(result["status"], "not-evaluated")
        self.assertFalse(result["eligible"])
        self.assertEqual(statuses(result), {"degree_level": "satisfied"})

    def test_nothing_at_all_to_check(self):
        program = make_program(min_cgpa=None, min_ielts=None, min_toefl=None, degree_level=None)
        result = check_program_eligibility(make_profile(), program)
        self.assertEqual(result["status"], "not-evaluated")
        self.assertEqual(result["matched_requirements"] + result["missing_requirements"], [])

    def test_field_mismatch_is_a_note_not_a_failure(self):
        result = check_program_eligibility(make_profile(), make_program(field_of_study="Cybersecurity"))
        self.assertEqual(result["status"], "eligible")
        self.assertNotIn("field_of_study", statuses(result))
        self.assertTrue(any("differs from" in note for note in result["notes"]))


if __name__ == "__main__":
    unittest.main()
