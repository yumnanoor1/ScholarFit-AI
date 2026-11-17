import unittest

from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert, select

from migrate_scholarship_record_versions import backfill_null_versions, count_null_versions


class ScholarshipRecordVersionBackfillTests(unittest.TestCase):
    def test_backfill_changes_only_null_versions_to_baseline_one(self):
        engine = create_engine("sqlite://")
        metadata = MetaData()
        scholarships = Table(
            "scholarships",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("record_version", Integer, nullable=True),
        )
        metadata.create_all(engine)

        with engine.begin() as connection:
            connection.execute(insert(scholarships), [
                {"id": 1, "record_version": None},
                {"id": 2, "record_version": 7},
            ])
            updated = backfill_null_versions(connection, scholarships)
            remaining = count_null_versions(connection, scholarships)
            versions = connection.execute(
                select(scholarships.c.id, scholarships.c.record_version).order_by(scholarships.c.id)
            ).all()

        self.assertEqual(updated, 1)
        self.assertEqual(remaining, 0)
        self.assertEqual(versions, [(1, 1), (2, 7)])


if __name__ == "__main__":
    unittest.main()
