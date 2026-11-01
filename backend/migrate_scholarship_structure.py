"""
Adds the structured scholarship columns and fills them from the reviewed table in
scholarship_structured_data.py. Safe to run again: columns are added only when missing, and a
row already at STRUCTURED_DATA_VERSION is left alone, so later admin edits aren't overwritten.
Original text columns, IDs and verification_status are never written.

  python migrate_scholarship_structure.py          add columns, fill rows, print a report
  python migrate_scholarship_structure.py --check  add columns and report; fills no rows
"""
import re
import sys
import unicodedata
from datetime import date

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.database import engine as default_engine
from app.models.opportunity import Scholarship
from app.schemas.opportunity import ScholarshipStructured
from scholarship_structured_data import RECORDS

STRUCTURED_DATA_VERSION = 1
ORIGINAL_DOES_NOT_CONTAIN = "not in the record's own text"


def _plain(value) -> str:
    folded = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def add_missing_columns(engine) -> list:
    existing = {column["name"] for column in inspect(engine).get_columns("scholarships")}
    added = []
    with engine.begin() as conn:
        for column in Scholarship.__table__.columns:
            if column.name in existing:
                continue
            sql_type = column.type.compile(dialect=engine.dialect)
            references = " REFERENCES scholarships(id) ON DELETE SET NULL" if column.foreign_keys else ""
            conn.execute(text(f"ALTER TABLE scholarships ADD COLUMN {column.name} {sql_type}{references}"))
            added.append(column.name)
    return added


def build_values(row, entry: dict) -> dict:
    """The entry checked against the shared schema, plus values read from the row itself."""
    values = {key: value for key, value in entry.items() if key != "name"}
    if "verification_basis" not in values:
        values["verification_basis"] = "official_source" if row.verification_status == "verified" else "not_verified"
    stated = re.match(r"\d{4}-\d{2}-\d{2}", row.last_verified or "")
    if stated:
        values["last_verified_date"] = stated.group()
    return ScholarshipStructured(**values).model_dump(exclude_unset=True)


def name_matches(row, entry: dict) -> bool:
    return _plain(row.name).startswith(_plain(entry["name"]))


MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
               "november", "december"]


def _digit_forms(number) -> set:
    whole = int(number)
    if whole != number:
        return {f"{number:g}"}
    return {str(whole), f"{whole:,}"}


def _date_appears(day: date, source: str) -> bool:
    month = MONTH_NAMES[day.month - 1][:3]
    # The year must follow the date: "2026-2027 cycle: 20 February 2026" doesn't support a 2027 date
    written = rf"\b0?{day.day}(\s*[-–]\s*\d{{1,2}})?\s+{month}\w*[^;]{{0,30}}\b{day.year}\b"
    return day.isoformat() in source or re.search(written, source) is not None


def audit_entry(row, values: dict) -> list:
    """Every stored number and date must appear in that record's own text, so nothing is invented."""
    problems = []
    money = {
        "tuition_amount": row.tuition_coverage, "tuition_amount_max": row.tuition_coverage,
        "stipend_amount": " ".join(filter(None, [row.living_stipend, row.tuition_coverage])),
        "stipend_amount_max": row.living_stipend, "travel_amount": row.travel_airfare,
        "tuition_percent_min": row.tuition_coverage, "tuition_percent_max": row.tuition_coverage,
        "min_percentage": row.min_academic_requirement, "min_gpa": row.min_academic_requirement,
        "min_gpa_scale": row.min_academic_requirement, "min_ielts": row.english_requirement,
    }
    for field, source in money.items():
        number = values.get(field)
        if number is not None and not any(form in (source or "") for form in _digit_forms(number)):
            problems.append(f"{field}={number} {ORIGINAL_DOES_NOT_CONTAIN}")
    for field in ("application_open_date", "application_deadline_date"):
        day = values.get(field)
        if day is not None and not _date_appears(day, (row.deadline or "").lower()):
            problems.append(f"{field}={day} {ORIGINAL_DOES_NOT_CONTAIN}")
    for field in ("official_info_url", "official_application_url"):
        url = values.get(field)
        if url and url not in (row.official_url or "") and url.rstrip("/") not in (row.official_url or ""):
            problems.append(f"{field}={url} {ORIGINAL_DOES_NOT_CONTAIN}")
    for url in values.get("additional_source_urls") or []:
        if url.rstrip("/") not in (row.official_url or ""):
            problems.append(f"additional_source_urls {url} {ORIGINAL_DOES_NOT_CONTAIN}")
    return problems


def find_duplicates(rows) -> list:
    """Pairs that look like one scholarship: same provider's first URL, or the same plain name."""
    def url_key(row):
        found = re.search(r"https?://[^\s;|]+", row.official_url or "")
        return found.group().rstrip("/").lower() if found else None

    pairs = []
    for index, first in enumerate(rows):
        for second in rows[index + 1:]:
            same_name = _plain(first.name) == _plain(second.name)
            same_url = url_key(first) is not None and url_key(first) == url_key(second)
            if same_name or same_url:
                pairs.append((first.id, second.id))
    return pairs


def backfill(session: Session) -> dict:
    report = {"updated": [], "already_current": [], "skipped": [], "problems": {}}
    for scholarship_id, entry in sorted(RECORDS.items()):
        row = session.get(Scholarship, scholarship_id)
        if row is None or not name_matches(row, entry):
            report["skipped"].append(scholarship_id)
            continue
        if (row.structured_data_version or 0) >= STRUCTURED_DATA_VERSION:
            report["already_current"].append(scholarship_id)
            continue
        values = build_values(row, entry)
        problems = audit_entry(row, values)
        if problems:
            report["problems"][scholarship_id] = problems
            continue
        for field, value in values.items():
            setattr(row, field, value)
        row.structured_data_version = STRUCTURED_DATA_VERSION
        report["updated"].append(scholarship_id)
    session.commit()
    return report


def check(session: Session) -> dict:
    """Validates every entry without writing anything."""
    problems = {}
    for scholarship_id, entry in sorted(RECORDS.items()):
        row = session.get(Scholarship, scholarship_id)
        if row is None or not name_matches(row, entry):
            problems[scholarship_id] = ["no matching row"]
            continue
        found = audit_entry(row, build_values(row, entry))
        if found:
            problems[scholarship_id] = found
    return problems


def main(engine=default_engine):
    if "--check" in sys.argv:
        add_missing_columns(engine)
    else:
        print("Columns added:", len(add_missing_columns(engine)))
    with Session(engine) as session:
        if "--check" in sys.argv:
            print("Problems:", check(session) or "none")
        else:
            report = backfill(session)
            print({key: (len(value) if key != "problems" else value) for key, value in report.items()})
        rows = session.query(Scholarship).order_by(Scholarship.id).all()
        print("Possible duplicates:", find_duplicates(rows))


if __name__ == "__main__":
    main()
