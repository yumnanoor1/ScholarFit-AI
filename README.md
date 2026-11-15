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

Discovery runs in its own process; FastAPI never starts or owns the scheduler. From the repository root in PowerShell, enable it and start the independent scheduler with the existing backend environment:

```powershell
Set-Location .\backend
$env:SCHOLARSHIP_DISCOVERY_ENABLED = "true"
$env:SCHOLARSHIP_DISCOVERY_INTERVAL_HOURS = "24"
.\.venv\Scripts\python.exe .\run_scholarship_discovery_scheduler.py
```

Provide `GROQ_API_KEY` for primary requests and `GROQ_API_KEY_2` for fallback requests. Before enabling discovery, apply these additive migrations in order against the explicitly verified database:

```powershell
python .\migrate_scholarship_discovery.py --target-database <expected-database-name> --apply
python .\migrate_scholarship_discovery_review.py --target-database <expected-database-name> --apply
python .\migrate_scholarship_discovery_scheduler.py --target-database <expected-database-name> --apply
python .\migrate_scholarship_discovery_publications.py --target-database <expected-database-name> --apply
```

The first scheduler start runs one initial scheduled slot immediately. Thereafter the interval is measured from the recorded scheduled slot. On restart after missed slots, the scheduler performs at most one catch-up run for the most recent missed slot and skips older missed slots; the unique scheduled-slot index prevents duplicate history rows. Scheduled and manual runs share the same PostgreSQL session advisory lock. Startup stale-run reconciliation uses recovery-only mode and does not create a discovery run or enter the manual discovery path. Abrupt termination releases that lock when PostgreSQL closes the connection, but may leave a `running` record; a later locked run marks records older than `SCHOLARSHIP_DISCOVERY_STALE_RUN_TIMEOUT_HOURS` (12 hours by default) as failed, never successful. The timeout is configurable from 1 to 720 hours. An active discovery process retains the lock, so it cannot be marked stale by a concurrent scheduler.

The migrations create the run-history and incomplete-review tables, add scheduled-trigger metadata and a unique scheduled-slot index, then add the Admin-approved publication schema; existing run rows are retained and default to `manual`. Application startup deliberately excludes discovery tables from automatic DDL. All migrations use PostgreSQL transaction-scoped advisory locks to serialize migration execution; the locks do not enforce dependency order, so apply them in the order shown above. Each migration checks that the configured database matches the explicitly supplied expected database name; the publication migration also rejects partial or incompatible schemas. The API's Admin monitoring section reports configuration and database run history; enabled status reflects configuration, not proof that the separate scheduler process is alive.

`GROQ_MODEL` is shared by Discovery, Admin Import, and RAG; it defaults to `llama-3.3-70b-versatile` when unset. Groq requests use a 60-second timeout, an optional RPM cap, and a per-organization concurrency limit. `GROQ_MAX_REQUEST_TOKENS` (default 6,000; `0` disables) is the application's per-request estimated-token budget — `ceil((system instruction + prompt characters) / 3.2) + GROQ_MAX_COMPLETION_TOKENS + 32` — and oversized requests are reduced or split locally. It is distinct from the provider's organization-wide rolling TPM quota. `GROQ_TPM_LIMIT` (default 8,000) configures local organization TPM admission with a 90% safety ceiling; `GROQ_FALLBACK_TPM_LIMIT` inherits the primary TPM limit unless set. `GROQ_RPM_LIMIT` is optional (unset or 0 disables the primary cap); `GROQ_FALLBACK_RPM_LIMIT` inherits it when unset (0 disables the fallback cap). `GROQ_MAX_CONCURRENT_REQUESTS` defaults to 1, `GROQ_RATE_LIMIT_RETRIES` to 3, `GROQ_MAX_COMPLETION_TOKENS` to 2,048, and `GROQ_MAX_INPUT_CHARS` to 6,000. That default is chosen so a full chunk for *every* registered source fits inside the 6,000-token per-request budget once 2,048 completion tokens are reserved, and still leaves room for the linked-URL block; the prompt also carries the source name, source URL and registry host country, so the worst case is per-source. `test_chunk_chars_default_fits_inside_the_token_cap` enforces this against the real source registry and names the offending source if prompt growth ever breaks it. TPM/RPM accounting is separated only when distinct `GROQ_ORG_ID` and `GROQ_FALLBACK_ORG_ID` values are configured; a second API key does not grant a separate organization quota. HTTP 429 responses use provider retry/reset headers when available, apply a cooldown, and follow bounded retry and separate-organization fallback behavior. TPM usage reported in a 429 is incorporated into the rolling-window estimate before retries. A 429 naming a per-day limit (`TPD`/`RPD`) is classified `quota_exhausted` and is not retried, because that limit cannot reset inside a run; a rate-limit wait longer than the remaining run budget (or 120 seconds without a budget) is abandoned rather than slept out. Where Groq names the exhausted limit, only its label and integers (`limit_type`, `limit`, `used`, `requested`) are retained and logged; the provider message, which embeds the organization id, is never logged or persisted. `GROQ_API_KEY_2` is not used to evade a 429 without those distinct organization IDs. A credential returning HTTP 401 is skipped for the rest of the process; restart after correcting or rotating that key. Fallback can be disabled with `GROQ_FALLBACK_ENABLED=false`.

Quota reservations and provider-observed TPM usage are process-local and may reset on deploy. The repository Dockerfile starts one Uvicorn worker by default; multiple workers or application replicas would maintain independent counters and could collectively exceed the provider quota. Deployments using multiple processes or replicas, or sharing the organization with other applications, should use shared atomic rolling-window accounting (for example, Redis) before relying on these limits globally.

Scholarship Discovery, Admin Import, and RAG use Groq with `GROQ_API_KEY` as the primary key and `GROQ_API_KEY_2` as the fallback. Fallback is enabled by default. Provider diagnostics log only allowlisted error metadata, validated status codes, finish reasons, and token counts; provider messages, generated output, request IDs, prompts, and page content are never logged. Scholarship validation, evidence checks, Admin review, and publication controls are unchanged.

`SCHOLARSHIP_DISCOVERY_ENABLED` defaults to `false`; `SCHOLARSHIP_DISCOVERY_INTERVAL_HOURS` defaults to `24` (1–8760). Other optional settings are `SCHOLARSHIP_DISCOVERY_STALE_RUN_TIMEOUT_HOURS`, `SCHOLARSHIP_DISCOVERY_REQUEST_TIMEOUT_SECONDS`, `SCHOLARSHIP_DISCOVERY_MAX_RESPONSE_BYTES`, `SCHOLARSHIP_DISCOVERY_MAX_EXTRACTED_CHARS`, `SCHOLARSHIP_DISCOVERY_MIN_EXTRACTED_CHARS`, `SCHOLARSHIP_DISCOVERY_MAX_PAGES_PER_SOURCE`, `SCHOLARSHIP_DISCOVERY_MAX_RETRIES`, `SCHOLARSHIP_DISCOVERY_REQUEST_DELAY_SECONDS`, and `SCHOLARSHIP_DISCOVERY_USER_AGENT`. Extraction prompts deduplicate and prioritize source-domain links plus explicitly reviewed per-source external domains, bounded by `SCHOLARSHIP_DISCOVERY_MAX_LINKED_URLS` (100), `SCHOLARSHIP_DISCOVERY_MAX_LINKED_URL_CHARS` (2048 per URL), and `SCHOLARSHIP_DISCOVERY_MAX_LINKED_URL_BYTES` (16,384 total URL bytes). No external domains are currently configured because repository evidence does not establish a separate portal relationship for any source. User-info URLs are rejected; sensitive query parameters and fragments are removed from prompt and persisted reference URLs, while harmless query parameters are retained. Linked URLs are offered with the first chunk of a page only; later chunks and 413-recovery sub-chunks send an empty `linked_urls` list with `linked_urls_limited` set, because repeating the URL block in every chunk multiplied request tokens without adding evidence. Links are followed only to `SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH` (default 1 = links found on the root page; `0` = root page only, maximum 5), and queued links are ordered so per-source scholarship-entry patterns (for DAAD, `stipendium/datenbank` or `detail=<n>`) are fetched before generic relevant links, since only the first few pages of a source are fetched. `linked_urls_discovered` counts unique, safety-approved URLs; the raw href count is reported separately as `linked_url_references`.

The complete serialized Groq request body is capped by `SCHOLARSHIP_DISCOVERY_MAX_PROVIDER_REQUEST_BYTES` (512,000 bytes), and its estimated token count by `GROQ_MAX_REQUEST_TOKENS`. Offline tests compare the decoded Groq SDK request body to the estimator payload and assert a conservative wire-byte upper bound because the SDK uses compact JSON serialization. If needed, prompt reduction first removes the lowest-priority links while retaining relevant scholarship links, then duplicate normalized text lines while retaining their first verbatim copy; unique page evidence is never truncated, and a request that still exceeds either budget fails locally as `payload_too_large` with no HTTP status, after which the chunk is split locally and retried. **HTTP 413 from Groq is a per-request token limit, not a body-size limit:** the response carries `type: tokens` / `code: rate_limit_exceeded` and names the limit, for example `(TPM): Limit 8000, Requested 9965`, meaning one request asked for more tokens than the organization allows per minute. Waiting cannot make that request succeed, so a 413 is never retried unchanged and never backed off — the request is made smaller instead. When a 413 reports a `TPM` limit, the effective token cap for the rest of that extractor's run is lowered to 90% of the reported limit and the following split respects the new cap. Source fetch retries remain bounded by `SCHOLARSHIP_DISCOVERY_MAX_RETRIES`; whole runs are not replayed after partial persistence.

One failed page no longer stops its source: extraction continues with the remaining pages, and the source reports `pages_extracted`, `pages_failed`, `page_failures[]`, and `extraction_status` (`all_pages_failed` or `some_pages_failed`) while keeping `status = "partial_failure"`. A source is counted once in `sources_failed` however many of its pages fail. Credential, permission, missing-key, model-unavailable, quota (`quota_error`, `quota_exhausted`), and invalid-source-URL failures still stop the source immediately, since they would repeat on every page. Within a page, one failed chunk no longer discards candidates from chunks that succeeded (`partial_chunk_failure`, `failed_chunk_count`, `failed_chunk_categories`); if every chunk fails, the first error is raised unchanged. Publication source success is recorded only after a page is extracted, so a failed extraction is never reported as a fresh success; pages skipped for insufficient content still record success as before. More than 10 candidates on one page keeps the first 10 and counts the overflow as rejected with reason `candidate_limit_exceeded`, instead of failing the page as `malformed_response`. Candidate rejections are additionally reported per source as `candidate_rejection_details` using specific allowlisted codes such as `evidence_mismatch:<field>`, `out_of_scope:degree_level`, `invalid_value:<field>`, and `invalid_evidence_url:<kind>`. Evidence quotes are accepted when they match either the raw page text or the URL-redacted text the model was actually shown, because the prompt rewrites bare domains to `[redacted URL]` and strips `#fragments`; a quote absent from both is still rejected. `python .\discover_scholarships.py` remains available for a one-off manual run and uses the same lock and run history.

Every Admin/API manual run and direct `discover_scholarships.py` invocation is restricted server-side to `daad-helmut-schmidt`, `daad-epos`, `nl-scholarship`, `leiden-excellence`, `maastricht-nl-high-potential`, `radboud-scholarship`, `kth-scholarship`, `lund-university-scholarships`, `chalmers-scholarships`, `eiffel-scholarship`, `sciences-po-emile-boutmy`, `chevening-pakistan`, `commonwealth-masters`, `commonwealth-shared`, and `turkiye-burslari`. Before starting, the runner verifies that each registry entry exists exactly once, is crawl-enabled and trust-reviewed with a nonempty trust basis, and is not discovery-only; any mismatch aborts before crawling. The controlled manual profile caps a run at 45 page-fetch starts (3 per source), 300 HTTP attempts including robots requests, retries, and redirect hops, 100 provider attempts including both Groq keys, 100 persisted review candidates, and 30 minutes. Manual HTTP timeouts, response size, retries, extracted text, provider timeout, and linked-prompt/payload limits are capped at 15 seconds, 10 MB, 2 retries, 30,000 characters, 60 seconds, and the documented defaults respectively; larger environment values cannot raise these caps. A monotonic deadline is passed to network/provider timeouts; per-attempt invocation gates serialize cancellation against the actual synchronous HTTP/provider call, with cancellation of an already-started call waiting for that call's gate to release. For PostgreSQL manual runs using psycopg or psycopg2, the runner uses an unpooled connection with a connect timeout capped at 15 seconds, applies per-statement and lock-wait timeouts from the remaining budget, and registers cancellation for active queries and commits. Failure/finalization writes receive a separate best-effort five-second window. This is not a guaranteed hard 30-minute wall-clock bound: direct `run_discovery` callers may acquire a session connection before the database guard is attached, and driver cancellation, result fetching, commit acknowledgements, process pauses, and database unavailability can still extend elapsed time; non-PostgreSQL dialects do not receive these database-specific bounds. Any already committed candidates remain pending for Admin review; discovery does not publish or index them automatically. HTTPS-to-HTTP redirects are rejected for discovery and Admin imports. These manual-only limits do not change scheduled or catch-up source selection, settings, or the 24-hour interval.

Discovery uses static HTML extraction: it does not execute JavaScript, so content rendered only by JavaScript is not guaranteed to be extracted. Extraction prioritizes `main` and `article` text while retaining other non-boilerplate page text; navigation, headers, footers, scripts, styles, consent banners, and utility forms are excluded. A successful page fetch can still yield insufficient usable text; pages shorter than `SCHOLARSHIP_DISCOVERY_MIN_EXTRACTED_CHARS` (80 by default) are recorded as insufficient and are not sent to a provider. A valid empty extraction means the provider returned a valid response with no qualifying candidates from the submitted page; it does not establish that the website has no scholarships. Crawler URLs are canonicalized without fragments, harmless query parameters are retained, and URLs containing sensitive or signed query parameters are skipped rather than fetched. Run history reports discovered URLs, unique linked pages attempted (counted when the first page HTTP request starts; queued pages beyond the page limit are not attempted), fetched/failed/skipped counts, extraction outcomes, and per-page original/retained character lengths when text is truncated. Local request-preflight rejections are reported separately from provider errors. These diagnostics contain no page text or page URLs.

For a live, database-free diagnostic of one eligible source, run `python .\diagnose_single_source_extraction.py daad --confirm RUN_SINGLE_SOURCE_EXTRACTION_DIAGNOSTIC` from `backend`; the primary Groq key must already be configured in the process environment. It uses the production fetcher and Groq extractor, runs the source pages sequentially, and reports sanitized diagnostics only; it does not run the scheduler, connect to a database, or save candidates. This command makes real website and Groq requests, so run it only when those external requests are authorized. Never pass API keys on the command line.

There is no automated downgrade. To roll back, first stop the discovery job, verify a suitable database backup, and obtain explicit operator approval. Publication tables reference each other and contain append-only review history; do not remove them without a reviewed dependency-aware rollback plan. To remove the discovery review/run schema, drop `scholarship_discovery_review_items` before `scholarship_discovery_runs` because the review table references run history:

```sql
DROP TABLE scholarship_discovery_review_items;
-- Only when also rolling back run history:
DROP TABLE scholarship_discovery_runs;
```

Dropping `scholarship_discovery_review_items` permanently deletes candidate evidence, conflicts, and all Admin review decisions. Do not run these statements without the backup and explicit approval.

The checked-in registry in `backend/app/services/scholarship_discovery_sources.py` is intentionally curated, not an exhaustive catalogue of European awards. Add a source only after reviewing its official status, domain, crawl terms and relevant scholarship pages. The crawler stays on the registered official domain, honors `robots.txt`, and enforces public-host, redirect, timeout, response-size, page-count, retry and request-delay limits. HTML, JSON and text PDFs are supported; PDF text extraction uses PyMuPDF.

Newly registered sources remain inactive until their trust basis and domain have been reviewed. Registry entries do not establish Pakistan eligibility; eligibility is extracted only from source evidence and candidate publication still requires Admin review.

Admin approval of a discovery source authorizes crawling only; it does not verify Pakistan eligibility or approve any scholarship for student-facing publication.

Existing published NAWA scholarships are not guaranteed to be excluded for Pakistani students when nationality eligibility is unknown or missing; that requires a separate eligibility review.

Host country is validated against an explicit European-country list, never a URL suffix. Transcontinental hosts are accepted only in the configured European-side cities; ambiguous borders and listed disputed or overseas locations are rejected for manual review. Other countries/locations are not inferred. Applicant nationality is not restricted by European host geography; only source-stated eligibility is extracted. The registry includes an Erasmus Mundus discovery-only catalogue because the catalogue itself says that not every listed Master's programme offers a scholarship; a programme listing alone is not evidence that an award is available.

Extraction uses evidence from explicitly classified sources and leaves unknown fields unset. Every candidate, including complete, trusted-source, conflicting, and potential-duplicate results, remains in the Admin review queue. Only explicit Admin `accepted` or `link_and_publish` decisions create a publication: acceptance also creates a new canonical scholarship, which remains `unverified`; link-and-publish associates the candidate with a matching existing scholarship without changing its fields. The review queue's **Publish and link existing scholarship** action requires the canonical scholarship ID and preserves canonical fields. Ordinary duplicate resolution remains separate. Admins can open **Discovery Publications** from the discovery overview to inspect linked scholarship titles, publication status, approved values, evidence, source URLs/classifications, freshness, reviewer/decision details, version history, and lifecycle events. The page uses `GET /admin/scholarships/discovery-publications` and `/discovery-publications/{id}/events`; lifecycle changes use `POST /admin/scholarships/discovery-publications/{id}/lifecycle` with the backend-supported revoke, expire, withdraw, and supersede decisions. Discovery stores a private page snapshot with review evidence and updates freshness only for already-linked publication sources; it does not prepare RAG source documents before review. After explicit acceptance or link-and-publish, source-document preparation may create pending documents/versions, but never approves or indexes them. An Admin can approve or reject a document version through `POST /admin/scholarships/{scholarship_id}/documents/{version_id}/review`; approval requires a currently verified scholarship and a successful current source check. Pending versions are not searchable by RAG. Publication, scholarship verification, document approval, and indexing are independent decisions. Student scholarship list/search/detail, recommendations, eligibility, saved-list retrieval and scholarship feasibility now use the same visibility policy: currently published discoveries may appear as `unverified`, while pending or inactive discovery-associated records remain hidden and independently verified canonical scholarships remain visible after publication revocation. Existing saved rows are retained when a publication is revoked but omitted while the scholarship is no longer student-visible. Scholarship-specific saved expense inputs are also visibility-gated. When the publication tables are unavailable, student retrieval falls back to canonical scholarships only. RAG indexing/retrieval is unchanged. The JSON run output and durable run row include source outcomes and counts, while administrator verification, publication lifecycle changes, approval, and rejection remain explicit human actions.
