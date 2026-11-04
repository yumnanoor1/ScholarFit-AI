from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from app.schemas.eligibility import DeadlineStatus

Category = Literal["strong", "good", "possible", "needs_verification"]


class ScoreDimension(BaseModel):
    dimension: str
    label: str
    weight: float
    value: float            # 0 to 1
    points: float           # this dimension's share of the score


class Exclusion(BaseModel):
    rule: Literal["not_eligible", "closed"]
    reason: str


class EligibilitySummary(BaseModel):
    status: Literal["eligible", "not_eligible", "missing_information", "not_evaluated"]
    outcome: Literal["eligible", "not_eligible", "verify_manually"]
    summary: str


class FundingSummary(BaseModel):
    tier: Literal["fully_funded", "substantially_funded", "partially_funded", "tuition_only", "incomplete"]
    label: str
    summary: str
    amount_confirmed: bool
    benefits: List[str]
    not_covered: List[str]
    duration_months: Optional[int]


class ScholarshipRecommendation(BaseModel):
    scholarship_id: int
    scholarship_name: str
    provider: Optional[str]
    country: Optional[str]
    rank: Optional[int]
    recommended: bool
    score: Optional[int]    # 0 to 100; None when a hard exclusion applies
    category: Optional[Category]
    category_label: Optional[str]
    category_reason: Optional[str]
    exclusions: List[Exclusion]
    eligibility: EligibilitySummary
    funding: FundingSummary
    deadline: DeadlineStatus
    positive: List[str]
    warnings: List[str]
    negative: List[str]
    breakdown: List[ScoreDimension]
    verification_status: Optional[str]
    official_url: Optional[str]


class ProfileGap(BaseModel):
    field: str
    label: str
    scholarships_affected: int


class RecommendationSummary(BaseModel):
    recommended: int
    excluded: int
    strong: int
    good: int
    possible: int
    needs_verification: int
    eligible: int
    verify_manually: int


class RecommendationList(BaseModel):
    profile_complete: bool
    profile_gaps: List[ProfileGap]
    summary: RecommendationSummary
    weights: Dict[str, float]
    recommendations: List[ScholarshipRecommendation]
    excluded: List[ScholarshipRecommendation]
    notes: List[str]
