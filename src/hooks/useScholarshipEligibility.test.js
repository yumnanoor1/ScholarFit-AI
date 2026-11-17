import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

let vite;
let buildEligibilityProfileKey;

function profileWithPreferences() {
  return {
    profileStatus: 'complete',
    degreeLevel: "Bachelor's",
    cgpa: '3.4',
    englishTest: 'IELTS',
    englishScore: '7',
    academicBackground: {
      currentDegree: "Bachelor's",
      cgpa: '3.4',
      gradingScale: '4.00',
      major: 'Computer Science',
      institution: 'Example University',
    },
    englishProficiency: {
      testType: 'IELTS',
      overallScore: '7',
      mediumOfInstruction: 'No',
    },
    personalInfo: {
      citizenshipCountry: 'Pakistan',
      dateOfBirth: '2000-01-01',
      fullName: 'Example Student',
    },
    studyPreferences: {
      fields: ['Computer Science'],
      preferredDegreeLevels: ["Master's"],
      fundingPreference: 'Fully funded only',
      fundingPreferences: ['Tuition waivers'],
      countries: ['Germany'],
      maxTuitionBudget: '1000',
    },
  };
}

before(async () => {
  vite = await createServer({
    configFile: false,
    envDir: fileURLToPath(new URL('.', import.meta.url)),
    resolve: { alias: { '@': fileURLToPath(new URL('..', import.meta.url)) } },
    server: { middlewareMode: true, hmr: false, ws: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
    appType: 'custom',
    logLevel: 'silent',
  });
  ({ buildEligibilityProfileKey } = await vite.ssrLoadModule('/src/hooks/useScholarshipEligibility.js'));
});

after(async () => {
  await vite?.close();
});

test('eligibility profile key changes when persisted eligibility preferences change', () => {
  const base = profileWithPreferences();
  const baseKey = buildEligibilityProfileKey(base);
  const changes = [
    (profile) => { profile.studyPreferences.fields = ['Mathematics']; },
    (profile) => { profile.studyPreferences.preferredDegreeLevels = ["Doctorate"]; },
    (profile) => { profile.studyPreferences.fundingPreference = 'Tuition only'; },
    (profile) => { profile.studyPreferences.fundingPreferences = ['Stipend']; },
    (profile) => { profile.englishProficiency.mediumOfInstruction = 'Yes'; },
  ];

  for (const change of changes) {
    const updated = structuredClone(base);
    change(updated);
    assert.notEqual(buildEligibilityProfileKey(updated), baseKey);
  }
});

test('eligibility profile key ignores unrelated profile changes and preference ordering', () => {
  const base = profileWithPreferences();
  const updated = structuredClone(base);
  updated.academicBackground.major = 'Applied Mathematics';
  updated.academicBackground.institution = 'Different University';
  updated.personalInfo.fullName = 'Different Student';
  updated.studyPreferences.countries = ['France'];
  updated.studyPreferences.maxTuitionBudget = '5000';
  updated.studyPreferences.fields = [' COMPUTER SCIENCE '];
  updated.studyPreferences.preferredDegreeLevels = ["MASTER'S"];
  updated.studyPreferences.fundingPreference = '  FULLY   FUNDED ONLY ';
  updated.studyPreferences.fundingPreferences = [' TUITION WAIVERS '];

  assert.equal(buildEligibilityProfileKey(updated), buildEligibilityProfileKey(base));
});

test('eligibility profile key distinguishes preference text the backend compares literally', () => {
  const base = profileWithPreferences();
  const changedField = structuredClone(base);
  changedField.studyPreferences.fields = ['Computer  Science'];
  assert.notEqual(buildEligibilityProfileKey(changedField), buildEligibilityProfileKey(base));

  const changedFundingType = structuredClone(base);
  changedFundingType.studyPreferences.fundingPreferences = ['Tuition  waivers'];
  assert.notEqual(buildEligibilityProfileKey(changedFundingType), buildEligibilityProfileKey(base));
});
