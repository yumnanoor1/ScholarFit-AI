import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BadgeCheck, CircleDollarSign, GraduationCap, Info, MapPin,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { getOpportunityTitle } from '../services/opportunityJourney';
import {
  calculateFinancialFeasibility,
  FINANCIAL_COSTS,
} from '../services/financialFeasibility';
import './FinancialFeasibility.css';

function isScholarship(opportunity) {
  return opportunity?.kind === 'scholarship' || opportunity?.id?.startsWith('sch-');
}

function isLinked(program, scholarship) {
  return Boolean(
    program &&
    scholarship &&
    (
      scholarship.programId === program.id ||
      scholarship.universityId === program.id ||
      program.scholarshipIds?.includes(scholarship.id)
    )
  );
}

function formatStudyPeriod(period) {
  if (period === 'total') return 'for the full study period';
  if (period === 'monthly') return 'per month';
  if (period === 'yearly') return 'per year';
  return 'study period not specified';
}

function formatDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function FinancialSource({ item }) {
  const updated = formatDate(item?.lastUpdated);
  const sourceUrl = typeof item?.sourceUrl === 'string' && /^https?:\/\//i.test(item.sourceUrl)
    ? item.sourceUrl
    : null;
  return (
    <span className="financial-item-source">
      {sourceUrl
        ? <a href={sourceUrl} target="_blank" rel="noreferrer">{item.source || 'View source'}</a>
        : item?.source || 'Source not provided'}
      {updated && <span> · Updated {updated}</span>}
    </span>
  );
}

function displayAmount(item) {
  return item?.amount !== '' &&
    item?.amount !== null &&
    item?.amount !== undefined &&
    Number.isFinite(Number(item.amount)) &&
    item?.currency
    ? `${item.currency} ${Number(item.amount).toLocaleString()} ${formatStudyPeriod(item.period)}`
    : 'Amount or currency not provided';
}

function getEstimateDefaults(country, currency) {
  const isGermany = country === 'Germany' && currency === 'EUR';
  const values = isGermany
    ? [3000, 12000, 1200, 100, 600, 1000]
    : currency === 'EUR'
      ? [18000, 14000, 1600, 250, 1000, 1500]
      : [25000, 18000, 2500, 500, 1500, 2000];
  return Object.fromEntries(FINANCIAL_COSTS.map(({ key }, index) => [
    key,
    { amount: String(values[index]), period: index === 3 || index === 4 ? 'total' : 'yearly' },
  ]));
}

function getInitialCostDraft(financialData, country, currency) {
  const estimates = getEstimateDefaults(country, currency);
  return Object.fromEntries(FINANCIAL_COSTS.map(({ key }) => {
    const provided = financialData?.costs?.[key];
    return [key, provided?.amount !== undefined && provided?.amount !== null
      ? { amount: String(provided.amount), period: provided.period || 'yearly' }
      : estimates[key]];
  }));
}

export default function FinancialFeasibility() {
  const { activeOpportunity, selectedOpportunities } = useProfile();
  const stateKey = JSON.stringify([
    activeOpportunity?.id || null,
    ...selectedOpportunities.map((item) => item.id).sort(),
  ]);

  return <FinancialFeasibilityContent key={stateKey} />;
}

function FinancialFeasibilityContent() {
  const navigate = useNavigate();
  const {
    activeOpportunity,
    selectedOpportunities,
    financialBudget,
    saveFinancialBudget,
  } = useProfile();
  const defaultCurrency = activeOpportunity?.country === 'Germany' ? 'EUR' : 'USD';
  const [budgetDraft, setBudgetDraft] = useState(() => ({
    amount: financialBudget.amount,
    currency: financialBudget.currency || defaultCurrency,
  }));
  const [budgetError, setBudgetError] = useState('');
  const [budgetSaved, setBudgetSaved] = useState(false);

  const activeIsScholarship = isScholarship(activeOpportunity);
  const linkedProgram = activeIsScholarship
    ? selectedOpportunities.find((item) => !isScholarship(item) && isLinked(item, activeOpportunity)) || null
    : activeOpportunity;
  const linkedScholarship = activeIsScholarship
    ? activeOpportunity
    : selectedOpportunities.find((item) => isScholarship(item) && isLinked(activeOpportunity, item)) || null;
  const financialData = linkedProgram?.financialData ||
    (activeIsScholarship ? activeOpportunity?.financialData : null) ||
    {};
  const scholarshipFunding = Array.isArray(linkedScholarship?.financialData?.funding)
    ? linkedScholarship.financialData.funding
    : [];
  const [costDraft, setCostDraft] = useState(() => getInitialCostDraft(financialData, activeOpportunity?.country, defaultCurrency));
  const [costCurrency, setCostCurrency] = useState(defaultCurrency);
  const calculation = calculateFinancialFeasibility({
    financialData,
    budget: financialBudget,
    funding: scholarshipFunding,
  });
  const duration = financialData.studyDuration;
  const durationLabel = duration?.value && duration?.unit
    ? `${duration.value} ${duration.unit}`
    : linkedProgram?.studyDuration || activeOpportunity?.studyDuration || 'Not provided';
  const costItems = FINANCIAL_COSTS.map(({ key, label }) => ({
    key,
    label,
    ...financialData.costs?.[key],
    ...costDraft[key],
    currency: costCurrency,
  }));
  const verifiedDurationSource = financialData.studyDuration?.sourceStatus === 'official-verified' ||
    (!duration && costItems.every((item) => item.period === 'total'));
  const verifiedCostSources = verifiedDurationSource &&
    costItems.every((item) => item.amount !== undefined && item.sourceStatus === 'official-verified');

  const saveBudget = (event) => {
    event.preventDefault();
    setBudgetError('');
    setBudgetSaved(false);
    if (!/^[A-Z]{3}$/.test(budgetDraft.currency.trim().toUpperCase())) {
      setBudgetError('Enter a 3-letter currency code, such as USD or EUR.');
      return;
    }
    try {
      saveFinancialBudget({
        amount: budgetDraft.amount,
        currency: costCurrency,
      });
      setBudgetSaved(true);
    } catch (error) {
      console.error('Unable to save the financial budget.', error);
      setBudgetError('Your budget could not be saved. Please check the amount and try again.');
    }
  };

  const estimatedTotals = useMemo(() => {
    const durationMonths = duration?.value && duration?.unit
      ? Number(duration.value) * (duration.unit === 'years' ? 12 : 1)
      : 24;
    const totals = costItems.map((item) => {
      const amount = Number(item.amount);
      if (item.amount === '' || !Number.isFinite(amount) || amount < 0) return null;
      if (item.period === 'total') return amount;
      if (item.period === 'monthly') return amount * durationMonths;
      return amount * durationMonths / 12;
    });
    return totals.every((amount) => amount !== null)
      ? { total: totals.reduce((sum, amount) => sum + amount, 0), items: totals }
      : null;
  }, [costItems, duration]);

  const budgetAmount = Number(budgetDraft.amount);
  const hasBudget = budgetDraft.amount !== '' && Number.isFinite(budgetAmount) && budgetAmount >= 0;
  const estimatedFunding = calculation.complete && calculation.currency === costCurrency
    ? calculation.applicableFunding
    : 0;
  const budgetContribution = estimatedTotals && hasBudget
    ? Math.min(budgetAmount, Math.max(0, estimatedTotals.total - estimatedFunding))
    : 0;
  const estimatedGap = estimatedTotals && hasBudget
    ? Math.max(0, estimatedTotals.total - estimatedFunding - budgetContribution)
    : null;

  if (!activeOpportunity) {
    return (
      <main className="page-container financial-page">
        <h1 className="page-title">Financial Feasibility</h1>
        <p className="page-subtitle">Review study costs, scholarship support, and your personal budget.</p>
        <section className="card financial-empty-state">
          <div className="financial-empty-icon"><CircleDollarSign size={22} /></div>
          <div>
            <h2>No opportunity selected</h2>
            <p>Select a university program or scholarship to review its financial information.</p>
          </div>
          <button className="btn btn-primary" onClick={() => navigate('/recommendations')}>Browse recommendations</button>
        </section>
      </main>
    );
  }

  return (
    <main className="page-container financial-page">
      <h1 className="page-title">Financial Feasibility</h1>
      <p className="page-subtitle">Check whether the selected Master's opportunity fits your study budget.</p>

      <section className="financial-opportunity card">
        <div className="financial-opportunity-icon"><GraduationCap size={22} /></div>
        <div className="financial-opportunity-copy">
          <span className="financial-eyebrow">Selected opportunity</span>
          <h2>{linkedProgram ? getOpportunityTitle(linkedProgram) : 'University program not linked'}</h2>
          <p><MapPin size={14} /> {linkedProgram?.university || linkedProgram?.provider || linkedProgram?.country || activeOpportunity.country || 'Country not provided'}</p>
          <div className="financial-opportunity-meta">
            {linkedProgram?.program && <span>Program: {linkedProgram.program}</span>}
            <span>Study duration: {durationLabel}</span>
            <span>Scholarship: {linkedScholarship ? getOpportunityTitle(linkedScholarship) : 'Not selected or linked'}</span>
          </div>
        </div>
        <span className={`financial-source-badge ${verifiedCostSources ? 'is-verified' : ''}`}>
          {verifiedCostSources
            ? <><BadgeCheck size={14} /> Verified financial data</>
            : <><Info size={14} /> Financial data not verified</>}
        </span>
      </section>

      <section className="financial-section financial-budget-step" aria-labelledby="financial-budget-title">
        <div className="financial-step-heading"><span>Step 1</span><h2 id="financial-budget-title">Your budget and currency</h2></div>
        <form className="card financial-budget-form" onSubmit={saveBudget}>
          <label>
            <span>Total available budget ({costCurrency})</span>
            <input
              type="number"
              min="0"
              step="any"
              required
              value={budgetDraft.amount}
              onChange={(event) => {
                setBudgetDraft((current) => ({ ...current, amount: event.target.value }));
                setBudgetSaved(false);
              }}
              placeholder="Enter your budget"
            />
          </label>
          <label className="financial-currency-field">
            <span>Currency</span>
            <select
              value={costCurrency}
              onChange={(event) => {
                setCostCurrency(event.target.value);
                setBudgetDraft((current) => ({ ...current, currency: event.target.value }));
                setCostDraft(getInitialCostDraft(financialData, linkedProgram?.country || activeOpportunity.country, event.target.value));
                setBudgetSaved(false);
              }}
            >
              <option value="EUR">EUR (€)</option>
              <option value="USD">USD ($)</option>
            </select>
          </label>
          <button type="submit" className="btn btn-primary">Save budget</button>
          {budgetSaved && <span className="financial-form-success" role="status">Budget saved.</span>}
          {budgetError && <span className="financial-form-error" role="alert">{budgetError}</span>}
          <p className="financial-currency-note">All budget and cost figures below use {costCurrency}. Switching currency resets the cost rows to estimates in that currency; review your budget after switching.</p>
        </form>
      </section>

      <div className="financial-dashboard-grid">
        <div className="financial-dashboard-main">
          <section className="financial-section financial-cost-section">
            <div className="financial-section-heading">
              <div className="financial-step-heading"><span>Step 2</span><h2>Study cost estimates</h2></div>
            </div>
            <div className="financial-cost-table-wrap">
              <table className="financial-cost-table">
                <thead>
                  <tr>
                    <th scope="col">Expense item</th>
                    <th scope="col">Amount ({costCurrency})</th>
                    <th scope="col">Period</th>
                    <th scope="col">Study-period estimate ({costCurrency})</th>
                  </tr>
                </thead>
                <tbody>
                  {costItems.map((item) => {
                    const total = estimatedTotals?.items[FINANCIAL_COSTS.findIndex(({ key }) => key === item.key)];
                    const isEstimate = !financialData.costs?.[item.key]?.amount;
                    return (
                      <tr key={item.key}>
                        <th scope="row">{item.label}</th>
                        <td>
                          <label className="financial-cost-input-wrap">
                            <input
                              type="number"
                              aria-label={`${item.label} amount in ${costCurrency}`}
                              min="0"
                              step="any"
                              value={costDraft[item.key]?.amount ?? ''}
                              onChange={(event) => setCostDraft((current) => ({
                                ...current,
                                [item.key]: { ...current[item.key], amount: event.target.value },
                              }))}
                            />
                            {isEstimate && <small>Estimate</small>}
                          </label>
                        </td>
                        <td>
                          <label className="financial-period-select">
                            <select
                              aria-label={`${item.label} cost period`}
                              value={costDraft[item.key]?.period || 'yearly'}
                              onChange={(event) => setCostDraft((current) => ({
                                ...current,
                                [item.key]: { ...current[item.key], period: event.target.value },
                              }))}
                            >
                              <option value="total">Study total</option>
                              <option value="yearly">Yearly</option>
                              <option value="monthly">Monthly</option>
                            </select>
                          </label>
                        </td>
                        <td>{total != null ? `${costCurrency} ${total.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="financial-table-footnote">Estimates are planning values, not provider quotes. Confirm tuition and living costs with the university. Currency: {costCurrency}. Study duration used: {durationLabel === 'Not provided' ? '24 months (estimate)' : durationLabel}.</p>
          </section>

          <section className="financial-results-step" aria-labelledby="financial-result-title">
            <div className="financial-step-heading"><span>Step 3</span><h2 id="financial-result-title">Estimated result</h2></div>
            {!hasBudget ? (
              <p className="financial-enter-budget">Enter your budget to see results.</p>
            ) : estimatedTotals ? (
              <div className="financial-result-cards">
                <article className="card"><span>Estimated total costs ({costCurrency})</span><strong>{estimatedTotals.total.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong></article>
                <article className="card"><span>Verified awarded funding ({costCurrency})</span><strong>{estimatedFunding.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong></article>
                <article className="card"><span>Estimated remaining gap ({costCurrency})</span><strong>{estimatedGap.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong></article>
              </div>
            ) : <p className="financial-enter-budget">Enter valid non-negative amounts for each cost to calculate an estimate.</p>}
          </section>

          {hasBudget && estimatedTotals && (
            <section className="financial-chart-step" aria-labelledby="financial-chart-title">
              <div className="financial-step-heading"><span>Step 4</span><h2 id="financial-chart-title">Costs vs budget and funding</h2></div>
              <div className="card financial-cost-chart">
                <div
                  className="financial-donut"
                  role="img"
                  aria-label={`Estimated costs ${costCurrency} ${estimatedTotals.total.toLocaleString()}, budget ${costCurrency} ${budgetContribution.toLocaleString()}, verified funding ${costCurrency} ${estimatedFunding.toLocaleString()}, remaining gap ${costCurrency} ${estimatedGap.toLocaleString()}`}
                  style={{
                    '--budget-share': `${estimatedTotals.total ? budgetContribution / estimatedTotals.total * 100 : 0}%`,
                    '--funding-share': `${estimatedTotals.total ? estimatedFunding / estimatedTotals.total * 100 : 0}%`,
                  }}
                >
                  <strong>{costCurrency}</strong>
                  <span>Estimated costs</span>
                </div>
                <ul className="financial-chart-legend">
                  <li><span className="budget-key" />Budget used <strong>{costCurrency} {budgetContribution.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong></li>
                  <li><span className="funding-key" />Verified funding <strong>{costCurrency} {estimatedFunding.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong></li>
                  <li><span className="gap-key" />Remaining gap <strong>{costCurrency} {estimatedGap.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong></li>
                </ul>
              </div>
            </section>
          )}

          {linkedScholarship && (
            <section className="financial-section">
              <div className="financial-section-heading">
                <div>
                  <span className="financial-eyebrow">Scholarship support</span>
                  <h2>Scholarship funding</h2>
                </div>
              </div>
              <div className="card financial-funding-card">
                <>
                  <div className="financial-funding-title">
                    <GraduationCap size={18} />
                    <strong>{getOpportunityTitle(linkedScholarship)}</strong>
                  </div>
                  {linkedScholarship.coverage && (
                    <div className="financial-listed-coverage">
                      <span>Listed terms (not confirmed)</span>
                      <strong>{linkedScholarship.coverage}</strong>
                      <FinancialSource item={linkedScholarship} />
                    </div>
                  )}
                  {scholarshipFunding.length > 0 ? (
                    <ul className="financial-funding-list">
                      {scholarshipFunding.map((item, index) => (
                        <li key={item.id || `${item.kind || 'funding'}-${index}`}>
                          <div>
                            <strong>{item.label || item.kind || 'Scholarship benefit'}</strong>
                            <span className={item.status === 'awarded' || item.status === 'confirmed' ? 'financial-award-confirmed' : 'financial-award-potential'}>
                              {item.status === 'awarded' || item.status === 'confirmed' ? 'Awarded / confirmed' : 'Potential · not counted'}
                            </span>
                          </div>
                          <strong>{displayAmount(item)}</strong>
                          <FinancialSource item={item} />
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="financial-muted-copy">No structured scholarship benefits are available to calculate funding from.</p>
                  )}
                </>
              </div>
            </section>
          )}
        </div>

      </div>
    </main>
  );
}
