import { beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createSavedQueue,
  dismissRemovedSaves,
  fetchSavedRecords,
  forgetLocalSave,
  forgetSavedRecord,
  getSavedNotice,
  getSaveErrorMessage,
  isBackendSavedId,
  loadSavedOpportunities,
  rememberSavedRecord,
  removeSavedScholarship,
  resolveSavedItem,
  saveScholarship,
} from './savedScholarshipsApi.js';
import {
  SAVED_OPPORTUNITIES_KEY,
  SAVED_SNAPSHOT_KEY,
  readOpportunityData,
  readRemovedSaves,
  readSavedLocally,
  readSavedSnapshot,
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

// A small stand-in for the backend: the list a request sees depends only on its token
function fakeBackend({ missing = [], failOn = null } = {}) {
  const server = { byToken: { 'token-a': [], 'token-b': [] }, calls: [], deleted: [], unverified: [] };
  const toRecord = (scholarship_id) => ({
    scholarship_id,
    scholarship: {
      id: scholarship_id,
      name: `Scholarship ${scholarship_id}`,
      verification_status: server.unverified.includes(scholarship_id) ? 'unverified' : 'verified',
    },
  });
  globalThis.fetch = async (url, options) => {
    const id = Number(url.split('/').filter(Boolean).pop());
    if (!options.headers) { // the public GET /scholarships/{id}
      if (failOn?.('PUBLIC', id)) throw new TypeError('Failed to fetch');
      return { status: server.deleted.includes(id) ? 404 : 200 };
    }
    const auth = options.headers.Authorization.replace('Bearer ', '');
    server.calls.push({ url, method: options.method, auth, body: options.body });
    if (failOn?.(options.method, id)) throw new TypeError('Failed to fetch');
    const list = server.byToken[auth];
    if (!list) return { ok: false, status: 401, json: async () => ({}) };
    if (options.method === 'POST') {
      if (missing.includes(id)) return { ok: false, status: 404, json: async () => ({}) };
      const repeat = list.includes(id);
      if (!repeat) list.push(id);
      return { ok: true, status: repeat ? 200 : 201, json: async () => toRecord(id) };
    }
    if (options.method === 'DELETE') {
      server.byToken[auth] = list.filter((item) => item !== id);
      return { ok: true, status: 204, json: async () => null };
    }
    return { ok: true, status: 200, json: async () => list.map(toRecord) };
  };
  return server;
}

const savedIds = async (token) => (await fetchSavedRecords(token)).map((record) => `sch-db-${record.scholarship_id}`);
const loadIds = async (token, userId) => (await loadSavedOpportunities(token, userId)).ids;
const storeLocally = (userId, ids) => writeUserStorage(SAVED_OPPORTUNITIES_KEY, userId, ids);

beforeEach(() => {
  globalThis.window = { localStorage: fakeStorage() };
});

test('saving and retrieving a scholarship', async () => {
  fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  assert.deepEqual(await savedIds('token-a'), ['sch-db-5']);
});

test('removing a saved scholarship', async () => {
  fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  await removeSavedScholarship('token-a', 'sch-db-5');
  assert.deepEqual(await savedIds('token-a'), []);
});

test('a duplicate save keeps one record', async () => {
  fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  await saveScholarship('token-a', 'sch-db-5');
  assert.deepEqual(await savedIds('token-a'), ['sch-db-5']);
});

test('two students keep separate lists', async () => {
  fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  await saveScholarship('token-b', 'sch-db-6');
  assert.deepEqual(await loadIds('token-a', USER_A), ['sch-db-5']);
  assert.deepEqual(await loadIds('token-b', USER_B), ['sch-db-6']);
});

test('requests carry the token and never a user ID', async () => {
  const server = fakeBackend();
  storeLocally(USER_A, ['sch-db-5']);
  await loadIds('token-a', USER_A);
  await removeSavedScholarship('token-a', 'sch-db-5');
  for (const call of server.calls) {
    assert.equal(call.body, undefined);
    assert.doesNotMatch(call.url, /user/i);
    assert.equal(call.auth, 'token-a');
  }
});

test('an unauthorized request fails with its status', async () => {
  fakeBackend();
  await assert.rejects(savedIds('expired'), (error) => error.status === 401);
  await assert.rejects(saveScholarship('expired', 'sch-db-5'), (error) => error.status === 401);
});

test('a later load, as after refresh or re-login, finds the same list', async () => {
  fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  window.localStorage.items.clear(); // nothing depends on browser storage
  assert.deepEqual(await loadIds('token-a', USER_A), ['sch-db-5']);
});

test('only scholarships use the backend', () => {
  assert.equal(isBackendSavedId('sch-db-5'), true);
  assert.equal(isBackendSavedId('univ-db-5'), false);
  assert.equal(isBackendSavedId('sch-1'), false); // older sample item
});

test("migration moves the owner's scholarships and keeps programs local", async () => {
  const server = fakeBackend();
  storeLocally(USER_A, ['sch-db-5', 'univ-db-2', 'sch-1', 'sch-db-6']);
  const ids = await loadIds('token-a', USER_A);
  assert.deepEqual(server.byToken['token-a'], [5, 6]);
  assert.deepEqual(readSavedLocally(USER_A), ['univ-db-2', 'sch-1']);
  assert.deepEqual(ids, ['univ-db-2', 'sch-1', 'sch-db-5', 'sch-db-6']);
});

test('migration does not duplicate what the database already holds', async () => {
  const server = fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  storeLocally(USER_A, ['sch-db-5']);
  assert.deepEqual(await loadIds('token-a', USER_A), ['sch-db-5']);
  assert.deepEqual(server.byToken['token-a'], [5]);
});

test('migration runs once: a removed scholarship does not come back', async () => {
  const server = fakeBackend();
  storeLocally(USER_A, ['sch-db-5']);
  await loadIds('token-a', USER_A);
  await removeSavedScholarship('token-a', 'sch-db-5');
  assert.deepEqual(await loadIds('token-a', USER_A), []);
  assert.deepEqual(server.byToken['token-a'], []);
});

test("migration ignores the old shared key and other students' keys", async () => {
  const server = fakeBackend();
  window.localStorage.setItem(SAVED_OPPORTUNITIES_KEY, '["sch-db-9"]');
  storeLocally(USER_B, ['sch-db-8']);
  assert.deepEqual(await loadIds('token-a', USER_A), []);
  assert.deepEqual(server.byToken['token-a'], []);
  assert.equal(window.localStorage.getItem(SAVED_OPPORTUNITIES_KEY), '["sch-db-9"]');
  assert.deepEqual(readSavedLocally(USER_B), ['sch-db-8']);
});

test("a failed migration keeps what wasn't moved and retries later", async () => {
  fakeBackend({ failOn: (method, id) => method === 'POST' && id === 6 });
  storeLocally(USER_A, ['sch-db-5', 'sch-db-6', 'sch-db-7']);
  const ids = await loadIds('token-a', USER_A);
  assert.deepEqual(readSavedLocally(USER_A), ['sch-db-6', 'sch-db-7']);
  assert.deepEqual(ids, ['sch-db-6', 'sch-db-7', 'sch-db-5']);
  fakeBackend();
  assert.equal((await loadIds('token-a', USER_A)).length, 2); // fresh backend took both
  assert.deepEqual(readSavedLocally(USER_A), []);
});

test('a scholarship that no longer exists is dropped from migration', async () => {
  fakeBackend({ missing: [5] });
  storeLocally(USER_A, ['sch-db-5', 'sch-db-6']);
  assert.deepEqual(await loadIds('token-a', USER_A), ['sch-db-6']);
  assert.deepEqual(readSavedLocally(USER_A), []);
});

test('backend down: loading fails and local items are untouched', async () => {
  fakeBackend({ failOn: () => true });
  storeLocally(USER_A, ['sch-db-5', 'univ-db-2']);
  await assert.rejects(loadSavedOpportunities('token-a', USER_A));
  assert.deepEqual(readSavedLocally(USER_A), ['sch-db-5', 'univ-db-2']);
});

test('backend down: a save rejects, so nothing can claim success', async () => {
  fakeBackend({ failOn: () => true });
  await assert.rejects(saveScholarship('token-a', 'sch-db-5'));
  await assert.rejects(removeSavedScholarship('token-a', 'sch-db-5'));
});

test('removing an item still waiting to migrate clears it locally', () => {
  storeLocally(USER_A, ['sch-db-5', 'univ-db-2']);
  forgetLocalSave(USER_A, 'sch-db-5');
  assert.deepEqual(readSavedLocally(USER_A), ['univ-db-2']);
});

test('a failed first load is an error, an empty list is a result', async () => {
  fakeBackend({ failOn: () => true });
  await assert.rejects(loadSavedOpportunities('token-a', USER_A));
  assert.equal(readSavedSnapshot(USER_A), null); // still unknown, not empty
  assert.equal(readOpportunityData(USER_A).hasSavedSnapshot, false);

  fakeBackend();
  const loaded = await loadSavedOpportunities('token-a', USER_A);
  assert.deepEqual(loaded.ids, []);
  assert.deepEqual(readSavedSnapshot(USER_A), []);
  assert.equal(readOpportunityData(USER_A).hasSavedSnapshot, true);
});

test('retry after a failure loads the saved list', async () => {
  fakeBackend({ failOn: () => true });
  await assert.rejects(loadSavedOpportunities('token-a', USER_A));
  const working = fakeBackend();
  working.byToken['token-a'].push(5);
  assert.deepEqual(await loadIds('token-a', USER_A), ['sch-db-5']);
});

test('the last confirmed list survives a failed reload', async () => {
  fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  await loadSavedOpportunities('token-a', USER_A);

  fakeBackend({ failOn: () => true });
  await assert.rejects(loadSavedOpportunities('token-a', USER_A));
  const known = readOpportunityData(USER_A);
  assert.deepEqual(known.savedOpportunities, ['sch-db-5']);
  assert.equal(known.savedRecords[0].scholarship.name, 'Scholarship 5');
  assert.equal(known.hasSavedSnapshot, true);
});

test('snapshots belong to one student', async () => {
  fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  await loadSavedOpportunities('token-a', USER_A);
  assert.deepEqual(readOpportunityData(USER_B).savedOpportunities, []);
  assert.equal(readOpportunityData(USER_B).hasSavedSnapshot, false);
  assert.equal(readOpportunityData(null).hasSavedSnapshot, false);
  assert.equal(writeUserStorage(SAVED_SNAPSHOT_KEY, undefined, []), false);
});

test('confirmed changes update an existing snapshot but never invent one', async () => {
  fakeBackend();
  const record = await saveScholarship('token-a', 'sch-db-5');
  rememberSavedRecord(USER_A, record);
  assert.equal(readSavedSnapshot(USER_A), null); // one record isn't the whole list

  await loadSavedOpportunities('token-a', USER_A);
  const next = await saveScholarship('token-a', 'sch-db-6');
  rememberSavedRecord(USER_A, next);
  rememberSavedRecord(USER_A, next);
  assert.equal(readSavedSnapshot(USER_A).length, 2);
  forgetSavedRecord(USER_A, 'sch-db-5');
  assert.deepEqual(readSavedSnapshot(USER_A).map((item) => item.scholarship_id), [6]);
});

test('the queue runs requests in order and survives failures', async () => {
  const enqueue = createSavedQueue();
  const order = [];
  let release;
  const first = enqueue(() => new Promise((resolve) => { release = () => { order.push('load'); resolve('loaded'); }; }));
  const second = enqueue(async () => { order.push('save'); throw new Error('failed'); });
  const third = enqueue(async () => { order.push('remove'); return 'removed'; });
  await new Promise((resolve) => setTimeout(resolve));
  assert.deepEqual(order, []);
  release();
  assert.equal(await first, 'loaded');
  await assert.rejects(second);
  assert.equal(await third, 'removed');
  assert.deepEqual(order, ['load', 'save', 'remove']);
});

test('a stuck request in one account does not hold up another', async () => {
  const accountA = createSavedQueue();
  const accountB = createSavedQueue();
  accountA(() => new Promise(() => {}));
  assert.equal(await accountB(async () => 'done'), 'done');
});

test('a slow load for one student writes only to that student', async () => {
  const server = fakeBackend();
  server.byToken['token-a'].push(5);
  const realFetch = globalThis.fetch;
  let release;
  globalThis.fetch = async (...args) => {
    await new Promise((resolve) => { release = resolve; });
    return realFetch(...args);
  };
  const slow = loadSavedOpportunities('token-a', USER_A);
  await new Promise((resolve) => setTimeout(resolve));
  globalThis.fetch = realFetch;
  server.byToken['token-b'].push(6);
  await loadSavedOpportunities('token-b', USER_B);
  release();
  await slow;
  assert.deepEqual(readOpportunityData(USER_A).savedOpportunities, ['sch-db-5']);
  assert.deepEqual(readOpportunityData(USER_B).savedOpportunities, ['sch-db-6']);
});

test('notices separate loading, a known list, an unknown list and normal use', () => {
  assert.equal(getSavedNotice('ready', true), null);
  assert.equal(getSavedNotice('ready', false), null);
  assert.equal(getSavedNotice('loading', true), null); // the last list stays on screen
  assert.equal(getSavedNotice('loading', false).kind, 'loading');
  assert.match(getSavedNotice('error', true).text, /last saved list/);
  assert.match(getSavedNotice('error', false).text, /may look empty/);
});

test('an unverified saved scholarship resolves from its record, not the catalog', async () => {
  const server = fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  server.unverified.push(5);
  const { records } = await loadSavedOpportunities('token-a', USER_A);
  const item = resolveSavedItem('sch-db-5', records, () => null);
  assert.equal(item.name, 'Scholarship 5');
  assert.equal(item.sourceStatus, 'unverified');
  assert.equal(item.applicationUrlStatus, 'unavailable');
});

test('the record overrides an older verified catalog entry', () => {
  const records = [{ scholarship_id: 5, scholarship: { id: 5, name: 'S', verification_status: 'unverified' } }];
  const stale = () => ({ id: 'sch-db-5', sourceStatus: 'official-verified' });
  assert.equal(resolveSavedItem('sch-db-5', records, stale).sourceStatus, 'unverified');
});

test('a verified saved scholarship stays verified, and a missing status is not', () => {
  const verified = [{ scholarship_id: 5, scholarship: {
    id: 5,
    name: 'S',
    verification_status: 'verified',
    verification_basis: 'official_source',
    official_info_url: 'https://example.org/scholarship',
    last_verified_date: '2026-10-01',
  } }];
  assert.equal(resolveSavedItem('sch-db-5', verified, () => null).sourceStatus, 'official-verified');
  const unknown = [{ scholarship_id: 5, scholarship: { id: 5, name: 'S', verification_status: null } }];
  assert.equal(resolveSavedItem('sch-db-5', unknown, () => null).sourceStatus, 'unverified');
});

test('saved programs still resolve from the catalog', () => {
  assert.equal(resolveSavedItem('univ-db-2', [], (id) => ({ id })).id, 'univ-db-2');
  assert.equal(resolveSavedItem('sch-db-404', [], () => null), null);
});

test('a deleted scholarship is reported once, with its name', async () => {
  const server = fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  await saveScholarship('token-a', 'sch-db-6');
  await loadSavedOpportunities('token-a', USER_A);
  server.byToken['token-a'] = [6];
  server.deleted.push(5);
  const { ids, removed } = await loadSavedOpportunities('token-a', USER_A);
  assert.deepEqual(ids, ['sch-db-6']);
  assert.deepEqual(removed, [{ scholarship_id: 5, name: 'Scholarship 5' }]);
  assert.equal((await loadSavedOpportunities('token-a', USER_A)).removed.length, 1);
  dismissRemovedSaves(USER_A);
  assert.deepEqual(readRemovedSaves(USER_A), []);
});

test('a scholarship removed on another device is not called deleted', async () => {
  const server = fakeBackend();
  await saveScholarship('token-a', 'sch-db-5');
  await loadSavedOpportunities('token-a', USER_A);
  server.byToken['token-a'] = [];
  assert.deepEqual((await loadSavedOpportunities('token-a', USER_A)).removed, []);
});

test('deletion is never reported when the check itself fails', async () => {
  const server = fakeBackend({ failOn: (method) => method === 'PUBLIC' });
  await saveScholarship('token-a', 'sch-db-5');
  await loadSavedOpportunities('token-a', USER_A);
  server.byToken['token-a'] = [];
  server.deleted.push(5);
  assert.deepEqual((await loadSavedOpportunities('token-a', USER_A)).removed, []);
});

test('error messages say what did not happen', () => {
  assert.match(getSaveErrorMessage(new TypeError('Failed to fetch'), false), /couldn't be saved/);
  assert.match(getSaveErrorMessage(new TypeError('Failed to fetch'), true), /couldn't be removed/);
  assert.match(getSaveErrorMessage({ status: 401 }, false), /sign in again/i);
  assert.match(getSaveErrorMessage({ status: 404 }, false), /no longer available/);
});
