import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, ArrowRight, RefreshCw } from 'lucide-react';
import { adminApi } from '../services/adminApi';
import {
  buildPublicationLifecyclePayload,
  getPublicationSummary,
  getPublicationVersionDetails,
} from '../services/adminPublicationState.js';
import { createLatestRequestGuard } from '../services/discoveryReviewState.js';

const PAGE_SIZE = 25;
const PUBLICATION_STATUSES = ['published', 'expired', 'withdrawn', 'revoked', 'superseded'];
const LIFECYCLE_ACTIONS = ['revoke', 'expire', 'withdraw', 'supersede'];
const LIFECYCLE_LABELS = {
  revoke: 'Revoke',
  expire: 'Expire',
  withdraw: 'Withdraw',
  supersede: 'Supersede',
};

function formatPublicationDate(value) {
  if (!value) return 'Not recorded';
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp)
    ? value
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp);
}

function PublicationVersion({ version, current }) {
  const details = getPublicationVersionDetails(version);
  return (
    <details className="admin-publication-version">
      <summary>
        Version {version.version_number}{current ? ' · Current' : ''}
        {' · '}{version.approval_decision.replace(/_/g, ' ')}
        {' · '}{formatPublicationDate(version.approved_at)}
      </summary>
      <dl className="admin-review-detail-fields">
        <div><dt>Review candidate</dt><dd>#{details.reviewItemId} · {details.candidateName || 'Unnamed candidate'}</dd></div>
        <div><dt>Host country</dt><dd>{details.hostCountry || 'Not recorded'}</dd></div>
        <div><dt>Reviewer</dt><dd>{details.reviewer}</dd></div>
        <div><dt>Decision time</dt><dd>{formatPublicationDate(details.approvedAt)}</dd></div>
      </dl>
      <h3>Approved scholarship values</h3>
      <pre className="admin-discovery-json">{JSON.stringify(details.approvedValues, null, 2)}</pre>
      <h3>Approved source evidence</h3>
      {details.sourceEvidence.length
        ? details.sourceEvidence.map((source, index) => (
          <section className="admin-import-evidence" key={`${source.source_id || 'source'}-${index}`}>
            <p>
              <strong>{source.source_name || source.source_id || 'Source'}</strong>
              {source.source_classification && ` · ${source.source_classification.replace(/_/g, ' ')}`}
            </p>
            {source.source_url && (
              <p><a href={source.source_url} target="_blank" rel="noreferrer">{source.source_url}</a></p>
            )}
            {source.trust_basis && <p><strong>Trust basis:</strong> {source.trust_basis}</p>}
            <pre className="admin-discovery-json">{JSON.stringify(source, null, 2)}</pre>
          </section>
        ))
        : <p className="admin-muted">No source evidence was recorded for this version.</p>}
    </details>
  );
}

export default function AdminScholarshipPublications({ token }) {
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState('');
  const [events, setEvents] = useState(null);
  const [eventsError, setEventsError] = useState('');
  const [listError, setListError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [decision, setDecision] = useState('');
  const [reason, setReason] = useState('');
  const [successorId, setSuccessorId] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [eventsRefresh, setEventsRefresh] = useState(0);
  const [listGuard] = useState(createLatestRequestGuard);
  const [eventsGuard] = useState(createLatestRequestGuard);

  const load = useCallback(() => {
    const requestId = listGuard.begin();
    return adminApi.discoveryPublications(token, {
      status: status || undefined,
      skip: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    })
      .then((data) => {
        if (listGuard.isCurrent(requestId)) {
          setResult(data);
          setListError('');
          setLoading(false);
        }
      })
      .catch((failure) => {
        if (listGuard.isCurrent(requestId)) {
          setListError(failure.message);
          setLoading(false);
        }
      });
  }, [listGuard, page, status, token]);

  useEffect(() => {
    load();
    return () => listGuard.invalidate();
  }, [load, listGuard, refresh]);

  const selected = result?.items.find((item) => item.id === selectedId) || null;
  useEffect(() => {
    if (!selectedId) return undefined;
    const requestId = eventsGuard.begin();
    adminApi.discoveryPublicationEvents(token, selectedId, 0, 100)
      .then((data) => {
        if (eventsGuard.isCurrent(requestId)) {
          setEvents(data);
          setEventsLoading(false);
        }
      })
      .catch((failure) => {
        if (eventsGuard.isCurrent(requestId)) {
          setEventsError(failure.message);
          setEventsLoading(false);
        }
      });
    return () => eventsGuard.invalidate();
  }, [eventsGuard, eventsRefresh, selectedId, token]);

  const retry = () => {
    listGuard.invalidate();
    setListError('');
    setLoading(true);
    setRefresh((value) => value + 1);
  };

  const selectPublication = (id) => {
    setSelectedId(id);
    setEvents(null);
    setEventsError('');
    setEventsLoading(Boolean(id));
    setActionError('');
    setNotice('');
    setDecision('');
    setReason('');
    setSuccessorId('');
  };

  const applyLifecycleAction = async () => {
    if (!selected || saving) return;
    let payload;
    try {
      payload = buildPublicationLifecyclePayload(decision, reason, successorId);
    } catch (failure) {
      setActionError(failure.message);
      return;
    }
    setSaving(true);
    setActionError('');
    setNotice('');
    try {
      const updated = await adminApi.transitionDiscoveryPublication(token, selected.id, payload);
      setNotice(`Publication status updated to ${updated.status}.`);
      setStatus('');
      setPage(0);
      setLoading(true);
      setDecision('');
      setReason('');
      setSuccessorId('');
      setRefresh((value) => value + 1);
      setEventsLoading(true);
      setEventsRefresh((value) => value + 1);
    } catch (failure) {
      setActionError(failure.message);
    } finally {
      setSaving(false);
    }
  };

  const changePage = (nextPage) => {
    setLoading(true);
    setSelectedId('');
    setEvents(null);
    setEventsError('');
    setEventsLoading(false);
    setPage(nextPage);
  };

  const items = result?.items || [];
  const total = result?.total || 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);
  const selectedSummary = selected ? getPublicationSummary(selected) : null;

  return (
    <div className="admin-publications-page">
      <header className="admin-publications-header">
        <div>
          <h1>Discovery Publications</h1>
          <p>Inspect approved discovery snapshots, source evidence, freshness, and publication history.</p>
        </div>
        <Link className="admin-link" to="/admin/scholarships?section=reviews">
          <ArrowLeft size={15} aria-hidden="true" /> Review queue
        </Link>
      </header>

      {notice && <p className="admin-notice is-success" role="status">{notice}</p>}
      {listError && (
        <p className="admin-notice is-error" role="alert">
          {listError} <button type="button" className="admin-link" onClick={retry}>Try again</button>
        </p>
      )}
      {loading && result && <p role="status">Refreshing publications…</p>}

      <section className="admin-card" aria-label="Discovery publication list">
        <div className="admin-publications-toolbar">
          <label className="admin-field">
            <span>Publication status</span>
            <select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(0);
                setSelectedId('');
                setEvents(null);
                setEventsError('');
                setEventsLoading(false);
                setLoading(true);
              }}
            >
              <option value="">All statuses</option>
              {PUBLICATION_STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <button type="button" className="btn btn-outline" onClick={retry} disabled={loading}>
            <RefreshCw size={15} aria-hidden="true" /> Refresh
          </button>
          <span className="admin-muted">{total} publication{total === 1 ? '' : 's'}</span>
        </div>
        <div className="admin-table-scroll">
          <table className="admin-table admin-publications-table">
            <thead>
              <tr>
                <th>Scholarship</th><th>Status</th><th>Approved version</th><th>Review candidate</th>
                <th>Sources / freshness</th><th>Created</th><th>Updated</th><th>Inspect</th>
              </tr>
            </thead>
            <tbody>
              {loading && !result && (
                <tr><td colSpan="8" role="status">Loading publications…</td></tr>
              )}
              {!loading && !listError && items.length === 0 && (
                <tr><td colSpan="8">No discovery publications match this status.</td></tr>
              )}
              {items.map((publication) => {
                const summary = getPublicationSummary(publication);
                return (
                  <tr key={publication.id} className={selectedId === publication.id ? 'is-selected' : ''}>
                    <td>
                      <strong>{summary.title}</strong>
                      <small>Publication {publication.id}</small>
                      <small>
                        Canonical <Link to={`/admin/scholarships/${publication.canonical_scholarship_id}`}>
                          #{publication.canonical_scholarship_id}
                        </Link>
                      </small>
                    </td>
                    <td><span className={`admin-verification-badge is-${publication.status}`}>{publication.status}</span></td>
                    <td>{summary.versionNumber ? `Version ${summary.versionNumber}` : 'None'}</td>
                    <td>{summary.reviewItemId ? `#${summary.reviewItemId} · ${publication.current_version?.candidate_name_at_approval || 'Candidate'}` : 'Not recorded'}</td>
                    <td>
                      {summary.sourceNames.length
                        ? summary.sourceNames.join(', ')
                        : 'No sources recorded'}
                      <small>Last checked: {formatPublicationDate(summary.lastCheckedAt)}</small>
                    </td>
                    <td>{formatPublicationDate(summary.createdAt)}</td>
                    <td>{formatPublicationDate(summary.updatedAt)}</td>
                    <td>
                      <button
                        type="button"
                        className="admin-link"
                        aria-pressed={selectedId === publication.id}
                        onClick={() => selectPublication(publication.id)}
                      >
                        {selectedId === publication.id ? 'Selected' : 'Inspect'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {pageCount > 1 && (
          <nav className="admin-publications-pagination" aria-label="Publication pages">
            <button type="button" className="btn btn-outline" disabled={page === 0 || loading} onClick={() => changePage(page - 1)}>
              <ArrowLeft size={15} aria-hidden="true" /> Previous
            </button>
            <span>Page {page + 1} of {pageCount}</span>
            <button type="button" className="btn btn-outline" disabled={page + 1 >= pageCount || loading} onClick={() => changePage(page + 1)}>
              Next <ArrowRight size={15} aria-hidden="true" />
            </button>
          </nav>
        )}
      </section>

      {selected && selectedSummary && (
        <section className="admin-card admin-publication-inspection" aria-label={`Publication ${selected.id} inspection`}>
          <header className="admin-publication-inspection-header">
            <div>
              <h2>{selectedSummary.title}</h2>
              <p className="admin-muted">
                Publication {selected.id} · Canonical scholarship{' '}
                <Link to={`/admin/scholarships/${selected.canonical_scholarship_id}`}>
                  #{selected.canonical_scholarship_id}
                </Link>
              </p>
            </div>
            <span className={`admin-verification-badge is-${selected.status}`}>{selected.status}</span>
          </header>

          <dl className="admin-review-detail-fields">
            <div><dt>Created</dt><dd>{formatPublicationDate(selected.created_at)}</dd></div>
            <div><dt>Updated</dt><dd>{formatPublicationDate(selected.updated_at)}</dd></div>
            <div><dt>Published</dt><dd>{formatPublicationDate(selected.published_at)}</dd></div>
            <div><dt>Revoked</dt><dd>{formatPublicationDate(selected.revoked_at)}</dd></div>
            <div><dt>Revoked by</dt><dd>{selected.revoked_by_email || '—'}</dd></div>
            <div><dt>Revocation reason</dt><dd>{selected.revocation_reason || '—'}</dd></div>
            <div><dt>Successor publication</dt><dd>{selected.superseded_by_publication_id || '—'}</dd></div>
          </dl>

          <h3>Publication sources and freshness</h3>
          {selected.sources?.length
            ? <div className="admin-table-scroll">
              <table className="admin-table admin-publication-sources">
                <thead><tr><th>Source</th><th>Classification</th><th>Trust basis</th><th>URL</th><th>Check status</th><th>Last checked</th><th>Last successful</th></tr></thead>
                <tbody>{selected.sources.map((source) => (
                  <tr key={source.id}>
                    <td>{source.source_name}<small>{source.source_id}</small></td>
                    <td>{source.source_classification.replace(/_/g, ' ')}</td>
                    <td>{source.source_trust_basis || '—'}</td>
                    <td><a href={source.source_url} target="_blank" rel="noreferrer">{source.source_url}</a></td>
                    <td>{source.source_check_status}</td>
                    <td>{formatPublicationDate(source.last_checked_at)}</td>
                    <td>{formatPublicationDate(source.last_successful_check_at)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            : <p className="admin-muted">No publication sources were recorded.</p>}

          <h3>Approved version history</h3>
          {selected.versions?.length
            ? selected.versions.map((version) => (
              <PublicationVersion
                key={version.id}
                version={version}
                current={version.id === selected.current_version_id}
              />
            ))
            : <p className="admin-muted">No approved versions were recorded.</p>}

          <h3>Lifecycle event history</h3>
          {eventsLoading && <p role="status">Loading lifecycle events…</p>}
          {eventsError && (
            <p className="admin-notice is-error" role="alert">
              {eventsError} <button type="button" className="admin-link" onClick={() => { setEventsError(''); setEventsLoading(true); setEventsRefresh((value) => value + 1); }}>Try again</button>
            </p>
          )}
          {!eventsLoading && !eventsError && events?.items.length === 0 && (
            <p className="admin-muted">No lifecycle events were recorded.</p>
          )}
          {events?.items.map((event) => (
            <article className="admin-publication-event" key={event.id}>
              <strong>{event.event_type.replace(/_/g, ' ')}</strong>
              <span>{formatPublicationDate(event.created_at)}</span>
              <span>{event.actor_email || 'System'}</span>
              {event.reason && <p>{event.reason}</p>}
              {Object.keys(event.event_data || {}).length > 0 && (
                <pre className="admin-discovery-json">{JSON.stringify(event.event_data, null, 2)}</pre>
              )}
            </article>
          ))}

          <h3>Manage lifecycle</h3>
          {selected.status !== 'published'
            ? <p className="admin-muted">Lifecycle transitions are only available for currently published records.</p>
            : <div className="admin-publication-lifecycle">
              <label className="admin-field">
                <span>Action</span>
                <select value={decision} onChange={(event) => setDecision(event.target.value)} disabled={saving}>
                  <option value="">Choose action</option>
                  {LIFECYCLE_ACTIONS.map((action) => (
                    <option key={action} value={action}>{LIFECYCLE_LABELS[action]}</option>
                  ))}
                </select>
              </label>
              {decision === 'supersede' && (
                <label className="admin-field">
                  <span>Successor publication ID</span>
                  <input value={successorId} onChange={(event) => setSuccessorId(event.target.value)} disabled={saving} />
                  <small>Enter the ID of another currently published discovery. The backend verifies it.</small>
                </label>
              )}
              <label className="admin-field admin-field-is-wide">
                <span>Reason</span>
                <textarea rows="3" maxLength="2000" value={reason} onChange={(event) => setReason(event.target.value)} disabled={saving} />
              </label>
              {actionError && <p className="admin-notice is-error" role="alert">{actionError}</p>}
              <button
                type="button"
                className="btn btn-primary"
                disabled={saving || !decision || !reason.trim() || (decision === 'supersede' && successorId.trim().length !== 36)}
                onClick={applyLifecycleAction}
              >
                {saving ? 'Saving…' : `Apply ${decision ? LIFECYCLE_LABELS[decision].toLowerCase() : 'lifecycle action'}`}
              </button>
            </div>}
        </section>
      )}
    </div>
  );
}
