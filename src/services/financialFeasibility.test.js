import test from 'node:test';
import assert from 'node:assert/strict';
import { calculateFinancialFeasibility } from './financialFeasibility.js';

function makeFinancialData(overrides = {}) {
  const costs = {
    tuition: 10000,
    accommodationFood: 12000,
    healthInsurance: 600,
    visaResidencePermit: 200,
    travel: 800,
    otherFees: 400,
  };
  return {
    studyDuration: { value: 2, unit: 'years', sourceStatus: 'official-verified' },
    costs: Object.fromEntries(Object.entries(costs).map(([key, amount]) => [
      key,
      {
        amount,
        currency: 'USD',
        period: key === 'visaResidencePermit' || key === 'travel' ? 'total' : 'yearly',
        sourceStatus: 'official-verified',
      },
    ])),
    ...overrides,
  };
}

test('annual and one-time costs are totalled across the study duration', () => {
  const result = calculateFinancialFeasibility({
    financialData: makeFinancialData(),
    budget: { amount: '10000', currency: 'USD' },
  });
  assert.equal(result.totalCost, 47000);
  assert.equal(result.fundingGap, 37000);
});

test('counts confirmed support once and caps tuition waivers at tuition cost', () => {
  const award = {
    id: 'award-1',
    amount: 7000,
    currency: 'USD',
    period: 'yearly',
    kind: 'tuition-waiver',
    status: 'awarded',
    sourceStatus: 'official-verified',
  };
  const result = calculateFinancialFeasibility({
    financialData: makeFinancialData(),
    budget: { amount: '10000', currency: 'USD' },
    funding: [award, award, {
      id: 'potential-award',
      amount: 9000,
      currency: 'USD',
      period: 'yearly',
      status: 'potential',
      sourceStatus: 'official-verified',
    }],
  });
  assert.equal(result.applicableFunding, 14000);
  assert.equal(result.fundingGap, 23000);
  assert.equal(result.potentialFunding.length, 1);
});

test('missing cost data and mismatched currencies do not produce an affordability result', () => {
  const missing = makeFinancialData();
  delete missing.costs.travel;
  const missingResult = calculateFinancialFeasibility({
    financialData: missing,
    budget: { amount: '10000', currency: 'USD' },
  });
  const currencyResult = calculateFinancialFeasibility({
    financialData: makeFinancialData(),
    budget: { amount: '10000', currency: 'EUR' },
  });
  assert.equal(missingResult.status, 'insufficient-information');
  assert.equal(currencyResult.status, 'insufficient-information');
  assert.equal(currencyResult.budgetCurrencyMismatch, true);
});

test('unverified listed costs cannot produce a definitive affordability status', () => {
  const financialData = makeFinancialData();
  financialData.costs.tuition.sourceStatus = 'unverified-sample';
  const result = calculateFinancialFeasibility({
    financialData,
    budget: { amount: '50000', currency: 'USD' },
  });
  assert.equal(result.complete, true);
  assert.equal(result.verified, false);
  assert.equal(result.status, 'unverified');
});

test('uses the newly selected opportunity financial data instead of retaining the prior total', () => {
  const budget = { amount: '10000', currency: 'USD' };
  const first = calculateFinancialFeasibility({
    financialData: makeFinancialData(),
    budget,
  });
  const secondOpportunity = makeFinancialData();
  secondOpportunity.costs.tuition.amount = 20000;
  const second = calculateFinancialFeasibility({
    financialData: secondOpportunity,
    budget,
  });
  assert.equal(first.totalCost, 47000);
  assert.equal(second.totalCost, 67000);
});

test('blank cost amounts are treated as missing rather than zero', () => {
  const financialData = makeFinancialData();
  financialData.costs.travel.amount = '';
  const result = calculateFinancialFeasibility({
    financialData,
    budget: { amount: '10000', currency: 'USD' },
  });
  assert.equal(result.status, 'insufficient-information');
  assert.equal(result.missingItems.some((item) => item.key === 'travel'), true);
});
