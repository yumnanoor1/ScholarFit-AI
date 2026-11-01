// Profile-vs-program helpers for the Explore list and the program detail page.
// Eligibility itself (CGPA, English, degree) comes from the backend; these only
// add the preference checks the backend does not do and format values for display.

const NOT_PROVIDED = 'Not in your profile';

// Generic campus photos in /public/images (not photos of the specific university)
const PROGRAM_IMAGES = [
  '/images/campus-building.jpg',
  '/images/campus-library.jpg',
  '/images/graduation-students.jpg',
  '/images/study-abroad-banner.jpg',
];

// Official site icons downloaded from each university's website (public/images/universities)
const UNIVERSITY_LOGOS = {
  'Technical University of Munich': '/images/universities/tum.png',
  'Saarland University': '/images/universities/saarland.png',
  'TU Wien': '/images/universities/tuwien.png',
  'Politecnico di Milano': '/images/universities/polimi.svg',
  'KTH Royal Institute of Technology': '/images/universities/kth.png',
  'Aalto University': '/images/universities/aalto.png',
  'Delft University of Technology': '/images/universities/tudelft.png',
  'Institut Polytechnique de Paris': '/images/universities/ipparis.png',
  'Eötvös Loránd University (ELTE)': '/images/universities/elte.png',
  'ETH Zurich': '/images/universities/eth.png',
};

// Scholarship providers -> logo of the awarding body or host university.
// Files go in public/images/universities; until a file exists the UI keeps its icon.
const SCHOLARSHIP_PROVIDER_LOGOS = {
  'German Academic Exchange Service': '/images/universities/daad.png',
  'UT Austin AI Lab': '/images/universities/utaustin.png',
  'Government of Ontario / UofT': '/images/universities/utoronto.png',
};

/** Logo for a university name, or null when we don't have one. */
export function getUniversityLogo(name) {
  return UNIVERSITY_LOGOS[name] || null;
}

/** Logo for a scholarship provider, or null when none is mapped. */
export function getProviderLogo(provider) {
  return SCHOLARSHIP_PROVIDER_LOGOS[provider] || UNIVERSITY_LOGOS[provider] || null;
}

// Site icons downloaded from each scholarship's official website (or its host university's),
// keyed by the domain of the scholarship's official URL.
const SCHOLARSHIP_LOGOS_BY_DOMAIN = {
  'adelaide.edu.au': '/images/universities/adelaide.png',
  'uva.nl': '/images/universities/uva.png',
  'anu.edu.au': '/images/universities/anu.png',
  'chalmers.se': '/images/universities/chalmers.png',
  'chevening.org': '/images/universities/chevening.png',
  'msmt.gov.cz': '/images/universities/msmt.png',
  'daad.de': '/images/universities/daad.png',
  'deutschlandstipendium.de': '/images/universities/deutschlandstipendium.png',
  'eacea.ec.europa.eu': '/images/universities/erasmus.png',
  'campusfrance.org': '/images/universities/campusfrance.png',
  'gatescambridge.org': '/images/universities/gatescambridge.png',
  'tudelft.nl': '/images/universities/tudelft.png',
  'kth.se': '/images/universities/kth.png',
  'universiteitleiden.nl': '/images/universities/leiden.png',
  'maastrichtuniversity.nl': '/images/universities/maastricht.png',
  'unimelb.edu.au': '/images/universities/unimelb.png',
  'studyinnl.org': '/images/universities/studyinnl.png',
  'polimi.it': '/images/universities/polimi.svg',
  'ru.nl': '/images/universities/radboud.png',
  'sciencespo.fr': '/images/universities/sciencespo.png',
  'nawa.gov.pl': '/images/universities/nawa.png',
  'si.se': '/images/universities/si.png',
  'turkiyeburslari.gov.tr': '/images/universities/turkiyeburslari.png',
};

// Listed under another body's website, so matched by name instead
const SCHOLARSHIP_LOGOS_BY_NAME = [
  [/stipendium hungaricum/i, '/images/universities/stipendiumhungaricum.png'],
];

/** Logo for a scholarship (its own or its host university's), or null when we don't have one. */
export function getScholarshipLogo(scholarship) {
  if (!scholarship) return null;
  const byName = SCHOLARSHIP_LOGOS_BY_NAME.find(([pattern]) => pattern.test(scholarship.name || scholarship.title || ''));
  if (byName) return byName[1];
  let host = '';
  try {
    host = new URL(scholarship.sourceUrl || scholarship.applicationUrl || '').hostname;
  } catch {
    host = '';
  }
  const domain = Object.keys(SCHOLARSHIP_LOGOS_BY_DOMAIN).find((key) => host === key || host.endsWith(`.${key}`));
  return domain ? SCHOLARSHIP_LOGOS_BY_DOMAIN[domain] : getProviderLogo(scholarship.provider);
}

/** Stable photo for a program: the same program always gets the same picture. */
export function getProgramImage(id) {
  const number = Number.parseInt(String(id).replace(/\D/g, ''), 10);
  const index = Number.isFinite(number) ? number % PROGRAM_IMAGES.length : 0;
  return PROGRAM_IMAGES[index];
}

function section(profile, name) {
  const verified = profile?.verifiedProfile || profile?.profileDraft || profile || {};
  return verified[name] || profile?.[name] || {};
}

function toNumber(value) {
  const number = Number.parseFloat(String(value ?? '').replace(/[^\d.]/g, ''));
  return Number.isFinite(number) ? number : null;
}

/** The profile values the detail page compares against. */
export function getProfileSnapshot(profile) {
  const academic = section(profile, 'academicBackground');
  const english = section(profile, 'englishProficiency');
  const preferences = section(profile, 'studyPreferences');
  const testType = english.testType && english.testType !== 'No Test / Not Taken' ? english.testType : null;
  return {
    degree: academic.currentDegree || profile?.degreeLevel || null,
    cgpa: toNumber(academic.cgpa ?? profile?.cgpa),
    cgpaScale: toNumber(academic.gradingScale) || 4,
    englishTest: testType,
    englishScore: testType ? toNumber(english.overallScore) : null,
    countries: (preferences.countries || profile?.preferredCountries || []).filter((country) => country && country !== 'Other'),
    fields: [...(preferences.fields || []), preferences.customField].filter((field) => field && field !== 'Other'),
    budget: toNumber(preferences.maxTuitionBudget),
    budgetCurrency: preferences.currency || 'USD',
  };
}

/** "What the program needs" and "what you have" for one backend requirement row. */
export function describeRequirement(requirement, program, snapshot) {
  if (requirement.field === 'cgpa') {
    const yours = snapshot.cgpa != null && snapshot.cgpa > 0
      ? `${snapshot.cgpa} / ${snapshot.cgpaScale}`
      : NOT_PROVIDED;
    return { needs: program.minCgpa != null ? `${program.minCgpa} / 4.0 minimum` : 'Not published', yours };
  }
  if (requirement.field === 'englishScore') {
    const needs = [
      program.minIelts != null ? `IELTS ${program.minIelts}` : null,
      program.minToefl != null ? `TOEFL iBT ${program.minToefl}` : null,
    ].filter(Boolean).join(' or ') || 'Not published';
    const yours = snapshot.englishTest && snapshot.englishScore != null
      ? `${snapshot.englishTest} ${snapshot.englishScore}`
      : NOT_PROVIDED;
    return { needs, yours };
  }
  if (requirement.field === 'degreeLevel') {
    const level = String(program.degree || '').toLowerCase();
    const needs = level.startsWith('phd') ? "Master's degree" : "Bachelor's degree";
    return { needs, yours: snapshot.degree || NOT_PROVIDED };
  }
  return { needs: '—', yours: '—' };
}

/** Tuition vs the student's maximum tuition budget, only when the currencies can be compared. */
export function getBudgetFit(program, snapshot) {
  if (snapshot.budget == null) {
    return { status: 'unknown', message: 'Add a maximum tuition budget to your profile to compare costs.' };
  }
  let tuition = null;
  let currency = snapshot.budgetCurrency;
  if (snapshot.budgetCurrency === program.tuitionCurrency) tuition = program.tuitionAmount;
  else if (snapshot.budgetCurrency === 'USD') tuition = program.tuitionUsd;
  if (tuition == null) {
    currency = program.tuitionCurrency;
    return {
      status: 'unknown',
      message: `Your budget is in ${snapshot.budgetCurrency} and this tuition is in ${currency || 'an unknown currency'}, so they can't be compared directly.`,
    };
  }
  const format = (value) => new Intl.NumberFormat('en', { style: 'currency', currency, maximumFractionDigits: 0 }).format(value);
  if (tuition <= snapshot.budget) {
    return { status: 'within', message: `Tuition of ${format(tuition)} / year is within your ${format(snapshot.budget)} budget.` };
  }
  return { status: 'over', message: `Tuition of ${format(tuition)} / year is ${format(tuition - snapshot.budget)} over your ${format(snapshot.budget)} budget.` };
}

export function getCountryFit(program, snapshot) {
  if (snapshot.countries.length === 0) return { status: 'unknown', message: 'No preferred countries in your profile.' };
  const match = snapshot.countries.some((country) => country.toLowerCase() === String(program.country || '').toLowerCase());
  return match
    ? { status: 'within', message: `${program.country} is one of your preferred countries.` }
    : { status: 'over', message: `${program.country} is not in your preferred countries (${snapshot.countries.join(', ')}).` };
}

export function getFieldFit(program, snapshot) {
  if (snapshot.fields.length === 0 || !program.fieldOfStudy) return { status: 'unknown', message: 'No preferred fields in your profile.' };
  const programField = program.fieldOfStudy.toLowerCase();
  const match = snapshot.fields.some((field) => {
    const value = field.toLowerCase();
    return programField.includes(value) || value.includes(programField);
  });
  return match
    ? { status: 'within', message: `Matches your preferred field (${snapshot.fields.join(', ')}).` }
    : { status: 'over', message: `Your preferred fields are ${snapshot.fields.join(', ')}.` };
}

/** Days until a YYYY-MM-DD deadline, relative to today. */
export function getDeadlineInfo(deadline, today = new Date()) {
  if (!deadline || !/^\d{4}-\d{2}-\d{2}$/.test(deadline)) return null;
  const [year, month, day] = deadline.split('-').map(Number);
  const target = Date.UTC(year, month - 1, day);
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((target - now) / 86400000);
  const label = new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(target);
  return { days, label, passed: days < 0 };
}

export function formatVerifiedDate(value) {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(date);
}
