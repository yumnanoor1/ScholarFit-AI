import { beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_APPLICATION_STRATEGY,
  getSelectedApplicationStrategy,
  saveApplicationTaskStatuses,
  saveSelectedApplicationStrategy,
} from './applicationWorkflow.js';
import {
  ACTIVE_OPPORTUNITY_KEY,
  APPLIED_OPPORTUNITIES_KEY,
  COMPARISON_OPPORTUNITIES_KEY,
  DOCUMENT_RECORDS_KEY,
  SAVED_OPPORTUNITIES_KEY,
  SELECTED_OPPORTUNITIES_KEY,
  APPLICATION_TASK_STATUS_KEY,
  EMAIL_ALERTS_KEY,
  PROFILE_KEY,
  getUserStorageKey,
  readEmailAlerts,
  readOpportunityData,
  readUserProfile,
  writeUserProfile,
  writeUserStorage,
} from './userStorage.js';

const USER_A = 7;
const USER_B = 12;

function fakeStorage() {
  const items = new Map();
  return {
    items,
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => items.set(key, String(value)),
    removeItem: (key) => items.delete(key),
  };
}

// The same writes ProfileContext makes for one student's session
function saveFor(userId, id) {
  const { savedOpportunities } = readOpportunityData(userId);
  writeUserStorage(SAVED_OPPORTUNITIES_KEY, userId, [...savedOpportunities, id]);
}

beforeEach(() => {
  globalThis.window = { localStorage: fakeStorage() };
});

test('each account sees only its own saved scholarships across logout and login', () => {
  saveFor(USER_A, 'sch-db-1');
  assert.deepEqual(readOpportunityData(null).savedOpportunities, []);   // A logged out

  assert.deepEqual(readOpportunityData(USER_B).savedOpportunities, []); // B can't see A's
  saveFor(USER_B, 'sch-db-2');
  saveFor(USER_B, 'sch-db-3');
  assert.deepEqual(readOpportunityData(USER_B).savedOpportunities, ['sch-db-2', 'sch-db-3']);

  assert.deepEqual(readOpportunityData(USER_A).savedOpportunities, ['sch-db-1']); // A returns
});

test('compare, selected, active, applied, task and document data are isolated', () => {
  writeUserStorage(COMPARISON_OPPORTUNITIES_KEY, USER_A, ['sch-db-1', 'sch-db-2']);
  writeUserStorage(SELECTED_OPPORTUNITIES_KEY, USER_A, [{ id: 'sch-db-1', kind: 'scholarship' }]);
  writeUserStorage(ACTIVE_OPPORTUNITY_KEY, USER_A, 'sch-db-1');
  writeUserStorage(APPLIED_OPPORTUNITIES_KEY, USER_A, ['sch-db-1']);
  writeUserStorage(APPLICATION_TASK_STATUS_KEY, USER_A, { 'sch-db-1': { review: 'done' } });
  writeUserStorage(DOCUMENT_RECORDS_KEY, USER_A, { passport: { fileName: 'passport.pdf' } });

  assert.deepEqual(readOpportunityData(USER_B), readOpportunityData(null));
  assert.deepEqual(readOpportunityData(USER_B).comparisonOpportunityIds, []);
  assert.deepEqual(readOpportunityData(USER_B).appliedOpportunityIds, []);
  assert.equal(readOpportunityData(USER_B).activeOpportunityId, null);

  const own = readOpportunityData(USER_A);
  assert.deepEqual(own.comparisonOpportunityIds, ['sch-db-1', 'sch-db-2']);
  assert.deepEqual(own.appliedOpportunityIds, ['sch-db-1']);
  assert.equal(own.activeOpportunityId, 'sch-db-1');
  assert.deepEqual(own.opportunityTaskStatuses, { 'sch-db-1': { review: 'done' } });
  assert.equal(own.documentRecords.passport.fileName, 'passport.pdf');
});

test('application strategy and task progress are isolated', () => {
  saveSelectedApplicationStrategy(USER_A, 'univ-db-1', 'Scholarship First');
  assert.equal(getSelectedApplicationStrategy(USER_A, 'univ-db-1'), 'Scholarship First');
  assert.equal(getSelectedApplicationStrategy(USER_B, 'univ-db-1'), DEFAULT_APPLICATION_STRATEGY);

  saveApplicationTaskStatuses(USER_A, 'sch-db-1', { review: 'done' });
  assert.deepEqual(readOpportunityData(USER_A).opportunityTaskStatuses, { 'sch-db-1': { review: 'done' } });
  assert.deepEqual(readOpportunityData(USER_B).opportunityTaskStatuses, {});
});

test('saving application progress without a user ID fails instead of using a shared key', () => {
  assert.throws(() => saveSelectedApplicationStrategy(undefined, 'univ-db-1', 'Scholarship First'));
  assert.throws(() => saveApplicationTaskStatuses(undefined, 'sch-db-1', { review: 'done' }));
  assert.equal(window.localStorage.items.size, 0);
});

test('nothing is written or read without a stable user ID', () => {
  for (const id of [undefined, null, '', '   ', Number.NaN, {}]) {
    assert.equal(getUserStorageKey(SAVED_OPPORTUNITIES_KEY, id), null);
    assert.equal(writeUserStorage(SAVED_OPPORTUNITIES_KEY, id, ['sch-db-1']), false);
  }
  assert.equal(window.localStorage.items.size, 0);
  assert.equal(getUserStorageKey(SAVED_OPPORTUNITIES_KEY, 7), 'fitscholar.savedOpportunities.v1.7');
});

test('legacy keys with no owner are never read, changed or removed', () => {
  const legacy = {
    [SAVED_OPPORTUNITIES_KEY]: '["sch-db-9"]',
    [COMPARISON_OPPORTUNITIES_KEY]: '["sch-db-9"]',
    [APPLIED_OPPORTUNITIES_KEY]: '["sch-db-9"]',
    [ACTIVE_OPPORTUNITY_KEY]: '"sch-db-9"',
  };
  Object.entries(legacy).forEach(([key, value]) => window.localStorage.setItem(key, value));

  const data = readOpportunityData(USER_A);
  assert.deepEqual(data.savedOpportunities, []);
  assert.deepEqual(data.comparisonOpportunityIds, []);
  assert.deepEqual(data.appliedOpportunityIds, []);
  assert.equal(data.activeOpportunityId, null);

  saveFor(USER_A, 'sch-db-1');
  Object.entries(legacy).forEach(([key, value]) => assert.equal(window.localStorage.getItem(key), value));
});

test('profiles are isolated across account switches and logout', () => {
  writeUserProfile(USER_A, { name: 'Student A', cgpa: '3.8' });
  assert.equal(readUserProfile(null), null);       // A logged out
  assert.equal(readUserProfile(USER_B), null);     // B can't see A's profile

  writeUserProfile(USER_B, { name: 'Student B', cgpa: '3.1' });
  assert.equal(readUserProfile(USER_B).name, 'Student B');
  assert.equal(readUserProfile(USER_A).name, 'Student A'); // A returns unchanged
});

test('a profile is written only under its own key, never a shared one', () => {
  writeUserProfile(USER_A, { name: 'Student A' });
  assert.deepEqual([...window.localStorage.items.keys()], [`${PROFILE_KEY}.${USER_A}`]);
});

test('signed-out or ID-less callers cannot read or overwrite a profile', () => {
  writeUserProfile(USER_A, { name: 'Student A' });
  for (const id of [undefined, null, '', '   ', Number.NaN]) {
    assert.equal(readUserProfile(id), null);
    assert.equal(writeUserProfile(id, { name: 'Intruder' }), false);
  }
  assert.equal(readUserProfile(USER_A).name, 'Student A');
  assert.equal(window.localStorage.items.size, 1);
});

test('the legacy shared profile is never read, changed or removed', () => {
  const legacy = JSON.stringify({ name: 'Unknown Owner', cgpa: '3.9' });
  window.localStorage.setItem(PROFILE_KEY, legacy);
  assert.equal(readUserProfile(USER_A), null);
  assert.equal(readUserProfile(null), null);
  writeUserProfile(USER_A, { name: 'Student A' });
  assert.equal(window.localStorage.getItem(PROFILE_KEY), legacy);
});

test('uploaded files are not stored with the profile', () => {
  writeUserProfile(USER_A, { name: 'Student A', profilePhoto: 'data:image', documents: { transcript: 'file', moiCertificate: 'file' } });
  const stored = readUserProfile(USER_A);
  assert.equal(stored.profilePhoto, null);
  assert.deepEqual(stored.documents, { transcript: null, moiCertificate: null });
});

test('a damaged stored profile is ignored', () => {
  for (const value of ['not json', '[1,2]', '5']) {
    window.localStorage.setItem(`${PROFILE_KEY}.${USER_A}`, value);
    assert.equal(readUserProfile(USER_A), null);
  }
});

test('email alert preferences are per account and default to on', () => {
  assert.equal(readEmailAlerts(USER_A), true);
  writeUserStorage(EMAIL_ALERTS_KEY, USER_A, false);
  assert.equal(readEmailAlerts(USER_A), false);
  assert.equal(readEmailAlerts(USER_B), true);
});

test('email alerts have no shared fallback without a user ID', () => {
  window.localStorage.setItem(`${EMAIL_ALERTS_KEY}.anonymous`, 'false'); // the old shared slot
  assert.equal(readEmailAlerts(undefined), true);
  assert.equal(writeUserStorage(EMAIL_ALERTS_KEY, undefined, false), false);
  assert.equal(window.localStorage.items.size, 1);
});

test('email alert values saved before this change still load', () => {
  window.localStorage.setItem(`${EMAIL_ALERTS_KEY}.${USER_A}`, 'false');
  assert.equal(readEmailAlerts(USER_A), false);
});

test('damaged stored values fall back to empty data', () => {
  window.localStorage.setItem(`${SAVED_OPPORTUNITIES_KEY}.${USER_A}`, 'not json');
  window.localStorage.setItem(`${COMPARISON_OPPORTUNITIES_KEY}.${USER_A}`, '{"a":1}');
  window.localStorage.setItem(`${ACTIVE_OPPORTUNITY_KEY}.${USER_A}`, '5');
  const data = readOpportunityData(USER_A);
  assert.deepEqual(data.savedOpportunities, []);
  assert.deepEqual(data.comparisonOpportunityIds, []);
  assert.equal(data.activeOpportunityId, null);
});
