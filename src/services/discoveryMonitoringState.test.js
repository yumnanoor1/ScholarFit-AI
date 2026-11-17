import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  formatAbsoluteTime,
  formatDiscoveryDuration,
  formatDiscoverySourceFailure,
  formatDiscoveryWorkerError,
  formatFailureCount,
  formatRelativeTime,
  formatSourceIdName,
  formatTimeWithRelative,
  getDiscoveryNextStep,
  getDiscoverySourceFailureDetails,
  getDiscoveryStatusLine,
  getDiscoveryWorkerStatusLabel,
  getLastFailureNote,
  getLastRunSummary,
  getManualRunPlan,
  getNextScheduledRunText,
  getDiscoveryAnalyticsCounts,
  getRunProgress,
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
  const failureDetails = getDiscoverySourceFailureDetails({
    error_category: 'http_status',
    failure_stage: 'robots',
    page_stage: 'root_fetch',
    http_status: 503,
    attempt_count: 2,
    attempt_limit: 3,
    cause_type: 'TimeoutError',
  });
  assert.deepEqual(failureDetails, [
    { label: 'Category', value: 'http_status' },
    { label: 'Stage', value: 'robots' },
    { label: 'Page', value: 'root_fetch' },
    { label: 'HTTP', value: '503' },
    { label: 'Attempts', value: '2/3' },
    { label: 'Cause', value: 'TimeoutError' },
  ]);

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

// --- plain-language formatting --------------------------------------------

test('durations read as minutes and seconds, not raw floats', () => {
  assert.equal(formatDiscoveryDuration(496.02), '8 min 16 s');
  assert.equal(formatDiscoveryDuration(45), '45 s');
  assert.equal(formatDiscoveryDuration(120), '2 min');
  assert.equal(formatDiscoveryDuration(3840), '1 h 4 min');
  assert.equal(formatDiscoveryDuration(3600), '1 h');
  assert.equal(formatDiscoveryDuration(0), '0 s');
});

test('a duration that is not a number produces nothing', () => {
  assert.equal(formatDiscoveryDuration(undefined), '');
  assert.equal(formatDiscoveryDuration(null), '');
  assert.equal(formatDiscoveryDuration(-5), '');
  assert.equal(formatDiscoveryDuration('abc'), '');
});

test('relative times are rounded to a unit an admin thinks in', () => {
  const now = Date.parse('2026-11-15T12:00:00Z');
  assert.equal(formatRelativeTime('2026-11-15T11:59:30Z', now), 'just now');
  assert.equal(formatRelativeTime('2026-11-15T11:51:00Z', now), '9 minutes ago');
  assert.equal(formatRelativeTime('2026-11-15T11:00:00Z', now), '1 hour ago');
  assert.equal(formatRelativeTime('2026-11-14T23:00:00Z', now), '13 hours ago');
  assert.equal(formatRelativeTime('2026-11-12T12:00:00Z', now), '3 days ago');
});

test('a time too old for a relative phrase falls back to the date alone', () => {
  const now = Date.parse('2026-11-15T12:00:00Z');
  assert.equal(formatRelativeTime('2025-01-01T12:00:00Z', now), '');
  assert.match(formatTimeWithRelative('2025-01-01T12:00:00Z', now), /^\d+ \w+, /);
});

test('a future scheduled time reads as future, not as "ago"', () => {
  const now = Date.parse('2026-11-15T12:00:00Z');
  assert.equal(formatRelativeTime('2026-11-15T15:00:00Z', now), 'in 3 hours');
});

test('times show relative and absolute together', () => {
  const now = Date.parse('2026-11-15T12:00:00Z');
  const shown = formatTimeWithRelative('2026-11-14T23:00:00Z', now);
  assert.match(shown, /^13 hours ago · /);
  // "14 Nov, 10:47 PM" shape: day, short month, then a 12-hour clock.
  assert.match(shown, /\d{1,2} \w{3}, \d{1,2}:\d{2} (AM|PM)$/);
});

test('a missing time says so instead of rendering an empty row', () => {
  assert.equal(formatTimeWithRelative(null), 'Not recorded');
  assert.equal(formatTimeWithRelative('not a date'), 'Not recorded');
});

test('failure counts are pluralised properly, never "Failure(S)"', () => {
  assert.equal(formatFailureCount(1), '1 failure');
  assert.equal(formatFailureCount(3), '3 failures');
  assert.equal(formatFailureCount(0), '0 failures');
  assert.equal(formatFailureCount(undefined), '0 failures');
  assert.doesNotMatch(formatFailureCount(2), /\(s\)/i);
});

test('a source id becomes a readable name', () => {
  assert.equal(formatSourceIdName('daad-helmut-schmidt'), 'Daad helmut schmidt');
  assert.equal(formatSourceIdName(''), '');
  assert.equal(formatSourceIdName(null), '');
});

// --- status and summary lines ---------------------------------------------

function monitoring(overrides = {}) {
  return {
    enabled: false,
    interval_hours: 24,
    current_run_status: 'idle',
    worker_status: 'idle',
    worker_duration_seconds: 0,
    worker_stage: null,
    review_queue_pending: 4,
    candidates_total: 4,
    recent_runs: [],
    last_attempted_run: {
      run_id: 'c0ffee00-1111-2222-3333-444455556666',
      trigger_type: 'manual',
      status: 'completed',
      display_status: 'succeeded',
      started_at: '2026-11-14T22:39:00Z',
      completed_at: '2026-11-14T22:47:16Z',
      duration_seconds: 496.02,
      sources_attempted: 4,
      sources_succeeded: 4,
      sources_failed: 0,
      candidates_discovered: 5,
      candidates_queued_for_review: 4,
      failed_sources: [],
      extraction_diagnostics: { candidates_rejected: 2 },
    },
    ...overrides,
  };
}

test('the status line is a sentence, not a system state', () => {
  const line = getDiscoveryStatusLine(monitoring());
  assert.equal(line.automatic, 'Automatic runs: Off');
  assert.equal(line.run, 'No run in progress');
});

test('the status line reports an enabled scheduler and an active run', () => {
  const line = getDiscoveryStatusLine(monitoring({
    enabled: true,
    worker_status: 'running',
    current_run_status: 'running',
  }));
  assert.equal(line.automatic, 'Automatic runs: On');
  assert.equal(line.run, 'Run in progress');
});

test('the last-run line replaces the worker/uuid/seconds line', () => {
  const summary = getLastRunSummary(monitoring());
  assert.equal(summary.text, 'Last run finished · 8 min 16 s · 4 sources · 5 candidates');
  // The UUID is kept for the tooltip and never printed in the line.
  assert.equal(summary.runId, 'c0ffee00-1111-2222-3333-444455556666');
  assert.doesNotMatch(summary.text, /c0ffee00/);
  assert.match(summary.title, /c0ffee00/);
});

test('a partial or failed run says so in the same line', () => {
  const partial = getLastRunSummary(monitoring({
    last_attempted_run: { ...monitoring().last_attempted_run, display_status: 'partial' },
  }));
  assert.match(partial.text, /^Last run finished with failures · /);
  const failed = getLastRunSummary(monitoring({
    last_attempted_run: { ...monitoring().last_attempted_run, display_status: 'failed' },
  }));
  assert.match(failed.text, /^Last run failed · /);
});

test('with no run recorded there is no summary line to show', () => {
  assert.equal(getLastRunSummary(monitoring({ last_attempted_run: null })), null);
  assert.equal(getLastRunSummary(null), null);
});

// --- the manual run estimate ---------------------------------------------

test('the run button is labelled with sources and a time range', () => {
  const plan = getManualRunPlan(monitoring({
    recent_runs: [{ trigger_type: 'manual', sources_attempted: 5 }],
  }));
  assert.equal(plan.sourceCount, 5);
  assert.equal(plan.basis, 'last_manual_run');
  assert.equal(plan.text, '5 sources · about 13–18 minutes');
});

test('one source is not pluralised', () => {
  const plan = getManualRunPlan(monitoring({
    recent_runs: [{ trigger_type: 'manual', sources_attempted: 1 }],
  }));
  assert.match(plan.text, /^1 source · about/);
});

test('with no manual run yet the estimate falls back to the last run and says so', () => {
  const plan = getManualRunPlan(monitoring({ recent_runs: [] }));
  assert.equal(plan.sourceCount, 4);
  assert.equal(plan.basis, 'last_run');
  assert.match(plan.title, /last run attempted/);
});

test('with nothing to go on no estimate is invented', () => {
  const plan = getManualRunPlan(monitoring({ recent_runs: [], last_attempted_run: null }));
  assert.equal(plan.sourceCount, null);
  assert.equal(plan.basis, 'unknown');
  assert.equal(plan.text, 'Source count not known yet');
  assert.doesNotMatch(plan.text, /minute/);
});

// --- progress while a run is going ---------------------------------------

test('progress names the current source, its position and the elapsed time', () => {
  const progress = getRunProgress(monitoring({
    worker_status: 'running',
    worker_stage: 'source:daad-epos',
    worker_duration_seconds: 185,
    current_run: { sources_attempted: 1, candidates_discovered: 0 },
    recent_runs: [{ trigger_type: 'manual', sources_attempted: 5 }],
  }));
  assert.equal(progress.sourceName, 'Daad epos');
  assert.equal(progress.position, 'source 2 of 5');
  assert.equal(progress.elapsed, '3 min 5 s');
});

test('a non-source stage is reported as itself rather than as a source', () => {
  const progress = getRunProgress(monitoring({
    worker_status: 'starting',
    worker_stage: 'waiting_for_worker_start',
    current_run: null,
  }));
  assert.equal(progress.sourceName, '');
  assert.equal(progress.stageLabel, 'waiting for worker start');
});

test('there is no progress block when nothing is running', () => {
  assert.equal(getRunProgress(monitoring()), null);
});

// --- discovery analytics, next step, last failure -------------------------

test('analytics use actual counts without implying sequential stages', () => {
  const currentRun = {
    run_id: 'current',
    candidates_discovered: 12,
    candidates_queued_for_review: 3,
    sources_attempted: 4,
    sources_succeeded: 3,
    extraction_diagnostics: { candidates_accepted: 12, candidates_rejected: 2 },
  };
  const counts = getDiscoveryAnalyticsCounts(monitoring({
    current_run: currentRun,
    review_queue_pending: 7,
  }));
  assert.equal(counts.run, currentRun);
  assert.equal(counts.candidatesFound, 12);
  assert.equal(counts.candidatesAccepted, 12);
  assert.equal(counts.candidatesRejected, 2);
  assert.equal(counts.awaitingReview, 7, 'global pending queue, not per-run queued count');
  assert.equal(counts.sourcesAttempted, 4);
  assert.equal(counts.sourcesSucceeded, 3);
});

test('analytics preserve zero and represent missing or invalid values as unavailable', () => {
  const counts = getDiscoveryAnalyticsCounts({
    current_run: {
      sources_attempted: 0,
      sources_succeeded: null,
      candidates_discovered: -1,
      extraction_diagnostics: { candidates_accepted: 0, candidates_rejected: '2' },
    },
    review_queue_pending: null,
  });
  assert.equal(counts.sourcesAttempted, 0);
  assert.equal(counts.sourcesSucceeded, null);
  assert.equal(counts.candidatesFound, null);
  assert.equal(counts.candidatesAccepted, 0);
  assert.equal(counts.candidatesRejected, null);
  assert.equal(counts.awaitingReview, null);
});

test('analytics have no run until monitoring returns a current or attempted run', () => {
  const counts = getDiscoveryAnalyticsCounts({ current_run: null, last_attempted_run: null });
  assert.equal(counts.run, null);
  assert.equal(counts.candidatesFound, null);
});

test('the next step points at the review queue when candidates are waiting', () => {
  const next = getDiscoveryNextStep(monitoring());
  assert.equal(next.text, '4 candidates waiting');
  assert.equal(next.cta, 'Review now');
  assert.match(next.href, /section=reviews/);
});

test('the next step defers to a run in progress', () => {
  const next = getDiscoveryNextStep(monitoring({ worker_status: 'running' }));
  assert.match(next.text, /in progress/);
  assert.equal(next.href, null);
});

test('a failed last run sends the admin to the history', () => {
  const base = monitoring({ review_queue_pending: 0 });
  const next = getDiscoveryNextStep({
    ...base,
    last_failed_run: { run_id: base.last_attempted_run.run_id },
  });
  assert.equal(next.text, 'The last run failed');
  assert.match(next.href, /section=history/);
});

test('the last failure is one line with a real plural', () => {
  const now = Date.parse('2026-11-15T12:00:00Z');
  const note = getLastFailureNote(monitoring({
    last_failed_run: {
      run_id: 'f1',
      completed_at: '2026-11-14T23:00:00Z',
      failed_sources: [{ source_id: 'a' }],
      error_summary: null,
    },
  }), now);
  const when = formatAbsoluteTime('2026-11-14T23:00:00Z');
  assert.equal(note.text, `Last failure: 13 hours ago · ${when} · 1 failure`);
  assert.match(when, /^\d{1,2} \w{3}, \d{1,2}:\d{2} (AM|PM)$/);
  assert.doesNotMatch(note.text, /\(s\)/i);
});

test('no failure recorded means no failure line', () => {
  assert.equal(getLastFailureNote(monitoring()), null);
});

// --- next scheduled run and the rejection card ---------------------------

test('with automatic runs off there is no next run to name', () => {
  assert.equal(
    getNextScheduledRunText(monitoring({ enabled: false, next_scheduled_run: '2026-11-16T03:00:00Z' })),
    'None (automatic runs are off)',
  );
});

test('with automatic runs on the next run shows relative and absolute', () => {
  const now = Date.parse('2026-11-15T12:00:00Z');
  const text = getNextScheduledRunText(
    monitoring({ enabled: true, next_scheduled_run: '2026-11-15T15:00:00Z' }),
    now,
  );
  assert.match(text, /^in 3 hours · /);
});

test('an enabled scheduler with no next run recorded says so', () => {
  assert.equal(
    getNextScheduledRunText(monitoring({ enabled: true, next_scheduled_run: null })),
    'Not recorded',
  );
  assert.equal(getNextScheduledRunText(null), 'Not recorded');
});

test('analytics use the active run instead of mixing in the previous run', () => {
  const current = {
    run_id: 'in-progress',
    candidates_discovered: 3,
    extraction_diagnostics: { candidates_accepted: 2, candidates_rejected: 9 },
  };
  const counts = getDiscoveryAnalyticsCounts(monitoring({ current_run: current }));
  assert.equal(counts.run, current);
  assert.equal(counts.candidatesFound, 3);
  assert.equal(counts.candidatesRejected, 9);
});
