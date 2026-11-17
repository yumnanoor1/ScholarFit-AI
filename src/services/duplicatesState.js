import { humanizeEnum, isSameStoredValue } from './textFormat.js';

/**
 * The Duplicates page: filtering, scoring display, and field comparison.
 *
 * Status is derived by the backend from the records themselves
 * (services/scholarship_quality.duplicate_pairs), not stored on a pair:
 *   needs_review  a suspected pair nobody has decided on
 *   flagged       one record points at the other, both still listed
 *   resolved      the duplicate is also archived, so students cannot see it
 *   dismissed     ruled out by an administrator, never suggested again
 */

export const DUPLICATE_STATUS_LABELS = {
  needs_review: 'Needs review',
  flagged: 'Flagged',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
};

/** The statuses that still want a decision. This is the default view. */
export const UNDECIDED_DUPLICATE_STATUSES = new Set(['needs_review', 'flagged']);

/**
 * One line of filters, each with its own count.
 *
 * "Needs a decision" merges needs_review and flagged: both want the same
 * thing from an administrator, and splitting them made four filters where two
 * would do. The status badges still name all four states.
 */
export const DUPLICATE_FILTERS = [
  { value: 'undecided', label: 'Needs a decision', countKey: 'undecided' },
  { value: 'resolved', label: 'Resolved', countKey: 'resolved' },
  { value: 'dismissed', label: 'Dismissed', countKey: 'dismissed' },
  { value: 'all', label: 'All', countKey: 'total' },
];

/** The filters with their counts filled in, so no summary cards are needed. */
export function getDuplicateFilterOptions(counts) {
  return DUPLICATE_FILTERS.map((filter) => ({
    ...filter,
    count: counts?.[filter.countKey] ?? 0,
  }));
}

export function getDuplicateStatusLabel(status) {
  return DUPLICATE_STATUS_LABELS[status] || DUPLICATE_STATUS_LABELS.needs_review;
}

/** A stable key for a pair, whichever way round it arrived. */
export function getPairKey(pair) {
  const first = Number(pair?.first_id);
  const second = Number(pair?.second_id);
  return first <= second ? `${first}-${second}` : `${second}-${first}`;
}

export function isSamePair(first, second) {
  if (!first || !second) return false;
  return getPairKey(first) === getPairKey(second);
}

function pairText(pair) {
  return [
    pair?.first_name,
    pair?.second_name,
    pair?.first?.country,
    pair?.second?.country,
    pair?.first?.provider,
    pair?.second?.provider,
  ].filter(Boolean).join(' ').toLowerCase();
}

/**
 * The pairs a filter and search should show.
 *
 * "undecided" is the default: a dismissed pair is not suggested again, and a
 * resolved one needs nothing further, so neither belongs in the working view.
 */
export function filterDuplicatePairs(pairs, { filter = 'undecided', search = '' } = {}) {
  const query = search.trim().toLowerCase();
  return (pairs || []).filter((pair) => {
    const status = pair?.status || 'needs_review';
    const matchesFilter = filter === 'all'
      ? true
      : filter === 'undecided'
        ? UNDECIDED_DUPLICATE_STATUSES.has(status)
        : status === filter;
    return matchesFilter && (!query || pairText(pair).includes(query));
  });
}

/** How many pairs sit in each status, for the filter counts. */
export function getDuplicateCounts(pairs) {
  const counts = {
    needs_review: 0, flagged: 0, resolved: 0, dismissed: 0, undecided: 0, total: 0,
  };
  for (const pair of pairs || []) {
    const status = pair?.status || 'needs_review';
    if (status in counts) counts[status] += 1;
    if (UNDECIDED_DUPLICATE_STATUSES.has(status)) counts.undecided += 1;
    counts.total += 1;
  }
  return counts;
}

// --- what a row shows -----------------------------------------------------

/**
 * The similarity the page shows in place of "Not scored".
 *
 * The backend sends the word overlap its own pairing threshold uses. A pair
 * from before that field existed has no score, and `shown: false` tells the
 * page to hide the column rather than print a zero that means "unknown".
 */
export function getPairSimilarity(pair) {
  const raw = pair?.similarity;
  if (typeof raw !== 'number' || !Number.isFinite(raw) || raw <= 0) {
    return { shown: false, percent: null, text: '', chips: [] };
  }
  const percent = Math.round(Math.min(1, raw) * 100);
  const chips = [];
  if (pair.same_country) chips.push('same country');
  if (pair.same_provider) chips.push('same provider');
  return {
    shown: true,
    percent,
    text: `${percent}% name match`,
    chips,
  };
}

/** True when every pair lacks a score, so the column should not be rendered. */
export function shouldShowSimilarityColumn(pairs) {
  return (pairs || []).some((pair) => getPairSimilarity(pair).shown);
}

/**
 * The name a compact row shows.
 *
 * Both names are only worth the space when they differ in a way a reader
 * would notice. Case, punctuation and the filler words the pairing already
 * ignores do not count, so "Helmut-Schmidt-Programm" and "Helmut Schmidt
 * Programme" show once.
 */
export function getPairRowLabel(pair) {
  const first = (pair?.first_name || pair?.first?.name || '').trim();
  const second = (pair?.second_name || pair?.second?.name || '').trim();
  const fold = (name) => name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .split(' ')
    .filter((word) => word && !NAME_FILLER.has(word))
    .sort()
    .join(' ');
  if (!first || !second) return { name: first || second || 'Unnamed record', showBoth: false };
  if (fold(first) === fold(second)) return { name: first, showBoth: false };
  return { name: first, otherName: second, showBoth: true };
}

const NAME_FILLER = new Set([
  'the', 'a', 'an', 'of', 'for', 'and',
  'scholarship', 'scholarships', 'programme', 'programm', 'program', 'programmes',
  'master', 'masters', 's',
]);

/**
 * The muted second line of a row: "#2 ↔ #17 · 96% match · same provider".
 *
 * Only what is true is listed, so a pair with no score and nothing in common
 * still reads cleanly as just the two ids.
 */
export function getPairMetaLine(pair) {
  const parts = [`#${pair?.first_id} ↔ #${pair?.second_id}`];
  const similarity = getPairSimilarity(pair);
  if (similarity.shown) parts.push(`${similarity.percent}% match`);
  if (pair?.same_provider) parts.push('same provider');
  if (pair?.same_country) parts.push('same country');
  return parts.join(' · ');
}

/** The registrable domain of a record's source, e.g. daad.de. */
export function getRecordDomain(record) {
  const url = record?.source_url;
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
  const suffix = parts.slice(-2).join('.');
  const twoLabelSuffixes = new Set([
    'ac.uk', 'gov.uk', 'co.uk', 'org.uk',
    'edu.au', 'gov.au', 'ac.jp', 'gov.pk', 'edu.pk',
  ]);
  return twoLabelSuffixes.has(suffix) ? parts.slice(-3).join('.') : suffix;
}

// --- the comparison table -------------------------------------------------

/**
 * The fields compared, in groups. Each row reads one value from each record,
 * so a field that needs assembling (an amount plus its currency) does it here
 * rather than in the markup.
 */
export const COMPARISON_GROUPS = [
  {
    label: 'Basics',
    fields: [
      { key: 'name', label: 'Name' },
      { key: 'provider', label: 'Provider' },
      { key: 'country', label: 'Country' },
      { key: 'degree_level', label: 'Degree level' },
      { key: 'host_institution', label: 'Host institution' },
      { key: 'verification_status', label: 'Verification' },
    ],
  },
  {
    label: 'Eligibility',
    fields: [
      { key: 'eligible_nationalities', label: 'Nationalities' },
      { key: 'eligible_fields', label: 'Fields of study' },
      { key: 'eligible_degree_levels', label: 'Eligible degree levels' },
      { key: 'min_gpa', label: 'Minimum GPA' },
      { key: 'english_requirement', label: 'English requirement' },
      { key: 'age_requirement', label: 'Age requirement' },
    ],
  },
  {
    label: 'Funding',
    fields: [
      { key: 'funding_type', label: 'Funding type' },
      { key: 'funding_level', label: 'Funding level' },
      { key: 'tuition_coverage', label: 'Tuition coverage' },
      {
        key: 'stipend',
        label: 'Stipend',
        read: (record) => (record?.stipend_amount == null
          ? null
          : `${record.stipend_amount} ${record.stipend_currency || ''}`.trim()),
      },
      { key: 'other_benefits', label: 'Other benefits' },
    ],
  },
  {
    label: 'Deadlines',
    fields: [
      { key: 'deadline', label: 'Deadline (as written)' },
      { key: 'application_deadline_date', label: 'Deadline date' },
      { key: 'deadline_type', label: 'Deadline type' },
      { key: 'application_cycle', label: 'Application cycle' },
    ],
  },
  {
    label: 'Links',
    fields: [
      {
        key: 'official_info_url',
        label: 'Official information URL',
        read: (record) => record?.official_info_url || record?.official_url || null,
        isLink: true,
      },
      { key: 'official_application_url', label: 'Application URL', isLink: true },
      { key: 'source_name', label: 'Source name' },
    ],
  },
];

function readField(record, field) {
  if (!record) return null;
  return field.read ? field.read(record) : record[field.key];
}

/** A value as one comparable string; an empty value becomes ''. */
export function normalizeComparisonValue(value) {
  if (value === null || value === undefined || value === '') return '';
  if (Array.isArray(value)) return value.map(normalizeComparisonValue).filter(Boolean).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value).trim();
}

/**
 * A stored enum as a reader would write it. The one shared formatter, so the
 * comparison, the Review Queue panel and the Discovery cards agree.
 *
 * Display only: comparison uses the raw value, so humanizing can never turn a
 * difference into a match.
 */
export const humanizeComparisonValue = humanizeEnum;

/**
 * The comparison table: one row per field, grouped, each marked same or
 * different. A row where both sides are empty is dropped — two blanks are not
 * a difference worth a line.
 */
export function buildComparisonRows(first, second, { onlyDifferences = false } = {}) {
  const groups = [];
  for (const group of COMPARISON_GROUPS) {
    const rows = [];
    for (const field of group.fields) {
      const firstValue = normalizeComparisonValue(readField(first, field));
      const secondValue = normalizeComparisonValue(readField(second, field));
      if (!firstValue && !secondValue) continue;
      // Compared raw and folded, shown humanized: two spellings of the same
      // answer are not something an administrator should have to arbitrate.
      const differs = !isSameStoredValue(firstValue, secondValue);
      if (onlyDifferences && !differs) continue;
      rows.push({
        key: field.key,
        label: field.label,
        isLink: Boolean(field.isLink),
        first: firstValue,
        second: secondValue,
        firstDisplay: humanizeComparisonValue(firstValue),
        secondDisplay: humanizeComparisonValue(secondValue),
        differs,
      });
    }
    if (rows.length) groups.push({ label: group.label, rows });
  }
  return groups;
}

/**
 * The whole comparison the panel renders.
 *
 * Differences are shown by default and the identical rows collapse into one
 * line, so a pair that matches on everything but the name does not open as
 * thirty rows of the same text. Each group carries its own difference count,
 * which is what decides whether it starts open.
 */
export function buildComparisonView(first, second, { onlyDifferences = true } = {}) {
  const all = buildComparisonRows(first, second);
  const groups = all
    .map((group) => {
      const differenceCount = group.rows.filter((row) => row.differs).length;
      const rows = onlyDifferences ? group.rows.filter((row) => row.differs) : group.rows;
      return { label: group.label, rows, differenceCount, totalRows: group.rows.length };
    })
    .filter((group) => group.rows.length > 0);
  const totalRows = all.reduce((total, group) => total + group.rows.length, 0);
  const differenceCount = all
    .reduce((total, group) => total + group.rows.filter((row) => row.differs).length, 0);
  return {
    groups,
    differenceCount,
    identicalCount: totalRows - differenceCount,
    hiddenCount: onlyDifferences ? totalRows - differenceCount : 0,
    totalRows,
  };
}

/** How many compared fields differ, for the toggle's label. */
export function countComparisonDifferences(first, second) {
  return buildComparisonRows(first, second)
    .reduce((total, group) => total + group.rows.filter((row) => row.differs).length, 0);
}

// --- resolve actions ------------------------------------------------------

/**
 * The actions offered for a pair, in the order they appear.
 *
 * Which way round a duplicate may point is a backend rule: a record that is
 * already a duplicate of something else cannot become the main record, so
 * that direction is withheld rather than offered and refused.
 */
export function getResolveActions(pair) {
  if (!pair) return [];
  const first = pair.first || { id: pair.first_id, name: pair.first_name };
  const second = pair.second || { id: pair.second_id, name: pair.second_name };
  const status = pair.status || 'needs_review';
  const actions = [];

  if (status === 'needs_review') {
    actions.push({
      key: 'dismiss',
      label: 'Not a duplicate',
      tone: 'outline',
      title: 'Stops this pair being suggested. Neither record changes.',
    });
  }

  const pointsElsewhere = (record, otherId) => record?.duplicate_of_id != null
    && record.duplicate_of_id !== otherId;

  if (!pointsElsewhere(second, first.id) && second?.duplicate_of_id !== first.id) {
    actions.push({
      key: 'mark_second',
      label: `Mark #${second.id} as duplicate of #${first.id}`,
      tone: 'primary',
      recordId: second.id,
      targetId: first.id,
      title: `#${second.id} becomes hidden from students. Nothing is merged or deleted.`,
    });
  }
  if (!pointsElsewhere(first, second.id) && first?.duplicate_of_id !== second.id) {
    actions.push({
      key: 'mark_first',
      label: `Mark #${first.id} as duplicate of #${second.id}`,
      tone: 'outline',
      recordId: first.id,
      targetId: second.id,
      title: `#${first.id} becomes hidden from students. Nothing is merged or deleted.`,
    });
  }

  // Archiving only makes sense once a duplicate has been chosen, and only
  // while it is still listed.
  if (pair.duplicate_id) {
    const duplicate = pair.duplicate_id === first.id ? first : second;
    if (!duplicate?.archived) {
      actions.push({
        key: 'archive',
        label: `Archive #${pair.duplicate_id}`,
        tone: 'outline',
        recordId: pair.duplicate_id,
        title: 'Takes the duplicate out of every listing. It keeps its ID and references.',
      });
    }
  }

  if (status === 'flagged' || status === 'resolved') {
    const duplicateId = pair.duplicate_id ?? second.id;
    actions.push({
      key: 'clear',
      label: 'Keep both · clear the flag',
      tone: 'outline',
      recordId: duplicateId,
      targetId: null,
      title: `#${duplicateId} becomes visible to students again.`,
    });
  }
  return actions;
}

/** What the confirm modal says for one action. */
export function describeResolveAction(action, pair) {
  const first = pair?.first || { id: pair?.first_id, name: pair?.first_name };
  const second = pair?.second || { id: pair?.second_id, name: pair?.second_name };
  switch (action?.key) {
    case 'dismiss':
      return {
        title: 'Not a duplicate?',
        body: `#${first.id} and #${second.id} stop being suggested as a pair. Neither record changes, and nothing is merged or deleted.`,
        confirmLabel: 'Not a duplicate',
      };
    case 'mark_second':
    case 'mark_first': {
      const duplicate = action.recordId;
      const main = action.targetId;
      return {
        title: `Mark #${duplicate} as a duplicate?`,
        body: `#${duplicate} will point at #${main} and will no longer be shown to students. Both records are kept, nothing is merged, and the change is recorded in the history.`,
        confirmLabel: 'Mark duplicate',
      };
    }
    case 'archive':
      return {
        title: `Archive #${action.recordId}?`,
        body: `#${action.recordId} leaves every listing but keeps its ID and anything linked to it. It can be restored from the Records page.`,
        confirmLabel: 'Archive duplicate',
      };
    case 'clear':
      return {
        title: 'Clear the duplicate flag?',
        body: `#${action.recordId} stops being marked as a duplicate and becomes visible to students again.`,
        confirmLabel: 'Clear the flag',
      };
    default:
      return { title: 'Confirm', body: '', confirmLabel: 'Confirm' };
  }
}

/** The message shown after an action succeeds. */
export function getResolveAnnouncement(action) {
  switch (action?.key) {
    case 'dismiss':
      return 'Recorded as not a duplicate. The pair will not be suggested again, and neither record changed.';
    case 'mark_second':
    case 'mark_first':
      return `#${action.recordId} is now a duplicate of #${action.targetId} and is hidden from students. Nothing was merged.`;
    case 'archive':
      return `#${action.recordId} was archived. It keeps its ID and references.`;
    case 'clear':
      return `The duplicate flag on #${action.recordId} was cleared.`;
    default:
      return 'Done.';
  }
}
