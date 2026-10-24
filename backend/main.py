from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app import models  # noqa: F401
from app.routers import auth, profile, universities, programs, scholarships, eligibility

# Database tables create karo
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="FitScholar API",
    description="Backend for the FitScholar study abroad and scholarship system",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers include karo
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(universities.router)
app.include_router(programs.router)
app.include_router(scholarships.router)
app.include_router(eligibility.router)


@app.get("/")
def home():
    return {"message": "FitScholar backend is running!"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}