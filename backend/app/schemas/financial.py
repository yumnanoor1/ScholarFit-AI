from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

Period = Literal["monthly", "semester", "yearly", "total"]
FeasibilityStatus = Literal["feasible", "partially_feasible", "not_feasible", "insufficient_data"]


def _currency(value: str) -> str:
    value = (value or "").strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError("Currency must be a 3-letter code such as EUR or USD")
    return value


class MoneyInput(BaseModel):
    amount: float = Field(..., ge=0, le=1e12, allow_inf_nan=False)
    currency: str

    _check_currency = field_validator("currency")(_currency)


class ExpenseInput(MoneyInput):
    period: Period
    # student_input: entered by the student; planning_estimate: a default the student has not confirmed
    source: Literal["student_input", "planning_estimate"] = "student_input"


class ExpenseInputs(BaseModel):
    living_costs: Optional[ExpenseInput] = None
    university_fees: Optional[ExpenseInput] = None
    health_insurance: Optional[ExpenseInput] = None
    visa: Optional[ExpenseInput] = None
    travel: Optional[ExpenseInput] = None
    application_fees: Optional[ExpenseInput] = None
    other: Optional[ExpenseInput] = None


class FeasibilityRequest(BaseModel):
    program_id: int = Field(..., gt=0)
    scholarship_id: Optional[int] = Field(None, gt=0)
    # Falls back to the saved budget, then the profile's budget_usd
    budget: Optional[MoneyInput] = None
    # Currency for every amount in the response; defaults to the program's tuition currency
    currency: Optional[str] = None
    # Falls back to the expenses saved for this program when none are sent
    expenses: Optional[ExpenseInputs] = None

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, value):
        return _currency(value) if value is not None else None


class CompareRequest(BaseModel):
    scenarios: List[FeasibilityRequest] = Field(..., min_length=1, max_length=6)


class CostLine(BaseModel):
    category: str
    label: str
    amount: Optional[float]                 # for the whole study period, in the response currency
    original_amount: Optional[float]
    original_amount_max: Optional[float] = None
    original_currency: Optional[str]
    period: Optional[Period]
    source: Literal["program_record", "student_input", "planning_estimate", "not_provided", "included"]
    is_estimate: bool
    note: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    last_verified: Optional[str] = None


class FundingLine(BaseModel):
    category: str                           # tuition | living_costs | tuition_and_living | other
    label: str
    amount: Optional[float]                 # counted amount, response currency; None when not counted
    counted: bool
    reason: str
    source_text: Optional[str] = None
    potential: bool = False                 # an amount exists, but the scholarship isn't confirmed for this program


class ProgramSummary(BaseModel):
    id: int
    name: str
    university: Optional[str]
    country: Optional[str]
    duration_months: Optional[int]
    tuition_annual: Optional[float]
    tuition_currency: Optional[str]
    last_verified: Optional[str]
    source_url: Optional[str]


class ScholarshipSummary(BaseModel):
    id: int
    name: str
    funding_type: Optional[str]
    verification_status: Optional[str]
    last_verified: Optional[str]
    source_url: Optional[str]
    applicable: bool
    counted: bool
    match_outcome: Optional[str] = None     # scholarship-program relationship; None when there's no information
    match_label: Optional[str] = None
    match_explanation: Optional[str] = None


class BudgetSummary(BaseModel):
    amount: Optional[float]                 # response currency
    original_amount: Optional[float]
    original_currency: Optional[str]
    source: Literal["request", "saved", "profile", "not_provided"]


class ExchangeRateInfo(BaseModel):
    source: str
    date: str
    used: bool
    age_days: int
    stale: bool                             # older than EXCHANGE_RATES_MAX_AGE_DAYS


class ScholarshipCoverage(BaseModel):
    tuition: float
    living: float
    combined_package: float                 # one award covering tuition and living together
    other: float
    total: float


class FeasibilityResult(BaseModel):
    status: FeasibilityStatus
    currency: str
    program: ProgramSummary
    scholarship: Optional[ScholarshipSummary]
    duration_months: Optional[int]
    costs: List[CostLine]
    tuition_cost: Optional[float]
    living_cost: Optional[float]
    other_costs: float                      # only the other expenses that are known
    total_estimated_cost: Optional[float]
    funding: List[FundingLine]
    confirmed_funding: float
    potential_funding: float = 0.0          # never included in any total
    scholarship_coverage: ScholarshipCoverage
    remaining_cost: Optional[float]
    budget: BudgetSummary
    funding_gap: Optional[float]            # how much the budget falls short (0 when covered)
    surplus: Optional[float]                # how much budget is left over (0 when short)
    coverage_percent: Optional[float]       # confirmed funding / total estimated cost
    exchange_rates: ExchangeRateInfo
    explanation: List[str]
    missing_data: List[str]
    uncertainties: List[str]


class BudgetUpdate(MoneyInput):
    pass


class FinancialPlanResponse(BaseModel):
    budget: Optional[MoneyInput]
    expenses: Dict[str, ExpenseInputs]      # keyed by program id
    updated_at: Optional[datetime]
    supported_currencies: List[str]
