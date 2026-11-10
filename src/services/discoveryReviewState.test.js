import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import {
  buildReviewDecisionPayload,
  createActionGuard,
  createLatestRequestGuard,
  getDiscoveryCandidateCounts,
  getReviewDecisionAnnouncement,
  getReviewQueueViewState,
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
