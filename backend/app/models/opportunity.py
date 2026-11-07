from sqlalchemy import Boolean, CheckConstraint, Column, Integer, JSON, String, Float, Date, DateTime, ForeignKey, Text, UniqueConstraint
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
    tuition_amount = Column(Float, nullable=True)           # as published by the university
    tuition_currency = Column(String, nullable=True)        # EUR | SEK | CHF ...
    living_cost_usd_per_year = Column(Float, nullable=True)
    language_of_instruction = Column(String, nullable=True)

    # Admission requirements
    min_cgpa = Column(Float, nullable=True)
    min_ielts = Column(Float, nullable=True)
    min_toefl = Column(Integer, nullable=True)
    required_degree = Column(String, nullable=True)

    application_deadline = Column(String, nullable=True)  # e.g. "2026-01-15"
    description = Column(Text, nullable=True)
    source_url = Column(String, nullable=True)
    last_verified = Column(Date, nullable=True)             # date source_url was checked

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    university = relationship("University", back_populates="programs")
    costs = relationship("ProgramCost", back_populates="program", cascade="all, delete-orphan")
    scholarship_links = relationship("ScholarshipProgramLink", back_populates="program", passive_deletes=True)


class ProgramCost(Base):
    """A published cost of a program, in its own currency. Only sourced figures belong here;
    a cost nobody has verified has no row, and the feasibility calculation reports it as missing."""
    __tablename__ = "program_costs"
    __table_args__ = (UniqueConstraint("program_id", "category", name="uq_program_cost_category"),)

    id = Column(Integer, primary_key=True, index=True)
    program_id = Column(Integer, ForeignKey("programs.id"), nullable=False, index=True)

    # living_costs (accommodation, food, everyday) | university_fees | application_fees
    # | health_insurance | visa | travel | other
    category = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    amount_max = Column(Float, nullable=True)           # upper end when the source gives a range
    currency = Column(String, nullable=False)
    period = Column(String, nullable=False)             # monthly | semester | yearly | total
    note = Column(Text, nullable=True)
    includes = Column(String, nullable=True)            # other categories inside this figure, comma separated
    is_estimate = Column(Boolean, default=False, nullable=False)   # the source itself calls it an estimate
    source_name = Column(String, nullable=True)
    source_url = Column(String, nullable=False)
    last_verified = Column(Date, nullable=False)

    program = relationship("Program", back_populates="costs")


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
    verification_status = Column(String, default="unverified", index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Structured values taken from the text columns above, which stay as the original wording.
    # Allowed values live in app/schemas/opportunity.py. NULL means the record doesn't say.
    nationality_scope = Column(String)
    eligible_countries = Column(JSON)
    excluded_countries = Column(JSON)
    eligible_regions = Column(JSON)
    excluded_regions = Column(JSON)
    eligible_degree_levels = Column(JSON)
    required_previous_degree = Column(String)
    discipline_scope = Column(String)
    eligible_disciplines = Column(JSON)
    academic_condition = Column(String)
    min_gpa = Column(Float)
    min_gpa_scale = Column(Float)
    min_percentage = Column(Float)
    english_requirement_type = Column(String)
    accepted_english_tests = Column(JSON)
    min_ielts = Column(Float)
    min_toefl = Column(Float)
    min_duolingo = Column(Float)
    min_age = Column(Integer)
    max_age = Column(Integer)
    gender_restriction = Column(String)
    applicant_restrictions = Column(JSON)
    residency_requirement = Column(Text)

    funding_level = Column(String)
    tuition_coverage_type = Column(String)
    tuition_percent_min = Column(Float)
    tuition_percent_max = Column(Float)
    tuition_amount = Column(Float)
    tuition_amount_max = Column(Float)
    tuition_currency = Column(String)
    tuition_period = Column(String)
    stipend_status = Column(String)
    stipend_amount = Column(Float)
    stipend_amount_max = Column(Float)
    stipend_currency = Column(String)
    stipend_period = Column(String)
    stipend_is_approximate = Column(Boolean)
    accommodation_status = Column(String)
    health_insurance_status = Column(String)
    travel_status = Column(String)
    travel_amount = Column(Float)
    travel_currency = Column(String)
    funding_duration_months = Column(Integer)
    costs_not_covered = Column(JSON)

    deadline_type = Column(String)
    application_open_date = Column(Date)
    application_deadline_date = Column(Date)
    application_cycle = Column(String)
    official_info_url = Column(Text)
    official_application_url = Column(Text)
    additional_source_urls = Column(JSON)
    application_channel = Column(String)
    required_documents_list = Column(JSON)

    verification_basis = Column(String)
    verification_notes = Column(Text)
    last_verified_date = Column(Date)
    duplicate_of_id = Column(Integer, ForeignKey("scholarships.id", ondelete="SET NULL"))
    structured_data_version = Column(Integer)   # set by migrate_scholarship_structure.py

    # Where the award can be held. NULL means nobody has reviewed it.
    institution_scope = Column(String)          # single_institution | participating_list | national
    host_institution = Column(String)           # the one institution, in the record's own words
    host_university_id = Column(Integer, ForeignKey("universities.id", ondelete="SET NULL"))   # set only when it's in our catalog

    # Administration. See services/scholarship_quality.py
    record_version = Column(Integer, nullable=False, default=1, server_default="1")  # optimistic concurrency token
    data_flags = Column(JSON)                   # open review flags, e.g. conflicting_information, review:english
    source_checks = Column(JSON)                # last link check per URL; never changes verification
    archived_at = Column(DateTime(timezone=True))   # archived records leave every listing but keep their ID and references
    archived_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    archive_reason = Column(Text)

    program_links = relationship("ScholarshipProgramLink", back_populates="scholarship", passive_deletes=True)

    @property
    def archived(self):
        return self.archived_at is not None


class ScholarshipAuditLog(Base):
    """Who changed a scholarship record, when, and what changed. scholarship_id stays after a delete."""
    __tablename__ = "scholarship_audit_log"

    id = Column(Integer, primary_key=True, index=True)
    scholarship_id = Column(Integer, nullable=False, index=True)
    action = Column(String, nullable=False)     # created | updated | verification | flag | archived | restored | ...
    changes = Column(JSON)                      # {field: [old, new]}
    note = Column(Text)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    actor_email = Column(String)                # the administrator, kept if the account goes
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ScholarshipProgramLink(Base):
    """A reviewed statement about one scholarship and one program. Which programs a scholarship may
    support is worked out in services/scholarship_matching.py; a row here adds the evidence for a pair.
    Its verification_status is about this relationship, not the scholarship record."""
    __tablename__ = "scholarship_program_links"
    __table_args__ = (
        UniqueConstraint("scholarship_id", "program_id", name="uq_scholarship_program_link"),
        CheckConstraint("outcome IN ('confirmed', 'potential', 'not_a_match', 'needs_verification')", name="ck_link_outcome"),
        CheckConstraint("verification_status IN ('verified', 'unverified')", name="ck_link_verification"),
        CheckConstraint(
            "outcome <> 'confirmed' OR (verification_status = 'verified' AND evidence IS NOT NULL "
            "AND source_url IS NOT NULL AND last_verified IS NOT NULL)",
            name="ck_link_confirmed_has_evidence"),
    )

    id = Column(Integer, primary_key=True, index=True)
    scholarship_id = Column(Integer, ForeignKey("scholarships.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id = Column(Integer, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)

    outcome = Column(String, nullable=False)
    # named_program | all_programs_at_university | programs_meeting_stated_criteria | unconfirmed
    relationship_type = Column(String, nullable=False)
    evidence = Column(Text)                     # what the source says about this pair
    source_url = Column(Text)
    verification_status = Column(String, nullable=False, default="unverified")
    last_verified = Column(Date)                # date source_url was actually read for this pair
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    scholarship = relationship("Scholarship", back_populates="program_links")
    program = relationship("Program", back_populates="scholarship_links")