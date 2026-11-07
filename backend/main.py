from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import is_production, validate_settings
from app.core.cors import allowed_origins
from app.core.http_security import install_http_security
from app.database import create_application_schema, engine
from app import models  # noqa: F401
from app.routers import auth, profile, scholarships, saved_scholarships, eligibility, financial_feasibility, recommendations, admin_scholarships, assistant
from app.routers import health
from app.services.scholarship_knowledge_schema import schema_is_ready
# Unsafe production settings stop the API here, before anything else runs
validate_settings()

# Keep the vector tables out of startup DDL; their explicit migration checks pgvector first.
create_application_schema(bind=engine)

app = FastAPI(
    title="FitScholar API",
    description="Backend for the FitScholar study abroad and scholarship system",
    version="1.0.0",
    # The API's own map stays private in production
    docs_url=None if is_production() else "/docs",
    redoc_url=None if is_production() else "/redoc",
    openapi_url=None if is_production() else "/openapi.json",
)

with engine.connect() as connection:
    app.state.scholarship_knowledge_schema_ready = schema_is_ready(connection)

# Added first so it runs inside CORS, and error replies stay readable by the frontend
install_http_security(app)

# Sign-in uses a bearer token, never cookies, so credentials stay off
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Retry-After"],
)

# Routers include karo
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(scholarships.router)
app.include_router(saved_scholarships.router)
app.include_router(eligibility.router)
app.include_router(financial_feasibility.router)
app.include_router(recommendations.router)
app.include_router(admin_scholarships.router)
app.include_router(assistant.router)
app.include_router(health.router)


@app.get("/")
def home():
    return {"message": "FitScholar backend is running!"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}