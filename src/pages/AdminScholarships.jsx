import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Activity, ArrowLeft, ArrowRight, BookOpen, CircleCheck, Clock3, Globe2, ListChecks, Plus, Radar, Search, ShieldAlert,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { adminApi } from '../services/adminApi';
import {
  formatDiscoverySourceFailure,
  formatDiscoveryWorkerError,
  getDiscoveryWorkerStatusLabel,
  isDiscoveryWorkerActive,
} from '../services/discoveryMonitoringState.js';
import AdminScholarshipPublications from './AdminScholarshipPublications.jsx';
import {
  buildReviewDecisionPayload,
  createActionGuard,
  createLatestRequestGuard,
  getDiscoveryCandidateCounts,
  getReviewDecisionAnnouncement,
  getReviewQueueViewState,
} from '../services/discoveryReviewState.js';
import { ISSUE_FILTERS } from '../services/adminScholarshipForm';
import './AdminScholarships.css';

const PAGE_SIZE = 25;

function RetryNotice({ message, onRetry }) {
  return (
    <p className="admin-notice is-error" role="alert">
      {message} <button type="button" className="admin-link" onClick={onRetry}>Try again</button>
    </p>
  );
}

function Duplicates({ token }) {
  const [pairs, setPairs] = useState(null);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [selectedPair, setSelectedPair] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [note, setNote] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [compareError, setCompareError] = useState('');
  const [loading, setLoading] = useState(true);
  const [compareLoading, setCompareLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [listGuard] = useState(createLatestRequestGuard);
  const [compareGuard] = useState(createLatestRequestGuard);

  const load = useCallback(() => {
    const requestId = listGuard.begin();
    adminApi.duplicates(token)
      .then((data) => {
        if (listGuard.isCurrent(requestId)) {
          setPairs(data);
          setLoading(false);
        }
      })
      .catch((failure) => {
        if (listGuard.isCurrent(requestId)) {
          setError(failure.message);
          setLoading(false);
        }
      });
  }, [listGuard, token]);

  useEffect(() => {
    load();
    return () => {
      listGuard.invalidate();
      compareGuard.invalidate();
    };
  }, [compareGuard, listGuard, load, refresh]);

  const open = (pair) => {
    setMessage('');
    setSelectedPair(pair);
    setComparison(null);
    setCompareError('');
    setCompareLoading(true);
    const requestId = compareGuard.begin();
    adminApi.compare(token, pair.first_id, pair.second_id)
      .then((data) => {
        if (compareGuard.isCurrent(requestId)) {
          setComparison({ ...data, pair });
          setCompareLoading(false);
        }
      })
      .catch((failure) => {
        if (compareGuard.isCurrent(requestId)) {
          setCompareError(failure.message);
          setCompareLoading(false);
        }
      });
  };
  const decide = async (recordId, target) => {
    setSaving(true);
    setError('');
    setMessage('');
    try {
      await adminApi.markDuplicate(token, recordId, { duplicate_of_id: target, note });
      setMessage(target ? `#${recordId} is now flagged as a duplicate of #${target}. Nothing was merged.` : `The duplicate flag on #${recordId} was cleared.`);
      setSelectedPair(null);
      setComparison(null);
      setNote('');
      setPage(0);
      setRefresh((value) => value + 1);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setSaving(false);
    }
  };

  const filteredPairs = (pairs || []).filter((pair) => {
    const matchesFilter = filter === 'all'
      || (filter === 'needs_review' && pair.kind === 'suspected')
      || (filter === 'flagged' && pair.kind === 'flagged');
    const query = search.trim().toLowerCase();
    const matchesSearch = !query || `${pair.first_name} ${pair.second_name}`.toLowerCase().includes(query);
    return matchesFilter && matchesSearch;
  });
  const pageCount = Math.ceil(filteredPairs.length / 10);
  const pagePairs = filteredPairs.slice(page * 10, (page + 1) * 10);
  const differenceFields = new Set((comparison?.differences || []).map((difference) => difference.field));
  const comparisonFields = [
    { label: 'Scholarship name', key: 'name' },
    { label: 'Provider', key: 'provider' },
    { label: 'Country', key: 'country' },
    { label: 'Deadline', key: 'deadline' },
    {
      label: 'Award amount',
      key: 'stipend_amount',
      value: (record) => record.stipend_amount == null
        ? '—'
        : `${record.stipend_amount} ${record.stipend_currency || ''}`.trim(),
    },
    { label: 'Official source URL', key: 'official_info_url', value: (record) => record.official_info_url || record.official_url },
    { label: 'Verification status', key: 'verification_status' },
  ];
  const filters = [
    { value: 'all', label: 'All' },
    { value: 'needs_review', label: 'Needs review' },
    { value: 'flagged', label: 'Flagged' },
  ];

  return (
    <div className="admin-duplicates-page">
      <header className="admin-duplicates-header">
        <div>
          <h1>Duplicates</h1>
          <p>Find and review scholarship records that may describe the same award.</p>
        </div>
      </header>
      {message && <p className="admin-notice is-success" role="status">{message}</p>}
      {error && <RetryNotice message={error} onRetry={() => setRefresh((value) => value + 1)} />}
      <section className="admin-card admin-duplicates-list" aria-label="Duplicate candidates">
        <div className="admin-duplicates-toolbar">
          <div className="admin-duplicates-filters" role="group" aria-label="Filter duplicate records">
            {filters.map((item) => (
              <button
                type="button"
                key={item.value}
                className={filter === item.value ? 'is-selected' : ''}
                aria-pressed={filter === item.value}
                onClick={() => { setFilter(item.value); setPage(0); }}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="admin-duplicates-search">
            <Search size={15} aria-hidden="true" />
            <input value={search} onChange={(event) => { setSearch(event.target.value); setPage(0); }} placeholder="Search scholarship name" aria-label="Search duplicate candidates" />
          </label>
        </div>
        <div className="admin-table-scroll">
          <table className="admin-table admin-duplicates-table">
            <thead>
              <tr><th>Record A</th><th>Record B</th><th>Match</th><th>Reason</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {loading && !pairs && Array.from({ length: 5 }, (_, index) => (
                <tr key={`duplicate-skeleton-${index}`} className="admin-skeleton-row" aria-hidden="true">
                  <td><span className="admin-skeleton-line is-long" /></td>
                  <td><span className="admin-skeleton-line is-long" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                  <td><span className="admin-skeleton-line" /></td>
                  <td><span className="admin-skeleton-pill" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                </tr>
              ))}
              {pairs && !loading && pagePairs.map((pair) => (
                <tr key={`${pair.first_id}-${pair.second_id}`} className={selectedPair?.first_id === pair.first_id && selectedPair?.second_id === pair.second_id ? 'is-selected' : ''}>
                  <td><strong>#{pair.first_id}</strong><span>{pair.first_name}</span></td>
                  <td><strong>#{pair.second_id}</strong><span>{pair.second_name}</span></td>
                  <td>Not scored</td>
                  <td>{pair.kind === 'flagged' ? 'Manually flagged' : 'Similar name and country'}</td>
                  <td>
                    <span className={`admin-duplicate-status is-${pair.kind}`}>
                      {pair.kind === 'flagged' ? 'Flagged' : 'Needs review'}
                    </span>
                  </td>
                  <td><button type="button" className="admin-duplicate-compare" onClick={() => open(pair)}>Compare</button></td>
                </tr>
              ))}
              {pairs && !loading && pagePairs.length === 0 && (
                <tr><td className="admin-duplicates-empty" colSpan="6">No duplicate candidates match this filter.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="admin-duplicates-legend">
          <span>Status key:</span>
          <span className="admin-duplicate-status is-suspected">Needs review</span>
          <span className="admin-duplicate-status is-flagged">Flagged</span>
        </div>
        <footer className="admin-duplicates-pagination">
          <span>
            Showing {filteredPairs.length === 0 ? 0 : page * 10 + 1}–{Math.min((page + 1) * 10, filteredPairs.length)} of {filteredPairs.length}
          </span>
          <div>
            <button type="button" disabled={loading || page === 0} onClick={() => setPage((value) => value - 1)}>
              <ArrowLeft size={14} aria-hidden="true" /> Previous
            </button>
            <button type="button" disabled={loading || !pageCount || page + 1 >= pageCount} onClick={() => setPage((value) => value + 1)}>
              Next <ArrowRight size={14} aria-hidden="true" />
            </button>
          </div>
        </footer>
      </section>
      <section className="admin-card admin-duplicates-comparison" aria-label="Compare records">
        <h2>Compare records</h2>
        {!selectedPair && <p className="admin-duplicates-prompt">Select a pair above to compare it. Differences will be highlighted here.</p>}
        {compareLoading && <p className="admin-duplicates-prompt" role="status">Loading comparison...</p>}
        {compareError && <RetryNotice message={compareError} onRetry={() => selectedPair && open(selectedPair)} />}
        {comparison && (
          <>
            <div className="admin-table-scroll">
              <table className="admin-table admin-duplicates-compare-table">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Record A · #{comparison.first.id}</th>
                    <th>Record B · #{comparison.second.id}</th>
                  </tr>
                </thead>
                <tbody>
                  {comparisonFields.map((field) => (
                    <tr key={field.key} className={differenceFields.has(field.key) ? 'is-different' : ''}>
                      <th scope="row">{field.label}</th>
                      <td>{formatCandidateValue(field.value ? field.value(comparison.first) : comparison.first[field.key])}</td>
                      <td>{formatCandidateValue(field.value ? field.value(comparison.second) : comparison.second[field.key])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="admin-duplicates-reference-counts">
              <span>Saved by students: <strong>{comparison.first_references.saved_by_students}</strong> / <strong>{comparison.second_references.saved_by_students}</strong></span>
              <span>Internal links: <strong>{comparison.first_references.internal_links}</strong> / <strong>{comparison.second_references.internal_links}</strong></span>
            </div>
            <label className="admin-duplicates-note">
              <span>Why (kept in the change history)</span>
              <input value={note} maxLength={1000} onChange={(event) => setNote(event.target.value)} placeholder="Add a short reason (at least 5 characters)" />
            </label>
            <div className="admin-actions">
              <button
                type="button"
                className="btn btn-primary"
                disabled={saving || note.trim().length < 5 || (
                  comparison.second.duplicate_of_id != null
                  && comparison.second.duplicate_of_id !== comparison.first.id
                )}
                onClick={() => decide(comparison.second.id, comparison.first.id)}
                title={comparison.second.duplicate_of_id != null && comparison.second.duplicate_of_id !== comparison.first.id
                  ? 'Record B is already flagged as a duplicate of another record.'
                  : undefined}
              >
                {saving ? 'Saving...' : 'Flag Record B as duplicate of Record A'}
              </button>
              {comparison.pair.kind === 'flagged' && (
                <button type="button" className="btn btn-outline" disabled={saving || note.trim().length < 5} onClick={() => decide(comparison.second.id, null)}>
                  Keep both · clear duplicate flag
                </button>
              )}
            </div>
          </>
        )}
        <p className="admin-duplicates-safety-note">
          Flagging records does not merge or delete them. Both records and their linked data remain unchanged.
        </p>
      </section>
    </div>
  );
}

function formatCandidateValue(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.map(formatCandidateValue).join(', ');
  if (typeof value === 'object') {
    if (Object.prototype.hasOwnProperty.call(value, 'value')) return formatCandidateValue(value.value);
    return Object.entries(value).map(([key, entry]) => `${key.replace(/_/g, ' ')}: ${formatCandidateValue(entry)}`).join('; ');
  }
  return String(value);
}

function getCandidateEligibility(values) {
  const fields = [
    ['eligibility_criteria', 'Eligibility'],
    ['eligibility', 'Eligibility'],
    ['degree_level', 'Degree level'],
    ['field_of_study', 'Field'],
    ['nationality', 'Nationality'],
    ['min_gpa', 'Minimum GPA'],
    ['english_requirement_type', 'English requirement'],
  ].filter(([key]) => values?.[key] !== null && values?.[key] !== undefined && values[key] !== '');
  return fields.length
    ? fields.map(([key, label]) => `${label}: ${formatCandidateValue(values[key])}`).join(' · ')
    : 'Not recorded';
}

function DiscoveryReviewCard({ item, token, onDone, saving: bulkSaving = false }) {
  const [valuesText, setValuesText] = useState(() => JSON.stringify(item.extracted_values, null, 2));
  const [duplicateId, setDuplicateId] = useState('');
  const [linkTargetId, setLinkTargetId] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [actionGuard] = useState(createActionGuard);

  const decide = async (decision) => {
    if (actionGuard.isActive()) return;
    setError('');
    let values;
    if (decision === 'accepted' || decision === 'link_and_publish') {
      try {
        values = JSON.parse(valuesText);
        if (!values || typeof values !== 'object' || Array.isArray(values)) {
          throw new Error('Publication values must be a JSON object.');
        }
      } catch (failure) {
        setError(failure instanceof SyntaxError ? 'Fix the candidate JSON before publishing.' : failure.message);
        return;
      }
    }

    let payload;
    try {
      payload = buildReviewDecisionPayload(decision, {
        values,
        duplicateId,
        linkToScholarshipId: linkTargetId,
      });
    } catch (failure) {
      setError(failure.message);
      return;
    }

    if (!actionGuard.tryStart()) return;
    setSaving(true);
    try {
      const updatedItem = await adminApi.reviewDiscovery(token, item.id, payload);
      onDone(decision, updatedItem);
    } catch (failure) {
      setError(failure.message);
    } finally {
      actionGuard.finish();
      setSaving(false);
    }
  };

  return (
    <aside className="admin-card admin-review-details" aria-label="Candidate details">
      <header className="admin-review-details-header">
        <h2>Candidate details</h2>
        <span className={`admin-review-status is-${item.review_status}`}>
          {item.review_status.replace(/_/g, ' ')}
        </span>
      </header>
      <p className="admin-review-detail-intro">
        {item.candidate_name || item.extracted_values?.name || 'Unnamed scholarship'}
        {item.host_country ? ` · ${item.host_country}` : ''}
      </p>
      {error && <p className="admin-notice is-error" role="alert">{error}</p>}
      <dl className="admin-review-detail-fields">
        <div><dt>Name</dt><dd>{formatCandidateValue(item.extracted_values?.name || item.candidate_name)}</dd></div>
        <div><dt>Source URL</dt><dd><a href={item.source_url} target="_blank" rel="noreferrer">{item.source_url}</a></dd></div>
        <div><dt>Deadline</dt><dd>{formatCandidateValue(item.extracted_values?.deadline || item.extracted_values?.application_deadline || item.extracted_values?.deadline_type)}</dd></div>
        <div><dt>Award amount</dt><dd>{formatCandidateValue(
          item.extracted_values?.award_amount
          || item.extracted_values?.stipend_amount
          || item.extracted_values?.living_stipend
          || item.extracted_values?.funding_type,
        )}</dd></div>
        <div><dt>Eligibility</dt><dd>{getCandidateEligibility(item.extracted_values)}</dd></div>
        <div><dt>Confidence</dt><dd>{formatCandidateValue(item.extracted_values?.confidence)}</dd></div>
      </dl>
      <div className="admin-review-source-meta">
        <span>{item.source_name}</span>
        <span>{item.source_classification.replace(/_/g, ' ')}</span>
        <span>Discovered {formatRunTime(item.created_at)}</span>
      </div>
      {item.review_reason && <p className="admin-review-reason"><strong>Review note:</strong> {item.review_reason}</p>}
      {item.missing_required_fields.length > 0 && (
        <p className="admin-review-warning">Missing: {item.missing_required_fields.join(', ')}</p>
      )}
      {item.conflicting_values.length > 0 && (
        <details className="admin-review-evidence">
          <summary>{item.conflicting_values.length} conflicting field(s)</summary>
          <pre className="admin-discovery-json">{JSON.stringify(item.conflicting_values, null, 2)}</pre>
        </details>
      )}
      <details className="admin-review-evidence">
        <summary>Source evidence and field provenance</summary>
        {item.source_trust_basis && <p><strong>Trust basis:</strong> {item.source_trust_basis}</p>}
        <pre className="admin-discovery-json">{JSON.stringify(item.field_sources, null, 2)}</pre>
        {item.evidence_excerpts.map((source) => (
          <section key={source.fingerprint} className="admin-import-evidence">
            <p>
              <strong>{source.source_name}</strong> · {source.source_classification.replace(/_/g, ' ')}
              {' · '}<a href={source.source_url} target="_blank" rel="noreferrer">{source.source_url}</a>
            </p>
            <p><strong>Extracted values:</strong></p>
            <pre className="admin-discovery-json">{JSON.stringify(source.extracted_values, null, 2)}</pre>
            <p><strong>Evidence excerpts:</strong></p>
            <pre className="admin-discovery-json">{JSON.stringify(source.evidence_excerpts, null, 2)}</pre>
            {source.page_count && <p className="admin-muted">Page count: {source.page_count}; specific page references were not available.</p>}
          </section>
        ))}
      </details>
      {item.review_status === 'reviewed' && (
        <div className="admin-review-edit">
          <button type="button" className="admin-link" onClick={() => setEditing((value) => !value)}>
            {editing ? 'Hide extracted fields' : 'Edit extracted fields'}
          </button>
          {editing && (
            <label className="admin-field">
              <span>Values to use when publishing (JSON)</span>
              <textarea
                className="admin-discovery-json-input"
                rows={10}
                value={valuesText}
                onChange={(event) => setValuesText(event.target.value)}
                disabled={saving || bulkSaving}
              />
            </label>
          )}
        </div>
      )}
      {item.review_status === 'pending' && (
        <div className="admin-review-detail-actions">
          <button type="button" className="btn btn-primary" disabled={saving || bulkSaving} onClick={() => decide('reviewed')}>
            {saving ? 'Saving...' : 'Mark reviewed'}
          </button>
        </div>
      )}
      {item.review_status === 'reviewed' && (
        <div className="admin-review-detail-actions">
          <button type="button" className="btn btn-primary" disabled={saving || bulkSaving} onClick={() => decide('accepted')}>
            Approve as unverified
          </button>
          <button type="button" className="btn btn-outline" disabled={saving || bulkSaving} onClick={() => decide('rejected')}>
            Reject
          </button>
          <details className="admin-review-duplicate">
            <summary>Mark duplicate</summary>
            <label className="admin-field">
              <span>Existing scholarship ID</span>
              <input
                type="number"
                min="1"
                value={duplicateId}
                onChange={(event) => setDuplicateId(event.target.value)}
                disabled={saving || bulkSaving}
              />
            </label>
            <button type="button" className="btn btn-outline" disabled={saving || bulkSaving || !duplicateId} onClick={() => decide('duplicate')}>
              Confirm duplicate
            </button>
          </details>
          <div className="admin-review-link-publish">
            <label className="admin-field">
              <span>Existing scholarship ID to link</span>
              <input
                type="number"
                min="1"
                step="1"
                value={linkTargetId}
                onChange={(event) => setLinkTargetId(event.target.value)}
                disabled={saving || bulkSaving}
              />
              <small>Publication records the approved discovery snapshot; it does not overwrite canonical scholarship fields.</small>
            </label>
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving || bulkSaving || !linkTargetId}
              onClick={() => decide('link_and_publish')}
            >
              Publish and link existing scholarship
            </button>
          </div>
        </div>
      )}
      {item.review_status === 'accepted' && (
        <p className="admin-review-final-state">
          {item.accepted_scholarship_id
            ? `Created scholarship #${item.accepted_scholarship_id} as unverified.`
            : 'This candidate was accepted.'}
        </p>
      )}
      {item.review_status === 'rejected' && <p className="admin-review-final-state">This candidate was rejected.</p>}
      {item.review_status === 'duplicate' && (
        <p className="admin-review-final-state">
          {item.duplicate_of_scholarship_id
            ? `Linked as a duplicate of scholarship #${item.duplicate_of_scholarship_id}; no records were merged.`
            : 'This candidate was marked as a duplicate; no records were merged.'}
        </p>
      )}
      <p className="admin-review-run">Discovery run: {item.discovery_run_id}</p>
      <p className="admin-review-safety-note">Approval creates an unverified scholarship, while link-and-publish preserves the existing canonical fields and creates an approved discovery publication snapshot.</p>
    </aside>
  );
}

function DiscoveryReviewQueue({ token }) {
  const [status, setStatus] = useState('all');
  const [page, setPage] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [bulkError, setBulkError] = useState('');
  const [loading, setLoading] = useState(true);
  const [announcement, setAnnouncement] = useState('');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkSaving, setBulkSaving] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [requestGuard] = useState(createLatestRequestGuard);

  const load = useCallback(() => {
    const requestId = requestGuard.begin();
    return adminApi.discoveryReviews(token, status === 'all' ? undefined : status, page * PAGE_SIZE, PAGE_SIZE, search)
      .then((data) => {
        if (requestGuard.isCurrent(requestId)) {
          setResult(data);
          setError('');
          setLoading(false);
        }
      })
      .catch((failure) => {
        if (requestGuard.isCurrent(requestId)) {
          setError(failure.message);
          setLoading(false);
        }
      });
  }, [requestGuard, token, status, page, search]);
  useEffect(() => {
    load();
    return () => requestGuard.invalidate();
  }, [load, refresh, requestGuard]);

  const changeStatus = (value) => {
    if (value === status) return;
    requestGuard.invalidate();
    setError('');
    setLoading(true);
    setStatus(value);
    setPage(0);
    setSelectedId(null);
    setSelectedIds([]);
    setAnnouncement('');
  };

  const viewState = getReviewQueueViewState({ loading, error, result });
  const handleDone = (decision, updatedItem) => {
    setAnnouncement(getReviewDecisionAnnouncement(decision, updatedItem));
    requestGuard.invalidate();
    setError('');
    setLoading(true);
    setSelectedId(null);
    setSelectedIds([]);
    setRefresh((value) => value + 1);
  };
  const retryLoad = () => {
    requestGuard.invalidate();
    setError('');
    setLoading(true);
    setRefresh((value) => value + 1);
  };
  const changePage = (nextPage) => {
    requestGuard.invalidate();
    setError('');
    setLoading(true);
    setPage(nextPage);
    setSelectedId(null);
    setSelectedIds([]);
  };
  const updateSearch = (value) => {
    requestGuard.invalidate();
    setSearch(value);
    setPage(0);
    setSelectedId(null);
    setSelectedIds([]);
    setError('');
    setLoading(true);
  };
  const pageItems = result?.items || [];
  const selectedItems = pageItems.filter((item) => selectedIds.includes(item.id));
  const selectedItem = pageItems.find((item) => item.id === selectedId);
  const allPageSelected = pageItems.length > 0 && pageItems.every((item) => selectedIds.includes(item.id));
  const canBulkResolve = selectedItems.length > 0
    && selectedItems.every((item) => item.review_status === 'reviewed');
  const statusLabels = {
    pending: 'Needs review',
    reviewed: 'Reviewed',
    accepted: 'Accepted',
    rejected: 'Rejected',
    duplicate: 'Duplicate',
  };
  const statusFilters = [
    { value: 'all', label: 'All' },
    { value: 'pending', label: 'Needs review' },
    { value: 'reviewed', label: 'Reviewed' },
    { value: 'accepted', label: 'Accepted' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'duplicate', label: 'Duplicate' },
  ];
  const toggleCandidate = (id, checked) => {
    setSelectedIds((current) => checked
      ? [...new Set([...current, id])]
      : current.filter((value) => value !== id));
  };
  const togglePage = (checked) => {
    setSelectedIds(checked ? pageItems.map((item) => item.id) : []);
  };
  const resolveSelected = async (decision) => {
    if (!canBulkResolve || bulkSaving) return;
    requestGuard.invalidate();
    setBulkSaving(true);
    setBulkError('');
    setError('');
    let completed = 0;
    try {
      for (const item of selectedItems) {
        await adminApi.reviewDiscovery(token, item.id, {
          decision,
          ...(decision === 'accepted' ? { values: item.extracted_values } : {}),
        });
        completed += 1;
      }
      setAnnouncement(
        decision === 'accepted'
          ? `${completed} candidate(s) approved as unverified scholarships.`
          : `${completed} candidate(s) rejected.`,
      );
      setSelectedIds([]);
      setSelectedId(null);
    } catch (failure) {
      setBulkError(completed
        ? `${completed} candidate(s) were resolved before the next action failed: ${failure.message}`
        : failure.message);
    } finally {
      setSelectedIds([]);
      setSelectedId(null);
      setBulkSaving(false);
      setLoading(true);
      setRefresh((value) => value + 1);
    }
  };

  return (
    <div className="admin-review-page">
      <header className="admin-review-page-header">
        <div>
          <h1>Review Queue</h1>
          <p>Check discovered candidates before they are published.</p>
        </div>
        <div className="admin-review-bulk-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!canBulkResolve || bulkSaving}
            title={!canBulkResolve ? 'Select reviewed candidates to approve.' : undefined}
            onClick={() => resolveSelected('accepted')}
          >
            {bulkSaving ? 'Working...' : 'Approve selected'}
          </button>
          <button
            type="button"
            className="btn btn-outline"
            disabled={!canBulkResolve || bulkSaving}
            title={!canBulkResolve ? 'Select reviewed candidates to reject.' : undefined}
            onClick={() => resolveSelected('rejected')}
          >
            Reject selected
          </button>
        </div>
      </header>
      {announcement && <p className="admin-notice is-success" role="status">{announcement}</p>}
      {bulkError && (
        <p className="admin-notice is-error" role="alert">
          {bulkError} <button type="button" className="admin-link" onClick={() => setBulkError('')}>Dismiss</button>
        </p>
      )}
      {viewState === 'error' && <RetryNotice message={error} onRetry={retryLoad} />}
      <div className="admin-review-workspace">
        <section className="admin-card admin-review-list" aria-label="Discovery candidates">
          <div className="admin-review-toolbar">
            <div className="admin-review-filters" role="group" aria-label="Filter candidates by review status">
              {statusFilters.map((filter) => (
                <button
                  type="button"
                  key={filter.value}
                  className={status === filter.value ? 'is-selected' : ''}
                  aria-pressed={status === filter.value}
                  disabled={bulkSaving}
                  onClick={() => changeStatus(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
            <label className="admin-review-search">
              <Search size={15} aria-hidden="true" />
              <input
                type="search"
                value={search}
                onChange={(event) => updateSearch(event.target.value)}
                placeholder="Search candidates"
                aria-label="Search candidates"
                disabled={bulkSaving}
              />
            </label>
          </div>
          <div className="admin-table-scroll admin-review-table-scroll">
            <table className="admin-table admin-review-table">
              <thead>
                <tr>
                  <th className="admin-review-checkbox-cell">
                    <input
                      type="checkbox"
                      checked={allPageSelected}
                      onChange={(event) => togglePage(event.target.checked)}
                      aria-label="Select all candidates on this page"
                      disabled={viewState !== 'results' || bulkSaving}
                    />
                  </th>
                  <th>Candidate</th>
                  <th>Source</th>
                  <th>Discovered</th>
                  <th>Confidence</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {viewState === 'loading' && Array.from({ length: 5 }, (_, index) => (
                  <tr className="admin-skeleton-row" key={`review-skeleton-${index}`} aria-hidden="true">
                    <td><span className="admin-skeleton-pill" /></td>
                    <td><span className="admin-skeleton-line is-long" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                    <td><span className="admin-skeleton-pill" /></td>
                  </tr>
                ))}
                {viewState === 'empty' && (
                  <tr><td className="admin-review-empty" colSpan="6">No candidates match this filter.</td></tr>
                )}
                {viewState === 'results' && result.items.map((item) => (
                  <tr
                    key={item.id}
                    className={`${selectedId === item.id ? 'is-current ' : ''}${selectedIds.includes(item.id) ? 'is-checked' : ''}`}
                  >
                    <td className="admin-review-checkbox-cell">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(item.id)}
                        onChange={(event) => toggleCandidate(item.id, event.target.checked)}
                        aria-label={`Select ${item.candidate_name || 'unnamed candidate'}`}
                        disabled={bulkSaving}
                      />
                    </td>
                    <td>
                      <button type="button" className="admin-review-candidate-button" onClick={() => setSelectedId(item.id)}>
                        {item.candidate_name || item.extracted_values?.name || 'Unnamed scholarship'}
                      </button>
                      <small>{item.host_country || 'Country not recorded'}</small>
                    </td>
                    <td>{item.source_name}</td>
                    <td>{formatRunTime(item.created_at)}</td>
                    <td><span className="admin-review-confidence">Not recorded</span></td>
                    <td><span className={`admin-review-status is-${item.review_status}`}>{statusLabels[item.review_status] || item.review_status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="admin-review-legend" aria-label="Review status key">
            <span>Status key:</span>
            <span className="admin-review-status is-pending">Needs review</span>
            <span className="admin-review-status is-reviewed">Reviewed</span>
            <span className="admin-review-status is-accepted">Accepted</span>
            <span className="admin-review-status is-rejected">Rejected</span>
            <span className="admin-review-status is-duplicate">Duplicate</span>
          </div>
          {result && viewState !== 'error' && (
            <footer className="admin-review-pagination">
              <span>
                Showing {result.total === 0 ? 0 : page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, result.total)} of {result.total}
                {selectedIds.length > 0 ? ` · ${selectedIds.length} selected` : ''}
              </span>
              <div>
                <button type="button" disabled={loading || page === 0 || bulkSaving} onClick={() => changePage(page - 1)}>
                  <ArrowLeft size={14} aria-hidden="true" /> Previous
                </button>
                <button type="button" disabled={loading || (page + 1) * PAGE_SIZE >= result.total || bulkSaving} onClick={() => changePage(page + 1)}>
                  Next <ArrowRight size={14} aria-hidden="true" />
                </button>
              </div>
            </footer>
          )}
        </section>
        {selectedItem
          ? <DiscoveryReviewCard key={selectedItem.id} item={selectedItem} token={token} onDone={handleDone} saving={bulkSaving} />
          : (
            <aside className="admin-card admin-review-details admin-review-details-empty" aria-label="Candidate details">
              <h2>Candidate details</h2>
              <p>Select a candidate to review its extracted fields.</p>
              <dl className="admin-review-detail-fields">
                {['Name', 'Source URL', 'Deadline', 'Award amount', 'Eligibility', 'Confidence'].map((label) => (
                  <div key={label}><dt>{label}</dt><dd>—</dd></div>
                ))}
              </dl>
            </aside>
          )}
      </div>
    </div>
  );
}

function formatRunTime(value) {
  return value ? new Date(value).toLocaleString() : 'Not available';
}

function getRecentRunActivity(runs) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(today);
    date.setDate(today.getDate() - 6 + index);
    return { date, count: 0 };
  });
  const dayKeys = new Map(days.map((day) => [day.date.toDateString(), day]));

  runs.forEach((run) => {
    const startedAt = new Date(run.started_at);
    const day = dayKeys.get(new Date(
      startedAt.getFullYear(),
      startedAt.getMonth(),
      startedAt.getDate(),
    ).toDateString());
    if (day) day.count += 1;
  });

  return days;
}

function AdminDashboard({ token }) {
  const [overview, setOverview] = useState({ summary: null, monitoring: null, reviews: null });
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [requestGuard] = useState(createLatestRequestGuard);

  const load = useCallback(() => {
    const requestId = requestGuard.begin();
    Promise.allSettled([
      adminApi.summary(token),
      adminApi.discoveryMonitoring(token),
      adminApi.discoveryReviews(token, 'pending', 0, 5),
    ]).then((results) => {
      if (!requestGuard.isCurrent(requestId)) return;

      const [summary, monitoring, reviews] = results;
      setOverview({
        summary: summary.status === 'fulfilled' ? summary.value : null,
        monitoring: monitoring.status === 'fulfilled' ? monitoring.value : null,
        reviews: reviews.status === 'fulfilled' ? reviews.value : null,
      });
      setErrors({
        summary: summary.status === 'rejected' ? summary.reason.message : '',
        monitoring: monitoring.status === 'rejected' ? monitoring.reason.message : '',
        reviews: reviews.status === 'rejected' ? reviews.reason.message : '',
      });
      setLoading(false);
    });
  }, [requestGuard, token]);

  useEffect(() => {
    load();
    return () => requestGuard.invalidate();
  }, [load, refresh, requestGuard]);

  const retry = () => {
    requestGuard.invalidate();
    setErrors({});
    setLoading(true);
    setRefresh((value) => value + 1);
  };
  const { summary, monitoring, reviews } = overview;
  const awaitingReview = monitoring?.review_queue_pending ?? 0;
  const runs = monitoring?.recent_runs ?? [];
  const activity = getRecentRunActivity(runs);
  const maxActivity = Math.max(...activity.map((day) => day.count), 1);
  const monitoringAvailable = Boolean(monitoring) && !errors.monitoring;
  const hasErrors = Object.values(errors).some(Boolean);

  return (
    <div className="admin-dashboard">
      <header className="admin-dashboard-header">
        <div>
          <span className="admin-eyebrow">Scholarship operations</span>
          <h1>Admin Dashboard</h1>
          <p>Scholarship management and discovery overview</p>
        </div>
        <div className={`admin-system-status${monitoringAvailable ? ' is-available' : ''}`} role="status">
          <span aria-hidden="true" />
          {loading && !monitoring ? 'Loading monitoring' : monitoringAvailable ? 'Monitoring data available' : 'Monitoring unavailable'}
        </div>
      </header>

      {hasErrors && (
        <RetryNotice message={`Some dashboard data could not be loaded: ${Object.values(errors).filter(Boolean).join(' ')}`} onRetry={retry} />
      )}

      <section className={`admin-attention${awaitingReview > 0 ? ' has-pending' : ''}`} aria-label="Review queue status">
        <div className="admin-attention-icon"><ShieldAlert size={20} aria-hidden="true" /></div>
        <div>
          <strong>
            {!monitoringAvailable
              ? loading && !monitoring ? 'Checking review queue status' : 'Review queue status unavailable'
              : awaitingReview > 0
                ? `${awaitingReview} ${awaitingReview === 1 ? 'candidate needs' : 'candidates need'} review`
                : 'Review queue is clear'}
          </strong>
          <p>
            {!monitoringAvailable
              ? 'The pending review count could not be confirmed.'
              : awaitingReview > 0
                ? 'Review discovery candidates before accepting any as scholarship records.'
                : 'There are no candidates currently awaiting review.'}
          </p>
        </div>
        <Link className="admin-dashboard-action" to="/admin/scholarships?section=reviews">
          Open review queue <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </section>

      <section className="admin-dashboard-stats" aria-label="Scholarship overview">
        <article className="admin-stat-card">
          <span className="admin-stat-icon is-blue"><BookOpen size={19} aria-hidden="true" /></span>
          <div><span>Total scholarships</span><strong>{summary?.total ?? '—'}</strong><small>Active records</small></div>
        </article>
        <article className="admin-stat-card">
          <span className="admin-stat-icon is-green"><CircleCheck size={19} aria-hidden="true" /></span>
          <div><span>Verified</span><strong>{summary?.verified ?? '—'}</strong><small>Verified records</small></div>
        </article>
        <article className="admin-stat-card">
          <span className="admin-stat-icon is-amber"><Clock3 size={19} aria-hidden="true" /></span>
          <div><span>Unverified</span><strong>{summary?.unverified ?? '—'}</strong><small>Awaiting verification</small></div>
        </article>
        <article className="admin-stat-card">
          <span className="admin-stat-icon is-violet"><ListChecksIcon /></span>
          <div><span>Candidates awaiting review</span><strong>{monitoring ? awaitingReview : '—'}</strong><small>Discovery review queue</small></div>
        </article>
      </section>

      <div className="admin-dashboard-grid">
        <div className="admin-dashboard-main">
          <section className="admin-dashboard-panel" aria-label="Recent discovery candidates">
            <header className="admin-panel-header">
              <div><h2>Recent discovery candidates</h2><p>Pending review items from the discovery queue</p></div>
              <Link to="/admin/scholarships?section=reviews">View queue <ArrowRight size={15} aria-hidden="true" /></Link>
            </header>
            {loading && !reviews && <p className="admin-dashboard-empty" role="status">Loading recent candidates...</p>}
            {!loading && errors.reviews && <p className="admin-dashboard-empty">Recent candidates are unavailable.</p>}
            {!loading && reviews?.items.length === 0 && <p className="admin-dashboard-empty">No candidates are awaiting review.</p>}
            {reviews?.items.length > 0 && (
              <div className="admin-dashboard-table-wrap">
                <table className="admin-dashboard-table">
                  <thead><tr><th>Candidate</th><th>Source</th><th>Discovered</th><th>Status</th></tr></thead>
                  <tbody>
                    {reviews.items.map((item) => (
                      <tr key={item.id}>
                        <td><strong>{item.candidate_name || 'Unnamed scholarship'}</strong><small>{item.host_country || 'Host country not recorded'}</small></td>
                        <td>{item.source_name}</td>
                        <td>{formatRunTime(item.created_at)}</td>
                        <td><span className="admin-review-status">{item.review_status.replace(/_/g, ' ')}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="admin-dashboard-panel" aria-label="Recent discovery activity">
            <header className="admin-panel-header">
              <div><h2>Discovery activity</h2><p>Daily run counts from the latest 25 run records</p></div>
              <Activity size={19} aria-hidden="true" />
            </header>
            {!monitoring && !loading && <p className="admin-dashboard-empty">Activity data is unavailable.</p>}
            {monitoring && runs.length === 0 && <p className="admin-dashboard-empty">No discovery runs have been recorded.</p>}
            {monitoring && runs.length > 0 && (
              <div className="admin-activity-chart" role="img" aria-label="Discovery runs by day across the last seven days, based on the latest 25 run records">
                {activity.map(({ date, count }) => (
                  <div className="admin-activity-day" key={date.toISOString()}>
                    <div className="admin-activity-track">
                      <span style={{ height: `${count ? Math.max(12, (count / maxActivity) * 100) : 0}%` }} />
                    </div>
                    <strong>{count}</strong>
                    <small>{date.toLocaleDateString(undefined, { weekday: 'short' })}</small>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <aside className="admin-dashboard-side">
          <section className="admin-dashboard-panel admin-automated-card">
            <header className="admin-panel-header">
              <div><h2>Automated discovery</h2><p>Scheduler configuration</p></div>
              <Radar size={19} aria-hidden="true" />
            </header>
            {monitoring ? (
              <>
                <div className="admin-discovery-state">
                  <span className={`admin-state-dot${monitoring.enabled ? ' is-enabled' : ''}`} />
                  <strong>{monitoring.enabled ? 'Enabled' : 'Disabled'}</strong>
                  <span>{monitoring.interval_hours} hour interval</span>
                </div>
                <dl className="admin-discovery-dl">
                  <div><dt>Current run</dt><dd>{monitoring.current_run_status}</dd></div>
                  <div><dt>Next scheduled run</dt><dd>{formatRunTime(monitoring.next_scheduled_run)}</dd></div>
                  <div><dt>Last successful run</dt><dd>{formatRunTime(monitoring.last_successful_run?.completed_at)}</dd></div>
                </dl>
                <p className="admin-health-note">Configuration is shown here; the separate scheduler process health is not reported.</p>
              </>
            ) : <p className="admin-dashboard-empty">{loading ? 'Loading scheduler configuration...' : 'Scheduler configuration is unavailable.'}</p>}
            <Link className="admin-secondary-action" to="/admin/scholarships?section=discovery">
              Discovery monitoring <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </section>

          <section className="admin-dashboard-panel">
            <header className="admin-panel-header">
              <div><h2>Recent discovery runs</h2><p>Latest run history returned by monitoring</p></div>
            </header>
            {monitoring && runs.length === 0 && <p className="admin-dashboard-empty">No run history yet.</p>}
            {monitoring && runs.slice(0, 4).map((run) => (
              <div className="admin-recent-run" key={run.run_id}>
                <span className={`admin-run-marker is-${run.status}`} />
                <div><strong>{run.trigger_type.replace(/_/g, ' ')}</strong><small>{formatRunTime(run.started_at)}</small></div>
                <span className={`admin-run-status is-${run.status}`}>{run.status}</span>
                <small className="admin-run-count">{run.candidates_discovered} candidates</small>
              </div>
            ))}
            <Link className="admin-secondary-action" to="/admin/scholarships?section=history">
              View discovery history <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </section>
        </aside>
      </div>
    </div>
  );
}

function ListChecksIcon() {
  return <ListChecks size={19} aria-hidden="true" />;
}

function DiscoveryMonitoring({ token, view = 'overview' }) {
  const [monitoring, setMonitoring] = useState(null);
  const [error, setError] = useState('');
  const [manualError, setManualError] = useState('');
  const [manualMessage, setManualMessage] = useState('');
  const [manualSubmitting, setManualSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [requestGuard] = useState(createLatestRequestGuard);

  const load = useCallback(() => {
    const requestId = requestGuard.begin();
    adminApi.discoveryMonitoring(token)
      .then((data) => {
        if (requestGuard.isCurrent(requestId)) {
          setMonitoring(data);
          setError('');
          setLoading(false);
        }
      })
      .catch((failure) => {
        if (requestGuard.isCurrent(requestId)) {
          setError(failure.message);
          setLoading(false);
        }
      });
  }, [requestGuard, token]);
  useEffect(() => {
    load();
    return () => requestGuard.invalidate();
  }, [load, refresh, requestGuard]);

  useEffect(() => {
    if (!isDiscoveryWorkerActive(monitoring?.worker_status)) return undefined;
    const intervalId = window.setInterval(() => {
      setRefresh((value) => value + 1);
    }, 4000);
    return () => window.clearInterval(intervalId);
  }, [monitoring?.worker_status]);

  const retry = () => {
    requestGuard.invalidate();
    setError('');
    setLoading(true);
    setRefresh((value) => value + 1);
  };

  const runDiscoveryNow = () => {
    setManualSubmitting(true);
    setManualError('');
    setManualMessage('');
    adminApi.startManualDiscovery(token)
      .then((run) => {
        setManualMessage(`Manual discovery started (${run.run_id}).`);
        setRefresh((value) => value + 1);
      })
      .catch((failure) => {
        setManualError(formatDiscoveryWorkerError(failure));
        setRefresh((value) => value + 1);
      })
      .finally(() => setManualSubmitting(false));
  };

  const candidateCounts = getDiscoveryCandidateCounts(monitoring);
  const lastRun = monitoring?.last_attempted_run;
  const activeRun = monitoring?.current_run;
  const workerStatus = monitoring?.worker_status
    || (monitoring?.current_run_status === 'running' ? 'running' : 'idle');
  const workerStatusLabel = getDiscoveryWorkerStatusLabel(workerStatus);
  const runIsActive = isDiscoveryWorkerActive(workerStatus);
  const workerBlocksSubmission = runIsActive
    || (workerStatus === 'interrupted_unknown' && !monitoring?.worker_recoverable);
  const lastRunStatus = lastRun?.display_status === 'succeeded'
    ? 'Success'
    : lastRun?.display_status === 'partial'
      ? 'Partial Failure'
      : lastRun?.display_status === 'failed'
        ? 'Failed'
        : lastRun?.display_status === 'running'
          ? 'Running'
          : null;

  if (view === 'overview') {
    const showTime = (value) => value ? formatRunTime(value) : '—';
    const configStatus = monitoring
      ? `${monitoring.enabled ? 'Enabled' : 'Disabled'} (configured) · ${monitoring.current_run_status}`
      : '—';

    return (
      <div className="admin-discovery-page">
        <header className="admin-discovery-page-header">
          <div>
            <h1>Automated Discovery</h1>
            <p>Configure and monitor scholarship discovery</p>
          </div>
          <div className="admin-discovery-header-actions">
            <span className="admin-discovery-system-status" role="status">
              <span aria-hidden="true" />
              {monitoring ? 'Scheduler process health: not reported' : loading ? 'Loading monitoring' : 'Monitoring unavailable'}
            </span>
            <button type="button" className="btn btn-outline" onClick={retry}>Refresh</button>
          </div>
        </header>

        {error && <RetryNotice message={error} onRetry={retry} />}

        <div className="admin-discovery-layout">
          <div className="admin-discovery-main">
            <section className="admin-discovery-panel" aria-label="Discovery controls">
              <header className="admin-discovery-panel-header">
                <h2>Automatic and manual discovery</h2>
                <span className="admin-discovery-unavailable">
                  {monitoring ? `${monitoring.interval_hours}-hour interval` : 'Configuration unavailable'}
                </span>
              </header>
              <div className="admin-discovery-control-row">
                <div>
                  <strong>Automated discovery</strong>
                  <p>{monitoring ? `Scheduler is ${monitoring.enabled ? 'enabled' : 'disabled'} in configuration` : 'Scheduler configuration is unavailable'}</p>
                </div>
                <button
                  type="button"
                  className={`admin-discovery-toggle${monitoring?.enabled ? ' is-on' : ''}`}
                  disabled
                  aria-pressed={Boolean(monitoring?.enabled)}
                  aria-label={`Automated discovery ${monitoring?.enabled ? 'enabled' : 'disabled'} in configuration; toggle unavailable`}
                >
                  <span />
                </button>
              </div>
              <div className="admin-discovery-control-row">
                <div>
                  <strong>Schedule</strong>
                  <p>Configured interval between scheduled runs</p>
                </div>
                <select disabled value={monitoring ? String(monitoring.interval_hours) : ''} aria-label="Configured discovery interval">
                  {monitoring
                    ? <option value={String(monitoring.interval_hours)}>Every {monitoring.interval_hours} hours</option>
                    : <option value="">Not available</option>}
                </select>
              </div>
              <div className="admin-discovery-control-row">
                <div>
                  <strong>Run discovery now</strong>
                  <p>
                    {workerStatus === 'interrupted_unknown'
                      ? monitoring.worker_recoverable
                        ? 'The last run was interrupted. A new run will reconcile it after obtaining the exclusive advisory lock.'
                        : 'The last run state cannot be verified. Refresh monitoring before retrying.'
                      : activeRun
                      ? `${activeRun.trigger_type.replace(/_/g, ' ')} discovery is active. Wait for it to finish.`
                      : workerStatus === 'submitting'
                        ? 'Manual discovery is being submitted.'
                        : workerStatus === 'starting'
                          ? 'Discovery is waiting for its worker to start.'
                      : 'Start a manual run without changing the automatic schedule.'}
                  </p>
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={runDiscoveryNow}
                  disabled={manualSubmitting || workerBlocksSubmission || !monitoring}
                >
                  {manualSubmitting || workerStatus === 'submitting'
                    ? 'Submitting…'
                    : workerStatus === 'starting'
                      ? 'Starting…'
                      : workerStatus === 'running'
                        ? 'Discovery running'
                        : workerStatus === 'interrupted_unknown' && !monitoring?.worker_recoverable
                          ? 'State unverified'
                        : 'Run Discovery Now'}
                </button>
              </div>
              {manualError && <p className="admin-notice is-error" role="alert">{manualError}</p>}
              {manualMessage && !manualError && <p className="admin-discovery-run-message" role="status">{manualMessage}</p>}
              {monitoring && (
                <p className="admin-discovery-run-message" role="status">
                  Worker: {workerStatusLabel}
                  {monitoring.worker_run_id ? ` · Run ${monitoring.worker_run_id}` : ''}
                  {monitoring.worker_trigger_type ? ` · ${monitoring.worker_trigger_type.replace(/_/g, ' ')}` : ''}
                  {monitoring.worker_started_at
                    ? ` · Started ${showTime(monitoring.worker_started_at)}`
                    : monitoring.worker_submitted_at
                      ? ` · Submitted ${showTime(monitoring.worker_submitted_at)}`
                      : ''}
                  {` · ${monitoring.worker_duration_seconds ?? 0}s`}
                  {monitoring.worker_stage ? ` · Stage: ${monitoring.worker_stage}` : ''}
                  {monitoring.worker_error ? ` · ${monitoring.worker_error}` : ''}
                </p>
              )}
              <p className="admin-discovery-control-note">
                Automatic enablement and interval come from backend configuration. Manual runs remain available independently; scheduler process health is not reported by this API.
              </p>
            </section>

            <section className="admin-discovery-panel" aria-label="Latest discovery run pipeline">
              <h2>Latest run pipeline</h2>
              {lastRun && (
                <p className="admin-discovery-last-run">
                  {lastRun.trigger_type.replace(/_/g, ' ')} run · {showTime(lastRun.started_at)}
                  {lastRunStatus ? ` · ${lastRunStatus}` : ''}
                </p>
              )}
              <div className="admin-discovery-pipeline">
                <div><span>Sources attempted</span><strong>{lastRun?.sources_attempted ?? '—'}</strong></div>
                <div><span>Sources succeeded</span><strong>{lastRun?.sources_succeeded ?? '—'}</strong></div>
                <div><span>Candidates found</span><strong>{lastRun?.candidates_discovered ?? '—'}</strong></div>
                <div><span>Awaiting review</span><strong>{lastRun?.candidates_queued_for_review ?? '—'}</strong></div>
              </div>
              {lastRun?.error_summary && (
                <p className="admin-discovery-last-run" role="status">
                  Failure category: {lastRun.error_summary}
                </p>
              )}
              {monitoring?.last_failed_run && monitoring.last_failed_run.run_id !== lastRun?.run_id && (
                <p className="admin-discovery-last-run" role="status">
                  Last failure: {showTime(monitoring.last_failed_run.completed_at)}
                  {monitoring.last_failed_run.error_summary
                    ? ` · ${monitoring.last_failed_run.error_summary}`
                    : ` · ${monitoring.last_failed_run.failed_sources.length} source failure(s)`}
                </p>
              )}
              {!lastRun && !error && <p className="admin-discovery-empty" role="status">No discovery run has been recorded yet.</p>}
            </section>
          </div>

          <aside className="admin-discovery-side">
            <section className="admin-discovery-panel" aria-label="Discovery overview">
              <h2>Overview</h2>
              <dl className="admin-discovery-overview">
                <div><dt>Status</dt><dd>{configStatus}{monitoring?.current_run_status === 'running' ? ' · Run active' : ''}</dd></div>
                <div><dt>Last run</dt><dd>{showTime(lastRun?.started_at)}</dd></div>
                <div><dt>Last completed run</dt><dd>{showTime(monitoring?.last_completed_run?.completed_at)}</dd></div>
                <div><dt>Last failed run</dt><dd>{showTime(monitoring?.last_failed_run?.completed_at)}</dd></div>
                <div><dt>Last scheduled run</dt><dd>{showTime(monitoring?.last_scheduled_run?.started_at)}</dd></div>
                <div><dt>Next scheduled run</dt><dd>{showTime(monitoring?.next_scheduled_run)}</dd></div>
                <div><dt>Manual run</dt><dd>{monitoring?.current_manual_run?.status || 'Idle'}</dd></div>
                <div><dt>Sources attempted</dt><dd>{lastRun?.sources_attempted ?? '—'}</dd></div>
                <div><dt>New candidates</dt><dd>{lastRun?.candidates_discovered ?? '—'}</dd></div>
                <div><dt>Requiring review</dt><dd>{monitoring ? candidateCounts.awaitingReview : '—'}</dd></div>
              </dl>
            </section>

            <section className="admin-discovery-panel admin-discovery-go-to" aria-label="Discovery navigation">
              <h2>Go to</h2>
              <Link to="/admin/scholarships?section=sources">Discovery Sources <ArrowRight size={14} aria-hidden="true" /></Link>
              <Link to="/admin/scholarships?section=reviews">Review Queue <ArrowRight size={14} aria-hidden="true" /></Link>
              <Link to="/admin/scholarships?section=history">Discovery History <ArrowRight size={14} aria-hidden="true" /></Link>
              <Link to="/admin/scholarships?section=publications">Discovery Publications <ArrowRight size={14} aria-hidden="true" /></Link>
            </section>
          </aside>
        </div>
      </div>
    );
  }

  return (
    <section className="admin-card admin-discovery-monitoring" aria-label="Scholarship discovery monitoring">
      <div className="admin-monitoring-header">
        <div>
          <h2>Discovery monitoring</h2>
          <p className="admin-muted">Scheduler status reflects configuration; it does not confirm that the separate scheduler process is running.</p>
        </div>
        <button type="button" className="btn btn-outline" onClick={retry}>Refresh</button>
      </div>
      {error && <RetryNotice message={error} onRetry={retry} />}
      {!monitoring && !error && loading && <p role="status">Loading discovery monitoring...</p>}
      {monitoring && (
        <>
          <div className="admin-tiles" aria-label="Discovery status">
            <div className="admin-tile">
              <strong>{monitoring.enabled ? 'Enabled' : 'Disabled'}</strong>
              <span>Scheduler configuration</span>
            </div>
            <div className="admin-tile">
              <strong>{getDiscoveryWorkerStatusLabel(monitoring.worker_status)}</strong>
              <span>Discovery worker</span>
            </div>
            <div className="admin-tile">
              <strong>{candidateCounts.awaitingReview}</strong>
              <span>Candidates awaiting review</span>
            </div>
            <div className="admin-tile">
              <strong>{candidateCounts.totalReviewCandidates}</strong>
              <span>Total review candidates</span>
            </div>
          </div>
          <dl className="admin-monitoring-times">
            <div><dt>Last attempted run</dt><dd>{formatRunTime(monitoring.last_attempted_run?.started_at)}</dd></div>
            <div><dt>Last completed run</dt><dd>{formatRunTime(monitoring.last_completed_run?.completed_at)}</dd></div>
            <div><dt>Last failed run</dt><dd>{formatRunTime(monitoring.last_failed_run?.completed_at)}</dd></div>
            <div><dt>Last successful run</dt><dd>{formatRunTime(monitoring.last_successful_run?.completed_at)}</dd></div>
            <div><dt>Next scheduled run</dt><dd>{formatRunTime(monitoring.next_scheduled_run)}</dd></div>
            <div><dt>Interval</dt><dd>{monitoring.interval_hours} hours</dd></div>
          </dl>
          <p className="admin-discovery-run-message" role="status">
            {monitoring.worker_run_id ? `Run ${monitoring.worker_run_id}` : 'No active run ID'}
            {monitoring.worker_trigger_type ? ` · ${monitoring.worker_trigger_type.replace(/_/g, ' ')}` : ''}
            {monitoring.worker_started_at ? ` · Started ${formatRunTime(monitoring.worker_started_at)}` : ''}
            {!monitoring.worker_started_at && monitoring.worker_submitted_at
              ? ` · Submitted ${formatRunTime(monitoring.worker_submitted_at)}`
              : ''}
            {` · ${monitoring.worker_duration_seconds ?? 0}s`}
            {monitoring.worker_stage ? ` · Stage: ${monitoring.worker_stage}` : ''}
            {monitoring.worker_error ? ` · ${monitoring.worker_error}` : ''}
          </p>
          <h3>Recent run history</h3>
          {monitoring.recent_runs.length === 0
            ? <p className="admin-muted">No discovery runs have been recorded.</p>
            : (
              <div className="admin-table-scroll">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Run</th><th>Trigger</th><th>Started</th><th>Duration</th><th>Status</th>
                      <th>Sources</th><th>Candidates</th><th>Created</th><th>Review queue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {monitoring.recent_runs.map((run) => (
                      <tr key={run.run_id}>
                        <td>{run.run_id}</td>
                        <td>{run.trigger_type.replace('_', ' ')}</td>
                        <td>{formatRunTime(run.started_at)}</td>
                        <td>{run.duration_seconds}s</td>
                        <td>{run.status}</td>
                        <td>{run.sources_succeeded} succeeded / {run.sources_failed} failed of {run.sources_attempted}</td>
                        <td>{run.candidates_discovered}</td>
                        <td>{run.scholarships_created}</td>
                        <td>{run.candidates_queued_for_review}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          {monitoring.recent_runs.some((run) => run.error_summary || run.failed_sources.length > 0) && (
            <div className="admin-discovery-failures">
              <h3>Recent failure summaries</h3>
              {monitoring.recent_runs
                .filter((run) => run.error_summary || run.failed_sources.length > 0)
                .map((run) => (
                  <details key={run.run_id}>
                    <summary>{run.run_id} · {run.error_summary || `${run.sources_failed} source failure(s)`}</summary>
                    {run.failed_sources.length > 0 && (
                      <ul>
                        {run.failed_sources.map((source) => (
                          <li key={`${run.run_id}-${source.source_id}`}>
                            <strong>{source.source_name || source.source_id}:</strong>{' '}
                            {formatDiscoverySourceFailure(source)}
                          </li>
                        ))}
                      </ul>
                    )}
                  </details>
                ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

const HISTORY_PAGE_SIZE = 5;

function DiscoveryHistory({ token }) {
  const [history, setHistory] = useState(null);
  const [status, setStatus] = useState('all');
  const [days, setDays] = useState(30);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [requestGuard] = useState(createLatestRequestGuard);

  const load = useCallback(() => {
    const requestId = requestGuard.begin();
    adminApi.discoveryHistory(token, {
      status: status === 'all' ? undefined : status,
      days,
      q: search,
      skip: page * HISTORY_PAGE_SIZE,
      limit: HISTORY_PAGE_SIZE,
    })
      .then((data) => {
        if (requestGuard.isCurrent(requestId)) {
          setHistory(data);
          setError('');
          setLoading(false);
        }
      })
      .catch((failure) => {
        if (requestGuard.isCurrent(requestId)) {
          setError(failure.message);
          setLoading(false);
        }
      });
  }, [requestGuard, token, status, days, search, page]);

  useEffect(() => {
    load();
    return () => requestGuard.invalidate();
  }, [load, refresh, requestGuard]);

  const changeFilter = (update) => {
    requestGuard.invalidate();
    setError('');
    setLoading(true);
    setHistory(null);
    setPage(0);
    setSelectedRunId('');
    update();
  };
  const retry = () => {
    requestGuard.invalidate();
    setError('');
    setLoading(true);
    setHistory(null);
    setRefresh((value) => value + 1);
  };
  const changePage = (nextPage) => {
    requestGuard.invalidate();
    setError('');
    setLoading(true);
    setHistory(null);
    setSelectedRunId('');
    setPage(nextPage);
  };

  const statusFilters = [
    { value: 'all', label: 'All' },
    { value: 'succeeded', label: 'Succeeded' },
    { value: 'partial', label: 'Partial' },
    { value: 'failed', label: 'Failed' },
  ];
  const statusLabels = {
    succeeded: 'Succeeded',
    partial: 'Partial',
    failed: 'Failed',
    running: 'Running',
  };
  const selectedRun = history?.items.find((run) => run.run_id === selectedRunId);
  const firstItem = history?.total ? page * HISTORY_PAGE_SIZE + 1 : 0;
  const lastItem = history ? Math.min((page + 1) * HISTORY_PAGE_SIZE, history.total) : 0;

  return (
    <div className="admin-history-page">
      <header className="admin-history-page-header">
        <div>
          <h1>Discovery History</h1>
          <p>Past discovery runs and their results.</p>
        </div>
        <label className="admin-history-range">
          <span className="admin-sr-only">History date range</span>
          <select
            value={days}
            onChange={(event) => {
              const nextDays = Number(event.target.value);
              if (nextDays !== days) changeFilter(() => setDays(nextDays));
            }}
          >
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
            <option value="365">Last 12 months</option>
            <option value="0">All time</option>
          </select>
        </label>
      </header>

      {error && <RetryNotice message={error} onRetry={retry} />}
      <section className="admin-history-card" aria-label="Discovery run history">
        <div className="admin-history-toolbar">
          <div className="admin-history-filters" role="group" aria-label="Filter runs by outcome">
            {statusFilters.map((filter) => (
              <button
                type="button"
                key={filter.value}
                className={status === filter.value ? 'is-selected' : ''}
                aria-pressed={status === filter.value}
                onClick={() => { if (status !== filter.value) changeFilter(() => setStatus(filter.value)); }}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <label className="admin-history-search">
            <Search size={15} aria-hidden="true" />
            <input
              type="search"
              value={search}
              onChange={(event) => changeFilter(() => setSearch(event.target.value))}
              placeholder="Search runs"
              aria-label="Search runs"
            />
          </label>
        </div>

        <div className="admin-table-scroll admin-history-table-scroll">
          <table className="admin-table admin-history-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Sources</th>
                <th>Pages</th>
                <th>Candidates</th>
                <th>Errors</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {!history && loading && Array.from({ length: 5 }, (_, index) => (
                <tr className="admin-skeleton-row" key={`history-skeleton-${index}`} aria-hidden="true">
                  <td><span className="admin-skeleton-pill" /></td>
                  <td><span className="admin-skeleton-line" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                  <td><span className="admin-skeleton-actions" /></td>
                </tr>
              ))}
              {history && !loading && history.items.length === 0 && (
                <tr>
                  <td className="admin-history-empty" colSpan="8">
                    No runs in this range. Try another date range or search term.
                  </td>
                </tr>
              )}
              {history && !loading && history.items.map((run) => (
                <tr key={run.run_id}>
                  <td><span className={`admin-history-status is-${run.display_status}`}>{statusLabels[run.display_status] || run.display_status}</span></td>
                  <td>
                    <strong>{formatRunTime(run.started_at)}</strong>
                    <small>{run.trigger_type.replace(/_/g, ' ')} · {run.run_id.slice(0, 8)}</small>
                  </td>
                  <td>{run.duration_seconds}s</td>
                  <td>{run.sources_succeeded}/{run.sources_attempted}</td>
                  <td>{run.pages_fetched}</td>
                  <td>{run.candidates_discovered}</td>
                  <td>{run.sources_failed ? <span className="admin-history-error-count">{run.sources_failed}</span> : '—'}</td>
                  <td>
                    <button type="button" className="admin-history-view-log" onClick={() => setSelectedRunId(run.run_id)}>
                      View log
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <footer className="admin-history-pagination">
          <span>
            Showing {history ? firstItem : '—'}–{history ? lastItem : '—'} of {history?.total ?? '—'}
            {history && history.total > HISTORY_PAGE_SIZE ? ` · page ${page + 1} of ${Math.ceil(history.total / HISTORY_PAGE_SIZE)}` : ''}
          </span>
          <div>
            <button type="button" disabled={loading || page === 0} onClick={() => changePage(page - 1)}>
              <ArrowLeft size={14} aria-hidden="true" /> Previous
            </button>
            <button
              type="button"
              disabled={loading || !history || (page + 1) * HISTORY_PAGE_SIZE >= history.total}
              onClick={() => changePage(page + 1)}
            >
              Next <ArrowRight size={14} aria-hidden="true" />
            </button>
          </div>
        </footer>
      </section>

      {selectedRun && (
        <section className="admin-history-log" aria-label={`Run log details for ${selectedRun.run_id}`}>
          <header>
            <div>
              <h2>Run log details</h2>
              <p>{selectedRun.run_id} · {selectedRun.trigger_type.replace(/_/g, ' ')} · {formatRunTime(selectedRun.started_at)}</p>
            </div>
            <button type="button" className="admin-link" onClick={() => setSelectedRunId('')}>Close</button>
          </header>
          <dl>
            <div><dt>Outcome</dt><dd>{statusLabels[selectedRun.display_status] || selectedRun.display_status}</dd></div>
            <div><dt>Sources</dt><dd>{selectedRun.sources_succeeded} succeeded, {selectedRun.sources_failed} failed of {selectedRun.sources_attempted}</dd></div>
            <div><dt>Pages fetched</dt><dd>{selectedRun.pages_fetched}</dd></div>
            <div><dt>Candidates discovered</dt><dd>{selectedRun.candidates_discovered}</dd></div>
            <div><dt>Review candidates queued</dt><dd>{selectedRun.candidates_queued_for_review}</dd></div>
            <div><dt>Scholarships created</dt><dd>{selectedRun.scholarships_created} (unverified)</dd></div>
          </dl>
          {selectedRun.error_summary && <p className="admin-notice is-error">{selectedRun.error_summary}</p>}
          {selectedRun.failed_sources.length > 0 ? (
            <ul>
              {selectedRun.failed_sources.map((source) => (
                <li key={`${selectedRun.run_id}-${source.source_id}`}>
                  <strong>{source.source_name || source.source_id}:</strong>{' '}
                  {formatDiscoverySourceFailure(source)}
                </li>
              ))}
            </ul>
          ) : !selectedRun.error_summary && (
            <p className="admin-muted">No source errors were recorded for this run.</p>
          )}
        </section>
      )}
    </div>
  );
}

const SOURCE_PAGE_SIZE = 5;

function DiscoverySources({ token }) {
  const [sources, setSources] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(0);
  const [requestGuard] = useState(createLatestRequestGuard);

  const load = useCallback(() => {
    const requestId = requestGuard.begin();
    adminApi.discoverySources(token)
      .then((data) => {
        if (!Array.isArray(data.items)) throw new Error('The discovery source response was invalid.');
        if (requestGuard.isCurrent(requestId)) {
          setSources(data.items);
          setError('');
          setLoading(false);
        }
      })
      .catch((failure) => {
        if (requestGuard.isCurrent(requestId)) {
          setError(failure.message);
          setLoading(false);
        }
      });
  }, [requestGuard, token]);

  useEffect(() => {
    load();
    return () => requestGuard.invalidate();
  }, [load, refresh, requestGuard]);

  const retry = () => {
    requestGuard.invalidate();
    setError('');
    setLoading(true);
    setRefresh((value) => value + 1);
  };

  const normalizedSearch = search.trim().toLowerCase();
  const visibleSources = (sources || []).filter((source) => {
    const matchesSearch = !normalizedSearch || [
      source.name,
      source.official_domain,
      source.category,
      source.country_or_region,
    ].some((value) => value.toLowerCase().includes(normalizedSearch));
    const matchesFilter = filter === 'all'
      || (filter === 'active' && source.active)
      || (filter === 'errors' && source.status === 'failed');
    return matchesSearch && matchesFilter;
  });
  const pageCount = Math.max(1, Math.ceil(visibleSources.length / SOURCE_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pageSources = visibleSources.slice(
    currentPage * SOURCE_PAGE_SIZE,
    (currentPage + 1) * SOURCE_PAGE_SIZE,
  );
  const statusLabels = {
    not_checked: 'Not checked',
    pending: 'Running',
    fetched: 'Checked',
    failed: 'Error',
    partial_failure: 'Partial failure',
    skipped: 'Skipped',
    trust_review_required: 'Trust review',
  };
  const formatCheckedAt = (value) => {
    if (!value) return 'Never checked';
    return Number.isNaN(new Date(value).getTime()) ? 'Unknown' : formatRunTime(value);
  };

  return (
    <div className="admin-sources-page">
      <header className="admin-discovery-page-header">
        <div>
          <h1>Discovery Sources</h1>
          <p>Review the curated sources used by scholarship discovery.</p>
        </div>
        <div className="admin-sources-header-actions">
          <span className="admin-sources-readonly"><Globe2 size={13} aria-hidden="true" /> Curated registry</span>
          <button type="button" className="btn btn-outline" onClick={retry}>Refresh</button>
          <button
            type="button"
            className="btn btn-primary"
            disabled
            title="Sources are managed in the curated registry and cannot be added from Admin."
          >
            <Plus size={14} aria-hidden="true" /> Add source
          </button>
        </div>
      </header>

      <section className="admin-sources-card" aria-label="Discovery source registry">
        <div className="admin-sources-toolbar">
          <div className="admin-sources-filters" role="group" aria-label="Filter discovery sources">
            {['all', 'active', 'paused', 'errors'].map((value) => (
              <button
                key={value}
                type="button"
                className={filter === value ? 'is-selected' : ''}
                aria-pressed={value === 'paused' ? undefined : filter === value}
                disabled={value === 'paused'}
                title={value === 'paused' ? 'The curated registry does not expose a pause state.' : undefined}
                onClick={() => { setFilter(value); setPage(0); }}
              >
                {value[0].toUpperCase() + value.slice(1)}
              </button>
            ))}
          </div>
          <label className="admin-sources-search">
            <Search size={15} aria-hidden="true" />
            <input
              type="search"
              value={search}
              onChange={(event) => { setSearch(event.target.value); setPage(0); }}
              placeholder="Search sources..."
              aria-label="Search discovery sources"
            />
          </label>
        </div>

        <p className="admin-sources-note">
          Active means eligible under the curated source rules; run status reflects recorded history, not scheduler health. Candidate counts include all recorded review items from each source, not only pending items. Add, edit, and pause are unavailable.
        </p>
        {error && <RetryNotice message={error} onRetry={retry} />}
        {!sources && loading && <p className="admin-sr-only" role="status">Loading discovery sources</p>}

        <div className="admin-table-scroll admin-sources-table-scroll">
          <table className="admin-table admin-sources-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>URL</th>
                <th>Type</th>
                <th>Latest status</th>
                <th>Last checked</th>
                <th>Review candidates</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {!sources && loading && Array.from({ length: SOURCE_PAGE_SIZE }, (_, index) => (
                <tr className="admin-skeleton-row" key={`source-skeleton-${index}`} aria-hidden="true">
                  <td><span className="admin-skeleton-line is-long" /></td>
                  <td><span className="admin-skeleton-line" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                  <td><span className="admin-skeleton-pill" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                  <td><span className="admin-skeleton-line is-short" /></td>
                  <td><span className="admin-skeleton-actions" /></td>
                </tr>
              ))}
              {pageSources.map((source) => (
                <tr key={source.source_id}>
                  <td>
                    <strong className="admin-source-name">{source.name}</strong>
                    <small>{source.country_or_region}</small>
                  </td>
                  <td>
                    <a className="admin-source-url" href={source.source_url} target="_blank" rel="noreferrer">
                      {source.official_domain}
                    </a>
                  </td>
                  <td><span className="admin-source-type">{source.category.replace(/_/g, ' ')}</span></td>
                  <td><span className={`admin-source-status is-${source.status}`}>{statusLabels[source.status] || 'Unknown'}</span></td>
                  <td>{formatCheckedAt(source.last_checked)}</td>
                  <td>{Number.isFinite(source.review_candidates) ? source.review_candidates : '—'}</td>
                  <td>
                    <div className="admin-source-actions" title="Source management is not available in Admin.">
                      <button type="button" disabled>Edit</button>
                      <span aria-hidden="true">·</span>
                      <button type="button" disabled>Pause</button>
                    </div>
                  </td>
                </tr>
              ))}
              {sources && !loading && visibleSources.length === 0 && (
                <tr><td className="admin-sources-empty" colSpan="7">No sources match these filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {sources && (
          <footer className="admin-sources-pagination">
            <span>
              Showing {visibleSources.length ? currentPage * SOURCE_PAGE_SIZE + 1 : 0}–{Math.min((currentPage + 1) * SOURCE_PAGE_SIZE, visibleSources.length)} of {visibleSources.length}
            </span>
            <div>
              <button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)} aria-label="Previous source page">
                <ArrowLeft size={14} aria-hidden="true" /> Prev
              </button>
              <button type="button" disabled={currentPage >= pageCount - 1} onClick={() => setPage(currentPage + 1)} aria-label="Next source page">
                Next <ArrowRight size={14} aria-hidden="true" />
              </button>
            </div>
          </footer>
        )}
      </section>
    </div>
  );
}

const VERIFICATION_CHECKLIST = [
  { key: 'source', label: 'Official source opens', note: 'Link loads and belongs to the provider' },
  { key: 'deadline', label: 'Deadline matches', note: 'Date agrees with the official page' },
  { key: 'award', label: 'Award amount matches', note: 'Funding details are accurate' },
  { key: 'eligibility', label: 'Eligibility matches', note: 'Country, level and field requirements' },
  { key: 'application', label: 'Application link works', note: 'Leads to the real application' },
];

function VerificationDetails({ token, scholarshipId, onChanged }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);
  const [notes, setNotes] = useState('');
  const [checks, setChecks] = useState({});
  const [acknowledgedConflicts, setAcknowledgedConflicts] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [requestGuard] = useState(createLatestRequestGuard);

  const load = useCallback(() => {
    const requestId = requestGuard.begin();
    adminApi.detail(token, scholarshipId)
      .then((data) => {
        if (requestGuard.isCurrent(requestId)) {
          setDetail(data);
          setNotes(data.scholarship.verification_notes || '');
          setLoadError('');
          setLoading(false);
        }
      })
      .catch((failure) => {
        if (requestGuard.isCurrent(requestId)) {
          setLoadError(failure.message);
          setLoading(false);
        }
      });
  }, [requestGuard, token, scholarshipId]);

  useEffect(() => {
    load();
    return () => requestGuard.invalidate();
  }, [load, refresh, requestGuard]);

  const retry = () => {
    requestGuard.invalidate();
    setLoadError('');
    setLoading(true);
    setRefresh((value) => value + 1);
  };
  const scholarship = detail?.scholarship;
  const officialUrl = scholarship?.official_info_url || scholarship?.official_url;
  const hasConflicts = Boolean(detail?.issues.some((issue) => issue.code === 'conflict'));
  const allChecksComplete = VERIFICATION_CHECKLIST.every(({ key }) => checks[key]);
  const verifiedBy = detail?.audit.find((entry) => entry.action === 'verification')?.actor_email || '—';
  const alreadyNeedsRecheck = Boolean(detail?.issues.some((issue) => issue.code === 'needs_reverification'));

  const markVerified = async () => {
    setActionError('');
    setNotice('');
    setSaving(true);
    const today = new Date();
    const verifiedOn = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    const checklistNote = VERIFICATION_CHECKLIST.map(({ label }) => label).join('; ');
    try {
      const updated = await adminApi.verify(token, scholarshipId, {
        status: 'verified',
        basis: 'official_source',
        source_url: officialUrl,
        verified_on: verifiedOn,
        notes: `${notes.trim()}\nChecklist confirmed: ${checklistNote}`,
        evidence_reviewed: true,
        acknowledge_conflicts: hasConflicts && acknowledgedConflicts,
      });
      setDetail(updated);
      setNotice('Scholarship marked verified.');
      onChanged();
    } catch (failure) {
      setActionError(failure.message);
    } finally {
      setSaving(false);
    }
  };

  const flagForRecheck = async () => {
    setActionError('');
    setNotice('');
    setSaving(true);
    try {
      const updated = await adminApi.flag(token, scholarshipId, {
        flag: 'needs_reverification',
        active: true,
        ...(notes.trim() ? { note: notes.trim() } : {}),
      });
      setDetail(updated);
      setNotice('Flagged for recheck. Verification status was not changed.');
      onChanged();
    } catch (failure) {
      setActionError(failure.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside className="admin-card admin-verification-details" aria-label="Verification checklist">
      <h2>Verification checklist</h2>
      {loading && <p role="status">Loading scholarship details...</p>}
      {loadError && <RetryNotice message={loadError} onRetry={retry} />}
      {!loading && !loadError && !detail && <p>Select a scholarship to start verifying it.</p>}
      {detail && (
        <>
          {!loading && (
            <p className="admin-verification-prompt">
              {scholarship.name} · {scholarship.verification_status || 'unverified'}
            </p>
          )}
          {notice && <p className="admin-notice is-success" role="status">{notice}</p>}
          {actionError && <p className="admin-notice is-error" role="alert">{actionError}</p>}
          <div className="admin-verification-checklist">
            {VERIFICATION_CHECKLIST.map(({ key, label, note }) => (
              <label className="admin-verification-check" key={key}>
                <input
                  type="checkbox"
                  checked={Boolean(checks[key])}
                  onChange={(event) => setChecks((current) => ({ ...current, [key]: event.target.checked }))}
                  disabled={saving || loading}
                />
                <span><strong>{label}</strong><small>{note}</small></span>
              </label>
            ))}
          </div>
          {hasConflicts && (
            <label className="admin-verification-conflict">
              <input
                type="checkbox"
                checked={acknowledgedConflicts}
                onChange={(event) => setAcknowledgedConflicts(event.target.checked)}
                disabled={saving || loading}
              />
              I reviewed and acknowledge the listed conflicts.
            </label>
          )}
          <label className="admin-verification-notes">
            <span>Add notes about what you checked</span>
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              maxLength={1000}
              rows={3}
              disabled={saving || loading}
              placeholder="Record evidence and verification notes (at least 10 characters)"
            />
          </label>
          <dl className="admin-verification-meta">
            <div><dt>Verified by</dt><dd>{scholarship.verification_status === 'verified' ? verifiedBy : '—'}</dd></div>
            <div><dt>Verified on</dt><dd>{scholarship.last_verified_date ? formatRunTime(scholarship.last_verified_date) : '—'}</dd></div>
          </dl>
          <div className="admin-verification-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving || loading || !allChecksComplete || notes.trim().length < 10 || !officialUrl || (hasConflicts && !acknowledgedConflicts)}
              onClick={markVerified}
              title={!allChecksComplete ? 'Complete each verification check first.' : undefined}
            >
              {saving ? 'Saving...' : 'Mark verified'}
            </button>
            <button
              type="button"
              className="btn btn-outline"
              disabled={saving || loading || alreadyNeedsRecheck}
              onClick={flagForRecheck}
            >
              Flag for recheck
            </button>
            {officialUrl
              ? <a className="btn btn-outline" href={officialUrl} target="_blank" rel="noreferrer">Open official source</a>
              : <button type="button" className="btn btn-outline" disabled>No official source</button>}
          </div>
          <p className="admin-verification-safety-note">
            Checklist confirmations are included in the verification audit note. Conflicts must be acknowledged before verification.
          </p>
        </>
      )}
      {!detail && !loading && !loadError && (
        <>
          <div className="admin-verification-checklist is-placeholder">
            {VERIFICATION_CHECKLIST.map(({ key, label, note }) => (
              <label className="admin-verification-check" key={key}>
                <input type="checkbox" disabled />
                <span><strong>{label}</strong><small>{note}</small></span>
              </label>
            ))}
          </div>
          <textarea className="admin-verification-placeholder-notes" disabled placeholder="Add notes about what you checked" />
          <dl className="admin-verification-meta">
            <div><dt>Verified by</dt><dd>—</dd></div>
            <div><dt>Verified on</dt><dd>—</dd></div>
          </dl>
          <div className="admin-verification-actions">
            <button type="button" className="btn btn-primary" disabled>Mark verified</button>
            <button type="button" className="btn btn-outline" disabled>Flag for recheck</button>
            <button type="button" className="btn btn-outline" disabled>Open official source</button>
          </div>
        </>
      )}
    </aside>
  );
}

function VerificationQueue({ token }) {
  const [status, setStatus] = useState('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [result, setResult] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [requestGuard] = useState(createLatestRequestGuard);

  const load = useCallback(() => {
    const requestId = requestGuard.begin();
    const query = new URLSearchParams({
      skip: String(page * PAGE_SIZE),
      limit: String(PAGE_SIZE),
      archived: 'false',
    });
    if (status === 'verified' || status === 'unverified') query.set('verification', status);
    if (status === 'needs_recheck') query.set('issue', 'verification_recheck');
    if (search.trim()) query.set('q', search.trim());
    adminApi.list(token, query.toString())
      .then((data) => {
        if (requestGuard.isCurrent(requestId)) {
          setResult(data);
          setError('');
          setLoading(false);
        }
      })
      .catch((failure) => {
        if (requestGuard.isCurrent(requestId)) {
          setError(failure.message);
          setLoading(false);
        }
      });
  }, [requestGuard, token, status, search, page]);

  useEffect(() => {
    load();
    return () => requestGuard.invalidate();
  }, [load, refresh, requestGuard]);

  const updateQuery = (update) => {
    requestGuard.invalidate();
    setResult(null);
    setError('');
    setLoading(true);
    setPage(0);
    setSelectedId(null);
    update();
  };
  const retry = () => {
    requestGuard.invalidate();
    setResult(null);
    setError('');
    setLoading(true);
    setRefresh((value) => value + 1);
  };
  const changePage = (nextPage) => {
    requestGuard.invalidate();
    setResult(null);
    setError('');
    setLoading(true);
    setSelectedId(null);
    setPage(nextPage);
  };
  const refreshList = useCallback(() => {
    requestGuard.invalidate();
    setResult(null);
    setLoading(true);
    setRefresh((value) => value + 1);
  }, [requestGuard]);

  const filters = [
    { value: 'all', label: 'All' },
    { value: 'unverified', label: 'Unverified' },
    { value: 'needs_recheck', label: 'Needs recheck' },
    { value: 'verified', label: 'Verified' },
  ];
  const rows = result?.items || [];
  const pageCount = result ? Math.ceil(result.total / PAGE_SIZE) : 0;
  const rowStatus = (row) => {
    if (row.issues.some((issue) => ['needs_reverification', 'stale_verification'].includes(issue.code))) return 'needs_recheck';
    if (row.issues.some((issue) => issue.code === 'broken_source')) return 'source_unreachable';
    return row.verification_status === 'verified' ? 'verified' : 'unverified';
  };
  const statusLabels = {
    verified: 'Verified',
    needs_recheck: 'Needs recheck',
    source_unreachable: 'Source unreachable',
    unverified: 'Unverified',
  };

  return (
    <div className="admin-verification-page">
      <header className="admin-verification-page-header">
        <div>
          <h1>Verification</h1>
          <p>Confirm scholarship details against official sources before they show as verified.</p>
        </div>
      </header>
      <div className="admin-verification-workspace">
        <section className="admin-card admin-verification-list" aria-label="Scholarships to verify">
          <div className="admin-verification-toolbar">
            <div className="admin-verification-filters" role="group" aria-label="Filter scholarships by verification">
              {filters.map((filter) => (
                <button
                  type="button"
                  key={filter.value}
                  className={status === filter.value ? 'is-selected' : ''}
                  aria-pressed={status === filter.value}
                  onClick={() => { if (status !== filter.value) updateQuery(() => setStatus(filter.value)); }}
                >
                  {filter.label}
                </button>
              ))}
            </div>
            <label className="admin-verification-search">
              <Search size={15} aria-hidden="true" />
              <input
                type="search"
                value={search}
                onChange={(event) => updateQuery(() => setSearch(event.target.value))}
                placeholder="Search scholarship or provider"
                aria-label="Search scholarships for verification"
              />
            </label>
          </div>
          {error && <RetryNotice message={error} onRetry={retry} />}
          <div className="admin-table-scroll admin-verification-table-scroll">
            <table className="admin-table admin-verification-table">
              <thead>
                <tr>
                  <th>Scholarship</th>
                  <th>Provider</th>
                  <th>Last verified</th>
                  <th>Official source</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {!result && loading && Array.from({ length: 5 }, (_, index) => (
                  <tr className="admin-skeleton-row" key={`verification-skeleton-${index}`} aria-hidden="true">
                    <td><span className="admin-skeleton-line is-long" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                    <td><span className="admin-skeleton-line" /></td>
                    <td><span className="admin-skeleton-pill" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                  </tr>
                ))}
                {result && !loading && rows.length === 0 && (
                  <tr><td className="admin-verification-empty" colSpan="6">No scholarships match this filter.</td></tr>
                )}
                {result && !loading && rows.map((row) => {
                  const currentStatus = rowStatus(row);
                  return (
                    <tr key={row.id} className={selectedId === row.id ? 'is-selected' : ''}>
                      <td><strong>{row.name}</strong></td>
                      <td>{row.provider || '—'}</td>
                      <td>{row.last_verified_date ? formatRunTime(row.last_verified_date) : '—'}</td>
                      <td>
                        {row.official_source_url
                          ? <a href={row.official_source_url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>Official source</a>
                          : '—'}
                      </td>
                      <td><span className={`admin-verification-status is-${currentStatus}`}>{statusLabels[currentStatus]}</span></td>
                      <td><button type="button" className="admin-verification-review" onClick={() => setSelectedId(row.id)}>Review</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="admin-verification-legend" aria-label="Verification status key">
            <span>Status key:</span>
            <span className="admin-verification-status is-verified">Verified</span>
            <span className="admin-verification-status is-needs_recheck">Needs recheck</span>
            <span className="admin-verification-status is-source_unreachable">Source unreachable</span>
            <span className="admin-verification-status is-unverified">Unverified</span>
          </div>
          {result && (
            <footer className="admin-verification-pagination">
              <span>
                Showing {result.total === 0 ? 0 : page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, result.total)} of {result.total}
              </span>
              <div>
                <button type="button" disabled={loading || page === 0} onClick={() => changePage(page - 1)}>
                  <ArrowLeft size={14} aria-hidden="true" /> Previous
                </button>
                <button type="button" disabled={loading || !pageCount || page + 1 >= pageCount} onClick={() => changePage(page + 1)}>
                  Next <ArrowRight size={14} aria-hidden="true" />
                </button>
              </div>
            </footer>
          )}
        </section>
        {selectedId
          ? <VerificationDetails key={selectedId} token={token} scholarshipId={selectedId} onChanged={refreshList} />
          : <VerificationDetailsEmpty />}
      </div>
    </div>
  );
}

function VerificationDetailsEmpty() {
  return (
    <aside className="admin-card admin-verification-details" aria-label="Verification checklist">
      <h2>Verification checklist</h2>
      <p className="admin-verification-prompt">Select a scholarship to start verifying it.</p>
      <div className="admin-verification-checklist is-placeholder">
        {VERIFICATION_CHECKLIST.map(({ key, label, note }) => (
          <label className="admin-verification-check" key={key}>
            <input type="checkbox" disabled />
            <span><strong>{label}</strong><small>{note}</small></span>
          </label>
        ))}
      </div>
      <textarea className="admin-verification-placeholder-notes" disabled placeholder="Add notes about what you checked" />
      <dl className="admin-verification-meta">
        <div><dt>Verified by</dt><dd>—</dd></div>
        <div><dt>Verified on</dt><dd>—</dd></div>
      </dl>
      <div className="admin-verification-actions">
        <button type="button" className="btn btn-primary" disabled>Mark verified</button>
        <button type="button" className="btn btn-outline" disabled>Flag for recheck</button>
        <button type="button" className="btn btn-outline" disabled>Open official source</button>
      </div>
    </aside>
  );
}

export default function AdminScholarships() {
  const { token } = useAuth();
  const [searchParams] = useSearchParams();
  const requestedSection = searchParams.get('section') || 'dashboard';
  const tab = ['dashboard', 'records', 'duplicates', 'discovery', 'sources', 'reviews', 'verification', 'history', 'publications'].includes(requestedSection)
    ? requestedSection
    : 'dashboard';
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [verification, setVerification] = useState('');
  const [issue, setIssue] = useState('');
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(0);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (tab !== 'records') return undefined;
    let current = true;
    const query = new URLSearchParams({ skip: String(page * PAGE_SIZE), limit: String(PAGE_SIZE), archived: String(archived) });
    if (search.trim()) query.set('q', search.trim());
    if (verification) query.set('verification', verification);
    if (issue) query.set('issue', issue);
    adminApi.list(token, query.toString())
      .then((list) => { if (current) { setRows(list); setError(''); } })
      .catch((failure) => { if (current) setError(failure.message); });
    return () => { current = false; };
  }, [token, search, verification, issue, archived, page, retry, tab]);

  const change = (setter) => (value) => { setter(value); setPage(0); };
  if (tab === 'dashboard') return <AdminDashboard token={token} />;

  const sectionTitles = {
    records: ['Scholarships', 'Manage verified and unverified scholarship records.'],
    duplicates: ['Duplicates', 'Find and review scholarship records that may describe the same award.'],
    discovery: ['Automated Discovery', 'Scheduler configuration and recent discovery run monitoring.'],
    sources: ['Discovery Sources', 'Review the curated sources used by scholarship discovery.'],
    reviews: ['Discovery Review Queue', 'Review candidates before accepting them as scholarship records.'],
    verification: ['Verification', 'Confirm scholarship details against official sources before they show as verified.'],
    history: ['Discovery History', 'Review the recorded outcomes of scholarship discovery runs.'],
    publications: ['Discovery Publications', 'Inspect approved snapshots, source evidence, freshness, and publication lifecycle.'],
  };
  const [title, subtitle] = sectionTitles[tab];

  return (
    <div className={`page-container admin-page${tab === 'records' ? ' admin-records-page' : ''}${tab === 'discovery' || tab === 'sources' ? ' admin-discovery-shell' : ''}${tab === 'reviews' ? ' admin-review-shell' : ''}${tab === 'verification' ? ' admin-verification-shell' : ''}${tab === 'duplicates' ? ' admin-duplicates-shell' : ''}${tab === 'history' ? ' admin-history-shell' : ''}`}>
      {tab !== 'discovery' && tab !== 'sources' && tab !== 'reviews' && tab !== 'verification' && tab !== 'duplicates' && tab !== 'history' && tab !== 'publications' && (
        <header className="admin-header">
          <div>
            <h1>{title}</h1>
            <p className="admin-muted">{subtitle}</p>
          </div>
          {tab === 'records' && (
            <Link className="btn btn-primary" to="/admin/scholarships/new"><Plus size={16} aria-hidden="true" /> Add scholarship</Link>
          )}
        </header>
      )}

      {tab === 'discovery' ? <DiscoveryMonitoring token={token} view="overview" />
        : tab === 'history' ? <DiscoveryHistory token={token} />
        : tab === 'sources' ? <DiscoverySources token={token} />
        : tab === 'verification' ? <VerificationQueue token={token} />
        : tab === 'reviews' ? <DiscoveryReviewQueue token={token} />
          : tab === 'publications' ? <AdminScholarshipPublications token={token} />
          : tab === 'duplicates' ? <Duplicates token={token} /> : (
        <section className="admin-card" aria-label="Scholarship records">
          <div className="admin-record-toolbar">
            <div className="admin-verification-filters" role="group" aria-label="Filter by verification status">
              <button type="button" aria-pressed={!verification} onClick={() => change(setVerification)('')}>All</button>
              <button type="button" aria-pressed={verification === 'verified'} onClick={() => change(setVerification)('verified')}>Verified</button>
              <button type="button" aria-pressed={verification === 'unverified'} onClick={() => change(setVerification)('unverified')}>Unverified</button>
            </div>
            <label className="admin-search">
              <Search size={15} aria-hidden="true" />
              <input type="search" value={search} onChange={(event) => change(setSearch)(event.target.value)} placeholder="Search name, provider or country" aria-label="Search records" />
            </label>
          </div>
          <details className="admin-record-more-filters">
            <summary>More filters{issue || archived ? ' · Active' : ''}</summary>
            <div className="admin-record-more-controls">
              <label>
                Data quality
                <select value={issue} onChange={(event) => change(setIssue)(event.target.value)} aria-label="Filter by data quality issue">
                  {ISSUE_FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <label className="admin-check">
                <input type="checkbox" checked={archived} onChange={(event) => change(setArchived)(event.target.checked)} /> Archived records
              </label>
            </div>
          </details>
          {error && <RetryNotice message={error} onRetry={() => setRetry((value) => value + 1)} />}
          {!rows && !error && <p className="admin-sr-only" role="status">Loading scholarship records</p>}
          <div className="admin-table-scroll">
            <table className="admin-table admin-records-table">
              <thead>
                <tr><th>Scholarship</th><th>Provider</th><th>Country</th><th>Deadline</th><th>Verification</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {!rows && !error && Array.from({ length: 5 }, (_, index) => (
                  <tr className="admin-skeleton-row" key={`skeleton-${index}`} aria-hidden="true">
                    <td><span className="admin-skeleton-line is-long" /></td>
                    <td><span className="admin-skeleton-line" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                    <td><span className="admin-skeleton-pill" /></td>
                    <td><span className="admin-skeleton-actions" /></td>
                  </tr>
                ))}
                {rows?.items.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link className="admin-record-name" to={`/admin/scholarships/${row.id}`}>{row.name}</Link>
                      {row.issues.length > 0 && <small className="admin-record-issues" title={row.issues.map((item) => item.label).join(', ')}>
                        {row.issues.length} item{row.issues.length === 1 ? '' : 's'} need attention
                      </small>}
                    </td>
                    <td>{row.provider || '—'}</td>
                    <td>{row.country?.replace(/\s*\(.*\)\s*$/, '') || '—'}</td>
                    <td>{row.deadline || '—'}</td>
                    <td>
                      <span className={`admin-verification-badge is-${row.verification_status === 'verified' ? 'verified' : 'unverified'}`}>
                        {row.verification_status || 'Unverified'}
                      </span>
                    </td>
                    <td><Link className="admin-record-open" aria-label={`View and edit ${row.name}`} to={`/admin/scholarships/${row.id}`}>View · Edit</Link></td>
                  </tr>
                ))}
                {rows?.items.length === 0 && (
                  <tr><td className="admin-record-empty" colSpan="6">No scholarship records match these filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {rows && (
            <footer className="admin-records-footer">
              <span>Showing {rows.total === 0 ? 0 : page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, rows.total)} of {rows.total}</span>
              <nav aria-label="Record pages">
                <button type="button" className="btn btn-outline" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>Previous</button>
                <button type="button" className="btn btn-outline" disabled={(page + 1) * PAGE_SIZE >= rows.total} onClick={() => setPage((value) => value + 1)}>Next</button>
              </nav>
            </footer>
          )}
        </section>
      )}
    </div>
  );
}
