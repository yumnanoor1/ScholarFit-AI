from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


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


# ---------- TOKEN ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- STUDENT PROFILE ----------
class ProfileCreate(BaseModel):
    degree_level: str
    field_of_study: str
    cgpa: float
    cgpa_scale: float = 4.0
    ielts_score: Optional[float] = None
    toefl_score: Optional[int] = None
    skills: Optional[str] = None
    research_interests: Optional[str] = None
    preferred_countries: Optional[str] = None
    budget_usd: Optional[float] = None


class ProfileUpdate(BaseModel):
    degree_level: Optional[str] = None
    field_of_study: Optional[str] = None
    cgpa: Optional[float] = None
    cgpa_scale: Optional[float] = None
    ielts_score: Optional[float] = None
    toefl_score: Optional[int] = None
    skills: Optional[str] = None
    research_interests: Optional[str] = None
    preferred_countries: Optional[str] = None
    budget_usd: Optional[float] = None


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

    class Config:
        from_attributes = True