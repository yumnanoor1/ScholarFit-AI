"""
Scholarship-focused profile guidance. Every requirement gap comes from the scholarship eligibility
service; optional gaps are limited to empty student profile fields.

Result types
  unmet                a stated requirement the profile does not meet
  missing_information  a checkable requirement the profile lacks data for (never treated as a failure)
  manual_verification  a requirement that can't be checked automatically; the record's text is kept
  optional             an empty profile field that no requirement depends on

Priority
  High    an unmet or missing mandatory requirement the student can act on
  Medium  an unmet requirement that can't realistically change, or a scholarship-level manual check
  Low     optional profile completion

A gap shared by several scholarships is one recommendation listing all of them. Nothing here
promises a scholarship.
"""
from typing import Optional

from app.services.scholarship_eligibility import evaluate_scholarship

CATEGORIES = [
    "Academic Improvement", "English Language Preparation", "Skills Development", "Work Experience",
    "Research and Projects", "Profile Completion", "Scholarship Eligibility",
    "Documentation and Verification",
]
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
PROFILE_ROUTE = "/profile?edit=1"
NOT_IN_PROFILE = "Not in your profile"
NOT_GUARANTEED = "Addressing these gaps does not guarantee a scholarship."

SHARED_KEYS = {"cgpa": "academic", "gender": "restrictions", "residency": "restrictions"}


def _value(value):
    return NOT_IN_PROFILE if value in (None, "") else str(value)


def _cgpa_text(profile):
    if profile.cgpa is None:
        return NOT_IN_PROFILE
    scale = getattr(profile, "cgpa_scale", None)
    if scale is None or scale <= 0:
        return f"{profile.cgpa:g} (scale not recorded)"
    return f"{profile.cgpa:g}/{scale:g}"


def _english_text(profile):
    scores = []
    if profile.ielts_score is not None:
        scores.append(f"IELTS {profile.ielts_score:g}")
    if profile.toefl_score is not None:
        scores.append(f"TOEFL {profile.toefl_score}")
    language_test = getattr(profile, "language_test", None) or {}
    if (isinstance(language_test, dict)
            and language_test.get("test_type") not in (None, "No Test / Not Taken")
            and language_test.get("overall_score") is not None):
        test_name = language_test.get("other_test_name") or language_test.get("test_type")
        if test_name and not any(score.lower().startswith(f"{test_name.lower()} ") for score in scores):
            scores.append(f"{test_name} {language_test['overall_score']:g}")
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
            why="The scholarship states an English minimum for applicants.",
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
            why="Scholarships can require a particular completed or current degree.",
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
            gap="These scholarships are limited to certain fields, stated in free text.",
            why="A field restriction can rule out an otherwise strong application.",
            action="Read the eligible-field wording below and confirm that your field qualifies.", route="/scholarships"),
        ("manual_verification", "academic"): dict(
            cgpa, category="Scholarship Eligibility", priority="Medium", actionability="manual_verification",
            title="Check non-numeric academic requirements",
            gap="These requirements use ranks, classes or approximate grades that can't be compared automatically.",
            why="Rules such as \"top 10% of graduates\" may still apply to you.",
            action="Check your transcript or ask its issuing institution for your class rank or grade equivalence if the scholarship needs it.",
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
        ("manual_verification", "unverified"): dict(
            requirement="Scholarship record", profile_information="Not evaluated",
            category="Documentation and Verification", priority="Medium", actionability="manual_verification",
            title="This scholarship record isn't verified",
            gap="This record hasn't been checked against its official source, so no result is given.",
            why="Unverified details may be wrong or out of date.",
            action="Read the official page directly before relying on this scholarship.", route="/scholarships"),
        ("manual_verification", "source_evidence"): dict(
            requirement="Official source evidence", profile_information="Not evaluated",
            category="Documentation and Verification", priority="High", actionability="manual_verification",
            title="Verify the scholarship's current official details",
            gap="Its source evidence is missing or out of date, so no eligibility result is given.",
            why="Requirements and deadlines should not be relied on without current official evidence.",
            action="Check the official scholarship page and have the record re-verified before relying on it.",
            route="/scholarships"),
        ("manual_verification", "record_review"): dict(
            requirement="Scholarship record review", profile_information="Not evaluated",
            category="Documentation and Verification", priority="High", actionability="manual_verification",
            title="This scholarship record is under review",
            gap="The record is being reviewed, so its eligibility details are not treated as confirmed.",
            why="Conflicting or flagged details may affect eligibility and funding information.",
            action="Check the official scholarship page and wait for the record review before relying on it.",
            route="/scholarships"),
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
        "A skills list can help prepare scholarship applications and supporting documents.",
        "Add the tools and subjects you know to your profile.")
    add("research", "Projects and research", profile.research_interests, "Research and Projects",
        "Describe your projects or research", "Useful for statements of purpose and merit-based scholarships.",
        "Add your main projects or research interests to your profile.")
    add("institution", "Institution", getattr(profile, "institution", None), "Profile Completion", "Add your institution",
        "Some scholarships consider the institution recorded in your education history.",
        "Add your current or previous institution to your education history.")
    academic_status = getattr(profile, "academic_status", None)
    graduation_date = getattr(profile, "graduation_date", None)
    if academic_status in (None, "") or graduation_date in (None, ""):
        missing_fields = [
            label for label, value in (("study status", academic_status), ("graduation date", graduation_date))
            if value in (None, "")
        ]
        gaps.append(dict(
            id="optional-status", category="Profile Completion", priority="Low", result_type="optional",
            actionability="achievable", title="Add your study status and graduation date",
            gap=f"{' and '.join(missing_fields).capitalize()} {'are' if len(missing_fields) > 1 else 'is'} missing from your profile.",
            why_it_matters="It shows whether your CGPA can still change, which changes the advice you get here.",
            suggested_action="Add whether you're studying or graduated, and your expected or actual graduation date.",
            requirement=None,
            profile_information=(f"Study status: {_value(academic_status)}; "
                                 f"Graduation date: {_value(graduation_date)}"),
            comparison="No requirement depends on this field.", expected_benefit=None, related=[],
            action_route=PROFILE_ROUTE,
        ))
    preference_values = (
        ("preferred fields", getattr(profile, "preferred_fields", None)),
        ("target degree levels", getattr(profile, "preferred_degree_levels", None)),
        ("preferred countries", getattr(profile, "preferred_countries", None)),
        ("funding preference", getattr(profile, "preferred_funding_types", None)
         or getattr(profile, "funding_preference", None)),
    )
    missing_preferences = [
        label for label, value in preference_values
        if value is None or value == "" or value == [] or value == {}
    ]
    if missing_preferences:
        gaps.append(dict(
            id="optional-preferences", category="Profile Completion", priority="Low", result_type="optional",
            actionability="achievable", title="Set your study preferences",
            gap=f"Not recorded: {', '.join(missing_preferences)}.",
            why_it_matters="Study preferences help focus recommendations on the fields, countries, degree levels, and funding you want.",
            suggested_action="Update your preferred fields, degree levels, countries, and funding in your profile.",
            requirement=None, profile_information=f"Missing preferences: {', '.join(missing_preferences)}",
            comparison="No eligibility requirement depends on these preferences.",
            expected_benefit="Helps tailor opportunity recommendations to your stated goals.",
            related=[], action_route=PROFILE_ROUTE,
        ))
    if not related_for_work:
        add("work", "Work experience", getattr(profile, "work_experience", None), "Work Experience",
            "Add your work experience", "It helps when comparing you with experience-based criteria.",
            "Add internships, jobs or volunteering to your profile.")
    if not has_budget:
        add("budget", "Budget", None, "Profile Completion", "Add your study budget",
            "Your budget is needed to check scholarship affordability.",
            "Enter it in the Financial Planner.", route="/financial")
    return gaps


def _opportunity(kind, item_id, name, organization, status, satisfied, unmet, missing, manual, url, verified,
                 deadline=None):
    return {"kind": kind, "id": item_id, "name": name, "organization": organization, "status": status,
            "satisfied": satisfied, "unmet": unmet, "missing_information": missing, "manual_verification": manual,
            "source_url": url, "last_verified": verified, "deadline": deadline}


def _scholarship_entry(result):
    def items(group):
        return [{"requirement": item["label"], "reason": item["reason"]} for item in group]

    source_is_current = result["verification_status"] == "verified" and not any(
        item["requirement"] in {"source_evidence", "record_review"} for item in result["needs_verification"]
    )
    return _opportunity("scholarship", result["scholarship_id"], result["scholarship_name"], result["provider"],
                        result["status"], items(result["satisfied"]), items(result["not_satisfied"]),
                        items(result["missing_information"]), items(result["needs_verification"]),
                        result["official_url"], result["last_verified"],
                        result["deadline"] if source_is_current else None)


def build_guidance(
    profile,
    scholarships,
    has_budget=False,
    today=None,
    include_optional=True,
    source_provenance_by_id=None,
) -> dict:
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
    for scholarship in scholarships:
        result = evaluate_scholarship(scholarship, profile, today=today)
        source_provenance = (source_provenance_by_id or {}).get(scholarship.id)
        entries.append({
            **_scholarship_entry(result),
            "source_provenance": source_provenance,
        })
        base = {"kind": "scholarship", "id": scholarship.id, "name": scholarship.name,
                "organization": scholarship.provider, "source_url": scholarship.official_url,
                "source_provenance": source_provenance}
        if scholarship.verification_status != "verified":
            add("manual_verification", "unverified", {**base, "requirement_text": None, "result": result["summary"]})
            continue
        for result_type, group in (("unmet", result["not_satisfied"]), ("missing_information", result["missing_information"]),
                                   ("manual_verification", result["needs_verification"])):
            for item in group:
                add(result_type, item["requirement"],
                    {**base, "requirement_text": item["source_text"], "result": item["reason"]})

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
    if include_optional:
        recommendations += _optional_gaps(profile, has_budget, has_work_review)
    recommendations.sort(key=lambda item: (PRIORITY_ORDER[item["priority"]], -len(item["related"]), item["title"]))

    counts = {}
    for item in recommendations:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    statuses = [entry["status"] for entry in entries]
    return {
        "summary": {
            "opportunities_evaluated": len(entries),
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
