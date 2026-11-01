"""
Profile improvement guidance. It holds no eligibility rules of its own: every gap comes from
check_program_eligibility or evaluate_scholarship, or from an empty field of the student's profile.

Result types
  unmet                a stated requirement the profile does not meet
  missing_information  a checkable requirement the profile lacks data for (never treated as a failure)
  manual_verification  a requirement that can't be checked automatically; the record's text is kept
  optional             an empty profile field that no requirement depends on

Priority
  High    an unmet or missing mandatory requirement the student can act on
  Medium  an unmet requirement that can't realistically change, or a scholarship-level manual check
  Low     checks left to university admission, and optional profile completion

A gap shared by several opportunities is one recommendation listing all of them. Nothing here
promises admission or funding.
"""
from typing import Optional

from app.services.eligibility_engine import check_program_eligibility
from app.services.scholarship_eligibility import evaluate_scholarship

CATEGORIES = [
    "Academic Improvement", "English Language Preparation", "Skills Development", "Work Experience",
    "Research and Projects", "Profile Completion", "Scholarship Eligibility",
    "University Admission Requirements", "Documentation and Verification",
]
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
PROFILE_ROUTE = "/profile?edit=1"
NOT_IN_PROFILE = "Not in your profile"
NOT_GUARANTEED = "Addressing these gaps does not guarantee admission or a scholarship."

PROGRAM_REQUIREMENT_LABELS = {"cgpa": "Minimum CGPA", "english": "English language", "degree_level": "Degree level"}
# Shared gaps: program and scholarship requirement names that mean the same thing
SHARED_KEYS = {"cgpa": "academic", "gender": "restrictions", "residency": "restrictions", "source_evidence": "restrictions",
               "record_review": "restrictions"}


def _value(value):
    return NOT_IN_PROFILE if value in (None, "") else str(value)


def _cgpa_text(profile):
    if profile.cgpa is None or profile.cgpa <= 0:
        return NOT_IN_PROFILE
    return f"{profile.cgpa:g}/{(profile.cgpa_scale or 4.0):g}"


def _english_text(profile):
    scores = []
    if profile.ielts_score is not None:
        scores.append(f"IELTS {profile.ielts_score:g}")
    if profile.toefl_score is not None:
        scores.append(f"TOEFL {profile.toefl_score}")
    return ", ".join(scores) or NOT_IN_PROFILE


def _templates(profile):
    """What each gap means for the student. Keys are (result type, requirement)."""
    status = (getattr(profile, "academic_status", None) or "").lower()
    still_studying = status == "studying"
    graduated = status == "graduated"
    cgpa = {"requirement": "Minimum academic result", "profile_information": f"CGPA: {_cgpa_text(profile)}"}
    english = {"requirement": "English language proof", "profile_information": f"English: {_english_text(profile)}"}
    nationality = {"requirement": "Nationality", "profile_information": f"Nationality: {_value(profile.nationality)}"}
    birth = {"requirement": "Age limit", "profile_information": f"Date of birth: {_value(profile.date_of_birth)}"}
    degree = {"requirement": "Degree level", "profile_information": f"Degree: {_value(profile.degree_level)}"}
    experience = {"requirement": "Work experience",
                  "profile_information": f"Work experience: {_value(getattr(profile, 'work_experience', None))}"}

    if still_studying:
        academic_gap = {"priority": "High", "actionability": "achievable",
                        "action": "You're still studying, so focus on your remaining courses. Compare your expected final "
                                  "result with each minimum, and keep other options that fit your current CGPA."}
    else:
        academic_gap = {"priority": "Medium", "actionability": "not_changeable",
                        "action": ("A completed degree's CGPA can't be changed. " if graduated else
                                   "If your degree is finished, this CGPA can't be changed. ")
                        + "Prioritise opportunities whose minimum you meet, and ask admissions whether other evidence "
                          "(such as a last-two-years average) is considered."}

    return {
        ("missing_information", "english"): dict(
            english, category="English Language Preparation", priority="High", actionability="achievable",
            title="Add an accepted English test result",
            gap="These opportunities set an English requirement that can be checked, but your profile has no comparable score.",
            why="Without a score, FitScholars can't tell whether you meet this requirement.",
            action="If you have a test result, add it to your profile. If not, book a test these opportunities accept, "
                   "and check each official page for whether an exemption applies to you.",
            route=PROFILE_ROUTE),
        ("unmet", "english"): dict(
            english, category="English Language Preparation", priority="High", actionability="achievable",
            title="Raise your English test score",
            gap=f"Your score ({_english_text(profile)}) is below the stated minimum.",
            why="English minimums are usually mandatory for admission or for the award.",
            action="Prepare for a retake aimed at the highest minimum listed below, then update your profile with the new score.",
            route=PROFILE_ROUTE),
        ("missing_information", "academic"): dict(
            cgpa, category="Profile Completion", priority="High", actionability="achievable",
            title="Add your CGPA and grading scale",
            gap="These opportunities state a minimum grade, but your profile has no CGPA.",
            why="Your academic result can't be compared with the stated minimums until it's in your profile.",
            action="Add your CGPA and its grading scale to your profile.", route=PROFILE_ROUTE),
        ("unmet", "academic"): dict(
            cgpa, category="Academic Improvement", title="Your CGPA is below some stated minimums",
            gap=f"Your CGPA ({_cgpa_text(profile)}) is below the minimum these opportunities state.",
            why="A stated minimum normally decides whether an application is considered.",
            route="/recommendations", **academic_gap),
        ("missing_information", "degree_level"): dict(
            degree, category="Profile Completion", priority="High", actionability="achievable",
            title="Add your current degree",
            gap="Your degree level is missing, so it can't be compared with the required level.",
            why="Master's programs and scholarships depend on your completed or current degree.",
            action="Add your current or completed degree to your profile.", route=PROFILE_ROUTE),
        ("unmet", "degree_level"): dict(
            degree, category="Academic Improvement", priority="High", actionability="achievable",
            title="Complete the required degree",
            gap="Your degree level is below what these opportunities require.",
            why="Degree level is a mandatory entry requirement.",
            action="Complete the required degree first, or look for opportunities at your current level.",
            route="/recommendations"),
        ("missing_information", "nationality"): dict(
            nationality, category="Profile Completion", priority="High", actionability="achievable",
            title="Add your country of citizenship",
            gap="Many scholarships limit who can apply by nationality, and your profile doesn't record yours.",
            why="Nationality rules decide whether you can apply at all.",
            action="Add your country of citizenship to your profile.", route=PROFILE_ROUTE),
        ("unmet", "nationality"): dict(
            nationality, category="Scholarship Eligibility", priority="Medium", actionability="not_changeable",
            title="Some scholarships aren't open to your nationality",
            gap="The records for these scholarships exclude your nationality.",
            why="A nationality restriction can't be worked around, so these are better left off your shortlist.",
            action="Focus on other scholarships. If your citizenship in your profile is wrong, correct it.",
            route="/scholarships"),
        ("missing_information", "age"): dict(
            birth, category="Profile Completion", priority="High", actionability="achievable",
            title="Add your date of birth",
            gap="These scholarships set an age limit, and your profile has no date of birth.",
            why="An age limit can decide whether you can apply.",
            action="Add your date of birth to your profile.", route=PROFILE_ROUTE),
        ("unmet", "age"): dict(
            birth, category="Scholarship Eligibility", priority="Medium", actionability="not_changeable",
            title="Some scholarships have an age limit you don't meet",
            gap="Your age is outside the limit these records state.",
            why="Age limits can't be changed; check the exact cut-off date in each call.",
            action="Check how the official call measures age, then focus on scholarships without this limit.",
            route="/scholarships"),
        ("manual_verification", "nationality"): dict(
            nationality, category="Documentation and Verification", priority="Medium", actionability="manual_verification",
            title="Check official country lists",
            gap="These scholarships depend on a published country list that can't be checked automatically.",
            why="If your country isn't listed, you can't apply.",
            action="Open each official page and look for your country on the current list.", route="/scholarships"),
        ("missing_information", "field"): dict(
            requirement="Eligible fields of study",
            profile_information=f"Field of study: {_value(profile.field_of_study)}",
            category="Profile Completion", priority="High", actionability="achievable",
            title="Add your field of study",
            gap="These scholarships are limited to certain fields, and your profile doesn't record yours.",
            why="A field restriction can rule out an otherwise strong application.",
            action="Add your field of study to your profile.", route=PROFILE_ROUTE),
        ("manual_verification", "field"): dict(
            requirement="Eligible fields of study",
            profile_information=f"Field of study: {_value(profile.field_of_study)}",
            category="Scholarship Eligibility", priority="Medium", actionability="manual_verification",
            title="Confirm your field qualifies",
            gap="These scholarships are limited to certain fields or programmes, stated in free text.",
            why="A field restriction can rule out an otherwise strong application.",
            action="Read the eligible-field wording below and confirm your intended program qualifies.", route="/scholarships"),
        ("manual_verification", "academic"): dict(
            cgpa, category="Scholarship Eligibility", priority="Medium", actionability="manual_verification",
            title="Check non-numeric academic requirements",
            gap="These requirements use ranks, classes or approximate grades that can't be compared automatically.",
            why="Rules such as \"top 10% of graduates\" may still apply to you.",
            action="Ask your university for your class rank or grade equivalence if the scholarship needs it.",
            route="/scholarships"),
        ("manual_verification", "bachelors_conditions"): dict(
            degree, category="Documentation and Verification", priority="Medium", actionability="manual_verification",
            requirement="Bachelor's degree conditions",
            title="Check conditions on your Bachelor's degree",
            gap="These scholarships set conditions such as graduation date, length or class of degree.",
            why="These conditions can exclude a degree that otherwise qualifies.",
            action="Compare your degree certificate and transcript with the wording below.", route="/scholarships"),
        ("manual_verification", "english"): dict(
            english, category="English Language Preparation", priority="Medium", actionability="manual_verification",
            title="Check whether your English test is accepted",
            gap="The stated requirement can't be compared directly with the test in your profile.",
            why="Scholarships may accept only some tests or equivalents.",
            action="Check the official page for accepted tests and equivalent scores.", route="/scholarships"),
        ("manual_verification", "age"): dict(
            birth, category="Documentation and Verification", priority="Medium", actionability="manual_verification",
            title="Check the age rule in the official call",
            gap="An age rule applies, but the record doesn't state it precisely.",
            why="An age limit can decide whether you can apply.",
            action="Read the current call for the exact limit.", route="/scholarships"),
        ("manual_verification", "work_experience"): dict(
            experience, category="Work Experience", priority="Medium", actionability="manual_verification",
            title="Review the work experience these scholarships expect",
            gap="These records mention work experience, which can't be checked automatically.",
            why="Some scholarships require or strongly favour relevant experience.",
            action="Compare your experience with the wording below. If you're short, look for internships, part-time "
                   "roles or volunteering in your field, and add them to your profile.",
            route=PROFILE_ROUTE),
        ("manual_verification", "restrictions"): dict(
            requirement="Other stated conditions", profile_information="Not recorded in your profile",
            category="Scholarship Eligibility", priority="Medium", actionability="manual_verification",
            title="Check the conditions these scholarships state",
            gap="These records state conditions your profile can't confirm, such as other funding or a previous degree.",
            why="One of these conditions can rule you out even when everything else is met.",
            action="Read the wording below and confirm on the official page whether it applies to you.", route="/scholarships"),
        ("manual_verification", "admission"): dict(
            requirement="Requirements set by the host university",
            profile_information=f"English: {_english_text(profile)}; CGPA: {_cgpa_text(profile)}",
            category="University Admission Requirements", priority="Low", actionability="manual_verification",
            title="Check the host university's requirements",
            gap="For these scholarships, some requirements are set by the university you apply to.",
            why="They're checked during admission, so they don't block the scholarship result here.",
            action="Once you've chosen a host program, check its admission page.", route="/universities"),
        ("manual_verification", "program_background"): dict(
            requirement="Academic background and prerequisites",
            profile_information=f"Degree: {_value(profile.degree_level)}; field: {_value(profile.field_of_study)}",
            category="University Admission Requirements", priority="Medium", actionability="manual_verification",
            title="Check background and prerequisite requirements",
            gap="Each program states its required background in free text, so it can't be compared automatically.",
            why="Missing a prerequisite subject can decide admission even if your grades and English are fine.",
            action="Compare your transcript with the wording below. If a subject is missing, a relevant course may help; "
                   "ask admissions whether it would be accepted.",
            route="/universities"),
        ("manual_verification", "no_published_minimum"): dict(
            requirement="Published admission minimums",
            profile_information=f"CGPA: {_cgpa_text(profile)}; English: {_english_text(profile)}",
            category="Documentation and Verification", priority="Medium", actionability="manual_verification",
            title="Confirm requirements on the official page",
            gap="These programs have no structured CGPA or English minimum in FitScholars.",
            why="No minimum on record doesn't mean there isn't one.",
            action="Check each official program page for its current requirements.", route="/universities"),
        ("manual_verification", "unverified"): dict(
            requirement="Scholarship record", profile_information="Not evaluated",
            category="Documentation and Verification", priority="Medium", actionability="manual_verification",
            title="This scholarship record isn't verified",
            gap="This record hasn't been checked against its official source, so no result is given.",
            why="Unverified details may be wrong or out of date.",
            action="Read the official page directly before relying on this scholarship.", route="/scholarships"),
    }


def _optional_gaps(profile, has_budget, related_for_work):
    """Empty profile fields no requirement depends on. Each names the field it came from."""
    gaps = []

    def add(key, field, value, category, title, why, action, route=PROFILE_ROUTE):
        if value in (None, ""):
            gaps.append(dict(id=f"optional-{key}", category=category, priority="Low", result_type="optional",
                             actionability="achievable", title=title,
                             gap=f"{field} is empty in your profile.", why_it_matters=why, suggested_action=action,
                             requirement=None, profile_information=f"{field}: {NOT_IN_PROFILE}",
                             comparison="No requirement depends on this field.",
                             expected_benefit=None, related=[], action_route=route))

    add("skills", "Technical skills", profile.skills, "Skills Development", "List your technical skills",
        "Programs state prerequisites in free text, and a skills list makes them easier to compare.",
        "Add the tools and subjects you know to your profile.")
    add("research", "Projects and research", profile.research_interests, "Research and Projects",
        "Describe your projects or research", "Useful for statements of purpose and merit-based scholarships.",
        "Add your main projects or research interests to your profile.")
    add("institution", "University", getattr(profile, "institution", None), "Profile Completion", "Add your university",
        "Some scholarships look at the university and record you studied at.", "Add your university to your profile.")
    add("status", "Study status", getattr(profile, "academic_status", None), "Profile Completion",
        "Add your study status and graduation date",
        "It shows whether your CGPA can still change, which changes the advice you get here.",
        "Add whether you're studying or graduated, and the date.")
    if not related_for_work:
        add("work", "Work experience", getattr(profile, "work_experience", None), "Work Experience",
            "Add your work experience", "It helps when comparing you with experience-based criteria.",
            "Add internships, jobs or volunteering to your profile.")
    if not has_budget:
        add("budget", "Budget", None, "Profile Completion", "Add your study budget",
            "Your budget is needed to check whether a program is affordable.",
            "Enter it in the Financial Planner.", route="/financial")
    return gaps


def _opportunity(kind, item_id, name, organization, status, satisfied, unmet, missing, manual, url, verified):
    return {"kind": kind, "id": item_id, "name": name, "organization": organization, "status": status,
            "satisfied": satisfied, "unmet": unmet, "missing_information": missing, "manual_verification": manual,
            "source_url": url, "last_verified": verified}


def _program_entry(program, result):
    def item(check):
        return {"requirement": PROGRAM_REQUIREMENT_LABELS.get(check["requirement"], check["requirement"]),
                "reason": check["message"]}

    checks = result["matched_requirements"] + result["missing_requirements"]
    pick = lambda status: [item(check) for check in checks if check["status"] == status]  # noqa: E731
    manual = [{"requirement": "Academic background and prerequisites", "reason": program.required_degree}] if program.required_degree else []
    university = getattr(program, "university", None)
    verified = getattr(program, "last_verified", None)
    return _opportunity("program", program.id, program.name, university.name if university else None,
                        result["status"].replace("-", "_"), pick("satisfied"), pick("not-satisfied"),
                        pick("missing-information"), manual, program.source_url,
                        verified.isoformat() if verified else None)


def _scholarship_entry(result):
    def items(group):
        return [{"requirement": item["label"], "reason": item["reason"]} for item in group]

    return _opportunity("scholarship", result["scholarship_id"], result["scholarship_name"], result["provider"],
                        result["status"], items(result["satisfied"]), items(result["not_satisfied"]),
                        items(result["missing_information"]), items(result["needs_verification"]),
                        result["official_url"], result["last_verified"])


def build_guidance(profile, programs, scholarships, has_budget=False, today=None) -> dict:
    templates = _templates(profile)
    found = {}

    def add(result_type, requirement, related):
        key = (result_type, SHARED_KEYS.get(requirement, requirement))
        if key not in templates:
            return
        found.setdefault(key, [])
        if not any(item["kind"] == related["kind"] and item["id"] == related["id"] for item in found[key]):
            found[key].append(related)

    entries = []
    for program in programs:
        result = check_program_eligibility(profile, program)
        entries.append(_program_entry(program, result))
        university = getattr(program, "university", None)
        base = {"kind": "program", "id": program.id, "name": program.name,
                "organization": university.name if university else None, "source_url": program.source_url}
        needed = " or ".join(filter(None, [f"IELTS {program.min_ielts:g}" if program.min_ielts is not None else None,
                                           f"TOEFL iBT {program.min_toefl}" if program.min_toefl is not None else None]))
        for check in result["missing_requirements"]:
            result_type = "unmet" if check["status"] == "not-satisfied" else "missing_information"
            text = needed if check["requirement"] == "english" else (
                f"Minimum CGPA {program.min_cgpa:g}/4.0" if check["requirement"] == "cgpa" else None)
            add(result_type, check["requirement"], {**base, "requirement_text": text, "result": check["message"]})
        if program.required_degree:
            add("manual_verification", "program_background",
                {**base, "requirement_text": program.required_degree, "result": "Needs a manual check"})
        if result["status"] == "not-evaluated":
            add("manual_verification", "no_published_minimum",
                {**base, "requirement_text": None, "result": "No structured minimum to compare"})

    for scholarship in scholarships:
        result = evaluate_scholarship(scholarship, profile, today=today)
        entries.append(_scholarship_entry(result))
        base = {"kind": "scholarship", "id": scholarship.id, "name": scholarship.name,
                "organization": scholarship.provider, "source_url": scholarship.official_url}
        if scholarship.verification_status != "verified":
            add("manual_verification", "unverified", {**base, "requirement_text": None, "result": result["summary"]})
            continue
        for result_type, group in (("unmet", result["not_satisfied"]), ("missing_information", result["missing_information"]),
                                   ("manual_verification", result["needs_verification"])):
            for item in group:
                requirement = "admission" if item["scope"] == "admission" else item["requirement"]
                add(result_type, requirement, {**base, "requirement_text": item["source_text"], "result": item["reason"]})

    recommendations = []
    for (result_type, requirement), related in found.items():
        template = templates[(result_type, requirement)]
        count = len(related)
        benefit = None
        if result_type == "missing_information":
            benefit = f"{count} {'opportunity' if count == 1 else 'opportunities'} can then be checked for this requirement."
        elif result_type == "unmet" and template["actionability"] == "achievable":
            benefit = f"Meeting it would clear this requirement at {count} {'opportunity' if count == 1 else 'opportunities'}."
        recommendations.append({
            "id": f"{result_type}-{requirement}".replace("_", "-"),
            "category": template["category"],
            "priority": template["priority"],
            "result_type": result_type,
            "actionability": template["actionability"],
            "title": template["title"],
            "gap": template["gap"],
            "why_it_matters": template["why"],
            "suggested_action": template["action"],
            "requirement": template["requirement"],
            "profile_information": template["profile_information"],
            "comparison": f"Checked against {count} {'opportunity' if count == 1 else 'opportunities'}.",
            "expected_benefit": benefit,
            "related": related,
            "action_route": template["route"],
        })

    has_work_review = ("manual_verification", "work_experience") in found
    recommendations += _optional_gaps(profile, has_budget, has_work_review)
    recommendations.sort(key=lambda item: (PRIORITY_ORDER[item["priority"]], -len(item["related"]), item["title"]))

    counts = {}
    for item in recommendations:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    statuses = [entry["status"] for entry in entries]
    return {
        "summary": {
            "opportunities_evaluated": len(entries),
            "programs_evaluated": len(programs),
            "scholarships_evaluated": len(scholarships),
            "eligible": statuses.count("eligible"),
            "not_eligible": statuses.count("not_eligible"),
            "missing_information": statuses.count("missing_information"),
            "not_evaluated": statuses.count("not_evaluated"),
            "high_priority": sum(item["priority"] == "High" for item in recommendations),
        },
        "categories": [{"name": name, "count": counts[name]} for name in CATEGORIES if name in counts],
        "recommendations": recommendations,
        "opportunities": entries,
        "notes": [NOT_GUARANTEED],
    }


def in_preferred_countries(country: Optional[str], preferred: list) -> bool:
    target = (country or "").lower()
    names = set(preferred)
    if "united kingdom" in names:
        names.add("uk")
    if "uk" in names:
        names.add("united kingdom")
    return any(name in target for name in names)
