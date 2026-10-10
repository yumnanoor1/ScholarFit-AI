export const APPLICATION_STRATEGY_KEY = 'fitscholar.applicationStrategies.v1';
export const APPLICATION_TASK_STATUS_KEY = 'fitscholar.applicationTaskStatuses.v1';
export const DEFAULT_APPLICATION_STRATEGY = 'University First';

function readObjectStorage(key) {
  try {
    const value = window.localStorage.getItem(key);
    const parsed = value ? JSON.parse(value) : {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function getSelectedApplicationStrategy(opportunityId) {
  if (!opportunityId) return DEFAULT_APPLICATION_STRATEGY;
  const strategies = readObjectStorage(APPLICATION_STRATEGY_KEY);
  return strategies[opportunityId] || DEFAULT_APPLICATION_STRATEGY;
}

export function saveSelectedApplicationStrategy(opportunityId, strategy) {
  window.localStorage.setItem(
    APPLICATION_STRATEGY_KEY,
    JSON.stringify({ ...readObjectStorage(APPLICATION_STRATEGY_KEY), [opportunityId]: strategy }),
  );
}

export function getApplicationTaskStatuses(opportunityId) {
  const statuses = readObjectStorage(APPLICATION_TASK_STATUS_KEY);
  return opportunityId ? statuses[opportunityId] || {} : statuses;
}

export function saveApplicationTaskStatuses(opportunityId, statuses) {
  window.localStorage.setItem(
    APPLICATION_TASK_STATUS_KEY,
    JSON.stringify({ ...readObjectStorage(APPLICATION_TASK_STATUS_KEY), [opportunityId]: statuses }),
  );
}

export function getPathwayTaskId(pathway, step) {
  const opportunityId = pathway.opportunityId || pathway.universityId;
  return `pathway:${opportunityId}:${step.id}`;
}
