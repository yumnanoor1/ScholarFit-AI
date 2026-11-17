import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  EMPTY_FILTERS, PAGE_SIZE, SORT_OPTIONS, buildSearchQuery, getActiveFilters, getPageCount, removeFilterValue, toggleFilterValue,
} from './scholarshipSearch.js';

const params = (filters, options) => new URLSearchParams(buildSearchQuery({ ...EMPTY_FILTERS, ...filters }, options));

test('empty filters send only the page', () => {
  assert.equal(buildSearchQuery(EMPTY_FILTERS), `skip=0&limit=${PAGE_SIZE}`);
});

test('search text is trimmed and spaces collapse', () => {
  assert.equal(params({ q: '  erasmus    mundus ' }).get('q'), 'erasmus mundus');
  assert.equal(params({ q: '   ' }).has('q'), false);
});

test('several values of a filter are all sent', () => {
  assert.deepEqual(params({ funding: ['fully_funded', 'tuition_only'] }).getAll('funding'), ['fully_funded', 'tuition_only']);
});

test('host country and nationality stay separate parameters', () => {
  const query = params({ host_country: ['Germany'], nationality: 'Pakistan' });
  assert.deepEqual(query.getAll('host_country'), ['Germany']);
  assert.equal(query.get('nationality'), 'Pakistan');
});

test('no user ID is ever sent', () => {
  assert.equal(buildSearchQuery(EMPTY_FILTERS, { programId: 1 }).includes('user'), false);
});

test('a page turns into skip', () => {
  assert.equal(params({}, { page: 3 }).get('skip'), String(2 * PAGE_SIZE));
});

test('unsupported program-match filters are never sent', () => {
  const query = params({ match: ['confirmed'], program_id: '4' });
  assert.equal(query.has('match'), false);
  assert.equal(query.has('program_id'), false);
});

test('toggling adds then removes', () => {
  const on = toggleFilterValue(EMPTY_FILTERS, 'deadline', 'open');
  assert.deepEqual(on.deadline, ['open']);
  assert.deepEqual(toggleFilterValue(on, 'deadline', 'open').deadline, []);
  assert.deepEqual(EMPTY_FILTERS.deadline, []);
});

test('clearing one filter keeps the others', () => {
  const filters = { ...EMPTY_FILTERS, q: 'daad', funding: ['fully_funded', 'tuition_only'], deadline: ['open'] };
  const next = removeFilterValue(filters, 'funding', 'tuition_only');
  assert.deepEqual(next.funding, ['fully_funded']);
  assert.deepEqual(next.deadline, ['open']);
  assert.equal(next.q, 'daad');
  assert.equal(removeFilterValue(filters, 'q', 'daad').q, '');
});

test('active filters use readable labels', () => {
  const options = { funding: [{ value: 'fully_funded', label: 'Fully funded' }] };
  const active = getActiveFilters({ ...EMPTY_FILTERS, q: ' daad ', funding: ['fully_funded'], nationality: 'Kenya', eligibility: ['verify_manually'] }, options);
  assert.deepEqual(active.map((item) => item.label), ['Search: daad', 'Citizen of: Kenya', 'Funding: Fully funded', 'Eligibility: Verify manually']);
});

test('page count handles empty results', () => {
  assert.equal(getPageCount(0), 1);
  assert.equal(getPageCount(PAGE_SIZE + 1), 2);
});

test('recommendation sorting asks for a login', () => {
  assert.equal(SORT_OPTIONS.find((item) => item.value === 'recommendation').needsLogin, true);
  assert.equal(SORT_OPTIONS.length, 7);
});

test('Explore uses the search API and leaves My Matches alone', () => {
  const page = readFileSync(new URL('../pages/Scholarships.jsx', import.meta.url), 'utf8');
  assert.ok(page.includes('apiService.searchScholarships'));
  assert.ok(!page.includes('match_score'));
  const matches = readFileSync(new URL('../pages/Recommendations.jsx', import.meta.url), 'utf8');
  assert.ok(!matches.includes('searchScholarships'));
});
