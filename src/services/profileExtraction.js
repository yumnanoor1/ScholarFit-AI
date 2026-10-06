import { EMPTY_PROFILE, mergeProfile } from '../data/profileModel.ts';

const REQUIRED_FIELDS = [
  'personalInfo.fullName', 'personalInfo.email', 'personalInfo.dateOfBirth',
  'personalInfo.gender', 'personalInfo.citizenshipCountry', 'personalInfo.currentCountry',
  'personalInfo.city', 'personalInfo.phoneNumber', 'academicBackground.currentDegree',
  'academicBackground.degreeTitle', 'academicBackground.major', 'academicBackground.institution',
  'academicBackground.institutionCountry', 'academicBackground.academicStatus',
  'academicBackground.currentYear', 'academicBackground.expectedGraduationDate',
  'academicBackground.graduationDate', 'academicBackground.cgpa', 'academicBackground.gradingScale', 'englishProficiency.testType',
  'academicBackground.relevantCoursework', 'academicBackground.technicalSkills', 'academicBackground.programmingLanguages',
  'englishProficiency.otherTestName', 'englishProficiency.mediumOfInstruction', 'studyPreferences.fields',
  'studyPreferences.countries', 'studyPreferences.fundingPreferences', 'studyPreferences.intake',
  'studyPreferences.studyMode', 'studyPreferences.programPreference', 'studyPreferences.maxTuitionBudget',
  'studyPreferences.maxLivingCostBudget', 'studyPreferences.currency', 'studyPreferences.duration'
];

const OPTIONAL_FIELDS = [
  'personalInfo.profilePhoto', 'academicBackground.transcript', 'academicBackground.certifications',
  'academicBackground.projects', 'englishProficiency.moiCertificate',
  'studyPreferences.additionalPreferences'
];

const REGION_OPTIONS = ['Europe', 'North America', 'Asia-Pacific'];
const COUNTRY_OPTIONS = [
  'Germany', 'Switzerland', 'Netherlands', 'Sweden', 'Finland', 'Austria', 'Hungary',
  'France', 'Italy', 'Canada', 'Australia', 'United States', 'United Kingdom',
];
const FUNDING_OPTIONS = [
  'Fully Funded', 'Mostly Funded', 'Partial Scholarship', 'Tuition Waiver',
  'Research Assistantship (RA)', 'Teaching Assistantship (TA)', 'Self-Funded',
];

function labeledValue(text, labels) {
  const labelPattern = labels.map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const match = text.match(new RegExp(`(?:^|\\n)\\s*(?:${labelPattern})\\s*[:\\-]\\s*([^\\n\\r]+)`, 'i'));
  return match?.[1]?.trim() || '';
}

function normalizeDate(value) {
  const match = value.match(/\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b/);
  if (match) return `${match[1]}-${match[2].padStart(2, '0')}-${match[3].padStart(2, '0')}`;
  const alternate = value.match(/\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b/);
  if (alternate) return `${alternate[3]}-${alternate[2].padStart(2, '0')}-${alternate[1].padStart(2, '0')}`;
  return '';
}

async function readPdfText(file) {
  try {
    const [pdfjs, worker] = await Promise.all([
      import('pdfjs-dist/build/pdf.mjs'),
      import('pdfjs-dist/build/pdf.worker.mjs?url'),
    ]);
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
    const document = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
    const pageLines = [];

    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      const content = await page.getTextContent();
      const lines = [];
      for (const item of content.items) {
        if (!('str' in item) || !item.str.trim()) continue;
        const y = item.transform?.[5] || 0;
        let line = lines.find((candidate) => Math.abs(candidate.y - y) < 2);
        if (!line) {
          line = { y, parts: [] };
          lines.push(line);
        }
        line.parts.push(item.str.trim());
      }
      pageLines.push(...lines.sort((left, right) => right.y - left.y).map((line) => line.parts.join(' ')));
    }

    return pageLines.join('\n');
  } catch {
    throw new Error('This PDF could not be read. Try another file or use a DOCX version.');
  }
}

async function readDocxText(file) {
  try {
    const mammothModule = await import('mammoth');
    const mammoth = mammothModule.default || mammothModule;
    const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() });
    return result.value || '';
  } catch {
    throw new Error('This DOCX could not be read. Try another file or use the CV extraction service.');
  }
}

async function readLegacyDocText(file) {
  try {
    const text = await file.text();
    const printable = Array.from(text).filter((character) => {
      const code = character.charCodeAt(0);
      return code === 9 || code === 10 || code === 13 || (code >= 32 && code <= 126);
    }).length;
    return printable / Math.max(text.length, 1) > 0.8 ? text : '';
  } catch {
    return '';
  }
}

async function readableDocumentText(file) {
  const extension = file.name.split('.').pop()?.toLowerCase();
  if (extension === 'pdf') return readPdfText(file);
  if (extension === 'docx') return readDocxText(file);
  if (extension === 'doc') return readLegacyDocText(file);
  return '';
}

export async function extractProfileFromCv(file, { user, onProgress } = {}) {
  const endpoint = import.meta.env.VITE_CV_EXTRACTION_API_URL;
  if (endpoint) {
    const body = new FormData();
    body.append('file', file);
    const response = await fetch(endpoint, { method: 'POST', body });
    if (!response.ok) throw new Error('The CV extraction service could not process this file.');
    const result = await response.json();
    return {
      ...result,
      profile: mergeProfile(result.profile),
      fieldStatuses: result.fieldStatuses || {},
      source: 'api',
      fileName: file.name,
      fileSize: file.size,
      fileType: file.type || file.name.split('.').pop()?.toUpperCase() || 'Document',
    };
  }

  const profile = structuredClone(EMPTY_PROFILE);
  const fieldStatuses = {};

  for (const path of OPTIONAL_FIELDS) fieldStatuses[path] = 'optional';
  onProgress?.('Reading CV');
  const text = await readableDocumentText(file);

  const accountName = user?.name || '';
  const accountEmail = user?.email || '';
  const personal = profile.personalInfo;
  personal.fullName = labeledValue(text, ['Full Name', 'Name']) || accountName;
  personal.email = text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)?.[0] || accountEmail;
  personal.dateOfBirth = normalizeDate(labeledValue(text, ['Date of Birth', 'DOB', 'Birth Date']));
  personal.gender = labeledValue(text, ['Gender']);
  personal.citizenshipCountry = labeledValue(text, ['Citizenship', 'Nationality']);
  personal.currentCountry = labeledValue(text, ['Current Country', 'Country of Residence']);
  personal.city = labeledValue(text, ['City', 'Location']);
  personal.phoneNumber = labeledValue(text, ['Phone', 'Phone Number', 'Mobile']);

  const academic = profile.academicBackground;
  academic.currentDegree = labeledValue(text, ['Current Degree', 'Degree Level']);
  academic.degreeTitle = labeledValue(text, ['Degree Title', 'Degree', 'Qualification']);
  academic.major = labeledValue(text, ['Major', 'Field of Study', 'Discipline']);
  academic.institution = labeledValue(text, ['University', 'Institution', 'College']);
  academic.institutionCountry = labeledValue(text, ['Country of Institution', 'University Country']);
  academic.currentYear = labeledValue(text, ['Current Semester', 'Current Year', 'Year of Study']);
  const academicStatus = labeledValue(text, ['Academic Status', 'Study Status']);
  academic.academicStatus = /\b(graduated|degree awarded|completed degree)\b/i.test(academicStatus) ? 'graduated' : /\b(studying|enrolled|current student)\b/i.test(academicStatus) ? 'studying' : '';
  academic.graduationDate = normalizeDate(labeledValue(text, ['Graduation Date', 'Date Graduated']));
  academic.expectedGraduationDate = normalizeDate(labeledValue(text, ['Expected Graduation', 'Expected Graduation Date']));
  const gpaMatch = text.match(/\b(?:CGPA|GPA)\s*(?::|-)?\s*(\d{1,3}(?:\.\d+)?)\s*(?:\/\s*(\d{1,3}(?:\.\d+)?))?/i);
  if (gpaMatch) {
    academic.cgpa = gpaMatch[1];
    const scale = gpaMatch[2] || '';
    const normalizedScale = { 4: '4.0', 5: '5.0', 10: '10.0', 100: '100' }[Number(scale)];
    academic.gradingScale = normalizedScale || (scale ? 'Other' : '');
    academic.customGradingScale = academic.gradingScale === 'Other' ? scale : '';
  }
  academic.relevantCoursework = labeledValue(text, ['Relevant Coursework', 'Coursework']);
  academic.technicalSkills = labeledValue(text, ['Technical Skills', 'Skills']);
  academic.programmingLanguages = labeledValue(text, ['Programming Languages', 'Languages']);
  academic.certifications = labeledValue(text, ['Certifications', 'Certificates']);
  academic.projects = labeledValue(text, ['Projects', 'Academic Experience']);

  const english = profile.englishProficiency;
  const testName = labeledValue(text, ['English Test', 'Language Test', 'Test Type']);
  if (/ielts/i.test(testName)) english.testType = 'IELTS';
  else if (/toefl/i.test(testName)) english.testType = 'TOEFL iBT';
  else if (/\bpte\b/i.test(testName)) english.testType = 'PTE';
  else if (/duolingo/i.test(testName)) english.testType = 'Duolingo English Test';
  else if (/no test|not taken/i.test(testName)) english.testType = 'No Test / Not Taken';
  else if (testName) {
    english.testType = 'Other';
    english.otherTestName = testName;
  }
  english.overallScore = labeledValue(text, ['Overall Band', 'Overall Score', 'IELTS Overall', 'TOEFL Total', 'PTE Overall']);
  english.listening = labeledValue(text, ['Listening']);
  english.reading = labeledValue(text, ['Reading']);
  english.writing = labeledValue(text, ['Writing']);
  english.speaking = labeledValue(text, ['Speaking']);
  english.testDate = normalizeDate(labeledValue(text, ['Test Date', 'Exam Date']));
  const moi = labeledValue(text, ['Medium of Instruction', 'Degree Taught in English']);
  if (/\byes\b/i.test(moi)) english.mediumOfInstruction = 'Yes';
  else if (/\bno\b/i.test(moi)) english.mediumOfInstruction = 'No';

  const preferences = profile.studyPreferences;
  preferences.fields = parseList(labeledValue(text, ["Preferred Master's Fields", 'Preferred Fields', 'Study Interests']));
  preferences.customField = labeledValue(text, ['Other Field', 'Other Discipline']);
  const otherCountry = labeledValue(text, ['Other Country']);
  const locationTerms = [
    ...parseList(labeledValue(text, ['Preferred Countries', 'Target Countries', 'Study Destinations'])),
    ...parseList(labeledValue(text, ['Preferred Regions', 'Target Regions'])),
  ];
  for (const term of locationTerms) {
    const region = REGION_OPTIONS.find((option) => option.toLowerCase() === term.toLowerCase());
    const country = COUNTRY_OPTIONS.find((option) => option.toLowerCase() === term.toLowerCase()) ||
      ({ usa: 'United States', uk: 'United Kingdom' })[term.toLowerCase()];
    if (region) preferences.regions.push(region);
    else if (country) preferences.countries.push(country);
    else if (term.toLowerCase() === 'other' && otherCountry) {
      preferences.countries.push('Other');
      preferences.otherCountry = otherCountry;
    } else if (term) {
      preferences.countries.push('Other');
      preferences.otherCountry = term;
    }
  }
  const fundingTerms = parseList(labeledValue(text, ['Funding Preference', 'Funding Requirements', 'Funding Type']));
  preferences.fundingPreferences = fundingTerms.map((term) => (
    FUNDING_OPTIONS.find((option) => option.toLowerCase() === term.toLowerCase())
  )).filter(Boolean);
  const intake = labeledValue(text, ['Preferred Intake', 'Intake']);
  preferences.intake = ['Spring', 'Fall', 'Any'].find((option) => option.toLowerCase() === intake.toLowerCase()) || '';
  const studyMode = labeledValue(text, ['Study Mode', 'Mode of Study']);
  preferences.studyMode = ['On Campus', 'Hybrid', 'Online', 'Flexible'].find((option) => option.toLowerCase() === studyMode.toLowerCase()) || '';
  const programPreference = labeledValue(text, ['Program Preference', 'Program Focus']);
  preferences.programPreference = ['Coursework Focused', 'Research Focused', 'Either'].find((option) => option.toLowerCase() === programPreference.toLowerCase()) || '';
  const duration = labeledValue(text, ['Preferred Duration', 'Program Duration']);
  preferences.duration = ['1 Year', '1.5 Years', '2 Years', 'Flexible'].find((option) => option.toLowerCase() === duration.toLowerCase()) || '';
  const tuitionBudget = labeledValue(text, ['Maximum Tuition Budget', 'Tuition Budget']);
  const livingBudget = labeledValue(text, ['Maximum Living Cost Budget', 'Living Cost Budget']);
  preferences.maxTuitionBudget = parseBudget(tuitionBudget);
  preferences.maxLivingCostBudget = parseBudget(livingBudget);
  const currencyText = `${tuitionBudget} ${livingBudget} ${labeledValue(text, ['Currency'])}`;
  preferences.currency = ['USD', 'EUR', 'GBP', 'CAD', 'AUD'].find((code) => new RegExp(`\\b${code}\\b`, 'i').test(currencyText)) || '';
  preferences.additionalPreferences = labeledValue(text, ['Additional Preferences', 'Study Preferences']);

  const statusesFromProfile = {
    'personalInfo.fullName': personal.fullName,
    'personalInfo.email': text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)?.[0],
    'personalInfo.dateOfBirth': personal.dateOfBirth,
    'personalInfo.gender': personal.gender,
    'personalInfo.citizenshipCountry': personal.citizenshipCountry,
    'personalInfo.currentCountry': personal.currentCountry,
    'personalInfo.city': personal.city,
    'personalInfo.phoneNumber': personal.phoneNumber,
    'academicBackground.currentDegree': academic.currentDegree,
    'academicBackground.degreeTitle': academic.degreeTitle,
    'academicBackground.major': academic.major,
    'academicBackground.institution': academic.institution,
    'academicBackground.institutionCountry': academic.institutionCountry,
    'academicBackground.academicStatus': academic.academicStatus,
    'academicBackground.currentYear': academic.academicStatus === 'studying' ? academic.currentYear : 'not-applicable',
    'academicBackground.cgpa': academic.cgpa,
    'academicBackground.gradingScale': academic.gradingScale,
    'academicBackground.customGradingScale': academic.gradingScale === 'Other' ? academic.customGradingScale : 'not-applicable',
    'academicBackground.expectedGraduationDate': academic.academicStatus === 'studying' ? academic.expectedGraduationDate : academic.academicStatus === 'graduated' ? 'not-applicable' : '',
    'academicBackground.graduationDate': academic.academicStatus === 'graduated' ? academic.graduationDate : academic.academicStatus === 'studying' ? 'not-applicable' : '',
    'academicBackground.relevantCoursework': academic.relevantCoursework,
    'academicBackground.technicalSkills': academic.technicalSkills,
    'academicBackground.programmingLanguages': academic.programmingLanguages,
    'englishProficiency.testType': english.testType,
    'englishProficiency.otherTestName': english.otherTestName,
    'englishProficiency.overallScore': english.overallScore,
    'englishProficiency.listening': english.listening,
    'englishProficiency.reading': english.reading,
    'englishProficiency.writing': english.writing,
    'englishProficiency.speaking': english.speaking,
    'englishProficiency.testDate': english.testDate,
    'englishProficiency.mediumOfInstruction': english.mediumOfInstruction,
    'studyPreferences.fields': preferences.fields.length,
    'studyPreferences.countries': preferences.countries.length,
    'studyPreferences.fundingPreferences': preferences.fundingPreferences.length,
    'studyPreferences.intake': preferences.intake,
    'studyPreferences.studyMode': preferences.studyMode,
    'studyPreferences.programPreference': preferences.programPreference,
    'studyPreferences.maxTuitionBudget': preferences.maxTuitionBudget,
    'studyPreferences.maxLivingCostBudget': preferences.maxLivingCostBudget,
    'studyPreferences.currency': preferences.currency,
    'studyPreferences.duration': preferences.duration,
  };

  for (const path of REQUIRED_FIELDS) {
    const value = statusesFromProfile[path];
    fieldStatuses[path] = value ? 'extracted' : 'missing';
  }
  fieldStatuses['academicBackground.customGradingScale'] = academic.gradingScale === 'Other'
    ? academic.customGradingScale ? 'extracted' : 'missing'
    : 'not-applicable';
  fieldStatuses['studyPreferences.customField'] = preferences.fields.includes('Other')
    ? preferences.customField ? 'extracted' : 'missing'
    : 'not-applicable';
  fieldStatuses['studyPreferences.otherCountry'] = preferences.countries.includes('Other')
    ? preferences.otherCountry ? 'extracted' : 'missing'
    : 'not-applicable';
  fieldStatuses['studyPreferences.regions'] = preferences.regions.length
    ? 'extracted'
    : preferences.countries.length ? 'not-applicable' : 'missing';
  if (preferences.regions.length && !preferences.countries.length) fieldStatuses['studyPreferences.countries'] = 'not-applicable';
  if (accountName && !labeledValue(text, ['Full Name', 'Name'])) fieldStatuses['personalInfo.fullName'] = 'account';
  if (accountEmail && !text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)) fieldStatuses['personalInfo.email'] = 'account';

  const testScoresRequired = !['', 'No Test / Not Taken'].includes(english.testType);
  if (!testScoresRequired) {
    for (const path of ['englishProficiency.overallScore', 'englishProficiency.listening', 'englishProficiency.reading', 'englishProficiency.writing', 'englishProficiency.speaking', 'englishProficiency.testDate']) {
      fieldStatuses[path] = 'optional';
    }
  }
  if (!['IELTS', 'TOEFL iBT', 'PTE'].includes(english.testType)) {
    for (const path of ['englishProficiency.listening', 'englishProficiency.reading', 'englishProficiency.writing', 'englishProficiency.speaking']) {
      fieldStatuses[path] = 'optional';
    }
  }
  if (english.testType !== 'Other') fieldStatuses['englishProficiency.otherTestName'] = 'not-applicable';

  onProgress?.('Preparing profile');
  return {
    profile,
    fieldStatuses,
    source: text ? 'local-demo-parser' : 'no-readable-text',
    fileName: file.name,
    fileSize: file.size,
    fileType: file.type || file.name.split('.').pop()?.toUpperCase() || 'Document',
  };
}

function parseList(value) {
  return value.split(/[,;|]/).map((item) => item.trim()).filter(Boolean);
}

function parseBudget(value) {
  const amount = value.match(/\d[\d,]*(?:\.\d+)?/)?.[0];
  return amount ? amount.replace(/,/g, '') : '';
}