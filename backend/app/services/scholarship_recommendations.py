"""
Ranks scholarships for one student. The score is how suitable a scholarship looks from the
recorded requirements, funding, deadline, and evidence. It is not a chance of winning an award.

Nothing is decided here: eligibility comes from scholarship_eligibility.py, the deadline from
scholarship_deadline, and funding from the scholarship record. This file only weighs those results.

Score: each dimension gives a value from 0 to 1, and
    score = 100 * sum(weight * value) / sum(weights that apply), rounded to a whole number.
Weights are eligibility 37.5, funding 25, academic 12.5, deadline 12.5, and evidence 12.5.
Saved degree and funding preferences affect their existing score dimensions, never mandatory eligibility.

Each requirement counts once: degree, grades, field and Bachelor's conditions feed the academic
dimension, the source check feeds evidence, and everything else feeds eligibility. Requirements
that are missing or unconfirmed earn less than met ones, and missing data never earns full value.

Hard exclusions: not eligible and closed deadline. An excluded scholarship has no score at all,
so no number can present it as suitable.
"""
from datetime import date
from app.services.eligibility_engine import _degree_rank
from app.services.scholarship_eligibility import ELIGIBLE, MISSING, NOT_ELIGIBLE, NOT_EVALUATED, SATISFIED, evaluate_scholarship
from app.services.student_scholarship_visibility import (
    deduplicate_student_scholarships,
    get_student_scholarships,
)

# ---- Every scoring constant lives here ----
WEIGHTS = {"eligibility": 37.5, "funding": 25, "academic": 12.5, "deadline": 12.5, "evidence": 12.5}
DIMENSION_LABELS = {"eligibility": "Eligibility", "funding": "Funding", "academic": "Academic fit",
                    "deadline": "Deadline", "evidence": "Evidence quality"}

ELIGIBLE_VALUE = 1.0
VERIFY_MANUALLY_CAP = 0.6       # the most an unconfirmed result can earn, reached when every checkable requirement is met
ACADEMIC_VALUES = {"satisfied": 1.0, "admission": 0.5, "manual": 0.25, "missing": 0.0}
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
NOT_A_PROBABILITY = "The score shows how suitable a scholarship looks from its records, not your chance of receiving an award."


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


def _preferred_degree_match(profile, scholarship):
    preferences = getattr(profile, "preferred_degree_levels", None) or []
    offered = getattr(scholarship, "eligible_degree_levels", None) or []
    if not offered and getattr(scholarship, "degree_level", None):
        offered = [scholarship.degree_level]
    preferred_ranks = {_degree_rank(level) for level in preferences}
    offered_ranks = {_degree_rank(level) for level in offered}
    preferred_ranks.discard(None)
    offered_ranks.discard(None)
    if not preferred_ranks or not offered_ranks:
        return None
    return bool(preferred_ranks & offered_ranks)


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
    }


def _funding_preference_match(funding, profile, scholarship):
    preference = " ".join(str(getattr(profile, "funding_preference", None) or "").lower().split())
    if preference in ("fully funded only", "full funding required") and funding["tier"] != "fully_funded":
        return False
    if (preference == "fully funded or substantial scholarship"
            and funding["tier"] not in ("fully_funded", "substantially_funded")):
        return False
    preferred_types = {
        item.strip().lower() for item in (getattr(profile, "preferred_funding_types", None) or [])
        if isinstance(item, str) and item.strip()
    }
    if (preferred_types == {"tuition waivers"} and scholarship is not None
            and scholarship.tuition_coverage_type == "none"):
        return False
    return None


def _funding_value(funding, profile=None, scholarship=None):
    if _funding_preference_match(funding, profile, scholarship) is False:
        return 0.0
    value = FUNDING_VALUES[funding["tier"]]
    return max(0.0, value - FUNDING_UNCONFIRMED_PENALTY) if not funding["amount_confirmed"] else value


def _evidence_value(scholarship, result):
    basis = scholarship.verification_basis
    value = EVIDENCE_VALUES.get(basis, 0.0)
    source_issue = any(item["requirement"] == SOURCE_REQUIREMENT for item in result["needs_verification"])
    if source_issue or scholarship.verification_status != "verified":
        value = min(value, EVIDENCE_VALUES["secondary_only"])
    if any(item.get("conflict") for item in _requirements(result)) or not scholarship.official_url:
        value *= EVIDENCE_PROBLEM_FACTOR
    return value


def _exclusions(result, deadline):
    found = []
    if result["status"] == NOT_ELIGIBLE:
        reasons = "; ".join(f"{item['label']}: {item['reason']}" for item in result["not_satisfied"])
        found.append({"rule": "not_eligible", "reason": reasons})
    if deadline["status"] == "closed":
        found.append({"rule": "closed", "reason": f"The listed deadline ({deadline['date']}) has passed, so you can't apply now. "
                                                  "This is separate from your eligibility."})
    return found


def _category(result, score, scholarship, conflict):
    """(category, why). Category limits come first: a score never lifts a result past them."""
    source_issue = next(
        (item for item in result["needs_verification"] if item["requirement"] == "source_evidence"),
        None,
    )
    if source_issue or scholarship.verification_status != "verified":
        return "needs_verification", source_issue["reason"] if source_issue else "This scholarship record is not verified."
    if conflict:
        return "needs_verification", "This record's details disagree, so check them first."
    if result["status"] == MISSING:
        return "needs_verification", "Your profile is missing information this scholarship needs."
    if result["status"] == NOT_EVALUATED:
        return "needs_verification", "Some eligibility requirements need verification before this can be considered a match."
    if result["status"] == ELIGIBLE:
        if score >= STRONG_MINIMUM:
            return "strong", "You meet the stated requirements and the score is high."
        if score >= GOOD_MINIMUM:
            return "good", "You meet the stated requirements."
        return "possible", "You meet the stated requirements, but the funding or evidence is weaker."
    if score >= POSSIBLE_MINIMUM:
        return "possible", "It looks suitable, but some requirements still need a manual check."
    return "needs_verification", "Too little could be confirmed for this scholarship."


def _reasons(result, funding, deadline, scholarship):
    positive, warnings, negative = [], [], []
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
    negative += [f"{item['label']}: {item['reason']}" for item in result["not_satisfied"]]
    if deadline["status"] == "closed":
        negative.append(f"The application period has closed ({deadline['date']}).")
    return positive, warnings, negative


def _breakdown(values):
    applied = sum(WEIGHTS[name] for name in values)
    rows = [{"dimension": name, "label": DIMENSION_LABELS[name], "weight": WEIGHTS[name], "value": round(value, 3),
             "points": round(100 * WEIGHTS[name] * value / applied, 1)} for name, value in values.items()]
    total = 100 * sum(WEIGHTS[name] * value for name, value in values.items()) / applied
    return rows, int(total + 0.5)


def recommend_scholarship(scholarship, profile, today=None) -> dict:
    """One scholarship's result. profile may be None: nothing is then treated as met."""
    today = today or date.today()
    result = evaluate_scholarship(scholarship, profile, today=today)
    source_issue = next(
        (item for item in result["needs_verification"] if item["requirement"] == "source_evidence"),
        None,
    )
    deadline = result["deadline"]
    funding = funding_summary(scholarship)
    exclusions = _exclusions(result, deadline)
    positive, warnings, negative = _reasons(result, funding, deadline, scholarship)
    preferred_degree_match = _preferred_degree_match(profile, scholarship)
    if preferred_degree_match is False:
        warnings.append("The scholarship's study level doesn't match your preferred target degree level.")
    if _funding_preference_match(funding, profile, scholarship) is False:
        funding_preference = " ".join(
            str(getattr(profile, "funding_preference", None) or "").lower().split()
        )
        preferred_types = {
            item.strip().lower() for item in (getattr(profile, "preferred_funding_types", None) or [])
            if isinstance(item, str) and item.strip()
        }
        if preferred_types == {"tuition waivers"} and scholarship.tuition_coverage_type == "none":
            warnings.append("Your profile prefers tuition waivers, but this record states that tuition is not covered.")
        elif funding_preference in ("fully funded only", "full funding required"):
            warnings.append("Your profile prefers fully funded scholarships only; this award is not confirmed as fully funded.")
        elif funding_preference == "fully funded or substantial scholarship":
            warnings.append("This award does not meet your preference for fully funded or substantial scholarships.")
        else:
            warnings.append("This award does not match your saved funding preference.")
    conflict = any(item.get("conflict") for item in _requirements(result))

    score = category = category_reason = None
    breakdown = []
    if not exclusions:
        academic_value = _academic_value(result)
        if preferred_degree_match is False:
            academic_value = 0.0
        values = {"eligibility": _eligibility_value(result),
                  "funding": _funding_value(funding, profile, scholarship),
                  "academic": academic_value, "deadline": DEADLINE_VALUES[deadline["status"]],
                  "evidence": _evidence_value(scholarship, result)}
        breakdown, score = _breakdown(values)
        category, category_reason = _category(result, score, scholarship, conflict)

    return {
        "scholarship_id": scholarship.id,
        "scholarship_name": scholarship.name,
        "provider": scholarship.provider,
        "country": scholarship.country,
        "rank": None,
        "recommended": not exclusions and source_issue is None,
        "score": score,
        "category": category,
        "category_label": CATEGORY_LABELS.get(category),
        "category_reason": category_reason,
        "exclusions": exclusions,
        "eligibility": {"status": result["status"], "outcome": result["outcome"], "summary": result["summary"]},
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


def recommend_for_student(db, profile, include_unverified=False, today=None) -> dict:
    """Ranked scholarships for a student, with the excluded ones listed apart."""
    records = get_student_scholarships(
        db,
        include_unverified=include_unverified,
        today=today,
    )
    records = deduplicate_student_scholarships(records)
    items = []
    for record in records:
        item = recommend_scholarship(record.scholarship, profile, today)
        item["source_provenance"] = record.source_provenance()
        items.append(item)

    ranked = [item for item in items if item["recommended"]]
    if include_unverified:
        # Opted-in records can be ranked for review without being marked recommended.
        ranked.extend(item for item in items if not item["recommended"] and item["category"] == "needs_verification")
    else:
        # Published discoveries are visible by default but never treated as verified matches.
        ranked.extend(
            item for item in items
            if not item["recommended"]
            and item["category"] == "needs_verification"
            and "live_discovery" in item["source_provenance"]["sources"]
        )
    ranked = sorted(ranked, key=_sort_key)
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    ranked_ids = {item["scholarship_id"] for item in ranked}
    excluded = sorted((item for item in items if item["scholarship_id"] not in ranked_ids),
                      key=lambda item: (item["scholarship_name"], item["scholarship_id"]))
    gaps = profile_gaps(items)
    for item in items:
        del item["_gaps"]
    counts = {key: sum(item["category"] == key for item in ranked) for key in CATEGORY_ORDER}
    return {
        "profile_complete": profile is not None and not gaps,
        "profile_gaps": gaps,
        "summary": {"recommended": sum(item["recommended"] for item in ranked), "excluded": len(excluded), **counts,
                    "eligible": sum(item["eligibility"]["status"] == ELIGIBLE for item in ranked if item["recommended"]),
                    "verify_manually": sum(item["eligibility"]["outcome"] == "verify_manually" for item in ranked if item["recommended"])},
        "weights": WEIGHTS,
        "recommendations": ranked,
        "excluded": excluded,
        "notes": [NOT_A_PROBABILITY],
    }


def recommend_one(db, scholarship, profile, today=None, source_provenance=None) -> dict:
    item = recommend_scholarship(scholarship, profile, today)
    item["source_provenance"] = source_provenance
    del item["_gaps"]
    return item
