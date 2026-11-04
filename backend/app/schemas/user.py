import re
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


def _profile_countries(value):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise ValueError("must be a list of values")
    countries = []
    for country in value:
        if not isinstance(country, str) or not country.strip():
            raise ValueError("items must not be blank")
        country = country.strip()
        if country not in countries:
            countries.append(country)
    return countries


def _profile_currency(value):
    if value is None:
        return None
    value = value.strip().upper()
    if not value:
        return None
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("must be a 3-letter currency code")
    return value


def _graduation_month(value):
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("must use YYYY-MM format")
    return value


def _validate_profile_data(data, require_budget_pairs=True):
    if data.cgpa is not None and data.cgpa_scale is not None and data.cgpa > data.cgpa_scale:
        raise ValueError("CGPA cannot be greater than its grading scale")
    if require_budget_pairs:
        for amount_name, currency_name in (
            ("tuition_budget_amount", "tuition_budget_currency"),
            ("living_budget_amount", "living_budget_currency"),
        ):
            amount = getattr(data, amount_name)
            currency = getattr(data, currency_name)
            if (amount is None) != (currency is None):
                raise ValueError(f"{amount_name} and {currency_name} must be provided together")
    if data.tuition_budget_currency not in (None, "USD") and data.budget_usd is not None:
        raise ValueError("budget_usd can only be used for a USD tuition budget")
    return data


# ---------- USER ----------
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- PASSWORD RESET ----------
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)
    new_password: str = Field(..., min_length=6, max_length=128)


class MessageResponse(BaseModel):
    message: str


# ---------- GOOGLE SIGN-IN ----------
class GoogleCredential(BaseModel):
    credential: str = Field(..., min_length=20, max_length=4096)


class GoogleLinkRequest(GoogleCredential):
    password: str = Field(..., min_length=1, max_length=128)


# ---------- TOKEN ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LanguageTestProfile(BaseModel):
    test_type: Optional[Literal[
        "IELTS", "TOEFL iBT", "PTE", "Duolingo English Test", "Other", "No Test / Not Taken"
    ]] = None
    other_test_name: Optional[str] = Field(None, max_length=100)
    overall_score: Optional[float] = Field(None, ge=0, le=1000, allow_inf_nan=False)
    listening: Optional[float] = Field(None, ge=0, le=1000, allow_inf_nan=False)
    reading: Optional[float] = Field(None, ge=0, le=1000, allow_inf_nan=False)
    writing: Optional[float] = Field(None, ge=0, le=1000, allow_inf_nan=False)
    speaking: Optional[float] = Field(None, ge=0, le=1000, allow_inf_nan=False)
    test_date: Optional[date] = None
    test_status: Optional[Literal["Not taken", "Booked", "Completed", "Not sure"]] = None
    willing_to_test: Optional[Literal["Yes", "No", "Not sure"]] = None
    medium_of_instruction: Optional[Literal["Yes", "No", "Not available"]] = None

    @field_validator("other_test_name")
    @classmethod
    def _trim_other_test_name(cls, value):
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _validate_test_scores(self):
        limits = {
            "IELTS": (9, 9),
            "TOEFL iBT": (120, 30),
            "PTE": (90, 90),
            "Duolingo English Test": (160, 160),
        }
        overall_limit, section_limit = limits.get(self.test_type, (1000, 1000))
        if self.overall_score is not None and self.overall_score > overall_limit:
            raise ValueError(f"{self.test_type} overall score cannot exceed {overall_limit}")
        for field in ("listening", "reading", "writing", "speaking"):
            score = getattr(self, field)
            if score is not None and score > section_limit:
                raise ValueError(f"{self.test_type} {field} score cannot exceed {section_limit}")
        if self.test_date and self.test_date > date.today():
            raise ValueError("test_date cannot be in the future")
        if self.test_status == "Completed":
            if not self.test_type or self.test_type == "No Test / Not Taken":
                raise ValueError("a completed test needs a test type")
            if self.overall_score is None:
                raise ValueError("a completed test needs an overall score")
            if self.test_type == "Other" and not self.other_test_name:
                raise ValueError("name the other English test")
        if self.test_type == "TOEFL iBT" and self.overall_score is not None and not self.overall_score.is_integer():
            raise ValueError("TOEFL iBT overall score must be a whole number")
        return self


# ---------- STUDENT PROFILE ----------
class ProfileCreate(BaseModel):
    degree_level: str = Field(..., min_length=1)
    field_of_study: str = Field(..., min_length=1)
    cgpa: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    cgpa_scale: Optional[float] = Field(None, gt=0, le=1000, allow_inf_nan=False)
    ielts_score: Optional[float] = Field(None, ge=0, le=9, allow_inf_nan=False)
    toefl_score: Optional[int] = Field(None, ge=0, le=120)
    skills: Optional[str] = None
    research_interests: Optional[str] = None
    preferred_countries: Optional[str] = None
    budget_usd: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    preferred_fields: Optional[List[str]] = None
    preferred_degree_levels: Optional[List[str]] = None
    preferred_funding_types: Optional[List[str]] = None
    funding_preference: Optional[str] = None
    language_test: Optional[LanguageTestProfile] = None
    tuition_budget_amount: Optional[float] = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    tuition_budget_currency: Optional[str] = None
    living_budget_amount: Optional[float] = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    living_budget_currency: Optional[str] = None
    form_details: Optional[Dict[str, Any]] = None
    nationality: Optional[str] = Field(None, max_length=100)
    date_of_birth: Optional[date] = None
    institution: Optional[str] = Field(None, max_length=200)
    academic_status: Optional[str] = Field(None, max_length=30)
    graduation_date: Optional[str] = Field(None, max_length=7)
    work_experience: Optional[str] = Field(None, max_length=2000)

    @field_validator("degree_level", "field_of_study")
    @classmethod
    def _trim_required_profile_fields(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("academic_status")
    @classmethod
    def _validate_academic_status(cls, value):
        if value is None:
            return None
        value = value.strip()
        if value not in {"studying", "graduated"}:
            raise ValueError("must be 'studying' or 'graduated'")
        return value

    @field_validator("preferred_fields", "preferred_degree_levels", "preferred_funding_types", mode="before")
    @classmethod
    def _normalize_profile_lists(cls, value):
        return _profile_countries(value)

    @field_validator("tuition_budget_currency", "living_budget_currency")
    @classmethod
    def _normalize_profile_currencies(cls, value):
        return _profile_currency(value)

    @field_validator("graduation_date")
    @classmethod
    def _validate_graduation_month(cls, value):
        return _graduation_month(value)

    @model_validator(mode="after")
    def _validate_profile_values(self):
        return _validate_profile_data(self)


class ProfileUpdate(BaseModel):
    degree_level: Optional[str] = None
    field_of_study: Optional[str] = None
    cgpa: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    cgpa_scale: Optional[float] = Field(None, gt=0, le=1000, allow_inf_nan=False)
    ielts_score: Optional[float] = Field(None, ge=0, le=9, allow_inf_nan=False)
    toefl_score: Optional[int] = Field(None, ge=0, le=120)
    skills: Optional[str] = None
    research_interests: Optional[str] = None
    preferred_countries: Optional[str] = None
    budget_usd: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    preferred_fields: Optional[List[str]] = None
    preferred_degree_levels: Optional[List[str]] = None
    preferred_funding_types: Optional[List[str]] = None
    funding_preference: Optional[str] = None
    language_test: Optional[LanguageTestProfile] = None
    tuition_budget_amount: Optional[float] = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    tuition_budget_currency: Optional[str] = None
    living_budget_amount: Optional[float] = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    living_budget_currency: Optional[str] = None
    form_details: Optional[Dict[str, Any]] = None
    nationality: Optional[str] = Field(None, max_length=100)
    date_of_birth: Optional[date] = None
    institution: Optional[str] = Field(None, max_length=200)
    academic_status: Optional[str] = Field(None, max_length=30)
    graduation_date: Optional[str] = Field(None, max_length=7)
    work_experience: Optional[str] = Field(None, max_length=2000)

    @field_validator("degree_level", "field_of_study")
    @classmethod
    def _trim_profile_fields(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("academic_status")
    @classmethod
    def _validate_academic_status(cls, value):
        if value is None:
            return None
        value = value.strip()
        if value not in {"studying", "graduated"}:
            raise ValueError("must be 'studying' or 'graduated'")
        return value

    @field_validator("preferred_fields", "preferred_degree_levels", "preferred_funding_types", mode="before")
    @classmethod
    def _normalize_profile_lists(cls, value):
        return _profile_countries(value)

    @field_validator("tuition_budget_currency", "living_budget_currency")
    @classmethod
    def _normalize_profile_currencies(cls, value):
        return _profile_currency(value)

    @field_validator("graduation_date")
    @classmethod
    def _validate_graduation_month(cls, value):
        return _graduation_month(value)

    @model_validator(mode="after")
    def _validate_profile_values(self):
        return _validate_profile_data(self, require_budget_pairs=False)


class ProfileStatus(BaseModel):
    required: bool
    complete: bool
    percent: int
    missing: List[str]


class ProfileResponse(BaseModel):
    id: int
    user_id: int
    degree_level: Optional[str]
    field_of_study: Optional[str]
    cgpa: Optional[float]
    cgpa_scale: Optional[float]
    ielts_score: Optional[float]
    toefl_score: Optional[int]
    skills: Optional[str]
    research_interests: Optional[str]
    preferred_countries: Optional[str]
    budget_usd: Optional[float]
    preferred_fields: Optional[List[str]] = None
    preferred_degree_levels: Optional[List[str]] = None
    preferred_funding_types: Optional[List[str]] = None
    funding_preference: Optional[str] = None
    language_test: Optional[LanguageTestProfile] = None
    tuition_budget_amount: Optional[float] = None
    tuition_budget_currency: Optional[str] = None
    living_budget_amount: Optional[float] = None
    living_budget_currency: Optional[str] = None
    form_details: Optional[Dict[str, Any]] = None
    nationality: Optional[str] = None
    date_of_birth: Optional[date] = None
    institution: Optional[str] = Field(None, max_length=200)
    academic_status: Optional[str] = Field(None, max_length=30)
    graduation_date: Optional[str] = Field(None, max_length=10)
    work_experience: Optional[str] = Field(None, max_length=2000)

    class Config:
        from_attributes = True