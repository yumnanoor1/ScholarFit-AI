// Saved scholarships live in PostgreSQL. The token identifies the student; no user ID is ever sent.
// Saved programs and older sample items have no backend table and stay in the student's browser storage.
import { mapScholarshipToFrontend, parseScholarshipId } from './opportunityApi.js';
import {
  SAVED_OPPORTUNITIES_KEY,
  SAVED_REMOVED_KEY,
  SAVED_SNAPSHOT_KEY,
  readRemovedSaves,
  readSavedLocally,
  readSavedSnapshot,
  writeUserStorage,
} from './userStorage.js';

const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
const REQUEST_TIMEOUT_MS = 15000;

async function request(path, token, method = 'GET') {
  const response = await fetch(`${API_BASE_URL}/saved-scholarships/${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), // a hung request must fail, not stay "loading"
  });
  if (!response.ok) {
    const error = new Error(`Saved scholarships request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

/** GET /saved-scholarships/ -> this student's records, each with its scholarship and current status */
export function fetchSavedRecords(token) {
  return request('', token);
}

/** POST /saved-scholarships/{id}. Saving twice is safe. */
export function saveScholarship(token, opportunityId) {
  return request(parseScholarshipId(opportunityId), token, 'POST');
}

/** DELETE /saved-scholarships/{id}. Removing twice is safe. */
export function removeSavedScholarship(token, opportunityId) {
  return request(parseScholarshipId(opportunityId), token, 'DELETE');
}

export function isBackendSavedId(id) {
  return parseScholarshipId(id) != null;
}

export function forgetLocalSave(userId, id) {
  const items = readSavedLocally(userId).filter((savedId) => savedId !== id);
  writeUserStorage(SAVED_OPPORTUNITIES_KEY, userId, items);
}

const toSavedId = (record) => `sch-db-${record.scholarship_id}`;

/** Runs one account's load, save and remove requests in order, so none can overwrite a newer result. */
export function createSavedQueue() {
  let tail = Promise.resolve();
  return (task) => {
    const result = tail.then(task);
    tail = result.catch(() => {});
    return result;
  };
}

/**
 * Moves scholarships from this student's own browser key into the database. Each one leaves the
 * browser only after the backend accepts it, so a failure loses nothing and the next load retries.
 * A 404 means the scholarship no longer exists. The old shared key has no known owner and is not read.
 */
async function migrateLocalSaves(token, userId) {
  for (const id of readSavedLocally(userId).filter(isBackendSavedId)) {
    try {
      await saveScholarship(token, id);
    } catch (error) {
      if (error.status !== 404) return; // offline or signed out: stop and keep the rest for next time
    }
    forgetLocalSave(userId, id);
  }
}

async function isDeleted(scholarshipId) {
  try {
    const response = await fetch(`${API_BASE_URL}/scholarships/${scholarshipId}`, {
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    return response.status === 404;
  } catch {
    return false; // unknown, so don't tell the student it was deleted
  }
}

/** Records that left the list because the scholarship was deleted, not because the student removed them. */
async function recordDeletedSaves(userId, previous, records) {
  const current = new Set(records.map((record) => record.scholarship_id));
  const removed = readRemovedSaves(userId);
  for (const record of previous.filter((item) => !current.has(item.scholarship_id))) {
    if (await isDeleted(record.scholarship_id)) {
      removed.push({ scholarship_id: record.scholarship_id, name: record.scholarship.name || null });
    }
  }
  writeUserStorage(SAVED_REMOVED_KEY, userId, removed);
  return removed;
}

/**
 * Everything saved for this student, as the backend confirms it. Rejects when the backend can't
 * answer, so a failure can never look like an empty list. An empty list is a successful result.
 */
export async function loadSavedOpportunities(token, userId) {
  await migrateLocalSaves(token, userId);
  const records = await fetchSavedRecords(token);
  const removed = await recordDeletedSaves(userId, readSavedSnapshot(userId) || [], records);
  writeUserStorage(SAVED_SNAPSHOT_KEY, userId, records);
  return { ids: [...new Set([...readSavedLocally(userId), ...records.map(toSavedId)])], records, removed };
}

// A partial snapshot would look like a complete list, so only an existing one is kept up to date
export function rememberSavedRecord(userId, record) {
  const snapshot = readSavedSnapshot(userId);
  if (!snapshot) return;
  writeUserStorage(SAVED_SNAPSHOT_KEY, userId, [
    ...snapshot.filter((item) => item.scholarship_id !== record.scholarship_id),
    record,
  ]);
}

export function forgetSavedRecord(userId, id) {
  const snapshot = readSavedSnapshot(userId);
  if (!snapshot) return;
  writeUserStorage(SAVED_SNAPSHOT_KEY, userId, snapshot.filter((item) => toSavedId(item) !== id));
}

export function dismissRemovedSaves(userId) {
  writeUserStorage(SAVED_REMOVED_KEY, userId, []);
}

/** The saved record comes first: it keeps its current status, while the catalog lists verified items only. */
export function resolveSavedItem(id, records, getCatalogItem) {
  const record = records.find((item) => toSavedId(item) === id);
  return record ? mapScholarshipToFrontend(record.scholarship) : getCatalogItem(id);
}

/** What to tell the student about saved data. An empty bookmark may not mean "not saved" in these states. */
export function getSavedNotice(status, hasSnapshot) {
  if (status === 'loading' && !hasSnapshot) {
    return { kind: 'loading', text: 'Loading your saved scholarships...' };
  }
  if (status !== 'error') return null;
  return {
    kind: 'error',
    text: hasSnapshot
      ? "Your saved scholarships couldn't be refreshed. Showing your last saved list."
      : "Your saved scholarships couldn't be loaded right now, so bookmarks may look empty.",
  };
}

export function getSaveErrorMessage(error, removing) {
  const action = removing ? 'removed' : 'saved';
  if (error?.status === 401) return `Please sign in again. This scholarship wasn't ${action}.`;
  if (error?.status === 404) return 'This scholarship is no longer available.';
  return `This scholarship couldn't be ${action}. Please check your connection and try again.`;
}
