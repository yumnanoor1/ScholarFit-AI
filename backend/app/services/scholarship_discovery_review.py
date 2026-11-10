"""Persistence and Admin decisions for discoveries that need human review."""
from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import text

from app.models.opportunity import Scholarship
from app.models.scholarship_discovery import ScholarshipDiscoveryReviewItem
from app.models.scholarship_discovery_publication import ScholarshipDiscoveryPublicationVersion
from app.schemas.opportunity import ScholarshipCreate
from app.services.scholarship_quality import (
    GUARDED_FIELDS,
    _lock_identity,
    create_discovered_record,
    find_possible_duplicate_records,
    record_audit,
)
from app.services.scholarship_discovery_fetch import resolve_trusted_source_url
from app.services.scholarship_discovery_publications import publish_review_item
from app.services.source_url_safety import safe_source_urls_in_text

REQUIRED_DISCOVERY_FIELDS = ("name", "country", "degree_level")
SOURCE_PRIORITY = {
    "trusted_listing": 1,
    "official_provider": 2,
    "government_authority": 2,
}
NON_COMPARABLE_FIELDS = {
    "source_name",
    "official_info_url",
    "official_application_url",
    "additional_source_urls",
}


def _identity(value):
    return " ".join((value or "").casefold().split()) if isinstance(value, str) else ""


def _safe_page_url(source, page):
    safe_url = resolve_trusted_source_url(page.url, page.url, source)
    if safe_url is None:
        raise ValueError("Discovery source URL is invalid")
    return safe_url


def _sanitize_url_text(value):
    if isinstance(value, str):
        return safe_source_urls_in_text(value)
    if isinstance(value, dict):
        return {key: _sanitize_url_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_url_text(item) for item in value]
    return value


def _fingerprint(source, page, values, evidence, page_url):
    material = {
        "source_id": source.source_id,
        "source_url": page_url,
        "content_hash": page.content_hash,
        "values": jsonable_encoder(values),
        "evidence": jsonable_encoder(evidence),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_entry(
    source,
    page,
    values,
    evidence,
    candidate_conflicts,
    page_url,
    run_id,
    fingerprint,
):
    observed_at = datetime.now(timezone.utc).isoformat()
    return {
        "fingerprint": fingerprint,
        "discovery_run_id": run_id,
        "source_id": source.source_id,
        "source_name": source.name,
        "source_classification": source.source_classification,
        "trust_basis": source.trust_basis,
        "source_url": page_url,
        "content_hash": page.content_hash,
        "page_count": page.page_count,
        "last_checked_at": observed_at,
        "last_successful_check_at": observed_at,
        "extracted_values": jsonable_encoder(values),
        "evidence_excerpts": jsonable_encoder(evidence),
        "candidate_conflicts": jsonable_encoder(candidate_conflicts),
        "_rag_page_snapshot": {
            "content_type": page.content_type,
            "text": _sanitize_url_text(page.text),
        },
    }


def _field_source(source, page, page_url):
    return {
        "source_id": source.source_id,
        "source_name": source.name,
        "source_classification": source.source_classification,
        "source_url": page_url,
    }


def _add_conflict(conflicts, field, first_value, first_source, second_value, second_source):
    pair = [
        {"value": first_value, **first_source},
        {"value": second_value, **second_source},
    ]
    first_priority = SOURCE_PRIORITY.get(first_source.get("source_classification"), 0)
    second_priority = SOURCE_PRIORITY.get(second_source.get("source_classification"), 0)
    preferred_source = None
    preferred_value = None
    if first_priority != second_priority:
        preferred_source, preferred_value = (
            (first_source, first_value)
            if first_priority > second_priority
            else (second_source, second_value)
        )
    conflict = {
        "field": field,
        "values": pair,
        "preferred_source": preferred_source,
        "preferred_value": preferred_value,
    }
    if conflict not in conflicts:
        conflicts.append(conflict)


def has_open_review_for_identity(db, name, country):
    normalized_name = _identity(name)
    normalized_country = _identity(country)
    if not normalized_name or not normalized_country:
        return False
    items = db.query(ScholarshipDiscoveryReviewItem).filter(
        ScholarshipDiscoveryReviewItem.review_status.in_(("pending", "reviewed")),
    ).all()
    return any(
        _identity(item.candidate_name) == normalized_name
        and _identity(item.host_country) == normalized_country
        for item in items
    )


def persist_review_candidate(
    db,
    run_id,
    source,
    page,
    candidate,
    reason,
    conflicts=(),
    lock_check=None,
    on_committed=None,
):
    values = _sanitize_url_text(jsonable_encoder(candidate.values))
    evidence = _sanitize_url_text(jsonable_encoder(candidate.evidence))
    candidate_conflicts = _sanitize_url_text(
        jsonable_encoder(getattr(candidate, "conflicting_values", ()))
    )
    page_url = _safe_page_url(source, page)
    fingerprint = _fingerprint(source, page, values, evidence, page_url)
    name = values.get("name") if isinstance(values.get("name"), str) else None
    country = values.get("country") if isinstance(values.get("country"), str) else None

    if name and country:
        _lock_identity(db, name, country)
    elif db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": f"discovery-review:{fingerprint}"},
        )

    item = None
    if name and country:
        for existing in db.query(ScholarshipDiscoveryReviewItem).filter(
            ScholarshipDiscoveryReviewItem.review_status.in_(("pending", "reviewed")),
        ).with_for_update().all():
            if (
                _identity(existing.candidate_name) == _identity(name)
                and _identity(existing.host_country) == _identity(country)
            ):
                item = existing
                break
    else:
        item = db.query(ScholarshipDiscoveryReviewItem).filter(
            ScholarshipDiscoveryReviewItem.candidate_fingerprint == fingerprint,
        ).with_for_update().first()

    source_record = _source_entry(
        source,
        page,
        values,
        evidence,
        candidate_conflicts,
        page_url,
        run_id,
        fingerprint,
    )
    if item is None:
        missing = sorted({
            *getattr(candidate, "missing_required_fields", ()),
            *(field for field in REQUIRED_DISCOVERY_FIELDS if not values.get(field)),
        })
        item = ScholarshipDiscoveryReviewItem(
            candidate_fingerprint=fingerprint,
            candidate_name=name,
            host_country=country,
            source_id=source.source_id,
            source_name=source.name,
            source_classification=source.source_classification,
            source_trust_basis=source.trust_basis,
            source_url=page_url,
            page_count=page.page_count,
            extracted_values=values,
            field_sources={
                field: _field_source(source, page, page_url)
                for field, value in values.items()
                if value not in (None, "")
            },
            evidence_excerpts=[source_record],
            missing_required_fields=missing,
            conflicting_values=list(candidate_conflicts),
            review_reason="; ".join(dict.fromkeys([reason, *getattr(candidate, "review_reasons", ())])),
            discovery_run_id=run_id,
        )
        db.add(item)
        db.flush()
    else:
        source_entries = list(item.evidence_excerpts or [])
        if any(entry.get("fingerprint") == fingerprint for entry in source_entries):
            return item, False

        merged_values = dict(item.extracted_values or {})
        field_sources = dict(item.field_sources or {})
        incoming_source = _field_source(source, page, page_url)
        conflicts_found = list(item.conflicting_values or [])
        for field, incoming_value in values.items():
            if field in NON_COMPARABLE_FIELDS or incoming_value in (None, ""):
                continue
            current_value = merged_values.get(field)
            if current_value in (None, ""):
                merged_values[field] = incoming_value
                field_sources[field] = incoming_source
                continue
            if current_value == incoming_value:
                continue
            current_source = field_sources.get(field, {
                "source_id": item.source_id,
                "source_name": item.source_name,
                "source_classification": item.source_classification,
                "source_url": item.source_url,
            })
            _add_conflict(
                conflicts_found,
                field,
                current_value,
                current_source,
                incoming_value,
                incoming_source,
            )
            if (
                SOURCE_PRIORITY.get(source.source_classification, 0)
                > SOURCE_PRIORITY.get(current_source.get("source_classification"), 0)
            ):
                merged_values[field] = incoming_value
                field_sources[field] = incoming_source

        for conflict in conflicts:
            conflicts_found.append(jsonable_encoder(conflict))
        for conflict in candidate_conflicts:
            conflicts_found.append({
                **jsonable_encoder(conflict),
                "source_classification": source.source_classification,
                "source_url": page_url,
            })
        item.extracted_values = merged_values
        item.field_sources = field_sources
        item.evidence_excerpts = source_entries + [source_record]
        item.conflicting_values = conflicts_found
        item.candidate_name = merged_values.get("name") or item.candidate_name
        item.host_country = merged_values.get("country") or item.host_country
        item.missing_required_fields = sorted(
            field for field in REQUIRED_DISCOVERY_FIELDS if not merged_values.get(field)
        )
        reasons = [reason, *getattr(candidate, "review_reasons", ())]
        item.review_reason = "; ".join(dict.fromkeys(filter(None, [item.review_reason, *reasons])))
        if SOURCE_PRIORITY.get(source.source_classification, 0) > SOURCE_PRIORITY.get(item.source_classification, 0):
            item.source_id = source.source_id
            item.source_name = source.name
            item.source_classification = source.source_classification
            item.source_trust_basis = source.trust_basis
            item.source_url = page_url
            item.page_count = page.page_count
        if item.review_status == "reviewed":
            item.review_status = "pending"
            item.reviewed_by_id = None
            item.reviewed_at = None
            item.review_note = None
        item.updated_at = datetime.now(timezone.utc)

    for conflict in conflicts:
        encoded_conflict = jsonable_encoder(conflict)
        if encoded_conflict not in item.conflicting_values:
            item.conflicting_values = [*(item.conflicting_values or []), encoded_conflict]

    if lock_check is not None:
        lock_check()
    db.commit()
    if on_committed is not None:
        on_committed()
    db.refresh(item)
    return item, True


def apply_review_action(
    db,
    item,
    *,
    decision,
    admin,
    values=None,
    duplicate_of_scholarship_id=None,
    link_to_scholarship_id=None,
    note=None,
):
    if decision == "reviewed":
        if item.review_status != "pending":
            raise HTTPException(status_code=409, detail="Only pending discoveries can be marked reviewed")
        item.review_status = "reviewed"
        item.reviewed_by_id = admin.id
        item.reviewed_at = datetime.now(timezone.utc)
        item.review_note = note
        item.updated_at = item.reviewed_at
        db.commit()
        db.refresh(item)
        return item
    if decision not in {"accepted", "rejected", "duplicate", "link_and_publish"}:
        raise HTTPException(status_code=422, detail="Unsupported discovery review decision")
    if item.review_status != "reviewed":
        if decision in {"accepted", "link_and_publish"} and item.review_status == "accepted":
            prior_version = (
                db.query(ScholarshipDiscoveryPublicationVersion)
                .filter(ScholarshipDiscoveryPublicationVersion.review_item_id == item.id)
                .first()
            )
            retry_values = dict(item.extracted_values or {})
            retry_values.update(values or {})
            try:
                validated_retry = ScholarshipCreate.model_validate(retry_values)
            except ValidationError:
                validated_retry = None
            same_target = (
                prior_version is not None
                and (
                    decision == "accepted"
                    and item.accepted_scholarship_id == prior_version.publication.canonical_scholarship_id
                    or decision == "link_and_publish"
                    and link_to_scholarship_id == prior_version.publication.canonical_scholarship_id
                )
            )
            if (
                prior_version is not None
                and prior_version.approval_decision == decision
                and same_target
                and validated_retry is not None
                and prior_version.approved_values
                == jsonable_encoder(validated_retry.model_dump(exclude_unset=True, exclude={"verification_status"}))
            ):
                return item
        raise HTTPException(status_code=409, detail="Mark the discovery reviewed before resolving it")

    now = datetime.now(timezone.utc)
    if decision in {"accepted", "link_and_publish"}:
        if decision == "accepted" and link_to_scholarship_id is not None:
            raise HTTPException(status_code=422, detail="A link target is only valid for link-and-publish")
        if decision == "link_and_publish" and not link_to_scholarship_id:
            raise HTTPException(status_code=422, detail="Choose the existing scholarship to link and publish")
        if decision == "link_and_publish" and duplicate_of_scholarship_id is not None:
            raise HTTPException(status_code=422, detail="Use the link target for link-and-publish")

        candidate_values = dict(item.extracted_values or {})
        candidate_values.update(values or {})
        protected = set(candidate_values) & GUARDED_FIELDS
        if "verification_status" in candidate_values:
            protected.add("verification_status")
        if protected:
            raise HTTPException(status_code=422, detail="Verification fields cannot be set while accepting a discovery")
        unsupported = set(candidate_values) - (set(ScholarshipCreate.model_fields) - {"verification_status"})
        if unsupported:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported scholarship fields: {', '.join(sorted(unsupported))}",
            )
        try:
            validated = ScholarshipCreate.model_validate(candidate_values)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Edit the extracted fields to satisfy the scholarship schema") from exc

        approved_values = validated.model_dump(exclude_unset=True, exclude={"verification_status"})
        if decision == "accepted":
            scholarship = create_discovered_record(
                db,
                approved_values,
                "Accepted from Admin discovery review; record remains unverified.",
                {
                    "review_item_id": item.id,
                    "source_evidence": item.evidence_excerpts,
                    "conflicting_values": item.conflicting_values,
                },
                commit=False,
            )
            audit_action = "discovery_review_accepted"
        else:
            exact_match = (
                db.query(Scholarship)
                .filter(
                    Scholarship.id == link_to_scholarship_id,
                    Scholarship.archived_at.is_(None),
                )
                .with_for_update()
                .first()
            )
            if exact_match is None:
                raise HTTPException(status_code=404, detail="Scholarship to link was not found")
            possible_matches = find_possible_duplicate_records(
                db,
                approved_values.get("name"),
                approved_values.get("country"),
            )
            if (
                exact_match.id not in {match.id for match in possible_matches}
                and not (
                    _identity(exact_match.name) == _identity(approved_values.get("name"))
                    and _identity(exact_match.country) == _identity(approved_values.get("country"))
                )
            ):
                raise HTTPException(
                    status_code=422,
                    detail="The selected scholarship does not match the discovery identity",
                )
            scholarship = exact_match
            audit_action = "discovery_review_linked"

        publication, _ = publish_review_item(
            db,
            item,
            scholarship,
            admin,
            decision=decision,
            approved_values=approved_values,
            note=note,
        )
        record_audit(
            db,
            scholarship.id,
            audit_action,
            admin,
            changes={
                "review_item_id": [None, item.id],
                "publication_id": [None, publication.id],
            },
            note=note,
        )
        from app.services.scholarship_discovery import prepare_review_evidence

        prepare_review_evidence(db, scholarship, item, approved_values)
        item.review_status = "accepted"
        item.accepted_scholarship_id = scholarship.id
        item.duplicate_of_scholarship_id = None
    elif decision == "rejected":
        item.review_status = "rejected"
        item.accepted_scholarship_id = None
        item.duplicate_of_scholarship_id = None
    elif decision == "duplicate":
        if not duplicate_of_scholarship_id:
            raise HTTPException(status_code=422, detail="Choose the existing scholarship for this duplicate")
        duplicate = db.query(Scholarship).filter(
            Scholarship.id == duplicate_of_scholarship_id,
            Scholarship.archived_at.is_(None),
        ).first()
        if duplicate is None:
            raise HTTPException(status_code=404, detail="Duplicate scholarship not found")
        item.review_status = "duplicate"
        item.duplicate_of_scholarship_id = duplicate.id
        item.accepted_scholarship_id = None

    item.reviewed_by_id = admin.id
    item.reviewed_at = now
    item.review_note = note
    item.updated_at = now
    db.commit()
    db.refresh(item)
    return item
