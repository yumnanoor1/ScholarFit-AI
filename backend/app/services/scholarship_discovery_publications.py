from datetime import datetime, timezone
import logging

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func

from app.models.opportunity import Scholarship
from app.models.scholarship_discovery import ScholarshipDiscoveryReviewItem
from app.models.scholarship_discovery_publication import (
    ScholarshipDiscoveryPublication,
    ScholarshipDiscoveryPublicationEvent,
    ScholarshipDiscoveryPublicationSource,
    ScholarshipDiscoveryPublicationVersion,
)
from app.services.scholarship_quality import record_audit

logger = logging.getLogger(__name__)

PUBLICATION_STATUSES = {"published", "expired", "withdrawn", "revoked", "superseded"}
LIFECYCLE_DECISIONS = {
    "revoke": "revoked",
    "expire": "expired",
    "withdraw": "withdrawn",
    "supersede": "superseded",
}


def _now():
    return datetime.now(timezone.utc)


def _datetime(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _observed_at(value):
    if value is None:
        return _now()
    parsed = _datetime(value)
    if parsed is None:
        raise ValueError("checked_at must be a datetime or valid ISO timestamp")
    return parsed


def _source_provenance(entries):
    return [
        {key: value for key, value in entry.items() if key != "_rag_page_snapshot"}
        for entry in entries or []
        if isinstance(entry, dict)
    ]


def _publication_source(db, publication, entry):
    source_id = entry.get("source_id")
    source_url = entry.get("source_url")
    if not isinstance(source_id, str) or not source_id or not isinstance(source_url, str):
        logger.warning("Skipping publication source without a valid identity or URL")
        return None

    from app.services.scholarship_discovery import _normalize_url

    normalized_url = _normalize_url(source_url)
    source = (
        db.query(ScholarshipDiscoveryPublicationSource)
        .filter(
            ScholarshipDiscoveryPublicationSource.publication_id == publication.id,
            ScholarshipDiscoveryPublicationSource.source_id == source_id,
            ScholarshipDiscoveryPublicationSource.normalized_url == normalized_url,
        )
        .with_for_update()
        .first()
    )
    observed_at = _datetime(entry.get("last_checked_at")) or _datetime(entry.get("observed_at"))
    content_hash = entry.get("content_hash")
    if source is None:
        source = ScholarshipDiscoveryPublicationSource(
            publication_id=publication.id,
            source_id=source_id,
            source_name=entry.get("source_name") or source_id,
            source_classification=entry.get("source_classification") or "trusted_listing",
            source_trust_basis=entry.get("trust_basis"),
            source_url=source_url,
            normalized_url=normalized_url,
            last_checked_at=observed_at,
            last_successful_check_at=observed_at,
            observed_content_hash=content_hash,
            source_check_status="succeeded" if observed_at else "not_checked",
        )
        db.add(source)
        return source

    last_checked_at = _datetime(source.last_checked_at)
    if observed_at is not None and (
        last_checked_at is None or observed_at >= last_checked_at
    ):
        changed = bool(
            source.observed_content_hash
            and content_hash
            and source.observed_content_hash != content_hash
        )
        source.source_name = entry.get("source_name") or source.source_name
        source.source_classification = entry.get("source_classification") or source.source_classification
        source.source_trust_basis = entry.get("trust_basis")
        source.source_url = source_url
        source.last_checked_at = observed_at
        source.last_successful_check_at = observed_at
        source.observed_content_hash = content_hash
        source.source_check_status = "content_changed" if changed else "succeeded"
    return source


def publish_review_item(
    db,
    item: ScholarshipDiscoveryReviewItem,
    scholarship: Scholarship,
    admin,
    *,
    decision: str,
    approved_values: dict,
    note=None,
):
    if decision not in {"accepted", "link_and_publish"}:
        raise ValueError("Unsupported publication approval decision")
    locked_scholarship = (
        db.query(Scholarship)
        .filter(Scholarship.id == scholarship.id, Scholarship.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if locked_scholarship is None:
        raise HTTPException(status_code=404, detail="Scholarship not found")

    prior_version = (
        db.query(ScholarshipDiscoveryPublicationVersion)
        .filter(ScholarshipDiscoveryPublicationVersion.review_item_id == item.id)
        .with_for_update()
        .first()
    )
    if prior_version is not None:
        if (
            prior_version.approval_decision == decision
            and prior_version.publication.canonical_scholarship_id == scholarship.id
            and prior_version.approved_values == jsonable_encoder(approved_values)
        ):
            return prior_version.publication, prior_version
        raise HTTPException(status_code=409, detail="This discovery was already published with a different decision")

    publication = (
        db.query(ScholarshipDiscoveryPublication)
        .filter(ScholarshipDiscoveryPublication.canonical_scholarship_id == scholarship.id)
        .with_for_update()
        .first()
    )
    created = publication is None
    if created:
        publication = ScholarshipDiscoveryPublication(
            canonical_scholarship_id=scholarship.id,
            status="published",
            published_at=_now(),
        )
        db.add(publication)
        db.flush()
    elif publication.status == "superseded":
        raise HTTPException(
            status_code=409,
            detail="This publication is superseded; link the discovery to its current publication instead",
        )

    version_number = (
        db.query(func.max(ScholarshipDiscoveryPublicationVersion.version_number))
        .filter(ScholarshipDiscoveryPublicationVersion.publication_id == publication.id)
        .scalar()
        or 0
    ) + 1
    now = _now()
    entries = item.evidence_excerpts or []
    version = ScholarshipDiscoveryPublicationVersion(
        publication_id=publication.id,
        review_item_id=item.id,
        version_number=version_number,
        candidate_name_at_approval=item.candidate_name,
        host_country_at_approval=item.host_country,
        approved_values=jsonable_encoder(approved_values),
        source_evidence=_source_provenance(entries),
        approval_decision=decision,
        approved_by_id=admin.id,
        approved_by_email=admin.email,
        approved_at=now,
    )
    db.add(version)
    db.flush()

    previous_status = publication.status
    previous_version_id = publication.current_version_id
    publication.current_version_id = version.id
    publication.status = "published"
    publication.published_at = now
    publication.updated_at = now
    publication.revoked_at = None
    publication.revoked_by_id = None
    publication.revoked_by_email = None
    publication.revocation_reason = None
    publication.superseded_by_publication_id = None

    for entry in entries:
        if isinstance(entry, dict):
            _publication_source(db, publication, entry)

    event_type = "published" if created else "republished" if previous_status != "published" else "version_approved"
    db.add(ScholarshipDiscoveryPublicationEvent(
        publication_id=publication.id,
        publication_version_id=version.id,
        event_type=event_type,
        previous_status=previous_status if not created else None,
        new_status="published",
        actor_id=admin.id,
        actor_email=admin.email,
        reason=note,
        event_data={"review_item_id": item.id, "decision": decision},
    ))
    if previous_version_id is not None:
        db.add(ScholarshipDiscoveryPublicationEvent(
            publication_id=publication.id,
            publication_version_id=previous_version_id,
            event_type="version_superseded",
            previous_status="published",
            new_status="published",
            actor_id=admin.id,
            actor_email=admin.email,
            reason=note,
            event_data={"superseded_by_version_id": version.id},
        ))
    return publication, version


def publication_version_for_review_item(db, review_item_id):
    return (
        db.query(ScholarshipDiscoveryPublicationVersion)
        .filter(ScholarshipDiscoveryPublicationVersion.review_item_id == review_item_id)
        .first()
    )


def record_publication_source_success(db, source_id, source_url, content_hash, checked_at=None):
    from app.services.scholarship_discovery import _normalize_url

    normalized_url = _normalize_url(source_url)
    observed_at = _observed_at(checked_at)
    sources = (
        db.query(ScholarshipDiscoveryPublicationSource)
        .filter(
            ScholarshipDiscoveryPublicationSource.source_id == source_id,
            ScholarshipDiscoveryPublicationSource.normalized_url == normalized_url,
        )
        .with_for_update()
        .all()
    )
    for source in sources:
        last_checked_at = _datetime(source.last_checked_at)
        if last_checked_at is not None and observed_at < last_checked_at:
            continue
        changed = bool(
            source.observed_content_hash
            and content_hash
            and source.observed_content_hash != content_hash
        )
        source.last_checked_at = observed_at
        source.last_successful_check_at = observed_at
        source.observed_content_hash = content_hash
        source.source_check_status = "content_changed" if changed else "succeeded"
    return len(sources)


def record_publication_source_failure(db, source_id, checked_at=None):
    observed_at = _observed_at(checked_at)
    sources = (
        db.query(ScholarshipDiscoveryPublicationSource)
        .filter(ScholarshipDiscoveryPublicationSource.source_id == source_id)
        .with_for_update()
        .all()
    )
    for source in sources:
        source.last_checked_at = observed_at
        source.source_check_status = "failed"
    return len(sources)


def transition_publication(
    db,
    publication_id,
    admin,
    *,
    decision,
    reason,
    superseded_by_publication_id=None,
):
    if decision not in LIFECYCLE_DECISIONS:
        raise HTTPException(status_code=422, detail="Unsupported publication lifecycle decision")
    if (decision == "supersede") != (superseded_by_publication_id is not None):
        raise HTTPException(status_code=422, detail="Choose a successor publication only when superseding")

    publication = (
        db.query(ScholarshipDiscoveryPublication)
        .filter(ScholarshipDiscoveryPublication.id == publication_id)
        .with_for_update()
        .first()
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Discovery publication not found")
    if publication.status != "published":
        raise HTTPException(status_code=409, detail="Only published discoveries can change lifecycle status")

    successor = None
    if decision == "supersede":
        successor = (
            db.query(ScholarshipDiscoveryPublication)
            .filter(
                ScholarshipDiscoveryPublication.id == superseded_by_publication_id,
                ScholarshipDiscoveryPublication.status == "published",
            )
            .with_for_update()
            .first()
        )
        if successor is None or successor.id == publication.id:
            raise HTTPException(status_code=404, detail="Published successor not found")

    new_status = LIFECYCLE_DECISIONS[decision]
    previous_status = publication.status
    now = _now()
    publication.status = new_status
    publication.updated_at = now
    if decision == "revoke":
        publication.revoked_at = now
        publication.revoked_by_id = admin.id
        publication.revoked_by_email = admin.email
        publication.revocation_reason = reason
    if successor is not None:
        publication.superseded_by_publication_id = successor.id

    db.add(ScholarshipDiscoveryPublicationEvent(
        publication_id=publication.id,
        publication_version_id=publication.current_version_id,
        event_type=new_status,
        previous_status=previous_status,
        new_status=new_status,
        actor_id=admin.id,
        actor_email=admin.email,
        reason=reason,
        event_data={"successor_publication_id": successor.id} if successor else {},
    ))
    record_audit(
        db,
        publication.canonical_scholarship_id,
        f"discovery_publication_{new_status}",
        admin,
        changes={"publication_status": [previous_status, new_status]},
        note=reason,
    )
    db.commit()
    db.refresh(publication)
    return publication
