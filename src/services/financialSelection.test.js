import test from 'node:test';
import assert from 'node:assert/strict';
import { buildFinancialRouteState, resolveFinancialSelection } from './financialSelection.js';

const program = { id: '7', _numericId: 7, kind: 'program' };
const scholarship = { id: 'sch-db-4', _numericId: 4, kind: 'scholarship' };

test('financial route state carries only a valid scholarship ID', () => {
  assert.deepEqual(buildFinancialRouteState({ programId: '7', scholarshipId: 4 }), { scholarshipId: 4 });
  assert.deepEqual(buildFinancialRouteState({ programId: '7', scholarshipId: 0 }), { scholarshipId: null });
  assert.deepEqual(buildFinancialRouteState(), { scholarshipId: null });
});

test('explicit route scholarship selection wins over saved selections', () => {
  const result = resolveFinancialSelection({
    routeState: buildFinancialRouteState({ scholarshipId: 4 }),
    activeOpportunity: { ...scholarship, id: 'sch-db-9' },
    selectedOpportunities: [scholarship],
  });
  assert.equal(result.scholarshipId, 4);
});

test('legacy program-only route state does not create a feasibility selection', () => {
  assert.deepEqual(resolveFinancialSelection({
    routeState: { programId: 7 },
    activeOpportunity: program,
    selectedOpportunities: [program],
  }), { scholarshipId: null });
});

test('sidebar selection uses the active or saved scholarship only', () => {
  assert.equal(resolveFinancialSelection({
    routeState: null,
    activeOpportunity: scholarship,
    selectedOpportunities: [program],
  }).scholarshipId, 4);
  assert.equal(resolveFinancialSelection({
    routeState: null,
    activeOpportunity: program,
    selectedOpportunities: [program, scholarship],
  }).scholarshipId, 4);
});

test('invalid and legacy IDs are ignored', () => {
  assert.equal(resolveFinancialSelection({ routeState: { scholarshipId: 'sch-1' } }).scholarshipId, null);
  assert.equal(resolveFinancialSelection({ routeState: { scholarshipId: 0 } }).scholarshipId, null);
  assert.equal(resolveFinancialSelection({ routeState: null, activeOpportunity: program }).scholarshipId, null);
});
