/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState } from 'react';
import { mockScholarships, mockUniversities } from '../data/mockData';

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
  const [savedOpportunities, setSavedOpportunities] = useState(["univ-1", "sch-1"]);
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
      if (prev.includes(id)) {
        return prev.filter(savedId => savedId !== id);
      } else {
        return [...prev, id];
      }
    });
  };

  const isOpportunitySaved = (id) => {
    return savedOpportunities.includes(id);
  };

  return (
    <ProfileContext.Provider value={{
      profile,
      loading,
      updateProfile,
      saveCvUpload,
      saveExtractedProfile,
      matchStatistics: calculateMatchStatistics(profile),
      savedOpportunities,
      toggleSaveOpportunity,
      isOpportunitySaved
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