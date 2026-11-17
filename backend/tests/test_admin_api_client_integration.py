import os
import secrets
import socket
import subprocess
import threading
import time
import unittest
from pathlib import Path

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = secrets.token_urlsafe(64)

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import issue_session_token
from app.database import Base, get_db
from app.models.user import User
from app.routers import admin_scholarships, scholarships


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NODE_TEST = PROJECT_ROOT / "src" / "services" / "adminApi.integration.test.js"


class AdminApiClientIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

        with self.session_factory() as session:
            admin = User(
                email="integration-admin@example.invalid",
                hashed_password="integration-test-only",
                full_name="Integration Admin",
                role="admin",
            )
            student = User(
                email="integration-student@example.invalid",
                hashed_password="integration-test-only",
                full_name="Integration Student",
                role="student",
            )
            session.add_all([admin, student])
            session.commit()
            admin_token = issue_session_token(admin)
            student_token = issue_session_token(student)

        self.server_error_token = secrets.token_urlsafe(32)
        self.app = FastAPI()

        @self.app.middleware("http")
        async def test_server_failure(request, call_next):
            if request.headers.get("authorization") == f"Bearer {self.server_error_token}":
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Test server unavailable"},
                )
            return await call_next(request)

        def test_get_db():
            with self.session_factory() as session:
                yield session

        self.app.dependency_overrides[get_db] = test_get_db
        self.app.include_router(scholarships.router)
        self.app.include_router(admin_scholarships.router)

        self.admin_token = admin_token
        self.student_token = student_token
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", 0))
        self.server_socket.listen()
        self.port = self.server_socket.getsockname()[1]

        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                log_level="critical",
                access_log=False,
                lifespan="off",
            )
        )
        self.server_thread = threading.Thread(
            target=self.server.run,
            kwargs={"sockets": [self.server_socket]},
            daemon=True,
        )
        self.server_thread.start()

        deadline = time.monotonic() + 10
        while not self.server.started and self.server_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.server.started:
            self.stop_server()
            self.fail("The isolated FastAPI test server did not start.")

    def tearDown(self):
        self.stop_server()
        self.engine.dispose()

    def stop_server(self):
        if getattr(self, "server", None) is not None:
            self.server.should_exit = True
        if getattr(self, "server_thread", None) is not None:
            self.server_thread.join(timeout=10)
        if getattr(self, "server_socket", None) is not None:
            self.server_socket.close()

    def test_javascript_admin_client_against_fastapi_over_loopback(self):
        api_url = f"http://127.0.0.1:{self.port}"
        node_environment = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
            if key in os.environ
        }
        node_environment.update(
            {
                "VITE_API_BASE_URL": api_url,
                "ADMIN_API_INTEGRATION_URL": api_url,
                "ADMIN_API_ADMIN_TOKEN": self.admin_token,
                "ADMIN_API_STUDENT_TOKEN": self.student_token,
                "ADMIN_API_SERVER_ERROR_TOKEN": self.server_error_token,
            }
        )
        result = subprocess.run(
            ["node", "--test", str(NODE_TEST)],
            cwd=PROJECT_ROOT,
            env=node_environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertIn("pass 8", result.stdout)
        self.assertIn("fail 0", result.stdout)
        self.assertIn("skipped 0", result.stdout)
        self.assertEqual(
            result.returncode,
            0,
            f"Node integration test failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
