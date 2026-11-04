import { getProfileApi, updateProfileApi } from './profileApi';
import { extractDocumentData } from './documentAnalysis.js';
import {
  getEligibilityErrorState,
  fetchMappedScholarships,
  fetchScholarshipById,
  mapScholarshipToFrontend,
  parseScholarshipId,
  postFinancialFeasibility,
  fetchProfileImprovements,
  askAssistant,
  fetchFinancialPlan,
  putFinancialBudget,
  putScholarshipExpenses,
  fetchScholarshipEligibilities,
  fetchScholarshipEligibilityById,
  mapScholarshipEligibilityToFrontend,
  fetchScholarshipRecommendations,
  fetchScholarshipRecommendation,
  fetchScholarshipSearch,
  fetchScholarshipFilterOptions,
} from './opportunityApi';
import { buildApplicationPathway } from './opportunityJourney.js';
/**
 * Service Layer for FitScholars
 * Provides an abstraction layer between UI components and backend services.
 * Profiles and scholarship features call the real FastAPI backend.
 * Features without a backend source return unavailable states instead of sample records.
 */
function readStoredToken() {
  return typeof window !== 'undefined' ? localStorage.getItem('fitscholar_token') : null;
}

export const apiService = {
  // ---------------------------------------------------------------------------
  // Profile Endpoints
  // ---------------------------------------------------------------------------

  /**
   * Fetch current user's academic profile
   * FastAPI Target Endpoint: GET /profile/
   */
  getProfile: async () => {
    const token = readStoredToken();
    if (!token) return { exists: false, data: null };
    return getProfileApi(token);
  },

  /**
   * Update academic credentials or preferences
   * FastAPI Target Endpoint: PUT /profile/
   */
  updateProfile: async (updatedData) => {
    const token = readStoredToken();
    if (!token) throw new Error('Sign in to update your profile.');
    return updateProfileApi(token, updatedData);
  },

  // ---------------------------------------------------------------------------
  /**
   * Check the student's backend profile against every verified scholarship.
   * FastAPI Endpoint: GET /eligibility/scholarships
   * Never rejects. Resolves to { state, results } like getProgramEligibilities;
   * results are keyed by the frontend scholarship ID ("sch-db-12").
   */
  getScholarshipEligibilities: async (token = readStoredToken()) => {
    if (!token) return { state: 'logged-out', results: {} };
    try {
      const data = await fetchScholarshipEligibilities(token);
      const results = Object.fromEntries(
        (Array.isArray(data) ? data : []).map((item) => [`sch-db-${item.scholarship_id}`, mapScholarshipEligibilityToFrontend(item)]),
      );
      return { state: 'ok', results };
    } catch (err) {
      console.warn('apiService.getScholarshipEligibilities backend error:', err?.message);
      return { state: getEligibilityErrorState(err), results: {} };
    }
  },

  /**
   * Check the student's backend profile against one scholarship.
   * FastAPI Endpoint: GET /eligibility/scholarships/{id}
   * Never rejects. Resolves to { state, evaluation }.
   */
  getScholarshipEligibilityById: async (id, token = readStoredToken()) => {
    if (!token) return { state: 'logged-out', evaluation: null };
    try {
      const data = await fetchScholarshipEligibilityById(token, id);
      return { state: 'ok', evaluation: mapScholarshipEligibilityToFrontend(data) };
    } catch (err) {
      console.warn('apiService.getScholarshipEligibilityById backend error:', err?.message);
      return { state: getEligibilityErrorState(err), evaluation: null };
    }
  },

  /**
   * Personal guidance from the student's profile and eligibility results.
   * FastAPI Endpoint: GET /eligibility/improvements
   * Never rejects. Resolves to { state, data } where state is
   * 'ok' | 'logged-out' | 'no-profile' | 'not-found' | 'error'.
   */
  getProfileImprovements: async (query, token = readStoredToken()) => {
    if (!token) return { state: 'logged-out', data: null };
    try {
      return { state: 'ok', data: await fetchProfileImprovements(token, query || {}) };
    } catch (err) {
      console.warn('apiService.getProfileImprovements backend error:', err?.message);
      return { state: getEligibilityErrorState(err), data: null };
    }
  },

  /**
   * FitScholar AI Assistant. FastAPI Endpoint: POST /assistant/chat
   * Rejects with an error carrying `.status`; the chat shows the message and offers a retry.
   */
  askAssistant: (message, context, token = readStoredToken()) => {
    if (!token) {
      const error = new Error('Please sign in again to use the assistant.');
      error.status = 401;
      return Promise.reject(error);
    }
    return askAssistant(token, message, context);
  },

  // ---------------------------------------------------------------------------
  // Scholarship & Funding Endpoints
  // ---------------------------------------------------------------------------

  /**
   * Retrieve verified scholarships from the real FastAPI backend.
   * FastAPI Endpoint: GET /scholarships/
   * Like programs, never falls back to mock data; errors reach the caller.
   */
  searchScholarships: (query, token = readStoredToken()) => fetchScholarshipSearch(query, token),

  getScholarshipFilterOptions: () => fetchScholarshipFilterOptions(),

  getMatchedScholarships: async () => {
    return fetchMappedScholarships();
  },

  /**
   * Resolve a previously selected opportunity by ID.
   * Checks programs and scholarships from the real backend.
   */
  getOpportunityById: async (id) => {
    if (parseScholarshipId(id) != null) {
      const scholarship = await fetchScholarshipById(id);
      return scholarship ? mapScholarshipToFrontend(scholarship) : null;
    }
    return null;
  },

  /**
   * Fetch details for a specific scholarship.
   * FastAPI Endpoint: GET /scholarships/{id}
   */
  getScholarshipById: async (id) => {
    const scholarship = await fetchScholarshipById(id);
    return scholarship ? mapScholarshipToFrontend(scholarship) : null;
  },

  // ---------------------------------------------------------------------------
  // Application Pathway & Financial Feasibility
  // ---------------------------------------------------------------------------

  getApplicationPathway: async (opportunityOrId, strategyOrDocumentRecords = {}) => {
    const opportunity = opportunityOrId && typeof opportunityOrId === 'object'
      ? opportunityOrId
      : await apiService.getOpportunityById(opportunityOrId);
    const documentRecords = strategyOrDocumentRecords
      && typeof strategyOrDocumentRecords === 'object'
      ? strategyOrDocumentRecords
      : {};
    return buildApplicationPathway(opportunity, { documentRecords });
  },

  /**
   * Calculate scholarship affordability using verified linked cost data.
   * FastAPI Endpoint: POST /financial-feasibility/calculate
   * Rejects with an error carrying `.status` (401 when signed out).
   */
  calculateFinancialFeasibility: async (payload, { signal, token = readStoredToken() } = {}) => {
    if (!token) {
      const error = new Error('Sign in to calculate financial feasibility.');
      error.status = 401;
      throw error;
    }
    return postFinancialFeasibility(token, payload, { signal });
  },

  /**
   * The student's saved budget and scholarship cost inputs.
   * FastAPI Endpoints: GET /financial-feasibility/plan, PUT .../plan/budget and scholarship expenses.
   * Reject with an error carrying `.status` (401 when signed out).
   */
  getFinancialPlan: async (token = readStoredToken()) => {
    if (!token) throw Object.assign(new Error('Sign in to see your financial plan.'), { status: 401 });
    return fetchFinancialPlan(token);
  },

  saveFinancialBudget: async (budget, token = readStoredToken()) => {
    if (!token) throw Object.assign(new Error('Sign in to save your budget.'), { status: 401 });
    return putFinancialBudget(token, budget);
  },

  saveScholarshipExpenses: async (scholarshipId, expenses, token = readStoredToken()) => {
    if (!token) throw Object.assign(new Error('Sign in to save your costs.'), { status: 401 });
    return putScholarshipExpenses(token, scholarshipId, expenses);
  },

  /**
   * Scholarships ranked for the logged-in student.
   * FastAPI Endpoint: GET /recommendations/scholarships
   * Never rejects. Resolves to { state, data }; state is 'ok' | 'logged-out' | 'not-found' | 'error'.
   */
  getRecommendations: async (token = readStoredToken()) => {
    if (!token) return { state: 'logged-out', data: null };
    try {
      return { state: 'ok', data: await fetchScholarshipRecommendations(token) };
    } catch (err) {
      console.warn('apiService.getRecommendations backend error:', err?.message);
      return { state: getEligibilityErrorState(err), data: null };
    }
  },

  /**
   * The logged-in student's result for one scholarship.
   * FastAPI Endpoint: GET /recommendations/scholarships/{id}
   * Never rejects. Resolves to { state, data }.
   */
  getScholarshipRecommendation: async (id, token = readStoredToken()) => {
    if (!token) return { state: 'logged-out', data: null };
    try {
      return { state: 'ok', data: await fetchScholarshipRecommendation(token, id) };
    } catch (err) {
      console.warn('apiService.getScholarshipRecommendation backend error:', err?.message);
      return { state: getEligibilityErrorState(err), data: null };
    }
  },

  // Document extraction has no backend implementation.
  extractDocumentData: async (file) => {
    return extractDocumentData(file);
  },
};
