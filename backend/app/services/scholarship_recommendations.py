"""
Ranks scholarships for one student and, when chosen, one program. The score is how suitable a
scholarship looks from the records. It is not a chance of winning an award or of being admitted.

Nothing is decided here: eligibility comes from scholarship_eligibility.py, the relationship from
scholarship_matching.py, the deadline from scholarship_deadline, and program amounts from
financial_feasibility.py. This file only weighs those results.

Score: each dimension gives a value from 0 to 1, and
    score = 100 * sum(weight * value) / sum(weights that apply), rounded to a whole number.
Program compatibility applies only when a program is selected, so its weight is left out otherwise.

Each requirement counts once: degree, grades, field and Bachelor's conditions feed the academic
dimension, the source check feeds evidence, and everything else feeds eligibility. Requirements
that are missing or unconfirmed earn less than met ones, and missing data never earns full value.

Hard exclusions: not eligible, not a match for the selected program, closed deadline. An excluded
scholarship has no score at all, so no number can present it as suitable.
"""
from datetime import date
from typing import Optional

from app.models.opportunity import Scholarship
from app.services.financial_feasibility import calculate_feasibility
from app.services.scholarship_eligibility import ELIGIBLE, MISSING, NOT_ELIGIBLE, NOT_EVALUATED, SATISFIED, evaluate_scholarship
from app.services.scholarship_matching import (
    CONFIRMED, LABELS as MATCH_LABELS, NEEDS_VERIFICATION, NOT_A_MATCH, POTENTIAL, evaluate_match, get_link, match_for_financial,
)

# ---- Every scoring constant lives here ----
WEIGHTS = {"eligibility": 30, "program": 20, "funding": 20, "academic": 10, "deadline": 10, "evidence": 10}
DIMENSION_LABELS = {"eligibility": "Eligibility", "program": "Program compatibility", "funding": "Funding",
                    "academic": "Academic fit", "deadline": "Deadline", "evidence": "Evidence quality"}

ELIGIBLE_VALUE = 1.0
VERIFY_MANUALLY_CAP = 0.6       # the most an unconfirmed result can earn, reached when every checkable requirement is met
ACADEMIC_VALUES = {"satisfied": 1.0, "admission": 0.5, "manual": 0.25, "missing": 0.0}
PROGRAM_VALUES = {CONFIRMED: 1.0, POTENTIAL: 0.6, NEEDS_VERIFICATION: 0.25}
FUNDING_VALUES = {"fully_funded": 1.0, "substantially_funded": 0.75, "tuition_only": 0.55, "partially_funded": 0.4, "incomplete": 0.1}
FUNDING_UNCONFIRMED_PENALTY = 0.1
DEADLINE_VALUES = {"open": 1.0, "upcoming": 0.8, "rolling": 0.8, "no_separate_deadline": 0.7, "unknown": 0.3}
EVIDENCE_VALUES = {"official_source": 1.0, "mixed_sources": 0.5, "secondary_only": 0.2, "not_verified": 0.0}
EVIDENCE_PROBLEM_FACTOR = 0.5   # a conflict, or no official link on record

STRONG_MINIMUM = 75
GOOD_MINIMUM = 60
POSSIBLE_MINIMUM = 40
# --------------------------------------------

CATEGORY_LABELS = {"strong": "Strong Match", "good": "Good Match", "possible": "Possible Match", "needs_verification": "Needs Verification"}
CATEGORY_ORDER = list(CATEGORY_LABELS)
FUNDING_LABELS = {"fully_funded": "Fully funded", "substantially_funded": "Substantially funded", "partially_funded": "Partially funded",
                  "tuition_only": "Tuition only", "incomplete": "Funding information incomplete"}
ACADEMIC_REQUIREMENTS = {"degree_level", "bachelors_conditions", "field", "academic"}
SOURCE_REQUIREMENT = "source_evidence"      # like record_review, this says how far to trust the record, so it feeds evidence
PROFILE_FIELDS = {"nationality": "Country of citizenship", "degree_level": "Current or completed degree",
                  "field": "Field of study", "academic": "CGPA and grading scale", "english": "English test score",
                  "age": "Date of birth"}
NOT_A_PROBABILITY = ("The score shows how suitable a scholarship looks from its records. "
                     "It isn't your chance of winning an award or being admitted.")


def _requirements(result):
    return result["satisfied"] + result["not_satisfied"] + result["missing_information"] + result["needs_verification"]


def _eligibility_value(result):
    if result["status"] == ELIGIBLE:
        return ELIGIBLE_VALUE
    items = [item for item in _requirements(result) if item["scope"] == "scholarship"
             and item["requirement"] not in ACADEMIC_REQUIREMENTS and item["requirement"] not in (SOURCE_REQUIREMENT, "record_review")]
    met = sum(item["status"] == SATISFIED for item in items)
    return VERIFY_MANUALLY_CAP * met / len(items) if items else 0.0


def _academic_value(result):
    def value(item):
        if item["status"] == SATISFIED:
            return ACADEMIC_VALUES["satisfied"]
        if item["status"] == MISSING:
            return ACADEMIC_VALUES["missing"]
        return ACADEMIC_VALUES["admission" if item["scope"] == "admission" else "manual"]

    values = [value(item) for item in _requirements(result) if item["requirement"] in ACADEMIC_REQUIREMENTS]
    return sum(values) / len(values) if values else 0.0


def _money(amount, currency):
    return f"{currency} {amount:,.0f}" if currency else f"{amount:,.0f}"


def _tuition_text(scholarship):
    kind = scholarship.tuition_coverage_type
    if kind == "full":
        return "Full tuition"
    if kind == "percentage" and scholarship.tuition_percent_min:
        low, high = scholarship.tuition_percent_min, scholarship.tuition_percent_max
        return f"{low:g}-{high:g}% of tuition" if high and high != low else f"{low:g}% of tuition"
    if kind == "fixed_amount" and scholarship.tuition_amount:
        return f"{_money(scholarship.tuition_amount, scholarship.tuition_currency)} towards costs"
    if kind == "tiered":
        return "Tuition support depends on the award"
    if kind == "conditional":
        return "Tuition support depends on the university"
    if kind == "none":
        return "Tuition not covered"
    return "Tuition coverage not confirmed"


def _stipend_text(scholarship):
    status = scholarship.stipend_status
    amount = scholarship.stipend_amount
    if status == "provided" and amount:
        period = {"monthly": " per month", "annual": " per year", "total": " in total"}.get(scholarship.stipend_period, "")
        return f"{'about ' if scholarship.stipend_is_approximate else ''}{_money(amount, scholarship.stipend_currency)}{period} stipend"
    if status == "provided":
        return "Stipend provided, amount not confirmed"
    if status == "conditional":
        return "Stipend for some awards only"
    if status == "none":
        return "No stipend"
    return None if status == "included_in_package" else "Stipend not confirmed"


def _funding_tier(scholarship):
    level = scholarship.funding_level
    tuition = scholarship.tuition_coverage_type
    stipend = scholarship.stipend_status
    if not level or level == "not_specified":
        return "incomplete"
    if level == "full" and tuition == "full" and stipend == "provided":
        return "fully_funded" if scholarship.verification_basis == "official_source" else "substantially_funded"
    if level == "tuition_only":
        return "tuition_only"
    if (tuition == "full" and stipend in ("provided", "conditional")) or (level == "mixed" and tuition != "none" and stipend == "provided"):
        return "substantially_funded"
    return "partially_funded"


def funding_summary(scholarship) -> dict:
    tier = _funding_tier(scholarship)
    unconfirmed = scholarship.stipend_status in ("provided", "conditional") and not scholarship.stipend_amount
    if scholarship.tuition_coverage_type in (None, "not_specified", "tiered", "conditional"):
        unconfirmed = True
    benefits = [label for label, status in (("accommodation", scholarship.accommodation_status),
                                            ("health insurance", scholarship.health_insurance_status),
                                            ("travel", scholarship.travel_status)) if status == "covered"]
    not_covered = [item.replace("_", " ") for item in scholarship.costs_not_covered or []]
    parts = list(filter(None, [_tuition_text(scholarship), _stipend_text(scholarship)]))
    if benefits:
        parts.append(f"also covers {', '.join(benefits)}")
    return {
        "tier": tier,
        "label": FUNDING_LABELS[tier],
        "summary": " · ".join(parts),
        "amount_confirmed": not unconfirmed,
        "benefits": benefits,
        "not_covered": not_covered,
        "duration_months": scholarship.funding_duration_months,
        "for_program": None,
    }


def _funding_value(funding):
    value = FUNDING_VALUES[funding["tier"]]
    return max(0.0, value - FUNDING_UNCONFIRMED_PENALTY) if not funding["amount_confirmed"] else value


def _evidence_value(scholarship, result):
    basis = scholarship.verification_basis
    value = EVIDENCE_VALUES.get(basis, 0.0)
    if scholarship.verification_status != "verified":
        value = min(value, EVIDENCE_VALUES["secondary_only"])
    if any(item.get("conflict") for item in _requirements(result)) or not scholarship.official_url:
        value *= EVIDENCE_PROBLEM_FACTOR
    return value


def _program_funding(scholarship, program, db):
    """Amounts from Financial Feasibility for the selected program, unchanged."""
    result = calculate_feasibility(program, scholarship=scholarship, match=match_for_financial(db, scholarship, program))
    return {"currency": result["currency"], "total_estimated_cost": result["total_estimated_cost"],
            "confirmed_funding": result["confirmed_funding"], "potential_funding": result["potential_funding"],
            "coverage_percent": result["coverage_percent"]}


def _exclusions(result, match, deadline):
    found = []
    if result["status"] == NOT_ELIGIBLE:
        reasons = "; ".join(f"{item['label']}: {item['reason']}" for item in result["not_satisfied"])
        found.append({"rule": "not_eligible", "reason": reasons})
    if match and match["outcome"] == NOT_A_MATCH:
        found.append({"rule": "not_a_match", "reason": match["explanation"]})
    if deadline["status"] == "closed":
        found.append({"rule": "closed", "reason": f"The listed deadline ({deadline['date']}) has passed, so you can't apply now. "
                                                  "This is separate from your eligibility."})
    return found


def _category(result, match, score, scholarship, conflict):
    """(category, why). Category limits come first: a score never lifts a result past them."""
    if scholarship.verification_status != "verified":
        return "needs_verification", "This scholarship record is not verified."
    if conflict:
        return "needs_verification", "This record's details disagree, so check them first."
    if result["status"] == MISSING:
        return "needs_verification", "Your profile is missing information this scholarship needs."
    if match and match["outcome"] == NEEDS_VERIFICATION:
        return "needs_verification", "It isn't clear that this scholarship supports your selected program."
    if result["status"] == ELIGIBLE:
        program_clear = not match or match["outcome"] == CONFIRMED
        if score >= STRONG_MINIMUM and program_clear:
            return "strong", "You meet the stated requirements and the score is high."
        if score >= GOOD_MINIMUM:
            return "good", "You meet the stated requirements."
        return "possible", "You meet the stated requirements, but the funding or evidence is weaker."
    if score >= POSSIBLE_MINIMUM:
        return "possible", "It looks suitable, but some requirements still need a manual check."
    return "needs_verification", "Too little could be confirmed for this scholarship."


def _reasons(result, match, funding, deadline, scholarship, program):
    positive, warnings, negative = [], [], []
    if match and match["outcome"] == CONFIRMED:
        positive.append(f"Confirmed for {program.name}: {match['explanation']}")
    if result["status"] == ELIGIBLE:
        positive.append("You meet the requirements this scholarship states.")
    positive += [f"{item['label']}: {item['reason']}" for item in result["satisfied"]]
    if funding["tier"] != "incomplete":
        positive.append(f"{funding['label']}: {funding['summary']}.")
    if deadline["status"] == "open":
        positive.append(f"Applications are open; the deadline is {deadline['date']} ({deadline['days_left']} days left).")
    elif deadline["status"] == "upcoming":
        positive.append(f"Applications open on {deadline['opens_on']}.")
    elif deadline["status"] in ("rolling", "no_separate_deadline"):
        positive.append(deadline["message"])

    warnings += [f"Add to your profile - {item['label']}: {item['reason']}" for item in result["missing_information"]]
    conflicts = [item for item in result["needs_verification"] if item.get("conflict")]
    warnings += [f"{item['label']}: {item['reason']}" for item in conflicts]
    if match and match["outcome"] == POTENTIAL:
        warnings.append(f"Only a potential match for {program.name}: {match['explanation']}")
    elif match and match["outcome"] == NEEDS_VERIFICATION:
        warnings.append(f"Check that this supports {program.name}: {match['explanation']}")
    warnings +=[f"{item['label']}: {item['reason']}" for item in result["needs_verification"]
                 if item["scope"] == "scholarship" and not item.get("conflict")]
    if scholarship.verification_status != "verified":
        warnings.append("This scholarship record is not verified.")
    if not funding["amount_confirmed"]:
        warnings.append("The funding amount isn't confirmed.")
    if funding["tier"] == "incomplete":
        warnings.append("Funding information is incomplete.")
    if funding["not_covered"]:
        warnings.append(f"Not covered: {', '.join(funding['not_covered'])}.")
    if deadline["status"] == "unknown":
        warnings.append("No exact deadline is on record, so check the official page.")
    if not match:   # true of every row, so it goes after the reasons specific to this record
        warnings.append("Program compatibility hasn't been evaluated, because no program is selected.")

    negative += [f"{item['label']}: {item['reason']}" for item in result["not_satisfied"]]
    if match and match["outcome"] == NOT_A_MATCH:
        negative.append(f"Not a match for {program.name}: {match['explanation']}")
    if deadline["status"] == "closed":
        negative.append(f"The application period has closed ({deadline['date']}).")
    return positive, warnings, negative


def _breakdown(values):
    applied = sum(WEIGHTS[name] for name in values)
    rows = [{"dimension": name, "label": DIMENSION_LABELS[name], "weight": WEIGHTS[name], "value": round(value, 3),
             "points": round(100 * WEIGHTS[name] * value / applied, 1)} for name, value in values.items()]
    total = 100 * sum(WEIGHTS[name] * value for name, value in values.items()) / applied
    return rows, int(total + 0.5)


def recommend_scholarship(scholarship, profile, program=None, link=None, db=None, today=None) -> dict:
    """One scholarship's result. profile may be None: nothing is then treated as met."""
    today = today or date.today()
    result = evaluate_scholarship(scholarship, profile, today=today)
    match = evaluate_match(scholarship, program, link) if program is not None else None
    deadline = result["deadline"]
    funding = funding_summary(scholarship)
    exclusions = _exclusions(result, match, deadline)
    positive, warnings, negative = _reasons(result, match, funding, deadline, scholarship, program)
    conflict = any(item.get("conflict") for item in _requirements(result))

    score = category = category_reason = None
    breakdown = []
    if not exclusions:
        values = {"eligibility": _eligibility_value(result), "funding": _funding_value(funding),
                  "academic": _academic_value(result), "deadline": DEADLINE_VALUES[deadline["status"]],
                  "evidence": _evidence_value(scholarship, result)}
        if match:
            values["program"] = PROGRAM_VALUES[match["outcome"]]
        breakdown, score = _breakdown(values)
        category, category_reason = _category(result, match, score, scholarship, conflict)
        if program is not None and db is not None:
            funding["for_program"] = _program_funding(scholarship, program, db)

    return {
        "scholarship_id": scholarship.id,
        "scholarship_name": scholarship.name,
        "provider": scholarship.provider,
        "country": scholarship.country,
        "rank": None,
        "recommended": not exclusions,
        "score": score,
        "category": category,
        "category_label": CATEGORY_LABELS.get(category),
        "category_reason": category_reason,
        "exclusions": exclusions,
        "eligibility": {"status": result["status"], "outcome": result["outcome"], "summary": result["summary"]},
        "program_match": ({"program_id": program.id, "program_name": program.name, "outcome": match["outcome"], "label": match["label"],
                           "explanation": match["explanation"],
                           "relationship_verification_status": match["relationship_verification_status"]} if match else None),
        "funding": funding,
        "deadline": deadline,
        "positive": positive,
        "warnings": warnings,
        "negative": negative,
        "breakdown": breakdown,
        "verification_status": scholarship.verification_status,
        "official_url": scholarship.official_url,
        "has_conflict": conflict,
        "_gaps": [item["requirement"] for item in result["missing_information"]],
    }


def _sort_key(item):
    return CATEGORY_ORDER.index(item["category"]), -item["score"], item["scholarship_name"], item["scholarship_id"]


def profile_gaps(items):
    counts = {}
    for item in items:
        for requirement in item["_gaps"]:
            if requirement in PROFILE_FIELDS:
                counts[requirement] = counts.get(requirement, 0) + 1
    gaps = [{"field": key, "label": PROFILE_FIELDS[key], "scholarships_affected": count} for key, count in counts.items()]
    return sorted(gaps, key=lambda gap: (-gap["scholarships_affected"], gap["field"]))


def recommend_for_student(db, profile, program=None, include_unverified=False, today=None) -> dict:
    """Ranked scholarships for a student, with the excluded ones listed apart."""
    query = db.query(Scholarship).filter(Scholarship.archived_at.is_(None)).order_by(Scholarship.id)
    if not include_unverified:
        query = query.filter(Scholarship.verification_status == "verified")
    scholarships = query.all()
    # A record flagged as a copy of another shown record would be the same opportunity twice
    shown = {item.id for item in scholarships}
    scholarships = [item for item in scholarships if item.duplicate_of_id not in shown]
    links = {}
    if program is not None:
        links = {item.id: get_link(db, item.id, program.id) for item in scholarships}
    items = [recommend_scholarship(item, profile, program, links.get(item.id), db, today) for item in scholarships]

    recommended = sorted((item for item in items if item["recommended"]), key=_sort_key)
    for rank, item in enumerate(recommended, start=1):
        item["rank"] = rank
    excluded = sorted((item for item in items if not item["recommended"]), key=lambda item: (item["scholarship_name"], item["scholarship_id"]))
    gaps = profile_gaps(items)
    for item in items:
        del item["_gaps"]
    counts = {key: sum(item["category"] == key for item in recommended) for key in CATEGORY_ORDER}
    return {
        "program": {"id": program.id, "name": program.name} if program is not None else None,
        "profile_complete": profile is not None and not gaps,
        "profile_gaps": gaps,
        "summary": {"recommended": len(recommended), "excluded": len(excluded), **counts,
                    "eligible": sum(item["eligibility"]["status"] == ELIGIBLE for item in recommended),
                    "verify_manually": sum(item["eligibility"]["outcome"] == "verify_manually" for item in recommended),
                    "potential_program_matches": sum((item["program_match"] or {}).get("outcome") == POTENTIAL for item in recommended)},
        "weights": WEIGHTS,
        "recommendations": recommended,
        "excluded": excluded,
        "notes": [NOT_A_PROBABILITY],
    }


def recommend_one(db, scholarship, profile, program=None, today=None) -> dict:
    link = get_link(db, scholarship.id, program.id) if program is not None else None
    item = recommend_scholarship(scholarship, profile, program, link, db, today)
    del item["_gaps"]
    return item
