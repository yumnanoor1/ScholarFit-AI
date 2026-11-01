from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

MatchOutcome = Literal["confirmed", "potential", "not_a_match", "needs_verification"]
RelationshipType = Literal["named_program", "all_programs_at_university", "programs_meeting_stated_criteria", "unconfirmed"]


class ScholarshipProgramLinkWrite(BaseModel):
    """What an admin states about one scholarship and program. IDs come from the URL."""
    model_config = {"extra": "forbid"}

    outcome: MatchOutcome
    relationship_type: RelationshipType
    evidence: Optional[str] = Field(None, max_length=4000)
    source_url: Optional[str] = Field(None, max_length=2000)
    verification_status: Literal["verified", "unverified"] = "unverified"
    last_verified: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=4000)

    @model_validator(mode="after")
    def confirmed_needs_evidence(self):
        if self.source_url and not self.source_url.startswith("https://"):
            raise ValueError("source_url must be an https:// address")
        if self.last_verified and self.last_verified > date.today():
            raise ValueError("last_verified can't be in the future")
        if self.outcome == "confirmed" and not (
                self.verification_status == "verified" and (self.evidence or "").strip()
                and self.source_url and self.last_verified):
            raise ValueError("A confirmed match needs evidence, source_url, last_verified and verification_status 'verified'")
        return self


class MatchCriterion(BaseModel):
    criterion: Literal["country", "degree", "discipline", "university", "other"]
    status: Literal["compatible", "incompatible", "unknown"]
    detail: str


class MatchResult(BaseModel):
    scholarship_id: int
    scholarship_name: str
    scholarship_country: Optional[str]
    funding_type: Optional[str]
    scholarship_verification_status: Optional[str]
    program_id: int
    program_name: str
    university_id: Optional[int]
    university_name: Optional[str]
    country: Optional[str]
    degree_level: Optional[str]
    field_of_study: Optional[str]
    outcome: MatchOutcome
    label: str
    explanation: str
    blocking_criterion: Optional[str]
    criteria: List[MatchCriterion]
    # The reviewed relationship, when there is one
    has_relationship: bool
    relationship_type: Optional[RelationshipType]
    evidence: Optional[str]
    source_url: Optional[str]
    relationship_verification_status: Optional[str]
    last_verified: Optional[date]
    notes: Optional[str]


class ScholarshipCoverageCounts(BaseModel):
    scholarship_id: int
    confirmed: int
    potential: int
    needs_verification: int
