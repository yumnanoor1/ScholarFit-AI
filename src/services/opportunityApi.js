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
import { mapRequiredDocumentNames } from './opportunityJourney.js';
import { getSourceEvidence } from './sourceVerification.js';

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
// API Calls
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Scholarships
// ---------------------------------------------------------------------------

// Persisted scholarship IDs stay distinct from legacy non-database selections.
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
  const sourceUrl = item.official_info_url || null;
  const lastVerified = item.last_verified_date || null;
  const evidence = getSourceEvidence({
    sourceUrl,
    lastVerified,
    verificationStatus: item.verification_status,
    verificationBasis: item.verification_basis,
  });
  const verified = evidence.status === 'verified';
  const structured = Boolean(item.structured_data_version);
  // Structured records name their own links, so a home page or example link isn't offered as the application
  const officialUrl = structured
    ? item.official_application_url || null
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
    verificationText: evidence.message || getVerificationText(item),
    verificationLabel: evidence.label,
    verificationMessage: evidence.message,
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
    applicationChannel: item.application_channel || null,
    admissionRequired: item.admission_required || null,
    nominationRequired: item.nomination_required || null,
    requiredDocumentsText: item.required_documents || null,
    applicationPathwayText: item.application_pathway || null,
    notes: item.notes || null,

    sourceName: item.source_name || null,
    sourceUrl,
    lastVerified,
    verificationStatus: verified ? 'verified' : 'unverified',
    recordedVerificationStatus: item.verification_status || null,
    archived: Boolean(item.archived),

    // Records the backend marks verified were checked against their official source
    sourceStatus: verified ? 'official-verified' : 'unverified',
    deadlineStatus: verified ? 'official-verified' : 'unverified',
    applicationUrl: officialUrl,
    applicationUrlStatus: verified && officialUrl ? 'official-verified' : 'unavailable',

    matchScore: null,
    requiredDocuments: mapRequiredDocumentNames(
      item.required_documents_list,
      item.required_documents,
      verified,
    ),
  };
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

/**
 * Evaluation shown when backend eligibility is unavailable. Never contains
 * requirement results, so nothing is fabricated.
 * state: 'logged-out' | 'no-profile' | 'profile-incomplete' | 'not-found' | 'error'
 */
export function getUnavailableEligibility(state) {
  const messages = {
    'logged-out': 'Log in to check your scholarship eligibility.',
    'no-profile': 'Complete your profile to check your scholarship eligibility.',
    'profile-incomplete': 'Complete your profile to check your scholarship eligibility.',
    'not-found': 'Scholarship eligibility is not available.',
    error: 'Eligibility could not be checked right now. Please try again later.',
  };
  return {
    status: ['no-profile', 'profile-incomplete'].includes(state) ? 'missing-information' : 'awaiting-verification',
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
    error.code = data?.detail?.code || data?.code;
    throw error;
  }
  return data;
}

/** Turns a failed eligibility request into an unavailable-state name. */
export function getEligibilityErrorState(error) {
  if (error?.status === 401) return 'logged-out';
  if (error?.status === 403 && error?.code === 'profile_incomplete') return 'profile-incomplete';
  if (error?.status === 404) {
    return /profile/i.test(error.message || '') ? 'no-profile' : 'not-found';
  }
  return 'error';
}


// ---------------------------------------------------------------------------
// Financial feasibility (authenticated)
// ---------------------------------------------------------------------------

/**
 * Calculate affordability for one scholarship scenario on the backend.
 * POST /financial-feasibility/calculate -> FeasibilityResult
 * Throws an error with `.status` (401 signed out, 404 unknown scholarship, 422 invalid input).
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

/** GET /recommendations/scholarships -> RecommendationList */
export function fetchScholarshipRecommendations(token) {
  return fetchEligibility('/recommendations/scholarships', token);
}

/** GET /recommendations/scholarships/{id} -> ScholarshipRecommendation */
export function fetchScholarshipRecommendation(token, id) {
  return fetchEligibility(`/recommendations/scholarships/${parseScholarshipId(id)}`, token);
}


/**
 * Saved financial plan (budget and own expense estimates) of the logged-in student.
 * GET /financial-feasibility/plan, PUT /financial-feasibility/plan/budget,
 * PUT /financial-feasibility/plan/scholarships/{scholarshipId}/expenses
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

export function putScholarshipExpenses(token, scholarshipId, expenses) {
  return financialPlanRequest(token, `/scholarships/${parseScholarshipId(scholarshipId)}/expenses`, 'PUT', expenses);
}


/**
 * Personal guidance for the logged-in student.
 * GET /eligibility/improvements?scholarship_id= -> ProfileImprovementResult
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

/** Query for a selected scholarship with a persisted backend record. */
export function getImprovementQuery(opportunity) {
  if (!opportunity) return null;
  const scholarshipId = parseScholarshipId(opportunity.id);
  if (scholarshipId != null) return { scholarship_id: scholarshipId };
  return null;
}
