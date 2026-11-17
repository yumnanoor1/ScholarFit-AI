import { EMPTY_PROFILE, mergeProfile } from '../data/profileModel';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
const GENERIC_SERVER_ERROR = 'Something went wrong on our side. Please try again.';

function extractErrorMessage(data, fallback = 'Request failed') {
  if (!data) return fallback;
  if (typeof data.detail === 'string') return data.detail === GENERIC_SERVER_ERROR ? fallback : data.detail;
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    const first = data.detail[0];
    return first?.msg || fallback;
  }
  if (typeof data.message === 'string') return data.message;
  return fallback;
}

/**
 * Fetch authenticated student's profile from FastAPI
 * Returns { exists: true, data } on 200
 * Returns { exists: false, data: null } on 404
 */
export async function getProfileApi(token) {
  if (!token) {
    return { exists: false, data: null };
  }

  const response = await fetch(`${API_BASE_URL}/profile/`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (response.status === 404) {
    return { exists: false, data: null };
  }

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const errorMsg = extractErrorMessage(data, 'Failed to fetch student profile');
    const error = new Error(errorMsg);
    error.status = response.status;
    throw error;
  }

  return { exists: true, data };
}

/**
 * Whether the signed-in student has finished their profile, worked out by the API from stored data.
 * Returns { required, complete, percent, missing }
 */
export async function getProfileStatusApi(token) {
  const response = await fetch(`${API_BASE_URL}/profile/status`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const error = new Error(extractErrorMessage(data, 'Failed to check your profile'));
    error.status = response.status;
    throw error;
  }

  return data;
}

/**
 * Create a new student profile in FastAPI
 */
export async function createProfileApi(token, payload) {
  const response = await fetch(`${API_BASE_URL}/profile/`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const errorMsg = extractErrorMessage(data, 'Your profile could not be saved. Your information is still available in this form. Please try again.');
    const error = new Error(errorMsg);
    error.status = response.status;
    throw error;
  }

  return data;
}

/**
 * Update existing student profile in FastAPI
 */
export async function updateProfileApi(token, payload) {
  const response = await fetch(`${API_BASE_URL}/profile/`, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const errorMsg = extractErrorMessage(data, 'Your profile changes could not be saved. Your information is still available in this form. Please try again.');
    const error = new Error(errorMsg);
    error.status = response.status;
    throw error;
  }

  return data;
}

/**
 * Maps the frontend multi-step form data into the backend StudentProfile schema
 */
export function mapFrontendToBackendProfile(data, fallback = {}) {
  const section = (name) => ({
    ...(fallback[name] || {}),
    ...(data[name] || {}),
  });
  const academic = section('academicBackground');
  const english = section('englishProficiency');
  const preferences = section('studyPreferences');
  const personal = section('personalInfo');
  const numberOrNull = (value, label) => {
    if (value === '' || value === null || value === undefined) return null;
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
      throw new Error(`${label} must be a valid non-negative number.`);
    }
    return parsed;
  };
  const list = (value) => (Array.isArray(value) ? value : [])
    .map((item) => typeof item === 'string' ? item.trim() : '')
    .filter((item, index, values) => item && values.indexOf(item) === index);
  const stripFiles = (value) => {
    if (typeof File !== 'undefined' && value instanceof File) return undefined;
    if (Array.isArray(value)) return value.map(stripFiles).filter((item) => item !== undefined);
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value)
        .map(([key, item]) => [key, stripFiles(item)])
        .filter(([, item]) => item !== undefined));
    }
    return value;
  };

  const degreeLevel = academic.currentDegree || academic.degreeTitle || fallback.degree_level || fallback.degreeLevel || null;
  const fieldOfStudy = academic.major || academic.degreeTitle || fallback.field_of_study || null;
  const scaleValue = academic.gradingScale === 'Other' ? academic.customGradingScale : academic.gradingScale;
  const cgpa = numberOrNull(academic.cgpa ?? fallback.cgpa, 'CGPA');
  const cgpaScale = numberOrNull(scaleValue ?? fallback.cgpa_scale, 'CGPA scale');
  const countries = list(preferences.countries).filter((country) => country !== 'Other');
  if (preferences.otherCountry?.trim()) countries.push(preferences.otherCountry.trim());

  const currency = String(preferences.currency || 'USD').trim().toUpperCase();
  const tuitionAmount = numberOrNull(preferences.maxTuitionBudget, 'Annual tuition budget');
  const livingAmount = numberOrNull(preferences.maxLivingCostBudget, 'Monthly living budget');
  const testType = english.testType || null;
  const hasEnglishTest = testType !== null && testType !== 'No Test / Not Taken';
  const languageTest = {
    test_type: testType,
    other_test_name: english.otherTestName?.trim() || null,
    overall_score: hasEnglishTest ? numberOrNull(english.overallScore, 'English test score') : null,
    listening: hasEnglishTest ? numberOrNull(english.listening, 'English listening score') : null,
    reading: hasEnglishTest ? numberOrNull(english.reading, 'English reading score') : null,
    writing: hasEnglishTest ? numberOrNull(english.writing, 'English writing score') : null,
    speaking: hasEnglishTest ? numberOrNull(english.speaking, 'English speaking score') : null,
    test_date: english.testDate || null,
    test_status: english.testStatus || null,
    willing_to_test: english.willingToTest || null,
    medium_of_instruction: english.mediumOfInstruction || null,
  };
  const savedDetails = {
    personalInfo: personal,
    academicBackground: academic,
    englishProficiency: english,
    studyPreferences: preferences,
    documentAvailability: data.documentAvailability || fallback.documentAvailability || {},
  };
  const formDetails = stripFiles(savedDetails);
  const legacyBudget = currency === 'USD' ? tuitionAmount : null;
  const preferredFields = list(preferences.fields)
    .filter((field) => field !== 'Other');
  if (preferences.customField?.trim() && !preferredFields.includes(preferences.customField.trim())) {
    preferredFields.push(preferences.customField.trim());
  }
  const preferredDegreeLevels = list(preferences.preferredDegreeLevels);
  if (!preferredDegreeLevels.length && preferences.intendedDegree) {
    preferredDegreeLevels.push(preferences.intendedDegree);
  }

  return {
    degree_level: degreeLevel,
    field_of_study: fieldOfStudy,
    cgpa,
    cgpa_scale: cgpaScale,
    ielts_score: hasEnglishTest && testType === 'IELTS' ? numberOrNull(english.overallScore, 'IELTS score') : null,
    toefl_score: hasEnglishTest && testType === 'TOEFL iBT' ? numberOrNull(english.overallScore, 'TOEFL iBT score') : null,
    skills: [academic.technicalSkills, academic.programmingLanguages].filter(Boolean).join(', ') || null,
    research_interests: academic.projects || null,
    preferred_countries: countries.join(', ') || null,
    budget_usd: legacyBudget,
    preferred_fields: preferredFields,
    preferred_degree_levels: preferredDegreeLevels,
    preferred_funding_types: list(preferences.fundingPreferences),
    funding_preference: preferences.fundingPreference || null,
    language_test: languageTest,
    tuition_budget_amount: tuitionAmount,
    tuition_budget_currency: tuitionAmount === null ? null : currency,
    living_budget_amount: livingAmount,
    living_budget_currency: livingAmount === null ? null : currency,
    form_details: formDetails,
    nationality: personal.citizenshipCountry?.trim() || null,
    date_of_birth: personal.dateOfBirth || null,
    institution: academic.institution?.trim() || null,
    academic_status: academic.academicStatus || null,
    graduation_date: (academic.academicStatus === 'graduated' ? academic.graduationDate : academic.expectedGraduationDate) || null,
    work_experience: academic.workExperience?.trim() || null,
  };
}

/**
 * Maps persisted profile data into the frontend StudentProfile structure.
 */
export function mapBackendToFrontendProfile(backendProfile, user = {}) {
  const storedDetails = backendProfile.form_details && typeof backendProfile.form_details === 'object'
    ? backendProfile.form_details
    : EMPTY_PROFILE;
  const base = mergeProfile(storedDetails || EMPTY_PROFILE);

  const fullName = user.name || user.full_name || base.personalInfo.fullName || '';
  const email = user.email || base.personalInfo.email || '';

  // 1. Personal Information (preserved from user/draft)
  base.personalInfo = {
    ...base.personalInfo,
    fullName: fullName,
    email: email,
    citizenshipCountry: backendProfile.nationality || base.personalInfo.citizenshipCountry || '',
    dateOfBirth: backendProfile.date_of_birth || base.personalInfo.dateOfBirth || '',
  };

  // 2. Academic Background (populated from backend)
  base.academicBackground = {
    ...base.academicBackground,
    currentDegree: backendProfile.degree_level || base.academicBackground.currentDegree || '',
    degreeTitle: base.academicBackground.degreeTitle || backendProfile.degree_level || '',
    major: backendProfile.field_of_study ?? base.academicBackground.major ?? '',
    cgpa: backendProfile.cgpa !== null && backendProfile.cgpa !== undefined ? String(backendProfile.cgpa) : base.academicBackground.cgpa,
    gradingScale: backendProfile.cgpa_scale !== null && backendProfile.cgpa_scale !== undefined ? String(backendProfile.cgpa_scale) : (base.academicBackground.gradingScale || ''),
    technicalSkills: backendProfile.skills || base.academicBackground.technicalSkills || '',
    projects: backendProfile.research_interests || base.academicBackground.projects || '',
    institution: backendProfile.institution || base.academicBackground.institution || '',
    academicStatus: backendProfile.academic_status || base.academicBackground.academicStatus || '',
    workExperience: backendProfile.work_experience || base.academicBackground.workExperience || '',
  };
  if (backendProfile.graduation_date) {
    const dateField = base.academicBackground.academicStatus === 'graduated' ? 'graduationDate' : 'expectedGraduationDate';
    base.academicBackground[dateField] = backendProfile.graduation_date;
  }

  // 3. English Proficiency (the structured test record is authoritative; legacy totals remain readable)
  const languageTest = backendProfile.language_test;
  if (languageTest) {
    base.englishProficiency = {
      ...base.englishProficiency,
      testType: languageTest.test_type || '',
      otherTestName: languageTest.other_test_name || '',
      overallScore: languageTest.overall_score === null || languageTest.overall_score === undefined ? '' : String(languageTest.overall_score),
      listening: languageTest.listening === null || languageTest.listening === undefined ? '' : String(languageTest.listening),
      reading: languageTest.reading === null || languageTest.reading === undefined ? '' : String(languageTest.reading),
      writing: languageTest.writing === null || languageTest.writing === undefined ? '' : String(languageTest.writing),
      speaking: languageTest.speaking === null || languageTest.speaking === undefined ? '' : String(languageTest.speaking),
      testDate: languageTest.test_date || '',
      testStatus: languageTest.test_status || '',
      willingToTest: languageTest.willing_to_test || '',
      mediumOfInstruction: languageTest.medium_of_instruction || '',
    };
  } else if (backendProfile.ielts_score !== null && backendProfile.ielts_score !== undefined) {
    base.englishProficiency = { ...base.englishProficiency, testType: 'IELTS', overallScore: String(backendProfile.ielts_score) };
  } else if (backendProfile.toefl_score !== null && backendProfile.toefl_score !== undefined) {
    base.englishProficiency = { ...base.englishProficiency, testType: 'TOEFL iBT', overallScore: String(backendProfile.toefl_score) };
  }

  // 4. Study Preferences (populated from backend)
  const countriesArray = backendProfile.preferred_countries !== null && backendProfile.preferred_countries !== undefined
    ? backendProfile.preferred_countries.split(',').map((c) => c.trim()).filter(Boolean)
    : (base.studyPreferences.countries || []);
  const fieldsArray = Array.isArray(backendProfile.preferred_fields)
    ? backendProfile.preferred_fields
    : (base.studyPreferences.fields || []);
  const tuitionBudget = backendProfile.tuition_budget_amount ?? backendProfile.budget_usd;
  const tuitionCurrency = backendProfile.tuition_budget_currency
    || (backendProfile.budget_usd !== null && backendProfile.budget_usd !== undefined ? 'USD' : null)
    || backendProfile.living_budget_currency
    || base.studyPreferences.currency;

  base.studyPreferences = {
    ...base.studyPreferences,
    fields: fieldsArray,
    countries: countriesArray,
    preferredDegreeLevels: backendProfile.preferred_degree_levels || base.studyPreferences.preferredDegreeLevels || [],
    intendedDegree: backendProfile.preferred_degree_levels?.[0] || base.studyPreferences.intendedDegree || '',
    fundingPreferences: backendProfile.preferred_funding_types || base.studyPreferences.fundingPreferences || [],
    fundingPreference: backendProfile.funding_preference ?? base.studyPreferences.fundingPreference ?? '',
    maxTuitionBudget: tuitionBudget !== null && tuitionBudget !== undefined
      ? String(tuitionBudget)
      : base.studyPreferences.maxTuitionBudget,
    maxLivingCostBudget: backendProfile.living_budget_amount !== null && backendProfile.living_budget_amount !== undefined
      ? String(backendProfile.living_budget_amount)
      : base.studyPreferences.maxLivingCostBudget,
    currency: tuitionCurrency || 'USD',
  };

  // 5. Top-level convenience properties used by Dashboard, matching, and header
  const skillsList = backendProfile.skills
    ? backendProfile.skills.split(',').map((s) => s.trim()).filter(Boolean)
    : (base.skills || []);

  return {
    ...base,
    id: backendProfile.id,
    user_id: backendProfile.user_id,
    name: fullName,
    firstName: fullName.split(' ')[0] || '',
    lastName: fullName.split(' ').slice(1).join(' '),
    email: email,
    degree: backendProfile.degree_level || base.degree,
    degreeLevel: backendProfile.degree_level || base.degreeLevel,
    university: base.academicBackground.institution || base.university || '',
    cgpa: backendProfile.cgpa !== null && backendProfile.cgpa !== undefined ? String(backendProfile.cgpa) : base.cgpa,
    englishTest: base.englishProficiency.testType || base.englishTest || 'IELTS',
    englishScore: base.englishProficiency.overallScore || base.englishScore || '',
    fieldOfInterest: fieldsArray.join(', ') || base.fieldOfInterest || '',
    skills: skillsList,
    projects: base.academicBackground.projects
      ? base.academicBackground.projects.split(',').map((project) => project.trim()).filter(Boolean)
      : [],
    researchExperience: base.academicBackground.projects || '',
    preferredCountries: countriesArray,
    preferredDegree: backendProfile.preferred_degree_levels?.[0] || base.studyPreferences.intendedDegree || '',
    fundingPreference: backendProfile.funding_preference ?? base.studyPreferences.fundingPreference ?? '',
    fundingPreferences: backendProfile.preferred_funding_types || base.studyPreferences.fundingPreferences || [],
    budget_usd: backendProfile.budget_usd,
    approximateBudget: tuitionBudget !== null && tuitionBudget !== undefined
      ? `${tuitionCurrency || 'USD'} ${Number(tuitionBudget).toLocaleString()} / year`
      : base.approximateBudget,
    // A stored row isn't a finished profile: the API's status decides that, in ProfileContext
    profileComplete: false,
    profileStatus: 'draft',
    verifiedProfile: base,
    hasBackendProfile: true,
  };
}
