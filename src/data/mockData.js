// Realistic Mock Dataset for FitScholars
// Structured for easy replacement with FastAPI endpoints and MongoDB documents

export const mockProfile = {
  id: "usr_991823",
  name: "Alexander Wright",
  degree: "BS Computer Science",
  degreeLevel: "Bachelor's",
  university: "National University of Sciences",
  cgpa: "3.65",
  graduationYear: "2024",
  englishTest: "IELTS",
  englishScore: "7.5",
  skills: ["Python", "Machine Learning", "Data Structures", "FastAPI", "React.js"],
  projects: ["AI Image Classifier", "Automated Grading System"],
  researchExperience: "Co-authored 1 conference paper on NLP for healthcare domain.",
  fieldOfInterest: "Computer Science & AI",
  preferredCountries: ["Germany", "United States", "Canada"],
  preferredDegree: "Master's",
  fundingPreference: "Full Funding Required",
  approximateBudget: "$5,000 / year",
  profileCompletionPercentage: 85
};

// Sample document requirements and application links. Replace with official data from the backend.
// A null applicationUrl means no verified official link is known; the UI must not invent one.
const SAMPLE_DOCUMENTS = [
  { id: "transcript", name: "Academic transcript", sourceStatus: "unverified-sample", reason: "Sample requirement; confirm with the official provider." },
  { id: "cv", name: "CV / Resume", sourceStatus: "unverified-sample", reason: "Sample requirement; confirm with the official provider." },
  { id: "english-test", name: "English test certificate", sourceStatus: "unverified-sample", reason: "Sample requirement; confirm accepted tests with the official provider." },
  { id: "statement-of-purpose", name: "Statement of purpose", sourceStatus: "unverified-sample", reason: "Sample requirement; confirm with the official provider." },
];

const withApplicationData = (opportunity) => ({
  ...opportunity,
  financialData: opportunity.financialData || {
    sourceStatus: opportunity.sourceStatus || "unverified-sample",
    studyDuration: null,
    costs: {},
    funding: [],
  },
  requiredDocuments: SAMPLE_DOCUMENTS,
  applicationUrl: null,
  applicationUrlStatus: "unavailable",
});

const baseUniversities = [
  {
    id: "univ-1",
    university: "Technical University of Munich",
    program: "M.Sc. Informatics",
    country: "Germany",
    degree: "Master's",
    eligibilityStatus: "Eligible",
    cgpaReq: "3.2",
    cgpaReqSatisfied: true,
    englishReq: "IELTS 7.0",
    englishReqSatisfied: true,
    deadline: "May 31, 2027",
    tuition: "$600 / year",
    matchScore: 94,
    matchReason: "Your CGPA (3.65) exceeds requirement (3.2) and your background aligns with faculty AI research focus.",
    sourceStatus: "unverified-sample",
    deadlineStatus: "unverified-sample",
    saved: true
  },
  {
    id: "univ-2",
    university: "University of Toronto",
    program: "M.Sc. Computer Science",
    country: "Canada",
    degree: "Master's",
    eligibilityStatus: "Requirements Missing",
    cgpaReq: "3.7",
    cgpaReqSatisfied: false,
    englishReq: "IELTS 7.5",
    englishReqSatisfied: true,
    deadline: "Dec 15, 2026",
    tuition: "$28,000 / year",
    matchScore: 78,
    matchReason: "Strong test scores and research paper, but CGPA is slightly under the recommended 3.7 threshold.",
    sourceStatus: "unverified-sample",
    deadlineStatus: "unverified-sample",
    saved: false
  },
  {
    id: "univ-3",
    university: "University of Texas at Austin",
    program: "M.S. Artificial Intelligence",
    country: "United States",
    degree: "Master's",
    eligibilityStatus: "Eligible",
    cgpaReq: "3.5",
    cgpaReqSatisfied: true,
    englishReq: "TOEFL 100 / IELTS 7.5",
    englishReqSatisfied: true,
    deadline: "Jan 15, 2027",
    tuition: "$24,000 / year",
    matchScore: 88,
    matchReason: "Matches your research background in NLP and Machine Learning projects.",
    sourceStatus: "unverified-sample",
    deadlineStatus: "unverified-sample",
    saved: true
  }
];

export const mockUniversities = baseUniversities.map(withApplicationData);

const baseScholarships = [
  {
    id: "sch-1",
    name: "DAAD EPOS Scholarship",
    provider: "German Academic Exchange Service",
    country: "Germany",
    eligibility: "Eligible",
    type: "Scholarship",
    coverage: "Full Tuition + €934/month living stipend",
    amount: 15000,
    deadline: "Oct 31, 2026",
    pathway: "University First",
    matchScore: 92,
    sourceStatus: "unverified-sample",
    deadlineStatus: "unverified-sample",
    saved: true
  },
  {
    id: "sch-2",
    name: "Graduate Research Assistantship (GRA)",
    provider: "UT Austin AI Lab",
    country: "United States",
    eligibility: "Eligible",
    type: "RA",
    coverage: "100% Tuition Waiver + $2,200/month stipend",
    amount: 26000,
    deadline: "Jan 15, 2027",
    pathway: "Combined Application",
    matchScore: 88,
    sourceStatus: "unverified-sample",
    deadlineStatus: "unverified-sample",
    saved: false
  },
  {
    id: "sch-3",
    name: "Ontario Graduate Scholarship (OGS)",
    provider: "Government of Ontario / UofT",
    country: "Canada",
    eligibility: "Requirements Missing",
    type: "Fellowship",
    coverage: "$15,000 per academic year",
    amount: 15000,
    deadline: "Nov 15, 2026",
    pathway: "Scholarship First",
    matchScore: 75,
    sourceStatus: "unverified-sample",
    deadlineStatus: "unverified-sample",
    saved: false
  }
];

export const mockScholarships = baseScholarships.map(withApplicationData);

export const mockApplicationPathways = [
  {
    universityId: "univ-1",
    type: "University First",
    steps: [
      {
        id: "build-profile",
        title: "Build Your Profile",
        description: "Complete your academic, personal, and language details to create your profile.",
        status: "pending",
      },
      {
        id: "explore-opportunities",
        title: "Explore Opportunities",
        description: "Discover universities, scholarships, and programs that match your goals.",
        status: "pending",
      },
      {
        id: "compare-shortlist",
        title: "Compare & Shortlist",
        description: "Shortlist the best options based on your preferences and eligibility.",
        status: "pending",
      },
      {
        id: "financial-feasibility",
        title: "Financial Feasibility",
        description: "Estimate tuition and living costs, review funding options, and check affordability.",
        status: "pending",
      },
      {
        id: "plan-application",
        title: "Plan Your Application",
        description: "Apply to the university first. Submit the Uni-Assist or university application, then apply for DAAD funding after receiving an admission decision.",
        status: "pending",
      },
      {
        id: "prepare-documents",
        title: "Prepare Documents",
        description: "Gather your verified transcript and the documents required for university admission and DAAD funding.",
        status: "pending",
      },
      {
        id: "track-deadlines",
        title: "Track Deadlines",
        description: "Track the university and scholarship deadlines separately and confirm dates with each official provider.",
        status: "pending",
      },
      {
        id: "application-ready",
        title: "Application Ready",
        description: "Review both applications and submit the scholarship application after following the university's admission process.",
        status: "pending",
      },
    ]
  },
  {
    universityId: "univ-3",
    type: "Combined Application",
    steps: [
      {
        id: "build-profile",
        title: "Build Your Profile",
        description: "Complete your academic, personal, and language details to create your profile.",
        status: "pending",
      },
      {
        id: "explore-opportunities",
        title: "Explore Opportunities",
        description: "Discover universities, scholarships, and programs that match your goals.",
        status: "pending",
      },
      {
        id: "compare-shortlist",
        title: "Compare & Shortlist",
        description: "Shortlist the best options based on your preferences and eligibility.",
        status: "pending",
      },
      {
        id: "financial-feasibility",
        title: "Financial Feasibility",
        description: "Estimate tuition and living costs, review funding options, and check affordability.",
        status: "pending",
      },
      {
        id: "plan-application",
        title: "Plan Your Application",
        description: "Use the combined application process. Contact potential research advisors and request assistantship consideration in the graduate application.",
        status: "pending",
      },
      {
        id: "prepare-documents",
        title: "Prepare Documents",
        description: "Gather your CV, transcripts, project portfolio, and other documents requested by the department.",
        status: "pending",
      },
      {
        id: "track-deadlines",
        title: "Track Deadlines",
        description: "Track application and interview dates and confirm the schedule with the department.",
        status: "pending",
      },
      {
        id: "application-ready",
        title: "Application Ready",
        description: "Review the combined application and prepare for any departmental interview.",
        status: "pending",
      },
    ]
  },
  {
    universityId: "univ-1",
    type: "Scholarship First",
    steps: [
      {
        id: "build-profile",
        title: "Build Your Profile",
        description: "Complete your academic, personal, and language details to create your profile.",
        status: "pending",
      },
      {
        id: "explore-opportunities",
        title: "Explore Opportunities",
        description: "Discover universities, scholarships, and programs that match your goals.",
        status: "pending",
      },
      {
        id: "compare-shortlist",
        title: "Compare & Shortlist",
        description: "Shortlist the best options based on your preferences and eligibility.",
        status: "pending",
      },
      {
        id: "financial-feasibility",
        title: "Financial Feasibility",
        description: "Estimate tuition and living costs, review funding options, and check affordability.",
        status: "pending",
      },
      {
        id: "plan-application",
        title: "Plan Your Application",
        description: "Apply for the scholarship first. Review its eligibility and submit the scholarship application, then apply to the university and follow the provider's instructions for linking admission and funding.",
        status: "pending",
      },
      {
        id: "prepare-documents",
        title: "Prepare Documents",
        description: "Gather the documents requested by the scholarship provider and the university, and verify their official requirements.",
        status: "pending",
      },
      {
        id: "track-deadlines",
        title: "Track Deadlines",
        description: "Track scholarship and university deadlines separately and confirm dates with each official provider.",
        status: "pending",
      },
      {
        id: "application-ready",
        title: "Application Ready",
        description: "Review both applications and make sure the university and scholarship submissions are linked as required.",
        status: "pending",
      },
    ]
  }
];

export const mockRecommendations = [
  {
    id: "univ-1",
    title: "M.Sc. Informatics",
    university: "Technical University of Munich",
    country: "Germany",
    deadline: "May 31, 2027",
    eligibilityStatus: "Eligible",
    score: 94,
    reasons: [
      "No tuition fees fit your annual self-funding budget target.",
      "Your 3.65 CGPA exceeds the minimum 3.2 eligibility criteria.",
      "NLP research paper directly aligns with lab focus."
    ],
    missingReq: null,
    nextAction: "Request official university transcript for Uni-Assist upload."
  },
  {
    id: "univ-2",
    title: "M.Sc. Computer Science",
    university: "University of Toronto",
    country: "Canada",
    deadline: "Dec 15, 2026",
    eligibilityStatus: "Requirements Missing",
    score: 78,
    reasons: [
      "High academic reputation alignment in artificial intelligence field.",
      "IELTS score of 7.5 satisfies maximum language requirement."
    ],
    missingReq: "CGPA is 0.05 points below the recommended 3.7 threshold.",
    nextAction: "Complete GRE General Test to supplement academic record."
  }
];
