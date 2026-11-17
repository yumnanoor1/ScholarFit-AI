import test from 'node:test';
import assert from 'node:assert/strict';
import { getSourceEvidence, SOURCE_VERIFICATION_MAX_AGE_DAYS } from './sourceVerification.js';

const today = '2026-11-02';

test('scholarship evidence is verified only with a current official source and date', () => {
  const evidence = getSourceEvidence({
    sourceUrl: 'https://example.org/scholarship',
    lastVerified: '2026-10-01',
    verificationStatus: 'verified',
    verificationBasis: 'official_source',
    today,
  });
  assert.equal(evidence.status, 'verified');
  assert.equal(evidence.label, 'Verified against official source');
});

test('stale scholarship evidence is labeled as requiring verification', () => {
  const evidence = getSourceEvidence({
    sourceUrl: 'https://example.org/scholarship',
    lastVerified: '2026-01-01',
    verificationStatus: 'verified',
    verificationBasis: 'official_source',
    today,
  });
  assert.equal(evidence.status, 'outdated');
  assert.match(evidence.label, /needs verification/i);
  assert.match(evidence.message, /over 180 days old/);
});

test('missing source information is never considered verified', () => {
  assert.equal(getSourceEvidence({
    sourceUrl: null,
    lastVerified: '2026-10-01',
    verificationStatus: 'verified',
    verificationBasis: 'official_source',
    today,
  }).status, 'needs-verification');
  assert.equal(getSourceEvidence({
    sourceUrl: 'https://example.org/scholarship',
    lastVerified: null,
    verificationStatus: 'verified',
    verificationBasis: 'official_source',
    today,
  }).status, 'needs-verification');
});

test('a current source date alone does not claim university or program verification', () => {
  const evidence = getSourceEvidence({
    sourceUrl: 'https://example.org/program',
    lastVerified: '2026-10-01',
    today,
  });
  assert.equal(evidence.status, 'recorded');
  assert.equal(evidence.label, 'Verification status not tracked');
});

test('the 180-day boundary remains current', () => {
  const day = new Date(`${today}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - SOURCE_VERIFICATION_MAX_AGE_DAYS);
  const evidence = getSourceEvidence({
    sourceUrl: 'https://example.org/scholarship',
    lastVerified: day.toISOString().slice(0, 10),
    verificationStatus: 'verified',
    verificationBasis: 'official_source',
    today,
  });
  assert.equal(evidence.status, 'verified');
});
