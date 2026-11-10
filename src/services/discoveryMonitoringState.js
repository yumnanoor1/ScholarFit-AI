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

export function formatDiscoverySourceFailure(source = {}) {
  const details = [];
  if (DISCOVERY_FAILURE_CATEGORIES.has(source.error_category)) {
    details.push(`Category: ${source.error_category}`);
  }

  const failureStage = DISCOVERY_FAILURE_STAGES.has(source.failure_stage)
    ? source.failure_stage
    : null;
  const pageStage = DISCOVERY_PAGE_STAGES.has(source.page_stage)
    ? source.page_stage
    : null;
  if (failureStage) {
    details.push(`Stage: ${failureStage}${pageStage ? ` (${pageStage} page)` : ''}`);
  } else if (pageStage) {
    details.push(`Page: ${pageStage}`);
  }

  if (Number.isInteger(source.http_status) && source.http_status >= 100 && source.http_status <= 599) {
    details.push(`HTTP ${source.http_status}`);
  }
  const attemptCount = Number.isInteger(source.attempt_count) && source.attempt_count > 0
    ? source.attempt_count
    : null;
  const attemptLimit = Number.isInteger(source.attempt_limit) && source.attempt_limit > 0
    ? source.attempt_limit
    : null;
  if (attemptCount !== null) {
    details.push(`Attempts: ${attemptCount}${attemptLimit !== null ? `/${attemptLimit}` : ''}`);
  }

  if (
    typeof source.cause_type === 'string'
    && /^[A-Za-z][A-Za-z0-9_]{0,79}$/.test(source.cause_type)
  ) {
    details.push(`Cause: ${source.cause_type}`);
  }
  return details.length > 0 ? details.join(' · ') : 'Failure details unavailable';
}
