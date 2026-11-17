from typing import List, Literal, Optional
from pydantic import BaseModel, field_serializer

from app.schemas.opportunity import ScholarshipSourceProvenance
from app.services.source_url_safety import safe_source_url


class RequirementResult(BaseModel):
    requirement: str          # cgpa | english | degree_level
    status: Literal["satisfied", "not-satisfied", "missing-information"]
    message: str


class EligibilityResult(BaseModel):
    program_id: int
    program_name: str
    university_name: str
    # eligible: every structured requirement checked and met
    # not-eligible: at least one checked requirement is not met
    # missing-information: a requirement could not be checked (profile data missing)
    # not-evaluated: the program has no structured CGPA/English minimum to check
    status: Literal["eligible", "not-eligible", "missing-information", "not-evaluated"]
    eligible: bool            # same as status == "eligible"
    matched_requirements: List[RequirementResult]
    missing_requirements: List[RequirementResult]  # not met or missing information
    notes: List[str]


# ---------- Scholarship eligibility ----------

class ScholarshipRequirement(BaseModel):
    requirement: str          # nationality | degree_level | bachelors_conditions | field | academic | english | age | work_experience | gender | residency | restrictions | source_evidence
    label: str
    status: Literal["satisfied", "not_satisfied", "missing_information", "not_evaluated"]
    reason: str
    source_text: Optional[str] = None   # the scholarship record's original wording
    scope: Literal["scholarship", "admission"]
    conflict: bool = False    # the structured data and the original wording disagree


class DeadlineStatus(BaseModel):
    status: Literal["open", "closed", "upcoming", "rolling", "no_separate_deadline", "unknown"]
    date: Optional[str] = None
    days_left: Optional[int] = None   # to the closing date, or to the opening date when upcoming
    text: Optional[str] = None
    opens_on: Optional[str] = None
    message: Optional[str] = None


class ScholarshipCoverage(BaseModel):
    tuition: Optional[str] = None
    living_stipend: Optional[str] = None
    other_benefits: Optional[str] = None


class ScholarshipEligibilityResult(BaseModel):
    scholarship_id: int
    scholarship_name: str
    provider: Optional[str]
    country: Optional[str]
    status: Literal["eligible", "not_eligible", "missing_information", "not_evaluated"]
    outcome: Literal["eligible", "not_eligible", "verify_manually"]
    eligible: bool
    summary: str
    satisfied: List[ScholarshipRequirement]
    not_satisfied: List[ScholarshipRequirement]
    missing_information: List[ScholarshipRequirement]
    needs_verification: List[ScholarshipRequirement]
    deadline: DeadlineStatus
    funding_type: Optional[str]
    coverage: ScholarshipCoverage
    verification_status: Optional[str]
    last_verified: Optional[str]
    official_url: Optional[str]
    source_name: Optional[str]
    source_provenance: Optional[ScholarshipSourceProvenance] = None
    match_score: Optional[float] = None   # always None here; scores come from GET /recommendations/scholarships
    notes: List[str]

    @field_serializer("official_url")
    def sanitize_official_url(self, value):
        return safe_source_url(value)


# ---------- Profile improvement guidance ----------

class RelatedOpportunity(BaseModel):
    kind: Literal["scholarship"]
    id: int
    name: str
    organization: Optional[str] = None
    requirement_text: Optional[str] = None   # the record's own wording
    result: str                              # what the comparison found
    source_url: Optional[str] = None
    source_provenance: Optional[ScholarshipSourceProvenance] = None

    @field_serializer("source_url")
    def sanitize_source_url(self, value):
        return safe_source_url(value)


class ImprovementRecommendation(BaseModel):
    id: str
    category: str
    priority: Literal["High", "Medium", "Low"]
    result_type: Literal["unmet", "missing_information", "manual_verification", "optional"]
    actionability: Literal["achievable", "manual_verification", "not_changeable"]
    title: str
    gap: str
    why_it_matters: str
    suggested_action: str
    requirement: Optional[str] = None
    profile_information: str
    comparison: str
    expected_benefit: Optional[str] = None
    related: List[RelatedOpportunity]
    action_route: str


class OpportunityRequirementResult(BaseModel):
    requirement: str
    reason: Optional[str] = None


class OpportunityEvaluation(BaseModel):
    kind: Literal["scholarship"]
    id: int
    name: str
    organization: Optional[str] = None
    status: Literal["eligible", "not_eligible", "missing_information", "not_evaluated"]
    satisfied: List[OpportunityRequirementResult]
    unmet: List[OpportunityRequirementResult]
    missing_information: List[OpportunityRequirementResult]
    manual_verification: List[OpportunityRequirementResult]
    source_url: Optional[str] = None
    last_verified: Optional[str] = None
    deadline: Optional[DeadlineStatus] = None
    source_provenance: Optional[ScholarshipSourceProvenance] = None

    @field_serializer("source_url")
    def sanitize_source_url(self, value):
        return safe_source_url(value)


class ImprovementSummary(BaseModel):
    opportunities_evaluated: int
    scholarships_evaluated: int
    eligible: int
    not_eligible: int
    missing_information: int
    not_evaluated: int
    high_priority: int


class ImprovementCategory(BaseModel):
    name: str
    count: int


class ImprovementScope(BaseModel):
    type: Literal["selected", "preferred_countries", "all"]
    description: str


class ProfileImprovementResult(BaseModel):
    scope: ImprovementScope
    summary: ImprovementSummary
    categories: List[ImprovementCategory]
    recommendations: List[ImprovementRecommendation]
    opportunities: List[OpportunityEvaluation]
    notes: List[str]
