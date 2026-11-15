import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import {
  applyCandidateDraft,
  buildBulkDecisionSteps,
  buildEditableCandidateDraft,
  buildReviewDecisionPayload,
  canResolveSelection,
  createActionGuard,
  createLatestRequestGuard,
  findPossibleDuplicates,
  getCandidateDeadline,
  getCandidateEvidenceStrength,
  getDiscoveryCandidateCounts,
  getDuplicateResolution,
  getEvidenceQuoteFor,
  getReviewDecisionAnnouncement,
  getReviewQueueViewState,
  getReviewReasons,
  getReviewStatusLabel,
  getRunLabel,
  getSourceDomain,
  groupReviewReasons,
  hasCandidateEdits,
  isResolvableReviewItem,
  normalizeCandidateName,
  REVIEW_STATUS_LABELS,
} from './discoveryReviewState.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function applyGuardedResponse(guard, requestId, promise, state) {
  return promise
    .then((value) => {
      if (guard.isCurrent(requestId)) {
        state.value = value;
        state.error = '';
      }
    })
    .catch((failure) => {
      if (guard.isCurrent(requestId)) state.error = failure.message;
    });
}

test('only the latest queue request may update results', () => {
  const guard = createLatestRequestGuard();
  const olderRequest = guard.begin();
  const newerRequest = guard.begin();

  assert.equal(guard.isCurrent(olderRequest), false);
  assert.equal(guard.isCurrent(newerRequest), true);

  guard.invalidate();
  assert.equal(guard.isCurrent(newerRequest), false);
});

test('monitoring candidate counts distinguish pending from all review items', () => {
  assert.deepEqual(
    getDiscoveryCandidateCounts({ review_queue_pending: 3, candidates_total: 8 }),
    { awaitingReview: 3, totalReviewCandidates: 8 },
  );
  assert.deepEqual(
    getDiscoveryCandidateCounts({ review_queue_pending: null, candidates_total: undefined }),
    { awaitingReview: 0, totalReviewCandidates: 0 },
  );
  assert.deepEqual(getDiscoveryCandidateCounts(null), {
    awaitingReview: 0,
    totalReviewCandidates: 0,
  });
});

test('an older successful monitoring response cannot overwrite a newer response', async () => {
  const guard = createLatestRequestGuard();
  const state = { value: null, error: '' };
  const older = deferred();
  const newer = deferred();
  const olderRequest = guard.begin();
  const olderResponse = applyGuardedResponse(guard, olderRequest, older.promise, state);
  const newerRequest = guard.begin();
  const newerResponse = applyGuardedResponse(guard, newerRequest, newer.promise, state);

  newer.resolve('new monitoring');
  await newerResponse;
  older.resolve('stale monitoring');
  await olderResponse;

  assert.equal(state.value, 'new monitoring');
  assert.equal(state.error, '');
});

test('an older failed monitoring response cannot overwrite a newer success', async () => {
  const guard = createLatestRequestGuard();
  const state = { value: null, error: '' };
  const older = deferred();
  const newer = deferred();
  const olderRequest = guard.begin();
  const olderResponse = applyGuardedResponse(guard, olderRequest, older.promise, state);
  const newerRequest = guard.begin();
  const newerResponse = applyGuardedResponse(guard, newerRequest, newer.promise, state);

  newer.resolve('new monitoring');
  await newerResponse;
  older.reject(new Error('stale failure'));
  await olderResponse;

  assert.equal(state.value, 'new monitoring');
  assert.equal(state.error, '');
});

test('README documents the Admin document-version review route', async () => {
  const readme = await readFile(new URL('../../README.md', import.meta.url), 'utf8');

  assert.ok(readme.includes('POST /admin/scholarships/{scholarship_id}/documents/{version_id}/review'));
  assert.ok(readme.includes('An Admin can approve or reject a document version through'));
  assert.ok(!readme.includes('A document-version approval endpoint is not present'));
});

test('only one review action may be active at a time', () => {
  const guard = createActionGuard();

  assert.equal(guard.tryStart(), true);
  assert.equal(guard.isActive(), true);
  assert.equal(guard.tryStart(), false);
  guard.finish();
  assert.equal(guard.tryStart(), true);
});

test('queue view state distinguishes loading, empty, results and error', () => {
  assert.equal(getReviewQueueViewState({ loading: true, error: '', result: null }), 'loading');
  assert.equal(getReviewQueueViewState({ loading: false, error: '', result: { items: [] } }), 'empty');
  assert.equal(getReviewQueueViewState({ loading: false, error: '', result: { items: [{ id: 1 }] } }), 'results');
  assert.equal(getReviewQueueViewState({ loading: false, error: 'Request failed', result: null }), 'error');
});

test('successful acceptance, rejection and duplicate decisions have explicit feedback', () => {
  assert.equal(
    getReviewDecisionAnnouncement('accepted', { accepted_scholarship_id: 17 }),
    'Candidate accepted; unverified scholarship #17 created.',
  );
  assert.equal(getReviewDecisionAnnouncement('rejected', {}), 'Candidate rejected.');
  assert.equal(
    getReviewDecisionAnnouncement('duplicate', { duplicate_of_scholarship_id: 9 }),
    'Candidate marked as a duplicate of scholarship #9; no records were merged.',
  );
  assert.equal(
    getReviewDecisionAnnouncement('link_and_publish', { accepted_scholarship_id: 17 }),
    'Discovery published and linked to scholarship #17; canonical fields were not overwritten.',
  );
});

test('link-and-publish action maps values and target without changing canonical fields', () => {
  assert.deepEqual(
    buildReviewDecisionPayload('link_and_publish', {
      values: { name: 'Existing Award', country: 'Finland' },
      linkToScholarshipId: '17',
    }),
    {
      decision: 'link_and_publish',
      values: { name: 'Existing Award', country: 'Finland' },
      link_to_scholarship_id: 17,
    },
  );
  assert.throws(
    () => buildReviewDecisionPayload('link_and_publish', { values: {}, linkToScholarshipId: 'invalid' }),
    /existing scholarship ID/,
  );
});

// --- evidence strength, review reasons, bulk decisions --------------------

function candidate(overrides = {}) {
  return {
    id: 7,
    review_status: 'pending',
    extracted_values: { name: 'Award', country: 'Germany', deadline: '30 June' },
    missing_required_fields: [],
    conflicting_values: [],
    review_reason: 'admin_review_required',
    evidence_excerpts: [
      {
        fingerprint: 'a'.repeat(64),
        evidence_excerpts: { name: 'The Award', country: 'hosted in Germany' },
      },
    ],
    ...overrides,
  };
}

test('evidence strength counts the fields that carry a quote', () => {
  const strength = getCandidateEvidenceStrength(candidate());
  assert.equal(strength.backed, 2);
  assert.equal(strength.total, 3);
  assert.equal(strength.summary, '2/3 fields quoted');
  assert.equal(strength.label, 'Partial');
});

test('evidence strength is Strong when nearly everything is quoted', () => {
  const strength = getCandidateEvidenceStrength(candidate({
    extracted_values: { name: 'Award', country: 'Germany' },
  }));
  assert.equal(strength.summary, '2/2 fields quoted');
  assert.equal(strength.label, 'Strong');
});

test('evidence strength flags missing and conflicting fields', () => {
  const strength = getCandidateEvidenceStrength(candidate({
    missing_required_fields: ['degree_level'],
    conflicting_values: [{ field: 'country' }],
  }));
  assert.equal(strength.label, 'Needs checks');
  assert.match(strength.title, /1 required field\(s\) missing/);
  assert.match(strength.title, /1 conflicting field\(s\)/);
});

test('evidence strength never reports a score it does not have', () => {
  const strength = getCandidateEvidenceStrength({});
  assert.equal(strength.summary, 'No extracted fields');
  assert.equal(strength.label, 'No fields');
  assert.equal(strength.backed, 0);
});

test('empty quotes do not count as evidence', () => {
  const strength = getCandidateEvidenceStrength(candidate({
    evidence_excerpts: [{ evidence_excerpts: { name: '   ', country: null } }],
  }));
  assert.equal(strength.backed, 0);
  assert.equal(strength.label, 'No evidence');
});

test('review reasons are split and de-duplicated', () => {
  assert.deepEqual(
    getReviewReasons({ review_reason: 'admin_review_required; host_country_from_source_registry; admin_review_required' }),
    ['admin_review_required', 'host_country_from_source_registry'],
  );
  assert.deepEqual(getReviewReasons({ review_reason: '  ' }), []);
  assert.deepEqual(getReviewReasons({}), []);
});

test('approve is offered whenever at least one candidate is selected', () => {
  assert.equal(canResolveSelection([]), false);
  assert.equal(canResolveSelection([candidate()]), true);
  assert.equal(canResolveSelection([candidate({ review_status: 'reviewed' })]), true);
});

test('a pending candidate is marked reviewed before it is resolved', () => {
  const steps = buildBulkDecisionSteps(candidate(), 'accepted');
  assert.deepEqual(steps, [
    { decision: 'reviewed' },
    { decision: 'accepted', values: { name: 'Award', country: 'Germany', deadline: '30 June' } },
  ]);
});

test('a reviewed candidate is resolved in one call', () => {
  const steps = buildBulkDecisionSteps(candidate({ review_status: 'reviewed' }), 'rejected');
  assert.deepEqual(steps, [{ decision: 'rejected' }]);
});

test('rejecting carries an optional reason on every step', () => {
  const steps = buildBulkDecisionSteps(candidate(), 'rejected', { note: '  not a scholarship  ' });
  assert.deepEqual(steps, [
    { decision: 'reviewed', note: 'not a scholarship' },
    { decision: 'rejected', note: 'not a scholarship' },
  ]);
});

test('rejecting sends no values, so nothing can be published', () => {
  for (const step of buildBulkDecisionSteps(candidate(), 'rejected')) {
    assert.equal(Object.prototype.hasOwnProperty.call(step, 'values'), false);
  }
});

test('an already resolved candidate is refused', () => {
  assert.equal(isResolvableReviewItem(candidate({ review_status: 'accepted' })), false);
  assert.throws(
    () => buildBulkDecisionSteps(candidate({ review_status: 'accepted' }), 'accepted'),
    /already accepted/,
  );
});

test('only approve and reject are bulk decisions', () => {
  assert.throws(() => buildBulkDecisionSteps(candidate(), 'duplicate'), /Unsupported/);
});

// --- the real stored evidence shape ---------------------------------------

/**
 * A candidate as the API actually serves one.
 *
 * The extractor stores only the structural quotes, so `evidence_excerpts`
 * holds `host_location`/`masters_evidence`/`scholarship_offer_evidence` and
 * never `name`, `country` or `degree_level`. Reading it as if the keys were
 * field names is what produced "0/N fields quoted" for every row.
 */
function storedCandidate(overrides = {}) {
  return {
    id: 29,
    review_status: 'pending',
    source_id: 'daad-helmut-schmidt',
    source_url: 'https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship/',
    host_country: 'Germany',
    candidate_name: 'Helmut-Schmidt-Programm',
    created_at: '2026-11-13T21:40:12Z',
    discovery_run_id: 'c0ffee00-1111-2222-3333-444455556666',
    extracted_values: {
      name: 'Helmut-Schmidt-Programm',
      country: 'Germany',
      degree_level: 'Master',
      deadline_type: 'fixed',
      application_deadline_date: '2027-07-31',
      host_institution: 'Universität Potsdam',
    },
    missing_required_fields: [],
    conflicting_values: [],
    review_reason: 'missing_evidence:name; missing_evidence:degree_level; missing_evidence:country',
    evidence_excerpts: [
      {
        fingerprint: 'b'.repeat(64),
        evidence_excerpts: {
          host_location: 'the programme is hosted at Universität Potsdam in Germany',
          masters_evidence: 'a Master’s degree programme in public policy',
          scholarship_offer_evidence: 'The Helmut-Schmidt-Programm offers scholarships',
        },
      },
    ],
    ...overrides,
  };
}

test('a page-level quote still counts for the field it vouches for', () => {
  const strength = getCandidateEvidenceStrength(storedCandidate());
  // name, country and degree_level are covered by the three structural
  // quotes. host_institution would need a host_city quote, and neither the
  // deadline date nor deadline_type is quoted at all.
  assert.equal(strength.backed, 3);
  assert.equal(strength.total, 6);
  assert.equal(strength.direct, 0);
  assert.equal(strength.summary, '3/6 fields quoted');
  assert.match(strength.title, /page-level quote/);
});

test('the real stored shape no longer reads 0 fields quoted', () => {
  assert.notEqual(getCandidateEvidenceStrength(storedCandidate()).backed, 0);
});

test('a direct per-field quote wins over the page-level one', () => {
  const item = storedCandidate({
    evidence_excerpts: [
      {
        evidence_excerpts: {
          host_location: 'hosted in Germany',
          country: 'the award is held in Germany',
        },
      },
    ],
  });
  const quote = getEvidenceQuoteFor(item, 'country');
  assert.equal(quote.kind, 'direct');
  assert.equal(quote.quote, 'the award is held in Germany');
});

test('a field with no quote reports none', () => {
  assert.equal(getEvidenceQuoteFor(storedCandidate(), 'application_deadline_date'), null);
});

// --- deadline -------------------------------------------------------------

test('the deadline row shows the date, with the type as a label', () => {
  const deadline = getCandidateDeadline(storedCandidate());
  assert.equal(deadline.text, '2027-07-31');
  assert.equal(deadline.typeLabel, 'Fixed date');
  assert.equal(deadline.isDate, true);
});

test('a rolling deadline says so instead of showing a type', () => {
  const deadline = getCandidateDeadline(storedCandidate({
    extracted_values: { deadline_type: 'rolling' },
  }));
  assert.match(deadline.text, /^Rolling/);
  assert.equal(deadline.typeLabel, '');
});

test('a missing deadline says it was not found rather than showing "fixed"', () => {
  const deadline = getCandidateDeadline(storedCandidate({
    extracted_values: { deadline_type: 'fixed' },
  }));
  assert.equal(deadline.text, 'Not found on page');
  assert.equal(deadline.typeLabel, 'Fixed date');
});

test('a deadline stated only as text is shown as written', () => {
  const deadline = getCandidateDeadline(storedCandidate({
    extracted_values: { deadline: '31 July, annually' },
  }));
  assert.equal(deadline.text, '31 July, annually');
});

// --- duplicates -----------------------------------------------------------

test('Programm and Programme normalize to the same name', () => {
  assert.equal(
    normalizeCandidateName('Helmut-Schmidt-Programm'),
    normalizeCandidateName('Helmut-Schmidt-Programme'),
  );
  assert.equal(
    normalizeCandidateName('The Helmut Schmidt Program'),
    normalizeCandidateName('Helmut-Schmidt-Programm'),
  );
});

test('different awards do not normalize together', () => {
  assert.notEqual(
    normalizeCandidateName('Helmut-Schmidt-Programm'),
    normalizeCandidateName('Konrad-Adenauer-Programm'),
  );
});

test('pending candidates with near-identical names are flagged for each other', () => {
  const flags = findPossibleDuplicates([
    storedCandidate({ id: 1, candidate_name: 'Helmut-Schmidt-Programm', source_id: 'a' }),
    storedCandidate({ id: 2, candidate_name: 'Helmut-Schmidt-Programme', source_id: 'b' }),
    storedCandidate({ id: 3, candidate_name: 'Something Else', source_id: 'c', host_country: 'Austria' }),
  ]);
  assert.deepEqual(flags.get(1), { reason: 'similar_name', matchIds: [2] });
  assert.deepEqual(flags.get(2), { reason: 'similar_name', matchIds: [1] });
  assert.equal(flags.has(3), false);
});

test('the same source and host country is flagged too', () => {
  const flags = findPossibleDuplicates([
    storedCandidate({ id: 4, candidate_name: 'One Award' }),
    storedCandidate({ id: 5, candidate_name: 'Another Award' }),
  ]);
  assert.equal(flags.get(4).reason, 'same_source_and_country');
  assert.deepEqual(flags.get(5).matchIds, [4]);
});

test('a name match is reported in preference to a shared source', () => {
  const flags = findPossibleDuplicates([
    storedCandidate({ id: 6, candidate_name: 'Helmut-Schmidt-Programm' }),
    storedCandidate({ id: 7, candidate_name: 'Helmut-Schmidt-Programme' }),
  ]);
  assert.equal(flags.get(6).reason, 'similar_name');
});

test('only pending candidates are flagged', () => {
  const flags = findPossibleDuplicates([
    storedCandidate({ id: 8, review_status: 'accepted' }),
    storedCandidate({ id: 9, review_status: 'rejected' }),
  ]);
  assert.equal(flags.size, 0);
});

test('a duplicate needs an existing scholarship, so one candidate is approved first', () => {
  const items = new Map([[2, storedCandidate({ id: 2 })]]);
  const resolution = getDuplicateResolution(storedCandidate({ id: 1 }), [2], items);
  assert.equal(resolution.kind, 'needs_scholarship');
  assert.deepEqual(resolution.approveFirstIds, [2]);
});

test('once a sibling has a scholarship, the duplicate target is known', () => {
  const items = new Map([[2, storedCandidate({ id: 2, accepted_scholarship_id: 414 })]]);
  const resolution = getDuplicateResolution(storedCandidate({ id: 1 }), [2], items);
  assert.equal(resolution.kind, 'scholarship');
  assert.equal(resolution.scholarshipId, 414);
});

// --- review reasons, status names, source and run display -----------------

test('review reasons are plain English and split into two groups', () => {
  const { mustCheck, optional } = groupReviewReasons(storedCandidate({
    review_reason: 'missing_evidence:name; missing_evidence:application_cycle; '
      + 'conflicting_host_location_evidence; host_country_from_source_registry',
  }));
  assert.deepEqual(mustCheck.map((reason) => reason.text), [
    'No quote for the name',
    'The page gives conflicting host locations',
  ]);
  assert.deepEqual(optional.map((reason) => reason.text), [
    'No quote for the application cycle',
    'Host country taken from the source registry, not the page',
  ]);
});

test('an unmapped review reason is still shown, never hidden', () => {
  const { optional } = groupReviewReasons({ review_reason: 'some_new_backend_code' });
  assert.deepEqual(optional.map((reason) => reason.text), ['some new backend code']);
});

test('one set of status names is used everywhere', () => {
  assert.deepEqual(Object.values(REVIEW_STATUS_LABELS), [
    'Needs review', 'Reviewed', 'Accepted', 'Rejected', 'Duplicate',
  ]);
  assert.equal(getReviewStatusLabel('pending'), 'Needs review');
  assert.equal(getReviewStatusLabel(undefined), 'Needs review');
});

test('the source column shows the registrable domain', () => {
  assert.equal(getSourceDomain(storedCandidate()), 'daad.de');
  assert.equal(
    getSourceDomain({ source_url: 'https://www.study.cam.ac.uk/funding' }),
    'cam.ac.uk',
  );
  assert.equal(getSourceDomain({ source_url: 'not a url' }), '');
  assert.equal(getSourceDomain({}), '');
});

test('the run is shown as a date, with the UUID kept for the tooltip', () => {
  const run = getRunLabel(storedCandidate());
  assert.equal(run.id, 'c0ffee00-1111-2222-3333-444455556666');
  assert.match(run.title, /c0ffee00-1111-2222-3333-444455556666/);
  assert.notEqual(run.text, run.id);
  assert.notEqual(run.text, 'Date not available');
});

test('a run with no recorded time says so', () => {
  assert.equal(getRunLabel({ discovery_run_id: 'x' }).text, 'Date not available');
});

// --- editing before approval ---------------------------------------------

test('the editable draft is built from the extracted values', () => {
  const draft = buildEditableCandidateDraft(storedCandidate());
  assert.equal(draft.name, 'Helmut-Schmidt-Programm');
  assert.equal(draft.application_deadline_date, '2027-07-31');
  assert.equal(draft.official_url, '');
});

test('an edit is applied and every untouched value is preserved', () => {
  const item = storedCandidate();
  const draft = { ...buildEditableCandidateDraft(item), country: 'Austria' };
  const values = applyCandidateDraft(item, draft);
  assert.equal(values.country, 'Austria');
  assert.equal(values.host_institution, 'Universität Potsdam');
  assert.equal(values.deadline_type, 'fixed');
  assert.equal(hasCandidateEdits(item, draft), true);
});

test('clearing a field removes it instead of publishing an empty string', () => {
  const item = storedCandidate();
  const values = applyCandidateDraft(item, {
    ...buildEditableCandidateDraft(item),
    application_deadline_date: '',
  });
  assert.equal(Object.prototype.hasOwnProperty.call(values, 'application_deadline_date'), false);
});

test('a list-valued field stays a list after editing', () => {
  const item = storedCandidate({
    extracted_values: { eligible_fields: ['Public policy'] },
  });
  const values = applyCandidateDraft(item, { eligible_fields: 'Public policy, Economics' });
  assert.deepEqual(values.eligible_fields, ['Public policy', 'Economics']);
});

test('an untouched draft changes nothing', () => {
  const item = storedCandidate();
  const draft = buildEditableCandidateDraft(item);
  assert.deepEqual(applyCandidateDraft(item, draft), item.extracted_values);
  assert.equal(hasCandidateEdits(item, draft), false);
});

test('approval publishes the edited values', () => {
  const item = storedCandidate();
  const draft = { ...buildEditableCandidateDraft(item), name: 'Helmut Schmidt Programme' };
  const steps = buildBulkDecisionSteps(item, 'accepted', { draft });
  assert.deepEqual(steps[0], { decision: 'reviewed' });
  assert.equal(steps[1].values.name, 'Helmut Schmidt Programme');
  assert.equal(steps[1].values.country, 'Germany');
});

test('rejection still sends no values, edited or not', () => {
  const item = storedCandidate();
  const draft = { ...buildEditableCandidateDraft(item), name: 'Changed' };
  for (const step of buildBulkDecisionSteps(item, 'rejected', { draft })) {
    assert.equal(Object.prototype.hasOwnProperty.call(step, 'values'), false);
  }
});
