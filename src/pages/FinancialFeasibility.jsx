import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle, BadgeCheck, CircleDollarSign, GraduationCap, Info, MapPin,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { getOpportunityTitle } from '../services/opportunityJourney';
import {
  calculateFinancialFeasibility,
  FINANCIAL_COSTS,
  getFinancialItemStudyTotal,
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

export default function FinancialFeasibility() {
  const navigate = useNavigate();
  const {
    activeOpportunity,
    selectedOpportunities,
    financialBudget,
    saveFinancialBudget,
  } = useProfile();
  const [budgetDraft, setBudgetDraft] = useState(financialBudget);
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
  const calculation = calculateFinancialFeasibility({
    financialData,
    budget: financialBudget,
    funding: scholarshipFunding,
  });
  const duration = financialData.studyDuration;
  const durationLabel = duration?.value && duration?.unit
    ? `${duration.value} ${duration.unit}`
    : linkedProgram?.studyDuration || activeOpportunity?.studyDuration || 'Not provided';
  const affordabilityLabel = calculation.status === 'affordable'
    ? 'Affordable based on verified costs, awarded funding, and your budget'
    : calculation.status === 'funding-gap'
      ? 'Funding gap'
      : calculation.status === 'unverified'
        ? 'Cannot confirm affordability: financial data or funding is unverified'
        : 'Insufficient information to calculate affordability.';

  const costItems = FINANCIAL_COSTS.map(({ key, label }) => ({
    key,
    label,
    ...financialData.costs?.[key],
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
        currency: budgetDraft.currency.trim().toUpperCase(),
      });
      setBudgetSaved(true);
    } catch (error) {
      console.error('Unable to save the financial budget.', error);
      setBudgetError('Your budget could not be saved. Please check the amount and try again.');
    }
  };

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

      <section className="financial-metrics-grid" aria-label="Financial overview">
        <article className="card financial-summary-card financial-summary-cost">
          <span>Total estimated study costs</span>
          <strong>{calculation.complete ? `${calculation.currency} ${calculation.totalCost.toLocaleString()}` : '—'}</strong>
          <small>
            {calculation.complete
              ? `For ${durationLabel === 'Not provided' ? 'the full study period' : durationLabel}`
              : 'Complete cost details to calculate'}
          </small>
        </article>
        <article className="card financial-summary-card financial-summary-funding">
          <span>Applicable awarded funding</span>
          <strong>{calculation.complete ? `${calculation.currency} ${calculation.applicableFunding.toLocaleString()}` : '—'}</strong>
          <small>Potential funding is not included</small>
        </article>
        <article className="card financial-summary-card financial-summary-gap">
          <span>Remaining funding gap</span>
          <strong>{calculation.complete ? `${calculation.currency} ${calculation.fundingGap.toLocaleString()}` : '—'}</strong>
          <small>After awarded funding and your budget</small>
        </article>
      </section>

      <div className="financial-dashboard-grid">
        <div className="financial-dashboard-main">
          <section className="financial-section financial-cost-section">
            <div className="financial-section-heading">
              <div>
                <span className="financial-eyebrow">Expense breakdown</span>
                <h2>Estimated study costs</h2>
              </div>
              <p>Amounts include their listed period and source. No currency conversions are applied.</p>
            </div>
            <div className="financial-cost-table-wrap">
              <table className="financial-cost-table">
                <thead>
                  <tr>
                    <th scope="col">Expense item</th>
                    <th scope="col">Estimated amount</th>
                    <th scope="col">Study-period total</th>
                    <th scope="col">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {costItems.map((item) => {
                    const total = getFinancialItemStudyTotal(item, calculation.durationMonths);
                    const isLegacyTuition = item.key === 'tuition' && !item.amount && linkedProgram?.tuition;
                    return (
                      <tr key={item.key}>
                        <th scope="row">{item.label}</th>
                        <td>
                          {item.amount !== undefined
                            ? displayAmount(item)
                            : isLegacyTuition
                              ? `${linkedProgram.tuition} · unverified listing`
                              : 'Not provided'}
                        </td>
                        <td>{total !== null && item.currency ? `${item.currency} ${total.toLocaleString()}` : '—'}</td>
                        <td>
                          {item.amount !== undefined
                            ? <FinancialSource item={item} />
                            : isLegacyTuition
                              ? <FinancialSource item={{ sourceStatus: linkedProgram.sourceStatus }} />
                              : <span className="financial-item-source">Source not provided</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

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

        <aside className="financial-dashboard-aside">
          <section className="financial-section">
            <div className="financial-section-heading">
              <div>
                <span className="financial-eyebrow">Personal contribution</span>
                <h2>Student budget</h2>
              </div>
              <p>Your budget stays separate from scholarship funding.</p>
            </div>
            <form className="card financial-budget-form" onSubmit={saveBudget}>
              <label>
                <span>Total available budget</span>
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
                  placeholder="Enter amount"
                />
              </label>
              <label className="financial-currency-field">
                <span>Currency code</span>
                <input
                  type="text"
                  required
                  maxLength={3}
                  pattern="[A-Za-z]{3}"
                  value={budgetDraft.currency}
                  onChange={(event) => {
                    setBudgetDraft((current) => ({ ...current, currency: event.target.value.toUpperCase() }));
                    setBudgetSaved(false);
                  }}
                  placeholder="USD"
                />
              </label>
              <button type="submit" className="btn btn-primary">Save budget</button>
              {budgetSaved && <span className="financial-form-success" role="status">Budget saved.</span>}
              {budgetError && <span className="financial-form-error" role="alert">{budgetError}</span>}
            </form>
          </section>

          <section className="card financial-affordability-card">
            <span className="financial-eyebrow">Affordability summary</span>
            <h2>Personal affordability</h2>
            <div className="financial-budget-overview">
              <span>Available personal budget</span>
              <strong>
                {financialBudget.amount !== '' && Number.isFinite(Number(financialBudget.amount))
                  ? `${financialBudget.currency} ${Number(financialBudget.amount).toLocaleString()}`
                  : 'Not provided'}
              </strong>
            </div>
            <p className="financial-gap-formula">Funding gap = max(0, total study cost − awarded funding − available budget).</p>
            <div className={`financial-status ${calculation.status}`} role="status">
              {calculation.status === 'insufficient-information' ? <AlertCircle size={18} /> : <Info size={18} />}
              <strong>{affordabilityLabel}</strong>
            </div>
            {!calculation.complete && (
              <p className="financial-missing-note">
                {calculation.budgetCurrencyMismatch
                  ? `Your budget currency (${financialBudget.currency}) does not match the opportunity cost currency (${calculation.currency}).`
                  : 'Verified costs for the full study duration and a budget in the same currency are required.'}
              </p>
            )}
          </section>

        </aside>
      </div>
    </main>
  );
}
