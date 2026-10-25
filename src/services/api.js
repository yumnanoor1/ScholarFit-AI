import { getProfileApi } from './profileApi';
import { fetchMappedPrograms, fetchProgramById, mapProgramToFrontend } from './opportunityApi';
import {
  mockProfile,
  mockScholarships,
  mockApplicationPathways,
  mockRecommendations,
} from '../data/mockData';

/**
 * Service Layer for FitScholars
 * Provides an abstraction layer between UI components and backend services.
 * Profile, Programs, and Universities now call the real FastAPI backend.
 * Scholarships, Pathways, Recommendations, and Document extraction still use mock data.
 */
export const apiService = {
  // ---------------------------------------------------------------------------
  // Profile Endpoints
  // ---------------------------------------------------------------------------

  /**
   * Fetch current user's academic profile
   * FastAPI Target Endpoint: GET /profile/
   */
  getProfile: async () => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('fitscholar_token') : null;
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
  // Scholarship & Funding Endpoints
  // ---------------------------------------------------------------------------

  /**
   * Retrieve matched scholarships, assistantships, and waivers.
   * Still uses mock data — scholarship backend integration is a separate task.
   */
  getMatchedScholarships: async () => {
    return new Promise((resolve) => {
      setTimeout(() => resolve([...mockScholarships]), 300);
    });
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
    // Fall back to mock scholarships
    const scholarships = await apiService.getMatchedScholarships();
    const scholarship = scholarships.find((item) => item.id === id);
    return scholarship ? { ...scholarship, kind: 'scholarship' } : null;
  },

  /**
   * Fetch details for a specific scholarship.
   * FastAPI Target Endpoint: GET /api/v1/scholarships/{id}
   */
  getScholarshipById: async (id) => {
    return new Promise((resolve) => {
      setTimeout(() => {
        const item = mockScholarships.find((s) => s.id === id);
        resolve(item || null);
      }, 200);
    });
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
   * Fetch explainable decision-support recommendations.
   * FastAPI Target Endpoint: GET /api/v1/recommendations
   */
  getRecommendations: async () => {
    return new Promise((resolve) => {
      setTimeout(() => resolve([...mockRecommendations]), 300);
    });
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
