import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  compareByRank, getCategoryTone, getCoverageNote, getEligibilityReason, getExclusionLabel, getMatchTone, getScholarshipDeadlineLabel,
} from './eligibilityBadges.js';
import { getSelectedProgramId, mapScholarshipEligibilityToFrontend, selectRelevantMatches } from './opportunityApi.js';

test('only confirmed-eligible categories look positive', () => {
  assert.equal(getCategoryTone('strong'), 'success');
  assert.equal(getCategoryTone('possible'), 'warning');
  assert.equal(getCategoryTone('needs_verification'), 'neutral');
  assert.equal(getCategoryTone(undefined), 'neutral');
});

test('ranked items come first and unranked ones keep their place', () => {
  const items = [{ id: 'program' }, { id: 'b', rank: 2 }, { id: 'a', rank: 1 }];
  assert.deepEqual([...items].sort(compareByRank).map((item) => item.id), ['a', 'b', 'program']);
});

test('exclusions are named plainly', () => {
  assert.equal(getExclusionLabel({ exclusions: [{ rule: 'not_eligible' }, { rule: 'closed' }] }), 'Not eligible · Applications closed');
  assert.equal(getExclusionLabel(null), '');
});

test('only a backend program counts as the selected program', () => {
  assert.equal(getSelectedProgramId('11'), 11);
  assert.equal(getSelectedProgramId('sch-db-11'), null);
  assert.equal(getSelectedProgramId(''), null);
  assert.equal(getSelectedProgramId(null), null);
});

test('My Matches states that a score is not a probability', () => {
  const source = readFileSync(new URL('../pages/Recommendations.jsx', import.meta.url), 'utf8');
  assert.ok(source.includes("aren't your chance of winning"));
  assert.ok(!source.includes('illustrative sample data'));
});

test('each relationship outcome looks different', () => {
  const tones = ['confirmed', 'potential', 'not_a_match', 'needs_verification'].map(getMatchTone);
  assert.equal(new Set(tones).size, 4);
  assert.equal(getMatchTone('something_else'), 'neutral');
});

test('the listing note never presents a potential match as confirmed', () => {
  assert.equal(getCoverageNote({ confirmed: 2, potential: 1, needs_verification: 0 }), 'Confirmed for 2 programs');
  assert.equal(getCoverageNote({ confirmed: 0, potential: 1, needs_verification: 3 }), 'Possible for 1 program');
  assert.equal(getCoverageNote({ confirmed: 0, potential: 0, needs_verification: 3 }), null);
  assert.equal(getCoverageNote(undefined), null);
});

test('details pages leave out pairs split only by host country', () => {
  const kept = selectRelevantMatches([
    { outcome: 'not_a_match', blocking_criterion: 'country' },
    { outcome: 'not_a_match', blocking_criterion: 'university' },
    { outcome: 'needs_verification', blocking_criterion: null },
  ]);
  assert.equal(kept.length, 2);
  assert.deepEqual(selectRelevantMatches(undefined), []);
});

test('each deadline state has its own label', () => {
  assert.deepEqual(getScholarshipDeadlineLabel({ status: 'open', date: '2026-12-08', days_left: 38 }), { label: 'Dec 8, 2026', note: '38 days left' });
  assert.equal(getScholarshipDeadlineLabel({ status: 'closed', date: '2026-02-20' }).note, 'Closed · check next cycle');
  assert.deepEqual(getScholarshipDeadlineLabel({ status: 'upcoming', date: '2027-02-01', opens_on: '2026-11-10', days_left: 10 }), { label: 'Opens Nov 10, 2026', note: 'Opens in 10 days' });
  assert.equal(getScholarshipDeadlineLabel({ status: 'rolling' }).label, 'Rolling');
  assert.equal(getScholarshipDeadlineLabel({ status: 'no_separate_deadline' }).label, 'No separate deadline');
  assert.equal(getScholarshipDeadlineLabel({ status: 'unknown', text: 'Varies' }), null);
});

test('backend outcome, conflict and deadline reach the page unchanged', () => {
  const evaluation = mapScholarshipEligibilityToFrontend({
    status: 'not_evaluated',
    outcome: 'verify_manually',
    summary: 'Check it',
    needs_verification: [{ requirement: 'age', label: 'Age', status: 'not_evaluated', reason: 'Disagree', source_text: 'Up to 25', scope: 'scholarship', conflict: true }],
    deadline: { status: 'upcoming', message: "Applications haven't opened yet." },
  });
  assert.equal(evaluation.status, 'awaiting-verification');
  assert.equal(evaluation.outcome, 'verify_manually');
  assert.equal(evaluation.requirements[0].conflict, true);
  assert.equal(evaluation.deadline.status, 'upcoming');
});

test('missing information is never described as met', () => {
  const evaluation = mapScholarshipEligibilityToFrontend({
    status: 'missing_information',
    missing_information: [{ requirement: 'english', label: 'English language', status: 'missing_information', reason: 'Add a score', scope: 'scholarship' }],
  });
  assert.equal(evaluation.status, 'missing-information');
  assert.equal(getEligibilityReason(evaluation), 'Add to profile: english language');
});

test('Compare has no eligibility rules of its own', () => {
  const source = readFileSync(new URL('../pages/Compare.jsx', import.meta.url), 'utf8');
  assert.ok(!source.includes('evaluateOpportunityEligibility'));
  assert.ok(source.includes('useScholarshipEligibilities'));
});
