import { getProfileApi } from './profileApi';
import {
  fetchMappedPrograms,
  fetchProgramById,
  mapProgramToFrontend,
  fetchProgramEligibilities,
  fetchProgramEligibilityById,
  mapEligibilityToFrontend,
  getEligibilityErrorState,
  fetchMappedScholarships,
  fetchScholarshipById,
  mapScholarshipToFrontend,
  parseScholarshipId,
  postFinancialFeasibility,
  fetchProfileImprovements,
  fetchFinancialPlan,
  putFinancialBudget,
  putProgramExpenses,
  fetchScholarshipEligibilities,
  fetchScholarshipEligibilityById,
  mapScholarshipEligibilityToFrontend,
  fetchScholarshipRecommendations,
  fetchScholarshipRecommendation,
  fetchScholarshipSearch,
  fetchScholarshipFilterOptions,
} from './opportunityApi';
import {
  mockProfile,
  mockScholarships,
  mockApplicationPathways,
} from '../data/mockData';

/**
 * Service Layer for FitScholars
 * Provides an abstraction layer between UI components and backend services.
 * Profile, Programs, Universities, Scholarships, and Program eligibility call the real FastAPI backend.
 * Pathways, Recommendations, and Document extraction have no backend endpoints yet and use local data.
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
    if (token) {
      try {
        const { exists, data } = await getProfileApi(token);
        if (exists && data) return data;
      } catch (err) {
        console.warn('apiService.getProfile backend error:', err?.message);
      }
    }
    return new Promise((resolve) => {
      setTimeout(() => resolve({ ...mockProfile }), 300);
    });
  },

  /**
   * Update academic credentials or preferences
   * FastAPI Target Endpoint: PUT /profile/
   */
  updateProfile: async (updatedData) => {
    return new Promise((resolve) => {
      setTimeout(() => {
        const updated = { ...mockProfile, ...updatedData };
        resolve({ success: true, data: updated });
      }, 400);
    });
  },

  // ---------------------------------------------------------------------------
  // University & Admission Matching Endpoints
  // ---------------------------------------------------------------------------

  /**
   * Retrieve programs from the real FastAPI backend.
   * FastAPI Endpoint: GET /programs/ + GET /universities/
   * Returns frontend-mapped program objects joined with university data.
   * Falls back to an empty array — never falls back to mock data.
   */
  getMatchedUniversities: async () => {
    return fetchMappedPrograms();
  },

  /**
   * Fetch details for a specific university program by its ID.
   * ID may be a string (e.g. "3") because ProfileContext stores string IDs.
   * FastAPI Endpoints: GET /programs/{id} + GET /universities/{university_id}
   * Returns null if not found.
   */
  getUniversityById: async (id) => {
    const result = await fetchProgramById(id);
    if (!result) return null;
    return mapProgramToFrontend(result.program, result.university);
  },

  // ---------------------------------------------------------------------------
  // Program Eligibility Endpoints (authenticated)
  // ---------------------------------------------------------------------------

  /**
   * Check the student's backend profile against every program.
   * FastAPI Endpoint: GET /eligibility/programs
   * Never rejects. Resolves to { state, results } where state is
   * 'ok' | 'logged-out' | 'no-profile' | 'error' and results maps the
   * frontend program ID (string) to a mapped evaluation.
   */
  getProgramEligibilities: async (token = readStoredToken()) => {
    if (!token) return { state: 'logged-out', results: {} };
    try {
      const data = await fetchProgramEligibilities(token);
      const results = Object.fromEntries(
        (Array.isArray(data) ? data : []).map((item) => [String(item.program_id), mapEligibilityToFrontend(item)]),
      );
      return { state: 'ok', results };
    } catch (err) {
      console.warn('apiService.getProgramEligibilities backend error:', err?.message);
      return { state: getEligibilityErrorState(err), results: {} };
    }
  },

  /**
   * Check the student's backend profile against one program.
   * FastAPI Endpoint: GET /eligibility/programs/{id}
   * Never rejects. Resolves to { state, evaluation } where state is
   * 'ok' | 'logged-out' | 'no-profile' | 'not-found' | 'error'.
   */
  getProgramEligibilityById: async (id, token = readStoredToken()) => {
    if (!token) return { state: 'logged-out', evaluation: null };
    if (!Number.isFinite(Number(id))) return { state: 'not-found', evaluation: null };
    try {
      const data = await fetchProgramEligibilityById(token, id);
      return { state: 'ok', evaluation: mapEligibilityToFrontend(data) };
    } catch (err) {
      console.warn('apiService.getProgramEligibilityById backend error:', err?.message);
      return { state: getEligibilityErrorState(err), evaluation: null };
    }
  },

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
   * Checks programs from the real backend first, then mock scholarships.
   */
  getOpportunityById: async (id) => {
    // Try real backend programs first
    try {
      const result = await fetchProgramById(id);
      if (result) {
        return { ...mapProgramToFrontend(result.program, result.university), kind: 'program' };
      }
    } catch (err) {
      console.warn('getOpportunityById: backend lookup failed:', err?.message);
    }
    // Backend scholarships use "sch-db-<id>"
    if (parseScholarshipId(id) != null) {
      const scholarship = await fetchScholarshipById(id);
      return scholarship ? mapScholarshipToFrontend(scholarship) : null;
    }
    // Older saved selections may still hold sample scholarship IDs (sch-1…)
    const sample = mockScholarships.find((item) => item.id === id);
    return sample ? { ...sample, kind: 'scholarship' } : null;
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

  /**
   * Get sequential application pathway steps for a target university.
   * FastAPI Target Endpoint: GET /api/v1/pathways/{universityId}
   */
  getApplicationPathway: async (universityId, strategy = 'University First') => {
    return new Promise((resolve) => {
      setTimeout(() => {
        const pathway = mockApplicationPathways.find(
          (item) => item.universityId === universityId && item.type === strategy,
        );
        resolve(pathway ? { ...pathway, opportunityId: universityId } : null);
      }, 300);
    });
  },

  /**
   * Calculate whether a program (optionally with a scholarship) fits the student's budget.
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
   * The student's saved budget and expense estimates.
   * FastAPI Endpoints: GET /financial-feasibility/plan, PUT .../plan/budget, PUT .../plan/expenses/{programId}
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

  saveProgramExpenses: async (programId, expenses, token = readStoredToken()) => {
    if (!token) throw Object.assign(new Error('Sign in to save your costs.'), { status: 401 });
    return putProgramExpenses(token, programId, expenses);
  },

  /**
   * Scholarships ranked for the logged-in student, optionally for one program.
   * FastAPI Endpoint: GET /recommendations/scholarships
   * Never rejects. Resolves to { state, data }; state is 'ok' | 'logged-out' | 'not-found' | 'error'.
   */
  getRecommendations: async (programId = null, token = readStoredToken()) => {
    if (!token) return { state: 'logged-out', data: null };
    try {
      return { state: 'ok', data: await fetchScholarshipRecommendations(token, programId) };
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
  getScholarshipRecommendation: async (id, programId = null, token = readStoredToken()) => {
    if (!token) return { state: 'logged-out', data: null };
    try {
      return { state: 'ok', data: await fetchScholarshipRecommendation(token, id, programId) };
    } catch (err) {
      console.warn('apiService.getScholarshipRecommendation backend error:', err?.message);
      return { state: getEligibilityErrorState(err), data: null };
    }
  },

  // ---------------------------------------------------------------------------
  // Document Parsing & Analysis Simulator
  // ---------------------------------------------------------------------------

  /**
   * Simulate uploading CV or Transcript for OCR / LLM information extraction.
   * FastAPI Target Endpoint: POST /api/v1/documents/analyze
   */
  extractDocumentData: async (file) => {
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve({
          fileName: file ? file.name : 'Official_Transcript.pdf',
          extractedData: {
            degreeFound: 'BS Computer Science',
            cgpaFound: '3.65',
            institutionFound: 'National University of Sciences',
            gradYearFound: '2024',
          },
          missingData: [
            'Official GRE Quantitative score report missing',
            'University registrar seal unverified on transcript page 2',
          ],
        });
      }, 800);
    });
  },
};
