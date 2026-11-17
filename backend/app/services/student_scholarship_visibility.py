"""Student-visible scholarship records from the canonical catalog and Discovery Cache."""
from dataclasses import dataclass
from datetime import date, timezone
import logging
import re
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app.models.opportunity import Scholarship, ScholarshipAuditLog
from app.models.scholarship_discovery_publication import (
    SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES,
    ScholarshipDiscoveryPublication,
)
from app.schemas.opportunity import StudentScholarshipResponse
from app.services.source_verification import is_currently_verified

logger = logging.getLogger(__name__)

DISCOVERY_CREATED_ACTION = "discovery_created"
DISCOVERY_SYSTEM_ACTOR = "system:scholarship-discovery"
PUBLICATION_TABLES = SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES


@dataclass(frozen=True)
class StudentScholarship:
    scholarship: Scholarship
    publication: Optional[ScholarshipDiscoveryPublication]
    independently_verified: bool
    discovery_created: bool

    @property
    def publication_active(self) -> bool:
        return self.publication is not None and self.publication.status == "published"

    def source_provenance(self) -> dict:
        sources = ["database"]
        if self.publication_active:
            sources.append("live_discovery")
        source_checks = (
            self.publication.sources
            if self.publication_active and self.publication is not None
            else []
        )
        last_checked = _latest_timestamp(source_checks, "last_checked_at")
        last_success = _latest_timestamp(source_checks, "last_successful_check_at")
        return {
            "sources": sources,
            "publication_status": self.publication.status if self.publication is not None else None,
            "publication_last_checked_at": last_checked,
            "publication_last_successful_check_at": last_success,
            "discovery_sources": [
                {
                    "source_id": source.source_id,
                    "source_name": source.source_name,
                    "source_classification": source.source_classification,
                    "source_url": source.source_url,
                    "last_checked_at": _as_utc(source.last_checked_at),
                    "last_successful_check_at": _as_utc(source.last_successful_check_at),
                }
                for source in source_checks
            ],
        }


def scholarship_response_payload(record: StudentScholarship) -> dict:
    payload = StudentScholarshipResponse.model_validate(record.scholarship).model_dump()
    payload["source_provenance"] = record.source_provenance()
    return payload


def _latest_timestamp(sources, field):
    timestamps = [
        _as_utc(getattr(source, field))
        for source in sources
        if getattr(source, field) is not None
    ]
    return max(timestamps) if timestamps else None


def _as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_missing_publication_table(error: SQLAlchemyError) -> bool:
    original = getattr(error, "orig", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    message = str(original or error).casefold()
    if sqlstate == "42P01":
        relation = getattr(getattr(original, "diag", None), "table_name", None)
        if relation:
            return relation.casefold() in PUBLICATION_TABLES
        match = re.search(r'relation\s+"?([a-z0-9_.]+)"?\s+does not exist', message)
        return bool(
            match
            and match.group(1).rsplit(".", 1)[-1].strip('"') in PUBLICATION_TABLES
        )
    if "no such table" in message:
        match = re.search(r"no such table:\s*[\"'`]?([a-z0-9_.]+)", message)
        return bool(
            match
            and match.group(1).rsplit(".", 1)[-1].strip('"') in PUBLICATION_TABLES
        )
    return False


def _canonical_rows(db, scholarship_id=None):
    query = db.query(Scholarship).filter(Scholarship.archived_at.is_(None))
    if scholarship_id is not None:
        query = query.filter(Scholarship.id == scholarship_id)
    return query.order_by(Scholarship.id).all()


def _discovery_created_ids(db, scholarship_ids):
    if not scholarship_ids:
        return set()
    existing_ids = set(scholarship_ids)
    return {
        row[0]
        for row in db.query(ScholarshipAuditLog.scholarship_id)
        .filter(
            ScholarshipAuditLog.action == DISCOVERY_CREATED_ACTION,
            ScholarshipAuditLog.actor_email == DISCOVERY_SYSTEM_ACTOR,
        )
        .distinct()
        .all()
        if row[0] in existing_ids
    }


def _publication_rows(db, scholarship_ids):
    if not scholarship_ids:
        return {}
    existing_ids = set(scholarship_ids)
    rows = (
        db.query(ScholarshipDiscoveryPublication)
        .options(joinedload(ScholarshipDiscoveryPublication.sources))
        .all()
    )
    return {
        row.canonical_scholarship_id: row
        for row in rows
        if row.canonical_scholarship_id in existing_ids
    }


def _load_publication_rows(db, scholarship_ids):
    try:
        return _publication_rows(db, scholarship_ids)
    except SQLAlchemyError as error:
        db.rollback()
        if not _is_missing_publication_table(error):
            raise
        logger.warning(
            "Discovery Cache tables are unavailable; using canonical scholarship visibility only",
        )
        return None


def get_student_scholarships(db, *, include_unverified=False, today=None):
    today = today or date.today()
    rows = _canonical_rows(db)
    scholarship_ids = [row.id for row in rows]
    if not scholarship_ids:
        return []

    discovery_created_ids = _discovery_created_ids(db, scholarship_ids)
    publications = _load_publication_rows(db, scholarship_ids)
    if publications is None:
        rows = _canonical_rows(db)
        scholarship_ids = [row.id for row in rows]
        discovery_created_ids = _discovery_created_ids(db, scholarship_ids)
        publications = {}

    visible = []
    for scholarship in rows:
        verified = is_currently_verified(scholarship, today)
        discovery_created = scholarship.id in discovery_created_ids
        publication = publications.get(scholarship.id)
        publication_active = publication is not None and publication.status == "published"
        discovery_derived = discovery_created or publication is not None
        if not (
            verified
            or publication_active
            or include_unverified and not discovery_derived
        ):
            continue
        visible.append(StudentScholarship(
            scholarship=scholarship,
            publication=publication,
            independently_verified=verified,
            discovery_created=discovery_created,
        ))
    return visible


def get_student_scholarship(
    db,
    scholarship_id,
    *,
    include_unverified=False,
    today=None,
):
    records = get_student_scholarships(
        db,
        include_unverified=include_unverified,
        today=today,
    )
    for record in deduplicate_student_scholarships(records):
        if record.scholarship.id == scholarship_id:
            return record
    return None


def deduplicate_student_scholarships(records):
    present_ids = {record.scholarship.id for record in records}
    return [
        record for record in records
        if record.scholarship.duplicate_of_id not in present_ids
    ]
