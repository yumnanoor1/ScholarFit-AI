import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { adminApi } from './adminApi.js';

let originalFetch;
let calls;

const jsonResponse = (data, { ok = true, status = 200 } = {}) => ({
  ok,
  status,
  json: async () => data,
});

beforeEach(() => {
  originalFetch = globalThis.fetch;
  calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ result: 'ok' });
  };
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

async function assertRequest(invoke, { path, method = 'GET', body }) {
  assert.deepEqual(await invoke(), { result: 'ok' });
  assert.equal(calls.length, 1);
  const [{ url, options }] = calls;
  assert.equal(url, `http://127.0.0.1:8000${path}`);
  assert.equal(options.method, method);
  assert.equal(options.headers.Authorization, 'Bearer api-token');
  if (body === undefined) {
    assert.equal(options.body, undefined);
  } else {
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(options.body), body);
  }
}

test('Admin JSON operations use the configured fallback base URL, paths, methods and bodies', async () => {
  const id = 17;
  const verification = { status: 'verified', evidence_reviewed: true };
  const flag = { flag: 'outdated_source', active: true };
  const review = { decision: 'rejected', note: 'Not eligible' };
  const duplicate = { duplicate_of_id: 18, note: 'Same award' };
  const body = { name: 'Updated award' };

  const operations = [
    [() => adminApi.summary('api-token'), '/admin/scholarships/summary'],
    [() => adminApi.list('api-token', 'q=Award&skip=5'), '/admin/scholarships?q=Award&skip=5'],
    [() => adminApi.detail('api-token', id), `/admin/scholarships/${id}`],
    [() => adminApi.create('api-token', body), '/scholarships/', 'POST', body],
    [() => adminApi.update('api-token', id, body), `/scholarships/${id}`, 'PUT', body],
    [() => adminApi.remove('api-token', id), `/scholarships/${id}`, 'DELETE'],
    [() => adminApi.verify('api-token', id, verification), `/admin/scholarships/${id}/verification`, 'POST', verification],
    [() => adminApi.flag('api-token', id, flag), `/admin/scholarships/${id}/flags`, 'POST', flag],
    [() => adminApi.checkSources('api-token', id), `/admin/scholarships/${id}/source-check`, 'POST'],
    [() => adminApi.archive('api-token', id, 'Expired cycle'), `/admin/scholarships/${id}/archive`, 'POST', { reason: 'Expired cycle' }],
    [() => adminApi.restore('api-token', id), `/admin/scholarships/${id}/restore`, 'POST'],
    [() => adminApi.duplicates('api-token'), '/admin/scholarships/duplicates'],
    [() => adminApi.compare('api-token', id, 18), `/admin/scholarships/duplicates/compare?first=${id}&second=18`],
    [() => adminApi.markDuplicate('api-token', id, duplicate), `/admin/scholarships/${id}/duplicate`, 'POST', duplicate],
    [() => adminApi.reviewDiscovery('api-token', id, review), `/admin/scholarships/discovery-reviews/${id}/review`, 'POST', review],
    [
      () => adminApi.reviewDiscovery('api-token', id, {
        decision: 'link_and_publish',
        link_to_scholarship_id: 24,
        values: { name: 'Existing Award', country: 'Finland' },
      }),
      `/admin/scholarships/discovery-reviews/${id}/review`,
      'POST',
      {
        decision: 'link_and_publish',
        link_to_scholarship_id: 24,
        values: { name: 'Existing Award', country: 'Finland' },
      },
    ],
    [
      () => adminApi.discoveryPublications('api-token', { status: 'published', scholarshipId: id, skip: 25, limit: 10 }),
      '/admin/scholarships/discovery-publications?skip=25&limit=10&status=published&scholarship_id=17',
    ],
    [
      () => adminApi.discoveryPublicationEvents('api-token', '00000000-0000-0000-0000-000000000001'),
      '/admin/scholarships/discovery-publications/00000000-0000-0000-0000-000000000001/events?skip=0&limit=50',
    ],
    [
      () => adminApi.transitionDiscoveryPublication(
        'api-token',
        '00000000-0000-0000-0000-000000000001',
        { decision: 'revoke', reason: 'Source withdrawn' },
      ),
      '/admin/scholarships/discovery-publications/00000000-0000-0000-0000-000000000001/lifecycle',
      'POST',
      { decision: 'revoke', reason: 'Source withdrawn' },
    ],
    [() => adminApi.discoveryMonitoring('api-token'), '/admin/scholarships/discovery-monitoring'],
    [() => adminApi.startManualDiscovery('api-token'), '/admin/scholarships/discovery-runs/manual', 'POST'],
    [() => adminApi.discoverySources('api-token'), '/admin/scholarships/discovery-sources'],
  ];

  for (const [invoke, path, method, requestBody] of operations) {
    calls = [];
    await assertRequest(invoke, { path, method, body: requestBody });
  }
});

test('publication list filters are URL-encoded and optional', async () => {
  await assertRequest(
    () => adminApi.discoveryPublications('api-token', { status: 'content changed', scholarshipId: 31 }),
    {
      path: '/admin/scholarships/discovery-publications?skip=0&limit=25&status=content+changed&scholarship_id=31',
    },
  );
  calls = [];
  await assertRequest(
    () => adminApi.discoveryPublications('api-token'),
    { path: '/admin/scholarships/discovery-publications?skip=0&limit=25' },
  );
});

test('discovery list filters and pagination are serialized and trimmed', async () => {
  await assertRequest(
    () => adminApi.discoveryReviews('api-token', 'pending', 3, 10, '  A&B  '),
    {
      path: '/admin/scholarships/discovery-reviews?skip=3&limit=10&status=pending&q=A%26B',
    },
  );
  calls = [];
  await assertRequest(
    () => adminApi.discoveryHistory('api-token', {
      status: 'partial',
      days: 14,
      q: '  Cycle 2  ',
      skip: 20,
      limit: 5,
    }),
    {
      path: '/admin/scholarships/discovery-history?days=14&skip=20&limit=5&status=partial&q=Cycle+2',
    },
  );
});

test('source extraction sends multipart form data without setting its content type', async () => {
  const file = new File(['%PDF-1.7'], 'award.pdf', { type: 'application/pdf' });
  await adminApi.extractScholarshipSource('api-token', {
    sourceType: 'pdf_upload',
    url: '',
    file,
  });

  const [{ url, options }] = calls;
  assert.equal(url, 'http://127.0.0.1:8000/admin/scholarships/import/extract');
  assert.equal(options.method, 'POST');
  assert.equal(options.headers.Authorization, 'Bearer api-token');
  assert.equal(options.headers['Content-Type'], undefined);
  assert.ok(options.body instanceof FormData);
  assert.equal(options.body.get('source_type'), 'pdf_upload');
  assert.equal(options.body.get('url'), null);
  assert.equal(options.body.get('file').name, 'award.pdf');
});

test('successful responses and structured discovery conflicts preserve their details', async () => {
  const response = { items: [{ id: 1, name: 'Award' }], total: 1 };
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return jsonResponse(response);
  };
  assert.deepEqual(await adminApi.summary('api-token'), response);

  globalThis.fetch = async () => jsonResponse({
    detail: [{ loc: ['body', 'name'], msg: 'Field required' }],
  }, { ok: false, status: 422 });
  await assert.rejects(adminApi.create('api-token', {}), (error) => {
    assert.equal(error.status, 422);
    assert.equal(error.message, 'name: Field required');
    return true;
  });

  globalThis.fetch = async () => jsonResponse({
    detail: {
      code: 'DISCOVERY_ADVISORY_LOCK_ACTIVE',
      message: 'Another discovery worker currently holds the PostgreSQL advisory lock.',
    },
  }, { ok: false, status: 409 });
  await assert.rejects(adminApi.startManualDiscovery('api-token'), (error) => {
    assert.equal(error.status, 409);
    assert.equal(error.code, 'DISCOVERY_ADVISORY_LOCK_ACTIVE');
    assert.equal(error.message, 'Another discovery worker currently holds the PostgreSQL advisory lock.');
    return true;
  });
});

test('non-JSON errors use the status fallback and token failures are surfaced', async () => {
  globalThis.fetch = async () => ({
    ok: false,
    status: 500,
    json: async () => { throw new Error('invalid JSON'); },
  });
  await assert.rejects(adminApi.summary('api-token'), (error) => {
    assert.equal(error.status, 500);
    assert.equal(error.message, 'The request failed (500).');
    return true;
  });

  for (const token of [undefined, 'invalid-or-expired-token']) {
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      return jsonResponse({ detail: 'Invalid token' }, { ok: false, status: 401 });
    };
    await assert.rejects(adminApi.summary(token), (error) => {
      assert.equal(error.status, 401);
      assert.equal(error.message, 'Invalid token');
      return true;
    });
    assert.equal(calls.at(-1).options.headers.Authorization, `Bearer ${token}`);
  }
});

test('network failures use the shared readable connection error', async () => {
  globalThis.fetch = async () => {
    throw new TypeError('network unavailable');
  };
  await assert.rejects(adminApi.summary('api-token'), {
    message: 'We couldn’t reach FitScholars. Check your connection and try again.',
  });
});
