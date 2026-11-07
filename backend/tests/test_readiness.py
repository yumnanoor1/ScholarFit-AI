import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.routers import health
from app.services.rag_service import RagUnavailable

MODEL_REVISION = "0123456789abcdef0123456789abcdef01234567"


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(health.router)
        app.state.scholarship_knowledge_schema_ready = True
        self.client = TestClient(app)

        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.connection.execute.return_value.scalar_one.return_value = 1

        self.engine = MagicMock()
        self.engine.connect.return_value = self.connection

        self.inspector = MagicMock()
        self.inspector.get_table_names.return_value = health.APPLICATION_TABLE_NAMES

    def request_ready(self):
        with (
            patch.object(health, "engine", self.engine),
            patch.object(health, "inspect", return_value=self.inspector),
            patch.object(health.rag_service, "get_model_revision", return_value=MODEL_REVISION),
        ):
            return self.client.get("/ready")

    def test_ready_when_all_checks_pass(self):
        with (
            patch.object(health, "engine", self.engine),
            patch.object(health, "inspect", return_value=self.inspector),
            patch.object(health.rag_service, "get_model_revision", return_value=MODEL_REVISION),
            patch.object(health.rag_service, "_load_model_with_revision") as load_model,
            patch.object(health.rag_service, "_gemini_client") as gemini_client,
        ):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
        load_model.assert_not_called()
        gemini_client.assert_not_called()

    def test_not_ready_when_database_is_unavailable(self):
        self.engine.connect.side_effect = SQLAlchemyError("sensitive database detail")

        response = self.request_ready()

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive database detail", response.text)

    def test_not_ready_when_knowledge_schema_is_not_ready(self):
        self.client.app.state.scholarship_knowledge_schema_ready = False

        response = self.request_ready()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Service is not ready"})

    def test_not_ready_when_application_tables_are_missing(self):
        self.inspector.get_table_names.return_value = set()

        response = self.request_ready()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Service is not ready"})

    def test_not_ready_when_model_revision_is_invalid(self):
        with (
            patch.object(health, "engine", self.engine),
            patch.object(health, "inspect", return_value=self.inspector),
            patch.object(
                health.rag_service,
                "get_model_revision",
                side_effect=RagUnavailable("invalid revision"),
            ),
        ):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("invalid revision", response.text)


if __name__ == "__main__":
    unittest.main()
