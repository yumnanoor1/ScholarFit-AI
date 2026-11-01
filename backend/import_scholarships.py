import glob
import pandas as pd

from app.database import get_db
from app.models.opportunity import Scholarship

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


def clean(value):
    """Empty cells ko None banao, baaqi sab ko text"""
    if pd.isna(value):
        return None
    return str(value).strip()


def is_unverified(row):
    """Agar key fields mein 'Not verified' ya secondary-source likha ho"""
    check = " ".join(
        str(row.get(f) or "")
        for f in ["pakistan_eligible", "last_verified", "min_academic_requirement", "deadline"]
    ).lower()
    return "not verified" in check or "secondary-source" in check


def main():
    frames = []
    for path in sorted(glob.glob("data/*.xlsx")):
        df = pd.read_excel(path)
        print(f"Read {len(df)} rows from {path}")
        frames.append(df)

    data = pd.concat(frames, ignore_index=True)
    data = data.rename(columns=COLUMN_MAP)
    data = data[list(COLUMN_MAP.values())]

    # Duplicate hatao (same name + country), naya wala rakho
    before = len(data)
    data["_key"] = data["name"].str.lower().str.strip() + "|" + data["country"].str.lower().str.strip()
    data = data.drop_duplicates(subset="_key", keep="last").drop(columns="_key")
    print(f"Duplicates removed: {before - len(data)}")

    db = next(get_db())
    added = skipped = unverified = 0

    for _, r in data.iterrows():
        row = {col: clean(r[col]) for col in COLUMN_MAP.values()}

        exists = (
            db.query(Scholarship)
            .filter(Scholarship.name == row["name"], Scholarship.country == row["country"])
            .first()
        )
        if exists:
            skipped += 1
            continue

        row["verification_status"] = "unverified" if is_unverified(row) else "verified"
        if row["verification_status"] == "unverified":
            unverified += 1

        db.add(Scholarship(**row))
        added += 1

    db.commit()
    print(f"Added: {added} | Already existed: {skipped} | Marked unverified: {unverified}")


if __name__ == "__main__":
    main()