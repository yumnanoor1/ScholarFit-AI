"""
Administration of scholarship records: data quality checks, the audit trail, and the rules for
changing a record. Reports problems and blocks unsafe writes; it never verifies, merges or deletes
anything by itself, and it never fills a structured field from text.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text, update

from app.models.opportunity import Scholarship, ScholarshipAuditLog, ScholarshipProgramLink, University
from app.models.user import SavedScholarship
from app.models.scholarship_knowledge import ScholarshipSourceDocument
from app.schemas.opportunity import ScholarshipResponse
from app.services.scholarship_eligibility import FULL_DATE_RE, ISO_DATE_RE, MONTHS, check_nationality, evaluate_scholarship
from app.services.source_url_safety import safe_source_url

STALE_AFTER_DAYS = 180
DUPLICATE_NAME_OVERLAP = 0.8
MANUAL_FLAGS = {"conflicting_information": "Conflicting information", "outdated_source": "Outdated source",
                "broken_source": "Broken source", "needs_reverification": "Needs re-verification"}
VERIFICATION_FIELDS = {"verification_basis", "verification_notes", "last_verified_date", "last_verified"}
GUARDED_FIELDS = VERIFICATION_FIELDS | {"duplicate_of_id"}

# Original wording and the structured values read from it. A change to one side alone needs a review.
REVIEW_GROUPS = {
    "nationality": (("eligible_nationalities", "pakistan_eligible"),
                    ("nationality_scope", "eligible_countries", "excluded_countries", "eligible_regions", "excluded_regions")),
    "degree": (("degree_level", "bachelors_requirement"), ("eligible_degree_levels", "required_previous_degree")),
    "field": (("eligible_fields",), ("discipline_scope", "eligible_disciplines")),
    "academic": (("min_academic_requirement",), ("academic_condition", "min_gpa", "min_gpa_scale", "min_percentage")),
    "english": (("english_requirement",), ("english_requirement_type", "accepted_english_tests", "min_ielts", "min_toefl", "min_duolingo")),
    "age": (("age_requirement",), ("min_age", "max_age")),
    "funding": (("funding_type", "tuition_coverage", "living_stipend", "travel_airfare", "accommodation", "health_insurance"),
                ("funding_level", "tuition_coverage_type", "tuition_percent_min", "tuition_percent_max", "tuition_amount", "tuition_amount_max",
                 "tuition_currency", "tuition_period", "stipend_status", "stipend_amount", "stipend_amount_max", "stipend_currency", "stipend_period",
                 "accommodation_status", "health_insurance_status", "travel_status", "travel_amount", "travel_currency", "funding_duration_months",
                 "costs_not_covered")),
    "deadline": (("deadline",), ("deadline_type", "application_open_date", "application_deadline_date", "application_cycle")),
    "documents": (("required_documents",), ("required_documents_list",)),
}
GROUP_LABELS = {"nationality": "Nationality", "degree": "Degree", "field": "Field of study", "academic": "Academic requirement",
                "english": "English requirement", "age": "Age", "funding": "Funding", "deadline": "Deadline", "documents": "Required documents"}
FUNDING_TEXT = {"Fully Funded": "full", "Partially Funded": "partial", "Tuition Only": "tuition_only", "Mixed Funding": "mixed"}


def _issue(code, label, severity, detail):
    return {"code": code, "label": label, "severity": severity, "detail": detail}


def _unspecified(*values):
    return [value for value in values if value in (None, "", "not_specified")]


def _stated_dates(text):
    found = set()
    for day, month, year in FULL_DATE_RE.findall(text or ""):
        number = MONTHS.get(month.lower()) or next((value for name, value in MONTHS.items() if name.startswith(month.lower()[:3])), None)
        found.add((int(year), number, int(day)))
    found |= {(int(year), int(month), int(day)) for year, month, day in ISO_DATE_RE.findall(text or "")}
    return found


def find_conflicts(scholarship, today=None) -> list:
    """Disagreements between the structured values and the original wording."""
    today = today or date.today()
    conflicts = []
    result = evaluate_scholarship(scholarship, None, today=today)
    for item in result["needs_verification"]:
        if item.get("conflict") and item["requirement"] != "record_review":
            conflicts.append(f"{item['label']}: {item['reason']}")
    if (scholarship.pakistan_eligible or "").strip():
        nationality = check_nationality(scholarship, "Pakistan")
        if nationality and nationality.get("conflict"):
            conflicts.append(f"Nationality: {nationality['reason']}")
    stated_level = FUNDING_TEXT.get(scholarship.funding_type)
    if stated_level and scholarship.funding_level and stated_level != scholarship.funding_level:
        conflicts.append(f"Funding: the record says {scholarship.funding_type}, but the funding level is {scholarship.funding_level}.")
    day = scholarship.application_deadline_date
    stated = _stated_dates(scholarship.deadline)
    if day and stated and (day.year, day.month, day.day) not in stated:
        conflicts.append(f"Deadline: {day.isoformat()} isn't among the dates in the deadline wording.")
    return conflicts


def find_issues(scholarship, today=None, duplicate_ids=frozenset()) -> list:
    """What needs attention on one record, most serious first."""
    today = today or date.today()
    issues = [_issue("conflict", "Conflicting information", "high", text) for text in find_conflicts(scholarship, today)]
    flags = scholarship.data_flags or []
    for flag in flags:
        if flag.startswith("review:"):
            group = flag.split(":", 1)[1]
            issues.append(_issue("needs_review", f"{GROUP_LABELS.get(group, group)} needs review", "high",
                                 "Its wording and structured values were changed separately."))
        elif flag in MANUAL_FLAGS:
            code = "conflict" if flag == "conflicting_information" else flag
            issues.append(_issue(code, MANUAL_FLAGS[flag], "high", "Flagged by an administrator."))
    if scholarship.verification_status != "verified":
        issues.append(_issue("unverified", "Unverified", "high", "This record isn't verified, so it's hidden from students by default."))
    if not scholarship.official_info_url:
        issues.append(_issue("missing_official_source", "No official source", "high", "No official information page is recorded."))
    if scholarship.verification_status == "verified" and scholarship.verification_basis != "official_source":
        issues.append(_issue("weak_evidence", "Not fully officially sourced", "medium", f"Verification basis: {scholarship.verification_basis or 'not recorded'}."))
    for check in scholarship.source_checks or []:
        if isinstance(check, dict) and check.get("status") == "broken":
            checked_url = safe_source_url(check.get("url")) or "[redacted invalid source URL]"
            issues.append(_issue("broken_url", "Broken link", "high",
                                 f"{checked_url} answered {check.get('http_status')} when checked."))
    if not scholarship.official_application_url and scholarship.application_channel not in ("automatic", "nomination"):
        issues.append(_issue("missing_application_url", "No application link", "medium", "No application page is recorded."))
    if scholarship.deadline_type in (None, "not_specified") or (scholarship.deadline_type == "fixed" and not scholarship.application_deadline_date):
        issues.append(_issue("missing_deadline", "Deadline missing", "medium", "No usable deadline is recorded."))
    if _unspecified(scholarship.funding_level, scholarship.tuition_coverage_type, scholarship.stipend_status):
        issues.append(_issue("missing_funding", "Funding details missing", "medium", "Funding level, tuition or stipend isn't specified."))
    if _unspecified(scholarship.nationality_scope, scholarship.discipline_scope, scholarship.academic_condition, scholarship.english_requirement_type):
        issues.append(_issue("missing_eligibility", "Eligibility details missing", "medium", "Nationality, field, academic or English rules aren't specified."))
    if not scholarship.structured_data_version:
        issues.append(_issue("no_structured_data", "No structured data", "high", "This record has no reviewed structured fields."))
    verified_on = scholarship.last_verified_date
    if verified_on is None:
        issues.append(_issue("never_verified", "No verification date", "medium", "No verification date is recorded."))
    elif verified_on < today - timedelta(days=STALE_AFTER_DAYS):
        issues.append(_issue("stale_verification", "Verification is old", "medium", f"Last verified on {verified_on.isoformat()}."))
    if scholarship.duplicate_of_id or scholarship.id in duplicate_ids:
        issues.append(_issue("duplicate", "Duplicate", "low", "Flagged as a duplicate or suspected duplicate."))
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(issues, key=lambda item: order[item["severity"]])


def _fold_name(name):
    plain = unicodedata.normalize("NFKD", (name or "").replace("ı", "i"))
    words = re.findall(r"[a-z0-9]+", "".join(char for char in plain if not unicodedata.combining(char)).lower())
    return {word for word in words if word not in {"the", "of", "for", "scholarship", "scholarships", "master", "masters", "s", "programme", "program"}}


def duplicate_pairs(rows) -> list:
    """Flagged pairs, plus suspected ones: same host country and nearly the same name. Never merged here."""
    by_id = {row.id: row for row in rows}
    pairs = [{"first_id": row.duplicate_of_id, "second_id": row.id, "kind": "flagged",
              "first_name": by_id[row.duplicate_of_id].name, "second_name": row.name}
             for row in rows if row.duplicate_of_id in by_id]
    known = {(pair["first_id"], pair["second_id"]) for pair in pairs}
    for index, first in enumerate(rows):
        for second in rows[index + 1:]:
            if (first.id, second.id) in known or first.country != second.country:
                continue
            one, two = _fold_name(first.name), _fold_name(second.name)
            if one and two and len(one & two) / len(one | two) >= DUPLICATE_NAME_OVERLAP:
                pairs.append({"first_id": first.id, "second_id": second.id, "kind": "suspected",
                              "first_name": first.name, "second_name": second.name})
    return pairs


def _plain(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def field_changes(before: dict, after: dict) -> dict:
    return {field: [_plain(before.get(field)), _plain(after[field])] for field in after if before.get(field) != after[field]}


def record_audit(db, scholarship_id, action, admin, changes=None, note=None):
    db.add(ScholarshipAuditLog(scholarship_id=scholarship_id, action=action, changes=changes or None, note=note,
                               actor_id=admin.id, actor_email=admin.email))


def record_discovery_audit(db, scholarship_id, action, changes=None, note=None):
    db.add(ScholarshipAuditLog(
        scholarship_id=scholarship_id,
        action=action,
        changes=changes or None,
        note=note,
        actor_id=None,
        actor_email="system:scholarship-discovery",
    ))


def update_scholarship_if_current(db, item, values: dict) -> int:
    """Atomically update a record only if its version is still current."""
    previous_version = item.record_version
    version_filter = (
        Scholarship.record_version.is_(None)
        if previous_version is None
        else Scholarship.record_version == previous_version
    )
    next_version = (previous_version or 0) + 1
    result = db.execute(
        update(Scholarship)
        .where(Scholarship.id == item.id, version_filter)
        .values(**{**values, "record_version": next_version})
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Someone changed this record after you opened it. Reload it so nothing is lost.",
        )
    db.expire(item)
    return next_version


def reference_counts(db, scholarship_id) -> dict:
    """How much depends on a record. Counts only, so no student is identified."""
    program_link_count = db.query(ScholarshipProgramLink).filter(
        ScholarshipProgramLink.scholarship_id == scholarship_id
    ).count()
    return {"saved_by_students": db.query(SavedScholarship).filter(SavedScholarship.scholarship_id == scholarship_id).count(),
            "program_links": program_link_count,
            "internal_links": program_link_count,
            "knowledge_documents": db.query(ScholarshipSourceDocument).filter(
                ScholarshipSourceDocument.scholarship_id == scholarship_id
            ).count(),
            "duplicates_pointing_here": db.query(Scholarship).filter(Scholarship.duplicate_of_id == scholarship_id).count()}


def _check_references(db, values, scholarship_id=None):
    university_id = values.get("host_university_id")
    if university_id is not None and not db.get(University, university_id):
        raise HTTPException(status_code=422, detail="host_university_id is not a university in the catalog")
    if values.get("institution_scope") == "single_institution" and not values.get("host_institution"):
        raise HTTPException(status_code=422, detail="A single-institution scholarship needs its host institution")


def write_result(item, warnings) -> dict:
    return {**ScholarshipResponse.model_validate(item).model_dump(), "data_flags": item.data_flags, "warnings": warnings}


def create_record(db, values: dict, admin) -> Scholarship:
    """New records always start unverified: the verification endpoint is the only way to verified."""
    _check_references(db, values)
    values = {key: value for key, value in values.items() if key not in GUARDED_FIELDS}
    _lock_identity(db, values.get("name"), values.get("country"))
    _reject_duplicate_identity(db, values.get("name"), values.get("country"))
    item = Scholarship(**values, verification_status="unverified", verification_basis="not_verified",
                       structured_data_version=1, record_version=1)
    db.add(item)
    db.flush()
    record_audit(db, item.id, "created", admin)
    db.commit()
    db.refresh(item)
    return item


def find_identity_record(db, name, country):
    normalized_name = _normalized_identity(name)
    normalized_country = _normalized_identity(country)
    return next(
        (
            item for item in db.query(Scholarship).filter(Scholarship.archived_at.is_(None)).all()
            if _normalized_identity(item.name) == normalized_name
            and _normalized_identity(item.country) == normalized_country
        ),
        None,
    )


def find_possible_duplicate_records(db, name, country):
    """Return same-country records whose names are close enough to require human review."""
    normalized_country = _normalized_identity(country)
    candidate_name = _fold_name(name)
    if not normalized_country or not candidate_name:
        return []

    matches = []
    for item in db.query(Scholarship).filter(Scholarship.archived_at.is_(None)).all():
        if _normalized_identity(item.country) != normalized_country:
            continue
        existing_name = _fold_name(item.name)
        if existing_name and len(candidate_name & existing_name) / len(candidate_name | existing_name) >= DUPLICATE_NAME_OVERLAP:
            matches.append(item)
    return matches


def create_discovered_record(db, values: dict, evidence_note: str, evidence: dict, *, commit=True) -> Scholarship:
    """Create an explicitly unverified discovery candidate without impersonating an administrator."""
    _check_references(db, values)
    values = {key: value for key, value in values.items() if key not in GUARDED_FIELDS}
    _lock_identity(db, values.get("name"), values.get("country"))
    _reject_duplicate_identity(db, values.get("name"), values.get("country"))
    item = Scholarship(
        **values,
        verification_status="unverified",
        verification_basis="not_verified",
        structured_data_version=1,
        record_version=1,
        data_flags=[],
    )
    conflicts = find_conflicts(item)
    if conflicts:
        item.data_flags = ["conflicting_information"]
    db.add(item)
    db.flush()
    record_discovery_audit(
        db,
        item.id,
        "discovery_created",
        changes={"evidence": evidence, "conflicts": conflicts},
        note=evidence_note,
    )
    if commit:
        db.commit()
        db.refresh(item)
    return item


def flag_discovery_proposal(db, item, proposed_values: dict, evidence_note: str, evidence: dict, *, commit=True):
    """Keep reviewed fields untouched and attach a machine-proposed change to the audit trail."""
    changes = field_changes(
        {field: getattr(item, field) for field in proposed_values},
        proposed_values,
    )
    flags = set(item.data_flags or [])
    if changes:
        flags.add("conflicting_information")
        update_scholarship_if_current(db, item, {"data_flags": sorted(flags)})
    record_discovery_audit(
        db,
        item.id,
        "discovery_proposal" if changes else "discovery_duplicate_skipped",
        changes={"proposed_values": changes, "evidence": evidence} if changes else {"evidence": evidence},
        note=evidence_note,
    )
    if commit:
        db.commit()
        db.refresh(item)
    return bool(changes)


def _review_flags(changed: set, flags: list, reviewed: list) -> tuple:
    """(open flags after this change, groups newly flagged)."""
    keep = set(flags)
    raised = []
    for group, (text, structured) in REVIEW_GROUPS.items():
        text_changed = bool(changed & set(text))
        structured_changed = bool(changed & set(structured))
        flag = f"review:{group}"
        if group in reviewed or (text_changed and structured_changed):
            keep.discard(flag)
        elif text_changed or structured_changed:
            keep.add(flag)
            raised.append(group)
    return sorted(keep), raised


def _normalized_identity(value):
    return " ".join((value or "").casefold().split())


def _reject_duplicate_identity(db, name, country, exclude_id=None):
    normalized_name = _normalized_identity(name)
    normalized_country = _normalized_identity(country)
    duplicate = next(
        (
            item for item in db.query(Scholarship).filter(Scholarship.archived_at.is_(None)).all()
            if item.id != exclude_id
            and _normalized_identity(item.name) == normalized_name
            and _normalized_identity(item.country) == normalized_country
        ),
        None,
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A scholarship with this name and host country already exists")


def _lock_identity(db, name, country):
    if db.get_bind().dialect.name == "postgresql":
        identity = f"{_normalized_identity(name)}\x1f{_normalized_identity(country)}"
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": identity},
        )


def update_record(db, item, data, admin) -> list:
    """Applies an edit and returns warnings for the administrator."""
    sent = data.model_dump(exclude_unset=True)
    expected = sent.pop("expected_version", None)
    reviewed = sent.pop("reviewed_groups", None) or []
    note = sent.pop("audit_note", None)
    unknown = sorted(set(reviewed) - set(REVIEW_GROUPS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown requirement group: {', '.join(unknown)}")
    if expected is not None and expected != (item.record_version or 0):
        raise HTTPException(status_code=409, detail="Someone changed this record after you opened it. Reload it so nothing is lost.")
    status_value = sent.pop("verification_status", None)
    if status_value is not None and status_value != item.verification_status:
        raise HTTPException(status_code=422, detail="Use the verification controls to change verification status")
    before = {field: getattr(item, field) for field in sent}
    changes = field_changes(before, sent)
    guarded = sorted(set(changes) & GUARDED_FIELDS)
    if guarded:
        raise HTTPException(status_code=422, detail=f"Use the verification or duplicate controls for: {', '.join(guarded)}")
    if "name" in changes and not (sent.get("name") or "").strip() or "country" in changes and not (sent.get("country") or "").strip():
        raise HTTPException(status_code=422, detail="Name and host country can't be empty")
    target_name = sent.get("name", item.name)
    target_country = sent.get("country", item.country)
    _lock_identity(db, target_name, target_country)
    _reject_duplicate_identity(db, target_name, target_country, item.id)
    _check_references(db, {"host_university_id": sent.get("host_university_id", item.host_university_id),
                           "institution_scope": sent.get("institution_scope", item.institution_scope),
                           "host_institution": sent.get("host_institution", item.host_institution)})
    if not changes and not reviewed:
        return []
    old_flags = item.data_flags or []
    updated_flags, raised = _review_flags(set(changes), old_flags, reviewed)
    values = {field: sent[field] for field in changes}
    if updated_flags != old_flags or (changes and item.data_flags is None):
        values["data_flags"] = updated_flags
    if not values:
        return []
    update_scholarship_if_current(db, item, values)
    audit_changes = changes or {"data_flags": [old_flags, updated_flags]}
    record_audit(db, item.id, "updated", admin, audit_changes, note)
    db.commit()
    db.refresh(item)
    warnings = [f"{GROUP_LABELS[group]}: the wording and structured values were changed separately, so this is held for review."
                for group in raised]
    return warnings + [f"Still conflicting - {text}" for text in find_conflicts(item)]


def delete_record(db, item, admin):
    references = reference_counts(db, item.id)
    if any(references.values()):
        raise HTTPException(status_code=409, detail=f"This record is in use ({references}), so archive it instead of deleting it.")
    record_audit(db, item.id, "deleted", admin, {"name": [item.name, None]})
    db.delete(item)
    db.commit()


def set_archived(db, item, admin, reason: Optional[str]):
    archiving = reason is not None
    values = {
        "archived_at": datetime.now(timezone.utc) if archiving else None,
        "archived_by_id": admin.id if archiving else None,
        "archive_reason": reason,
    }
    update_scholarship_if_current(db, item, values)
    record_audit(db, item.id, "archived" if archiving else "restored", admin, note=reason)
    db.commit()
    db.refresh(item)
