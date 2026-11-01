from sqlalchemy import Column, Integer, JSON, String, Float, Date, DateTime, ForeignKey, Text, UniqueConstraint
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

    # Used by scholarship eligibility (nationality and age limits)
    nationality = Column(String, nullable=True)       # country of citizenship, e.g. "Pakistan"
    date_of_birth = Column(Date, nullable=True)

    # Used by profile improvement guidance
    institution = Column(String, nullable=True)
    academic_status = Column(String, nullable=True)   # studying | graduated
    graduation_date = Column(String, nullable=True)   # YYYY-MM (expected or actual)
    work_experience = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relation
    user = relationship("User", back_populates="profile")

class StudentFinancialPlan(Base):
    """The student's saved budget and the expense estimates they entered, per program."""
    __tablename__ = "student_financial_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    budget_amount = Column(Float, nullable=True)
    budget_currency = Column(String, nullable=True)
    # {"<program_id>": {"living_costs": {"amount": 1100, "currency": "EUR", "period": "monthly"}, ...}}
    expenses = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SavedScholarship(Base):
    """A scholarship the student bookmarked. The owner always comes from the signed-in session."""
    __tablename__ = "saved_scholarships"
    __table_args__ = (UniqueConstraint("user_id", "scholarship_id", name="uq_saved_scholarship_user_scholarship"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scholarship_id = Column(Integer, ForeignKey("scholarships.id", ondelete="CASCADE"), nullable=False, index=True)
    saved_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    scholarship = relationship("Scholarship")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Sirf SHA-256 hash store hota hai; asal token sirf email link mein jata hai
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
