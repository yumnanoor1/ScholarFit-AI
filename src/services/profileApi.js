import { EMPTY_PROFILE } from '../data/profileModel';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

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
    const errorMsg = extractErrorMessage(data, 'Failed to create profile');
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
    const errorMsg = extractErrorMessage(data, 'Failed to update profile');
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
  const academic = data.academicBackground || fallback.academicBackground || {};
  const english = data.englishProficiency || fallback.englishProficiency || {};
  const preferences = data.studyPreferences || fallback.studyPreferences || {};
  const personal = data.personalInfo || fallback.personalInfo || {};

  // 1. degree_level (Required by backend ProfileCreate)
  const degreeLevel = academic.currentDegree || academic.degreeTitle || fallback.degreeLevel || "Bachelor's";

  // 2. field_of_study (Required by backend ProfileCreate)
  // The chosen fields come first: major is filled from this column on load, so it would hide every later edit
  const chosenFields = Array.isArray(preferences.fields) ? preferences.fields.filter((f) => f !== 'Other') : [];
  let fieldOfStudy = [...chosenFields, ...(preferences.customField ? [preferences.customField] : [])].join(', ');
  if (!fieldOfStudy) {
    fieldOfStudy = academic.major || fallback.fieldOfInterest || fallback.field_of_study || 'General';
  }

  // 3. cgpa & cgpa_scale (Required by backend ProfileCreate)
  const chosenScale = academic.gradingScale === 'Other' ? academic.customGradingScale : academic.gradingScale;
  let rawScale = chosenScale ? Number.parseFloat(chosenScale) : null;
  if (rawScale === null || !Number.isFinite(rawScale) || rawScale <= 0) {
    rawScale = fallback.cgpa_scale ? Number.parseFloat(fallback.cgpa_scale) : 4.0;
  }
  if (!rawScale || rawScale <= 0) rawScale = 4.0;

  let rawCgpa = academic.cgpa !== undefined && academic.cgpa !== '' && academic.cgpa !== null
    ? Number.parseFloat(academic.cgpa)
    : null;
  if (rawCgpa === null || !Number.isFinite(rawCgpa)) {
    rawCgpa = fallback.cgpa ? Number.parseFloat(fallback.cgpa) : 0.0;
  }

  // Ensure CGPA is within [0, scale] to prevent backend 400 error
  if (rawCgpa > rawScale) {
    rawCgpa = rawScale;
  }
  if (rawCgpa < 0) {
    rawCgpa = 0.0;
  }

  // 4. English language scores
  const testType = english.testType || fallback.englishTest || '';
  const scoreStr = english.overallScore || fallback.englishScore || '';
  let ieltsScore = null;
  let toeflScore = null;

  if (/ielts/i.test(testType)) {
    const parsed = Number.parseFloat(scoreStr);
    if (Number.isFinite(parsed) && parsed >= 0) ieltsScore = parsed;
  } else if (/toefl/i.test(testType)) {
    const parsed = Number.parseInt(scoreStr, 10);
    if (Number.isFinite(parsed) && parsed >= 0) toeflScore = parsed;
  }

  // 5. skills (comma-separated string)
  const skillsList = [academic.technicalSkills, academic.programmingLanguages].filter(Boolean);
  // A submitted form has the last word, so an optional field can be cleared
  const submittedAcademic = Boolean(data.academicBackground);
  let skills = skillsList.length > 0 || submittedAcademic
    ? skillsList.join(', ')
    : (Array.isArray(fallback.skills) ? fallback.skills.join(', ') : fallback.skills || null);

  // 6. research_interests (string)
  const researchInterests = academic.projects
    || (submittedAcademic ? null : fallback.researchExperience || fallback.research_interests)
    || null;

  // 7. preferred_countries (comma-separated string)
  let countriesList = [];
  if (Array.isArray(preferences.countries)) {
    countriesList = [
      ...preferences.countries.filter((c) => c !== 'Other'),
      ...(preferences.otherCountry ? [preferences.otherCountry] : [])
    ];
  } else if (typeof preferences.countries === 'string' && preferences.countries) {
    countriesList = preferences.countries.split(',').map((c) => c.trim()).filter(Boolean);
  } else if (Array.isArray(fallback.preferredCountries)) {
    countriesList = fallback.preferredCountries;
  }
  const preferredCountries = countriesList.length > 0 ? countriesList.join(',') : null;

  // 8. budget_usd (Float)
  let budgetUsd = null;
  if (preferences.maxTuitionBudget) {
    const parsed = Number.parseFloat(preferences.maxTuitionBudget.toString().replace(/[^\d.]/g, ''));
    if (Number.isFinite(parsed) && parsed >= 0) budgetUsd = parsed;
  } else if (fallback.approximateBudget) {
    const parsed = Number.parseFloat(fallback.approximateBudget.toString().replace(/[^\d.]/g, ''));
    if (Number.isFinite(parsed) && parsed >= 0) budgetUsd = parsed;
  }

  return {
    degree_level: degreeLevel,
    field_of_study: fieldOfStudy,
    cgpa: rawCgpa !== null ? rawCgpa : 0.0,
    cgpa_scale: rawScale,
    ielts_score: ieltsScore,
    toefl_score: toeflScore,
    skills: skills || null,
    research_interests: researchInterests || null,
    preferred_countries: preferredCountries || null,
    budget_usd: budgetUsd,
    // Used by scholarship eligibility (nationality and age limits)
    nationality: (personal.citizenshipCountry || '').trim() || null,
    date_of_birth: /^\d{4}-\d{2}-\d{2}$/.test(personal.dateOfBirth || '') ? personal.dateOfBirth : null,
    // Used by profile improvement guidance
    institution: (academic.institution || '').trim() || null,
    academic_status: academic.academicStatus || null,
    graduation_date: (academic.academicStatus === 'graduated' ? academic.graduationDate : academic.expectedGraduationDate) || null,
    work_experience: (academic.workExperience || '').trim() || null,
  };
}

/**
 * Maps the backend StudentProfile response into the frontend StudentProfile structure,
 * merging with any cached client-side fields to preserve unsupported attributes.
 */
export function mapBackendToFrontendProfile(backendProfile, user = {}, cachedDraft = {}) {
  const base = cachedDraft && cachedDraft.personalInfo
    ? structuredClone(cachedDraft)
    : structuredClone(EMPTY_PROFILE);

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
    currentDegree: backendProfile.degree_level || base.academicBackground.currentDegree || "Bachelor's",
    degreeTitle: base.academicBackground.degreeTitle || backendProfile.degree_level || "Bachelor's",
    major: backendProfile.field_of_study || base.academicBackground.major || '',
    cgpa: backendProfile.cgpa !== null && backendProfile.cgpa !== undefined ? String(backendProfile.cgpa) : base.academicBackground.cgpa,
    gradingScale: backendProfile.cgpa_scale !== null && backendProfile.cgpa_scale !== undefined ? String(backendProfile.cgpa_scale) : (base.academicBackground.gradingScale || '4.00'),
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

  // 3. English Proficiency (populated from backend test scores)
  if (backendProfile.ielts_score !== null && backendProfile.ielts_score !== undefined) {
    base.englishProficiency = {
      ...base.englishProficiency,
      testType: 'IELTS',
      overallScore: String(backendProfile.ielts_score),
    };
  } else if (backendProfile.toefl_score !== null && backendProfile.toefl_score !== undefined) {
    base.englishProficiency = {
      ...base.englishProficiency,
      testType: 'TOEFL iBT',
      overallScore: String(backendProfile.toefl_score),
    };
  }

  // 4. Study Preferences (populated from backend)
  const countriesArray = backendProfile.preferred_countries
    ? backendProfile.preferred_countries.split(',').map((c) => c.trim()).filter(Boolean)
    : (base.studyPreferences.countries || []);

  const fieldsArray = backendProfile.field_of_study
    ? backendProfile.field_of_study.split(',').map((f) => f.trim()).filter(Boolean)
    : (base.studyPreferences.fields || []);

  base.studyPreferences = {
    ...base.studyPreferences,
    fields: fieldsArray,
    countries: countriesArray,
    maxTuitionBudget: backendProfile.budget_usd !== null && backendProfile.budget_usd !== undefined
      ? String(backendProfile.budget_usd)
      : base.studyPreferences.maxTuitionBudget,
    currency: base.studyPreferences.currency || 'USD',
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
    fieldOfInterest: backendProfile.field_of_study || base.fieldOfInterest || '',
    skills: skillsList,
    preferredCountries: countriesArray,
    approximateBudget: backendProfile.budget_usd
      ? `$${backendProfile.budget_usd.toLocaleString()} / year`
      : base.approximateBudget,
    // A stored row isn't a finished profile: the API's status decides that, in ProfileContext
    profileComplete: false,
    profileStatus: 'draft',
    verifiedProfile: base,
    hasBackendProfile: true,
  };
}

