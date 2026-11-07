import test from 'node:test';
import assert from 'node:assert/strict';
import { extractDocumentData } from './documentAnalysis.js';
import { fetchMappedScholarships } from './opportunityApi.js';

test('document analysis rejects instead of returning fabricated extraction results', async () => {
  await assert.rejects(
    extractDocumentData({ name: 'transcript.pdf' }),
    /Document analysis is unavailable/,
  );
});

test('an empty scholarship catalogue remains empty', async (context) => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response('[]', { status: 200 });
  context.after(() => { globalThis.fetch = originalFetch; });
  assert.deepEqual(await fetchMappedScholarships(), []);
});

test('catalogue API failures propagate without sample fallbacks', async (context) => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError('network unavailable'); };
  context.after(() => { globalThis.fetch = originalFetch; });
  await assert.rejects(fetchMappedScholarships(), /network unavailable/);
});
