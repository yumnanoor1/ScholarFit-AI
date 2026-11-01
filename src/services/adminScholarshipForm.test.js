import assert from 'node:assert/strict';
import test from 'node:test';
import {
  FORM_SECTIONS, getOpenReviewGroups, isDirty, toFormValues, toPayload, validateForm,
} from './adminScholarshipForm.js';
import { getErrorMessage } from './adminApi.js';

const blank = () => toFormValues(null);

test('blank fields are sent as null, never 0, false or an empty string', () => {
  const payload = toPayload(blank());
  assert.ok(Object.values(payload).every((value) => value === null));
});

test('a real zero and a real no are kept', () => {
  const payload = toPayload({ ...blank(), travel_amount: '0', stipend_is_approximate: 'false' });
  assert.equal(payload.travel_amount, 0);
  assert.equal(payload.stipend_is_approximate, false);
});

test('a record survives the form unchanged', () => {
  const record = { name: 'A', min_ielts: 6.5, eligible_countries: ['Pakistan', 'Kenya'], stipend_is_approximate: false, min_age: null };
  const payload = toPayload(toFormValues(record));
  assert.equal(payload.min_ielts, 6.5);
  assert.deepEqual(payload.eligible_countries, ['Pakistan', 'Kenya']);
  assert.equal(payload.stipend_is_approximate, false);
  assert.equal(payload.min_age, null);
});

test('list fields split by line, so names with commas stay whole', () => {
  const payload = toPayload({ ...blank(), eligible_disciplines: 'History, French Language\n\n  Law ' });
  assert.deepEqual(payload.eligible_disciplines, ['History, French Language', 'Law']);
});

test('required fields and formats are checked', () => {
  const errors = validateForm({ ...blank(), min_ielts: 'six', min_age: '20.5', official_info_url: 'example' });
  assert.ok(errors.name && errors.country);
  assert.ok(errors.min_ielts && errors.min_age && errors.official_info_url);
  assert.deepEqual(validateForm({ ...blank(), name: 'A', country: 'B', official_info_url: 'https://example.org/a' }), {});
});

test('verification fields are not part of the edit form', () => {
  const names = FORM_SECTIONS.flatMap((section) => section.fields.map((field) => field.name));
  ['verification_status', 'verification_basis', 'last_verified_date', 'duplicate_of_id', 'role'].forEach((name) => assert.ok(!names.includes(name), name));
  assert.equal(new Set(names).size, names.length);
});

test('changes are noticed', () => {
  const original = toFormValues({ name: 'A' });
  assert.equal(isDirty(original, original), false);
  assert.equal(isDirty({ ...original, name: 'B' }, original), true);
});

test('open review groups come from the flags', () => {
  assert.deepEqual(getOpenReviewGroups(['outdated_source', 'review:english']), ['english']);
  assert.deepEqual(getOpenReviewGroups(null), []);
});

test('validation errors name the field', () => {
  assert.equal(getErrorMessage({ detail: [{ loc: ['body', 'funding_level'], msg: 'Input should be full' }] }, 422), 'funding_level: Input should be full');
  assert.equal(getErrorMessage({ detail: 'Nope' }, 403), 'Nope');
  assert.equal(getErrorMessage(null, 500), 'The request failed (500).');
});
