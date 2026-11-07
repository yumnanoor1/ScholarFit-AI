import re
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, field_serializer, field_validator, model_validator

from app.services.source_url_safety import UnsafeSourceURL, safe_source_url, validate_source_url


# ---------- UNIVERSITY ----------
class UniversityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    country: str = Field(..., min_length=1, max_length=100)
    city: Optional[str] = Field(None, max_length=120)
    ranking: Optional[int] = Field(None, gt=0)
    website: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None

    @field_validator("name", "country", "city")
    @classmethod
    def _trim_required_identity(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("website")
    @classmethod
    def _valid_website(cls, value):
        if value is not None and not is_web_url(value.strip()):
            raise ValueError("must be a single http or https URL")
        return value.strip() if value is not None else None


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
    university_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=255)
    degree_level: Optional[str] = None
    field_of_study: Optional[str] = None
    duration_months: Optional[int] = Field(None, gt=0)
    tuition_usd_per_year: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    tuition_amount: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    tuition_currency: Optional[str] = None
    living_cost_usd_per_year: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    language_of_instruction: Optional[str] = None
    min_cgpa: Optional[float] = Field(None, ge=0, le=4, allow_inf_nan=False)
    min_ielts: Optional[float] = Field(None, ge=0, le=9, allow_inf_nan=False)
    min_toefl: Optional[int] = Field(None, ge=0, le=120)
    required_degree: Optional[str] = None
    application_deadline: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    source_url: Optional[str] = Field(None, max_length=500)
    last_verified: Optional[date] = None

    @field_validator("name")
    @classmethod
    def _nonblank_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("application_deadline")
    @classmethod
    def _valid_deadline(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        try:
            date.fromisoformat(value)
        except ValueError:
            if value.casefold() not in {"rolling", "not specified", "unknown", "see official source"}:
                raise ValueError("must be an ISO date or an explicit non-date status")
        return value

    @field_validator("source_url")
    @classmethod
    def _valid_source_url(cls, value):
        if value is not None and not is_web_url(value.strip()):
            raise ValueError("must be a single http or https URL")
        return value.strip() if value is not None else None

    @field_validator("tuition_currency")
    @classmethod
    def _valid_program_currency(cls, value):
        if value is not None:
            value = value.strip().upper()
            if len(value) != 3 or not value.isalpha():
                raise ValueError("must be a 3-letter currency code")
        return value

    @model_validator(mode="after")
    def _consistent_program_data(self):
        if (self.tuition_amount is None) != (self.tuition_currency is None):
            raise ValueError("published tuition amount and currency must be supplied together")
        if (self.source_url is None) != (self.last_verified is None):
            raise ValueError("source URL and its verification date must be supplied together")
        if self.last_verified and self.last_verified > date.today():
            raise ValueError("verification date can't be in the future")
        return self


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
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    country: Optional[str] = Field(None, min_length=1, max_length=100)
    city: Optional[str] = Field(None, max_length=120)
    ranking: Optional[int] = Field(None, gt=0)
    website: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None

    @field_validator("name", "country", "city")
    @classmethod
    def _trim_updated_identity(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("website")
    @classmethod
    def _valid_updated_website(cls, value):
        if value is not None and not is_web_url(value.strip()):
            raise ValueError("must be a single http or https URL")
        return value.strip() if value is not None else None


class ProgramUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    degree_level: Optional[str] = None
    field_of_study: Optional[str] = None
    duration_months: Optional[int] = Field(None, gt=0)
    tuition_usd_per_year: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    tuition_amount: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    tuition_currency: Optional[str] = None
    living_cost_usd_per_year: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    language_of_instruction: Optional[str] = None
    min_cgpa: Optional[float] = Field(None, ge=0, le=4, allow_inf_nan=False)
    min_ielts: Optional[float] = Field(None, ge=0, le=9, allow_inf_nan=False)
    min_toefl: Optional[int] = Field(None, ge=0, le=120)
    required_degree: Optional[str] = None
    application_deadline: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    source_url: Optional[str] = Field(None, max_length=500)
    last_verified: Optional[date] = None

    @field_validator("name")
    @classmethod
    def _nonblank_updated_name(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("application_deadline")
    @classmethod
    def _valid_updated_deadline(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        try:
            date.fromisoformat(value)
        except ValueError:
            if value.casefold() not in {"rolling", "not specified", "unknown", "see official source"}:
                raise ValueError("must be an ISO date or an explicit non-date status")
        return value

    @field_validator("source_url")
    @classmethod
    def _valid_updated_source_url(cls, value):
        if value is not None and not is_web_url(value.strip()):
            raise ValueError("must be a single http or https URL")
        return value.strip() if value is not None else None

    @field_validator("tuition_currency")
    @classmethod
    def _valid_updated_currency(cls, value):
        if value is not None:
            value = value.strip().upper()
            if len(value) != 3 or not value.isalpha():
                raise ValueError("must be a 3-letter currency code")
        return value

    @model_validator(mode="after")
    def _consistent_updated_program_data(self):
        if (self.tuition_amount is None) != (self.tuition_currency is None):
            raise ValueError("published tuition amount and currency must be supplied together")
        if (self.source_url is None) != (self.last_verified is None):
            raise ValueError("source URL and its verification date must be supplied together")
        if self.last_verified and self.last_verified > date.today():
            raise ValueError("verification date can't be in the future")
        return self


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
        if self.min_gpa is not None and self.min_gpa_scale is not None and self.min_gpa > self.min_gpa_scale:
            raise ValueError("min_gpa can't exceed its grading scale")
        if self.last_verified_date and self.last_verified_date > date.today():
            raise ValueError("verification date can't be in the future")
        return self


def is_web_url(value: str) -> bool:
    return bool(re.fullmatch(r"https?://[^\s;|]+\.[^\s;|]+", value or ""))


class ScholarshipBase(ScholarshipStructured):
    model_config = {"extra": "forbid", "from_attributes": True, "hide_input_in_errors": True}

    country: Optional[str] = Field(None, min_length=1, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
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

    @field_validator("country", "name")
    @classmethod
    def _trim_scholarship_identity(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("last_verified")
    @classmethod
    def _valid_legacy_verification_date(cls, value):
        if value is None or value == "":
            return None
        try:
            verified_on = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("must be an ISO date") from exc
        if verified_on > date.today():
            raise ValueError("verification date can't be in the future")
        return verified_on.isoformat()


class ScholarshipWriteBase(ScholarshipBase):
    @field_validator("official_url", "official_info_url", "official_application_url")
    @classmethod
    def _sanitize_source_url(cls, value):
        if value is None:
            return None
        try:
            validate_source_url(value)
        except UnsafeSourceURL:
            raise ValueError("must be a valid HTTP or HTTPS URL without credentials") from None
        safe_url = safe_source_url(value)
        if safe_url is None:
            raise ValueError("must be a valid HTTP or HTTPS URL without credentials")
        return safe_url

    @field_validator("additional_source_urls")
    @classmethod
    def _sanitize_additional_source_urls(cls, value):
        if value is None:
            return None
        sanitized = []
        for url in value:
            try:
                validate_source_url(url)
            except UnsafeSourceURL:
                raise ValueError("every entry must be a valid HTTP or HTTPS URL without credentials") from None
            safe_url = safe_source_url(url)
            if safe_url is None:
                raise ValueError("every entry must be a valid HTTP or HTTPS URL without credentials")
            sanitized.append(safe_url)
        return sanitized


class ScholarshipCreate(ScholarshipWriteBase):
    country: str
    name: str
    verification_status: Optional[Literal["verified", "unverified"]] = Field(None, exclude=True)


class ScholarshipUpdate(ScholarshipWriteBase):
    structured_data_version: Optional[int] = Field(None, exclude=True)
    verification_status: Optional[str] = None  # verified | unverified; only the verification endpoint can set "verified"
    expected_version: Optional[int] = None     # record_version the form was loaded with
    reviewed_groups: List[str] = []            # requirement groups the admin confirms are consistent
    audit_note: Optional[str] = None

    @field_validator("country", "name")
    @classmethod
    def _trim_scholarship_identity(cls, value):
        return value.strip() if value is not None else None


class ScholarshipResponse(ScholarshipBase):
    id: int
    country: str = Field(..., min_length=1)
    verification_status: Optional[str] = None
    structured_data_version: Optional[int] = None   # read-only; the frontend's sign that structured fields are filled
    record_version: Optional[int] = None
    archived: bool = False

    @field_validator("official_url", "official_info_url", "official_application_url", mode="before")
    @classmethod
    def _sanitize_legacy_source_url(cls, value):
        return safe_source_url(value)

    @field_validator("additional_source_urls", mode="before")
    @classmethod
    def _sanitize_legacy_additional_source_urls(cls, value):
        if value is None:
            return None
        if not isinstance(value, (list, tuple)):
            return None
        return [safe for url in value if (safe := safe_source_url(url)) is not None]

    @field_serializer("official_url", "official_info_url", "official_application_url")
    def _serialize_source_url(self, value):
        return safe_source_url(value)

    @field_serializer("additional_source_urls")
    def _serialize_additional_source_urls(self, value):
        if value is None:
            return None
        return [safe for url in value if (safe := safe_source_url(url)) is not None]


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
