import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AlertTriangle, CheckCircle2, Info, Loader2, Wallet,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import { parseScholarshipId } from '../services/opportunityApi';
import { resolveFinancialSelection } from '../services/financialSelection';
import './FinancialFeasibility.css';

const COST_ROWS = [
  ['living_costs', 'Living costs'],
  ['university_fees', 'Institution fees'],
  ['health_insurance', 'Health insurance'],
  ['visa', 'Visa and residence permit'],
  ['travel', 'Travel expenses'],
  ['application_fees', 'Application fees'],
  ['other', 'Other relevant fees'],
];
const ONE_OFF_COSTS = new Set(['visa', 'travel', 'application_fees']);
const STATUS_DISPLAY = {
  feasible: 'Affordable with the available information',
  partially_feasible: 'Partially affordable',
  not_feasible: 'Not affordable with this budget',
  insufficient_data: 'Insufficient information to calculate affordability',
};

function getErrorMessage(error) {
  if (error?.status === 401) return 'Your session has expired. Sign in again to continue.';
  if (error?.status === 404) return error.message || 'This scholarship is no longer available.';
  if (error?.status === 422) return error.message || 'Check that all amounts are valid and non-negative.';
  return error?.message || 'The request could not be completed. Please try again.';
}

function validAmount(value) {
  return value !== '' && value != null && Number.isFinite(Number(value)) && Number(value) >= 0;
}

function expensePayload(drafts) {
  return Object.fromEntries(Object.entries(drafts)
    .filter(([, row]) => validAmount(row.amount))
    .map(([category, row]) => [category, {
      amount: Number(row.amount),
      currency: row.currency,
      period: row.period,
      source: 'student_input',
    }]));
}

function money(amount, currency) {
  if (amount == null || !Number.isFinite(Number(amount))) return 'Not available';
  return `${currency || ''} ${Number(amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}`.trim();
}

export default function FinancialFeasibility() {
  const { activeOpportunity, selectedOpportunities } = useProfile();
  const navigate = useNavigate();
  const routeState = useLocation().state;
  const selection = resolveFinancialSelection({ routeState, activeOpportunity, selectedOpportunities });
  const [planState, setPlanState] = useState({ plan: null, error: '', loading: true });
  const [scholarships, setScholarships] = useState([]);
  const [scholarshipId, setScholarshipId] = useState(selection.scholarshipId);
  const [currency, setCurrency] = useState('USD');
  const [budgetAmount, setBudgetAmount] = useState('');
  const [draftState, setDraftState] = useState({ key: '', value: {} });
  const [saveState, setSaveState] = useState({ saving: false, saved: false, error: '' });
  const [response, setResponse] = useState({ key: '', result: null, error: '' });
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let current = true;
    Promise.all([apiService.getFinancialPlan(), apiService.getMatchedScholarships()])
      .then(([plan, items]) => {
        if (!current) return;
        setPlanState({ plan, error: '', loading: false });
        setScholarships(items);
        const supported = plan.supported_currencies || [];
        const defaultCurrency = plan.budget?.currency || (supported.includes('EUR') ? 'EUR' : supported[0]) || 'USD';
        setCurrency(defaultCurrency);
        setBudgetAmount(plan.budget ? String(plan.budget.amount) : '');
        if (selection.scholarshipId) setScholarshipId(selection.scholarshipId);
        else if (items.length) setScholarshipId((current) => current || items[0]._numericId);
      })
      .catch((error) => {
        console.error('Unable to load the scholarship financial plan.', error);
        if (current) setPlanState({ plan: null, error: getErrorMessage(error), loading: false });
      });
    return () => { current = false; };
  }, [retry, selection.scholarshipId]);

  const draftKey = scholarshipId ? String(scholarshipId) : '';
  const savedExpenses = planState.plan?.expenses?.[`scholarship:${scholarshipId}`] || {};
  const savedDrafts = Object.fromEntries(Object.entries(savedExpenses)
      .filter(([, row]) => row)
      .map(([category, row]) => [category, {
        amount: String(row.amount),
        currency: row.currency,
        period: row.period,
      }]));
  const drafts = draftState.key === draftKey ? draftState.value : savedDrafts;
  const setDrafts = (update) => setDraftState((current) => ({
    key: draftKey,
    value: typeof update === 'function'
      ? update(current.key === draftKey ? current.value : savedDrafts)
      : update,
  }));

  const supported = planState.plan?.supported_currencies || [];
  const selectedScholarship = scholarships.find((item) => item._numericId === scholarshipId) || null;
  const budgetIsValid = validAmount(budgetAmount);
  const expenses = expensePayload(drafts);
  const invalidCost = Object.values(drafts).some((row) => row.amount !== '' && !validAmount(row.amount));
  const payloadKey = scholarshipId && !invalidCost ? JSON.stringify({
    scholarship_id: scholarshipId,
    currency,
    ...(budgetIsValid ? { budget: { amount: Number(budgetAmount), currency } } : {}),
    expenses,
  }) : '';

  useEffect(() => {
    if (!payloadKey) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      apiService.calculateFinancialFeasibility(JSON.parse(payloadKey), { signal: controller.signal })
        .then((result) => setResponse({ key: payloadKey, result, error: '' }))
        .catch((error) => {
          if (error?.name === 'AbortError') return;
          console.error('Unable to calculate scholarship financial feasibility.', error);
          setResponse({ key: payloadKey, result: null, error: getErrorMessage(error) });
        });
    }, 350);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [payloadKey]);

  const savePlan = async (event) => {
    event.preventDefault();
    if (!budgetIsValid) {
      setSaveState({ saving: false, saved: false, error: 'Enter a total budget of zero or more.' });
      return;
    }
    setSaveState({ saving: true, saved: false, error: '' });
    try {
      let next = await apiService.saveFinancialBudget({ amount: Number(budgetAmount), currency });
      if (scholarshipId) next = await apiService.saveScholarshipExpenses(scholarshipId, expenses);
      setPlanState({ plan: next, error: '', loading: false });
      setSaveState({ saving: false, saved: true, error: '' });
    } catch (error) {
      console.error('Unable to save the scholarship financial plan.', error);
      setSaveState({ saving: false, saved: false, error: getErrorMessage(error) });
    }
  };

  if (planState.loading) {
    return <main className="page-container financial-page"><p className="fin-summary-empty" role="status"><Loader2 size={22} className="fin-spin" /> Loading your financial plan…</p></main>;
  }
  if (planState.error) {
    return (
      <main className="page-container financial-page">
        <h1 className="page-title">Scholarship Financial Feasibility</h1>
        <section className="fin-card fin-empty" role="alert">
          <AlertTriangle size={28} aria-hidden="true" />
          <h2>Your financial plan could not be loaded</h2>
          <p>{planState.error}</p>
          <button type="button" className="btn btn-primary" onClick={() => { setPlanState({ plan: null, error: '', loading: true }); setRetry((value) => value + 1); }}>Try again</button>
        </section>
      </main>
    );
  }

  const current = payloadKey && response.key === payloadKey ? response : null;
  const result = current?.result;
  const lines = Object.fromEntries((result?.costs || []).map((line) => [line.category, line]));

  return (
    <main className="page-container financial-page">
      <h1 className="page-title">Scholarship Financial Feasibility</h1>

      {!scholarships.length ? (
        <section className="fin-card fin-empty">
          <span className="fin-empty-icon" aria-hidden="true"><Info size={28} /></span>
          <h2>No scholarships are available to assess</h2>
          <p>Scholarship affordability needs an existing scholarship record. Browse the scholarship catalogue or try again later.</p>
          <button type="button" className="btn btn-outline" onClick={() => navigate('/scholarships')}>Browse scholarships</button>
        </section>
      ) : (
        <>
          <section className="fin-card">
            <header className="fin-card-head">
              <span className="fin-step">1</span>
              <div><h2>Choose a scholarship</h2><p>Only saved scholarship records are used in this estimate.</p></div>
            </header>
            <label className="fin-budget-scholarship">
              <span>Scholarship</span>
              <select value={scholarshipId || ''} onChange={(event) => {
                setScholarshipId(parseScholarshipId(event.target.value) || Number(event.target.value) || null);
                setSaveState({ saving: false, saved: false, error: '' });
              }}>
                {scholarshipId && !selectedScholarship && <option value={scholarshipId}>Selected scholarship</option>}
                {scholarships.map((item) => <option key={item.id} value={item._numericId}>{item.name}</option>)}
              </select>
            </label>
            {selectedScholarship && <p className="fin-note">{selectedScholarship.provider || 'Provider not listed'} · {selectedScholarship.country || 'Country not listed'} · Source status: {selectedScholarship.verificationLabel || 'not recorded'}</p>}
          </section>

          <div className="fin-layout">
            <div className="fin-main">
              <section className="fin-card" aria-labelledby="financial-budget-title">
                <header className="fin-card-head">
                  <span className="fin-step">2</span>
                  <div><h2 id="financial-budget-title">Your total budget</h2><p>Funds available for the full study period.</p></div>
                </header>
                <form className="fin-budget-form" onSubmit={savePlan}>
                  <label className="fin-budget-amount">
                    <span>Total available budget</span>
                    <span className="fin-money-input">
                      <Wallet size={18} aria-hidden="true" />
                      <input type="number" min="0" step="any" value={budgetAmount} onChange={(event) => {
                        setBudgetAmount(event.target.value);
                        setSaveState({ saving: false, saved: false, error: '' });
                      }} placeholder="Enter your budget" />
                      <em>{currency}</em>
                    </span>
                  </label>
                  <label className="fin-budget-currency">
                    <span>Currency</span>
                    <select value={currency} onChange={(event) => setCurrency(event.target.value)}>
                      {supported.map((code) => <option key={code} value={code}>{code}</option>)}
                    </select>
                  </label>
                  <button type="submit" className="btn btn-primary" disabled={saveState.saving || !budgetIsValid}>
                    {saveState.saving ? 'Saving…' : 'Save plan'}
                  </button>
                  {saveState.saved && <span className="fin-form-success" role="status"><CheckCircle2 size={14} /> Your plan is saved.</span>}
                  {saveState.error && <span className="fin-form-error" role="alert">{saveState.error}</span>}
                </form>
                <p className="fin-note">Changing the currency changes how the amount is interpreted. It does not convert your typed budget.</p>
              </section>

              <section className="fin-card" aria-labelledby="financial-cost-title">
                <header className="fin-card-head">
                  <span className="fin-step">3</span>
                  <div><h2 id="financial-cost-title">Additional cost estimates</h2><p>Verified scholarship-linked records may provide tuition or other costs. Add your own figures for costs that are missing.</p></div>
                </header>
                <ul className="fin-cost-list">
                  {COST_ROWS.map(([category, label]) => {
                    const line = lines[category];
                    const draft = drafts[category];
                    const row = draft || {};
                    return (
                      <li key={category} className="fin-cost-row">
                        <div className="fin-cost-copy">
                          <strong>{label}</strong>
                          {line?.amount != null && <small>Recorded estimate: {money(line.amount, result.currency)}{line.source_name ? ` · ${line.source_name}` : ''}</small>}
                          {line?.source_url && <a href={line.source_url} target="_blank" rel="noopener noreferrer">View cost source</a>}
                          {line?.note && <small>{line.note}</small>}
                        </div>
                        <label className="fin-cost-input">
                          <span className="sr-only">{label} amount</span>
                          <input type="number" min="0" step="any" value={row.amount || ''} placeholder="Your estimate" onChange={(event) => setDrafts((currentDrafts) => ({
                            ...currentDrafts,
                            [category]: {
                              amount: event.target.value,
                              currency: row.currency || line?.original_currency || currency,
                              period: row.period || line?.period || (ONE_OFF_COSTS.has(category) ? 'total' : 'yearly'),
                            },
                          }))} />
                          <select aria-label={`${label} currency`} value={row.currency || line?.original_currency || currency} onChange={(event) => setDrafts((currentDrafts) => ({
                            ...currentDrafts,
                            [category]: { amount: row.amount || '', currency: event.target.value, period: row.period || line?.period || 'yearly' },
                          }))}>
                            {supported.map((code) => <option key={code} value={code}>{code}</option>)}
                          </select>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </section>
            </div>

            <aside className="fin-summary">
              <section className="fin-card" aria-live="polite">
                <h2>Affordability result</h2>
                {!payloadKey && <p>Choose a scholarship to calculate affordability.</p>}
                {payloadKey && !current && <p role="status"><Loader2 size={18} className="fin-spin" /> Calculating from available data…</p>}
                {current?.error && <p className="fin-form-error" role="alert">{current.error}</p>}
                {result && (
                  <>
                    <h3 className={`fin-result-status is-${result.status}`}>{STATUS_DISPLAY[result.status] || STATUS_DISPLAY.insufficient_data}</h3>
                    <p className="fin-result-explanation">{result.scholarship?.verification_issue || result.explanation?.[0]}</p>
                    <dl className="fin-result-values">
                      <div><dt>Estimated costs</dt><dd>{money(result.total_estimated_cost, result.currency)}</dd></div>
                      <div><dt>Confirmed funding</dt><dd>{money(result.confirmed_funding, result.currency)}</dd></div>
                      <div><dt>Funding gap</dt><dd>{money(result.funding_gap, result.currency)}</dd></div>
                    </dl>
                    {result.missing_data?.length > 0 && (
                      <div className="fin-missing-data">
                        <strong>What is missing or uncertain</strong>
                        <ul>{result.missing_data.map((item) => <li key={item}>{item}</li>)}</ul>
                      </div>
                    )}
                    {result.uncertainties?.length > 0 && <ul className="fin-uncertainties">{result.uncertainties.map((item) => <li key={item}>{item}</li>)}</ul>}
                    <p className="fin-note">Potential or unverified scholarship funding is not included as confirmed funding.</p>
                  </>
                )}
              </section>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}
