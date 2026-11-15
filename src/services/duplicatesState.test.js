import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildComparisonRows,
  buildComparisonView,
  countComparisonDifferences,
  describeResolveAction,
  DUPLICATE_STATUS_LABELS,
  filterDuplicatePairs,
  getDuplicateCounts,
  getDuplicateFilterOptions,
  getDuplicateStatusLabel,
  getPairKey,
  getPairMetaLine,
  getPairRowLabel,
  getPairSimilarity,
  getRecordDomain,
  getResolveActions,
  getResolveAnnouncement,
  humanizeComparisonValue,
  isSamePair,
  normalizeComparisonValue,
  shouldShowSimilarityColumn,
} from './duplicatesState.js';
import { humanizeEnum } from './textFormat.js';

function record(id, overrides = {}) {
  return {
    id,
    name: `Award ${id}`,
    provider: 'DAAD',
    country: 'Germany',
    degree_level: 'Master',
    source_url: 'https://www.daad.de/en/award/',
    verification_status: 'verified',
    archived: false,
    duplicate_of_id: null,
    ...overrides,
  };
}

function pair(overrides = {}) {
  const first = overrides.first || record(1);
  const second = overrides.second || record(2);
  return {
    first_id: first.id,
    second_id: second.id,
    first_name: first.name,
    second_name: second.name,
    kind: 'suspected',
    status: 'needs_review',
    duplicate_id: null,
    similarity: 0.86,
    same_country: true,
    same_provider: true,
    ...overrides,
    first,
    second,
  };
}

// --- filtering ------------------------------------------------------------

test('the default view shows only pairs that still need a decision', () => {
  const pairs = [
    pair({ status: 'needs_review' }),
    pair({ first: record(3), second: record(4), status: 'flagged' }),
    pair({ first: record(5), second: record(6), status: 'resolved' }),
    pair({ first: record(7), second: record(8), status: 'dismissed' }),
  ];
  const shown = filterDuplicatePairs(pairs);
  assert.deepEqual(shown.map((item) => item.status), ['needs_review', 'flagged']);
});

test('a dismissed pair is hidden from the default view but has its own filter', () => {
  const pairs = [pair({ status: 'dismissed' })];
  assert.equal(filterDuplicatePairs(pairs).length, 0);
  assert.equal(filterDuplicatePairs(pairs, { filter: 'dismissed' }).length, 1);
  assert.equal(filterDuplicatePairs(pairs, { filter: 'all' }).length, 1);
});

test('each status filter shows only that status', () => {
  const pairs = [
    pair({ status: 'needs_review' }),
    pair({ first: record(3), second: record(4), status: 'flagged' }),
    pair({ first: record(5), second: record(6), status: 'resolved' }),
  ];
  for (const status of ['needs_review', 'flagged', 'resolved']) {
    const shown = filterDuplicatePairs(pairs, { filter: status });
    assert.deepEqual(shown.map((item) => item.status), [status], status);
  }
});

test('search matches either name, country or provider', () => {
  const pairs = [
    pair(),
    pair({
      first: record(3, { name: 'Chevening', country: 'United Kingdom', provider: 'FCDO' }),
      second: record(4, { name: 'Chevening Award', country: 'United Kingdom', provider: 'FCDO' }),
    }),
  ];
  assert.equal(filterDuplicatePairs(pairs, { search: 'chevening' }).length, 1);
  assert.equal(filterDuplicatePairs(pairs, { search: 'FCDO' }).length, 1);
  assert.equal(filterDuplicatePairs(pairs, { search: 'germany' }).length, 1);
  assert.equal(filterDuplicatePairs(pairs, { search: '   ' }).length, 2);
  assert.equal(filterDuplicatePairs(pairs, { search: 'nothing here' }).length, 0);
});

test('a pair with no status is treated as needing review', () => {
  const shown = filterDuplicatePairs([{ first_id: 1, second_id: 2 }]);
  assert.equal(shown.length, 1);
});

test('counts drive the summary cards', () => {
  const counts = getDuplicateCounts([
    pair({ status: 'needs_review' }),
    pair({ status: 'needs_review' }),
    pair({ status: 'flagged' }),
    pair({ status: 'resolved' }),
    pair({ status: 'dismissed' }),
  ]);
  assert.equal(counts.needs_review, 2);
  assert.equal(counts.flagged, 1);
  assert.equal(counts.resolved, 1);
  assert.equal(counts.dismissed, 1);
  assert.equal(counts.undecided, 3);
  assert.equal(counts.total, 5);
});

test('counts of nothing are zero, not undefined', () => {
  const counts = getDuplicateCounts(null);
  assert.equal(counts.total, 0);
  assert.equal(counts.undecided, 0);
});

// --- identity -------------------------------------------------------------

test('a pair key does not depend on which record came first', () => {
  assert.equal(getPairKey({ first_id: 7, second_id: 3 }), '3-7');
  assert.equal(getPairKey({ first_id: 3, second_id: 7 }), '3-7');
  assert.ok(isSamePair({ first_id: 3, second_id: 7 }, { first_id: 7, second_id: 3 }));
  assert.equal(isSamePair({ first_id: 3, second_id: 7 }, { first_id: 3, second_id: 8 }), false);
  assert.equal(isSamePair(null, { first_id: 1, second_id: 2 }), false);
});

// --- scoring --------------------------------------------------------------

test('similarity replaces "Not scored" with a percentage and chips', () => {
  const score = getPairSimilarity(pair());
  assert.equal(score.shown, true);
  assert.equal(score.percent, 86);
  assert.equal(score.text, '86% name match');
  assert.deepEqual(score.chips, ['same country', 'same provider']);
});

test('chips only claim what the pair reports', () => {
  const score = getPairSimilarity(pair({ same_country: true, same_provider: false }));
  assert.deepEqual(score.chips, ['same country']);
});

test('an unscoreable pair hides the column instead of showing zero', () => {
  for (const similarity of [0, null, undefined, NaN, 'high']) {
    const score = getPairSimilarity(pair({ similarity }));
    assert.equal(score.shown, false, String(similarity));
    assert.equal(score.percent, null);
  }
  assert.equal(shouldShowSimilarityColumn([pair({ similarity: 0 })]), false);
  assert.equal(shouldShowSimilarityColumn([pair({ similarity: 0 }), pair()]), true);
  assert.equal(shouldShowSimilarityColumn([]), false);
});

test('the source domain is shown, not the whole URL', () => {
  assert.equal(getRecordDomain(record(1)), 'daad.de');
  assert.equal(getRecordDomain({ source_url: 'https://www.study.cam.ac.uk/funding' }), 'cam.ac.uk');
  assert.equal(getRecordDomain({ source_url: 'not a url' }), '');
  assert.equal(getRecordDomain({}), '');
  assert.equal(getRecordDomain(null), '');
});

// --- the comparison table -------------------------------------------------

test('values are compared as text, so a list and a string can be told apart', () => {
  assert.equal(normalizeComparisonValue(null), '');
  assert.equal(normalizeComparisonValue(''), '');
  assert.equal(normalizeComparisonValue(['a', 'b']), 'a, b');
  assert.equal(normalizeComparisonValue(' spaced '), 'spaced');
  assert.equal(normalizeComparisonValue(4.5), '4.5');
});

test('the comparison is grouped, with differing rows marked', () => {
  const groups = buildComparisonRows(
    record(1, { name: 'Alpha', funding_type: 'Full' }),
    record(2, { name: 'Alpha Award', funding_type: 'Full' }),
  );
  // The list payload carries source_url; official_info_url only arrives with
  // the full comparison, so the Links group is empty for these two.
  const labels = groups.map((group) => group.label);
  assert.deepEqual(labels, ['Basics', 'Funding']);
  const basics = groups[0].rows;
  assert.equal(basics.find((row) => row.key === 'name').differs, true);
  assert.equal(basics.find((row) => row.key === 'country').differs, false);
  assert.equal(groups[1].rows.find((row) => row.key === 'funding_type').differs, false);
});

test('a field empty on both sides is left out entirely', () => {
  const groups = buildComparisonRows(record(1), record(2));
  const keys = groups.flatMap((group) => group.rows.map((row) => row.key));
  assert.equal(keys.includes('min_gpa'), false);
  assert.equal(keys.includes('age_requirement'), false);
});

test('"show only differences" drops the identical rows', () => {
  const first = record(1, { name: 'Alpha' });
  const second = record(2, { name: 'Alpha Award' });
  const all = buildComparisonRows(first, second);
  const onlyDiffs = buildComparisonRows(first, second, { onlyDifferences: true });
  const rowCount = (groups) => groups.reduce((total, group) => total + group.rows.length, 0);
  assert.ok(rowCount(onlyDiffs) < rowCount(all));
  assert.ok(onlyDiffs.every((group) => group.rows.every((row) => row.differs)));
  assert.equal(countComparisonDifferences(first, second), rowCount(onlyDiffs));
});

test('a stipend is compared with its currency, not as a bare number', () => {
  const groups = buildComparisonRows(
    record(1, { stipend_amount: 934, stipend_currency: 'EUR' }),
    record(2, { stipend_amount: 934, stipend_currency: 'USD' }),
  );
  const stipend = groups.flatMap((group) => group.rows).find((row) => row.key === 'stipend');
  assert.equal(stipend.first, '934 EUR');
  assert.equal(stipend.differs, true);
});

test('the information URL falls back to the legacy field', () => {
  const groups = buildComparisonRows(
    record(1, { source_url: null, official_info_url: null, official_url: 'https://a.example/x' }),
    record(2, { source_url: null, official_info_url: 'https://a.example/x' }),
  );
  const link = groups.flatMap((group) => group.rows).find((row) => row.key === 'official_info_url');
  assert.equal(link.differs, false);
  assert.equal(link.isLink, true);
});

// --- resolve actions ------------------------------------------------------

test('a pair needing review offers dismiss and both directions', () => {
  const actions = getResolveActions(pair());
  assert.deepEqual(actions.map((action) => action.key), ['dismiss', 'mark_second', 'mark_first']);
  const markSecond = actions[1];
  assert.equal(markSecond.recordId, 2);
  assert.equal(markSecond.targetId, 1);
});

test('a record already pointing elsewhere is not offered as a duplicate', () => {
  const actions = getResolveActions(pair({
    second: record(2, { duplicate_of_id: 99 }),
  }));
  assert.equal(actions.some((action) => action.key === 'mark_second'), false);
  assert.equal(actions.some((action) => action.key === 'mark_first'), true);
});

test('a flagged pair offers archiving the duplicate and clearing the flag', () => {
  const actions = getResolveActions(pair({
    status: 'flagged',
    duplicate_id: 2,
    second: record(2, { duplicate_of_id: 1 }),
  }));
  const keys = actions.map((action) => action.key);
  assert.equal(keys.includes('dismiss'), false, 'a decided pair is not dismissed');
  assert.equal(keys.includes('archive'), true);
  assert.equal(keys.includes('clear'), true);
  assert.equal(actions.find((action) => action.key === 'archive').recordId, 2);
  assert.equal(actions.find((action) => action.key === 'clear').targetId, null);
});

test('an already archived duplicate is not offered for archiving again', () => {
  const actions = getResolveActions(pair({
    status: 'resolved',
    duplicate_id: 2,
    second: record(2, { duplicate_of_id: 1, archived: true }),
  }));
  assert.equal(actions.some((action) => action.key === 'archive'), false);
  assert.equal(actions.some((action) => action.key === 'clear'), true);
});

test('a pair with no records still offers actions from its ids', () => {
  const actions = getResolveActions({
    first_id: 4, second_id: 9, first_name: 'A', second_name: 'B', status: 'needs_review',
  });
  assert.equal(actions.find((action) => action.key === 'mark_second').recordId, 9);
});

test('no pair means no actions', () => {
  assert.deepEqual(getResolveActions(null), []);
});

test('every action explains itself before it is confirmed', () => {
  const current = pair();
  for (const action of getResolveActions(current)) {
    const description = describeResolveAction(action, current);
    assert.ok(description.title.length > 0, action.key);
    assert.ok(description.body.length > 20, action.key);
    assert.ok(description.confirmLabel.length > 0, action.key);
  }
});

test('marking a duplicate says what happens to students', () => {
  const current = pair();
  const action = getResolveActions(current).find((item) => item.key === 'mark_second');
  const described = describeResolveAction(action, current);
  assert.match(described.body, /no longer be shown to students/);
  assert.match(described.body, /nothing is merged/i);
});

test('dismissing says neither record changes', () => {
  const current = pair();
  const action = getResolveActions(current).find((item) => item.key === 'dismiss');
  assert.match(describeResolveAction(action, current).body, /Neither record changes/);
});

test('each action has its own success message', () => {
  assert.match(getResolveAnnouncement({ key: 'dismiss' }), /not be suggested again/);
  assert.match(
    getResolveAnnouncement({ key: 'mark_second', recordId: 2, targetId: 1 }),
    /#2 is now a duplicate of #1/,
  );
  assert.match(getResolveAnnouncement({ key: 'archive', recordId: 2 }), /archived/);
  assert.match(getResolveAnnouncement({ key: 'clear', recordId: 2 }), /cleared/);
});

// --- status names ---------------------------------------------------------

test('one set of status names is used everywhere', () => {
  assert.deepEqual(Object.values(DUPLICATE_STATUS_LABELS), [
    'Needs review', 'Flagged', 'Resolved', 'Dismissed',
  ]);
  assert.equal(getDuplicateStatusLabel('resolved'), 'Resolved');
  assert.equal(getDuplicateStatusLabel(undefined), 'Needs review');
});

// --- the simplified list row ----------------------------------------------

test('a pair whose names only differ in wording shows the name once', () => {
  const label = getPairRowLabel({
    first_id: 2,
    second_id: 17,
    first_name: 'Helmut-Schmidt-Programm',
    second_name: 'Helmut Schmidt Programme',
  });
  assert.equal(label.showBoth, false);
  assert.equal(label.name, 'Helmut-Schmidt-Programm');
});

test('genuinely different names are both shown', () => {
  const label = getPairRowLabel({
    first_id: 3, second_id: 4, first_name: 'Alpha Award', second_name: 'Beta Grant',
  });
  assert.equal(label.showBoth, true);
  assert.equal(label.name, 'Alpha Award');
  assert.equal(label.otherName, 'Beta Grant');
});

test('a missing name does not produce a lopsided row', () => {
  assert.equal(getPairRowLabel({ first_name: 'Alpha', second_name: '' }).showBoth, false);
  assert.equal(getPairRowLabel({ first_name: '', second_name: '' }).name, 'Unnamed record');
  assert.equal(getPairRowLabel(null).name, 'Unnamed record');
});

test('the row meta line is ids, score and what the records share', () => {
  assert.equal(
    getPairMetaLine({
      first_id: 2, second_id: 17, similarity: 0.96, same_provider: true, same_country: true,
    }),
    '#2 ↔ #17 · 96% match · same provider · same country',
  );
});

test('the meta line claims nothing it cannot back', () => {
  assert.equal(
    getPairMetaLine({ first_id: 3, second_id: 4, similarity: 0, same_provider: false, same_country: false }),
    '#3 ↔ #4',
  );
  assert.equal(
    getPairMetaLine({ first_id: 3, second_id: 4, similarity: 0.8, same_country: true }),
    '#3 ↔ #4 · 80% match · same country',
  );
});

// --- filters with counts ---------------------------------------------------

test('the filters are one line of four, each with its count', () => {
  const options = getDuplicateFilterOptions(getDuplicateCounts([
    pair({ status: 'needs_review' }),
    pair({ first: record(3), second: record(4), status: 'flagged' }),
    pair({ first: record(5), second: record(6), status: 'resolved' }),
    pair({ first: record(7), second: record(8), status: 'dismissed' }),
  ]));
  assert.deepEqual(options.map((option) => [option.label, option.count]), [
    ['Needs a decision', 2],
    ['Resolved', 1],
    ['Dismissed', 1],
    ['All', 4],
  ]);
});

test('filter counts with no pairs are zero, not undefined', () => {
  for (const option of getDuplicateFilterOptions(getDuplicateCounts([]))) {
    assert.equal(option.count, 0, option.label);
  }
  for (const option of getDuplicateFilterOptions(undefined)) {
    assert.equal(option.count, 0, option.label);
  }
});

// --- humanized values ------------------------------------------------------

test('stored enums are shown as a reader would write them', () => {
  assert.equal(humanizeComparisonValue('full'), 'Full');
  assert.equal(humanizeComparisonValue('varies_by_institution'), 'Varies by institution');
  assert.equal(humanizeComparisonValue('masters, phd'), 'Masters, Phd');
});

test('prose, names and URLs are left exactly as stored', () => {
  for (const value of [
    'Open to all nationalities',
    'https://www.daad.de/en/award/',
    'Germany',
    '934 EUR',
    '2027-07-31',
    'DAAD',
  ]) {
    assert.equal(humanizeComparisonValue(value), value, value);
  }
  assert.equal(humanizeComparisonValue(''), '');
  assert.equal(humanizeComparisonValue(null), null);
});

test('humanizing is display only and cannot hide a difference', () => {
  const groups = buildComparisonRows(
    record(1, { funding_type: 'full' }),
    record(2, { funding_type: 'partial' }),
  );
  const row = groups.flatMap((group) => group.rows).find((item) => item.key === 'funding_type');
  assert.equal(row.differs, true);
  assert.equal(row.first, 'full');
  assert.equal(row.firstDisplay, 'Full');
  assert.equal(row.secondDisplay, 'Partial');
});

// --- the comparison view ---------------------------------------------------

test('the view shows differences and counts the hidden identical fields', () => {
  const view = buildComparisonView(
    record(1, { name: 'Alpha' }),
    record(2, { name: 'Alpha Award' }),
  );
  assert.equal(view.differenceCount, 1);
  assert.ok(view.hiddenCount > 0);
  assert.equal(view.hiddenCount + view.differenceCount, view.totalRows);
  assert.ok(view.groups.every((group) => group.rows.every((row) => row.differs)));
});

test('turning the toggle off shows every row and hides nothing', () => {
  const view = buildComparisonView(
    record(1, { name: 'Alpha' }),
    record(2, { name: 'Alpha Award' }),
    { onlyDifferences: false },
  );
  assert.equal(view.hiddenCount, 0);
  const shown = view.groups.reduce((total, group) => total + group.rows.length, 0);
  assert.equal(shown, view.totalRows);
});

test('each group reports its own difference count, which decides if it opens', () => {
  const view = buildComparisonView(
    record(1, { name: 'Alpha', funding_type: 'full' }),
    record(2, { name: 'Beta', funding_type: 'full' }),
    { onlyDifferences: false },
  );
  const basics = view.groups.find((group) => group.label === 'Basics');
  const funding = view.groups.find((group) => group.label === 'Funding');
  assert.ok(basics.differenceCount > 0, 'Basics differs, so it opens');
  assert.equal(funding.differenceCount, 0, 'Funding matches, so it stays closed');
});

test('two identical records leave no groups and nothing to decide between', () => {
  const view = buildComparisonView(record(1), record(1));
  assert.equal(view.differenceCount, 0);
  assert.deepEqual(view.groups, []);
  assert.equal(view.hiddenCount, view.totalRows);
});

test('an empty group is dropped rather than rendered as a heading', () => {
  const view = buildComparisonView(record(1), record(2), { onlyDifferences: true });
  assert.ok(view.groups.every((group) => group.rows.length > 0));
});

// --- case and whitespace are not differences ------------------------------

test('values differing only in case or spacing count as the same', () => {
  const groups = buildComparisonRows(
    record(1, { funding_type: 'Full', country: 'Germany  ' }),
    record(2, { funding_type: 'full', country: 'germany' }),
  );
  const rows = groups.flatMap((group) => group.rows);
  assert.equal(rows.find((row) => row.key === 'funding_type').differs, false);
  assert.equal(rows.find((row) => row.key === 'country').differs, false);
});

test('a real difference survives the folding', () => {
  const groups = buildComparisonRows(
    record(1, { funding_type: 'Full' }),
    record(2, { funding_type: 'partial' }),
  );
  const row = groups.flatMap((group) => group.rows).find((item) => item.key === 'funding_type');
  assert.equal(row.differs, true);
});

test('two records that differ only in case have nothing to decide', () => {
  const view = buildComparisonView(
    record(1, { name: 'Alpha Award' }),
    record(2, { name: 'alpha award' }),
  );
  assert.equal(view.differenceCount, 0);
  assert.deepEqual(view.groups, []);
});

test('the comparison formatter is the shared one', () => {
  assert.equal(humanizeComparisonValue, humanizeEnum);
});
