from app.models.user import StudentProfile
from app.models.opportunity import Program

# Requirement statuses
SATISFIED = "satisfied"
NOT_SATISFIED = "not-satisfied"
MISSING_INFORMATION = "missing-information"

# Overall statuses
ELIGIBLE = "eligible"
NOT_ELIGIBLE = "not-eligible"
NOT_EVALUATED = "not-evaluated"

# Degree ladder. profile.degree_level = student's completed/current degree,
# program.degree_level = degree the program awards (the student's target).
DEGREE_RANKS = {"bachelor": 1, "master": 2, "phd": 3}
DEGREE_NAMES = {1: "Bachelor's", 2: "Master's", 3: "PhD"}

# Requirements published by the program itself. A program is only "eligible"
# when at least one of these was actually checked against the profile.
PUBLISHED_REQUIREMENTS = {"cgpa", "english"}

# New TOEFL iBT scale (since Jan 2026) is 1-6; program thresholds use 0-120
NEW_TOEFL_SCALE_MAX = 6


def _norm(text):
    return (text or "").strip().lower()


def _degree_rank(text):
    """Bachelor's / Master / MSc / PhD -> 1 / 2 / 3, unknown -> None"""
    value = _norm(text).replace("'", "").replace(".", "")
    if value.startswith(("phd", "doctor")):
        return 3
    if value.startswith(("master", "msc", "ms ", "ma ", "mphil")) or value in ("ms", "ma"):
        return 2
    if value.startswith(("bachelor", "bsc", "bs ", "ba ", "be ", "beng")) or value in ("bs", "ba", "be"):
        return 1
    return None


def _item(requirement: str, status: str, message: str) -> dict:
    return {"requirement": requirement, "status": status, "message": message}


def _check_cgpa(profile, program):
    # ProfileCreate requires cgpa, so the frontend sends 0.0 when it is unknown
    if profile.cgpa is None or profile.cgpa <= 0:
        return _item("cgpa", MISSING_INFORMATION, "CGPA is not in your profile")

    scale = profile.cgpa_scale or 4.0
    normalized = round(profile.cgpa / scale * 4.0, 2)
    if normalized >= program.min_cgpa:
        return _item(
            "cgpa", SATISFIED,
            f"Your CGPA ({normalized}/4.0) meets the minimum of {program.min_cgpa}",
        )
    return _item(
        "cgpa", NOT_SATISFIED,
        f"Your CGPA ({normalized}/4.0) is below the minimum of {program.min_cgpa}",
    )


def _check_english(profile, program):
    """IELTS or TOEFL, either one is enough. Only compares tests the program publishes."""
    needed = []
    if program.min_ielts is not None:
        needed.append(f"IELTS {program.min_ielts}")
    if program.min_toefl is not None:
        needed.append(f"TOEFL iBT {program.min_toefl}")
    needed_text = " or ".join(needed)

    toefl = profile.toefl_score
    toefl_new_scale = toefl is not None and toefl <= NEW_TOEFL_SCALE_MAX

    compared = []  # (test name, score, minimum, passed)
    if program.min_ielts is not None and profile.ielts_score is not None:
        compared.append(("IELTS", profile.ielts_score, program.min_ielts,
                         profile.ielts_score >= program.min_ielts))
    if program.min_toefl is not None and toefl is not None and not toefl_new_scale:
        compared.append(("TOEFL", toefl, program.min_toefl, toefl >= program.min_toefl))

    for test, score, minimum, passed in compared:
        if passed:
            return _item("english", SATISFIED,
                         f"Your {test} ({score}) meets the minimum of {minimum}")
    if compared:
        scores = ", ".join(f"{test} {score}" for test, score, _, _ in compared)
        return _item("english", NOT_SATISFIED,
                     f"Your {scores} is below the requirement. Needed: {needed_text}")

    # Nothing comparable: no score, a score for a test this program does not
    # publish, or a TOEFL score on the new 1-6 scale
    if toefl_new_scale and program.min_toefl is not None:
        reason = (f"Your TOEFL score ({toefl}) looks like the new 1-6 scale; "
                  f"this program's threshold uses the 0-120 scale")
    elif profile.ielts_score is None and toefl is None:
        reason = "No English test score in your profile"
    else:
        reason = "Your English test is not one this program lists a minimum score for"
    return _item("english", MISSING_INFORMATION, f"{reason}. Needed: {needed_text}")


def _check_degree(profile, program):
    """A program at level N needs a completed degree at level N-1 or higher."""
    target = _degree_rank(program.degree_level)
    if target is None:
        return None  # program level unknown, nothing to check

    current = _degree_rank(profile.degree_level)
    if current is None:
        return _item("degree_level", MISSING_INFORMATION,
                     "Your current or completed degree level is not in your profile")

    required = DEGREE_NAMES.get(target - 1)
    if required is None:
        return None
    if current >= target - 1:
        return _item("degree_level", SATISFIED,
                     f"Your {DEGREE_NAMES[current]} degree is the right level "
                     f"to apply for a {DEGREE_NAMES[target]} program")
    return _item("degree_level", NOT_SATISFIED,
                 f"A {DEGREE_NAMES[target]} program needs a {required} degree; "
                 f"your profile shows {DEGREE_NAMES[current]}")


def check_program_eligibility(profile: StudentProfile, program: Program) -> dict:
    """Rule-based check of a student profile against one program's structured
    requirements. It never guarantees admission."""
    checks = []
    notes = []

    if program.min_cgpa is not None:
        checks.append(_check_cgpa(profile, program))
    if program.min_ielts is not None or program.min_toefl is not None:
        checks.append(_check_english(profile, program))
    degree = _check_degree(profile, program)
    if degree:
        checks.append(degree)

    # Field of study is the program's subject, not an admission rule, so it is
    # only shown as information (real background rules are in required_degree)
    if program.field_of_study and profile.field_of_study:
        a = _norm(program.field_of_study)
        b = _norm(profile.field_of_study)
        relation = "matches" if (a in b or b in a) else "differs from"
        notes.append(
            f"Program field ({program.field_of_study}) {relation} your field "
            f"({profile.field_of_study}); check the background requirements below"
        )
    if program.required_degree:
        notes.append(f"Required degree: {program.required_degree} (please verify manually)")

    statuses = [c["status"] for c in checks]
    published_checked = any(
        c["requirement"] in PUBLISHED_REQUIREMENTS and c["status"] != MISSING_INFORMATION
        for c in checks
    )
    if NOT_SATISFIED in statuses:
        status = NOT_ELIGIBLE
    elif MISSING_INFORMATION in statuses:
        status = MISSING_INFORMATION
    elif not published_checked:
        status = NOT_EVALUATED
        notes.append("This program has no structured CGPA or English test minimum to "
                     "check; confirm requirements on the official page")
    else:
        status = ELIGIBLE

    if status == ELIGIBLE:
        notes.append("Meeting these minimums does not guarantee admission")

    return {
        "program_id": program.id,
        "program_name": program.name,
        "university_name": program.university.name if program.university else "",
        "status": status,
        "eligible": status == ELIGIBLE,
        "matched_requirements": [c for c in checks if c["status"] == SATISFIED],
        "missing_requirements": [c for c in checks if c["status"] != SATISFIED],
        "notes": notes,
    }
