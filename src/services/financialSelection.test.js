import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildFinancialRouteState,
  getBackendProgramId,
  resolveFinancialSelection,
} from './financialSelection.js';

const program = { id: '7', _numericId: 7, kind: 'program', university: 'TUM' };
const otherProgram = { id: '9', _numericId: 9, kind: 'program' };
const scholarship = { id: 'sch-db-4', _numericId: 4, kind: 'scholarship' };

test('route state carries the program and scholarship IDs as positive integers', () => {
  assert.deepEqual(buildFinancialRouteState({ programId: '7', scholarshipId: 4 }), { programId: 7, scholarshipId: 4, universityId: null });
  assert.deepEqual(buildFinancialRouteState({ programId: 'x', scholarshipId: 0 }), { programId: null, scholarshipId: null, universityId: null });
  assert.deepEqual(buildFinancialRouteState(), { programId: null, scholarshipId: null, universityId: null });
});

test('route state wins over the saved selection', () => {
  const result = resolveFinancialSelection({
    routeState: buildFinancialRouteState({ programId: 9, scholarshipId: 4 }),
    activeOpportunity: program,
    selectedOpportunities: [program, otherProgram, scholarship],
  });
  assert.equal(result.programId, 9);
  assert.equal(result.scholarshipId, 4);
  assert.equal(result.program, otherProgram);
});

test('a program click never inherits an earlier scholarship', () => {
  const result = resolveFinancialSelection({
    routeState: buildFinancialRouteState({ programId: 7 }),
    activeOpportunity: program,
    selectedOpportunities: [program, scholarship],
  });
  assert.equal(result.scholarshipId, null);
});

test('a program missing from the saved selection is reported so it can be fetched', () => {
  const result = resolveFinancialSelection({
    routeState: buildFinancialRouteState({ programId: 12, scholarshipId: 4 }),
    activeOpportunity: null,
    selectedOpportunities: [],
  });
  assert.equal(result.programId, 12);
  assert.equal(result.program, null);
});

test('opening from the sidebar uses the active program and any selected scholarship', () => {
  const result = resolveFinancialSelection({
    routeState: null,
    activeOpportunity: program,
    selectedOpportunities: [program, scholarship],
  });
  assert.equal(result.programId, 7);
  assert.equal(result.scholarshipId, 4);
});

test('an active scholarship falls back to the first selected program', () => {
  const result = resolveFinancialSelection({
    routeState: null,
    activeOpportunity: scholarship,
    selectedOpportunities: [scholarship, program],
  });
  assert.equal(result.programId, 7);
  assert.equal(result.scholarshipId, 4);
});

test('nothing selected, or only sample programs, gives no program to calculate', () => {
  assert.equal(resolveFinancialSelection({ routeState: null, activeOpportunity: null, selectedOpportunities: [] }).programId, null);
  assert.equal(getBackendProgramId({ id: 'univ-1', kind: 'program' }), null);
  assert.equal(resolveFinancialSelection({ routeState: undefined, activeOpportunity: scholarship, selectedOpportunities: [scholarship] }).programId, null);
});
