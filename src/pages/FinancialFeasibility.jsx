import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AlertTriangle, Award, BadgeCheck, CheckCircle2, Clock, GraduationCap, HeartPulse, Home,
  Info, Landmark, Loader2, MapPin, PiggyBank, Plane, Receipt, Stamp, Wallet, XCircle,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { getOpportunityTitle } from '../services/opportunityJourney';
import { getUniversityLogo } from '../services/programFit';
import { apiService } from '../services/api';
import { buildFinancialRouteState, getBackendProgramId, resolveFinancialSelection } from '../services/financialSelection';
import './FinancialFeasibility.css';

// Rows of the page, in order. `category` is the backend cost category.
const COST_ROWS = [
  { category: 'tuition', label: 'Tuition fees', icon: GraduationCap, tone: 'blue' },
  { category: 'living_costs', label: 'Living costs', icon: Home, tone: 'cyan' },
  { category: 'university_fees', label: 'University fees', icon: Landmark, tone: 'blue' },
  { category: 'health_insurance', label: 'Health insurance', icon: HeartPulse, tone: 'green' },
  { category: 'visa', label: 'Visa and residence permit', icon: Stamp, tone: 'navy' },
  { category: 'travel', label: 'Travel expenses', icon: Plane, tone: 'sky' },
  { category: 'application_fees', label: 'Application fees', icon: Receipt, tone: 'navy' },
  { category: 'other', label: 'Other relevant fees', icon: Receipt, tone: 'amber' },
];

// One-off costs start as a study total, so a visa fee isn't multiplied by the study years
const ONE_OFF_COSTS = new Set(['visa', 'travel', 'application_fees']);
const defaultPeriod = (category) => (ONE_OFF_COSTS.has(category) ? 'total' : 'yearly');

const STATUS_DISPLAY = {
  feasible: { label: 'Feasible', tone: 'is-covered', icon: CheckCircle2 },
  partially_feasible: { label: 'Partially feasible', tone: 'is-gap', icon: AlertTriangle },
  not_feasible: { label: 'Not feasible', tone: 'is-short', icon: XCircle },
  insufficient_data: { label: 'Insufficient information', tone: 'is-unknown', icon: Info },
};

function getApiErrorMessage(error) {
  if (error?.status === 401) return 'Your session has expired. Sign in again to continue.';
  if (error?.status === 404) return error.message || 'This program or scholarship is no longer available.';
  if (error?.status === 422) return error.message || 'Some amounts are not valid. Use non-negative numbers.';
  return 'The request could not be completed right now. Please try again.';
}

function isValidAmount(value) {
  return value !== '' && value != null && Number.isFinite(Number(value)) && Number(value) >= 0;
}

/** Student rows that hold a usable number, in the shape the backend stores. */
function toExpensePayload(drafts) {
  return Object.fromEntries(Object.entries(drafts)
    .filter(([, row]) => isValidAmount(row.amount))
    .map(([category, row]) => [category, {
      amount: Number(row.amount),
      currency: row.currency,
      period: row.period,
      source: 'student_input',
    }]));
}

function formatRecordRange(line) {
  const number = (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return `${line.original_currency} ${number(line.original_amount)}–${number(line.original_amount_max)}`;
}

/** Shown when no program is selected: pick one instead of reaching a dead end. */
function ProgramPicker({ scholarshipId }) {
  const navigate = useNavigate();
  const { selectOpportunity } = useProfile();
  const [state, setState] = useState({ status: 'loading', programs: [] });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let isCurrent = true;
    apiService.getMatchedUniversities()
      .then((programs) => { if (isCurrent) setState({ status: 'ready', programs }); })
      .catch((error) => {
        console.error('Unable to load programs for the financial planner.', error);
        if (isCurrent) setState({ status: 'error', programs: [] });
      });
    return () => { isCurrent = false; };
  }, [attempt]);

  const choose = (program) => {
    selectOpportunity({ ...program, kind: 'program' });
    navigate('/financial', {
      replace: true,
      state: buildFinancialRouteState({ programId: program._numericId ?? program.id, scholarshipId }),
    });
  };

  return (
    <main className="page-container financial-page is-empty">
      <h1 className="page-title">Financial Feasibility</h1>
      <p className="page-subtitle">Review study costs, scholarship support, and your personal budget.</p>
      <section className="fin-card fin-empty" aria-labelledby="financial-picker-title">
        <span className="fin-empty-icon" aria-hidden="true"><PiggyBank size={30} /></span>
        <h2 id="financial-picker-title">Select a Master’s program</h2>
        <p>
          {scholarshipId != null
            ? 'A scholarship is checked against a program’s costs. Choose the program you would study.'
            : 'Choose a program to compare its costs with your budget. You can add a scholarship afterwards.'}
        </p>
        {state.status === 'loading' && <p className="fin-summary-empty" role="status"><Loader2 size={22} className="fin-spin" aria-hidden="true" /> Loading programs…</p>}
        {state.status === 'error' && (
          <>
            <p className="fin-form-error" role="alert">Programs could not be loaded right now.</p>
            <button type="button" className="btn btn-primary" onClick={() => { setState({ status: 'loading', programs: [] }); setAttempt((value) => value + 1); }}>Try again</button>
          </>
        )}
        {state.status === 'ready' && state.programs.length === 0 && <p>No programs are available yet.</p>}
        {state.status === 'ready' && state.programs.length > 0 && (
          <ul className="fin-picker-list">
            {state.programs.map((program) => (
              <li key={program.id}>
                <button type="button" onClick={() => choose(program)}>
                  <strong>{getOpportunityTitle(program)}</strong>
                  <span>{[program.university, program.country].filter(Boolean).join(' · ')}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="btn btn-outline" onClick={() => navigate('/recommendations')}>Browse recommendations</button>
      </section>
    </main>
  );
}

export default function FinancialFeasibility() {
  const { activeOpportunity, selectedOpportunities } = useProfile();
  const routeState = useLocation().state;
  const [planState, setPlanState] = useState({ plan: null, error: '' });
  const [attempt, setAttempt] = useState(0);
  const [lookup, setLookup] = useState({ programId: null, program: null, error: false });
  const [lookupAttempt, setLookupAttempt] = useState(0);

  const selection = resolveFinancialSelection({ routeState, activeOpportunity, selectedOpportunities });
  const needsLookup = Boolean(selection.programId) && !selection.program;

  // The program may not be in the saved selection (e.g. opened from a card); load it from the backend
  useEffect(() => {
    if (!needsLookup) return undefined;
    let isCurrent = true;
    apiService.getUniversityById(selection.programId)
      .then((program) => { if (isCurrent) setLookup({ programId: selection.programId, program, error: !program }); })
      .catch((error) => {
        console.error('Unable to load the selected program.', error);
        if (isCurrent) setLookup({ programId: selection.programId, program: null, error: true });
      });
    return () => { isCurrent = false; };
  }, [needsLookup, selection.programId, lookupAttempt]);

  useEffect(() => {
    let isCurrent = true;
    apiService.getFinancialPlan()
      .then((plan) => { if (isCurrent) setPlanState({ plan, error: '' }); })
      .catch((error) => {
        console.error('Unable to load the financial plan.', error);
        if (isCurrent) setPlanState({ plan: null, error: getApiErrorMessage(error) });
      });
    return () => { isCurrent = false; };
  }, [attempt]);

  const loaded = lookup.programId === selection.programId ? lookup : null;
  const program = selection.program || (loaded?.program ? { ...loaded.program, kind: 'program' } : null);
  const stateKey = JSON.stringify([selection.programId, selection.scholarshipId]);

  if (planState.error) {
    return (
      <main className="page-container financial-page">
        <h1 className="page-title">Financial Feasibility</h1>
        <section className="fin-card fin-empty" role="alert">
          <span className="fin-empty-icon" aria-hidden="true"><AlertTriangle size={30} /></span>
          <h2>Your financial plan could not be loaded</h2>
          <p>{planState.error}</p>
          <button className="btn btn-primary" onClick={() => { setPlanState({ plan: null, error: '' }); setAttempt((value) => value + 1); }}>Try again</button>
        </section>
      </main>
    );
  }
  if (!planState.plan) {
    return (
      <main className="page-container financial-page">
        <h1 className="page-title">Financial Feasibility</h1>
        <p className="fin-summary-empty" role="status"><Loader2 size={22} className="fin-spin" aria-hidden="true" /> Loading your financial plan…</p>
      </main>
    );
  }
  if (!selection.programId) {
    return <ProgramPicker scholarshipId={selection.scholarshipId} />;
  }
  if (needsLookup && !program) {
    if (loaded?.error) {
      return (
        <main className="page-container financial-page">
          <h1 className="page-title">Financial Feasibility</h1>
          <section className="fin-card fin-empty" role="alert">
            <span className="fin-empty-icon" aria-hidden="true"><AlertTriangle size={30} /></span>
            <h2>The selected program could not be loaded</h2>
            <p>It may no longer be available, or the connection failed.</p>
            <button className="btn btn-primary" onClick={() => { setLookup({ programId: null, program: null, error: false }); setLookupAttempt((value) => value + 1); }}>Try again</button>
          </section>
        </main>
      );
    }
    return (
      <main className="page-container financial-page">
        <h1 className="page-title">Financial Feasibility</h1>
        <p className="fin-summary-empty" role="status"><Loader2 size={22} className="fin-spin" aria-hidden="true" /> Loading the selected program…</p>
      </main>
    );
  }
  return (
    <FinancialFeasibilityContent
      key={stateKey}
      initialPlan={planState.plan}
      program={program}
      initialScholarshipId={selection.scholarshipId}
    />
  );
}

function FinancialFeasibilityContent({ initialPlan, program, initialScholarshipId }) {
  const programId = getBackendProgramId(program);
  const supported = initialPlan.supported_currencies;
  const defaultCurrency = initialPlan.budget?.currency
    || (supported.includes(program?.tuitionCurrency) ? program.tuitionCurrency : 'EUR');

  const [plan, setPlan] = useState(initialPlan);
  const [currency, setCurrency] = useState(defaultCurrency);
  const [budgetAmount, setBudgetAmount] = useState(initialPlan.budget ? String(initialPlan.budget.amount) : '');
  const [drafts, setDrafts] = useState(() => Object.fromEntries(
    Object.entries(initialPlan.expenses?.[String(programId)] || {})
      .filter(([, row]) => row)
      .map(([category, row]) => [category, { amount: String(row.amount), currency: row.currency, period: row.period }]),
  ));
  const [scholarshipId, setScholarshipId] = useState(initialScholarshipId);
  const [scholarships, setScholarships] = useState([]);
  const [saveState, setSaveState] = useState({ saving: false, saved: false, error: '' });
  // key = the payload the stored result or error belongs to
  const [apiResponse, setApiResponse] = useState({ key: '', result: null, error: '' });

  useEffect(() => {
    if (!programId) return undefined;
    let isCurrent = true;
    const country = String(program?.country || '').toLowerCase();
    apiService.getMatchedScholarships()
      .then((items) => {
        if (!isCurrent) return;
        // Only scholarships for study in the program's country; the backend still checks
        // university-specific ones and explains when a scholarship can't be counted
        setScholarships(items.filter((item) => {
          const target = String(item.country || '').toLowerCase();
          if (initialScholarshipId != null && item._numericId === initialScholarshipId) return true;
          return Boolean(country) && target.includes(country) && !target.startsWith('european union');
        }));
      })
      .catch((error) => console.error('Unable to load scholarships for the financial planner.', error));
    return () => { isCurrent = false; };
  }, [programId, program?.country, initialScholarshipId]);

  const budgetIsValid = isValidAmount(budgetAmount);
  const expensePayload = useMemo(() => toExpensePayload(drafts), [drafts]);
  const invalidRow = Object.values(drafts).some((row) => row.amount !== '' && !isValidAmount(row.amount));
  const payloadKey = programId ? JSON.stringify({
    program_id: programId,
    scholarship_id: scholarshipId ?? null,
    currency,
    ...(budgetIsValid ? { budget: { amount: Number(budgetAmount), currency } } : {}),
    expenses: expensePayload,
  }) : '';

  // Recalculate shortly after anything changes; identical payloads never reach the backend twice
  useEffect(() => {
    if (!payloadKey) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      apiService.calculateFinancialFeasibility(JSON.parse(payloadKey), { signal: controller.signal })
        .then((result) => setApiResponse({ key: payloadKey, result, error: '' }))
        .catch((error) => {
          if (error?.name === 'AbortError') return;
          console.error('Unable to calculate financial feasibility.', error);
          setApiResponse((current) => ({ key: payloadKey, result: current.result, error: getApiErrorMessage(error) }));
        });
    }, 400);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [payloadKey]);

  const savePlan = async (event) => {
    event.preventDefault();
    if (saveState.saving) return;
    if (!budgetIsValid) {
      setSaveState({ saving: false, saved: false, error: 'Enter a budget of zero or more.' });
      return;
    }
    setSaveState({ saving: true, saved: false, error: '' });
    try {
      let next = await apiService.saveFinancialBudget({ amount: Number(budgetAmount), currency });
      const savedExpenses = JSON.stringify(plan.expenses?.[String(programId)] || {});
      if (programId && JSON.stringify(expensePayload) !== savedExpenses) {
        next = await apiService.saveProgramExpenses(programId, expensePayload);
      }
      setPlan(next);
      setSaveState({ saving: false, saved: true, error: '' });
    } catch (error) {
      console.error('Unable to save the financial plan.', error);
      setSaveState({ saving: false, saved: false, error: getApiErrorMessage(error) });
    }
  };

  const isCurrentResponse = apiResponse.key === payloadKey;
  const apiState = {
    status: !isCurrentResponse ? 'loading' : apiResponse.error ? 'error' : 'ok',
    error: isCurrentResponse ? apiResponse.error : '',
  };
  const result = apiResponse.result?.program?.id === programId ? apiResponse.result : null;
  const lines = Object.fromEntries((result?.costs || []).map((line) => [line.category, line]));
  const formatMoney = (amount) => `${result?.currency || currency} ${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const logo = getUniversityLogo(program.university);
  const months = result?.duration_months ?? program.durationMonths;
  const usesOnlySources = result && result.missing_data.length === 0
    && result.costs.every((line) => line.amount == null || ['program_record', 'included'].includes(line.source));

  const updateRow = (category, line, change) => {
    setSaveState((current) => ({ ...current, saved: false }));
    setDrafts((current) => ({
      ...current,
      [category]: {
        amount: current[category]?.amount ?? String(line?.original_amount_max ?? line?.original_amount ?? ''),
        currency: current[category]?.currency || line?.original_currency || currency,
        period: current[category]?.period || line?.period || defaultPeriod(category),
        ...change,
      },
    }));
  };
  const resetRow = (category) => {
    setSaveState((current) => ({ ...current, saved: false }));
    setDrafts((current) => {
      const next = { ...current };
      delete next[category];
      return next;
    });
  };

  return (
    <main className="page-container financial-page">
      <h1 className="page-title">Financial Feasibility</h1>

      <section className="fin-hero" aria-label="Selected opportunity">
        <span className={`fin-hero-mark ${logo ? 'has-logo' : ''}`} aria-hidden="true">
          {logo ? <img src={logo} alt="" /> : <GraduationCap size={26} />}
        </span>
        <div className="fin-hero-copy">
          <span className="fin-hero-eyebrow">Planning costs for</span>
          <h2>{getOpportunityTitle(program)}</h2>
          <p>
            <MapPin size={14} aria-hidden="true" />
            {[program.university, program.country].filter(Boolean).join(' · ') || 'Country not provided'}
          </p>
          <div className="fin-hero-chips">
            <span><Clock size={13} aria-hidden="true" /> {months ? `${months} months` : 'Duration not provided'}</span>
            <span><Award size={13} aria-hidden="true" /> {result?.scholarship?.name || 'No scholarship selected'}</span>
          </div>
        </div>
        {result && (
          <span className={`fin-hero-badge ${usesOnlySources ? 'is-verified' : ''}`}>
            {usesOnlySources
              ? <><BadgeCheck size={14} aria-hidden="true" /> Costs from official sources</>
              : <><Info size={14} aria-hidden="true" /> {result.missing_data.length ? 'Some costs are missing' : 'Includes your own figures'}</>}
          </span>
        )}
      </section>

      <div className="fin-layout">
        <div className="fin-main">
          <section className="fin-card" aria-labelledby="financial-budget-title">
            <header className="fin-card-head">
              <span className="fin-step">1</span>
              <div>
                <h2 id="financial-budget-title">Your budget</h2>
                <p>Everything you can put towards the full study period.</p>
              </div>
            </header>
            <form className="fin-budget-form" onSubmit={savePlan}>
              <label className="fin-budget-amount">
                <span>Total available budget</span>
                <span className="fin-money-input">
                  <Wallet size={18} aria-hidden="true" />
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={budgetAmount}
                    onChange={(event) => {
                      setBudgetAmount(event.target.value);
                      setSaveState({ saving: false, saved: false, error: '' });
                    }}
                    placeholder="Enter your budget"
                  />
                  <em>{currency}</em>
                </span>
              </label>
              <label className="fin-budget-currency">
                <span>Currency</span>
                <select
                  value={currency}
                  onChange={(event) => {
                    setCurrency(event.target.value);
                    setSaveState({ saving: false, saved: false, error: '' });
                  }}
                >
                  {supported.map((code) => <option key={code} value={code}>{code}</option>)}
                </select>
              </label>
              <button type="submit" className="btn btn-primary" disabled={saveState.saving}>
                {saveState.saving ? 'Saving…' : 'Save plan'}
              </button>
              <label className="fin-budget-scholarship">
                <span>Scholarship</span>
                <select
                  value={scholarshipId ?? ''}
                  onChange={(event) => setScholarshipId(event.target.value ? Number(event.target.value) : null)}
                >
                  <option value="">No scholarship</option>
                  {scholarships.map((item) => (
                    <option key={item.id} value={item._numericId}>{item.name}</option>
                  ))}
                </select>
              </label>
              {saveState.saved && <span className="fin-form-success" role="status"><CheckCircle2 size={14} aria-hidden="true" /> Your plan is saved to your account.</span>}
              {saveState.error && <span className="fin-form-error" role="alert">{saveState.error}</span>}
            </form>
            <p className="fin-note">Changing the currency doesn’t convert your budget: the amount above is read in the chosen currency.</p>
          </section>

          <section className="fin-card" aria-labelledby="financial-cost-title">
            <header className="fin-card-head">
              <span className="fin-step">2</span>
              <div>
                <h2 id="financial-cost-title">Study costs</h2>
                <p>{months ? `Totals cover ${months} months.` : 'Totals can’t be calculated without the program duration.'} Enter your own figure for any cost.</p>
              </div>
            </header>
            <ul className="fin-cost-list">
              {COST_ROWS.map(({ category, label, icon: CostIcon, tone }) => {
                const line = lines[category];
                const draft = drafts[category];
                const isTuition = category === 'tuition';
                const fromRecord = line?.source === 'program_record' && !draft;
                const isIncluded = line?.source === 'included' && !draft;
                const isMissing = result && !draft && !isIncluded && line?.amount == null;
                const share = result?.total_estimated_cost && line?.amount != null
                  ? line.amount / result.total_estimated_cost * 100
                  : 0;
                const rowCurrency = draft?.currency || line?.original_currency || currency;
                const shownAmount = draft?.amount ?? line?.original_amount_max ?? line?.original_amount ?? '';
                return (
                  <li key={category} className={`fin-cost-row tone-${tone}`}>
                    <span className="fin-cost-icon" aria-hidden="true"><CostIcon size={18} /></span>
                    <div className="fin-cost-label">
                      <strong>{label}</strong>
                      {draft && <small className="is-record">Your figure</small>}
                      {fromRecord && !line.is_estimate && <small className="is-record">From program record</small>}
                      {fromRecord && line.is_estimate && <small>Published estimate</small>}
                      {isIncluded && <small className="is-record">{line.note}</small>}
                      {isMissing && <small className="is-missing">Missing · verify manually</small>}
                    </div>
                    <span className="fin-money-input is-compact">
                      <input
                        type="number"
                        aria-label={`${label} amount in ${rowCurrency}`}
                        min="0"
                        step="any"
                        value={shownAmount}
                        placeholder={isIncluded ? 'Included' : 'Amount'}
                        readOnly={isTuition}
                        disabled={isTuition}
                        onChange={(event) => updateRow(category, line, { amount: event.target.value })}
                      />
                      <em>{rowCurrency}</em>
                    </span>
                    <select
                      className="fin-period"
                      aria-label={`${label} cost period`}
                      value={draft?.period || line?.period || defaultPeriod(category)}
                      disabled={isTuition}
                      onChange={(event) => updateRow(category, line, { period: event.target.value })}
                    >
                      <option value="total">Study total</option>
                      <option value="yearly">Yearly</option>
                      <option value="semester">Per semester</option>
                      <option value="monthly">Monthly</option>
                    </select>
                    <strong className="fin-cost-total">{line?.amount != null ? formatMoney(line.amount) : result ? 'Unknown' : '—'}</strong>
                    <span className="fin-cost-share" aria-hidden="true"><span style={{ width: `${share}%` }} /></span>
                    {fromRecord && !isTuition && (
                      <p className="fin-cost-source">
                        {line.original_amount_max != null && <>{formatRecordRange(line)}; the upper end is used. </>}
                        {line.note && <>{line.note} </>}
                        {line.source_url
                          ? <a href={line.source_url} target="_blank" rel="noreferrer">{line.source_name || 'Source'}</a>
                          : line.source_name}
                        {line.last_verified && <> · checked {line.last_verified}</>}
                      </p>
                    )}
                    {draft && (
                      <button type="button" className="fin-cost-reset" onClick={() => resetRow(category)}>Remove my figure</button>
                    )}
                  </li>
                );
              })}
            </ul>
            {invalidRow && <p className="fin-form-error" role="alert">Rows with a negative or invalid amount are ignored.</p>}
            <p className="fin-note">Published estimates come from each university. Rows marked missing have no official figure; enter your own to include them.</p>
          </section>
        </div>

        <aside className="fin-card fin-summary" aria-labelledby="financial-result-title">
          <header className="fin-card-head">
            <span className="fin-step">3</span>
            <div>
              <h2 id="financial-result-title">Your result</h2>
              <p>Calculated by FitScholars from your plan and the program’s costs.</p>
            </div>
          </header>
          <BackendResult state={apiState} result={result} formatMoney={formatMoney} />
        </aside>
      </div>
    </main>
  );
}

/** Result panel driven by POST /financial-feasibility/calculate */
function BackendResult({ state, result, formatMoney }) {
  const { status, error } = state;
  if (!result) {
    if (status === 'error') {
      return <p className="fin-summary-empty is-error" role="alert"><AlertTriangle size={22} aria-hidden="true" /> {error}</p>;
    }
    return <p className="fin-summary-empty" role="status"><Loader2 size={22} className="fin-spin" aria-hidden="true" /> Calculating…</p>;
  }

  const display = STATUS_DISPLAY[result.status] || STATUS_DISPLAY.insufficient_data;
  const total = result.total_estimated_cost;
  const remaining = result.remaining_cost;
  const budget = result.budget.amount;
  const budgetUsed = remaining != null && budget != null ? Math.min(budget, remaining) : 0;
  const counted = result.funding.filter((line) => line.counted);
  const potential = result.funding.filter((line) => line.potential);
  const money = (value) => (value != null ? formatMoney(value) : 'Unknown');

  return (
    <div className={`fin-result ${status === 'loading' ? 'is-refreshing' : ''}`} aria-busy={status === 'loading'}>
      {status === 'error' && <p className="fin-result-error" role="alert"><AlertTriangle size={15} aria-hidden="true" /> {error} Showing the last result.</p>}
      <p className={`fin-status ${display.tone}`} role="status">
        <display.icon size={16} aria-hidden="true" /> {display.label}
      </p>

      {total != null && (
        <div
          className="financial-donut"
          role="img"
          aria-label={`Estimated costs ${formatMoney(total)}, budget used ${formatMoney(budgetUsed)}, scholarship coverage ${formatMoney(result.confirmed_funding)}`}
          style={{
            '--budget-share': `${total ? budgetUsed / total * 100 : 0}%`,
            '--funding-share': `${total ? result.confirmed_funding / total * 100 : 0}%`,
          }}
        >
          <span>Total costs</span>
          <strong>{formatMoney(total)}</strong>
        </div>
      )}

      <section className="fin-group" aria-label="Costs">
        <h3>Costs</h3>
        <ul className="fin-legend">
          <li><span /> Tuition fees <strong>{money(result.tuition_cost)}</strong></li>
          <li><span /> Living expenses <strong>{money(result.living_cost)}</strong></li>
          <li><span /> Other known costs <strong>{money(result.other_costs)}</strong></li>
          <li className="is-sum"><span /> Total estimated expenses <strong>{money(total)}</strong></li>
        </ul>
      </section>

      <section className="fin-group" aria-label="Funding and budget">
        <h3>Funding and budget</h3>
        <ul className="fin-legend">
          <li><span /> Scholarship coverage <strong>{formatMoney(result.confirmed_funding)}{result.coverage_percent != null ? ` · ${Math.round(result.coverage_percent)}%` : ''}</strong></li>
          <li className="is-sum"><span /> Remaining to pay <strong>{money(remaining)}</strong></li>
          <li><span /> Your budget <strong>{budget != null ? formatMoney(budget) : 'Not entered'}</strong></li>
          <li className="is-sum"><span /> {result.surplus ? 'Surplus' : 'Funding gap'} <strong>{money(result.funding_gap == null ? null : result.surplus || result.funding_gap)}</strong></li>
        </ul>
      </section>

      {result.explanation.map((line) => <p key={line} className="fin-explain">{line}</p>)}

      {counted.length > 0 && (
        <div className="fin-detail-list">
          <strong>Funding counted</strong>
          <ul>{counted.map((line) => <li key={line.label}>{line.label}: {formatMoney(line.amount)} <em>{line.reason}</em></li>)}</ul>
        </div>
      )}
      {potential.length > 0 && (
        <div className="fin-detail-list is-uncertain">
          <strong>Possible funding, not counted · {result.scholarship.match_label}</strong>
          <ul>{potential.map((line) => <li key={line.label}>{line.label}: {formatMoney(line.amount)}</li>)}</ul>
        </div>
      )}
      {result.scholarship?.match_outcome === 'confirmed' && (
        <p className="fin-explain">{result.scholarship.match_label}: {result.scholarship.match_explanation}</p>
      )}
      {result.missing_data.length > 0 && (
        <div className="fin-detail-list is-missing">
          <strong>Missing information</strong>
          <ul>{result.missing_data.map((line) => <li key={line}>{line}</li>)}</ul>
        </div>
      )}
      {result.uncertainties.length > 0 && (
        <div className="fin-detail-list is-uncertain">
          <strong>Uncertain or not counted</strong>
          <ul>{result.uncertainties.map((line) => <li key={line}>{line}</li>)}</ul>
        </div>
      )}
      <p className="fin-note">
        All amounts in {result.currency}.
        {result.exchange_rates.used && ` Converted with ${result.exchange_rates.source} of ${result.exchange_rates.date}.`}
        {result.exchange_rates.used && result.exchange_rates.stale && ' These rates are out of date.'}
      </p>
    </div>
  );
}
