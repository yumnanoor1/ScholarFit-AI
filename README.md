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

## Scholarship discovery (optional)

Discovery is an external, single-process daily job; the API does not start a background scheduler. From `backend`, run `python discover_scholarships.py` once per day under the deployment's scheduler. Set `SCHOLARSHIP_DISCOVERY_ENABLED=true`, provide the existing `GEMINI_API_KEY` for evidence-bound extraction, and apply the discovery run-history table migration once:

```powershell
python migrate_scholarship_discovery.py --target-database <expected-database-name> --apply
```

The migration adds only `scholarship_discovery_runs`; it does not change scholarship or knowledge records. Application startup deliberately excludes this table from automatic DDL. Other optional settings are `SCHOLARSHIP_DISCOVERY_MODEL`, `SCHOLARSHIP_DISCOVERY_REQUEST_TIMEOUT_SECONDS`, `SCHOLARSHIP_DISCOVERY_MAX_RESPONSE_BYTES`, `SCHOLARSHIP_DISCOVERY_MAX_EXTRACTED_CHARS`, `SCHOLARSHIP_DISCOVERY_MAX_PAGES_PER_SOURCE`, `SCHOLARSHIP_DISCOVERY_MAX_RETRIES`, `SCHOLARSHIP_DISCOVERY_REQUEST_DELAY_SECONDS`, and `SCHOLARSHIP_DISCOVERY_USER_AGENT`. Review `scholarship_discovery_settings()` for defaults and limits. Do not schedule multiple copies of the job concurrently.

The checked-in registry in `backend/app/services/scholarship_discovery_sources.py` is intentionally curated, not an exhaustive catalogue of European awards. Add a source only after reviewing its official status, domain, crawl terms and relevant scholarship pages. The crawler stays on the registered official domain, honors `robots.txt`, and enforces public-host, redirect, timeout, response-size, page-count, retry and request-delay limits. HTML, JSON and text PDFs are supported; PDF text extraction uses PyMuPDF.

Host country is validated against an explicit European-country list, never a URL suffix. Transcontinental hosts are accepted only in the configured European-side cities; ambiguous borders and listed disputed or overseas locations are rejected for manual review. Other countries/locations are not inferred. Applicant nationality is not restricted by European host geography; only source-stated eligibility is extracted. The registry includes an Erasmus Mundus discovery-only catalogue because the catalogue itself says that not every listed Master's programme offers a scholarship; a programme listing alone is not evidence that an award is available.

Extraction uses only exact quotes from fetched official pages as evidence and leaves unknown fields unset. New scholarship records always remain `unverified` and use the `system:scholarship-discovery` audit actor. Discovery registers official source documents, but creates immutable pending document versions only after the scholarship has separately passed human official-source verification. It creates no chunks, approvals or embeddings. A document-version approval endpoint is not present in this codebase and remains a separate Part 2 task; pending versions are not searchable by RAG. The JSON run output and durable run row include source outcomes and counts, while administrator verification, approval and rejection remain human actions.
