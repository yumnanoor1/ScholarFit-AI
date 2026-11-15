import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildCandidatePatch,
  describeImportReading,
  getImportCandidates,
  getImportFailureGuidance,
  SOURCE_BLOCKED_CATEGORY,
} from './adminScholarshipImport.js';
import { getErrorMessage } from './adminApi.js';

function blockedError(status = 403) {
  const error = new Error('The official site refused our request (HTTP 403). It blocks automatic reading.');
  error.status = 424;
  error.category = SOURCE_BLOCKED_CATEGORY;
  error.httpStatus = status;
  return error;
}

test('a blocked source gets a plain explanation and the three things that work', () => {
  const guidance = getImportFailureGuidance(blockedError(403));
  assert.equal(guidance.blocked, true);
  assert.equal(guidance.httpStatus, 403);
  assert.equal(
    guidance.message,
    'This website blocked automatic reading (HTTP 403). '
    + 'Paste the page text, upload the PDF, or fill in the details manually.',
  );
  assert.equal(guidance.offerFallbacks, true);
});

test('the status the site returned is named when there is one', () => {
  for (const status of [401, 403, 429]) {
    const guidance = getImportFailureGuidance(blockedError(status));
    assert.match(guidance.message, new RegExp(`HTTP ${status}`), String(status));
  }
});

test('a block with no status still reads as a block', () => {
  const error = new Error('robots.txt does not allow us to read this page.');
  error.category = SOURCE_BLOCKED_CATEGORY;
  const guidance = getImportFailureGuidance(error);
  assert.equal(guidance.blocked, true);
  assert.equal(guidance.httpStatus, null);
  assert.doesNotMatch(guidance.message, /HTTP/);
  assert.equal(guidance.offerFallbacks, true);
});

test('any other failure keeps its own message and offers no false choices', () => {
  const error = new Error('The source timed out.');
  error.status = 502;
  const guidance = getImportFailureGuidance(error);
  assert.equal(guidance.blocked, false);
  assert.equal(guidance.message, 'The source timed out.');
  assert.equal(guidance.offerFallbacks, false);
});

test('no failure means no guidance panel', () => {
  assert.equal(getImportFailureGuidance(null), null);
  assert.equal(getImportFailureGuidance(undefined), null);
});

test('a failure with no message still says something', () => {
  assert.equal(getImportFailureGuidance({}).message, 'The import failed.');
});

test('the structured backend detail is read as a message', () => {
  const detail = {
    category: 'source_blocked',
    http_status: 403,
    message: 'The official site refused our request (HTTP 403). It blocks automatic reading.',
  };
  assert.equal(getErrorMessage({ detail }, 424), detail.message);
});

// --- several candidates from one long page -------------------------------

function draft(overrides = {}) {
  return {
    chunk_count: 12,
    candidates: [
      {
        label: 'The Example Award',
        values: { name: 'The Example Award' },
        fields: {
          name: { status: 'extracted', value: 'The Example Award' },
          country: { status: 'extracted', value: 'Germany' },
          deadline: { status: 'uncertain', value: 'soon' },
        },
      },
      {
        label: 'The Second Grant',
        values: { name: 'The Second Grant' },
        fields: { name: { status: 'extracted', value: 'The Second Grant' } },
      },
    ],
    ...overrides,
  };
}

test('a page describing several awards offers each one', () => {
  const candidates = getImportCandidates(draft());
  assert.deepEqual(candidates.map((item) => item.label), ['The Example Award', 'The Second Grant']);
  assert.equal(candidates[0].extractedCount, 2);
  assert.equal(candidates[1].extractedCount, 1);
});

test('one candidate is no choice at all', () => {
  assert.deepEqual(getImportCandidates(draft({ candidates: [draft().candidates[0]] })), []);
  assert.deepEqual(getImportCandidates(draft({ candidates: [] })), []);
  assert.deepEqual(getImportCandidates({}), []);
  assert.deepEqual(getImportCandidates(null), []);
});

test('choosing a candidate fills only the fields it evidenced', () => {
  const [first] = getImportCandidates(draft());
  const patch = buildCandidatePatch(first, {});
  assert.deepEqual(Object.keys(patch).sort(), ['country', 'name']);
  assert.equal(patch.name, 'The Example Award');
});

test('choosing a candidate never overwrites what an admin typed', () => {
  const [first] = getImportCandidates(draft());
  const patch = buildCandidatePatch(first, { name: 'My own title' });
  assert.equal(Object.hasOwn(patch, 'name'), false);
  assert.equal(patch.country, 'Germany');
});

test('a long page says how it was read', () => {
  assert.equal(describeImportReading(draft()), 'Read in 12 sections because the page is long.');
  assert.equal(describeImportReading({ chunk_count: 1 }), '');
  assert.equal(describeImportReading({}), '');
});

test('a page too large and a busy provider each get their own guidance', () => {
  for (const category of ['page_too_large', 'provider_busy']) {
    const error = new Error('This page is very long. Try pasting only the scholarship section, or upload the official PDF.');
    error.category = category;
    const guidance = getImportFailureGuidance(error);
    assert.equal(guidance.blocked, category === 'source_blocked');
    assert.ok(guidance.message.length > 20, category);
  }
});
