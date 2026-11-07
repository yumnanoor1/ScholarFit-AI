import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Search } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { adminApi } from '../services/adminApi';
import { ISSUE_FILTERS } from '../services/adminScholarshipForm';
import './AdminScholarships.css';

const PAGE_SIZE = 25;
const SEVERITY_TONES = { high: 'danger', medium: 'warning', low: 'neutral' };
const TILES = [
  ['total', 'Total scholarships', ''], ['verified', 'Verified', ''], ['unverified', 'Unverified', 'unverified'], ['conflicting', 'Conflicting', 'conflict'],
  ['missing_official_source', 'No official source', 'missing_official_source'], ['incomplete_structured', 'Incomplete fields', 'attention'],
  ['needs_reverification', 'Need re-verification', 'stale_verification'], ['duplicates', 'Duplicates', 'duplicate'],
];

function RetryNotice({ message, onRetry }) {
  return (
    <p className="admin-notice is-error" role="alert">
      {message} <button type="button" className="admin-link" onClick={onRetry}>Try again</button>
    </p>
  );
}

function Duplicates({ token }) {
  const [pairs, setPairs] = useState(null);
  const [error, setError] = useState('');
  const [comparison, setComparison] = useState(null);
  const [note, setNote] = useState('');
  const [message, setMessage] = useState('');

  const load = useCallback(() => {
    adminApi.duplicates(token)
      .then((data) => { setPairs(data); setError(''); })
      .catch((failure) => setError(failure.message));
  }, [token]);
  useEffect(load, [load]);

  const open = (pair) => {
    setMessage('');
    adminApi.compare(token, pair.first_id, pair.second_id)
      .then((data) => setComparison({ ...data, pair }))
      .catch((failure) => setError(failure.message));
  };
  const decide = async (recordId, target) => {
    try {
      await adminApi.markDuplicate(token, recordId, { duplicate_of_id: target, note });
      setMessage(target ? `#${recordId} is now flagged as a duplicate of #${target}. Nothing was merged.` : `The duplicate flag on #${recordId} was cleared.`);
      setComparison(null);
      setNote('');
      load();
    } catch (failure) {
      setError(failure.message);
    }
  };

  if (error) return <RetryNotice message={error} onRetry={load} />;
  if (!pairs) return <p role="status">Loading duplicates...</p>;
  return (
    <section className="admin-card" aria-label="Duplicate review">
      <h2>Duplicate review</h2>
      <p className="admin-muted">Records are compared here and only flagged. Nothing is merged or deleted, and both keep their IDs and everything linked to them.</p>
      {message && <p className="admin-notice is-success" role="status">{message}</p>}
      {pairs.length === 0 && <p>No duplicates are flagged or suspected.</p>}
      <ul className="admin-list">
        {pairs.map((pair) => (
          <li key={`${pair.first_id}-${pair.second_id}`}>
            <span className={`program-status is-${pair.kind === 'flagged' ? 'warning' : 'neutral'}`}>{pair.kind === 'flagged' ? 'Flagged' : 'Suspected'}</span>
            <span>#{pair.first_id} {pair.first_name} · #{pair.second_id} {pair.second_name}</span>
            <button type="button" className="btn btn-outline" onClick={() => open(pair)}>Compare</button>
          </li>
        ))}
      </ul>
      {comparison && (
        <div className="admin-compare">
          <h3>{comparison.differences.length} differing fields</h3>
          <div className="admin-table-scroll">
            <table className="admin-table">
              <thead>
                <tr><th>Field</th><th>#{comparison.first.id}</th><th>#{comparison.second.id}</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Saved by students / internal links</td>
                  <td>{comparison.first_references.saved_by_students} / {comparison.first_references.internal_links}</td>
                  <td>{comparison.second_references.saved_by_students} / {comparison.second_references.internal_links}</td>
                </tr>
                {comparison.differences.map((item) => (
                  <tr key={item.field}><td>{item.field}</td><td>{JSON.stringify(item.first)}</td><td>{JSON.stringify(item.second)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <label className="admin-field">
            <span>Why (kept in the change history)</span>
            <input value={note} onChange={(event) => setNote(event.target.value)} />
          </label>
          <div className="admin-actions">
            <button type="button" className="btn btn-outline" disabled={note.trim().length < 5} onClick={() => decide(comparison.second.id, comparison.first.id)}>
              Flag #{comparison.second.id} as a duplicate of #{comparison.first.id}
            </button>
            {comparison.pair.kind === 'flagged' && (
              <button type="button" className="btn btn-outline" disabled={note.trim().length < 5} onClick={() => decide(comparison.second.id, null)}>Not a duplicate: clear the flag</button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export default function AdminScholarships() {
  const { token } = useAuth();
  const [tab, setTab] = useState('records');
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [verification, setVerification] = useState('');
  const [issue, setIssue] = useState('');
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(0);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let current = true;
    const query = new URLSearchParams({ skip: String(page * PAGE_SIZE), limit: String(PAGE_SIZE), archived: String(archived) });
    if (search.trim()) query.set('q', search.trim());
    if (verification) query.set('verification', verification);
    if (issue) query.set('issue', issue);
    Promise.all([adminApi.summary(token), adminApi.list(token, query.toString())])
      .then(([counts, list]) => { if (current) { setSummary(counts); setRows(list); setError(''); } })
      .catch((failure) => { if (current) setError(failure.message); });
    return () => { current = false; };
  }, [token, search, verification, issue, archived, page, retry]);

  const change = (setter) => (value) => { setter(value); setPage(0); };

  return (
    <div className="page-container admin-page">
      <header className="admin-header">
        <div>
          <h1>Scholarship administration</h1>
          <p className="admin-muted">Keep scholarship records accurate. Changes here reach students straight away.</p>
        </div>
        <Link className="btn btn-primary" to="/admin/scholarships/new"><Plus size={16} aria-hidden="true" /> Add scholarship</Link>
      </header>

      {summary && (
        <section className="admin-tiles" aria-label="Catalog summary">
          {TILES.map(([key, label, filter]) => (
            <button type="button" key={key} className="admin-tile" onClick={() => { setTab('records'); change(setIssue)(filter); }}>
              <strong>{summary[key]}</strong><span>{label}</span>
            </button>
          ))}
          <div className="admin-tile">
            <strong>{summary.sources_checked ? summary.broken_sources : '-'}</strong>
            <span>{summary.sources_checked ? `Broken links (${summary.sources_checked} checked)` : 'Broken links: none checked yet'}</span>
          </div>
        </section>
      )}

      <div className="admin-tabs" role="group" aria-label="Administration sections">
        <button type="button" aria-pressed={tab === 'records'} onClick={() => setTab('records')}>Records</button>
        <button type="button" aria-pressed={tab === 'duplicates'} onClick={() => setTab('duplicates')}>Duplicates</button>
      </div>

      {tab === 'duplicates' ? <Duplicates token={token} /> : (
        <section className="admin-card" aria-label="Scholarship records">
          <div className="admin-filters">
            <label className="admin-search">
              <Search size={15} aria-hidden="true" />
              <input type="search" value={search} onChange={(event) => change(setSearch)(event.target.value)} placeholder="Name, provider or country" aria-label="Search records" />
            </label>
            <select value={verification} onChange={(event) => change(setVerification)(event.target.value)} aria-label="Filter by verification">
              <option value="">Any verification</option><option value="verified">Verified</option><option value="unverified">Unverified</option>
            </select>
            <select value={issue} onChange={(event) => change(setIssue)(event.target.value)} aria-label="Filter by issue">
              {ISSUE_FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <label className="admin-check">
              <input type="checkbox" checked={archived} onChange={(event) => change(setArchived)(event.target.checked)} /> Archived
            </label>
          </div>
          {error && <RetryNotice message={error} onRetry={() => setRetry((value) => value + 1)} />}
          {!rows && !error && <p role="status">Loading records...</p>}
          {rows && (
            <>
              <p className="admin-muted" role="status">{rows.total} record{rows.total === 1 ? '' : 's'}</p>
              {rows.total === 0 && <p>No records match these filters.</p>}
              <div className="admin-table-scroll">
                <table className="admin-table">
                  <thead><tr><th>ID</th><th>Scholarship</th><th>Host</th><th>Verification</th><th>Needs attention</th></tr></thead>
                  <tbody>
                    {rows.items.map((row) => (
                      <tr key={row.id}>
                        <td>{row.id}</td>
                        <td><Link to={`/admin/scholarships/${row.id}`}>{row.name}</Link><small>{row.provider}</small></td>
                        <td>{row.country?.replace(/\s*\(.*\)\s*$/, '')}</td>
                        <td>
                          <span className={`program-status is-${row.verification_status === 'verified' ? 'success' : 'neutral'}`}>{row.verification_status}</span>
                          <small>{row.last_verified_date || 'No date'}</small>
                        </td>
                        <td className="admin-issues">
                          {row.issues.slice(0, 3).map((item) => <span key={`${item.code}-${item.detail}`} className={`program-status is-${SEVERITY_TONES[item.severity]}`}>{item.label}</span>)}
                          {row.issues.length > 3 && <small>+{row.issues.length - 3} more</small>}
                          {row.issues.length === 0 && <small>Nothing found</small>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {rows.total > PAGE_SIZE && (
                <nav className="admin-actions" aria-label="Record pages">
                  <button type="button" className="btn btn-outline" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>Previous</button>
                  <span>Page {page + 1} of {Math.ceil(rows.total / PAGE_SIZE)}</span>
                  <button type="button" className="btn btn-outline" disabled={(page + 1) * PAGE_SIZE >= rows.total} onClick={() => setPage((value) => value + 1)}>Next</button>
                </nav>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
}
