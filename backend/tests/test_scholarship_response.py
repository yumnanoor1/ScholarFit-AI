import asyncio
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.permissions import require_complete_profile
from app.core.http_security import install_http_security
from app.database import get_db
from app.models.opportunity import Scholarship
from app.models.user import SavedScholarship
from app.routers import saved_scholarships, scholarships
from app.schemas.admin import AdminScholarship, AuditEntry
from app.schemas.eligibility import OpportunityEvaluation, RelatedOpportunity, ScholarshipEligibilityResult
from app.schemas.financial import ScholarshipSummary
from app.schemas.opportunity import SavedScholarshipResponse, ScholarshipCreate, ScholarshipResponse
from app.schemas.recommendation import ScholarshipRecommendation


LONG_COUNTRIES = (
    "European Union (multi-country, incl. hosted at institutions in France, Netherlands, and other EU states)",
    "European Union (multi-country, hosted across consortium institutions incl. France, Netherlands, and other member states)",
)
COUNTRY_VALUES = (*LONG_COUNTRIES, "Germany")


def call(app, path, query_string=b""):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(
        app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": query_string,
                "root_path": "",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("test", 80),
            },
            receive,
            send,
        )
    )

    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    return sent[0]["status"], json.loads(body)


class ScholarshipResponseTests(unittest.TestCase):
    def test_response_schema_preserves_long_and_normal_country_values(self):
        for country in COUNTRY_VALUES:
            with self.subTest(country=country):
                response = ScholarshipResponse.model_validate(
                    {"id": 1, "name": "Erasmus Mundus Joint Masters", "country": country}
                )
                self.assertEqual(response.country, country)

    def test_get_scholarships_returns_long_and_normal_country_values(self):
        records = [
            Scholarship(id=index, name=f"Scholarship {index}", country=country)
            for index, country in enumerate(COUNTRY_VALUES, start=1)
        ]

        class Query:
            def __init__(self, rows):
                self.rows = rows

            def filter(self, *_conditions):
                return self

            def order_by(self, *_ordering):
                return self

            def offset(self, _offset):
                return self

            def limit(self, _limit):
                return self

            def all(self):
                return self.rows

        class Session:
            def query(self, _model):
                return Query(records)

        app = FastAPI()
        app.include_router(scholarships.router)
        app.dependency_overrides[get_db] = Session
        status_code, response_body = call(
            app, "/scholarships/", b"include_unverified=true"
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(
            {record["country"] for record in response_body},
            set(COUNTRY_VALUES),
        )

    def test_public_list_and_detail_sanitize_unsafe_legacy_urls(self):
        unsafe_url = "https://student:FAKE-URL-CREDENTIAL-98765@official.example/page"
        record = Scholarship(
            id=3,
            name="Legacy Scholarship",
            country="Finland",
            official_url=unsafe_url,
            official_info_url="https://official.example/info?api_key=FAKE-QUERY-98765&lang=en",
            official_application_url="https://official.example/apply?round=2#application",
            additional_source_urls=[
                "https://official.example/guide?language=fi#section",
                unsafe_url,
                "ftp://official.example/invalid",
            ],
        )

        class Query:
            def filter(self, *_conditions):
                return self

            def order_by(self, *_ordering):
                return self

            def offset(self, _offset):
                return self

            def limit(self, _limit):
                return self

            def all(self):
                return [record]

            def first(self):
                return record

        class Session:
            def query(self, _model):
                return Query()

        app = FastAPI()
        app.include_router(scholarships.router)
        app.dependency_overrides[get_db] = Session
        list_status, listed = call(app, "/scholarships/", b"include_unverified=true")
        detail_status, detail = call(app, "/scholarships/3")

        self.assertEqual((list_status, detail_status), (200, 200))
        for body in (listed[0], detail):
            self.assertIsNone(body["official_url"])
            self.assertEqual(body["official_info_url"], "https://official.example/info?lang=en")
            self.assertEqual(body["official_application_url"], "https://official.example/apply?round=2")
            self.assertEqual(body["additional_source_urls"], ["https://official.example/guide?language=fi"])
        self.assertNotIn("FAKE-URL-CREDENTIAL-98765", str(listed) + str(detail))
        self.assertNotIn("FAKE-QUERY-98765", str(listed) + str(detail))

    def test_admin_and_independent_student_response_models_sanitize_legacy_urls(self):
        unsafe_url = "https://student:FAKE-URL-CREDENTIAL-98765@official.example/source"
        scholarship = AdminScholarship.model_validate(
            {
                "id": 1,
                "name": "Legacy Scholarship",
                "country": "Finland",
                "official_url": unsafe_url,
                "official_info_url": "https://official.example/info?token=FAKE-QUERY-98765&lang=en",
                "official_application_url": "https://official.example/apply#form",
                "additional_source_urls": [unsafe_url, "https://official.example/page?lang=en"],
                "source_checks": [{"url": unsafe_url}],
            }
        ).model_dump()
        self.assertIsNone(scholarship["official_url"])
        self.assertEqual(scholarship["official_info_url"], "https://official.example/info?lang=en")
        self.assertEqual(scholarship["official_application_url"], "https://official.example/apply")
        self.assertEqual(scholarship["additional_source_urls"], ["https://official.example/page?lang=en"])
        self.assertNotIn("FAKE-URL-CREDENTIAL-98765", str(scholarship))
        self.assertNotIn("FAKE-QUERY-98765", str(scholarship))

        audit = AuditEntry.model_construct(
            id=1,
            action="update",
            changes={"official_url": [unsafe_url, "https://official.example/next?api_key=FAKE-QUERY-98765"]},
            note=f"Imported from {unsafe_url}",
            actor_email=None,
            created_at=None,
        ).model_dump()
        self.assertNotIn("FAKE-URL-CREDENTIAL-98765", str(audit))
        self.assertNotIn("FAKE-QUERY-98765", str(audit))

        recommendation = ScholarshipRecommendation.model_construct(official_url=unsafe_url).model_dump()
        eligibility = ScholarshipEligibilityResult.model_construct(official_url=unsafe_url).model_dump()
        related = RelatedOpportunity.model_construct(source_url=unsafe_url).model_dump()
        evaluation = OpportunityEvaluation.model_construct(source_url=unsafe_url).model_dump()
        financial = ScholarshipSummary.model_construct(source_url=unsafe_url).model_dump()
        for response in (recommendation, eligibility, related, evaluation, financial):
            url_field = "official_url" if "official_url" in response else "source_url"
            self.assertIsNone(response[url_field])

    def test_validation_error_does_not_echo_credentials_or_log_them(self):
        app = FastAPI()
        install_http_security(app)

        @app.post("/scholarships")
        def create_scholarship(payload: ScholarshipCreate):
            return payload

        secret = "FAKE-URL-CREDENTIAL-98765"
        with patch("app.core.http_security.logger.error") as error_log, \
                patch("app.core.http_security.logger.exception") as exception_log:
            response = TestClient(app).post(
                "/scholarships",
                json={
                    "name": "Legacy Scholarship",
                    "country": "Finland",
                    "official_url": f"https://student:{secret}@official.example/source",
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)
        self.assertNotIn("input", response.json()["detail"][0])
        error_log.assert_not_called()
        exception_log.assert_not_called()

    def test_saved_scholarship_refresh_serializes_long_country_values(self):
        records = [
            SimpleNamespace(
                id=index,
                scholarship_id=index,
                saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                scholarship=Scholarship(
                    id=index, name=f"Scholarship {index}", country=country
                ),
            )
            for index, country in enumerate(LONG_COUNTRIES, start=1)
        ]

        class Query:
            def options(self, *_options):
                return self

            def filter(self, *_conditions):
                return self

            def order_by(self, *_ordering):
                return self

            def all(self):
                return records

        class Session:
            def query(self, model):
                if model is SavedScholarship:
                    return Query()
                raise AssertionError(f"Unexpected query model: {model}")

        app = FastAPI()
        app.include_router(saved_scholarships.router)
        app.dependency_overrides[get_db] = Session
        app.dependency_overrides[require_complete_profile] = lambda: SimpleNamespace(id=7)
        status_code, response_body = call(app, "/saved-scholarships/")

        self.assertEqual(status_code, 200)
        self.assertEqual(
            {record["scholarship"]["country"] for record in response_body},
            set(LONG_COUNTRIES),
        )
