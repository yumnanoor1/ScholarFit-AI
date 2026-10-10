export const FINANCIAL_COSTS = [
  { key: 'tuition', label: 'Tuition fees' },
  { key: 'accommodationFood', label: 'Accommodation and food' },
  { key: 'healthInsurance', label: 'Health insurance' },
  { key: 'visaResidencePermit', label: 'Visa and residence permit' },
  { key: 'travel', label: 'Travel expenses' },
  { key: 'otherFees', label: 'Other relevant fees' },
];

const PERIODS = new Set(['total', 'monthly', 'yearly']);

function getDurationMonths(duration) {
  if (!duration || !Number.isFinite(Number(duration.value)) || Number(duration.value) <= 0) return null;
  if (duration.unit === 'months') return Number(duration.value);
  if (duration.unit === 'years') return Number(duration.value) * 12;
  return null;
}

function normalizeCurrency(currency) {
  return typeof currency === 'string' && /^[A-Z]{3}$/i.test(currency)
    ? currency.toUpperCase()
    : null;
}

function amountForStudyPeriod(item, durationMonths) {
  if (item?.amount === '' || item?.amount === null || item?.amount === undefined) return null;
  const amount = Number(item?.amount);
  if (
    !Number.isFinite(amount) ||
    amount < 0 ||
    !PERIODS.has(item.period)
  ) return null;
  if (item.period === 'total') return amount;
  if (!Number.isFinite(durationMonths) || durationMonths <= 0) return null;
  if (item.period === 'monthly') return amount * durationMonths;
  return amount * (durationMonths / 12);
}

function isVerifiedFinancialData(item) {
  return item?.sourceStatus === 'official-verified';
}

export function calculateFinancialFeasibility({
  financialData,
  budget,
  funding = [],
}) {
  const durationMonths = getDurationMonths(financialData?.studyDuration);
  const costItems = FINANCIAL_COSTS.map(({ key, label }) => ({
    key,
    label,
    ...financialData?.costs?.[key],
  }));
  const currency = costItems.map((item) => normalizeCurrency(item.currency)).find(Boolean) || null;
  const missingItems = costItems.filter((item) => (
    amountForStudyPeriod(item, durationMonths || 0) === null ||
    normalizeCurrency(item.currency) !== currency
  ));
  const budgetAmount = Number(budget?.amount);
  const budgetIsValid = budget?.amount !== '' &&
    Number.isFinite(budgetAmount) &&
    budgetAmount >= 0 &&
    Boolean(normalizeCurrency(budget?.currency)) &&
    normalizeCurrency(budget.currency) === currency;
  const costTotals = durationMonths
    ? costItems.map((item) => amountForStudyPeriod(item, durationMonths))
    : [];
  const validCostData = (durationMonths !== null || costItems.every((item) => item.period === 'total')) &&
    costTotals.length === FINANCIAL_COSTS.length &&
    costTotals.every((amount) => amount !== null) &&
    missingItems.length === 0;

  if (!validCostData || !budgetIsValid) {
    return {
      complete: false,
      verified: false,
      currency: currency || null,
      durationMonths,
      totalCost: null,
      applicableFunding: null,
      personalBudget: budgetIsValid ? budgetAmount : null,
      fundingGap: null,
      missingItems: missingItems.map(({ key, label }) => ({ key, label })),
      budgetCurrencyMismatch: Boolean(budget?.currency && currency && budget.currency !== currency),
      status: 'insufficient-information',
    };
  }

  const totalCost = costTotals.reduce((total, amount) => total + amount, 0);
  const tuitionTotal = costTotals[0];
  const seenFundingIds = new Set();
  let applicableFunding = 0;
  let tuitionWaiver = 0;
  let fundingUnverified = false;
  const potentialFunding = [];

  funding.forEach((item, index) => {
    const id = item.id || `funding-${index}`;
    if (seenFundingIds.has(id)) return;
    seenFundingIds.add(id);

    if (item.status !== 'awarded' && item.status !== 'confirmed') {
      potentialFunding.push(item);
      return;
    }
    if (
      normalizeCurrency(item.currency) !== currency ||
      amountForStudyPeriod(item, durationMonths) === null ||
      !isVerifiedFinancialData(item)
    ) {
      fundingUnverified = true;
      potentialFunding.push(item);
      return;
    }

    const value = amountForStudyPeriod(item, durationMonths);
    if (item.kind === 'tuition-waiver') {
      tuitionWaiver = Math.min(tuitionTotal, tuitionWaiver + value);
    } else {
      applicableFunding += value;
    }
  });

  applicableFunding = Math.min(totalCost, applicableFunding + tuitionWaiver);
  const fundingGap = Math.max(0, totalCost - applicableFunding - budgetAmount);
  const durationVerified = durationMonths === null
    ? costItems.every((item) => item.period === 'total')
    : isVerifiedFinancialData(financialData.studyDuration);
  const verified = costItems.every(isVerifiedFinancialData) &&
    durationVerified &&
    !fundingUnverified;

  return {
    complete: true,
    verified,
    currency,
    durationMonths,
    totalCost,
    applicableFunding,
    personalBudget: budgetAmount,
    fundingGap,
    missingItems: [],
    budgetCurrencyMismatch: false,
    potentialFunding,
    status: verified
      ? (fundingGap === 0 ? 'affordable' : 'funding-gap')
      : 'unverified',
  };
}

export function getFinancialItemStudyTotal(item, durationMonths) {
  return amountForStudyPeriod(item, durationMonths);
}
