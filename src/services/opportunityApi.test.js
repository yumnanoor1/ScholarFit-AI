import test from 'node:test';
import assert from 'node:assert/strict';
import {
  getUnavailableEligibility,
  getEligibilityErrorState,
  fetchScholarshipRecommendation,
  mapScholarshipToFrontend,
} from './opportunityApi.js';

test('scholarship documents come from the stored list', () => {
  const mapped = mapScholarshipToFrontend({
    id: 12,
    verification_status: 'verified',
    verification_basis: 'official_source',
    official_info_url: 'https://example.org/scholarship',
    last_verified_date: '2026-10-01',
    application_channel: 'direct',
    required_documents_list: ['CV', ' Academic transcripts ', '', null],
  });
  const documents = mapped.requiredDocuments;
  assert.equal(mapped.applicationChannel, 'direct');
  assert.deepEqual(documents, [
    { id: 'cv', name: 'CV', sourceStatus: 'official-verified' },
    { id: 'academic-transcripts', name: 'Academic transcripts', sourceStatus: 'official-verified' },
  ]);
  assert.deepEqual(mapScholarshipToFrontend({ id: 13 }).requiredDocuments, []);
});

test('scholarship documents fall back to original wording when no structured list exists', () => {
  const documents = mapScholarshipToFrontend({
    id: 14,
    verification_status: 'verified',
    verification_basis: 'official_source',
    official_info_url: 'https://example.org/scholarship',
    last_verified_date: '2026-10-01',
    required_documents: '1. CV; Academic transcripts,\nPassport',
    required_documents_list: [],
  }).requiredDocuments;
  assert.deepEqual(documents, [
    { id: 'cv', name: 'CV', sourceStatus: 'official-verified' },
    { id: 'academic-transcripts', name: 'Academic transcripts', sourceStatus: 'official-verified' },
    { id: 'passport', name: 'Passport', sourceStatus: 'official-verified' },
  ]);
});

test('structured scholarship document names take precedence over original wording', () => {
  const documents = mapScholarshipToFrontend({
    id: 15,
    required_documents: 'Legacy wording',
    required_documents_list: ['Current list'],
  }).requiredDocuments;
  assert.deepEqual(documents.map(({ name }) => name), ['Current list']);
});

test('unavailable states carry no fabricated requirements', () => {
  for (const state of ['logged-out', 'no-profile', 'not-found', 'error']) {
    const result = getUnavailableEligibility(state);
    assert.deepEqual(result.requirements, []);
    assert.equal(result.source, 'unavailable');
    assert.ok(result.message.length > 0);
  }
  assert.equal(getUnavailableEligibility('no-profile').status, 'missing-information');
  assert.equal(getUnavailableEligibility('profile-incomplete').status, 'missing-information');
  assert.equal(getUnavailableEligibility('logged-out').status, 'awaiting-verification');
});

test('HTTP errors map to the right unavailable state', () => {
  assert.equal(getEligibilityErrorState({ status: 401, message: 'Invalid token' }), 'logged-out');
  assert.equal(getEligibilityErrorState({ status: 403, code: 'profile_incomplete' }), 'profile-incomplete');
  assert.equal(getEligibilityErrorState({ status: 404, message: 'Profile not created yet. Create one first with POST /profile/' }), 'no-profile');
  assert.equal(getEligibilityErrorState({ status: 404, message: 'Scholarship not found' }), 'not-found');
  assert.equal(getEligibilityErrorState({ status: 500, message: 'boom' }), 'error');
  assert.equal(getEligibilityErrorState(new TypeError('Failed to fetch')), 'error');
});

test('recommendation profile gate preserves the incomplete-profile state', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 403,
    json: async () => ({ detail: { code: 'profile_incomplete', message: 'Complete your profile.' } }),
  });
  try {
    await assert.rejects(
      fetchScholarshipRecommendation('token', 'sch-db-12'),
      (error) => {
        assert.equal(getEligibilityErrorState(error), 'profile-incomplete');
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
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
  const result = getUnavailableEligibility('no-profile');
  assert.deepEqual(result.requirements, []);
  assert.match(result.message, /scholarship/);
});

import { getImprovementQuery } from './opportunityApi.js';

test('guidance query uses persisted scholarship IDs and ignores non-database selections', () => {
  assert.deepEqual(getImprovementQuery({ id: 'sch-db-12', kind: 'scholarship' }), { scholarship_id: 12 });
  assert.equal(getImprovementQuery({ id: '3', kind: 'scholarship' }), null);
  assert.equal(getImprovementQuery({ id: 'sch-1', kind: 'scholarship' }), null);
  assert.equal(getImprovementQuery(null), null);
});
