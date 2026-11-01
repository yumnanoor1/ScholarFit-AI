import {
  getAcademicSummary,
  getAudienceSummary,
  getCoverageSummary,
  getDeadlineRows,
  getEnglishSummary,
  getFundingRows,
  getOfficialLinks,
  getRequirementRows,
  getVerificationText,
} from './scholarshipDisplay.js';

// Optional chaining lets the pure mapping helpers below run under `node --test`
const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

function extractErrorMessage(data, fallback = 'Request failed') {
  if (!data) return fallback;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    const first = data.detail[0];
    return first?.msg || fallback;
  }
  if (typeof data.message === 'string') return data.message;
  return fallback;
}

// ---------------------------------------------------------------------------
// Field Mapping Helper
// ---------------------------------------------------------------------------

/**
 * Maps a backend ProgramResponse + UniversityResponse to the shape
 * expected by Universities.jsx program cards.
 *
 * Backend program fields:
 *   id, university_id, name, degree_level, field_of_study, duration_months,
 *   tuition_usd_per_year, living_cost_usd_per_year, min_cgpa, min_ielts,
 *   min_toefl, required_degree, application_deadline, description, source_url
 *
 * Backend university fields:
 *   id, name, country, city, ranking, website, description
 */
/** "€12,000" / "SEK 192,500" style amount, or null when unknown. */
export function formatMoney(amount, currency) {
  if (amount == null || !currency) return null;
  try {
    return new Intl.NumberFormat('en', { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount);
  } catch {
    return `${currency} ${Math.round(amount).toLocaleString()}`;
  }
}

export function mapProgramToFrontend(program, university) {
  const tuition =
    program.tuition_usd_per_year != null
      ? `$${Number(program.tuition_usd_per_year).toLocaleString()} / year`
      : null;

  let englishReq = null;
  if (program.min_ielts != null && program.min_toefl != null) {
    englishReq = `IELTS ${program.min_ielts} / TOEFL ${program.min_toefl}`;
  } else if (program.min_ielts != null) {
    englishReq = `IELTS ${program.min_ielts}`;
  } else if (program.min_toefl != null) {
    englishReq = `TOEFL ${program.min_toefl}`;
  }

  return {
    // IDs kept as strings to match existing ProfileContext save/compare logic
    id: String(program.id),
    _numericId: program.id,

    // Core program fields
    program: program.name,
    degree: program.degree_level || null,
    fieldOfStudy: program.field_of_study || null,
    description: program.description || null,
    sourceUrl: program.source_url || null,

    // University identity (joined)
    university: university?.name || 'University not listed',
    country: university?.country || null,
    city: university?.city || null,
    universityWebsite: university?.website || null,

    // Cost & timeline
    tuition: tuition,
    duration: program.duration_months ? `${program.duration_months} months` : null,
    deadline: program.application_deadline || null,

    // Raw values for the list and detail pages
    tuitionUsd: program.tuition_usd_per_year ?? null,
    tuitionAmount: program.tuition_amount ?? null,
    tuitionCurrency: program.tuition_currency || null,
    tuitionOriginal: program.tuition_amount === 0 ? 'No tuition fee' : formatMoney(program.tuition_amount, program.tuition_currency),
    durationMonths: program.duration_months ?? null,
    language: program.language_of_instruction || null,
    lastVerified: program.last_verified || null,
    minCgpa: program.min_cgpa ?? null,
    minIelts: program.min_ielts ?? null,
    minToefl: program.min_toefl ?? null,

    // Requirements
    cgpaReq: program.min_cgpa != null ? String(program.min_cgpa) : null,
    englishReq: englishReq,
    requiredDegree: program.required_degree || null,

    // Match score — not computed by this integration step
    matchScore: null,

    // Indicate data came from real backend (not mock)
    sourceStatus: 'live-backend',
    requiredDocuments: [],
    applicationUrl: null,
    applicationUrlStatus: 'unavailable',

    kind: 'program',
  };
}

// ---------------------------------------------------------------------------
// API Calls
// ---------------------------------------------------------------------------

/**
 * Fetch all universities with optional filters.
 * GET /universities/?country=&search=&skip=&limit=
 */
export async function fetchUniversities({ country, search, skip = 0, limit = 100 } = {}) {
  const params = new URLSearchParams();
  if (country) params.set('country', country);
  if (search) params.set('search', search);
  params.set('skip', String(skip));
  params.set('limit', String(limit));

  const response = await fetch(`${API_BASE_URL}/universities/?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch universities (${response.status})`);
  }
  return response.json(); // UniversityResponse[]
}

/**
 * Fetch a single university by its numeric ID.
 * GET /universities/{id}
 * Returns null (not a throw) on 404 so callers can handle missing gracefully.
 */
export async function fetchUniversityById(id) {
  const response = await fetch(`${API_BASE_URL}/universities/${id}`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Failed to fetch university ${id} (${response.status})`);
  }
  return response.json(); // UniversityResponse
}

/**
 * Fetch all programs with optional filters.
 * GET /programs/?country=&field_of_study=&degree_level=&max_tuition=&search=&skip=&limit=
 */
export async function fetchPrograms({
  country,
  field_of_study,
  degree_level,
  max_tuition,
  deadline_before,
  university_id,
  search,
  skip = 0,
  limit = 100,
} = {}) {
  const params = new URLSearchParams();
  if (country) params.set('country', country);
  if (field_of_study) params.set('field_of_study', field_of_study);
  if (degree_level) params.set('degree_level', degree_level);
  if (max_tuition != null) params.set('max_tuition', String(max_tuition));
  if (deadline_before) params.set('deadline_before', deadline_before);
  if (university_id != null) params.set('university_id', String(university_id));
  if (search) params.set('search', search);
  params.set('skip', String(skip));
  params.set('limit', String(limit));

  const response = await fetch(`${API_BASE_URL}/programs/?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch programs (${response.status})`);
  }
  return response.json(); // ProgramResponse[]
}

/**
 * Fetch a single program by its numeric ID, then joins its university.
 * Returns { program: ProgramResponse, university: UniversityResponse|null }
 * Returns null on 404.
 */
export async function fetchProgramById(id) {
  const numericId = Number(id);
  if (!Number.isFinite(numericId)) return null;

  const response = await fetch(`${API_BASE_URL}/programs/${numericId}`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Failed to fetch program ${numericId} (${response.status})`);
  }
  const program = await response.json(); // ProgramResponse

  // Join university to get name/country for the detail page
  const university = await fetchUniversityById(program.university_id);

  return { program, university };
}

/**
 * Fetches all programs and all universities, joins them, and returns
 * an array of frontend-mapped program objects ready for Universities.jsx.
 *
 * If the database is empty this returns [] — the UI handles that with its
 * existing "No programs match these filters" empty state.
 */
export async function fetchMappedPrograms(filters = {}) {
  const [programs, universities] = await Promise.all([
    fetchPrograms(filters),
    fetchUniversities(),
  ]);

  // Build a lookup map so joining is O(1) per program
  const universityMap = Object.fromEntries(universities.map((u) => [u.id, u]));

  return programs.map((p) => mapProgramToFrontend(p, universityMap[p.university_id] || null));
}

// ---------------------------------------------------------------------------
// Scholarships
// ---------------------------------------------------------------------------

// Frontend IDs for backend scholarships. The "sch-" prefix is how the app tells
// scholarships from programs; "db-" keeps them apart from the old mock IDs (sch-1…).
const SCHOLARSHIP_ID_PREFIX = 'sch-db-';

export function toScholarshipId(numericId) {
  return `${SCHOLARSHIP_ID_PREFIX}${numericId}`;
}

/** Numeric backend ID for a frontend scholarship ID, or null if it isn't one. */
export function parseScholarshipId(id) {
  const match = String(id ?? '').match(/^sch-db-(\d+)$/);
  return match ? Number(match[1]) : null;
}

// Spreadsheet text such as "No / Not specified" means the benefit isn't offered or listed
function listedValue(value) {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text || /^(no|n\/a|none|not specified)\b/i.test(text)) return null;
  return text;
}

/** First http(s) URL in a field that may hold several ("a ; b | c"). */
function firstUrl(value) {
  const match = String(value ?? '').match(/https?:\/\/[^\s;|,]+/i);
  return match ? match[0] : null;
}

/**
 * Maps a backend ScholarshipResponse to the shape the scholarship pages use.
 * Match scores are not computed by the backend, so matchScore stays null.
 */
export function mapScholarshipToFrontend(item) {
  const verified = item.verification_status === 'verified';
  const structured = Boolean(item.structured_data_version);
  // Structured records name their own links, so a home page or example link isn't offered as the application
  const officialUrl = structured
    ? item.official_application_url || item.official_info_url || null
    : firstUrl(item.official_url);
  const benefits = [
    ['Tuition', listedValue(item.tuition_coverage)],
    ['Living stipend', listedValue(item.living_stipend)],
    ['Travel / airfare', listedValue(item.travel_airfare)],
    ['Accommodation', listedValue(item.accommodation)],
    ['Health insurance', listedValue(item.health_insurance)],
    ['Visa support', listedValue(item.visa_support)],
    ['Other benefits', listedValue(item.other_benefits)],
  ].filter(([, value]) => value).map(([label, value]) => ({ label, value }));

  return {
    id: toScholarshipId(item.id),
    _numericId: item.id,
    kind: 'scholarship',

    name: item.name,
    title: item.name,
    provider: item.provider || null,
    country: item.country || null,
    type: item.funding_type || null,
    degree: item.degree_level || null,
    studyType: item.study_type || null,

    coverage: listedValue(item.tuition_coverage) || item.funding_type || null,
    coverageSummary: getCoverageSummary(item),
    fundingRows: getFundingRows(item),
    requirementSummaryRows: getRequirementRows(item),
    deadlineRows: getDeadlineRows(item),
    officialLinks: getOfficialLinks(item),
    academicSummary: structured ? getAcademicSummary(item) : null,
    englishSummary: structured ? getEnglishSummary(item) : null,
    audienceSummary: structured ? getAudienceSummary(item) : null,
    verificationText: getVerificationText(item),
    verificationNotes: item.verification_notes || null,
    duplicateOf: item.duplicate_of_id ? toScholarshipId(item.duplicate_of_id) : null,
    deadlineDate: item.application_deadline_date || null,
    benefits,
    duration: item.duration || null,
    deadline: item.deadline || null,

    eligibleNationalities: item.eligible_nationalities || null,
    pakistanEligible: item.pakistan_eligible || null,
    eligibleFields: item.eligible_fields || null,
    academicRequirement: item.min_academic_requirement || null,
    bachelorsRequirement: item.bachelors_requirement || null,
    englishRequirement: item.english_requirement || null,
    workExperience: item.work_experience || null,
    ageRequirement: item.age_requirement || null,

    applicationMethod: item.application_method || null,
    admissionRequired: item.admission_required || null,
    nominationRequired: item.nomination_required || null,
    requiredDocumentsText: item.required_documents || null,
    applicationPathwayText: item.application_pathway || null,
    notes: item.notes || null,

    sourceName: item.source_name || null,
    sourceUrl: officialUrl,
    lastVerified: item.last_verified || null,
    verificationStatus: item.verification_status || null,
    archived: Boolean(item.archived),

    // Records the backend marks verified were checked against their official source
    sourceStatus: verified ? 'official-verified' : 'unverified',
    deadlineStatus: verified ? 'official-verified' : 'unverified',
    applicationUrl: officialUrl,
    applicationUrlStatus: verified && officialUrl ? 'official-verified' : 'unavailable',

    matchScore: null,
    requiredDocuments: mapRequiredDocuments(item.required_documents_list, verified),
  };
}

/** The record's document list. IDs come from the name, so one upload counts wherever that document is required. */
function mapRequiredDocuments(names, verified) {
  return (Array.isArray(names) ? names : [])
    .filter((name) => typeof name === 'string' && name.trim())
    .map((name) => ({
      id: name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''),
      name: name.trim(),
      sourceStatus: verified ? 'official-verified' : 'unverified',
    }));
}

/**
 * Fetch scholarships. Only verified records unless include_unverified is set.
 * GET /scholarships/?country=&funding_type=&degree_level=&search=&skip=&limit=
 */
export async function fetchScholarships({
  country,
  funding_type,
  degree_level,
  search,
  include_unverified = false,
  skip = 0,
  limit = 100,
} = {}) {
  const params = new URLSearchParams();
  if (country) params.set('country', country);
  if (funding_type) params.set('funding_type', funding_type);
  if (degree_level) params.set('degree_level', degree_level);
  if (search) params.set('search', search);
  if (include_unverified) params.set('include_unverified', 'true');
  params.set('skip', String(skip));
  params.set('limit', String(limit));

  const response = await fetch(`${API_BASE_URL}/scholarships/?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch scholarships (${response.status})`);
  }
  return response.json(); // ScholarshipResponse[]
}

/**
 * Fetch one scholarship by frontend ID ("sch-db-12").
 * GET /scholarships/{id}
 * Returns null for unknown IDs and on 404.
 */
export async function fetchScholarshipById(id) {
  const numericId = parseScholarshipId(id);
  if (numericId == null) return null;

  const response = await fetch(`${API_BASE_URL}/scholarships/${numericId}`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Failed to fetch scholarship ${numericId} (${response.status})`);
  }
  return response.json(); // ScholarshipResponse
}

/**
 * Search and filters for Explore. GET /scholarships/search?... -> ScholarshipSearchResult
 * The token is sent when there is one, so personal results stay the signed-in student's own.
 */
export async function fetchScholarshipSearch(query, token) {
  const response = await fetch(`${API_BASE_URL}/scholarships/search?${query}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new Error(`Failed to search scholarships (${response.status})`);
  return response.json();
}

/** GET /scholarships/filter-options -> the choices the data supports. */
export async function fetchScholarshipFilterOptions() {
  const response = await fetch(`${API_BASE_URL}/scholarships/filter-options`);
  if (!response.ok) throw new Error(`Failed to load filter options (${response.status})`);
  return response.json();
}

/** All verified scholarships, mapped for the frontend. */
export async function fetchMappedScholarships(filters = {}) {
  const scholarships = await fetchScholarships(filters);
  return scholarships.map(mapScholarshipToFrontend);
}

// ---------------------------------------------------------------------------
// Eligibility (authenticated)
// ---------------------------------------------------------------------------

// Backend overall status -> frontend status used by the pages
const ELIGIBILITY_STATUS_MAP = {
  eligible: 'satisfied',
  'not-eligible': 'not-satisfied',
  'missing-information': 'missing-information',
  'not-evaluated': 'awaiting-verification',
};

const REQUIREMENT_STATUSES = ['satisfied', 'not-satisfied', 'missing-information'];

// Backend requirement key -> requirement shape the pages already render
const REQUIREMENT_META = {
  cgpa: { id: 'minimum-cgpa', category: 'academic', label: 'Minimum CGPA', field: 'cgpa' },
  english: { id: 'language-test', category: 'language', label: 'Language proficiency', field: 'englishScore' },
  degree_level: { id: 'degree-level', category: 'academic', label: 'Degree level', field: 'degreeLevel' },
};

const AWAITING_MESSAGE = 'No structured CGPA or English requirement is available to check for this program. Confirm requirements on the official page.';

function worstRequirementStatus(requirements) {
  const statuses = requirements.map((requirement) => requirement.status);
  if (statuses.includes('not-satisfied')) return 'not-satisfied';
  if (statuses.includes('missing-information')) return 'missing-information';
  if (statuses.includes('awaiting-verification')) return 'awaiting-verification';
  return 'satisfied';
}

/**
 * Maps a backend EligibilityResult to { status, requirements, notes, message }.
 * Each requirement keeps its own backend status; the overall status is never
 * upgraded to 'satisfied' from the `eligible` flag alone.
 */
export function mapEligibilityToFrontend(result) {
  const backendRequirements = [
    ...(result?.matched_requirements || []),
    ...(result?.missing_requirements || []),
  ];
  const requirements = backendRequirements.map((item) => ({
    ...(REQUIREMENT_META[item.requirement] || {
      id: item.requirement,
      category: 'other',
      label: item.requirement,
      field: item.requirement,
    }),
    status: REQUIREMENT_STATUSES.includes(item.status) ? item.status : 'awaiting-verification',
    message: item.message || '',
    sourceStatus: 'live-backend',
    required: true,
  }));

  let status = ELIGIBILITY_STATUS_MAP[result?.status] || 'awaiting-verification';
  if (status === 'satisfied' && (requirements.length === 0 || worstRequirementStatus(requirements) !== 'satisfied')) {
    status = requirements.length === 0 ? 'awaiting-verification' : worstRequirementStatus(requirements);
  }

  return {
    status,
    requirements,
    notes: Array.isArray(result?.notes) ? result.notes : [],
    message: status === 'awaiting-verification' ? AWAITING_MESSAGE : '',
    source: 'backend',
  };
}

/**
 * Evaluation shown when backend eligibility is unavailable. Never contains
 * requirement results, so nothing is fabricated.
 * state: 'logged-out' | 'no-profile' | 'not-found' | 'error'
 */
export function getUnavailableEligibility(state, kind = 'program') {
  const subject = kind === 'scholarship' ? 'scholarship' : 'program';
  const messages = {
    'logged-out': `Log in to check your eligibility for this ${subject}.`,
    'no-profile': `Complete your profile to check your eligibility for this ${subject}.`,
    'not-found': `Eligibility is not available for this ${subject}.`,
    error: 'Eligibility could not be checked right now. Please try again later.',
  };
  return {
    status: state === 'no-profile' ? 'missing-information' : 'awaiting-verification',
    requirements: [],
    notes: [],
    message: messages[state] || messages.error,
    source: 'unavailable',
  };
}

async function fetchEligibility(path, token) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const error = new Error(extractErrorMessage(data, `Failed to check eligibility (${response.status})`));
    error.status = response.status;
    throw error;
  }
  return data;
}

/**
 * Check the logged-in student's profile against every program.
 * GET /eligibility/programs  -> EligibilityResult[]
 * Throws an error with `.status` (401 invalid token, 404 no profile).
 */
export async function fetchProgramEligibilities(token) {
  return fetchEligibility('/eligibility/programs', token);
}

/**
 * Check the logged-in student's profile against one program.
 * GET /eligibility/programs/{id}  -> EligibilityResult
 * Throws an error with `.status` (401 invalid token, 404 no profile or no program).
 */
export async function fetchProgramEligibilityById(token, id) {
  return fetchEligibility(`/eligibility/programs/${Number(id)}`, token);
}

/** Turns a failed eligibility request into an unavailable-state name. */
export function getEligibilityErrorState(error) {
  if (error?.status === 401) return 'logged-out';
  if (error?.status === 404) {
    return /profile/i.test(error.message || '') ? 'no-profile' : 'not-found';
  }
  return 'error';
}


// ---------------------------------------------------------------------------
// Financial feasibility (authenticated)
// ---------------------------------------------------------------------------

/**
 * Calculate affordability for one program scenario on the backend.
 * POST /financial-feasibility/calculate -> FeasibilityResult
 * Throws an error with `.status` (401 signed out, 404 unknown program/scholarship, 422 invalid input).
 */
export async function postFinancialFeasibility(token, payload, { signal } = {}) {
  const response = await fetch(`${API_BASE_URL}/financial-feasibility/calculate`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    signal,
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const error = new Error(extractErrorMessage(data, `Failed to calculate financial feasibility (${response.status})`));
    error.status = response.status;
    throw error;
  }
  return data;
}


// ---------------------------------------------------------------------------
// Scholarship eligibility (authenticated)
// ---------------------------------------------------------------------------

// Backend scholarship statuses -> the statuses the pages already use for programs
const SCHOLARSHIP_STATUS_MAP = {
  eligible: 'satisfied',
  not_eligible: 'not-satisfied',
  missing_information: 'missing-information',
  not_evaluated: 'awaiting-verification',
};

const SCHOLARSHIP_REQUIREMENT_STATUS_MAP = {
  satisfied: 'satisfied',
  not_satisfied: 'not-satisfied',
  missing_information: 'missing-information',
  not_evaluated: 'awaiting-verification',
};

/**
 * Check the logged-in student's profile against every verified scholarship.
 * GET /eligibility/scholarships -> ScholarshipEligibilityResult[]
 * Throws an error with `.status` (401 invalid token, 404 no profile).
 */
export async function fetchScholarshipEligibilities(token) {
  return fetchEligibility('/eligibility/scholarships', token);
}

/**
 * Check the logged-in student's profile against one scholarship.
 * GET /eligibility/scholarships/{id} -> ScholarshipEligibilityResult
 */
export async function fetchScholarshipEligibilityById(token, id) {
  const numericId = parseScholarshipId(id);
  if (numericId == null) {
    const error = new Error('Scholarship not found');
    error.status = 404;
    throw error;
  }
  return fetchEligibility(`/eligibility/scholarships/${numericId}`, token);
}

/** Backend scholarship eligibility -> the evaluation shape the pages render. */
export function mapScholarshipEligibilityToFrontend(result) {
  const groups = [
    ...(result?.satisfied || []),
    ...(result?.not_satisfied || []),
    ...(result?.missing_information || []),
    ...(result?.needs_verification || []),
  ];
  const requirements = groups.map((item) => ({
    id: item.requirement,
    label: item.label,
    status: SCHOLARSHIP_REQUIREMENT_STATUS_MAP[item.status] || 'awaiting-verification',
    message: item.reason || '',
    sourceText: item.source_text || null,
    scope: item.scope || 'scholarship',
    conflict: Boolean(item.conflict),
    sourceStatus: 'live-backend',
    required: true,
  }));
  return {
    status: SCHOLARSHIP_STATUS_MAP[result?.status] || 'awaiting-verification',
    outcome: result?.outcome || 'verify_manually',
    summary: result?.summary || '',
    message: result?.summary || '',
    requirements,
    deadline: result?.deadline || null,
    notes: Array.isArray(result?.notes) ? result.notes : [],
    officialUrl: result?.official_url || null,
    lastVerified: result?.last_verified || null,
    verificationStatus: result?.verification_status || null,
    source: 'backend',
  };
}


// ---------------------------------------------------------------------------
// Scholarship recommendations (authenticated)
// ---------------------------------------------------------------------------

const programQuery = (programId) => (programId != null ? `?program_id=${Number(programId)}` : '');

/** GET /recommendations/scholarships?program_id= -> RecommendationList */
export function fetchScholarshipRecommendations(token, programId = null) {
  return fetchEligibility(`/recommendations/scholarships${programQuery(programId)}`, token);
}

/** GET /recommendations/scholarships/{id}?program_id= -> ScholarshipRecommendation */
export function fetchScholarshipRecommendation(token, id, programId = null) {
  return fetchEligibility(`/recommendations/scholarships/${parseScholarshipId(id)}${programQuery(programId)}`, token);
}

/** The selected journey opportunity's program ID, or null when it isn't a backend program. */
export function getSelectedProgramId(opportunityId) {
  return /^\d+$/.test(String(opportunityId ?? '')) ? Number(opportunityId) : null;
}


// ---------------------------------------------------------------------------
// Scholarship-program relationships (public)
// ---------------------------------------------------------------------------

async function fetchMatches(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) throw new Error(`Failed to load scholarship and program matches (${response.status})`);
  return response.json();
}

/** GET /scholarships/{id}/programs -> MatchResult[], ruled-out programs included. */
export function fetchScholarshipPrograms(id) {
  return fetchMatches(`/scholarships/${parseScholarshipId(id)}/programs?include_not_matches=true`);
}

/** GET /programs/{id}/scholarships -> MatchResult[], ruled-out scholarships included. */
export function fetchProgramScholarships(programId) {
  return fetchMatches(`/programs/${Number(programId)}/scholarships?include_not_matches=true`);
}

/** GET /scholarships/program-coverage -> per-scholarship counts, keyed by frontend ID. */
export async function fetchScholarshipProgramCoverage() {
  const rows = await fetchMatches('/scholarships/program-coverage');
  return Object.fromEntries(rows.map((row) => [`${SCHOLARSHIP_ID_PREFIX}${row.scholarship_id}`, row]));
}

/**
 * Matches worth showing on a details page: a different host country says nothing useful about
 * this pair, so only ruled-out pairs with a closer reason stay.
 */
export function selectRelevantMatches(matches) {
  return (matches || []).filter((item) => item.outcome !== 'not_a_match' || item.blocking_criterion !== 'country');
}


/**
 * Saved financial plan (budget and own expense estimates) of the logged-in student.
 * GET /financial-feasibility/plan, PUT /financial-feasibility/plan/budget,
 * PUT /financial-feasibility/plan/expenses/{programId}
 * Each resolves to the whole plan and throws an error with `.status`.
 */
async function financialPlanRequest(token, path, method, body) {
  const response = await fetch(`${API_BASE_URL}/financial-feasibility/plan${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const error = new Error(extractErrorMessage(data, `Failed to update your financial plan (${response.status})`));
    error.status = response.status;
    throw error;
  }
  return data;
}

export function fetchFinancialPlan(token) {
  return financialPlanRequest(token, '', 'GET');
}

export function putFinancialBudget(token, budget) {
  return financialPlanRequest(token, '/budget', 'PUT', budget);
}

export function putProgramExpenses(token, programId, expenses) {
  return financialPlanRequest(token, `/expenses/${programId}`, 'PUT', expenses);
}


/**
 * Personal guidance for the logged-in student.
 * GET /eligibility/improvements?program_id=&scholarship_id= -> ProfileImprovementResult
 * Throws an error with `.status` (401 invalid token, 404 no profile or unknown opportunity).
 */
export async function fetchProfileImprovements(token, query = {}) {
  const params = new URLSearchParams(query).toString();
  return fetchEligibility(`/eligibility/improvements${params ? `?${params}` : ''}`, token);
}

/**
 * Ask the FitScholar AI Assistant. POST /assistant/chat -> AssistantReply
 * Throws an error with `.status` (401 signed out, 403 profile incomplete or admin, 429 too many messages).
 */
export async function askAssistant(token, message, context = {}) {
  const response = await fetch(`${API_BASE_URL}/assistant/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify({ message, context }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(extractErrorMessage(data, `The assistant could not answer (${response.status})`));
    error.status = response.status;
    throw error;
  }
  return data;
}

/** Query for one selected opportunity. Older sample selections (univ-1, sch-1) have no backend record. */
export function getImprovementQuery(opportunity) {
  if (!opportunity) return null;
  const scholarshipId = parseScholarshipId(opportunity.id);
  if (scholarshipId != null) return { scholarship_id: scholarshipId };
  const programId = Number(opportunity._numericId ?? opportunity.id);
  if (opportunity.kind !== 'scholarship' && Number.isInteger(programId) && programId > 0) return { program_id: programId };
  return null;
}
