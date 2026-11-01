from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import is_production, validate_settings
from app.core.cors import allowed_origins
from app.core.http_security import install_http_security
from app.database import Base, engine
from app import models  # noqa: F401
from app.routers import auth, profile, universities, programs, scholarships, saved_scholarships, eligibility, financial_feasibility, recommendations, admin_scholarships, assistant
# Unsafe production settings stop the API here, before anything else runs
validate_settings()

# Database tables create karo
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="FitScholar API",
    description="Backend for the FitScholar study abroad and scholarship system",
    version="1.0.0",
    # The API's own map stays private in production
    docs_url=None if is_production() else "/docs",
    redoc_url=None if is_production() else "/redoc",
    openapi_url=None if is_production() else "/openapi.json",
)

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
app.include_router(universities.router)
app.include_router(programs.router)
app.include_router(scholarships.router)
app.include_router(saved_scholarships.router)
app.include_router(eligibility.router)
app.include_router(financial_feasibility.router)
app.include_router(recommendations.router)
app.include_router(admin_scholarships.router)
app.include_router(assistant.router)


@app.get("/")
def home():
    return {"message": "FitScholar backend is running!"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}