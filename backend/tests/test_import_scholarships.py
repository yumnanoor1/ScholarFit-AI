import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.opportunity import Scholarship, ScholarshipAuditLog
from import_scholarships import import_records, load_import_records, main


def workbook_row(**overrides):
    row = {
        "Country": "Germany",
        "Scholarship Name": "Test Scholarship",
        "Official Scholarship URL": "https://official.example.org/info",
    }
    row.update(overrides)
    return row


class ImportValidationTests(unittest.TestCase):
    def test_splits_source_links_and_does_not_treat_imported_note_as_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.xlsx"
            pd.DataFrame([workbook_row(
                **{
                    "Official Scholarship URL": (
                        "https://official.example.org/info | partner page: "
                        "https://partner.example.org/award"
                    ),
                    "Last Verified Date": "Not verified",
                }
            )]).to_excel(path, index=False)

            records, duplicates = load_import_records(directory)

        self.assertEqual(duplicates, [])
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["official_info_url"], "https://official.example.org/info")
        self.assertEqual(record["additional_source_urls"], ["https://partner.example.org/award"])
        self.assertEqual(record["last_verified"], None)
        self.assertIn("Not verified", record["verification_notes"])

    def test_duplicate_rows_keep_the_first_and_report_both_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            pd.DataFrame([workbook_row(**{"Study Type": "Old wording"})]).to_excel(
                Path(directory) / "a.xlsx", index=False,
            )
            pd.DataFrame([workbook_row(**{"Scholarship Name": "  TEST SCHOLARSHIP  ", "Study Type": "Updated wording"})]).to_excel(
                Path(directory) / "b.xlsx", index=False,
            )

            records, duplicates = load_import_records(directory)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["study_type"], "Old wording")
        self.assertEqual(
            duplicates,
            ["b.xlsx row 2: TEST SCHOLARSHIP (Germany) duplicates a.xlsx row 2"],
        )

    def test_import_stops_before_database_access_when_duplicates_need_resolution(self):
        duplicate = "b.xlsx row 2: Test Scholarship (Germany) duplicates a.xlsx row 2"
        with patch("import_scholarships.load_import_records", return_value=([], [duplicate])):
            with patch("import_scholarships.SessionLocal") as session_factory:
                with self.assertRaisesRegex(SystemExit, "Resolve duplicate workbook rows"):
                    main()

        session_factory.assert_not_called()

    def test_invalid_required_fields_fail_with_workbook_and_row(self):
        with tempfile.TemporaryDirectory() as directory:
            pd.DataFrame([workbook_row(**{"Scholarship Name": ""})]).to_excel(
                Path(directory) / "bad.xlsx", index=False,
            )

            with self.assertRaisesRegex(ValueError, r"bad\.xlsx row 2: Scholarship Name"):
                load_import_records(directory)

    def test_invalid_source_url_fails_with_workbook_and_row(self):
        with tempfile.TemporaryDirectory() as directory:
            pd.DataFrame([workbook_row(**{"Official Scholarship URL": "https://"})]).to_excel(
                Path(directory) / "bad.xlsx", index=False,
            )

            with self.assertRaisesRegex(ValueError, r"bad\.xlsx row 2: Invalid source URL"):
                load_import_records(directory)

    def test_missing_workbook_headers_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            pd.DataFrame([{"Scholarship Name": "Test Scholarship"}]).to_excel(
                Path(directory) / "bad.xlsx", index=False,
            )

            with self.assertRaisesRegex(ValueError, r"bad\.xlsx: missing required columns: Country"):
                load_import_records(directory)

    def test_database_import_stays_unverified_and_is_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            pd.DataFrame([workbook_row(**{"Last Verified Date": "2026-10-01"})]).to_excel(
                Path(directory) / "sources.xlsx", index=False,
            )
            records, _ = load_import_records(directory)

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine)()
        self.addCleanup(session.close)
        added, skipped = import_records(session, records)

        self.assertEqual((added, skipped), (["Test Scholarship"], []))
        record = session.query(Scholarship).one()
        self.assertEqual((record.verification_status, record.verification_basis), ("unverified", "not_verified"))
        self.assertEqual(record.record_version, 1)
        self.assertEqual(record.official_info_url, "https://official.example.org/info")
        self.assertEqual(record.last_verified, "2026-10-01")
        self.assertIsNone(record.last_verified_date)
        audit = session.query(ScholarshipAuditLog).one()
        self.assertEqual(audit.action, "imported")
        self.assertIn("manual official-source review is required", audit.note)

        added, skipped = import_records(session, records)
        self.assertEqual((added, skipped), ([], ["Test Scholarship (Germany)"]))
        self.assertEqual(session.query(Scholarship).count(), 1)


if __name__ == "__main__":
    unittest.main()
