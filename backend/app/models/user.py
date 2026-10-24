from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, default="student")  # student | admin
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relation: ek user ka ek profile
    profile = relationship("StudentProfile", back_populates="user", uselist=False)


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # Academic info
    degree_level = Column(String)           # Bachelor | Master | PhD
    field_of_study = Column(String)
    cgpa = Column(Float)
    cgpa_scale = Column(Float, default=4.0)

    # Language
    ielts_score = Column(Float, nullable=True)
    toefl_score = Column(Integer, nullable=True)

    # Extra
    skills = Column(Text)                    # comma separated
    research_interests = Column(Text)
    preferred_countries = Column(Text)       # comma separated (e.g. "Germany,UK")
    budget_usd = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relation
    user = relationship("User", back_populates="profile")