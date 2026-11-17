const LIFECYCLE_DECISIONS = new Set(['revoke', 'expire', 'withdraw', 'supersede']);

export function getPublicationSummary(publication) {
  const sources = publication.sources || [];
  const checkedAt = sources
    .map((source) => source.last_checked_at)
    .filter(Boolean)
    .sort((left, right) => Date.parse(right) - Date.parse(left))[0] || null;

  return {
    title: publication.scholarship_name || publication.current_version?.candidate_name_at_approval || 'Untitled scholarship',
    canonicalScholarshipId: publication.canonical_scholarship_id,
    status: publication.status,
    versionNumber: publication.current_version_number ?? publication.current_version?.version_number ?? null,
    reviewItemId: publication.current_version?.review_item_id ?? null,
    sourceNames: sources.map((source) => source.source_name),
    lastCheckedAt: checkedAt,
    createdAt: publication.created_at,
    updatedAt: publication.updated_at,
  };
}

export function getPublicationVersionDetails(version) {
  return {
    reviewItemId: version.review_item_id,
    candidateName: version.candidate_name_at_approval,
    hostCountry: version.host_country_at_approval,
    approvalDecision: version.approval_decision,
    reviewer: version.approved_by_email,
    approvedAt: version.approved_at,
    approvedValues: version.approved_values || {},
    sourceEvidence: Array.isArray(version.source_evidence) ? version.source_evidence : [],
  };
}

export function buildPublicationLifecyclePayload(decision, reason, successorPublicationId = '') {
  if (!LIFECYCLE_DECISIONS.has(decision)) {
    throw new Error('Choose a supported publication lifecycle action.');
  }
  const trimmedReason = reason.trim();
  if (!trimmedReason) {
    throw new Error('Enter a reason for the lifecycle action.');
  }
  const payload = { decision, reason: trimmedReason };
  if (decision === 'supersede') {
    const successorId = successorPublicationId.trim();
    if (successorId.length !== 36) {
      throw new Error('Enter the ID of an existing published successor.');
    }
    payload.superseded_by_publication_id = successorId;
  }
  return payload;
}
