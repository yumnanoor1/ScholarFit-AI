from typing import List, Literal, Optional

from pydantic import BaseModel

from app.schemas.eligibility import DeadlineStatus
from app.schemas.opportunity import StudentScholarshipResponse
from app.schemas.recommendation import EligibilitySummary, Exclusion, ProfileGap

SortOption = Literal["relevance", "recommendation", "name", "deadline", "funding", "country", "verified"]
FundingFilter = Literal["fully_funded", "substantially_funded", "partially_funded", "tuition_only", "incomplete"]
BenefitFilter = Literal["stipend", "accommodation", "travel", "health_insurance"]
DeadlineFilter = Literal["open", "upcoming", "rolling", "no_separate_deadline", "closed", "unknown"]
VerificationFilter = Literal["verified", "unverified", "conflicting"]
EligibilityFilter = Literal["eligible", "verify_manually", "not_eligible"]
ScopeFilter = Literal["all", "all_except", "listed", "published_list", "not_specified"]
ConditionFilter = Literal["numeric", "degree_class", "class_rank", "merit_based", "set_by_institution", "not_specified"]


class ScholarshipSearchItem(BaseModel):
    scholarship: StudentScholarshipResponse
    matched_fields: List[str]
    nationality_status: Optional[str]       # the chosen nationality's result, when that filter is used
    funding_tier: FundingFilter
    funding_label: str
    deadline: DeadlineStatus
    has_conflict: bool
    eligibility: Optional[EligibilitySummary]   # None unless signed in
    score: Optional[int]
    category_label: Optional[str]
    exclusions: List[Exclusion]


class ScholarshipSearchResult(BaseModel):
    total: int
    skip: int
    limit: int
    sort: SortOption
    signed_in: bool
    profile_incomplete: bool
    profile_gaps: List[ProfileGap]
    items: List[ScholarshipSearchItem]


class FilterOption(BaseModel):
    value: str
    label: str
    count: int


class ScholarshipFilterOptions(BaseModel):
    host_countries: List[FilterOption]
    degree_levels: List[FilterOption]
    disciplines: List[FilterOption]
    nationality_scopes: List[FilterOption]
    academic_conditions: List[FilterOption]
    funding: List[FilterOption]
    benefits: List[FilterOption]
    deadlines: List[FilterOption]
    verification: List[FilterOption]
    nationalities: List[str]
