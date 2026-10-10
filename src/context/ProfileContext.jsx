/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState } from 'react';
import { mockScholarships, mockUniversities } from '../data/mockData';
import { getApplicationTaskStatuses, saveApplicationTaskStatuses } from '../services/applicationWorkflow';

const ProfileContext = createContext(null);

const DEFAULT_PROFILE = {
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
  profileCompletionPercentage: 0,
  profileSetupStep: 0,
  profileComplete: false
};

const PROFILE_STORAGE_KEY = 'fitscholar.profile.v2';
const SAVED_OPPORTUNITIES_STORAGE_KEY = 'fitscholar.savedOpportunities.v1';
const DEFAULT_SAVED_OPPORTUNITIES = ['univ-1', 'sch-1'];
const COMPARISON_OPPORTUNITIES_STORAGE_KEY = 'fitscholar.comparisonOpportunities.v1';
const SELECTED_OPPORTUNITIES_STORAGE_KEY = 'fitscholar.selectedOpportunities.v1';
const ACTIVE_OPPORTUNITY_STORAGE_KEY = 'fitscholar.activeOpportunity.v1';
const APPLIED_OPPORTUNITIES_STORAGE_KEY = 'fitscholar.appliedOpportunities.v1';
const DOCUMENT_RECORDS_STORAGE_KEY = 'fitscholar.documentRecords.v1';
const FINANCIAL_BUDGET_STORAGE_KEY = 'fitscholar.financialBudget.v1';

function readJsonStorage(key, fallback) {
  if (typeof window === 'undefined') return fallback;
  try {
    const stored = window.localStorage.getItem(key);
    return stored ? JSON.parse(stored) : fallback;
  } catch {
    return fallback;
  }
}

function persistJsonStorage(key, value) {
  if (typeof window === 'undefined') return false;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    console.error(`Unable to persist ${key} in browser storage.`);
    return false;
  }
}

function readSavedOpportunities() {
  if (typeof window === 'undefined') return DEFAULT_SAVED_OPPORTUNITIES;
  try {
    const saved = window.localStorage.getItem(SAVED_OPPORTUNITIES_STORAGE_KEY);
    if (!saved) return DEFAULT_SAVED_OPPORTUNITIES;
    const parsed = JSON.parse(saved);
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string') : DEFAULT_SAVED_OPPORTUNITIES;
  } catch {
    return DEFAULT_SAVED_OPPORTUNITIES;
  }
}

function readSavedProfile() {
  if (typeof window === 'undefined') return DEFAULT_PROFILE;
  try {
    const savedProfile = window.localStorage.getItem(PROFILE_STORAGE_KEY);
    return savedProfile ? { ...DEFAULT_PROFILE, ...JSON.parse(savedProfile) } : DEFAULT_PROFILE;
  } catch {
    return DEFAULT_PROFILE;
  }
}

function persistProfile(profile) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile, (key, value) => (
      ['profilePhoto', 'transcript', 'moiCertificate'].includes(key) ? null : value
    )));
  } catch {
    return;
  }
}

function getPreferredCountries(value) {
  const countries = Array.isArray(value) ? value : String(value || '').split(',');
  return countries.map((country) => country.trim().toLowerCase()).filter(Boolean);
}

function calculateMatchStatistics(profile) {
  const preferredCountries = getPreferredCountries(profile.preferredCountries);
  const preferredRegions = profile.studyPreferences?.regions || [];
  const countriesByRegion = {
    Europe: ['germany', 'switzerland', 'netherlands', 'sweden', 'finland', 'austria', 'hungary', 'france', 'italy', 'united kingdom'],
    'North America': ['canada', 'united states', 'usa'],
    'Asia-Pacific': ['australia', 'new zealand', 'japan', 'singapore', 'south korea']
  };
  const countryMatches = (country) => (
    (preferredCountries.length === 0 && preferredRegions.length === 0) ||
    country === 'Global' ||
    preferredCountries.includes(country.toLowerCase()) ||
    preferredRegions.some((region) => countriesByRegion[region]?.includes(country.toLowerCase()))
  );
  const cgpa = Number.parseFloat(profile.cgpa);
  const testScore = Number.parseFloat(profile.englishScore);
  const testName = profile.englishTest || 'IELTS';

  const matchingUniversities = mockUniversities.filter((university) => {
    if (!countryMatches(university.country)) return false;
    if (profile.preferredDegree && university.degree !== profile.preferredDegree) return false;

    const requiredCgpa = Number.parseFloat(university.cgpaReq);
    if (Number.isFinite(cgpa) && Number.isFinite(requiredCgpa) && cgpa < requiredCgpa) return false;

    const scoreRequirement = university.englishReq.match(new RegExp(`${testName}\\s*(\\d+(?:\\.\\d+)?)`, 'i'));
    if (scoreRequirement && Number.isFinite(testScore) && testScore < Number(scoreRequirement[1])) return false;

    return true;
  });

  const fundedScholarships = mockScholarships.filter((scholarship) => (
    scholarship.eligibility === 'Eligible' &&
    scholarship.amount > 0 &&
    countryMatches(scholarship.country)
  ));
  const tuitionCosts = matchingUniversities
    .map((university) => Number(university.tuition.replace(/[^\d.]/g, '')))
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  const middle = Math.floor(tuitionCosts.length / 2);
  const medianTuition = tuitionCosts.length === 0
    ? null
    : tuitionCosts.length % 2 === 0
      ? (tuitionCosts[middle - 1] + tuitionCosts[middle]) / 2
      : tuitionCosts[middle];

  return {
    eligibleCount: matchingUniversities.length + fundedScholarships.length,
    fundedCount: profile.fundingPreference === 'Self-Funded' ? 0 : fundedScholarships.length,
    medianTuition: medianTuition === null
      ? 'No matches'
      : `$${Math.round(medianTuition).toLocaleString()} / year`
  };
}

export function ProfileProvider({ children }) {
  const [profile, setProfile] = useState(readSavedProfile);
  const [savedOpportunities, setSavedOpportunities] = useState(readSavedOpportunities);
  const [comparisonOpportunityIds, setComparisonOpportunityIds] = useState(() => {
    const ids = readJsonStorage(COMPARISON_OPPORTUNITIES_STORAGE_KEY, []);
    return Array.isArray(ids) ? [...new Set(ids.filter((id) => typeof id === 'string'))].slice(0, 2) : [];
  });
  const [selectedOpportunities, setSelectedOpportunities] = useState(() => {
    const opportunities = readJsonStorage(SELECTED_OPPORTUNITIES_STORAGE_KEY, []);
    return Array.isArray(opportunities) ? opportunities.filter((item) => item && typeof item.id === 'string') : [];
  });
  const [activeOpportunityId, setActiveOpportunityId] = useState(() => (
    readJsonStorage(ACTIVE_OPPORTUNITY_STORAGE_KEY, null)
  ));
  const [appliedOpportunityIds, setAppliedOpportunityIds] = useState(() => {
    const ids = readJsonStorage(APPLIED_OPPORTUNITIES_STORAGE_KEY, []);
    return Array.isArray(ids) ? ids.filter((id) => typeof id === 'string') : [];
  });
  const [opportunityTaskStatuses, setOpportunityTaskStatuses] = useState(() => {
    const statuses = getApplicationTaskStatuses();
    return statuses && typeof statuses === 'object' && !Array.isArray(statuses) ? statuses : {};
  });
  const [documentRecords, setDocumentRecords] = useState(() => {
    const records = readJsonStorage(DOCUMENT_RECORDS_STORAGE_KEY, {});
    return records && typeof records === 'object' && !Array.isArray(records) ? records : {};
  });
  const [financialBudget, setFinancialBudget] = useState(() => {
    const budget = readJsonStorage(FINANCIAL_BUDGET_STORAGE_KEY, null);
    return budget && typeof budget.amount === 'string' && typeof budget.currency === 'string'
      ? budget
      : { amount: '', currency: '' };
  });
  const [loading, setLoading] = useState(false);

  const saveCvUpload = (fileInfo) => {
    setProfile((current) => {
      const nextProfile = { ...current, cvUpload: fileInfo };
      persistProfile(nextProfile);
      return nextProfile;
    });
  };

  const saveExtractedProfile = ({ extractedProfile, fieldStatuses, fileInfo }) => {
    setProfile((current) => {
      const nextProfile = {
        ...current,
        ...extractedProfile,
        cvUpload: fileInfo,
        extractedProfile,
        profileDraft: extractedProfile,
        extractionFieldStatuses: fieldStatuses,
        fieldStatuses,
        profileMethod: 'cv',
        profileSetupStep: 0,
        profileComplete: false,
        profileCompletionPercentage: 0,
        verifiedProfile: null,
      };
      persistProfile(nextProfile);
      return nextProfile;
    });
  };

  const updateProfile = async (updatedData, progress = { step: 0, complete: false }) => {
    setLoading(true);
    return new Promise((resolve) => {
      setTimeout(() => {
        const personal = updatedData.personalInfo || {};
        const academic = updatedData.academicBackground || {};
        const english = updatedData.englishProficiency || {};
        const preferences = updatedData.studyPreferences || {};
        const fullName = personal.fullName || profile.name || '';
        const preferredCountries = [
          ...(preferences.countries || []).filter((country) => country !== 'Other'),
          ...(preferences.otherCountry ? [preferences.otherCountry] : [])
        ];
        const chosenFunding = preferences.fundingPreferences || [];
        const overallScore = english.overallScore || '';
        const legacyEnglishTest = english.testType === 'TOEFL iBT' ? 'TOEFL' : english.testType || profile.englishTest;
        const graduationDate = academic.academicStatus === 'graduated'
          ? academic.graduationDate
          : academic.expectedGraduationDate;
        const approximateBudget = preferences.maxTuitionBudget
          ? `${preferences.currency || 'USD'} ${preferences.maxTuitionBudget} / year`
          : profile.approximateBudget;
        const isCvSource = progress.source === 'cv';
        const finalProfile = {
          ...profile,
          ...updatedData,
          name: fullName,
          firstName: fullName.split(' ')[0] || '',
          lastName: fullName.split(' ').slice(1).join(' '),
          email: personal.email || profile.email || '',
          degree: academic.degreeTitle || academic.major || profile.degree,
          degreeLevel: academic.currentDegree || profile.degreeLevel,
          university: academic.institution || profile.university,
          cgpa: academic.cgpa || profile.cgpa,
          graduationYear: graduationDate || academic.currentYear || profile.graduationYear,
          englishTest: legacyEnglishTest,
          englishScore: english.testType === 'No Test / Not Taken' ? '' : overallScore || profile.englishScore,
          fieldOfInterest: preferences.fields?.filter((field) => field !== 'Other').join(', ') || preferences.customField || academic.major || profile.fieldOfInterest,
          skills: [academic.technicalSkills, academic.programmingLanguages].filter(Boolean).join(', ').split(',').map((skill) => skill.trim()).filter(Boolean),
          projects: academic.projects ? academic.projects.split(',').map((project) => project.trim()).filter(Boolean) : profile.projects,
          preferredCountries: preferences.countries ? preferredCountries : getPreferredCountries(profile.preferredCountries),
          preferredDegree: "Master's",
          fundingPreference: chosenFunding.join(', ') || profile.fundingPreference,
          approximateBudget,
          profileCompletionPercentage: progress.complete ? 100 : Math.round(((progress.step + 1) / 4) * 100),
          profileSetupStep: progress.complete ? 4 : progress.step + 1,
          profileComplete: Boolean(progress.complete),
          profileStatus: progress.complete ? 'complete' : 'draft',
          profileMethod: isCvSource ? 'cv' : 'manual',
          cvUpload: isCvSource ? profile.cvUpload || null : null,
          extractedProfile: isCvSource ? profile.extractedProfile || null : null,
          extractionFieldStatuses: isCvSource ? profile.extractionFieldStatuses || {} : {},
          profileDraft: updatedData,
          fieldStatuses: progress.fieldStatuses || (isCvSource ? profile.fieldStatuses || {} : {}),
          verifiedProfile: progress.complete ? updatedData : null,
        };
        persistProfile(finalProfile);
        setProfile(finalProfile);
        setLoading(false);
        resolve({ success: true, profile: finalProfile, matchStatistics: calculateMatchStatistics(finalProfile) });
      }, 400);
    });
  };

  const toggleSaveOpportunity = (id) => {
    setSavedOpportunities((prev) => {
      const next = prev.includes(id)
        ? prev.filter((savedId) => savedId !== id)
        : [...prev, id];
      try {
        window.localStorage.setItem(SAVED_OPPORTUNITIES_STORAGE_KEY, JSON.stringify(next));
      } catch {
        return next;
      }
      return next;
    });
  };

  const isOpportunitySaved = (id) => {
    return savedOpportunities.includes(id);
  };

  const toggleComparisonOpportunity = (id) => {
    if (typeof id !== 'string' || !id) {
      throw new Error('A comparison opportunity must have a stable ID.');
    }
    setComparisonOpportunityIds((current) => {
      const next = current.includes(id)
        ? current.filter((selectedId) => selectedId !== id)
        : current.length < 2
          ? [...current, id]
          : current;
      if (next !== current) persistJsonStorage(COMPARISON_OPPORTUNITIES_STORAGE_KEY, next);
      return next;
    });
  };

  const clearComparisonOpportunities = () => {
    persistJsonStorage(COMPARISON_OPPORTUNITIES_STORAGE_KEY, []);
    setComparisonOpportunityIds([]);
  };

  const activeOpportunity = selectedOpportunities.find((item) => item.id === activeOpportunityId) || null;

  const selectOpportunity = (opportunity) => {
    if (!opportunity || typeof opportunity.id !== 'string') {
      throw new Error('A selected opportunity must have a stable ID.');
    }
    const kind = opportunity.kind || (opportunity.id.startsWith('sch-') ? 'scholarship' : 'program');
    const snapshot = { ...opportunity, kind };
    const next = selectedOpportunities.some((item) => item.id === snapshot.id)
      ? selectedOpportunities.map((item) => item.id === snapshot.id ? snapshot : item)
      : [...selectedOpportunities, snapshot];
    persistJsonStorage(SELECTED_OPPORTUNITIES_STORAGE_KEY, next);
    setSelectedOpportunities(next);
    setActiveOpportunityId(snapshot.id);
    persistJsonStorage(ACTIVE_OPPORTUNITY_STORAGE_KEY, snapshot.id);
  };

  const setActiveOpportunity = (id) => {
    if (id !== null && !selectedOpportunities.some((item) => item.id === id)) {
      throw new Error('Only a selected opportunity can become active.');
    }
    setActiveOpportunityId(id);
    persistJsonStorage(ACTIVE_OPPORTUNITY_STORAGE_KEY, id);
  };

  const removeSelectedOpportunity = (id) => {
    const next = selectedOpportunities.filter((item) => item.id !== id);
    persistJsonStorage(SELECTED_OPPORTUNITIES_STORAGE_KEY, next);
    setSelectedOpportunities(next);
    if (activeOpportunityId === id) setActiveOpportunity(null);
  };

  const markOpportunityApplied = (id, applied) => {
    const next = applied
      ? [...new Set([...appliedOpportunityIds, id])]
      : appliedOpportunityIds.filter((item) => item !== id);
    persistJsonStorage(APPLIED_OPPORTUNITIES_STORAGE_KEY, next);
    setAppliedOpportunityIds(next);
  };

  const setOpportunityTaskStatus = (opportunityId, taskId, status) => {
    if (!['todo', 'in-progress', 'done'].includes(status)) {
      throw new Error(`Unsupported task status: ${status}`);
    }
    const next = {
      ...opportunityTaskStatuses,
      [opportunityId]: { ...opportunityTaskStatuses[opportunityId], [taskId]: status },
    };
    saveApplicationTaskStatuses(opportunityId, next[opportunityId]);
    setOpportunityTaskStatuses(next);
  };

  // Stores file metadata only; file contents must go to backend storage. One record per document ID, shared by all opportunities.
  const saveDocumentRecord = (documentId, file) => {
    const previous = documentRecords[documentId];
    const record = {
      fileName: file.name,
      fileSize: file.size,
      uploadedAt: new Date().toISOString(),
      replacedCount: previous ? (previous.replacedCount || 0) + 1 : 0,
      status: 'awaiting-verification',
    };
    const next = { ...documentRecords, [documentId]: record };
    persistJsonStorage(DOCUMENT_RECORDS_STORAGE_KEY, next);
    setDocumentRecords(next);
  };

  const removeDocumentRecord = (documentId) => {
    const next = { ...documentRecords };
    delete next[documentId];
    persistJsonStorage(DOCUMENT_RECORDS_STORAGE_KEY, next);
    setDocumentRecords(next);
  };

  const saveFinancialBudget = (budget) => {
    if (
      !budget ||
      typeof budget.amount !== 'string' ||
      typeof budget.currency !== 'string' ||
      (budget.amount !== '' && (!Number.isFinite(Number(budget.amount)) || Number(budget.amount) < 0))
    ) {
      throw new Error('Enter a valid non-negative total study budget and currency.');
    }
    const next = { amount: budget.amount, currency: budget.currency.trim().toUpperCase() };
    if (!persistJsonStorage(FINANCIAL_BUDGET_STORAGE_KEY, next)) {
      throw new Error('Unable to persist the financial budget in browser storage.');
    }
    setFinancialBudget(next);
  };

  return (
    <ProfileContext.Provider value={{
      documentRecords,
      saveDocumentRecord,
      removeDocumentRecord,
      financialBudget,
      saveFinancialBudget,
      profile,
      loading,
      updateProfile,
      saveCvUpload,
      saveExtractedProfile,
      matchStatistics: calculateMatchStatistics(profile),
      savedOpportunities,
      toggleSaveOpportunity,
      isOpportunitySaved,
      comparisonOpportunityIds,
      toggleComparisonOpportunity,
      clearComparisonOpportunities,
      selectedOpportunities,
      activeOpportunityId,
      activeOpportunity,
      selectOpportunity,
      setActiveOpportunity,
      removeSelectedOpportunity,
      appliedOpportunityIds,
      markOpportunityApplied,
      opportunityTaskStatuses,
      setOpportunityTaskStatus,
    }}>
      {children}
    </ProfileContext.Provider>
  );
}

export function useProfile() {
  const context = useContext(ProfileContext);
  if (!context) {
    throw new Error('useProfile must be used within a ProfileProvider');
  }
  return context;
}