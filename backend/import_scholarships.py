import argparse
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from app.database import SessionLocal
from app.models.opportunity import Scholarship, ScholarshipAuditLog
from app.schemas.opportunity import ScholarshipCreate, is_web_url

DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCE_URL_RE = re.compile(r"https?://[^\s;|<>]*", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,;:!?)]}"

COLUMN_MAP = {
    "Country": "country",
    "Scholarship Name": "name",
    "Provider": "provider",
    "Degree Level": "degree_level",
    "Study Type": "study_type",
    "Eligible Nationalities": "eligible_nationalities",
    "Is Pakistan Eligible?": "pakistan_eligible",
    "Eligible Fields": "eligible_fields",
    "Minimum CGPA / Academic Requirement": "min_academic_requirement",
    "Bachelor's Degree Requirement": "bachelors_requirement",
    "English Language Requirement": "english_requirement",
    "Work Experience Requirement": "work_experience",
    "Age Requirement": "age_requirement",
    "Funding Type": "funding_type",
    "Tuition Coverage": "tuition_coverage",
    "Living Stipend": "living_stipend",
    "Travel / Airfare": "travel_airfare",
    "Accommodation": "accommodation",
    "Health Insurance": "health_insurance",
    "Visa Support": "visa_support",
    "Other Benefits": "other_benefits",
    "Scholarship Duration": "duration",
    "Application Deadline": "deadline",
    "Application Method": "application_method",
    "Admission Required?": "admission_required",
    "Nomination Required?": "nomination_required",
    "Required Documents": "required_documents",
    "Application Pathway": "application_pathway",
    "Official Scholarship URL": "official_url",
    "Official Source Name": "source_name",
    "Last Verified Date": "last_verified",
    "Notes / Restrictions": "notes",
}
REQUIRED_COLUMNS = {"Country", "Scholarship Name"}


def clean(value):
    """Convert spreadsheet blanks to None and date cells to ISO dates."""
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _source_urls(value):
    urls = []
    for candidate in SOURCE_URL_RE.findall(value or ""):
        url = candidate.rstrip(TRAILING_URL_PUNCTUATION)
        if not is_web_url(url):
            raise ValueError(f"Invalid source URL: {url}")
        if url not in urls:
            urls.append(url)
    return urls


def _identity(name, country):
    return (" ".join(name.casefold().split()), " ".join(country.casefold().split()))


def _validation_message(error):
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()
    )


def load_import_records(source_dir=DATA_DIR):
    """Validate all workbook rows before any database connection or write."""
    paths = sorted(Path(source_dir).glob("*.xlsx"))
    if not paths:
        raise FileNotFoundError(f"No scholarship .xlsx files found in {source_dir}")

    records = []
    positions = {}
    duplicate_rows = []
    for path in paths:
        frame = pd.read_excel(path)
        missing_columns = sorted(REQUIRED_COLUMNS - set(frame.columns))
        if missing_columns:
            raise ValueError(f"{path.name}: missing required columns: {', '.join(missing_columns)}")
        frame = frame.rename(columns=COLUMN_MAP).reindex(columns=list(COLUMN_MAP.values()))

        for index, source_row in frame.iterrows():
            row_number = index + 2
            for source_column in REQUIRED_COLUMNS:
                value = source_row.get(COLUMN_MAP[source_column])
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{path.name} row {row_number}: {source_column} must be text and cannot be blank")

            values = {field: clean(source_row.get(field)) for field in COLUMN_MAP.values()}
            try:
                urls = _source_urls(values.get("official_url"))
            except ValueError as error:
                raise ValueError(f"{path.name} row {row_number}: {error}") from error
            if urls:
                values["official_info_url"] = urls[0]
                values["additional_source_urls"] = urls[1:] or None

            legacy_verified = values.get("last_verified")
            if legacy_verified:
                try:
                    date.fromisoformat(legacy_verified)
                except ValueError:
                    existing_note = values.get("verification_notes")
                    imported_note = (
                        f"Imported Last Verified Date value was not an ISO date and was not treated as verification: "
                        f"{legacy_verified}"
                    )
                    values["verification_notes"] = (
                        f"{existing_note}\n{imported_note}" if existing_note else imported_note
                    )
                    values["last_verified"] = None

            try:
                validated = ScholarshipCreate.model_validate(values)
            except ValidationError as error:
                name = values.get("name") or "<unnamed>"
                raise ValueError(
                    f"{path.name} row {row_number} ({name}): {_validation_message(error)}"
                ) from error

            record = validated.model_dump(exclude_unset=True)
            record["_import_source_file"] = path.name
            key = _identity(record["name"], record["country"])
            if key in positions:
                previous_file, previous_row = positions[key]
                duplicate_rows.append(
                    f"{path.name} row {row_number}: {record['name']} ({record['country']}) "
                    f"duplicates {previous_file} row {previous_row}"
                )
            else:
                positions[key] = (path.name, row_number)
                records.append(record)

    return records, duplicate_rows


def import_records(db, records):
    """Insert unique, validated records in one transaction; imports never verify them."""
    existing_rows = (
        db.query(Scholarship.name, Scholarship.country)
        .filter(Scholarship.archived_at.is_(None))
        .all()
    )
    existing = {_identity(name, country) for name, country in existing_rows}
    added = []
    skipped = []

    for record in records:
        values = {key: value for key, value in record.items() if not key.startswith("_")}
        key = _identity(values["name"], values["country"])
        if key in existing:
            skipped.append(f"{values['name']} ({values['country']})")
            continue

        existing.add(key)
        item = Scholarship(
            **values,
            verification_status="unverified",
            verification_basis="not_verified",
            record_version=1,
        )
        db.add(item)
        db.flush()
        db.add(ScholarshipAuditLog(
            scholarship_id=item.id,
            action="imported",
            changes={"verification_status": [None, "unverified"]},
            note=f"Imported from {record['_import_source_file']}; manual official-source review is required.",
        ))
        added.append(item.name)

    db.commit()
    return added, skipped


def main(dry_run=False):
    records, duplicate_rows = load_import_records()
    if duplicate_rows:
        print(f"Duplicate workbook rows requiring manual resolution: {len(duplicate_rows)}")
        for duplicate in duplicate_rows:
            print(f"  {duplicate}")

    if dry_run:
        print(f"Validated {len(records)} unique scholarship records; no database was accessed.")
        return

    if duplicate_rows:
        raise SystemExit("Resolve duplicate workbook rows before importing.")

    with SessionLocal() as db:
        added, skipped = import_records(db, records)

    print(f"Added unverified: {len(added)} | Already existed: {len(skipped)}")
    for name in skipped:
        print(f"  Already exists: {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate and import scholarship workbooks.")
    parser.add_argument("--dry-run", action="store_true", help="Validate workbook records without connecting to the database.")
    main(dry_run=parser.parse_args().dry_run)
