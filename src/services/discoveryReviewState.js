export function createLatestRequestGuard() {
  let latestRequest = 0;

  return {
    begin() {
      latestRequest += 1;
      return latestRequest;
    },
    isCurrent(requestId) {
      return requestId === latestRequest;
    },
    invalidate() {
      latestRequest += 1;
    },
  };
}

export function createActionGuard() {
  let active = false;

  return {
    isActive() {
      return active;
    },
    tryStart() {
      if (active) return false;
      active = true;
      return true;
    },
    finish() {
      active = false;
    },
  };
}

export function getReviewQueueViewState({ loading, error, result }) {
  if (error) return 'error';
  if (loading || !result) return 'loading';
  return result.items.length === 0 ? 'empty' : 'results';
}

export function getDiscoveryCandidateCounts(monitoring) {
  return {
    awaitingReview: monitoring?.review_queue_pending ?? 0,
    totalReviewCandidates: monitoring?.candidates_total ?? 0,
  };
}

export function getReviewDecisionAnnouncement(decision, item) {
  switch (decision) {
    case 'link_and_publish':
      return item.accepted_scholarship_id
        ? `Discovery published and linked to scholarship #${item.accepted_scholarship_id}; canonical fields were not overwritten.`
        : 'Discovery published and linked to the existing scholarship; canonical fields were not overwritten.';
    case 'accepted':
      return item.accepted_scholarship_id
        ? `Candidate accepted; unverified scholarship #${item.accepted_scholarship_id} created.`
        : 'Candidate accepted.';
    case 'rejected':
      return 'Candidate rejected.';
    case 'duplicate':
      return item.duplicate_of_scholarship_id
        ? `Candidate marked as a duplicate of scholarship #${item.duplicate_of_scholarship_id}; no records were merged.`
        : 'Candidate marked as a duplicate; no records were merged.';
    case 'reviewed':
      return 'Candidate marked as reviewed.';
    default:
      throw new Error(`Unsupported discovery review decision: ${decision}`);
  }
}

export function buildReviewDecisionPayload(decision, {
  values,
  duplicateId,
  linkToScholarshipId,
} = {}) {
  const payload = { decision };
  if ((decision === 'accepted' || decision === 'link_and_publish') && values !== undefined) {
    payload.values = values;
  }
  if (decision === 'duplicate') {
    const id = Number(duplicateId);
    if (!Number.isInteger(id) || id < 1) {
      throw new Error('Enter a valid existing scholarship ID.');
    }
    payload.duplicate_of_scholarship_id = id;
  }
  if (decision === 'link_and_publish') {
    const id = Number(linkToScholarshipId);
    if (!Number.isInteger(id) || id < 1) {
      throw new Error('Enter a valid existing scholarship ID to link.');
    }
    payload.link_to_scholarship_id = id;
  }
  return payload;
}
