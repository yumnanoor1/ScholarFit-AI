const ACTIVE_WORKER_STATUSES = new Set(['submitting', 'starting', 'running']);

const WORKER_STATUS_LABELS = {
  idle: 'Idle',
  submitting: 'Submitting',
  starting: 'Starting',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  interrupted_unknown: 'Interrupted / unknown',
};

const DISCOVERY_FAILURE_CATEGORIES = new Set([
  'http_status',
  'timeout',
  'connection_error',
  'dns_error',
  'robots_check_failed',
  'content_validation_failed',
  'unknown',
]);
const DISCOVERY_FAILURE_STAGES = new Set(['robots', 'root_fetch', 'linked_page']);
const DISCOVERY_PAGE_STAGES = new Set(['root_fetch', 'linked_page']);

export function isDiscoveryWorkerActive(status) {
  return ACTIVE_WORKER_STATUSES.has(status);
}

export function getDiscoveryWorkerStatusLabel(status) {
  return WORKER_STATUS_LABELS[status] || WORKER_STATUS_LABELS.idle;
}

export function formatDiscoveryWorkerError(error) {
  if (!error) return '';
  if (typeof error === 'string') return error;
  return error.code ? `${error.code}: ${error.message}` : error.message;
}

export function getDiscoverySourceFailureDetails(source = {}) {
  const details = [];
  if (DISCOVERY_FAILURE_CATEGORIES.has(source.error_category)) {
    details.push({ label: 'Category', value: source.error_category });
  }

  const failureStage = DISCOVERY_FAILURE_STAGES.has(source.failure_stage)
    ? source.failure_stage
    : null;
  const pageStage = DISCOVERY_PAGE_STAGES.has(source.page_stage)
    ? source.page_stage
    : null;
  if (failureStage) {
    details.push({ label: 'Stage', value: failureStage });
    if (pageStage) details.push({ label: 'Page', value: pageStage });
  } else if (pageStage) {
    details.push({ label: 'Page', value: pageStage });
  }

  if (Number.isInteger(source.http_status) && source.http_status >= 100 && source.http_status <= 599) {
    details.push({ label: 'HTTP', value: String(source.http_status) });
  }
  const attemptCount = Number.isInteger(source.attempt_count) && source.attempt_count > 0
    ? source.attempt_count
    : null;
  const attemptLimit = Number.isInteger(source.attempt_limit) && source.attempt_limit > 0
    ? source.attempt_limit
    : null;
  if (attemptCount !== null) {
    details.push({
      label: 'Attempts',
      value: `${attemptCount}${attemptLimit !== null ? `/${attemptLimit}` : ''}`,
    });
  }

  if (
    typeof source.cause_type === 'string'
    && /^[A-Za-z][A-Za-z0-9_]{0,79}$/.test(source.cause_type)
  ) {
    details.push({ label: 'Cause', value: source.cause_type });
  }
  return details;
}

export function formatDiscoverySourceFailure(source = {}) {
  const details = getDiscoverySourceFailureDetails(source);
  if (details.length === 0) return 'Failure details unavailable';
  const formatted = [];
  details.forEach((detail, index) => {
    if (detail.label === 'Stage' && details[index + 1]?.label === 'Page') {
      formatted.push(`Stage: ${detail.value} (${details[index + 1].value} page)`);
    } else if (detail.label === 'Page' && details[index - 1]?.label === 'Stage') {
      return;
    } else if (detail.label === 'HTTP') {
      formatted.push(`HTTP ${detail.value}`);
    } else {
      formatted.push(`${detail.label}: ${detail.value}`);
    }
  });
  return formatted.join(' · ');
}

// --- plain-language formatting --------------------------------------------

/**
 * A duration an admin can read: "45 s", "8 min 16 s", "1 h 4 min".
 *
 * The page used to print the raw float ("496.02s"), which is a developer's
 * unit, not an answer to "how long did that take".
 */
export function formatDiscoveryDuration(seconds) {
  // Number(null) and Number('') are both 0, which would print a missing
  // duration as "0 s". Only a real number counts.
  if (typeof seconds !== 'number' && typeof seconds !== 'string') return '';
  if (typeof seconds === 'string' && !seconds.trim()) return '';
  const total = Number(seconds);
  if (!Number.isFinite(total) || total < 0) return '';
  const whole = Math.round(total);
  if (whole < 60) return `${whole} s`;
  const minutes = Math.floor(whole / 60);
  if (minutes < 60) {
    const rest = whole % 60;
    return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes ? `${hours} h ${restMinutes} min` : `${hours} h`;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "just now", "9 minutes ago", "13 hours ago", "3 days ago", or ''. */
export function formatRelativeTime(value, now = Date.now()) {
  if (!value) return '';
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return '';
  const elapsed = now - then;
  if (elapsed < 0) {
    const ahead = -elapsed;
    if (ahead < MINUTE) return 'in under a minute';
    if (ahead < HOUR) return `in ${Math.round(ahead / MINUTE)} minutes`;
    if (ahead < DAY) return `in ${Math.round(ahead / HOUR)} hours`;
    return `in ${Math.round(ahead / DAY)} days`;
  }
  if (elapsed < MINUTE) return 'just now';
  if (elapsed < HOUR) {
    const minutes = Math.round(elapsed / MINUTE);
    return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  }
  if (elapsed < DAY) {
    const hours = Math.round(elapsed / HOUR);
    return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  }
  const days = Math.round(elapsed / DAY);
  if (days <= 30) return `${days} day${days === 1 ? '' : 's'} ago`;
  return '';
}

/** "14 Nov, 10:47 PM" — short, with no seconds and no timezone noise. */
export function formatAbsoluteTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  // en-GB for the day-first shape the page asks for; the default locale would
  // render "Nov 14" in en-US and lose the agreed format.
  const day = date.toLocaleString('en-GB', { day: 'numeric', month: 'short' });
  const time = date
    .toLocaleString('en-GB', { hour: 'numeric', minute: '2-digit', hour12: true })
    .toUpperCase();
  return `${day}, ${time}`;
}

/**
 * Relative and absolute together: "13 hours ago · 14 Nov, 10:47 PM".
 *
 * Relative answers "is this stale?" at a glance; absolute is what an admin
 * quotes in a message to someone else. Both, always.
 */
export function formatTimeWithRelative(value, now = Date.now()) {
  const absolute = formatAbsoluteTime(value);
  if (!absolute) return 'Not recorded';
  const relative = formatRelativeTime(value, now);
  return relative ? `${relative} · ${absolute}` : absolute;
}

/** "1 failure" / "3 failures" — never "Failure(S)". */
export function formatFailureCount(count) {
  const total = Number.isFinite(Number(count)) ? Math.max(0, Math.round(Number(count))) : 0;
  return `${total} ${total === 1 ? 'failure' : 'failures'}`;
}

/** A source id as a readable name: "daad-epos" -> "Daad epos". */
export function formatSourceIdName(sourceId) {
  if (typeof sourceId !== 'string' || !sourceId.trim()) return '';
  const words = sourceId.trim().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// --- status and summary lines ---------------------------------------------

/**
 * "Automatic runs: Off · No run in progress".
 *
 * Replaces "Disabled (configured) · idle", which read as a system state
 * rather than a sentence.
 */
export function getDiscoveryStatusLine(monitoring) {
  if (!monitoring) {
    return { automatic: 'Automatic runs: unknown', run: 'Run state unknown', enabled: false };
  }
  const active = isDiscoveryWorkerActive(monitoring.worker_status)
    || monitoring.current_run_status === 'running';
  return {
    automatic: `Automatic runs: ${monitoring.enabled ? 'On' : 'Off'}`,
    run: active ? 'Run in progress' : 'No run in progress',
    enabled: Boolean(monitoring.enabled),
  };
}

/**
 * "Last run finished · 8 min 16 s · 4 sources · 5 candidates".
 *
 * The run id is returned separately for a tooltip rather than printed: a UUID
 * tells an admin nothing and crowds out what does.
 */
export function getLastRunSummary(monitoring) {
  const run = monitoring?.current_run
    || monitoring?.last_attempted_run
    || monitoring?.last_completed_run
    || null;
  if (!run) return null;
  const running = run.status === 'running' || run.display_status === 'running';
  const outcome = running
    ? 'Run in progress'
    : run.display_status === 'failed'
      ? 'Last run failed'
      : run.display_status === 'partial'
        ? 'Last run finished with failures'
        : 'Last run finished';
  const parts = [outcome];
  const duration = formatDiscoveryDuration(
    running ? monitoring?.worker_duration_seconds ?? run.duration_seconds : run.duration_seconds,
  );
  if (duration) parts.push(duration);
  const sources = Number(run.sources_attempted);
  if (Number.isFinite(sources)) parts.push(`${sources} source${sources === 1 ? '' : 's'}`);
  const candidates = Number(run.candidates_discovered);
  if (Number.isFinite(candidates)) {
    parts.push(`${candidates} candidate${candidates === 1 ? '' : 's'}`);
  }
  return {
    text: parts.join(' · '),
    runId: run.run_id || '',
    title: run.run_id ? `Run ${run.run_id}` : '',
    running,
  };
}

// --- running a manual discovery ------------------------------------------

/** Minutes a single source typically takes, for the pre-run estimate. */
const MINUTES_PER_SOURCE_LOW = 2.5;
const MINUTES_PER_SOURCE_HIGH = 3.5;

function mostRecentManualRun(monitoring) {
  if (monitoring?.current_manual_run) return monitoring.current_manual_run;
  const runs = Array.isArray(monitoring?.recent_runs) ? monitoring.recent_runs : [];
  return runs.find((run) => run?.trigger_type === 'manual') || null;
}

/**
 * How many sources a manual run will cover, and roughly how long.
 *
 * The API does not expose the manual source selection (it comes from
 * CONTROLLED_MANUAL_SOURCE_IDS and an optional env override), so this counts
 * the sources the last manual run actually attempted and says so through
 * `basis`. With nothing to go on it returns no estimate rather than a guess.
 */
export function getManualRunPlan(monitoring) {
  const manual = mostRecentManualRun(monitoring);
  const fallback = monitoring?.last_attempted_run;
  let sourceCount = null;
  let basis = 'unknown';
  if (Number.isFinite(Number(manual?.sources_attempted)) && Number(manual.sources_attempted) > 0) {
    sourceCount = Number(manual.sources_attempted);
    basis = 'last_manual_run';
  } else if (
    Number.isFinite(Number(fallback?.sources_attempted))
    && Number(fallback.sources_attempted) > 0
  ) {
    sourceCount = Number(fallback.sources_attempted);
    basis = 'last_run';
  }
  if (sourceCount === null) {
    return {
      sourceCount: null,
      basis,
      text: 'Source count not known yet',
      title: 'No previous run to estimate from. The sources come from the server configuration.',
    };
  }
  const lowerMinutes = Math.max(1, Math.round(sourceCount * MINUTES_PER_SOURCE_LOW));
  const upperMinutes = Math.max(lowerMinutes + 1, Math.round(sourceCount * MINUTES_PER_SOURCE_HIGH));
  return {
    sourceCount,
    basis,
    lowerMinutes,
    upperMinutes,
    text: `${sourceCount} source${sourceCount === 1 ? '' : 's'} · about ${lowerMinutes}–${upperMinutes} minutes`,
    title: basis === 'last_manual_run'
      ? 'Based on the sources the last manual run attempted, at roughly 3 minutes each.'
      : 'Based on the sources the last run attempted, at roughly 3 minutes each.',
  };
}

/**
 * What to show while a run is going: which source, how far through, how long.
 *
 * `worker_stage` carries "source:<id>" for the source being processed, and
 * the running run row's sources_attempted grows as each one commits.
 */
export function getRunProgress(monitoring) {
  const active = isDiscoveryWorkerActive(monitoring?.worker_status);
  if (!active) return null;
  const stage = typeof monitoring?.worker_stage === 'string' ? monitoring.worker_stage : '';
  const sourceId = stage.startsWith('source:') ? stage.slice('source:'.length) : '';
  const attempted = Number(monitoring?.current_run?.sources_attempted);
  const total = getManualRunPlan(monitoring).sourceCount;
  const index = Number.isFinite(attempted) ? attempted + 1 : null;
  const position = index === null
    ? ''
    : total && index <= total
      ? `source ${index} of ${total}`
      : `source ${index}`;
  return {
    sourceName: formatSourceIdName(sourceId),
    position,
    elapsed: formatDiscoveryDuration(monitoring?.worker_duration_seconds ?? 0),
    stageLabel: sourceId ? '' : stage.replace(/_/g, ' '),
  };
}

// --- discovery analytics and the next step -------------------------------

/** Counts are intentionally kept independent; the backend doesn't expose a funnel. */
export function getDiscoveryAnalyticsCounts(monitoring) {
  const run = monitoring?.current_run || monitoring?.last_attempted_run || null;
  const count = (value) => (
    typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
  );
  return {
    run,
    sourcesAttempted: count(run?.sources_attempted),
    sourcesSucceeded: count(run?.sources_succeeded),
    candidatesFound: count(run?.candidates_discovered),
    candidatesAccepted: count(run?.extraction_diagnostics?.candidates_accepted),
    candidatesRejected: count(run?.extraction_diagnostics?.candidates_rejected),
    awaitingReview: count(monitoring?.review_queue_pending),
  };
}

/** The single most useful thing to do next, as a card. */
export function getDiscoveryNextStep(monitoring) {
  if (!monitoring) return null;
  const pending = Number(monitoring.review_queue_pending) || 0;
  if (isDiscoveryWorkerActive(monitoring.worker_status)) {
    return { text: 'A discovery run is in progress', cta: null, href: null };
  }
  if (pending > 0) {
    return {
      text: `${pending} candidate${pending === 1 ? '' : 's'} waiting`,
      cta: 'Review now',
      href: '/admin/scholarships?section=reviews',
    };
  }
  const failed = monitoring.last_failed_run;
  const lastRun = monitoring.last_attempted_run;
  if (failed && lastRun && failed.run_id === lastRun.run_id) {
    return {
      text: 'The last run failed',
      cta: 'See discovery history',
      href: '/admin/scholarships?section=history',
    };
  }
  if (!lastRun) {
    return { text: 'No discovery run has been recorded yet', cta: null, href: null };
  }
  return {
    text: 'Nothing waiting for review',
    cta: 'Check discovery sources',
    href: '/admin/scholarships?section=sources',
  };
}

/**
 * What to show for "Next scheduled run".
 *
 * With automatic runs off there is no next run to name, and printing a stale
 * timestamp implied one was coming.
 */
export function getNextScheduledRunText(monitoring, now = Date.now()) {
  if (!monitoring) return 'Not recorded';
  if (!monitoring.enabled) return 'None (automatic runs are off)';
  return formatTimeWithRelative(monitoring.next_scheduled_run, now);
}

/** The last failure, as one muted line, or null when there is nothing to say. */
export function getLastFailureNote(monitoring, now = Date.now()) {
  const failed = monitoring?.last_failed_run;
  if (!failed) return null;
  const when = formatTimeWithRelative(failed.completed_at || failed.started_at, now);
  const detail = failed.error_summary
    || formatFailureCount(failed.failed_sources?.length ?? failed.sources_failed ?? 0);
  return { text: `Last failure: ${when} · ${detail}`, runId: failed.run_id || '' };
}
