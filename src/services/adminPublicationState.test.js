import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildPublicationLifecyclePayload,
  getPublicationSummary,
  getPublicationVersionDetails,
} from './adminPublicationState.js';

test('publication summary maps title, linked record, candidate, sources and freshness', () => {
  const summary = getPublicationSummary({
    scholarship_name: 'Global Scholars Award',
    canonical_scholarship_id: 24,
    status: 'published',
    current_version_number: 3,
    current_version: { version_number: 3, review_item_id: 82, candidate_name_at_approval: 'Global Scholars' },
    sources: [
      { source_name: 'Earlier source', last_checked_at: '2026-02-01T10:00:00Z' },
      { source_name: 'Current source', last_checked_at: '2026-02-04T10:00:00Z' },
    ],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-02-04T10:00:00Z',
  });

  assert.deepEqual(summary, {
    title: 'Global Scholars Award',
    canonicalScholarshipId: 24,
    status: 'published',
    versionNumber: 3,
    reviewItemId: 82,
    sourceNames: ['Earlier source', 'Current source'],
    lastCheckedAt: '2026-02-04T10:00:00Z',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-02-04T10:00:00Z',
  });
});

test('publication version inspection maps approved values, evidence, decision and reviewer', () => {
  const details = getPublicationVersionDetails({
    review_item_id: 82,
    candidate_name_at_approval: 'Global Scholars',
    host_country_at_approval: 'Germany',
    approval_decision: 'link_and_publish',
    approved_by_email: 'admin@example.test',
    approved_at: '2026-02-04T10:00:00Z',
    approved_values: { name: 'Global Scholars Award', country: 'Germany' },
    source_evidence: [{ source_name: 'Official provider', source_url: 'https://example.org/award' }],
  });

  assert.deepEqual(details, {
    reviewItemId: 82,
    candidateName: 'Global Scholars',
    hostCountry: 'Germany',
    approvalDecision: 'link_and_publish',
    reviewer: 'admin@example.test',
    approvedAt: '2026-02-04T10:00:00Z',
    approvedValues: { name: 'Global Scholars Award', country: 'Germany' },
    sourceEvidence: [{ source_name: 'Official provider', source_url: 'https://example.org/award' }],
  });
});

test('lifecycle payloads match backend decisions and require a superseding publication', () => {
  for (const decision of ['revoke', 'expire', 'withdraw']) {
    assert.deepEqual(
      buildPublicationLifecyclePayload(decision, '  Source is no longer valid  '),
      { decision, reason: 'Source is no longer valid' },
    );
  }
  assert.deepEqual(
    buildPublicationLifecyclePayload(
      'supersede',
      'New publication replaces this one',
      '00000000-0000-0000-0000-000000000002',
    ),
    {
      decision: 'supersede',
      reason: 'New publication replaces this one',
      superseded_by_publication_id: '00000000-0000-0000-0000-000000000002',
    },
  );
  assert.throws(() => buildPublicationLifecyclePayload('supersede', 'No successor'), /successor/);
  assert.throws(() => buildPublicationLifecyclePayload('revoke', '   '), /reason/);
});
