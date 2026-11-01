import re
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


# ---------- UNIVERSITY ----------
class UniversityCreate(BaseModel):
    name: str
    country: str
    city: Optional[str] = None
    ranking: Optional[int] = None
    website: Optional[str] = None
    description: Optional[str] = None


class UniversityResponse(BaseModel):
    id: int
    name: str
    country: str
    city: Optional[str]
    ranking: Optional[int]
    website: Optional[str]
    description: Optional[str]

    class Config:
        from_attributes = True


# ---------- PROGRAM ----------
class ProgramCreate(BaseModel):
    university_id: int
    name: str
    degree_level: Optional[str] = None
    field_of_study: Optional[str] = None
    duration_months: Optional[int] = None
    tuition_usd_per_year: Optional[float] = None
    tuition_amount: Optional[float] = None
    tuition_currency: Optional[str] = None
    living_cost_usd_per_year: Optional[float] = None
    language_of_instruction: Optional[str] = None
    min_cgpa: Optional[float] = None
    min_ielts: Optional[float] = None
    min_toefl: Optional[int] = None
    required_degree: Optional[str] = None
    application_deadline: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None
    last_verified: Optional[date] = None


class ProgramResponse(BaseModel):
    id: int
    university_id: int
    name: str
    degree_level: Optional[str]
    field_of_study: Optional[str]
    duration_months: Optional[int]
    tuition_usd_per_year: Optional[float]
    tuition_amount: Optional[float] = None
    tuition_currency: Optional[str] = None
    living_cost_usd_per_year: Optional[float]
    language_of_instruction: Optional[str] = None
    min_cgpa: Optional[float]
    min_ielts: Optional[float]
    min_toefl: Optional[int]
    required_degree: Optional[str]
    application_deadline: Optional[str]
    description: Optional[str]
    source_url: Optional[str]
    last_verified: Optional[date] = None

    class Config:
        from_attributes = True
        

# ---------- UPDATE SCHEMAS (PUT ke liye) ----------
class UniversityUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    ranking: Optional[int] = None
    website: Optional[str] = None
    description: Optional[str] = None


class ProgramUpdate(BaseModel):
    name: Optional[str] = None
    degree_level: Optional[str] = None
    field_of_study: Optional[str] = None
    duration_months: Optional[int] = None
    tuition_usd_per_year: Optional[float] = None
    tuition_amount: Optional[float] = None
    tuition_currency: Optional[str] = None
    living_cost_usd_per_year: Optional[float] = None
    language_of_instruction: Optional[str] = None
    min_cgpa: Optional[float] = None
    min_ielts: Optional[float] = None
    min_toefl: Optional[int] = None
    required_degree: Optional[str] = None
    application_deadline: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None
    last_verified: Optional[date] = None


# ---------- SCHOLARSHIP ----------
CURRENCY_CODES = {"EUR", "GBP", "AUD", "USD", "TRY", "HUF", "SEK", "PLN", "CZK", "MYR"}
BenefitStatus = Literal["covered", "via_stipend", "partial", "not_covered", "not_specified"]
AmountPeriod = Literal["monthly", "annual", "total"]
ApplicantRestriction = Literal[
    "former_citizenship_excluded", "nationality_cap", "dual_citizenship_excluded", "first_time_applicant",
    "second_masters_excluded", "previous_scholarship_excluded", "high_income_study_excluded",
    "other_funding_excluded", "employee_excluded", "financial_need_required", "eu_tax_household_excluded",
    "residency_required", "participating_institution_only", "enrolled_student_required", "fee_paying_only",
    "first_year_only", "early_application_only", "admission_test_required", "minimum_work_experience",
    "return_home_required",
]


class ScholarshipStructured(BaseModel):
    """Structured scholarship fields. None means the record doesn't say; it never means zero or "no"."""
    model_config = {"extra": "forbid"}

    nationality_scope: Optional[Literal["all", "all_except", "listed", "published_list", "not_specified"]] = None
    eligible_countries: Optional[List[str]] = None      # named in the record; complete only when scope is "listed"
    excluded_countries: Optional[List[str]] = None
    eligible_regions: Optional[List[str]] = None
    excluded_regions: Optional[List[str]] = None
    eligible_degree_levels: Optional[List[str]] = None
    required_previous_degree: Optional[str] = None
    discipline_scope: Optional[Literal["all", "listed", "restricted", "varies", "not_specified"]] = None
    eligible_disciplines: Optional[List[str]] = None
    academic_condition: Optional[Literal[
        "numeric", "degree_class", "class_rank", "merit_based", "set_by_institution", "not_specified"]] = None
    min_gpa: Optional[float] = Field(None, gt=0)
    min_gpa_scale: Optional[float] = Field(None, gt=0)
    min_percentage: Optional[float] = Field(None, gt=0, le=100)
    english_requirement_type: Optional[Literal["test_required", "set_by_institution", "not_required", "not_specified"]] = None
    accepted_english_tests: Optional[List[str]] = None
    min_ielts: Optional[float] = Field(None, ge=0, le=9)
    min_toefl: Optional[float] = Field(None, ge=0, le=120)
    min_duolingo: Optional[float] = Field(None, ge=0, le=160)
    min_age: Optional[int] = Field(None, gt=0, lt=120)
    max_age: Optional[int] = Field(None, gt=0, lt=120)
    gender_restriction: Optional[Literal["women"]] = None
    applicant_restrictions: Optional[List[ApplicantRestriction]] = None
    residency_requirement: Optional[str] = None

    funding_level: Optional[Literal["full", "partial", "tuition_only", "mixed", "not_specified"]] = None
    tuition_coverage_type: Optional[Literal[
        "full", "percentage", "fixed_amount", "tiered", "conditional", "none", "not_specified"]] = None
    tuition_percent_min: Optional[float] = Field(None, gt=0, le=100)
    tuition_percent_max: Optional[float] = Field(None, gt=0, le=100)
    tuition_amount: Optional[float] = Field(None, gt=0)
    tuition_amount_max: Optional[float] = Field(None, gt=0)
    tuition_currency: Optional[str] = None
    tuition_period: Optional[AmountPeriod] = None
    stipend_status: Optional[Literal["provided", "included_in_package", "conditional", "none", "not_specified"]] = None
    stipend_amount: Optional[float] = Field(None, gt=0)
    stipend_amount_max: Optional[float] = Field(None, gt=0)
    stipend_currency: Optional[str] = None
    stipend_period: Optional[AmountPeriod] = None
    stipend_is_approximate: Optional[bool] = None
    accommodation_status: Optional[BenefitStatus] = None
    health_insurance_status: Optional[BenefitStatus] = None
    travel_status: Optional[BenefitStatus] = None
    travel_amount: Optional[float] = Field(None, gt=0)
    travel_currency: Optional[str] = None
    funding_duration_months: Optional[int] = Field(None, gt=0)
    costs_not_covered: Optional[List[Literal["tuition", "living_costs"]]] = None

    deadline_type: Optional[Literal[
        "fixed", "rolling", "annual", "varies_by_institution", "no_separate_deadline", "not_specified"]] = None
    application_open_date: Optional[date] = None
    application_deadline_date: Optional[date] = None
    application_cycle: Optional[str] = None
    official_info_url: Optional[str] = None
    official_application_url: Optional[str] = None
    additional_source_urls: Optional[List[str]] = None
    application_channel: Optional[Literal["direct", "via_institution", "nomination", "automatic", "not_specified"]] = None
    required_documents_list: Optional[List[str]] = None

    verification_basis: Optional[Literal["official_source", "mixed_sources", "secondary_only", "not_verified"]] = None
    verification_notes: Optional[str] = None
    last_verified_date: Optional[date] = None
    duplicate_of_id: Optional[int] = Field(None, gt=0)

    institution_scope: Optional[Literal["single_institution", "participating_list", "national"]] = None
    host_institution: Optional[str] = None
    host_university_id: Optional[int] = Field(None, gt=0)

    @field_validator("official_info_url", "official_application_url")
    @classmethod
    def _web_url(cls, value):
        if value is not None and not is_web_url(value):
            raise ValueError("must be a single http or https URL")
        return value

    @field_validator("additional_source_urls")
    @classmethod
    def _web_urls(cls, value):
        if value is not None and not all(is_web_url(item) for item in value):
            raise ValueError("every entry must be a single http or https URL")
        return value

    @field_validator("tuition_currency", "stipend_currency", "travel_currency")
    @classmethod
    def _currency(cls, value):
        if value is not None and value not in CURRENCY_CODES:
            raise ValueError("must be a known ISO currency code")
        return value

    @model_validator(mode="after")
    def _consistent(self):
        # A number without its unit can't be read, and a range must run upward
        if self.stipend_amount_max is not None and self.stipend_currency is None:
            raise ValueError("a stipend amount needs a currency")
        if self.stipend_amount is not None and self.stipend_currency is None:
            raise ValueError("a stipend amount needs a currency")
        if self.tuition_amount is not None and self.tuition_currency is None:
            raise ValueError("a tuition amount needs a currency")
        if self.travel_amount is not None and self.travel_currency is None:
            raise ValueError("a travel amount needs a currency")
        if (self.min_gpa is None) != (self.min_gpa_scale is None):
            raise ValueError("min_gpa and min_gpa_scale go together")
        for low, high in ((self.stipend_amount, self.stipend_amount_max), (self.tuition_amount, self.tuition_amount_max),
                          (self.tuition_percent_min, self.tuition_percent_max), (self.min_age, self.max_age),
                          (self.application_open_date, self.application_deadline_date)):
            if low is not None and high is not None and low > high:
                raise ValueError("a range must run from low to high")
        return self


def is_web_url(value: str) -> bool:
    return bool(re.fullmatch(r"https?://[^\s;|]+\.[^\s;|]+", value or ""))


class ScholarshipBase(ScholarshipStructured):
    model_config = {"extra": "ignore", "from_attributes": True}

    country: Optional[str] = None
    name: Optional[str] = None
    provider: Optional[str] = None
    degree_level: Optional[str] = None
    study_type: Optional[str] = None
    eligible_nationalities: Optional[str] = None
    pakistan_eligible: Optional[str] = None
    eligible_fields: Optional[str] = None
    min_academic_requirement: Optional[str] = None
    bachelors_requirement: Optional[str] = None
    english_requirement: Optional[str] = None
    work_experience: Optional[str] = None
    age_requirement: Optional[str] = None
    funding_type: Optional[str] = None
    tuition_coverage: Optional[str] = None
    living_stipend: Optional[str] = None
    travel_airfare: Optional[str] = None
    accommodation: Optional[str] = None
    health_insurance: Optional[str] = None
    visa_support: Optional[str] = None
    other_benefits: Optional[str] = None
    duration: Optional[str] = None
    deadline: Optional[str] = None
    application_method: Optional[str] = None
    admission_required: Optional[str] = None
    nomination_required: Optional[str] = None
    required_documents: Optional[str] = None
    application_pathway: Optional[str] = None
    official_url: Optional[str] = None
    source_name: Optional[str] = None
    last_verified: Optional[str] = None
    notes: Optional[str] = None


class ScholarshipCreate(ScholarshipBase):
    country: str
    name: str


class ScholarshipUpdate(ScholarshipBase):
    verification_status: Optional[str] = None  # verified | unverified; only the verification endpoint can set "verified"
    expected_version: Optional[int] = None     # record_version the form was loaded with
    reviewed_groups: List[str] = []            # requirement groups the admin confirms are consistent
    audit_note: Optional[str] = None


class ScholarshipResponse(ScholarshipBase):
    id: int
    verification_status: Optional[str] = None
    structured_data_version: Optional[int] = None   # read-only; the frontend's sign that structured fields are filled
    record_version: Optional[int] = None
    archived: bool = False


class ScholarshipWriteResult(ScholarshipResponse):
    data_flags: Optional[List[str]] = None
    warnings: List[str] = []


class SavedScholarshipResponse(BaseModel):
    id: int
    scholarship_id: int
    saved_at: datetime
    scholarship: ScholarshipResponse

    class Config:
        from_attributes = True


# ---------- PROGRAM COST ----------
CostCategory = Literal["living_costs", "university_fees", "application_fees", "health_insurance", "visa", "travel", "other"]


class ProgramCostUpdate(BaseModel):
    amount: float = Field(..., ge=0, le=1e12, allow_inf_nan=False)
    amount_max: Optional[float] = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    note: Optional[str] = None
    includes: Optional[str] = None
    currency: str
    period: Literal["monthly", "semester", "yearly", "total"]
    is_estimate: bool = False
    source_name: Optional[str] = None
    # A cost needs a source and a check date: unsourced figures don't belong in this table
    source_url: HttpUrl
    last_verified: date

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, value):
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("Currency must be a 3-letter code such as EUR or USD")
        return value


class ProgramCostResponse(BaseModel):
    id: int
    program_id: int
    category: str
    amount: float
    amount_max: Optional[float] = None
    note: Optional[str] = None
    includes: Optional[str] = None
    currency: str
    period: str
    is_estimate: bool
    source_name: Optional[str] = None
    source_url: str
    last_verified: date

    class Config:
        from_attributes = True
