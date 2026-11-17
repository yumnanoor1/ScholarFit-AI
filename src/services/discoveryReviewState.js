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

// --- candidate evidence ----------------------------------------------------

const UNSET_VALUES = new Set([null, undefined, '']);

function isSet(value) {
  if (UNSET_VALUES.has(value)) return false;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function quoteText(value) {
  return typeof value === 'string' ? value.trim() : '';
}

/**
 * Which value fields each stored evidence key actually vouches for.
 *
 * The extractor asks the model for one quote per value field, but in practice
 * it returns only the structural quotes the response shape names explicitly,
 * so `evidence` holds keys from a different namespace than `values`
 * (`host_location`, not `country`). Comparing the two namespaces directly is
 * what made every candidate read "0/N fields quoted".
 *
 * These are the mappings the extraction rules themselves state:
 *   host_location  must link study, institution or campus to the host country
 *   host_city      names the host city, hence the hosting institution
 *   masters_evidence           proves the award is Master's level
 *   scholarship_offer_evidence proves this page offers the named award
 */
export const EVIDENCE_KEY_FIELDS = {
  host_location: ['country'],
  host_city: ['host_city', 'host_institution'],
  masters_evidence: ['degree_level', 'eligible_degree_levels'],
  scholarship_offer_evidence: ['name'],
};

/** Every field name the stored evidence quotes cover, across all sources. */
export function getEvidenceBackedFieldNames(item) {
  return new Set(getFieldQuotes(item).keys());
}

/**
 * field -> { quote, key, kind } for every field an evidence quote covers.
 *
 * `kind` is 'direct' when the quote was stored under the field's own name and
 * 'page' when it comes from one of the structural quotes above, so the panel
 * can say which it is showing rather than implying a per-field quote exists.
 * A direct quote always wins over a structural one.
 */
export function getFieldQuotes(item) {
  const quotes = new Map();
  const put = (field, quote, key, kind) => {
    if (!quote) return;
    const existing = quotes.get(field);
    if (existing && existing.kind === 'direct' && kind !== 'direct') return;
    quotes.set(field, { quote, key, kind });
  };
  for (const snapshot of item?.evidence_excerpts || []) {
    const stored = snapshot?.evidence_excerpts;
    if (!stored || typeof stored !== 'object') continue;
    for (const [key, raw] of Object.entries(stored)) {
      const quote = quoteText(raw);
      if (!quote) continue;
      const mapped = EVIDENCE_KEY_FIELDS[key];
      if (mapped) {
        for (const field of mapped) put(field, quote, key, 'page');
      } else {
        put(key, quote, key, 'direct');
      }
    }
  }
  return quotes;
}

/** The evidence quote behind one field, or null when there is none. */
export function getEvidenceQuoteFor(item, field) {
  return getFieldQuotes(item).get(field) || null;
}

/**
 * How much of this candidate an official page actually vouches for.
 *
 * The API records no confidence score, so the column used to read "Not
 * recorded" for every row. This counts the extracted fields that carry an
 * exact evidence quote, which is the thing the extractor really verified.
 */
export function getCandidateEvidenceStrength(item) {
  const values = item?.extracted_values && typeof item.extracted_values === 'object'
    ? item.extracted_values
    : {};
  const filled = Object.keys(values).filter((field) => isSet(values[field]));
  const quotes = getFieldQuotes(item);
  const backedFields = filled.filter((field) => quotes.has(field));
  const backed = backedFields.length;
  const direct = backedFields.filter((field) => quotes.get(field).kind === 'direct').length;
  const total = filled.length;
  const missing = (item?.missing_required_fields || []).length;
  const conflicts = (item?.conflicting_values || []).length;
  const ratio = total === 0 ? 0 : backed / total;

  let label = 'No evidence';
  if (total === 0) label = 'No fields';
  else if (missing > 0 || conflicts > 0) label = 'Needs checks';
  else if (ratio >= 0.75) label = 'Strong';
  else if (ratio >= 0.4) label = 'Partial';
  else if (backed > 0) label = 'Weak';

  const notes = [];
  if (backed > 0 && direct < backed) {
    notes.push(
      `${backed - direct} of those rest on a page-level quote (host location, `
      + 'Master’s level or the scholarship offer) rather than a quote for the field itself',
    );
  }
  if (missing > 0) notes.push(`${missing} required field(s) missing`);
  if (conflicts > 0) notes.push(`${conflicts} conflicting field(s)`);

  return {
    backed,
    direct,
    total,
    label,
    summary: total === 0 ? 'No extracted fields' : `${backed}/${total} fields quoted`,
    title: [
      `${backed} of ${total} extracted field(s) carry an exact quote from the source page`,
      ...notes,
    ].join('. '),
  };
}

// --- review reasons --------------------------------------------------------

/**
 * Plain English for each review-reason code, and whether an admin has to act
 * on it. 'must' covers missing required fields and contradictions; 'optional'
 * covers detail an admin can accept without checking.
 */
const REVIEW_REASON_TEXT = {
  admin_review_required: ['Needs an admin decision', 'must'],
  incomplete_or_conflicting_candidate: ['The record is incomplete or contradicts itself', 'must'],
  ambiguous_duplicate: ['May already exist as a scholarship', 'must'],
  missing_scholarship_identity: ['The host country could not be established', 'must'],
  host_location_requires_review: ['The host location needs a human check', 'must'],
  conflicting_host_location_evidence: ['The page gives conflicting host locations', 'must'],
  missing_host_location_evidence: ['No quote ties the award to a host country', 'must'],
  missing_host_country_evidence: ['No quote ties the award to a host country', 'must'],
  missing_masters_scope_confirmation: ['Master’s-only scope is unconfirmed', 'must'],
  missing_masters_evidence: ['No quote proves this is a Master’s award', 'must'],
  masters_evidence_unclear: ['The Master’s-level quote is unclear', 'must'],
  missing_scholarship_offer_evidence: ['No quote proves the page offers this award', 'must'],
  scholarship_offer_evidence_unclear: ['The scholarship-offer quote is unclear', 'must'],
  evidence_mismatch_fields_dropped: ['Some values were dropped: their quotes did not match the page', 'must'],
  host_country_from_source_registry: ['Host country taken from the source registry, not the page', 'optional'],
  missing_host_city_evidence: ['No quote names the host city', 'optional'],
  invalid_values_dropped: ['Some values were dropped for being malformed', 'optional'],
  unsupported_fields_dropped: ['The model returned fields this schema does not have', 'optional'],
  unapproved_urls_dropped: ['Links that were not official page links were dropped', 'optional'],
  third_party_application_link_unverified: ['The application link came from a third-party listing', 'optional'],
  third_party_source_links_unverified: ['Source links came from a third-party listing', 'optional'],
};

const FIELD_LABELS = {
  name: 'name',
  country: 'country',
  degree_level: 'degree level',
  eligible_degree_levels: 'eligible degree levels',
  host_institution: 'host institution',
  host_city: 'host city',
  official_url: 'official URL',
  official_info_url: 'official information URL',
  official_application_url: 'official application URL',
  application_deadline_date: 'deadline date',
  application_open_date: 'opening date',
  application_cycle: 'application cycle',
  application_method: 'how to apply',
  application_channel: 'application channel',
  deadline_type: 'deadline type',
  funding_type: 'funding type',
  funding_level: 'funding level',
  tuition_coverage: 'tuition coverage',
  tuition_coverage_type: 'tuition coverage type',
  required_documents_list: 'required documents',
  additional_source_urls: 'additional source URLs',
};

/** A field name as an admin should read it. */
export function describeField(field) {
  if (typeof field !== 'string' || !field) return 'this field';
  return FIELD_LABELS[field] || field.replace(/_/g, ' ');
}

/** The fields whose absent quote matters most to a reviewer. */
const REQUIRED_EVIDENCE_FIELDS = new Set(['name', 'country', 'degree_level']);

/** One review-reason code as plain English, with the group it belongs in. */
export function describeReviewReason(code) {
  const known = REVIEW_REASON_TEXT[code];
  if (known) return { code, text: known[0], group: known[1] };
  if (code.startsWith('missing_evidence:')) {
    const field = code.slice('missing_evidence:'.length);
    return {
      code,
      text: `No quote for the ${describeField(field)}`,
      group: REQUIRED_EVIDENCE_FIELDS.has(field) ? 'must' : 'optional',
    };
  }
  if (code.startsWith('evidence_dropped:')) {
    return {
      code,
      text: `The ${describeField(code.slice('evidence_dropped:'.length))} was dropped: its quote did not match the page`,
      group: 'must',
    };
  }
  if (code.startsWith('url_dropped:')) {
    return {
      code,
      text: `The ${describeField(code.slice('url_dropped:'.length))} was dropped: it was not an official page link`,
      group: 'optional',
    };
  }
  if (code.startsWith('invalid_dropped:')) {
    return {
      code,
      text: `The ${describeField(code.slice('invalid_dropped:'.length))} was dropped for being malformed`,
      group: 'optional',
    };
  }
  // An unmapped code is shown as itself rather than hidden.
  return { code, text: code.replace(/_/g, ' '), group: 'optional' };
}

/** The review reasons the backend joined into one string. */
export function getReviewReasons(item) {
  const reason = item?.review_reason;
  if (typeof reason !== 'string' || !reason.trim()) return [];
  return [...new Set(reason.split(';').map((part) => part.trim()).filter(Boolean))];
}

/** Review reasons split into what must be checked and what is detail. */
export function groupReviewReasons(item) {
  const mustCheck = [];
  const optional = [];
  const seen = new Set();
  for (const code of getReviewReasons(item)) {
    const described = describeReviewReason(code);
    if (seen.has(described.text)) continue;
    seen.add(described.text);
    (described.group === 'must' ? mustCheck : optional).push(described);
  }
  return { mustCheck, optional };
}

// --- one set of status names ----------------------------------------------

export const REVIEW_STATUS_LABELS = {
  pending: 'Needs review',
  reviewed: 'Reviewed',
  accepted: 'Accepted',
  rejected: 'Rejected',
  duplicate: 'Duplicate',
};

export function getReviewStatusLabel(status) {
  return REVIEW_STATUS_LABELS[status] || 'Needs review';
}

// --- deadline, source and run display -------------------------------------

const DEADLINE_TYPE_LABELS = {
  fixed: 'Fixed date',
  rolling: 'Rolling',
  annual: 'Annual',
  multiple_rounds: 'Multiple rounds',
  not_specified: 'Not stated',
};

/**
 * What to show in the Deadline row.
 *
 * The panel used to fall back to `deadline_type`, so a candidate with a real
 * date showed the word "fixed". The date is the answer; the type is a label
 * beside it.
 */
export function getCandidateDeadline(item) {
  const values = item?.extracted_values || {};
  const type = typeof values.deadline_type === 'string' ? values.deadline_type : '';
  const typeLabel = type ? (DEADLINE_TYPE_LABELS[type] || type.replace(/_/g, ' ')) : '';
  const date = quoteText(values.application_deadline_date);
  if (date) return { text: date, typeLabel, isDate: true };
  const stated = quoteText(values.deadline) || quoteText(values.application_deadline);
  if (stated) return { text: stated, typeLabel, isDate: false };
  if (type === 'rolling') return { text: 'Rolling — no fixed date', typeLabel: '', isDate: false };
  return { text: 'Not found on page', typeLabel, isDate: false };
}

/** The registrable domain of the source, e.g. daad.de, for the Source column. */
export function getSourceDomain(item) {
  const url = item?.source_url;
  if (typeof url !== 'string' || !url) return '';
  let host;
  try {
    host = new URL(url).hostname;
  } catch {
    return '';
  }
  host = host.replace(/^www\d*\./, '');
  const parts = host.split('.');
  if (parts.length <= 2) return host;
  // Keep two labels, or three for a public suffix like .ac.uk or .gov.pk.
  const suffix = parts.slice(-2).join('.');
  const twoLabelSuffixes = new Set([
    'ac.uk', 'gov.uk', 'co.uk', 'org.uk',
    'edu.au', 'gov.au', 'ac.jp', 'gov.pk', 'edu.pk',
  ]);
  return twoLabelSuffixes.has(suffix) ? parts.slice(-3).join('.') : suffix;
}

/**
 * The run as a date and time, with the raw UUID kept for the tooltip.
 *
 * The API does not send the run's own started_at with a review item, so this
 * uses when the candidate was recorded, which happens during the run.
 */
export function getRunLabel(item) {
  const id = typeof item?.discovery_run_id === 'string' ? item.discovery_run_id : '';
  const recorded = item?.created_at ? new Date(item.created_at) : null;
  const text = recorded && !Number.isNaN(recorded.getTime())
    ? recorded.toLocaleString()
    : 'Date not available';
  return { text, id, title: id ? `Discovery run ${id}` : 'Discovery run' };
}

// --- possible duplicates in the queue -------------------------------------

const NAME_SYNONYMS = {
  programme: 'programm',
  program: 'programm',
  programmes: 'programm',
  programs: 'programm',
  scholarships: 'scholarship',
  fellowships: 'fellowship',
  awards: 'award',
  grants: 'grant',
  stipendium: 'scholarship',
  stipendien: 'scholarship',
};

const NAME_NOISE = new Set(['the', 'a', 'an', 'of', 'for', 'and', 'der', 'die', 'das', 'und', 'fur', 'de']);

/** A candidate name reduced to comparable tokens. */
export function normalizeCandidateName(name) {
  if (typeof name !== 'string') return '';
  const tokens = name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .split(' ')
    .filter((token) => token && !NAME_NOISE.has(token))
    .map((token) => {
      if (NAME_SYNONYMS[token]) return NAME_SYNONYMS[token];
      // "Programme" and "Programm" are the same word; a trailing e on a long
      // token carries no meaning for matching purposes.
      return token.length > 5 && token.endsWith('e') ? token.slice(0, -1) : token;
    });
  return [...new Set(tokens)].sort().join(' ');
}

function candidateName(item) {
  return item?.candidate_name || item?.extracted_values?.name || '';
}

/**
 * Pending candidates that look like the same award.
 *
 * Two pending items are flagged when their normalized names match, or when
 * they share a source and a host country. Flagging only annotates the queue:
 * nothing is merged, and the admin still decides.
 */
export function findPossibleDuplicates(items) {
  const pending = (items || []).filter((item) => item?.review_status === 'pending');
  const groups = new Map();
  const addTo = (key, item, reason) => {
    if (!key) return;
    const group = groups.get(key) || { ids: [], reason };
    group.ids.push(item.id);
    groups.set(key, group);
  };
  for (const item of pending) {
    const name = normalizeCandidateName(candidateName(item));
    if (name) addTo(`name:${name}`, item, 'similar_name');
  }
  for (const item of pending) {
    const country = quoteText(item.host_country).toLowerCase();
    if (item.source_id && country) {
      addTo(`source:${item.source_id}|${country}`, item, 'same_source_and_country');
    }
  }
  const flagged = new Map();
  for (const group of groups.values()) {
    if (group.ids.length < 2) continue;
    for (const id of group.ids) {
      const others = group.ids.filter((other) => other !== id);
      const existing = flagged.get(id);
      // A name match is the stronger signal, so it is kept over a shared
      // source and country.
      if (existing && existing.reason === 'similar_name' && group.reason !== 'similar_name') continue;
      flagged.set(id, {
        reason: group.reason,
        matchIds: [...new Set([...(existing?.matchIds || []), ...others])].sort((a, b) => a - b),
      });
    }
  }
  return flagged;
}

export const DUPLICATE_REASON_TEXT = {
  similar_name: 'nearly the same name',
  same_source_and_country: 'same source and host country',
};

/**
 * How this candidate could be marked a duplicate.
 *
 * The backend records a duplicate against an existing SCHOLARSHIP, so a pair
 * of pending candidates cannot be linked to each other: one has to be
 * approved first. This says which case applies.
 */
export function getDuplicateResolution(item, matchIds, itemsById) {
  for (const id of matchIds || []) {
    const sibling = itemsById?.get?.(id) || itemsById?.[id];
    const scholarshipId = sibling?.accepted_scholarship_id;
    if (scholarshipId) return { kind: 'scholarship', scholarshipId, siblingId: id };
  }
  return { kind: 'needs_scholarship', approveFirstIds: [...(matchIds || [])] };
}

// --- editing a candidate before approval ----------------------------------

/**
 * The fields an admin may correct before approving, in panel order. Every
 * other extracted value is published unchanged.
 */
export const EDITABLE_CANDIDATE_FIELDS = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'country', label: 'Country', type: 'text' },
  { field: 'degree_level', label: 'Degree level', type: 'text' },
  { field: 'application_deadline_date', label: 'Deadline date', type: 'date' },
  { field: 'funding_type', label: 'Award / funding', type: 'text' },
  { field: 'eligible_fields', label: 'Eligibility summary', type: 'text' },
  { field: 'official_url', label: 'Official URL', type: 'url' },
];

function draftValue(value) {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'object') return '';
  return String(value);
}

/** The editable fields of a candidate as plain strings. */
export function buildEditableCandidateDraft(item) {
  const values = item?.extracted_values || {};
  const draft = {};
  for (const { field } of EDITABLE_CANDIDATE_FIELDS) {
    draft[field] = draftValue(values[field]);
  }
  return draft;
}

const LIST_VALUED_FIELDS = new Set(['eligible_fields']);

/**
 * The extracted values with the admin's edits applied.
 *
 * A field the admin cleared is removed rather than published as an empty
 * string, and a field they did not touch keeps its original value and type.
 */
export function applyCandidateDraft(item, draft) {
  const values = { ...(item?.extracted_values || {}) };
  const original = buildEditableCandidateDraft(item);
  for (const { field } of EDITABLE_CANDIDATE_FIELDS) {
    const next = draft?.[field];
    if (next === undefined || next === original[field]) continue;
    const trimmed = typeof next === 'string' ? next.trim() : next;
    if (trimmed === '') {
      delete values[field];
      continue;
    }
    if (LIST_VALUED_FIELDS.has(field) && Array.isArray(item?.extracted_values?.[field])) {
      values[field] = String(trimmed).split(',').map((part) => part.trim()).filter(Boolean);
      continue;
    }
    values[field] = trimmed;
  }
  return values;
}

/** Whether the admin changed anything in the editable fields. */
export function hasCandidateEdits(item, draft) {
  const original = buildEditableCandidateDraft(item);
  return EDITABLE_CANDIDATE_FIELDS.some(({ field }) => {
    const next = draft?.[field];
    return next !== undefined && next !== original[field];
  });
}

// --- resolving candidates --------------------------------------------------

export const UNRESOLVED_REVIEW_STATUSES = new Set(['pending', 'reviewed']);

export function isResolvableReviewItem(item) {
  return UNRESOLVED_REVIEW_STATUSES.has(item?.review_status);
}

/** Approve/Reject are offered whenever at least one candidate is selected. */
export function canResolveSelection(items) {
  return (items || []).length > 0;
}

/**
 * The calls one candidate needs for a decision.
 *
 * The backend refuses to resolve a candidate that has not been marked
 * reviewed ("Mark the discovery reviewed before resolving it", HTTP 409), so a
 * pending candidate is marked reviewed first and then resolved. Clicking
 * Approve or Reject IS the deliberate review, and both steps are recorded.
 *
 * `draft` carries the admin's edits to the editable fields; approval publishes
 * the edited values, and rejection never sends values at all.
 */
export function buildBulkDecisionSteps(item, decision, { note, draft } = {}) {
  if (decision !== 'accepted' && decision !== 'rejected') {
    throw new Error(`Unsupported bulk discovery decision: ${decision}`);
  }
  if (!isResolvableReviewItem(item)) {
    throw new Error(`Candidate ${item?.id} is already ${item?.review_status}.`);
  }
  const trimmedNote = typeof note === 'string' && note.trim() ? note.trim() : undefined;
  const steps = [];
  if (item.review_status === 'pending') {
    steps.push({ decision: 'reviewed', ...(trimmedNote ? { note: trimmedNote } : {}) });
  }
  const final = { decision };
  if (decision === 'accepted') {
    final.values = draft
      ? applyCandidateDraft(item, draft)
      : (item.extracted_values || {});
  }
  if (trimmedNote) final.note = trimmedNote;
  steps.push(final);
  return steps;
}

// --- every populated field, grouped -------------------------------------

/**
 * The groups the panel shows all remaining extracted fields in.
 *
 * The panel used to show 7 editable fields and 6 read-only rows, so a
 * candidate carrying 38 values displayed about 13 of them and the rest were
 * visible only inside the provenance JSON. These are the same groups the
 * Duplicates compare panel uses, so the two read alike.
 */
export const EXTRACTED_FIELD_GROUPS = [
  {
    label: 'Basics',
    fields: ['name', 'provider', 'country', 'host_institution', 'host_city',
      'degree_level', 'study_type', 'institution_scope', 'source_name'],
  },
  {
    label: 'Eligibility',
    fields: ['eligible_nationalities', 'nationality_scope', 'eligible_countries',
      'excluded_countries', 'eligible_regions', 'excluded_regions', 'pakistan_eligible',
      'eligible_fields', 'discipline_scope', 'eligible_disciplines',
      'eligible_degree_levels', 'required_previous_degree', 'bachelors_requirement',
      'min_academic_requirement', 'academic_condition', 'min_gpa', 'min_gpa_scale',
      'min_percentage', 'english_requirement', 'english_requirement_type',
      'accepted_english_tests', 'min_ielts', 'min_toefl', 'min_duolingo',
      'age_requirement', 'min_age', 'max_age', 'gender_restriction',
      'applicant_restrictions', 'residency_requirement', 'work_experience'],
  },
  {
    label: 'Funding',
    fields: ['funding_type', 'funding_level', 'tuition_coverage', 'tuition_coverage_type',
      'tuition_percent_min', 'tuition_percent_max', 'tuition_amount', 'tuition_amount_max',
      'tuition_currency', 'tuition_period', 'living_stipend', 'stipend_status',
      'stipend_amount', 'stipend_amount_max', 'stipend_currency', 'stipend_period',
      'stipend_is_approximate', 'accommodation', 'accommodation_status',
      'health_insurance', 'health_insurance_status', 'travel_airfare', 'travel_status',
      'travel_amount', 'travel_currency', 'other_benefits', 'costs_not_covered',
      'funding_duration_months', 'duration'],
  },
  {
    label: 'Deadlines',
    fields: ['deadline', 'deadline_type', 'application_open_date',
      'application_deadline_date', 'application_cycle'],
  },
  {
    label: 'Application',
    fields: ['application_method', 'application_channel', 'application_pathway',
      'admission_required', 'nomination_required', 'required_documents',
      'required_documents_list', 'notes'],
  },
  {
    label: 'Links',
    fields: ['official_url', 'official_info_url', 'official_application_url',
      'additional_source_urls'],
  },
];

function hasValue(value) {
  if (value === null || value === undefined || value === '') return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'string') return value.trim() !== '';
  return true;
}

/** A stored value as one readable string. */
export function formatExtractedValue(value) {
  if (!hasValue(value)) return '';
  if (Array.isArray(value)) return value.map((item) => formatExtractedValue(item)).join(', ');
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/**
 * Every populated extracted field, grouped, with its quote where there is one.
 *
 * `skip` holds the fields already shown as editable inputs, so nothing is
 * listed twice. A field the groups do not mention still appears, under
 * "Other", so a new schema field can never go invisible.
 */
export function getExtractedFieldGroups(item, { skip = [] } = {}) {
  const values = item?.extracted_values && typeof item.extracted_values === 'object'
    ? item.extracted_values
    : {};
  const quotes = getFieldQuotes(item);
  const skipped = new Set(skip);
  const grouped = [];
  const placed = new Set();

  const row = (field) => {
    const quote = quotes.get(field) || null;
    return {
      field,
      label: describeField(field),
      value: formatExtractedValue(values[field]),
      quote: quote ? quote.quote : '',
      quoteKind: quote ? quote.kind : '',
    };
  };

  for (const group of EXTRACTED_FIELD_GROUPS) {
    const rows = [];
    for (const field of group.fields) {
      placed.add(field);
      if (skipped.has(field) || !hasValue(values[field])) continue;
      rows.push(row(field));
    }
    if (rows.length) grouped.push({ label: group.label, rows });
  }

  const others = Object.keys(values)
    .filter((field) => !placed.has(field) && !skipped.has(field) && hasValue(values[field]))
    .sort()
    .map(row);
  if (others.length) grouped.push({ label: 'Other', rows: others });
  return grouped;
}

/** How many populated fields the panel is showing, for the section label. */
export function countExtractedFields(groups) {
  return (groups || []).reduce((total, group) => total + group.rows.length, 0);
}
