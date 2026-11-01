"""
Whether a scholarship can support a program. This is about the pair of records, never a student:
nationality and residency are checked by scholarship_eligibility.py and can't prove program funding.

Outcomes
  confirmed           a reviewed relationship with official evidence, and nothing contradicts it
  potential           the structured fields fit, but no source confirms this program
  not_a_match         a stated condition rules the program out
  needs_verification  something important is missing, ambiguous, conflicting or thinly sourced

The rules alone can never give "confirmed", and a shared country is never enough: the scholarship
must also be open across that country's institutions or belong to the program's own university.
Universities are compared by ID, never by name.
"""
import re
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.models.opportunity import Program, Scholarship, ScholarshipProgramLink

CONFIRMED = "confirmed"
POTENTIAL = "potential"
NOT_A_MATCH = "not_a_match"
NEEDS_VERIFICATION = "needs_verification"

LABELS = {CONFIRMED: "Confirmed Match", POTENTIAL: "Potential Match", NOT_A_MATCH: "Not a Match",
          NEEDS_VERIFICATION: "Needs Verification"}

COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
UNKNOWN = "unknown"

# Program fields we can place in a broad group, and the listed disciplines that include that group
COMPUTING_FIELD = re.compile(r"comput|informatics|data science|artificial intelligence|machine learning|cyber|software", re.I)
COVERS_COMPUTING = {"stem", "technology", "engineering", "engineering sciences", "mathematics and digital science"}


def _criterion(name, status, detail):
    return {"criterion": name, "status": status, "detail": detail}


def _check_country(scholarship, program):
    host = scholarship.country
    country = program.university.country if program.university else None
    if not host or not country:
        return _criterion("country", UNKNOWN, "The scholarship's or program's country is not recorded.")
    if host.lower().startswith("european union"):
        return _criterion("country", UNKNOWN, "This award funds its own multi-country courses, so the host country doesn't settle it.")
    if country.lower() in host.lower():
        return _criterion("country", COMPATIBLE, f"Both are in {country}.")
    return _criterion("country", INCOMPATIBLE, f"This scholarship is for study in {host}, not {country}.")


def _check_degree(scholarship, program):
    level = program.degree_level or ""
    if not level:
        return _criterion("degree", UNKNOWN, "The program's degree level is not recorded.")
    if not re.match(r"master", level, re.I):
        return _criterion("degree", INCOMPATIBLE, f"This is a {level} program; these records cover Master's study.")
    levels = scholarship.eligible_degree_levels or []
    if not levels:
        return _criterion("degree", UNKNOWN, "The scholarship's degree levels are not recorded.")
    if "Master's" in levels:
        return _criterion("degree", COMPATIBLE, "The scholarship covers Master's study.")
    if any(re.match(r"master", item, re.I) for item in levels):
        return _criterion("degree", UNKNOWN, "The scholarship covers research Master's only, and the program's type isn't recorded.")
    return _criterion("degree", INCOMPATIBLE, f"This scholarship is for {', '.join(levels)} study.")


def _check_discipline(scholarship, program):
    scope = scholarship.discipline_scope
    field = program.field_of_study or ""
    if scope == "all":
        return _criterion("discipline", COMPATIBLE, "The scholarship isn't limited to certain fields.")
    disciplines = scholarship.eligible_disciplines or []
    if scope not in ("listed", "restricted") or not disciplines:
        return _criterion("discipline", UNKNOWN, "The record doesn't list which fields qualify.")
    named = ", ".join(disciplines)
    if not COMPUTING_FIELD.search(field):
        return _criterion("discipline", UNKNOWN, f"{field or 'This field'} can't be compared with the listed fields: {named}.")
    if any(item.lower() in COVERS_COMPUTING for item in disciplines):
        return _criterion("discipline", COMPATIBLE, f"{field} falls within the listed fields: {named}.")
    if scope == "listed":
        return _criterion("discipline", INCOMPATIBLE, f"This scholarship is for {named}, which doesn't include {field}.")
    return _criterion("discipline", UNKNOWN, f"The record's main fields are {named}; other fields aren't ruled out.")


def _check_university(scholarship, program):
    scope = scholarship.institution_scope
    name = program.university.name if program.university else "this university"
    if scope == "single_institution":
        if scholarship.host_university_id == program.university_id:
            return _criterion("university", COMPATIBLE, f"This is {name}'s own scholarship.")
        return _criterion("university", INCOMPATIBLE, f"This scholarship is only for {scholarship.host_institution}, not {name}.")
    if scope == "participating_list":
        return _criterion("university", UNKNOWN, f"Only listed institutions or courses take part, and {name} isn't confirmed as one.")
    if scope == "national":
        return _criterion("university", COMPATIBLE, "The scholarship isn't tied to one institution, but that doesn't prove it covers this program.")
    return _criterion("university", UNKNOWN, "The record doesn't say which institutions take part.")


def _check_other(scholarship):
    if scholarship.verification_status != "verified":
        return _criterion("other", UNKNOWN, "This scholarship record is not verified.")
    return _criterion("other", COMPATIBLE, "Who may hold the award is checked separately, against each student's profile.")


def _apply_link(rule_outcome, blocking, link, scholarship):
    """The final outcome and explanation once a stored relationship is taken into account."""
    if link.outcome == NOT_A_MATCH:
        return NOT_A_MATCH, "A reviewed relationship rules this program out."
    if rule_outcome == NOT_A_MATCH:
        return NEEDS_VERIFICATION, f"The stored relationship conflicts with the records: {blocking['detail']}"
    if link.outcome == CONFIRMED:
        if scholarship.verification_status != "verified":
            return NEEDS_VERIFICATION, "The relationship has evidence, but the scholarship record itself is not verified."
        return CONFIRMED, "An official source confirms this scholarship supports this program."
    if link.outcome == POTENTIAL:
        return POTENTIAL, "The records fit, but no official source confirms this program yet."
    return NEEDS_VERIFICATION, "Important evidence for this program is missing or unclear."


def evaluate_match(scholarship, program, link=None) -> dict:
    """The outcome for one pair. Pass the stored ScholarshipProgramLink when there is one."""
    criteria = [_check_country(scholarship, program), _check_degree(scholarship, program),
                _check_university(scholarship, program), _check_discipline(scholarship, program),
                _check_other(scholarship)]
    blocking = next((item for item in criteria if item["status"] == INCOMPATIBLE), None)
    unknown = next((item for item in criteria if item["status"] == UNKNOWN), None)
    if blocking:
        outcome, explanation = NOT_A_MATCH, blocking["detail"]
    elif unknown:
        outcome, explanation = NEEDS_VERIFICATION, unknown["detail"]
    else:
        outcome, explanation = POTENTIAL, "The records fit, but no official source confirms this program yet."
    if link is not None:
        outcome, explanation = _apply_link(outcome, blocking, link, scholarship)

    university = program.university
    return {
        "scholarship_id": scholarship.id,
        "scholarship_name": scholarship.name,
        "scholarship_country": scholarship.country,
        "funding_type": scholarship.funding_type,
        "scholarship_verification_status": scholarship.verification_status,
        "program_id": program.id,
        "program_name": program.name,
        "university_id": program.university_id,
        "university_name": university.name if university else None,
        "country": university.country if university else None,
        "degree_level": program.degree_level,
        "field_of_study": program.field_of_study,
        "outcome": outcome,
        "label": LABELS[outcome],
        "explanation": explanation,
        "blocking_criterion": blocking["criterion"] if blocking else None,
        "criteria": criteria,
        "has_relationship": link is not None,
        "relationship_type": link.relationship_type if link else None,
        "evidence": link.evidence if link else None,
        "source_url": link.source_url if link else None,
        "relationship_verification_status": link.verification_status if link else None,
        "last_verified": link.last_verified if link else None,
        "notes": link.notes if link else None,
    }


def get_link(db: Session, scholarship_id: int, program_id: int) -> Optional[ScholarshipProgramLink]:
    return (db.query(ScholarshipProgramLink)
            .filter(ScholarshipProgramLink.scholarship_id == scholarship_id, ScholarshipProgramLink.program_id == program_id)
            .first())


def _programs(db: Session):
    return db.query(Program).options(joinedload(Program.university)).order_by(Program.id).all()


def _outcome_order(result):
    return list(LABELS).index(result["outcome"])


def programs_for_scholarship(db: Session, scholarship, include_not_matches=False) -> list:
    links = {link.program_id: link for link in
             db.query(ScholarshipProgramLink).filter(ScholarshipProgramLink.scholarship_id == scholarship.id)}
    results = [evaluate_match(scholarship, program, links.get(program.id)) for program in _programs(db)]
    results = [item for item in results if include_not_matches or item["outcome"] != NOT_A_MATCH]
    return sorted(results, key=lambda item: (_outcome_order(item), item["program_id"]))


def scholarships_for_program(db: Session, program, include_not_matches=False, include_unverified=False) -> list:
    links = {link.scholarship_id: link for link in
             db.query(ScholarshipProgramLink).filter(ScholarshipProgramLink.program_id == program.id)}
    query = db.query(Scholarship).filter(Scholarship.archived_at.is_(None)).order_by(Scholarship.id)
    if not include_unverified:
        query = query.filter(Scholarship.verification_status == "verified")
    results = [evaluate_match(scholarship, program, links.get(scholarship.id)) for scholarship in query.all()]
    results = [item for item in results if include_not_matches or item["outcome"] != NOT_A_MATCH]
    return sorted(results, key=lambda item: (_outcome_order(item), item["scholarship_id"]))


def coverage_counts(db: Session, include_unverified=False) -> list:
    """How many programs each scholarship may support, for listings."""
    links = {(link.scholarship_id, link.program_id): link for link in db.query(ScholarshipProgramLink)}
    programs = _programs(db)
    query = db.query(Scholarship).filter(Scholarship.archived_at.is_(None)).order_by(Scholarship.id)
    if not include_unverified:
        query = query.filter(Scholarship.verification_status == "verified")
    rows = []
    for scholarship in query.all():
        outcomes = [evaluate_match(scholarship, program, links.get((scholarship.id, program.id)))["outcome"]
                    for program in programs]
        rows.append({"scholarship_id": scholarship.id, "confirmed": outcomes.count(CONFIRMED),
                     "potential": outcomes.count(POTENTIAL), "needs_verification": outcomes.count(NEEDS_VERIFICATION)})
    return rows


def match_for_financial(db: Session, scholarship, program) -> Optional[dict]:
    """The outcome Financial Feasibility should respect, or None when no relationship information
    exists for this pair and nothing rules it out, so the calculation stays as it was."""
    link = get_link(db, scholarship.id, program.id)
    result = evaluate_match(scholarship, program, link)
    return result if link is not None or result["outcome"] == NOT_A_MATCH else None
