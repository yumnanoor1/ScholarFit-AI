import {
  APPLICATION_STRATEGY_KEY,
  APPLICATION_TASK_STATUS_KEY,
  readUserObject,
  writeUserStorage,
} from './userStorage.js';

export const DEFAULT_APPLICATION_STRATEGY = 'University First';

function saveOpportunityValue(baseKey, userId, opportunityId, value) {
  const next = { ...readUserObject(baseKey, userId), [opportunityId]: value };
  if (!writeUserStorage(baseKey, userId, next)) {
    throw new Error('Application progress could not be saved.');
  }
}

export function getSelectedApplicationStrategy(userId, opportunityId) {
  if (!opportunityId) return DEFAULT_APPLICATION_STRATEGY;
  return readUserObject(APPLICATION_STRATEGY_KEY, userId)[opportunityId] || DEFAULT_APPLICATION_STRATEGY;
}

export function saveSelectedApplicationStrategy(userId, opportunityId, strategy) {
  saveOpportunityValue(APPLICATION_STRATEGY_KEY, userId, opportunityId, strategy);
}

export function saveApplicationTaskStatuses(userId, opportunityId, statuses) {
  saveOpportunityValue(APPLICATION_TASK_STATUS_KEY, userId, opportunityId, statuses);
}

export function getPathwayTaskId(pathway, step) {
  const opportunityId = pathway.opportunityId || pathway.universityId;
  return `pathway:${opportunityId}:${step.id}`;
}
