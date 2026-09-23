import { 
  mockProfile, 
  mockUniversities, 
  mockScholarships, 
  mockApplicationPathways, 
  mockRecommendations, 
  mockTimelineEvents 
} from '../data/mockData';

// Base URL for future FastAPI integration
const API_BASE_URL = 'http://localhost:8000/api/v1';

/**
 * Service Layer for FitScholar AI
 * Provides an abstraction layer between UI components and backend services.
 * Currently uses mock data with realistic latency delays.
 */
export const apiService = {
  // ---------------------------------------------------------------------------
  // Profile Endpoints
  // ---------------------------------------------------------------------------
  
  /**
   * Fetch current user's academic profile
   * FastAPI Target Endpoint: GET /api/v1/profile/me
   */
  getProfile: async () => {
    return new Promise((resolve) => {
      setTimeout(() => resolve({ ...mockProfile }), 300);
    });
  },

  /**
   * Update academic credentials or preferences
   * FastAPI Target Endpoint: PUT /api/v1/profile/me
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
   * Retrieve matched universities with eligibility status and fit scores
   * FastAPI Target Endpoint: POST /api/v1/matching/universities
   */
  getMatchedUniversities: async (filters = {}) => {
    return new Promise((resolve) => {
      setTimeout(() => {
        let results = [...mockUniversities];

        // Basic client-side filtering simulation
        if (filters.status && filters.status !== 'All') {
          results = results.filter(u => u.eligibilityStatus === filters.status);
        }
        if (filters.country && filters.country !== 'All') {
          results = results.filter(u => u.country === filters.country);
        }
        if (filters.search) {
          const query = filters.search.toLowerCase();
          results = results.filter(u => 
            u.program.toLowerCase().includes(query) || 
            u.university.toLowerCase().includes(query)
          );
        }

        resolve(results);
      }, 300);
    });
  },

  /**
   * Fetch details for a specific university program
   * FastAPI Target Endpoint: GET /api/v1/universities/{id}
   */
  getUniversityById: async (id) => {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        const item = mockUniversities.find(u => u.id === id);
        if (item) resolve(item);
        else resolve(mockUniversities[0]); // Fallback for testing
      }, 200);
    });
  },

  // ---------------------------------------------------------------------------
  // Scholarship & Funding Endpoints
  // ---------------------------------------------------------------------------

  /**
   * Retrieve matched scholarships, assistantships, and waivers
   * FastAPI Target Endpoint: POST /api/v1/matching/scholarships
   */
  getMatchedScholarships: async () => {
    return new Promise((resolve) => {
      setTimeout(() => resolve([...mockScholarships]), 300);
    });
  },

  /**
   * Fetch details for a specific scholarship
   * FastAPI Target Endpoint: GET /api/v1/scholarships/{id}
   */
  getScholarshipById: async (id) => {
    return new Promise((resolve) => {
      setTimeout(() => {
        const item = mockScholarships.find(s => s.id === id);
        resolve(item || mockScholarships[0]);
      }, 200);
    });
  },

  // ---------------------------------------------------------------------------
  // Application Pathway & Financial Feasibility
  // ---------------------------------------------------------------------------

  /**
   * Get sequential application pathway steps for a target university
   * FastAPI Target Endpoint: GET /api/v1/pathways/{universityId}
   */
  getApplicationPathway: async (universityId) => {
    return new Promise((resolve) => {
      setTimeout(() => {
        const pathway = mockApplicationPathways.find(p => p.universityId === universityId);
        resolve(pathway || mockApplicationPathways[0]);
      }, 300);
    });
  },

  /**
   * Fetch explainable decision-support recommendations
   * FastAPI Target Endpoint: GET /api/v1/recommendations
   */
  getRecommendations: async () => {
    return new Promise((resolve) => {
      setTimeout(() => resolve([...mockRecommendations]), 300);
    });
  },

  /**
   * Fetch upcoming timeline deadlines and milestone dates
   * FastAPI Target Endpoint: GET /api/v1/timeline
   */
  getTimelineEvents: async () => {
    return new Promise((resolve) => {
      setTimeout(() => resolve([...mockTimelineEvents]), 300);
    });
  },

  // ---------------------------------------------------------------------------
  // Document Parsing & Analysis Simulator
  // ---------------------------------------------------------------------------

  /**
   * Simulate uploading CV or Transcript for OCR / LLM information extraction
   * FastAPI Target Endpoint: POST /api/v1/documents/analyze
   */
  extractDocumentData: async (file) => {
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve({
          fileName: file ? file.name : "Official_Transcript.pdf",
          extractedData: {
            degreeFound: "BS Computer Science",
            cgpaFound: "3.65",
            institutionFound: "National University of Sciences",
            gradYearFound: "2024"
          },
          missingData: [
            "Official GRE Quantitative score report missing",
            "University registrar seal unverified on transcript page 2"
          ]
        });
      }, 800);
    });
  }
};