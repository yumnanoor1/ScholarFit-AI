from sqlalchemy import CheckConstraint, Column, DateTime, JSON, String, text

from app.database import Base


SCHOLARSHIP_DISCOVERY_TABLE_NAMES = frozenset({"scholarship_discovery_runs"})


class ScholarshipDiscoveryRun(Base):
    __tablename__ = "scholarship_discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_scholarship_discovery_run_status",
        ),
    )

    id = Column(String(36), primary_key=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    status = Column(String(16), nullable=False, default="running", server_default="running")
    summary = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    source_results = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
