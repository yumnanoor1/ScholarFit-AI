"""
Search, filters and sorting for Explore Scholarships. Eligibility, relationships, deadlines, funding
tiers and scores all come from recommend_scholarship, so this file holds no rules of its own: it only
decides which results to show and in what order.

The catalog is small, so one query per request (narrowed in SQL by visibility and host country) is
filtered here. Accent-insensitive word matching and the computed filters can't be done in SQL anyway.

Host country and eligible nationality are separate: host is scholarships.country, and nationality
goes through the eligibility engine's check_nationality.
"""
import re
import unicodedata
from collections import Counter
from datetime import date
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.models.opportunity import Program, Scholarship, ScholarshipProgramLink
from app.services.scholarship_eligibility import NOT_SATISFIED, check_nationality, evaluate_scholarship, scholarship_deadline
from app.services.scholarship_matching import LABELS as MATCH_LABELS, NOT_A_MATCH
from app.services.scholarship_recommendations import FUNDING_LABELS, FUNDING_VALUES, funding_summary, profile_gaps, recommend_scholarship

ALL_FIELDS = "all_fields"
# Structured fields are searched first; these text columns are the fallback.
# Long free-text notes aren't searched: nearly every one mentions universities, Pakistan and funding.
# Brackets in a description are skipped because they list what's excluded ("(Erasmus Mundus ... excluded)").
STRUCTURED_SEARCH = {"Name": lambda s: s.name, "Provider": lambda s: s.provider, "Host country": lambda s: s.country,
                     "Institution": lambda s: s.host_institution,
                     "Eligible nationalities": lambda s: " ".join(s.eligible_countries or []),
                     "Degree level": lambda s: " ".join(s.eligible_degree_levels or []),
                     "Disciplines": lambda s: " ".join(s.eligible_disciplines or [])}
TEXT_SEARCH = {"Eligible nationalities": lambda s: s.eligible_nationalities, "Degree level": lambda s: s.degree_level,
               "Disciplines": lambda s: s.eligible_fields, "Description": lambda s: re.sub(r"[(][^)]*[)]", " ", s.study_type or ""),
               "Academic requirements": lambda s: s.min_academic_requirement}

BENEFITS = {"stipend": lambda s: s.stipend_status in ("provided", "included_in_package"),
            "accommodation": lambda s: s.accommodation_status in ("covered", "partial"),
            "travel": lambda s: s.travel_status == "covered",
            "health_insurance": lambda s: s.health_insurance_status in ("covered", "partial")}
BENEFIT_LABELS = {"stipend": "Stipend", "accommodation": "Accommodation", "travel": "Travel", "health_insurance": "Health insurance"}
DEADLINE_LABELS = {"open": "Open", "upcoming": "Upcoming", "rolling": "Rolling", "no_separate_deadline": "No separate deadline",
                   "closed": "Closed", "unknown": "Unknown"}
SCOPE_LABELS = {"all": "Open to all nationalities", "all_except": "All except named countries", "listed": "Named countries only",
                "published_list": "Published country list"}
CONDITION_LABELS = {"numeric": "Fixed minimum grade", "degree_class": "Degree class", "class_rank": "Class rank",
                    "merit_based": "Merit-based, no fixed minimum", "set_by_institution": "Set by the university", "not_specified": "Not specified"}
FUNDING_ORDER = sorted(FUNDING_VALUES, key=FUNDING_VALUES.get, reverse=True)


def short_country(country: Optional[str]) -> str:
    """"European Union (multi-country, ...)" -> "European Union"."""
    return re.sub(r"\s*\(.*\)\s*$", "", country or "")


def _fold(text: Optional[str]) -> str:
    plain = unicodedata.normalize("NFKD", (text or "").replace("ı", "i"))
    return "".join(char for char in plain if not unicodedata.combining(char)).lower()


def search_terms(query: Optional[str]) -> list:
    return _fold(query).split()


def _hits(fields, scholarship, terms):
    """Field labels whose words start with a term. The word start keeps "law" from matching "flaw"."""
    return {label: [term for term in terms if re.search(rf"\b{re.escape(term)}", _fold(read(scholarship)))] for label, read in fields.items()}


def match_search(scholarship, terms):
    """(matched field labels, found in structured fields only). Every term must be found somewhere."""
    structured = _hits(STRUCTURED_SEARCH, scholarship, terms)
    text = _hits(TEXT_SEARCH, scholarship, terms)
    in_structured = {term for found in structured.values() for term in found}
    in_text = {term for found in text.values() for term in found}
    if not set(terms) <= in_structured | in_text:
        return None, False
    labels = [label for label, found in structured.items() if found]
    labels += [label for label, found in text.items() if found and label not in labels]
    return labels, set(terms) <= in_structured


def _covers_discipline(scholarship, wanted):
    if scholarship.discipline_scope == "all":
        return True
    return any(item in (scholarship.eligible_disciplines or []) for item in wanted if item != ALL_FIELDS)


def _passes_record_filters(scholarship, filters):
    if filters.get("degree") and not set(filters["degree"]) & set(scholarship.eligible_degree_levels or []):
        return False
    if filters.get("discipline") and not _covers_discipline(scholarship, filters["discipline"]):
        return False
    if filters.get("academic_condition") and scholarship.academic_condition not in filters["academic_condition"]:
        return False
    if filters.get("nationality_scope") and scholarship.nationality_scope not in filters["nationality_scope"]:
        return False
    if any(not BENEFITS[item](scholarship) for item in filters.get("benefit") or []):
        return False
    return True


def _passes_result_filters(item, filters):
    if filters.get("funding") and item["funding"]["tier"] not in filters["funding"]:
        return False
    if filters.get("deadline") and item["deadline"]["status"] not in filters["deadline"]:
        return False
    if "conflicting" in (filters.get("verification") or []) and not item["has_conflict"]:
        return False
    if filters.get("eligibility") and item["eligibility"]["outcome"] not in filters["eligibility"]:
        return False
    match = item["program_match"]
    if match:
        wanted = filters.get("match") or []
        if match["outcome"] not in wanted and (wanted or match["outcome"] == NOT_A_MATCH):
            return False
    return True


def _last(value, present):
    """Missing values sort after present ones in every direction."""
    return (0, value) if present else (1, value)


def _deadline_key(item):
    day = item["deadline"]["date"]
    closed = item["deadline"]["status"] == "closed"
    if not day:
        return 2, ""
    return (1, _negated(day)) if closed else (0, day)


def _negated(day):
    """Most recently closed first: days before a fixed date, so a larger date sorts earlier."""
    return (date(9999, 1, 1) - date.fromisoformat(day)).days


SORTS = {
    "recommendation": lambda item: _last(-(item["score"] or 0), item["score"] is not None),
    "name": lambda item: _fold(item["scholarship_name"]),
    "deadline": _deadline_key,
    "funding": lambda item: FUNDING_ORDER.index(item["funding"]["tier"]),
    "country": lambda item: _fold(short_country(item["country"])),
    "verified": lambda item: _last(-(item["_verified"].toordinal() if item["_verified"] else 0), item["_verified"] is not None),
}


def _sorted(items, sort):
    def key(item):
        tie = (_fold(item["scholarship_name"]), item["scholarship_id"])
        if sort == "relevance":
            return (not item["_structured_hit"], *tie)
        return (SORTS[sort](item), *tie)

    return sorted(items, key=key)


def search_scholarships(db, filters: dict, profile, signed_in: bool, program=None, sort: Optional[str] = None,
                        skip: int = 0, limit: int = 20, today=None) -> dict:
    today = today or date.today()
    terms = search_terms(filters.get("q"))
    statuses = [item for item in filters.get("verification") or [] if item != "conflicting"] or ["verified"]
    query = db.query(Scholarship).filter(Scholarship.verification_status.in_(statuses), Scholarship.archived_at.is_(None))
    hosts = filters.get("host_country") or []
    if hosts:
        query = query.filter(or_(*[Scholarship.country == host for host in hosts],
                                 *[Scholarship.country.startswith(f"{host} (", autoescape=True) for host in hosts]))
    links = {}
    if program is not None:
        links = {link.scholarship_id: link for link in
                 db.query(ScholarshipProgramLink).filter(ScholarshipProgramLink.program_id == program.id)}

    nationality = (filters.get("nationality") or "").strip()
    matched = []
    gaps_from = []
    for scholarship in query.order_by(Scholarship.id).all():
        labels, structured_hit = match_search(scholarship, terms) if terms else ([], True)
        if labels is None or not _passes_record_filters(scholarship, filters):
            continue
        nationality_status = None
        if nationality:
            nationality_status = (check_nationality(scholarship, nationality) or {"status": None})["status"]
            if nationality_status == NOT_SATISFIED:
                continue
        item = recommend_scholarship(scholarship, profile, program, links.get(scholarship.id), None, today)
        if not _passes_result_filters(item, filters):
            continue
        gaps_from.append(item)
        matched.append((scholarship, item, labels, structured_hit, nationality_status))

    # The same opportunity shows once when both records match
    present = {scholarship.id for scholarship, *_ in matched}
    results = []
    for scholarship, item, labels, structured_hit, nationality_status in matched:
        if scholarship.duplicate_of_id in present:
            continue
        results.append({**item, "scholarship": scholarship, "matched_fields": labels, "nationality_status": nationality_status,
                        "_structured_hit": structured_hit, "_verified": scholarship.last_verified_date})

    sort = sort or ("relevance" if terms else "recommendation" if signed_in else "name")
    ordered = _sorted(results, sort)
    gaps = profile_gaps(gaps_from) if signed_in else []
    return {
        "total": len(ordered),
        "skip": skip,
        "limit": limit,
        "sort": sort,
        "signed_in": signed_in,
        "profile_incomplete": signed_in and (profile is None or bool(gaps)),
        "profile_gaps": gaps,
        "program": {"id": program.id, "name": program.name} if program is not None else None,
        "items": [_public(item, signed_in) for item in ordered[skip:skip + limit]],
    }


def _public(item, signed_in):
    """Only what Explore shows. Personal results are left out for visitors who aren't signed in."""
    return {
        "scholarship": item["scholarship"],
        "matched_fields": item["matched_fields"],
        "nationality_status": item["nationality_status"],
        "funding_tier": item["funding"]["tier"],
        "funding_label": item["funding"]["label"],
        "deadline": item["deadline"],
        "has_conflict": item["has_conflict"],
        "eligibility": item["eligibility"] if signed_in else None,
        "score": item["score"] if signed_in else None,
        "category_label": item["category_label"] if signed_in else None,
        "exclusions": item["exclusions"] if signed_in else [],
        "program_match": item["program_match"],
    }


def filter_options(db, today=None) -> dict:
    """The filter choices the data really supports, with counts over the verified catalog."""
    today = today or date.today()
    rows = db.query(Scholarship).filter(Scholarship.archived_at.is_(None)).order_by(Scholarship.id).all()
    visible = [item for item in rows if item.verification_status == "verified"]
    unverified = len(rows) - len(visible)
    conflicts = sum(any(req.get("conflict") for req in evaluate_scholarship(item, None, today=today)["needs_verification"]) for item in visible)

    def options(counts, labels=None):
        return [{"value": value, "label": (labels or {}).get(value, value), "count": count}
                for value, count in sorted(counts.items(), key=lambda pair: str((labels or {}).get(pair[0], pair[0]))) if value and count]

    disciplines = Counter(name for item in visible for name in item.eligible_disciplines or [])
    open_to_all = sum(item.discipline_scope == "all" for item in visible)
    deadlines = Counter(scholarship_deadline(item, today)["status"] for item in visible)
    tiers = Counter(funding_summary(item)["tier"] for item in visible)
    programs = db.query(Program).options(joinedload(Program.university)).order_by(Program.name, Program.id).all()
    return {
        "host_countries": options(Counter(short_country(item.country) for item in visible)),
        "degree_levels": options(Counter(level for item in visible for level in item.eligible_degree_levels or [])),
        "disciplines": ([{"value": ALL_FIELDS, "label": "Open to all fields", "count": open_to_all}] if open_to_all else []) + options(disciplines),
        "nationality_scopes": options(Counter(item.nationality_scope for item in visible), SCOPE_LABELS),
        "academic_conditions": options(Counter(item.academic_condition for item in visible), CONDITION_LABELS),
        "funding": [{"value": tier, "label": FUNDING_LABELS[tier], "count": tiers[tier]} for tier in FUNDING_ORDER if tiers[tier]],
        "benefits": [{"value": name, "label": BENEFIT_LABELS[name], "count": sum(check(item) for item in visible)}
                     for name, check in BENEFITS.items() if any(check(item) for item in visible)],
        "deadlines": [{"value": name, "label": label, "count": deadlines[name]} for name, label in DEADLINE_LABELS.items() if deadlines[name]],
        "verification": [item for item in (
            {"value": "verified", "label": "Verified", "count": len(visible)},
            {"value": "unverified", "label": "Unverified", "count": unverified},
            {"value": "conflicting", "label": "Conflicting information", "count": conflicts}) if item["count"]],
        "match_outcomes": [{"value": key, "label": label, "count": 0} for key, label in MATCH_LABELS.items()],
        "nationalities": sorted({"Pakistan", *(name for item in rows for name in (item.eligible_countries or []) + (item.excluded_countries or []))}),
        "programs": [{"id": item.id, "name": item.name, "university": item.university.name if item.university else None} for item in programs],
    }
