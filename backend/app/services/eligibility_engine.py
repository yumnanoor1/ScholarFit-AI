from app.models.user import StudentProfile
from app.models.opportunity import Program


def _norm(text):
    return (text or "").strip().lower()


def _item(requirement: str, message: str) -> dict:
    return {"requirement": requirement, "message": message}


def check_program_eligibility(profile: StudentProfile, program: Program) -> dict:
    """Rule-based check of a student profile against one program."""
    matched = []
    missing = []
    notes = []

    # 1) CGPA (student CGPA is converted to a 4.0 scale)
    if program.min_cgpa is not None:
        if profile.cgpa is None:
            missing.append(_item("cgpa", "CGPA is not in your profile"))
        else:
            scale = profile.cgpa_scale or 4.0
            normalized = round(profile.cgpa / scale * 4.0, 2)
            if normalized >= program.min_cgpa:
                matched.append(_item(
                    "cgpa",
                    f"Your CGPA ({normalized}/4.0) meets the minimum of {program.min_cgpa}",
                ))
            else:
                missing.append(_item(
                    "cgpa",
                    f"Your CGPA ({normalized}/4.0) is below the minimum of {program.min_cgpa}",
                ))

    # 2) English test (IELTS or TOEFL, either one is enough)
    needs_ielts = program.min_ielts is not None
    needs_toefl = program.min_toefl is not None
    if needs_ielts or needs_toefl:
        ielts_ok = (
            needs_ielts
            and profile.ielts_score is not None
            and profile.ielts_score >= program.min_ielts
        )
        toefl_ok = (
            needs_toefl
            and profile.toefl_score is not None
            and profile.toefl_score >= program.min_toefl
        )
        if ielts_ok:
            matched.append(_item(
                "english",
                f"Your IELTS ({profile.ielts_score}) meets the minimum of {program.min_ielts}",
            ))
        elif toefl_ok:
            matched.append(_item(
                "english",
                f"Your TOEFL ({profile.toefl_score}) meets the minimum of {program.min_toefl}",
            ))
        else:
            options = []
            if needs_ielts:
                options.append(f"IELTS {program.min_ielts}")
            if needs_toefl:
                options.append(f"TOEFL {program.min_toefl}")
            missing.append(_item(
                "english",
                "English requirement not met. Needed: " + " or ".join(options),
            ))

    # 3) Degree level (compare the first 6 letters: Master / Master's, Bachelor, PhD)
    if program.degree_level and profile.degree_level:
        if _norm(program.degree_level)[:6] == _norm(profile.degree_level)[:6]:
            matched.append(_item(
                "degree_level",
                f"Degree level matches ({program.degree_level})",
            ))
        else:
            missing.append(_item(
                "degree_level",
                f"Program is {program.degree_level}, but your profile targets {profile.degree_level}",
            ))

    # 4) Field of study (one text contains the other)
    if program.field_of_study and profile.field_of_study:
        a = _norm(program.field_of_study)
        b = _norm(profile.field_of_study)
        if a in b or b in a:
            matched.append(_item(
                "field_of_study",
                f"Field matches ({program.field_of_study})",
            ))
        else:
            missing.append(_item(
                "field_of_study",
                f"Program field is {program.field_of_study}, your field is {profile.field_of_study}",
            ))

    # 5) Not checked automatically
    if program.required_degree:
        notes.append(
            f"Required degree: {program.required_degree} (please verify manually)"
        )

    return {
        "program_id": program.id,
        "program_name": program.name,
        "university_name": program.university.name if program.university else "",
        "eligible": len(missing) == 0,
        "matched_requirements": matched,
        "missing_requirements": missing,
        "notes": notes,
    }