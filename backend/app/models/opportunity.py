from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class University(Base):
    __tablename__ = "universities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    country = Column(String, nullable=False, index=True)
    city = Column(String)
    ranking = Column(Integer, nullable=True)
    website = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    programs = relationship("Program", back_populates="university")


class Program(Base):
    __tablename__ = "programs"

    id = Column(Integer, primary_key=True, index=True)
    university_id = Column(Integer, ForeignKey("universities.id"), nullable=False)

    name = Column(String, nullable=False, index=True)
    degree_level = Column(String)             # Master | PhD
    field_of_study = Column(String, index=True)
    duration_months = Column(Integer)
    tuition_usd_per_year = Column(Float)
    living_cost_usd_per_year = Column(Float, nullable=True)

    # Admission requirements
    min_cgpa = Column(Float, nullable=True)
    min_ielts = Column(Float, nullable=True)
    min_toefl = Column(Integer, nullable=True)
    required_degree = Column(String, nullable=True)

    application_deadline = Column(String, nullable=True)  # e.g. "2026-01-15"
    description = Column(Text, nullable=True)
    source_url = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    university = relationship("University", back_populates="programs")
    

class Scholarship(Base):
    __tablename__ = "scholarships"

    id = Column(Integer, primary_key=True, index=True)

    country = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    provider = Column(Text)
    degree_level = Column(String, index=True)
    study_type = Column(Text)
    eligible_nationalities = Column(Text)
    pakistan_eligible = Column(Text)
    eligible_fields = Column(Text)
    min_academic_requirement = Column(Text)
    bachelors_requirement = Column(Text)
    english_requirement = Column(Text)
    work_experience = Column(Text)
    age_requirement = Column(Text)
    funding_type = Column(String, index=True)
    tuition_coverage = Column(Text)
    living_stipend = Column(Text)
    travel_airfare = Column(Text)
    accommodation = Column(Text)
    health_insurance = Column(Text)
    visa_support = Column(Text)
    other_benefits = Column(Text)
    duration = Column(Text)
    deadline = Column(Text)
    application_method = Column(Text)
    admission_required = Column(Text)
    nomination_required = Column(Text)
    required_documents = Column(Text)
    application_pathway = Column(Text)
    official_url = Column(Text)
    source_name = Column(Text)
    last_verified = Column(Text)
    notes = Column(Text)

    # verified | unverified (unverified ko students ko recommend nahi karenge)
    verification_status = Column(String, default="verified", index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())