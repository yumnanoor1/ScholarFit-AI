import assert from 'node:assert/strict';
import test from 'node:test';
import { humanizeEnum, isSameStoredValue } from './textFormat.js';

test('stored enums read as a person would write them', () => {
  assert.equal(humanizeEnum('full'), 'Full');
  assert.equal(humanizeEnum('varies_by_institution'), 'Varies by institution');
  assert.equal(humanizeEnum('government_authority'), 'Government authority');
  assert.equal(humanizeEnum('official_provider'), 'Official provider');
  assert.equal(humanizeEnum('catch_up'), 'Catch up');
  assert.equal(humanizeEnum('masters, phd'), 'Masters, Phd');
});

test('prose, names, dates, amounts and URLs are left exactly as stored', () => {
  for (const value of [
    'Open to all nationalities',
    'https://www.daad.de/en/award/',
    'Germany',
    'DAAD',
    '934 EUR',
    '2027-07-31',
    'Master of Science (MSc)',
    'A sentence with words.',
  ]) {
    assert.equal(humanizeEnum(value), value, value);
  }
});

test('anything that is not a string comes back untouched', () => {
  assert.equal(humanizeEnum(''), '');
  assert.equal(humanizeEnum(null), null);
  assert.equal(humanizeEnum(undefined), undefined);
  assert.equal(humanizeEnum(7), 7);
});

test('a list is only humanized when every item is a token', () => {
  assert.equal(humanizeEnum('full, varies_by_institution'), 'Full, Varies by institution');
  // One real sentence in the list and the whole value is left alone.
  assert.equal(
    humanizeEnum('full, Decided by the host university'),
    'full, Decided by the host university',
  );
});

test('case and whitespace alone are not a difference', () => {
  assert.equal(isSameStoredValue('Full', 'full'), true);
  assert.equal(isSameStoredValue('Full  ', ' full'), true);
  assert.equal(isSameStoredValue('Open   to all', 'open to all'), true);
  assert.equal(isSameStoredValue('a\nb', 'a b'), true);
});

test('a real difference is still a difference', () => {
  assert.equal(isSameStoredValue('full', 'partial'), false);
  assert.equal(isSameStoredValue('Germany', 'Austria'), false);
  assert.equal(isSameStoredValue('934', '935'), false);
});

test('an empty value equals another empty value, whatever its type', () => {
  assert.equal(isSameStoredValue('', null), true);
  assert.equal(isSameStoredValue(undefined, '   '), true);
  assert.equal(isSameStoredValue('', 'x'), false);
});
