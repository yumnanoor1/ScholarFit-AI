import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mapEligibilityToFrontend,
  getUnavailableEligibility,
  getEligibilityErrorState,
  mapScholarshipToFrontend,
} from './opportunityApi.js';

test('scholarship documents come from the stored list', () => {
  const documents = mapScholarshipToFrontend({
    id: 12, verification_status: 'verified', required_documents_list: ['CV', ' Academic transcripts ', '', null],
  }).requiredDocuments;
  assert.deepEqual(documents, [
    { id: 'cv', name: 'CV', sourceStatus: 'official-verified' },
    { id: 'academic-transcripts', name: 'Academic transcripts', sourceStatus: 'official-verified' },
  ]);
  assert.deepEqual(mapScholarshipToFrontend({ id: 13 }).requiredDocuments, []);
});

function backendResult(overrides = {}) {
  return {
    program_id: 1,
    program_name: 'Computer Science (M.Sc.)',
    university_name: 'Saarland University',
    status: 'eligible',
    eligible: true,
    matched_requirements: [
      { requirement: 'cgpa', status: 'satisfied', message: 'Your CGPA (3.8/4.0) meets the minimum of 3.0' },
      { requirement: 'english', status: 'satisfied', message: 'Your IELTS (7.5) meets the minimum of 7.0' },
      { requirement: 'degree_level', status: 'satisfied', message: "Your Bachelor's degree is the right level" },
    ],
    missing_requirements: [],
    notes: ['Meeting these minimums does not guarantee admission'],
    ...overrides,
  };
}

test('eligible result maps every requirement to satisfied with page fields', () => {
  const result = mapEligibilityToFrontend(backendResult());
  assert.equal(result.status, 'satisfied');
  assert.equal(result.source, 'backend');
  assert.deepEqual(result.requirements.map((r) => [r.field, r.status]), [
    ['cgpa', 'satisfied'],
    ['englishScore', 'satisfied'],
    ['degreeLevel', 'satisfied'],
  ]);
  assert.deepEqual(result.notes, ['Meeting these minimums does not guarantee admission']);
});

test('not-eligible keeps satisfied and unmet requirements distinct', () => {
  const result = mapEligibilityToFrontend(backendResult({
    status: 'not-eligible',
    eligible: false,
    matched_requirements: [{ requirement: 'english', status: 'satisfied', message: 'ok' }],
    missing_requirements: [{ requirement: 'cgpa', status: 'not-satisfied', message: 'below' }],
  }));
  assert.equal(result.status, 'not-satisfied');
  assert.equal(result.requirements.find((r) => r.field === 'cgpa').status, 'not-satisfied');
  assert.equal(result.requirements.find((r) => r.field === 'englishScore').status, 'satisfied');
});

test('missing English score maps to missing-information', () => {
  const result = mapEligibilityToFrontend(backendResult({
    status: 'missing-information',
    eligible: false,
    matched_requirements: [{ requirement: 'cgpa', status: 'satisfied', message: 'ok' }],
    missing_requirements: [{ requirement: 'english', status: 'missing-information', message: 'No English test score' }],
  }));
  assert.equal(result.status, 'missing-information');
  assert.equal(result.requirements.find((r) => r.field === 'englishScore').status, 'missing-information');
});

test('not-evaluated maps to awaiting-verification with a message', () => {
  const result = mapEligibilityToFrontend(backendResult({
    status: 'not-evaluated',
    eligible: false,
    matched_requirements: [{ requirement: 'degree_level', status: 'satisfied', message: 'ok' }],
  }));
  assert.equal(result.status, 'awaiting-verification');
  assert.ok(result.message.length > 0);
});

test('eligible flag alone never produces satisfied', () => {
  const noRequirements = mapEligibilityToFrontend(backendResult({ matched_requirements: [] }));
  assert.equal(noRequirements.status, 'awaiting-verification');

  // Older backend without per-requirement status: nothing is assumed satisfied
  const legacy = mapEligibilityToFrontend({
    eligible: true,
    matched_requirements: [{ requirement: 'cgpa', message: 'ok' }],
    missing_requirements: [],
    notes: [],
  });
  assert.equal(legacy.status, 'awaiting-verification');
  assert.equal(legacy.requirements[0].status, 'awaiting-verification');

  // Contradictory payload is downgraded to the worst requirement status
  const contradictory = mapEligibilityToFrontend(backendResult({
    missing_requirements: [{ requirement: 'english', status: 'not-satisfied', message: 'below' }],
  }));
  assert.equal(contradictory.status, 'not-satisfied');
});

test('unavailable states carry no fabricated requirements', () => {
  for (const state of ['logged-out', 'no-profile', 'not-found', 'error']) {
    const result = getUnavailableEligibility(state);
    assert.deepEqual(result.requirements, []);
    assert.equal(result.source, 'unavailable');
    assert.ok(result.message.length > 0);
  }
  assert.equal(getUnavailableEligibility('no-profile').status, 'missing-information');
  assert.equal(getUnavailableEligibility('logged-out').status, 'awaiting-verification');
});

test('HTTP errors map to the right unavailable state', () => {
  assert.equal(getEligibilityErrorState({ status: 401, message: 'Invalid token' }), 'logged-out');
  assert.equal(getEligibilityErrorState({ status: 404, message: 'Profile not created yet. Create one first with POST /profile/' }), 'no-profile');
  assert.equal(getEligibilityErrorState({ status: 404, message: 'Program not found' }), 'not-found');
  assert.equal(getEligibilityErrorState({ status: 500, message: 'boom' }), 'error');
  assert.equal(getEligibilityErrorState(new TypeError('Failed to fetch')), 'error');
});

// ---------------------------------------------------------------------------
// Scholarship eligibility mapping
// ---------------------------------------------------------------------------
import { mapScholarshipEligibilityToFrontend } from './opportunityApi.js';

function scholarshipResult(overrides = {}) {
  return {
    scholarship_id: 12,
    scholarship_name: 'KTH Scholarship',
    status: 'missing_information',
    eligible: false,
    summary: 'Some information needed for this scholarship is missing from your profile.',
    satisfied: [{ requirement: 'degree_level', label: 'Degree level', status: 'satisfied', reason: 'OK', source_text: "Master's", scope: 'scholarship' }],
    not_satisfied: [],
    missing_information: [{ requirement: 'nationality', label: 'Nationality', status: 'missing_information', reason: 'Add your country', source_text: 'Open to all non-EU/EEA nationalities', scope: 'scholarship' }],
    needs_verification: [{ requirement: 'english', label: 'English language', status: 'not_evaluated', reason: 'Set by the university', source_text: 'Yes - per KTH', scope: 'admission' }],
    deadline: { status: 'open', date: '2026-12-08', days_left: 40, text: '8 December 2026' },
    official_url: 'https://www.kth.se',
    last_verified: '2026-09-30',
    verification_status: 'verified',
    notes: ['Meeting the stated requirements does not mean you will be selected or receive funding.'],
    match_score: null,
    ...overrides,
  };
}

test('scholarship statuses map to the statuses the pages render', () => {
  assert.equal(mapScholarshipEligibilityToFrontend(scholarshipResult()).status, 'missing-information');
  assert.equal(mapScholarshipEligibilityToFrontend(scholarshipResult({ status: 'eligible' })).status, 'satisfied');
  assert.equal(mapScholarshipEligibilityToFrontend(scholarshipResult({ status: 'not_eligible' })).status, 'not-satisfied');
  assert.equal(mapScholarshipEligibilityToFrontend(scholarshipResult({ status: 'not_evaluated' })).status, 'awaiting-verification');
});

test('scholarship requirements keep their reason, original text and scope', () => {
  const { requirements, deadline, officialUrl } = mapScholarshipEligibilityToFrontend(scholarshipResult());
  const english = requirements.find((item) => item.id === 'english');
  assert.equal(english.status, 'awaiting-verification');
  assert.equal(english.scope, 'admission');
  assert.equal(english.sourceText, 'Yes - per KTH');
  assert.equal(requirements.find((item) => item.id === 'nationality').message, 'Add your country');
  assert.equal(deadline.days_left, 40);
  assert.equal(officialUrl, 'https://www.kth.se');
});

test('unavailable scholarship eligibility never fabricates requirements', () => {
  const result = getUnavailableEligibility('no-profile', 'scholarship');
  assert.deepEqual(result.requirements, []);
  assert.match(result.message, /scholarship/);
});


import { getImprovementQuery } from './opportunityApi.js';

test('guidance query uses backend IDs and ignores sample selections', () => {
  assert.deepEqual(getImprovementQuery({ id: '3', _numericId: 3, kind: 'program' }), { program_id: 3 });
  assert.deepEqual(getImprovementQuery({ id: 'sch-db-12', kind: 'scholarship' }), { scholarship_id: 12 });
  assert.equal(getImprovementQuery({ id: 'univ-1', kind: 'program' }), null);
  assert.equal(getImprovementQuery({ id: 'sch-1', kind: 'scholarship' }), null);
  assert.equal(getImprovementQuery(null), null);
});
