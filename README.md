# FitScholar AI

FitScholar AI is a React/Vite student application backed by a FastAPI API and a SQL database.

## Requirements

- Python 3.12.10 (the backend test environment used for this audit)
- Node.js 20.19+ or 22.12+ (required by Vite 8)
- A PostgreSQL database for local or deployed API use

## Configuration

1. Copy `.env.example` to `.env`.
2. Copy `backend/.env.example` to `backend/.env`.
3. Configure `VITE_API_BASE_URL` to the backend URL. Development falls back to `http://127.0.0.1:8000`; production builds require a real HTTPS backend URL and reject missing, local, or example URLs.
4. Set `VITE_GOOGLE_CLIENT_ID` in the frontend and the matching `GOOGLE_CLIENT_ID` in the backend. The frontend value is public; do not put a Google client secret in it.
5. Set the backend database URL and other required values for the intended environment. Never point development or tests at a shared or production database.

**Database caution:** `backend/main.py` runs `Base.metadata.create_all()` during startup and can create missing tables. The Google sign-in integration also requires the nullable `users.google_sub` column and its unique index; `backend/migrate_google_accounts.py` documents the separately controlled migration. Verify the database and schema target before starting the API, and do not run migrations without approval.

## Local development

Install frontend dependencies from the repository root:

```powershell
npm install
npm run dev
```

In another terminal, install and start the backend using a verified local database:

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

## Tests and checks

From the repository root:

```powershell
node --test src\services\*.test.js
npm run lint
npm run build
```

From `backend`:

```powershell
python -m unittest discover -s tests -v
```

Backend tests use isolated in-memory SQLite fixtures. Integration or browser tests that require credentials or a persistent database must use an explicitly verified test environment.
