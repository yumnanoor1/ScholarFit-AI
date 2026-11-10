import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  formatDiscoverySourceFailure,
  formatDiscoveryWorkerError,
  getDiscoveryWorkerStatusLabel,
  isDiscoveryWorkerActive,
} from './discoveryMonitoringState.js';

test('worker statuses label active, terminal, and interrupted states distinctly', () => {
  assert.equal(getDiscoveryWorkerStatusLabel('idle'), 'Idle');
  assert.equal(getDiscoveryWorkerStatusLabel('submitting'), 'Submitting');
  assert.equal(getDiscoveryWorkerStatusLabel('starting'), 'Starting');
  assert.equal(getDiscoveryWorkerStatusLabel('running'), 'Running');
  assert.equal(getDiscoveryWorkerStatusLabel('completed'), 'Completed');
  assert.equal(getDiscoveryWorkerStatusLabel('failed'), 'Failed');
  assert.equal(getDiscoveryWorkerStatusLabel('interrupted_unknown'), 'Interrupted / unknown');

  assert.equal(isDiscoveryWorkerActive('submitting'), true);
  assert.equal(isDiscoveryWorkerActive('starting'), true);
  assert.equal(isDiscoveryWorkerActive('running'), true);
  assert.equal(isDiscoveryWorkerActive('completed'), false);
  assert.equal(isDiscoveryWorkerActive('interrupted_unknown'), false);
});

test('manual submission errors show the server error code and explanation', () => {
  assert.equal(
    formatDiscoveryWorkerError({
      code: 'MANUAL_SUBMISSION_IN_PROGRESS',
      message: 'A manual discovery submission is already in progress.',
    }),
    'MANUAL_SUBMISSION_IN_PROGRESS: A manual discovery submission is already in progress.',
  );
  assert.equal(formatDiscoveryWorkerError({ message: 'Request failed.' }), 'Request failed.');
});

test('discovery source failures render safe structured diagnostics', () => {
  assert.equal(
    formatDiscoverySourceFailure({
      error: 'private exception text',
      error_category: 'http_status',
      failure_stage: 'robots',
      page_stage: 'root_fetch',
      http_status: 503,
      attempt_count: 2,
      attempt_limit: 3,
      cause_type: 'TimeoutError',
      source_url: 'https://official.example/?token=do-not-render',
    }),
    'Category: http_status · Stage: robots (root_fetch page) · HTTP 503 · Attempts: 2/3 · Cause: TimeoutError',
  );
});

test('older source failures render a safe fallback without exposing legacy error text', () => {
  assert.equal(
    formatDiscoverySourceFailure({
      status: 'failed',
      error: 'private exception text token=do-not-render',
      source_url: 'https://official.example/?token=do-not-render',
    }),
    'Failure details unavailable',
  );
});

test('invalid diagnostic values and sensitive fields are not rendered', () => {
  const rendered = formatDiscoverySourceFailure({
    error_category: 'private text',
    failure_stage: 'https://secret.example/',
    page_stage: 'private exception detail',
    http_status: 900,
    attempt_count: 0,
    cause_type: 'RuntimeError token=secret',
    source_url: 'https://official.example/?token=secret',
    response_body: 'private body',
  });
  assert.equal(rendered, 'Failure details unavailable');
  assert.doesNotMatch(rendered, /secret|private|official\.example|response/i);
});
