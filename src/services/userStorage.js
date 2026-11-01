// Browser storage for one signed-in student. Each value lives under `<base key>.<user ID>`.
// Without a user ID there is no key, so nothing can land in a shared slot. Older keys with no
// user ID have no known owner: they are never read, moved or deleted.
export const SAVED_OPPORTUNITIES_KEY = 'fitscholar.savedOpportunities.v1';
export const COMPARISON_OPPORTUNITIES_KEY = 'fitscholar.comparisonOpportunities.v1';
export const SELECTED_OPPORTUNITIES_KEY = 'fitscholar.selectedOpportunities.v1';
export const ACTIVE_OPPORTUNITY_KEY = 'fitscholar.activeOpportunity.v1';
export const APPLIED_OPPORTUNITIES_KEY = 'fitscholar.appliedOpportunities.v1';
export const DOCUMENT_RECORDS_KEY = 'fitscholar.documentRecords.v1';
export const APPLICATION_STRATEGY_KEY = 'fitscholar.applicationStrategies.v1';
export const APPLICATION_TASK_STATUS_KEY = 'fitscholar.applicationTaskStatuses.v1';
export const SAVED_SNAPSHOT_KEY = 'fitscholar.savedScholarshipsSnapshot.v1';
export const SAVED_REMOVED_KEY = 'fitscholar.savedScholarshipsRemoved.v1';
export const PROFILE_KEY = 'fitscholar.profile.v2';
export const EMAIL_ALERTS_KEY = 'fitscholar.settings.emailDeadlineAlerts.v1';

// Uploaded files never go into browser storage
const UNSTORED_PROFILE_FIELDS = ['profilePhoto', 'transcript', 'moiCertificate'];

export function getUserStorageKey(baseKey, userId) {
  const hasId = typeof userId === 'number'
    ? Number.isFinite(userId)
    : typeof userId === 'string' && userId.trim() !== '';
  return hasId ? `${baseKey}.${userId}` : null;
}

export function readUserStorage(baseKey, userId, fallback) {
  const key = getUserStorageKey(baseKey, userId);
  if (!key || typeof window === 'undefined') return fallback;
  try {
    const stored = window.localStorage.getItem(key);
    return stored ? JSON.parse(stored) : fallback;
  } catch {
    return fallback;
  }
}

export function writeUserStorage(baseKey, userId, value, replacer) {
  const key = getUserStorageKey(baseKey, userId);
  if (!key || typeof window === 'undefined') return false;
  try {
    window.localStorage.setItem(key, JSON.stringify(value, replacer));
    return true;
  } catch {
    console.error(`Unable to persist ${baseKey} in browser storage.`);
    return false;
  }
}

function readIdList(baseKey, userId) {
  const ids = readUserStorage(baseKey, userId, []);
  return Array.isArray(ids) ? ids.filter((id) => typeof id === 'string') : [];
}

/** Items saved in this browser: programs, plus any scholarships not yet moved to the database. */
export function readSavedLocally(userId) {
  return readIdList(SAVED_OPPORTUNITIES_KEY, userId);
}

export function readUserObject(baseKey, userId) {
  const value = readUserStorage(baseKey, userId, {});
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

/** The saved records the backend last confirmed, or null when it never has for this student. */
export function readSavedSnapshot(userId) {
  const records = readUserStorage(SAVED_SNAPSHOT_KEY, userId, null);
  return Array.isArray(records)
    ? records.filter((record) => Number.isInteger(record?.scholarship_id) && record.scholarship)
    : null;
}

/** Saved scholarships that were deleted from FitScholars, kept until the student dismisses the notice. */
export function readRemovedSaves(userId) {
  const removed = readUserStorage(SAVED_REMOVED_KEY, userId, []);
  return Array.isArray(removed) ? removed.filter((item) => Number.isInteger(item?.scholarship_id)) : [];
}

/** The student's own saved profile, or null. Never another account's and never a shared copy. */
export function readUserProfile(userId) {
  const profile = readUserStorage(PROFILE_KEY, userId, null);
  return profile && typeof profile === 'object' && !Array.isArray(profile) ? profile : null;
}

export function writeUserProfile(userId, profile) {
  return writeUserStorage(PROFILE_KEY, userId, profile, (key, value) => (
    UNSTORED_PROFILE_FIELDS.includes(key) ? null : value
  ));
}

/** Email deadline alerts are on until the student turns them off. */
export function readEmailAlerts(userId) {
  const enabled = readUserStorage(EMAIL_ALERTS_KEY, userId, true);
  if (typeof enabled === 'boolean') return enabled;
  console.error('Ignoring an invalid stored email alert preference.');
  return true;
}

/** Everything ProfileContext keeps per student. Empty when no one is signed in. */
export function readOpportunityData(userId) {
  const selected = readUserStorage(SELECTED_OPPORTUNITIES_KEY, userId, []);
  const activeId = readUserStorage(ACTIVE_OPPORTUNITY_KEY, userId, null);
  const snapshot = readSavedSnapshot(userId);
  return {
    savedOpportunities: [...new Set([
      ...readSavedLocally(userId),
      ...(snapshot || []).map((record) => `sch-db-${record.scholarship_id}`),
    ])],
    savedRecords: snapshot || [],
    hasSavedSnapshot: snapshot !== null,
    removedSaves: readRemovedSaves(userId),
    comparisonOpportunityIds: [...new Set(readIdList(COMPARISON_OPPORTUNITIES_KEY, userId))].slice(0, 2),
    selectedOpportunities: Array.isArray(selected) ? selected.filter((item) => item && typeof item.id === 'string') : [],
    activeOpportunityId: typeof activeId === 'string' ? activeId : null,
    appliedOpportunityIds: readIdList(APPLIED_OPPORTUNITIES_KEY, userId),
    opportunityTaskStatuses: readUserObject(APPLICATION_TASK_STATUS_KEY, userId),
    documentRecords: readUserObject(DOCUMENT_RECORDS_KEY, userId),
  };
}
