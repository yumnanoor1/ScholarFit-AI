from pydantic import BaseModel
from typing import Optional
from datetime import datetime


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
    living_cost_usd_per_year: Optional[float] = None
    min_cgpa: Optional[float] = None
    min_ielts: Optional[float] = None
    min_toefl: Optional[int] = None
    required_degree: Optional[str] = None
    application_deadline: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None


class ProgramResponse(BaseModel):
    id: int
    university_id: int
    name: str
    degree_level: Optional[str]
    field_of_study: Optional[str]
    duration_months: Optional[int]
    tuition_usd_per_year: Optional[float]
    living_cost_usd_per_year: Optional[float]
    min_cgpa: Optional[float]
    min_ielts: Optional[float]
    min_toefl: Optional[int]
    required_degree: Optional[str]
    application_deadline: Optional[str]
    description: Optional[str]
    source_url: Optional[str]

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
    living_cost_usd_per_year: Optional[float] = None
    min_cgpa: Optional[float] = None
    min_ielts: Optional[float] = None
    min_toefl: Optional[int] = None
    required_degree: Optional[str] = None
    application_deadline: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None
    

# ---------- SCHOLARSHIP ----------
class ScholarshipBase(BaseModel):
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
    verification_status: Optional[str] = None  # verified | unverified


class ScholarshipResponse(ScholarshipBase):
    id: int
    verification_status: Optional[str] = None

    class Config:
        from_attributes = True