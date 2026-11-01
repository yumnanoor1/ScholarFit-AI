from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.matching import MatchResult
from app.schemas.opportunity import ScholarshipResponse, is_web_url


class QualityIssue(BaseModel):
    code: str
    label: str
    severity: Literal["high", "medium", "low"]
    detail: str


class AdminSummary(BaseModel):
    total: int
    verified: int
    unverified: int
    archived: int
    conflicting: int
    missing_official_source: int
    incomplete_structured: int
    needs_reverification: int
    broken_sources: int
    sources_checked: int
    duplicates: int


class AdminRow(BaseModel):
    id: int
    name: str
    provider: Optional[str]
    country: Optional[str]
    verification_status: Optional[str]
    verification_basis: Optional[str]
    last_verified_date: Optional[date]
    archived: bool
    duplicate_of_id: Optional[int]
    issues: List[QualityIssue]


class AdminRowPage(BaseModel):
    total: int
    items: List[AdminRow]


class AuditEntry(BaseModel):
    id: int
    action: str
    changes: Optional[dict]
    note: Optional[str]
    actor_email: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class ReferenceCounts(BaseModel):
    saved_by_students: int
    program_links: int
    duplicates_pointing_here: int


class AdminScholarship(ScholarshipResponse):
    data_flags: Optional[List[str]] = None
    source_checks: Optional[List[dict]] = None
    archived_at: Optional[datetime] = None
    archive_reason: Optional[str] = None


class AdminDetail(BaseModel):
    scholarship: AdminScholarship
    issues: List[QualityIssue]
    references: ReferenceCounts
    audit: List[AuditEntry]
    relationships: List[MatchResult]


class VerificationWrite(BaseModel):
    model_config = {"extra": "forbid"}

    status: Literal["verified", "unverified"]
    basis: Literal["official_source", "mixed_sources", "secondary_only", "not_verified"]
    source_url: Optional[str] = Field(None, max_length=2000)
    verified_on: Optional[date] = None
    notes: str = Field(..., min_length=10, max_length=4000)
    evidence_reviewed: bool = False
    acknowledge_conflicts: bool = False

    @field_validator("source_url")
    @classmethod
    def _url(cls, value):
        if value is not None and not is_web_url(value):
            raise ValueError("must be a single http or https URL")
        return value


class FlagWrite(BaseModel):
    model_config = {"extra": "forbid"}

    flag: Literal["conflicting_information", "outdated_source", "broken_source", "needs_reverification"]
    active: bool
    note: Optional[str] = Field(None, max_length=1000)


class ArchiveWrite(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(..., min_length=5, max_length=1000)


class DuplicateWrite(BaseModel):
    model_config = {"extra": "forbid"}

    duplicate_of_id: Optional[int] = Field(None, gt=0)      # None clears the flag
    note: str = Field(..., min_length=5, max_length=1000)


class DuplicatePair(BaseModel):
    first_id: int
    second_id: int
    first_name: str
    second_name: str
    kind: Literal["flagged", "suspected"]


class FieldDifference(BaseModel):
    field: str
    first: object = None
    second: object = None


class DuplicateComparison(BaseModel):
    first: AdminScholarship
    second: AdminScholarship
    differences: List[FieldDifference]
    first_references: ReferenceCounts
    second_references: ReferenceCounts
