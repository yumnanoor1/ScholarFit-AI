import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Activity, ArrowLeft, ArrowRight, BookOpen, Building2, ChevronDown, ChevronRight, CircleCheck, ClipboardList, Clock3, CopyCheck,
  ExternalLink, Globe2, Info,
  ListChecks, Plus, Radar, Search, ShieldAlert, X,
} from 'lucide-react';
import DiscoveryAnalyticsChart from '../components/admin/DiscoveryAnalyticsChart.jsx';
import { useAuth } from '../context/AuthContext';
import { adminApi } from '../services/adminApi';
import {
  formatAbsoluteTime,
  formatDiscoveryDuration,
  formatDiscoverySourceFailure,
  getDiscoverySourceFailureDetails,
  formatDiscoveryWorkerError,
  formatFailureCount,
  formatRelativeTime,
  formatTimeWithRelative,
  getDiscoveryNextStep,
  getDiscoveryStatusLine,
  getDiscoveryWorkerStatusLabel,
  getLastFailureNote,
  getLastRunSummary,
  getManualRunPlan,
  getNextScheduledRunText,
  getDiscoveryAnalyticsCounts,
  getRunProgress,
  isDiscoveryWorkerActive,
} from '../services/discoveryMonitoringState.js';
import AdminScholarshipPublications from './AdminScholarshipPublications.jsx';
import {
  applyCandidateDraft,
  buildBulkDecisionSteps,
  buildEditableCandidateDraft,
  buildReviewDecisionPayload,
  canResolveSelection,
  createActionGuard,
  countExtractedFields,
  createLatestRequestGuard,
  DUPLICATE_REASON_TEXT,
  EDITABLE_CANDIDATE_FIELDS,
  findPossibleDuplicates,
  getExtractedFieldGroups,
  getCandidateDeadline,
  getCandidateEvidenceStrength,
  getDiscoveryCandidateCounts,
  getDuplicateResolution,
  getEvidenceQuoteFor,
  getReviewDecisionAnnouncement,
  getReviewQueueViewState,
  getReviewStatusLabel,
  getRunLabel,
  getSourceDomain,
  groupReviewReasons,
  hasCandidateEdits,
  isResolvableReviewItem,
  REVIEW_STATUS_LABELS,
} from '../services/discoveryReviewState.js';
import {
  buildComparisonView,
  describeResolveAction,
  filterDuplicatePairs,
  getDuplicateCounts,
  getDuplicateFilterOptions,
  getDuplicateStatusLabel,
  getPairKey,
  getPairMetaLine,
  getPairRowLabel,
  getResolveActions,
  getResolveAnnouncement,
} from '../services/duplicatesState.js';
import { ISSUE_FILTERS } from '../services/adminScholarshipForm';
import { humanizeEnum } from '../services/textFormat.js';
import './AdminScholarships.css';

const PAGE_SIZE = 25;
// Discovery runs take minutes per source; polling faster only adds requests.
const MONITORING_POLL_MS = 10000;
const REVIEW_FILTERS = [
  { value: 'all', label: 'All' },
  ...Object.entries(REVIEW_STATUS_LABELS).map(([value, label]) => ({
    value,
    label: value === 'pending' ? 'Needs Review' : label,
  })),
];

function formatReviewCount(value) {
  return Number.isInteger(value) && value >= 0 ? value.toLocaleString() : '—';
}

function RetryNotice({ message, onRetry }) {
  return (
    <p className="admin-notice is-error" role="alert">
      {message} <button type="button" className="admin-link" onClick={onRetry}>Try again</button>
    </p>
  );
}

/** A value clamped to three lines, with "Show more" when it overflows. */
function ClampedValue({ text, isLink }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return <span className="admin-duplicates-blank">—</span>;
  // Long enough that the clamp will bite; the exact height is the CSS's job.
  const clampable = text.length > 180;
  if (isLink) {
    return (
      <>
        <a
          className={`admin-duplicates-value${clampable && !expanded ? ' is-clamped' : ''}`}
          href={text}
          target="_blank"
          rel="noreferrer"
        >
          {text}
        </a>
        {clampable && (
          <button
            type="button"
            className="admin-link admin-duplicates-show-more"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
      </>
    );
  }
  return (
    <>
      <span className={`admin-duplicates-value${clampable && !expanded ? ' is-clamped' : ''}`}>
        {text}
      </span>
      {clampable && (
        <button
          type="button"
          className="admin-link admin-duplicates-show-more"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </>
  );
}

const comparisonSectionLabels = {
  Basics: 'Basic Information',
  Eligibility: 'Eligibility Requirements',
  Funding: 'Funding Information',
  Deadlines: 'Application Information',
  Links: 'Additional Details',
};

/** One collapsible field group. Open when it holds a difference. */
function ComparisonGroup({ group, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = `compare-group-${group.label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  return (
    <>
      <tbody className={`admin-duplicates-group-heading${open ? ' is-open' : ''}`}>
        <tr>
          <th colSpan={3} scope="rowgroup">
            <button
              type="button"
              className="admin-duplicates-group-row"
              aria-expanded={open}
              aria-controls={bodyId}
              onClick={() => setOpen((value) => !value)}
            >
              <span className="admin-duplicates-group-label">{group.label}</span>
              {group.differenceCount > 0 && (
                <span className="admin-duplicates-group-count">{group.differenceCount}</span>
              )}
              <ChevronDown size={15} className="admin-duplicates-group-chevron" aria-hidden="true" />
            </button>
          </th>
        </tr>
      </tbody>
      <tbody id={bodyId} className="admin-duplicates-group-body" hidden={!open}>
        {group.rows.map((row) => (
          <tr key={row.key} className={row.differs ? 'is-different' : 'is-same'}>
            <th scope="row" title={row.differs ? 'Values differ' : undefined}>
              {row.key === 'name' ? 'Scholarship name' : row.label}
            </th>
            <td><ClampedValue text={row.firstDisplay} isLink={row.isLink} /></td>
            <td><ClampedValue text={row.secondDisplay} isLink={row.isLink} /></td>
          </tr>
        ))}
      </tbody>
    </>
  );
}

function Duplicates({ token }) {
  const [pairs, setPairs] = useState(null);
  const [filter, setFilter] = useState('undecided');
  const [search, setSearch] = useState('');
  const [selectedKey, setSelectedKey] = useState(null);
  const [comparison, setComparison] = useState(null);
  // 2: differences only, by default.
  const [onlyDifferences, setOnlyDifferences] = useState(true);
  const [note, setNote] = useState('');
  const [pendingAction, setPendingAction] = useState(null);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState('');
  // Carries the pair it belongs to, so a stale message cannot show against a
  // different pair.
  const [compareFailure, setCompareFailure] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [listGuard] = useState(createLatestRequestGuard);
  const [compareGuard] = useState(createLatestRequestGuard);
  const [actionGuard] = useState(createActionGuard);

  const load = useCallback(() => {
    const requestId = listGuard.begin();
    adminApi.duplicates(token)
      .then((data) => {
        if (listGuard.isCurrent(requestId)) {
          setPairs(data);
          setError('');
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

  const counts = getDuplicateCounts(pairs);
  const visiblePairs = filterDuplicatePairs(pairs, { filter, search });

  // 3: auto-select, derived rather than synced. The first visible pair is
  // used whenever the stored key is not in the current list, so the compare
  // panel is never empty while pairs exist and no effect has to correct it.
  const activeKey = visiblePairs.some((pair) => getPairKey(pair) === selectedKey)
    ? selectedKey
    : (visiblePairs[0] ? getPairKey(visiblePairs[0]) : null);
  const selectedPair = visiblePairs.find((pair) => getPairKey(pair) === activeKey) || null;
  const firstId = selectedPair?.first_id ?? null;
  const secondId = selectedPair?.second_id ?? null;

  // The comparison follows the selection. Nothing is set synchronously here:
  // loading and failure are derived below from what has arrived.
  useEffect(() => {
    if (firstId === null || secondId === null) return undefined;
    const requestId = compareGuard.begin();
    const key = getPairKey({ first_id: firstId, second_id: secondId });
    adminApi.compare(token, firstId, secondId)
      .then((data) => {
        if (compareGuard.isCurrent(requestId)) setComparison({ ...data, key });
      })
      .catch((failure) => {
        if (compareGuard.isCurrent(requestId)) {
          setCompareFailure({ key, message: failure.message });
        }
      });
    return () => compareGuard.invalidate();
  }, [compareGuard, firstId, secondId, token, refresh]);

  const comparisonFor = comparison && comparison.key === activeKey ? comparison : null;
  const compareError = compareFailure && compareFailure.key === activeKey
    ? compareFailure.message
    : '';
  const compareLoading = Boolean(selectedPair) && !comparisonFor && !compareError;
  const view = comparisonFor
    ? buildComparisonView(comparisonFor.first, comparisonFor.second, { onlyDifferences })
    : null;
  const comparisonSections = view
    ? view.groups.map((group) => ({ ...group, label: comparisonSectionLabels[group.label] || group.label }))
    : [];

  const runAction = async () => {
    if (!pendingAction || !selectedPair) return;
    if (actionGuard.isActive()) return;
    if (!actionGuard.tryStart()) return;
    const action = pendingAction;
    setSaving(true);
    setError('');
    try {
      if (action.key === 'dismiss') {
        await adminApi.dismissDuplicatePair(token, {
          first_id: selectedPair.first_id,
          second_id: selectedPair.second_id,
          ...(note.trim() ? { note: note.trim() } : {}),
        });
      } else if (action.key === 'archive') {
        await adminApi.archive(token, action.recordId, note.trim() || 'Duplicate record');
      } else {
        await adminApi.markDuplicate(token, action.recordId, {
          duplicate_of_id: action.targetId,
          ...(note.trim() ? { note: note.trim() } : {}),
        });
      }
      setToast({ tone: 'success', text: getResolveAnnouncement(action) });
      setPendingAction(null);
      setNote('');
      setRefresh((value) => value + 1);
    } catch (failure) {
      setToast({ tone: 'error', text: failure.message });
      setPendingAction(null);
    } finally {
      actionGuard.finish();
      setSaving(false);
    }
  };

  const changeFilter = (value) => {
    setFilter(value);
    setSelectedKey(null);
    setToast(null);
  };

  const actions = getResolveActions(selectedPair);
  const pendingDescription = pendingAction
    ? describeResolveAction(pendingAction, selectedPair)
    : null;

  return (
    <div className="admin-review-page admin-duplicates-page">
      {/* 1: the Review Queue header, so both pages start at the same place. */}
      <header className="admin-review-page-header">
        <div>
          <h1>Duplicates</h1>
        </div>
        <button type="button" className="btn btn-outline" onClick={() => setRefresh((value) => value + 1)}>
          Refresh
        </button>
      </header>

      {toast && (
        <p className={`admin-notice ${toast.tone === 'error' ? 'is-error' : 'is-success'}`} role="status">
          {toast.text}
          {' '}
          <button type="button" className="admin-link" onClick={() => setToast(null)}>Dismiss</button>
        </p>
      )}
      {error && <RetryNotice message={error} onRetry={() => setRefresh((value) => value + 1)} />}

      {/* Keep the pair list above its comparison panel. */}
      <div className="admin-review-workspace admin-duplicates-workspace">
        <section className="admin-card admin-duplicates-list" aria-label="Possible duplicate pairs">
          {/* 4: the filters carry the counts, so there are no summary cards. */}
          <div className="admin-duplicates-toolbar">
            <div className="admin-duplicates-filters" role="group" aria-label="Filter duplicate pairs">
              {getDuplicateFilterOptions(counts).map((item) => (
                <button
                  type="button"
                  key={item.value}
                  className={filter === item.value ? 'is-selected' : ''}
                  aria-pressed={filter === item.value}
                  onClick={() => changeFilter(item.value)}
                >
                  {item.label} {pairs ? (
                    <span className="admin-duplicates-filter-count">{item.count}</span>
                  ) : null}
                </button>
              ))}
            </div>
            <label className="admin-duplicates-search">
              <Search size={15} aria-hidden="true" />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search name, country or provider"
                aria-label="Search duplicate pairs"
              />
            </label>
          </div>

          {/* 1: one compact row per pair. */}
          <ul className="admin-duplicates-pairs">
            {loading && !pairs && Array.from({ length: 5 }, (_, index) => (
              <li key={`duplicate-skeleton-${index}`} className="admin-duplicates-pair is-skeleton" aria-hidden="true">
                <span className="admin-skeleton-line is-long" />
                <span className="admin-skeleton-line is-short" />
              </li>
            ))}
            {pairs && visiblePairs.map((pair) => {
              const key = getPairKey(pair);
              const label = getPairRowLabel(pair);
              return (
                <li key={key}>
                  <button
                    type="button"
                    className={`admin-duplicates-pair${activeKey === key ? ' is-current' : ''}`}
                    aria-current={activeKey === key}
                    onClick={() => setSelectedKey(key)}
                  >
                    <span className="admin-duplicates-pair-name" title={label.showBoth ? `${label.name} / ${label.otherName}` : label.name}>
                      {label.showBoth ? `${label.name} / ${label.otherName}` : label.name}
                    </span>
                    <span className="admin-duplicates-pair-meta">{getPairMetaLine(pair)}</span>
                    <span className={`admin-duplicate-status is-${pair.status || 'needs_review'}`}>
                      {getDuplicateStatusLabel(pair.status)}
                    </span>
                  </button>
                </li>
              );
            })}
            {pairs && visiblePairs.length === 0 && (
              <li className="admin-duplicates-empty">
                {/* 8: an empty state with an icon. */}
                <div className="admin-review-empty-block">
                  <CopyCheck size={22} aria-hidden="true" />
                  <p>No possible duplicates right now.</p>
                </div>
              </li>
            )}
          </ul>
        </section>

        <section className="admin-card admin-duplicates-comparison" aria-label="Compare records">
          {!selectedPair && (
            <div className="admin-review-empty-block">
              <CopyCheck size={22} aria-hidden="true" />
              <p>Select a pair to compare it.</p>
            </div>
          )}
          {compareError && (
            <RetryNotice message={compareError} onRetry={() => setRefresh((value) => value + 1)} />
          )}
          {selectedPair && compareLoading && (
            <p className="admin-duplicates-prompt" role="status">Loading comparison…</p>
          )}

          {selectedPair && comparisonFor && view && (
            <>
              {/* 2: the header row stays put while the fields scroll. */}
              <div className="admin-duplicates-compare-head">
                <div className="admin-duplicates-compare-title">
                  <h2>Compare records</h2>
                  <label className="admin-duplicates-diff-toggle">
                    <input
                      type="checkbox"
                      checked={onlyDifferences}
                      onChange={(event) => setOnlyDifferences(event.target.checked)}
                    />
                    <span>Show only differences ({view.differenceCount})</span>
                  </label>
                </div>
              </div>

              <div className="admin-duplicates-compare-body">
                <table className="admin-duplicates-compare-table">
                  <colgroup>
                    <col style={{ width: '18%' }} />
                    <col style={{ width: '41%' }} />
                    <col style={{ width: '41%' }} />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">Field</th>
                      <th scope="col">Record A · #{comparisonFor.first.id}</th>
                      <th scope="col">Record B · #{comparisonFor.second.id}</th>
                    </tr>
                  </thead>
                  {/* Groups collapse; only those holding a difference open. */}
                  {comparisonSections.map((group) => (
                    <ComparisonGroup
                      key={`${activeKey}-${group.label}`}
                      group={group}
                      defaultOpen={group.differenceCount > 0}
                    />
                  ))}
                </table>

                {comparisonSections.length === 0 && (
                  <p className="admin-duplicates-prompt" role="status">
                    {onlyDifferences
                      ? 'These two records match on every compared field.'
                      : 'Neither record has any of the compared fields filled in.'}
                  </p>
                )}

                {/* 2: the identical fields as one line, not thirty rows. */}
                {onlyDifferences && view.hiddenCount > 0 && (
                  <p className="admin-duplicates-hidden-note">
                    {view.hiddenCount} identical field{view.hiddenCount === 1 ? '' : 's'} hidden
                    {' · '}
                    <button
                      type="button"
                      className="admin-link"
                      onClick={() => setOnlyDifferences(false)}
                    >
                      Show
                    </button>
                  </p>
                )}

                <p className="admin-duplicates-reference-counts">
                  Saved by students: <strong>{comparisonFor.first_references.saved_by_students}</strong>
                  {' / '}
                  <strong>{comparisonFor.second_references.saved_by_students}</strong>
                  {' · '}
                  Internal links: <strong>{comparisonFor.first_references.internal_links}</strong>
                  {' / '}
                  <strong>{comparisonFor.second_references.internal_links}</strong>
                </p>
              </div>

              {/* 2 and 6: the resolve bar stays visible while fields scroll. */}
              <div className="admin-duplicates-resolve">
                <div className="admin-field admin-duplicates-note">
                  <input
                    value={note}
                    maxLength={1000}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="Reason (optional)"
                    aria-label="Optional reason, kept in the change history"
                    disabled={saving}
                  />
                </div>
                <div className="admin-duplicates-resolve-actions">
                  {actions.map((action) => (
                    <button
                      key={action.key}
                      type="button"
                      className={`btn btn-${action.tone}`}
                      title={action.title}
                      disabled={saving}
                      onClick={() => setPendingAction(action)}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
                <p className="admin-duplicates-safety-note">
                  Marking a duplicate never merges or deletes records. Both are kept, with their
                  IDs and everything linked to them.
                </p>
              </div>
            </>
          )}
        </section>
      </div>

      {pendingAction && pendingDescription && (
        <ConfirmDialog
          title={pendingDescription.title}
          confirmLabel={pendingDescription.confirmLabel}
          busy={saving}
          onCancel={() => setPendingAction(null)}
          onConfirm={runAction}
          body={(
            <>
              <p>{pendingDescription.body}</p>
              {note.trim() && <p className="admin-discovery-config-note">Reason: {note.trim()}</p>}
            </>
          )}
        />
      )}
    </div>
  );
}

function AccordionSection({ id, label, count = null, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = `${id}-body`;
  return (
    <div className={`admin-review-accordion${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="admin-review-accordion-row"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="admin-review-accordion-label">{label}</span>
        {count !== null && <span className="admin-review-accordion-count">{count}</span>}
        <ChevronDown size={15} className="admin-review-accordion-chevron" aria-hidden="true" />
      </button>
      <div className="admin-review-accordion-body" id={bodyId} hidden={!open}>
        {children}
      </div>
    </div>
  );
}

function EvidenceQuote({ item, field }) {
  const quote = getEvidenceQuoteFor(item, field);
  if (!quote) return <span className="admin-review-quote-missing">No source quote</span>;
  return (
    <details className="admin-review-quote-details">
      <summary className="admin-chevron-summary">
        <ChevronRight size={14} aria-hidden="true" />
        {quote.kind === 'page' ? 'View page quote' : 'View source quote'}
      </summary>
      <p className={`admin-review-quote is-${quote.kind}`}>
        <q>{quote.quote}</q>
        {quote.kind === 'page' && (
          <span
            className="admin-review-quote-kind"
            title={`Stored as ${quote.key.replace(/_/g, ' ')}: a page-level quote, not a quote for this field alone`}
          >
            page quote
          </span>
        )}
      </p>
    </details>
  );
}

function ReviewEditableField({ item, field, label, type, value, disabled, onChange }) {
  const [expanded, setExpanded] = useState(false);
  const expandable = field === 'eligible_fields' && value.length > 140;
  return (
    <label className="admin-review-edit-field">
      <span>{label}</span>
      {field === 'eligible_fields' ? (
        <textarea
          rows={expandable && expanded ? 5 : 2}
          value={value}
          onChange={(event) => onChange(field, event.target.value)}
          placeholder="Not found on page"
          disabled={disabled}
        />
      ) : (
        <input
          type={type === 'date' ? 'text' : type}
          value={value}
          onChange={(event) => onChange(field, event.target.value)}
          placeholder={type === 'date' ? 'YYYY-MM-DD' : 'Not found on page'}
          disabled={disabled}
        />
      )}
      {expandable && (
        <button
          type="button"
          className="admin-review-expand-field"
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          Show {expanded ? 'less' : 'more'}
        </button>
      )}
      <EvidenceQuote item={item} field={field} />
    </label>
  );
}

function EvidenceMeter({ strength, needsChecks = false, compact = false, label = 'Evidence' }) {
  const percentage = strength.total > 0
    ? Math.round((strength.backed / strength.total) * 100)
    : 0;
  return (
    <div className="admin-review-evidence-meter" title={strength.title}>
      <div className="admin-review-evidence-summary">
        {!compact && <span className="admin-review-evidence-label">{label}</span>}
        <strong>{strength.backed}/{strength.total}{compact ? '' : ' fields quoted'}</strong>
        {needsChecks && (
          <span className="admin-review-evidence-warning">
            {compact ? null : <ShieldAlert size={13} aria-hidden="true" />}
            Checks needed
          </span>
        )}
      </div>
      <div
        className="admin-review-evidence-track"
        role="progressbar"
        aria-label="Source evidence coverage, not an eligibility score"
        aria-valuemin={0}
        aria-valuemax={Math.max(strength.total, 1)}
        aria-valuenow={strength.backed}
      >
        <span style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

function DuplicateBadge({ flag, item, itemsById, onPrefill }) {
  if (!flag) return null;
  const resolution = getDuplicateResolution(item, flag.matchIds, itemsById);
  return (
    <div className="admin-review-duplicate-flag">
      <p>
        <strong>
          <CopyCheck size={15} aria-hidden="true" />
          Possible duplicate of{' '}
          {flag.matchIds.map((id) => (
            <span className="admin-review-duplicate-id" key={id}>#{id}</span>
          ))}
        </strong>
        {` — ${DUPLICATE_REASON_TEXT[flag.reason] || flag.reason}.`}
      </p>
      {resolution.kind === 'scholarship' ? (
        <button
          type="button"
          className="admin-link"
          onClick={() => onPrefill(String(resolution.scholarshipId))}
        >
          {`Mark as duplicate of scholarship #${resolution.scholarshipId}`}
        </button>
      ) : (
        <p className="admin-review-duplicate-hint">
          A duplicate is recorded against an existing scholarship, so approve one of
          these candidates first, then mark the others duplicates of the scholarship it creates.
          Nothing is merged either way.
        </p>
      )}
    </div>
  );
}

function DiscoveryReviewCard({
  item,
  token,
  onDone,
  saving: bulkSaving = false,
  duplicateFlag = null,
  itemsById = null,
}) {
  const [draft, setDraft] = useState(() => buildEditableCandidateDraft(item));
  const [valuesText, setValuesText] = useState(() => JSON.stringify(item.extracted_values, null, 2));
  const [duplicateId, setDuplicateId] = useState('');
  const [linkTargetId, setLinkTargetId] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [actionGuard] = useState(createActionGuard);
  const [note, setNote] = useState('');
  const evidence = getCandidateEvidenceStrength(item);
  const { mustCheck, optional } = groupReviewReasons(item);
  const needsChecks = mustCheck.length > 0
    || item.missing_required_fields.length > 0
    || item.conflicting_values.length > 0;
  const resolvable = isResolvableReviewItem(item);
  const deadline = getCandidateDeadline(item);
  const run = getRunLabel(item);
  const sourceDomain = getSourceDomain(item);
  const country = item.host_country || item.extracted_values?.country || '';
  const degreeLevel = item.extracted_values?.degree_level || '';
  const edited = hasCandidateEdits(item, draft);
  const extractedGroups = getExtractedFieldGroups(item, {
    skip: EDITABLE_CANDIDATE_FIELDS.map((entry) => entry.field),
  });

  const setField = (field, value) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };

  // Approve/Reject straight from the panel, including for a pending
  // candidate: the backend requires it to be marked reviewed first, so that
  // call is made as part of the same click. Approval publishes the edited
  // values.
  const resolve = async (decision) => {
    if (actionGuard.isActive()) return;
    setError('');
    let steps;
    try {
      steps = buildBulkDecisionSteps(item, decision, { note, draft });
    } catch (failure) {
      setError(failure.message);
      return;
    }
    if (!actionGuard.tryStart()) return;
    setSaving(true);
    try {
      let updatedItem = item;
      for (const step of steps) {
        updatedItem = await adminApi.reviewDiscovery(token, item.id, step);
      }
      onDone(decision, updatedItem);
    } catch (failure) {
      setError(failure.message);
    } finally {
      actionGuard.finish();
      setSaving(false);
    }
  };

  const decide = async (decision) => {
    if (actionGuard.isActive()) return;
    setError('');
    let values;
    if (decision === 'accepted' || decision === 'link_and_publish') {
      if (editing) {
        try {
          values = JSON.parse(valuesText);
          if (!values || typeof values !== 'object' || Array.isArray(values)) {
            throw new Error('Publication values must be a JSON object.');
          }
        } catch (failure) {
          setError(failure instanceof SyntaxError ? 'Fix the candidate JSON before publishing.' : failure.message);
          return;
        }
      } else {
        values = applyCandidateDraft(item, draft);
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

  const busy = saving || bulkSaving;
  const helpText = 'Approval creates an unverified scholarship; link-and-publish keeps the '
    + 'existing canonical fields and records an approved discovery snapshot.';

  return (
    <aside className="admin-card admin-review-details" aria-label="Candidate details">
      <div className="admin-review-details-body">
        <header className="admin-review-details-header">
          <h2>Candidate Details</h2>
          <span className={`admin-review-status is-${item.review_status}`}>
            {getReviewStatusLabel(item.review_status)}
          </span>
        </header>
        <p className="admin-review-detail-intro">
          {item.candidate_name || item.extracted_values?.name || 'Unnamed scholarship'}
        </p>
        {(country || degreeLevel) && (
          <p className="admin-review-detail-subtitle">
            {country}{country && degreeLevel ? ' · ' : ''}{degreeLevel}
          </p>
        )}
        {error && <p className="admin-notice is-error" role="alert">{error}</p>}
        <DuplicateBadge
          flag={duplicateFlag}
          item={item}
          itemsById={itemsById}
          onPrefill={setDuplicateId}
        />

        <EvidenceMeter strength={evidence} needsChecks={needsChecks} label="Evidence Completeness" />

        {(country || degreeLevel || item.source_name || item.source_url) && (
          <>
            <h3 className="admin-review-section-label">Scholarship Information</h3>
            <dl className="admin-review-detail-fields admin-review-source-fields">
              {country && (
                <div>
                  <dt>Country</dt>
                  <dd>{country}</dd>
                </div>
              )}
              {degreeLevel && (
                <div>
                  <dt>Degree Level</dt>
                  <dd>{degreeLevel}</dd>
                </div>
              )}
              {item.source_name && (
                <div>
                  <dt>Source</dt>
                  <dd>{item.source_name}{sourceDomain ? ` · ${sourceDomain}` : ''}</dd>
                </div>
              )}
              {item.source_url && (
                <div>
                  <dt>Original URL</dt>
                  <dd>
                    <a href={item.source_url} target="_blank" rel="noreferrer">
                      {item.source_url} <ExternalLink size={12} aria-hidden="true" />
                    </a>
                  </dd>
                </div>
              )}
            </dl>
          </>
        )}

        <div className="admin-review-accordions">
          <AccordionSection id={`requirements-${item.id}`} label="Requirements">
            {resolvable && <p className="admin-review-accordion-note">Editable before approval.</p>}
            <div className="admin-review-edit-fields">
              {EDITABLE_CANDIDATE_FIELDS.map(({ field, label, type }) => (
                <ReviewEditableField
                  key={field}
                  item={item}
                  field={field}
                  label={label}
                  type={type}
                  value={draft[field] ?? ''}
                  disabled={busy || !resolvable}
                  onChange={setField}
                />
              ))}
            </div>
          </AccordionSection>
          {edited && (
            <p className="admin-review-edited-note" role="status">
              Edited. Approving publishes these values.
            </p>
          )}

          <AccordionSection id={`additional-${item.id}`} label="Additional details">
            <div className="admin-review-nested-accordions">
              <AccordionSection id={`record-${item.id}`} label="Record details">
                <dl className="admin-review-detail-fields">
                  <div>
                    <dt>Deadline</dt>
                    <dd>
                      {deadline.text}
                      {deadline.typeLabel && (
                        <span className="admin-review-field-tag">{deadline.typeLabel}</span>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Trust</dt>
                    <dd>{humanizeEnum(item.source_classification)}</dd>
                  </div>
                  <div>
                    <dt>Run</dt>
                    <dd title={run.title}>{run.text}</dd>
                  </div>
                </dl>
              </AccordionSection>
              {/* 5: every other populated field, grouped, with its quote.
                  The panel showed about 13 of a candidate's 38 values. */}
              {extractedGroups.map((group) => (
                <AccordionSection
                  key={`${item.id}-${group.label}`}
                  id={`extracted-${group.label.toLowerCase()}-${item.id}`}
                  label={group.label}
                  count={group.rows.length}
                >
                  <dl className="admin-review-extracted-fields">
                    {group.rows.map((row) => (
                      <div key={row.field}>
                        <dt>{row.label}</dt>
                        <dd>
                          <span className="admin-review-extracted-value">{row.value}</span>
                          {row.quote
                            ? (
                              <span className={`admin-review-quote is-${row.quoteKind}`}>
                                <q>{row.quote}</q>
                              </span>
                            )
                            : <span className="admin-review-quote is-missing">No quote found</span>}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </AccordionSection>
              ))}
              {(needsChecks || optional.length > 0) && (
                <AccordionSection id={`warnings-${item.id}`} label="Checks and warnings">
                  {item.missing_required_fields.length > 0 && (
                    <p className="admin-review-warning">
                      Missing: {item.missing_required_fields.join(', ')}
                    </p>
                  )}
                  {mustCheck.length > 0 && (
                    <ul className="admin-review-reason-list">
                      {mustCheck.map((reason) => (
                        <li key={reason.code} title={reason.code}>{reason.text}</li>
                      ))}
                    </ul>
                  )}
                  {optional.length > 0 && (
                    <ul className="admin-review-reason-list">
                      {optional.map((reason) => (
                        <li key={reason.code} title={reason.code}>{reason.text}</li>
                      ))}
                    </ul>
                  )}
                  {item.conflicting_values.length > 0 && (
                    <pre className="admin-discovery-json">{JSON.stringify(item.conflicting_values, null, 2)}</pre>
                  )}
                </AccordionSection>
              )}
              <AccordionSection id={`provenance-${item.id}`} label="Source evidence">
                {item.source_trust_basis && (
                  <p className="admin-review-accordion-note"><strong>Trust basis:</strong> {item.source_trust_basis}</p>
                )}
                <pre className="admin-discovery-json">{JSON.stringify(item.field_sources, null, 2)}</pre>
                {item.evidence_excerpts.map((source) => (
                  <section key={source.fingerprint} className="admin-import-evidence">
                    <p>
                      <strong>{source.source_name}</strong> · {humanizeEnum(source.source_classification)}
                      {' · '}<a href={source.source_url} target="_blank" rel="noreferrer">{source.source_url}</a>
                    </p>
                    <p><strong>Extracted values:</strong></p>
                    <pre className="admin-discovery-json">{JSON.stringify(source.extracted_values, null, 2)}</pre>
                    <p><strong>Evidence excerpts:</strong></p>
                    <pre className="admin-discovery-json">{JSON.stringify(source.evidence_excerpts, null, 2)}</pre>
                    {source.page_count && (
                      <p className="admin-review-accordion-note">
                        Page count: {source.page_count}; specific page references were not available.
                      </p>
                    )}
                  </section>
                ))}
              </AccordionSection>

              {resolvable && (
                <AccordionSection id={`advanced-${item.id}`} label="Advanced actions">
                  <label className="admin-field">
                    <span>Mark duplicate of existing scholarship ID</span>
                    <input
                      type="number"
                      min="1"
                      value={duplicateId}
                      onChange={(event) => setDuplicateId(event.target.value)}
                      disabled={busy}
                    />
                  </label>
                  <button
                    type="button"
                    className="btn btn-outline"
                    disabled={busy || !duplicateId}
                    onClick={() => decide('duplicate')}
                  >
                    Confirm duplicate
                  </button>
                  <label className="admin-field">
                    <span>Existing scholarship ID to link and publish</span>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={linkTargetId}
                      onChange={(event) => setLinkTargetId(event.target.value)}
                      disabled={busy}
                    />
                    <small>Publication records the approved discovery snapshot; it does not overwrite canonical scholarship fields.</small>
                  </label>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy || !linkTargetId}
                    onClick={() => decide('link_and_publish')}
                  >
                    Publish and link existing scholarship
                  </button>
                  <button type="button" className="admin-link" onClick={() => setEditing((value) => !value)}>
                    {editing ? 'Hide raw JSON' : 'Edit all fields as JSON'}
                  </button>
                  {editing && (
                    <label className="admin-field">
                      <span>Values to use when publishing (JSON)</span>
                      <textarea
                        className="admin-discovery-json-input"
                        rows={10}
                        value={valuesText}
                        onChange={(event) => setValuesText(event.target.value)}
                        disabled={busy}
                      />
                      <small>The JSON replaces the edited fields above when it is open.</small>
                    </label>
                  )}
                </AccordionSection>
              )}
            </div>
          </AccordionSection>
        </div>

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
        {!resolvable && <p className="admin-review-help-note">{helpText}</p>}
      </div>

      {resolvable && (
        <div className="admin-review-action-bar">
          <div className="admin-field admin-review-action-reason">
            <input
              type="text"
              maxLength={1000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Reason (optional)"
              aria-label="Optional review reason"
              disabled={busy}
            />
          </div>
          <div className="admin-review-action-buttons">
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy}
              onClick={() => resolve('accepted')}
            >
              {saving ? 'Working...' : 'Approve'}
            </button>
            <span
              className="admin-review-help-tip"
              tabIndex={0}
              role="note"
              aria-label={helpText}
              title={helpText}
            >
              <Info size={14} aria-hidden="true" />
            </span>
            <button
              type="button"
              className="btn btn-outline"
              disabled={busy}
              onClick={() => resolve('rejected')}
            >
              Reject
            </button>
          </div>
          {item.review_status === 'pending' && (
            <button
              type="button"
              className="admin-link admin-review-reviewed-only"
              disabled={busy}
              onClick={() => decide('reviewed')}
            >
              Mark reviewed only
            </button>
          )}
        </div>
      )}
    </aside>
  );
}

function DiscoveryReviewQueue({ token }) {
  const [status, setStatus] = useState('all');
  const [page, setPage] = useState(0);
  const [result, setResult] = useState(null);
  const [reviewCounts, setReviewCounts] = useState(null);
  const [reviewCountsError, setReviewCountsError] = useState('');
  const [error, setError] = useState('');
  const [bulkError, setBulkError] = useState('');
  const [loading, setLoading] = useState(true);
  const [announcement, setAnnouncement] = useState('');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkNote, setBulkNote] = useState('');
  const [bulkSaving, setBulkSaving] = useState(false);
  const [reasonOpen, setReasonOpen] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [requestGuard] = useState(createLatestRequestGuard);
  const [countRequestGuard] = useState(createLatestRequestGuard);

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

  useEffect(() => {
    const requestId = countRequestGuard.begin();
    Promise.all(REVIEW_FILTERS.map(async ({ value }) => {
      const data = await adminApi.discoveryReviews(
        token,
        value === 'all' ? undefined : value,
        0,
        1,
      );
      if (!Number.isInteger(data.total) || data.total < 0) {
        throw new Error('The review count response was invalid.');
      }
      return [value, data.total];
    })).then((entries) => {
      if (countRequestGuard.isCurrent(requestId)) {
        setReviewCounts(Object.fromEntries(entries));
        setReviewCountsError('');
      }
    }).catch((failure) => {
      if (countRequestGuard.isCurrent(requestId)) {
        setReviewCountsError(failure.message || 'Review counts could not be loaded.');
      }
    });
    return () => countRequestGuard.invalidate();
  }, [countRequestGuard, refresh, token]);

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
    setReviewCountsError('');
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
  const canBulkResolve = canResolveSelection(selectedItems);
  const alreadyResolved = selectedItems.filter((item) => !isResolvableReviewItem(item));
  // Flagging is advisory: it annotates the queue and merges nothing.
  const duplicateFlags = findPossibleDuplicates(pageItems);
  const itemsById = new Map(pageItems.map((item) => [item.id, item]));
  const toggleCandidate = (id, checked) => {
    setSelectedIds((current) => checked
      ? [...new Set([...current, id])]
      : current.filter((value) => value !== id));
    // Checking a row is also how an admin picks the one to look at.
    if (checked) setSelectedId(id);
    else if (selectedId === id) setSelectedId(null);
  };
  const togglePage = (checked) => {
    setSelectedIds(checked ? pageItems.map((item) => item.id) : []);
  };
  const clearSelection = () => {
    setSelectedIds([]);
    setReasonOpen(false);
  };
  const resolveSelected = async (decision) => {
    if (!canBulkResolve || bulkSaving) return;
    requestGuard.invalidate();
    setBulkSaving(true);
    setBulkError('');
    setAnnouncement('');
    setError('');
    let completed = 0;
    const skipped = [];
    try {
      for (const item of selectedItems) {
        if (!isResolvableReviewItem(item)) {
          skipped.push(item.id);
          continue;
        }
        // A pending candidate has to be marked reviewed before the backend
        // will resolve it; both calls happen here.
        // Bulk decisions publish the extracted values as they are; only the
        // details panel offers field edits.
        for (const step of buildBulkDecisionSteps(item, decision, { note: bulkNote })) {
          await adminApi.reviewDiscovery(token, item.id, step);
        }
        completed += 1;
      }
      const skippedNote = skipped.length
        ? ` ${skipped.length} already resolved candidate(s) were left unchanged.`
        : '';
      setAnnouncement(
        (decision === 'accepted'
          ? `${completed} candidate(s) approved; an unverified scholarship was created for each.`
          : `${completed} candidate(s) rejected; no scholarship was created.`) + skippedNote,
      );
      setSelectedIds([]);
      setSelectedId(null);
      setBulkNote('');
      setReasonOpen(false);
    } catch (failure) {
      setBulkError(completed
        ? `${completed} candidate(s) were resolved before the next action failed: ${failure.message}`
        : failure.message);
    } finally {
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
        </div>
        <div className="admin-review-pending-indicator" aria-label={`${formatReviewCount(reviewCounts?.pending)} candidates pending review`}>
          <Clock3 size={17} aria-hidden="true" />
          <span><strong>{formatReviewCount(reviewCounts?.pending)}</strong> pending review</span>
        </div>
      </header>
      {reviewCountsError && (
        <p className="admin-notice is-error" role="alert">
          Filter counts unavailable: {reviewCountsError}{' '}
          <button type="button" className="admin-link" onClick={retryLoad}>Retry</button>
        </p>
      )}
      {announcement && <p className="admin-notice is-success" role="status">{announcement}</p>}
      {alreadyResolved.length > 0 && (
        <p className="admin-notice" role="status">
          {alreadyResolved.length} selected candidate(s) are already resolved and will be left unchanged.
        </p>
      )}
      {bulkError && (
        <p className="admin-notice is-error" role="alert">
          {bulkError} <button type="button" className="admin-link" onClick={() => setBulkError('')}>Dismiss</button>
        </p>
      )}
      {viewState === 'error' && <RetryNotice message={error} onRetry={retryLoad} />}
      <div className="admin-review-workspace">
        <div className="admin-review-main">
          <div className="admin-review-summary" role="group" aria-label="Review status summary">
            <article className="admin-review-summary-card is-pending">
              <span className="admin-review-summary-icon"><Clock3 size={21} aria-hidden="true" /></span>
              <div><span>Pending</span><strong>{formatReviewCount(reviewCounts?.pending)}</strong></div>
            </article>
            <article className="admin-review-summary-card is-approved">
              <span className="admin-review-summary-icon"><CircleCheck size={21} aria-hidden="true" /></span>
              <div><span>Approved</span><strong>{formatReviewCount(reviewCounts?.accepted)}</strong></div>
            </article>
            <article className="admin-review-summary-card is-rejected">
              <span className="admin-review-summary-icon"><X size={21} aria-hidden="true" /></span>
              <div><span>Rejected</span><strong>{formatReviewCount(reviewCounts?.rejected)}</strong></div>
            </article>
          </div>
          <section className="admin-card admin-review-list" aria-label="Discovery candidates">
          {selectedItems.length > 0 && (
            <div className="admin-review-selection-bar" role="group" aria-label="Actions for the selected candidates">
              <span className="admin-review-selection-count">{selectedItems.length} selected</span>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!canBulkResolve || bulkSaving}
                onClick={() => resolveSelected('accepted')}
              >
                {bulkSaving ? 'Working...' : 'Approve'}
              </button>
              <button
                type="button"
                className="btn btn-outline"
                disabled={!canBulkResolve || bulkSaving}
                onClick={() => resolveSelected('rejected')}
              >
                Reject
              </button>
              <div className="admin-review-reason-popover">
                <button
                  type="button"
                  className="btn btn-outline"
                  aria-expanded={reasonOpen}
                  aria-controls="bulk-reason-popover"
                  disabled={bulkSaving}
                  onClick={() => setReasonOpen((value) => !value)}
                >
                  {bulkNote.trim() ? 'Reason added' : 'Add reason'}
                </button>
                <div id="bulk-reason-popover" className="admin-review-reason-popover-body" hidden={!reasonOpen}>
                  <label className="admin-field">
                    <span>Reason (optional)</span>
                    <input
                      type="text"
                      maxLength={1000}
                      value={bulkNote}
                      onChange={(event) => setBulkNote(event.target.value)}
                      placeholder="Recorded with the decision"
                      disabled={bulkSaving}
                    />
                  </label>
                  <button
                    type="button"
                    className="admin-link"
                    onClick={() => setReasonOpen(false)}
                  >
                    Done
                  </button>
                </div>
              </div>
              <button
                type="button"
                className="admin-link admin-review-selection-clear"
                disabled={bulkSaving}
                onClick={clearSelection}
              >
                <X size={13} aria-hidden="true" /> Clear
              </button>
            </div>
          )}
          <div className="admin-review-toolbar">
            <div className="admin-review-filters" role="group" aria-label="Filter candidates by review status">
              {REVIEW_FILTERS.map((filter) => (
                <button
                  type="button"
                  key={filter.value}
                  className={status === filter.value ? 'is-selected' : ''}
                  aria-pressed={status === filter.value}
                  disabled={bulkSaving}
                  onClick={() => changeStatus(filter.value)}
                >
                  {filter.label}
                  <span className="admin-review-filter-count">{formatReviewCount(reviewCounts?.[filter.value])}</span>
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
                  <th>Scholarship</th>
                  <th>Source</th>
                  <th>Discovered</th>
                  <th>Evidence</th>
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
                {viewState === 'results' && result.items.map((item) => {
                  const name = item.candidate_name || item.extracted_values?.name || 'Unnamed scholarship';
                  const flag = duplicateFlags.get(item.id);
                  const strength = getCandidateEvidenceStrength(item);
                  const { mustCheck } = groupReviewReasons(item);
                  const needsChecks = mustCheck.length > 0
                    || item.missing_required_fields.length > 0
                    || item.conflicting_values.length > 0;
                  return (
                    <tr
                      key={item.id}
                      className={`${selectedId === item.id ? 'is-current ' : ''}${selectedIds.includes(item.id) ? 'is-checked' : ''}`}
                      onClick={() => setSelectedId(item.id)}
                      onKeyDown={(event) => {
                        // Only the row itself: Space must still toggle the
                        // checkbox and Enter must still work in the name button.
                        if (event.target !== event.currentTarget) return;
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          setSelectedId(item.id);
                        }
                      }}
                      tabIndex={0}
                      aria-selected={selectedId === item.id}
                      style={{ cursor: 'pointer' }}
                    >
                    <td
                      className="admin-review-checkbox-cell"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(item.id)}
                        onChange={(event) => toggleCandidate(item.id, event.target.checked)}
                        aria-label={`Select ${item.candidate_name || 'unnamed candidate'}`}
                        disabled={bulkSaving}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="admin-review-candidate-button"
                        title={name}
                        onClick={() => setSelectedId(item.id)}
                      >
                        {name}
                      </button>
                      <small>{item.host_country || item.extracted_values?.country || 'Country not recorded'}</small>
                      {flag && (
                        <small
                          className="admin-review-duplicate-badge"
                          title={`Possible duplicate: ${DUPLICATE_REASON_TEXT[flag.reason] || flag.reason}. Nothing is merged.`}
                        >
                          <CopyCheck size={12} aria-hidden="true" />
                          <span>Duplicate of</span>
                          {flag.matchIds.map((id) => (
                            <strong key={id}>#{id}</strong>
                          ))}
                        </small>
                      )}
                    </td>
                    <td>
                      <div className="admin-review-source">
                        <span>{item.source_name || 'Source not recorded'}</span>
                        {getSourceDomain(item) && <small>{getSourceDomain(item)}</small>}
                      </div>
                    </td>
                    <td>
                      <time
                        className="admin-review-discovered"
                        dateTime={item.created_at || undefined}
                        title={formatAbsoluteTime(item.created_at) || undefined}
                      >
                        <span>{formatRelativeTime(item.created_at) || formatAbsoluteTime(item.created_at) || 'Not recorded'}</span>
                      </time>
                    </td>
                    <td>
                      <EvidenceMeter strength={strength} needsChecks={needsChecks} compact />
                    </td>
                    <td><span className={`admin-review-status is-${item.review_status}`}>{getReviewStatusLabel(item.review_status)}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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
        </div>
        {selectedItem
          ? (
            <DiscoveryReviewCard
              key={selectedItem.id}
              item={selectedItem}
              token={token}
              onDone={handleDone}
              saving={bulkSaving}
              duplicateFlag={duplicateFlags.get(selectedItem.id) || null}
              itemsById={itemsById}
            />
          )
          : (
            <aside className="admin-card admin-review-details admin-review-details-empty" aria-label="Candidate details">
              <div className="admin-review-empty-block">
                <span className="admin-review-empty-icon"><ClipboardList size={24} aria-hidden="true" /></span>
                <h2>Ready to review?</h2>
                <p>Select a scholarship candidate from the list to inspect its details, evidence, and verification status.</p>
                {Number.isInteger(reviewCounts?.pending) && (
                  <span className="admin-review-empty-pending">
                    {formatReviewCount(reviewCounts.pending)} candidates pending review
                  </span>
                )}
              </div>
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
                        <td><span className={`admin-review-status is-${item.review_status}`}>{getReviewStatusLabel(item.review_status)}</span></td>
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
                <div><strong>{humanizeEnum(run.trigger_type)}</strong><small>{formatRunTime(run.started_at)}</small></div>
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

/**
 * An in-page confirmation, not window.confirm.
 *
 * Escape cancels, the confirm button takes focus on open, and the backdrop is
 * a sibling button so a click outside also cancels without trapping anything.
 */
function ConfirmDialog({ title, body, confirmLabel, onConfirm, onCancel, busy = false }) {
  const confirmRef = useRef(null);
  useEffect(() => {
    confirmRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onCancel();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onCancel]);

  return (
    <div className="admin-modal-backdrop">
      <div
        className="admin-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="admin-modal-title"
      >
        <h2 id="admin-modal-title">{title}</h2>
        <div className="admin-modal-body">{body}</div>
        <div className="admin-modal-actions">
          <button type="button" className="btn btn-outline" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            ref={confirmRef}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Starting…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** A value that is configured on the server and cannot be changed here. */
function ReadOnlySetting({ label, description, badges }) {
  return (
    <div className="admin-discovery-setting">
      <div className="admin-discovery-setting-text">
        <strong>{label}</strong>
        {description && <p>{description}</p>}
      </div>
      <div className="admin-discovery-setting-values">
        {badges.map((badge) => (
          <span
            key={badge.text}
            className={`admin-discovery-config-badge${badge.tone ? ` is-${badge.tone}` : ''}`}
          >
            {badge.text}
          </span>
        ))}
        <span className="admin-discovery-config-note">Set in server configuration</span>
      </div>
    </div>
  );
}

function DiscoveryMonitoring({ token, view = 'overview' }) {
  const [monitoring, setMonitoring] = useState(null);
  const [error, setError] = useState('');
  const [manualError, setManualError] = useState('');
  const [manualMessage, setManualMessage] = useState('');
  const [manualSubmitting, setManualSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
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

  // Poll only while a run is actually active, only while the tab is visible,
  // and only ever through one interval. A hidden tab left polling for hours
  // is what buried the backend in requests.
  const workerActive = isDiscoveryWorkerActive(monitoring?.worker_status);
  useEffect(() => {
    if (!workerActive) return undefined;

    let intervalId = null;
    const stop = () => {
      if (intervalId !== null) {
        window.clearInterval(intervalId);
        intervalId = null;
      }
    };
    const start = () => {
      if (intervalId !== null) return;
      intervalId = window.setInterval(() => {
        setRefresh((value) => value + 1);
      }, MONITORING_POLL_MS);
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        setRefresh((value) => value + 1);
        start();
      } else {
        stop();
      }
    };

    if (document.visibilityState === 'visible') start();
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      stop();
    };
  }, [workerActive]);

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
      .then(() => {
        setConfirmOpen(false);
        setManualMessage('Manual discovery started.');
        setRefresh((value) => value + 1);
      })
      .catch((failure) => {
        setConfirmOpen(false);
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

  if (view === 'overview') {
    const statusLine = getDiscoveryStatusLine(monitoring);
    const runSummary = getLastRunSummary(monitoring);
    const manualPlan = getManualRunPlan(monitoring);
    const progress = getRunProgress(monitoring);
    const analytics = getDiscoveryAnalyticsCounts(monitoring);
    const pipelineRun = analytics.run;
    const nextStep = getDiscoveryNextStep(monitoring);
    const failureNote = getLastFailureNote(monitoring);
    const runStatus = pipelineRun?.display_status || pipelineRun?.status || workerStatus;
    const showTime = (value) => formatTimeWithRelative(value);
    const formatMetricValue = (value) => (
      value === null ? '—' : value.toLocaleString()
    );

    return (
      <div className="admin-discovery-page">
        <header className="admin-discovery-page-header">
          <div>
            <h1>Automated Discovery</h1>
          </div>
          <div className="admin-discovery-header-actions">
            {!monitoring && (
              <span className="admin-discovery-system-status" role="status">
                {loading ? 'Loading' : 'Monitoring unavailable'}
              </span>
            )}
            <button type="button" className="btn btn-outline" onClick={retry}>Refresh</button>
          </div>
        </header>

        {error && <RetryNotice message={error} onRetry={retry} />}

        <div className="admin-discovery-layout">
          <div className="admin-discovery-main">
            <section className="admin-discovery-panel" aria-label="Discovery controls">
              <header className="admin-discovery-panel-header">
                <h2>Automatic and manual discovery</h2>
              </header>

              {/* 1: read-only configuration reads as status, never as a control. */}
              <ReadOnlySetting
                label="Automatic runs"
                description="Scheduled discovery without anyone starting it"
                badges={[{
                  text: monitoring ? (monitoring.enabled ? 'On' : 'Off') : 'Unknown',
                  tone: monitoring?.enabled ? 'on' : 'off',
                }]}
              />
              <ReadOnlySetting
                label="Schedule"
                description="How often a scheduled run starts"
                badges={[{
                  text: monitoring ? `Every ${monitoring.interval_hours} hours` : 'Unknown',
                }]}
              />

              <div className="admin-discovery-setting">
                <div className="admin-discovery-setting-text">
                  <strong>Run discovery now</strong>
                  <p>
                    {workerStatus === 'interrupted_unknown'
                      ? monitoring.worker_recoverable
                        ? 'The last run was interrupted. Starting a new one will tidy it up.'
                        : 'The last run state cannot be verified. Refresh before retrying.'
                      : activeRun
                        ? 'A run is already going. Wait for it to finish.'
                        : workerStatus === 'submitting'
                          ? 'Starting the run.'
                          : workerStatus === 'starting'
                            ? 'Waiting for the worker to start.'
                            : 'Starts one run now. The automatic schedule is unchanged.'}
                  </p>
                </div>
                <div className="admin-discovery-setting-values">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => setConfirmOpen(true)}
                    disabled={manualSubmitting || workerBlocksSubmission || !monitoring}
                  >
                    {manualSubmitting || workerStatus === 'submitting'
                      ? 'Starting…'
                      : workerStatus === 'starting'
                        ? 'Starting…'
                        : workerStatus === 'running'
                          ? 'Run in progress'
                          : workerStatus === 'interrupted_unknown' && !monitoring?.worker_recoverable
                            ? 'State unverified'
                            : 'Run Discovery Now'}
                  </button>
                </div>
              </div>

              {manualError && <p className="admin-notice is-error" role="alert">{manualError}</p>}
              {manualMessage && !manualError && (
                <p className="admin-discovery-run-message" role="status">{manualMessage}</p>
              )}

              {/* 4: progress from the monitoring data already being polled. */}
              {progress && (
                <div className="admin-discovery-progress" role="status">
                  <span className="admin-discovery-progress-dot" aria-hidden="true" />
                  <div>
                    <strong>
                      {progress.sourceName || progress.stageLabel || workerStatusLabel}
                    </strong>
                    <p>
                      {[progress.position, progress.elapsed ? `${progress.elapsed} elapsed` : '']
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                  </div>
                </div>
              )}

              {/* 2: one line, in plain words, with the run id in the tooltip. */}
              {runSummary && !progress && (
                <p className="admin-discovery-run-summary" title={runSummary.title} role="status">
                  {runSummary.text}
                </p>
              )}
            </section>

            <section className="admin-discovery-panel" aria-label="Scholarship discovery analytics">
              <div className="admin-discovery-analytics-header">
                <div>
                  <h2>Scholarship discovery analytics</h2>
                  <p>Latest run outcomes and current review workload.</p>
                </div>
                <div className="admin-discovery-analytics-actions">
                  <Link className="admin-discovery-review-link" to="/admin/scholarships?section=reviews">
                    Review queue <ArrowRight size={13} aria-hidden="true" />
                  </Link>
                  {runIsActive && (
                    <span className="admin-discovery-live-status" role="status">
                      <Activity size={14} aria-hidden="true" />
                      Updating live
                    </span>
                  )}
                </div>
              </div>
              {pipelineRun && (
                <dl className="admin-discovery-analytics-summary">
                  <div>
                    <dt><Globe2 size={14} aria-hidden="true" /> Sources attempted / succeeded</dt>
                    <dd>
                      {formatMetricValue(analytics.sourcesAttempted)}
                      {' / '}
                      {formatMetricValue(analytics.sourcesSucceeded)}
                    </dd>
                  </div>
                  <div>
                    <dt><BookOpen size={14} aria-hidden="true" /> Candidates found</dt>
                    <dd>{formatMetricValue(analytics.candidatesFound)}</dd>
                  </div>
                  <div>
                    <dt><Activity size={14} aria-hidden="true" /> Run status</dt>
                    <dd>
                      <span className={`admin-discovery-run-status is-${runStatus}`}>
                        {humanizeEnum(runStatus)}
                      </span>
                    </dd>
                  </div>
                  <div>
                    <dt><Clock3 size={14} aria-hidden="true" /> Run duration</dt>
                    <dd>
                      {formatDiscoveryDuration(
                        pipelineRun.duration_seconds ?? monitoring?.worker_duration_seconds,
                      ) || '—'}
                    </dd>
                  </div>
                  <div>
                    <dt><Radar size={14} aria-hidden="true" /> Last run</dt>
                    <dd>
                      {pipelineRun.started_at
                        ? (
                          <time dateTime={pipelineRun.started_at}>
                            {formatAbsoluteTime(pipelineRun.started_at) || '—'}
                          </time>
                        )
                        : '—'}
                    </dd>
                  </div>
                </dl>
              )}
              <DiscoveryAnalyticsChart
                counts={analytics}
                hasRun={Boolean(pipelineRun)}
                loading={(loading && !monitoring) || (runIsActive && !pipelineRun)}
                error={!monitoring ? error : ''}
              />
              {pipelineRun?.display_status === 'failed' && !failureNote && (
                <p className="admin-discovery-analytics-error" role="alert">
                  {pipelineRun.error_summary || 'The latest discovery run failed.'}
                </p>
              )}
              {/* The failure detail remains linked to its full run history. */}
              {failureNote && (
                <p className="admin-discovery-failure-note" role="status">
                  {failureNote.text}
                  {' '}
                  <Link to="/admin/scholarships?section=history">See history</Link>
                </p>
              )}
            </section>
          </div>

          <aside className="admin-discovery-side">
            {/* 10: one next action, rather than a list of links. */}
            {nextStep && (
              <section
                className={`admin-discovery-panel admin-discovery-next-step${nextStep.cta === 'Review now' ? ' is-pending' : ''}`}
                aria-label="Next step"
              >
                <h2>Next step</h2>
                <p>{nextStep.text}</p>
                {nextStep.href && nextStep.cta && (
                  <Link className="btn btn-primary" to={nextStep.href}>
                    {nextStep.cta} <ArrowRight size={14} aria-hidden="true" />
                  </Link>
                )}
              </section>
            )}

            {/* 3: status and times only; the counts live in the pipeline. */}
            <section className="admin-discovery-panel" aria-label="Discovery overview">
              <h2>Overview</h2>
              <dl className="admin-discovery-overview">
                <div>
                  <dt>Status</dt>
                  <dd className="admin-discovery-overview-status">
                    <span className={`admin-discovery-overview-badge is-${monitoring ? (monitoring.enabled ? 'on' : 'off') : 'unknown'}`}>
                      {statusLine.automatic.replace('Automatic runs: ', '')}
                    </span>
                    <span className={`admin-discovery-overview-badge ${runIsActive ? 'is-running' : 'is-idle'}`}>
                      {statusLine.run}
                    </span>
                  </dd>
                </div>
                <div><dt>Last run</dt><dd>{showTime(lastRun?.started_at)}</dd></div>
                <div><dt>Next scheduled run</dt><dd>{getNextScheduledRunText(monitoring)}</dd></div>
                <div>
                  <dt>Manual run</dt>
                  <dd>
                    <span className={`admin-discovery-overview-badge ${monitoring?.current_manual_run?.status === 'running' ? 'is-running' : 'is-idle'}`}>
                      {monitoring?.current_manual_run?.status === 'running' ? 'In progress' : 'Not running'}
                    </span>
                  </dd>
                </div>
              </dl>
            </section>

            {/* 2: the developer-facing detail, out of the way but not lost. */}
            {monitoring && (
              <section className="admin-discovery-panel admin-discovery-technical" aria-label="Technical details">
                <AccordionSection id="discovery-technical" label="Technical details">
                  <dl className="admin-discovery-overview">
                    <div><dt>Worker</dt><dd>{workerStatusLabel}</dd></div>
                    {monitoring.worker_run_id && (
                      <div><dt>Run id</dt><dd className="admin-discovery-run-id">{monitoring.worker_run_id}</dd></div>
                    )}
                    {monitoring.worker_stage && (
                      <div><dt>Stage</dt><dd>{humanizeEnum(monitoring.worker_stage)}</dd></div>
                    )}
                    <div>
                      <dt>Worker duration</dt>
                      <dd>{formatDiscoveryDuration(monitoring.worker_duration_seconds) || '—'}</dd>
                    </div>
                    <div><dt>Scheduler process health</dt><dd>Not reported by this API</dd></div>
                    <div><dt>Last completed run</dt><dd>{showTime(monitoring.last_completed_run?.completed_at)}</dd></div>
                    <div><dt>Last failed run</dt><dd>{showTime(monitoring.last_failed_run?.completed_at)}</dd></div>
                    <div><dt>Last scheduled run</dt><dd>{showTime(monitoring.last_scheduled_run?.started_at)}</dd></div>
                    <div><dt>Review candidates</dt><dd>{candidateCounts.totalReviewCandidates}</dd></div>
                    <div><dt>Database</dt><dd>{monitoring.database_name}</dd></div>
                  </dl>
                  {monitoring.worker_error && (
                    <p className="admin-discovery-failure-note">{monitoring.worker_error}</p>
                  )}
                </AccordionSection>
              </section>
            )}
          </aside>
        </div>

        {confirmOpen && (
          <ConfirmDialog
            title="Run discovery now?"
            confirmLabel="Run discovery"
            busy={manualSubmitting}
            onCancel={() => setConfirmOpen(false)}
            onConfirm={runDiscoveryNow}
            body={(
              <>
                <p>
                  {manualPlan.sourceCount === null
                    ? 'This starts one discovery run over the sources set in the server configuration.'
                    : `This checks ${manualPlan.sourceCount} source${manualPlan.sourceCount === 1 ? '' : 's'} and usually takes about ${manualPlan.lowerMinutes}–${manualPlan.upperMinutes} minutes.`}
                </p>
                <p className="admin-discovery-config-note">
                  Candidates go to the Review Queue. Nothing reaches students without your approval.
                </p>
              </>
            )}
          />
        )}
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
              <strong>{monitoring.enabled ? 'On' : 'Off'}</strong>
              <span>Automatic runs</span>
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
            <div><dt>Last attempted run</dt><dd>{formatTimeWithRelative(monitoring.last_attempted_run?.started_at)}</dd></div>
            <div><dt>Last completed run</dt><dd>{formatTimeWithRelative(monitoring.last_completed_run?.completed_at)}</dd></div>
            <div><dt>Last failed run</dt><dd>{formatTimeWithRelative(monitoring.last_failed_run?.completed_at)}</dd></div>
            <div><dt>Last successful run</dt><dd>{formatTimeWithRelative(monitoring.last_successful_run?.completed_at)}</dd></div>
            <div><dt>Next scheduled run</dt><dd>{getNextScheduledRunText(monitoring)}</dd></div>
            <div><dt>Interval</dt><dd>Every {monitoring.interval_hours} hours</dd></div>
          </dl>
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
                        <td title={`Run ${run.run_id}`}>{formatAbsoluteTime(run.started_at)}</td>
                        <td>{run.trigger_type.replace('_', ' ')}</td>
                        <td>{formatTimeWithRelative(run.started_at)}</td>
                        <td>{formatDiscoveryDuration(run.duration_seconds) || '—'}</td>
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
                  <AccordionSection
                    key={run.run_id}
                    id={`run-failure-${run.run_id}`}
                    label={`${formatAbsoluteTime(run.started_at)} · ${run.error_summary || formatFailureCount(run.sources_failed)}`}
                  >
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
                  </AccordionSection>
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
                    <small>{humanizeEnum(run.trigger_type)} · {run.run_id.slice(0, 8)}</small>
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
            <div className="admin-history-log-heading">
              <h2>Run log details</h2>
              <p>Run outcome, processing totals, and source diagnostics.</p>
            </div>
            <button type="button" className="admin-link" onClick={() => setSelectedRunId('')}>Close</button>
          </header>
          <dl className="admin-history-log-meta">
            <div><dt>Run ID</dt><dd><code>{selectedRun.run_id}</code></dd></div>
            <div><dt>Trigger</dt><dd>{humanizeEnum(selectedRun.trigger_type)}</dd></div>
            <div><dt>Started</dt><dd>{formatRunTime(selectedRun.started_at)}</dd></div>
          </dl>
          <dl className="admin-history-log-metrics">
            <div className={`is-outcome is-${selectedRun.display_status}`}>
              <dt>Outcome</dt>
              <dd>
                <span className={`admin-history-status is-${selectedRun.display_status}`}>
                  {statusLabels[selectedRun.display_status] || selectedRun.display_status}
                </span>
              </dd>
            </div>
            <div className="is-sources">
              <dt>Sources</dt>
              <dd>
                <span className="is-success"><strong>{selectedRun.sources_succeeded}</strong> succeeded</span>
                <span className="is-failure"><strong>{selectedRun.sources_failed}</strong> failed</span>
                <small>of {selectedRun.sources_attempted} attempted</small>
              </dd>
            </div>
            <div><dt>Pages fetched</dt><dd>{selectedRun.pages_fetched}</dd></div>
            <div><dt>Candidates discovered</dt><dd>{selectedRun.candidates_discovered}</dd></div>
            <div><dt>Review candidates queued</dt><dd>{selectedRun.candidates_queued_for_review}</dd></div>
            <div className="is-created">
              <dt>Scholarships created</dt>
              <dd><strong>{selectedRun.scholarships_created}</strong><small>Unverified</small></dd>
            </div>
          </dl>
          {selectedRun.error_summary && (
            <div className="admin-history-run-error" role="alert">
              <strong>Run error</strong>
              <p>{selectedRun.error_summary}</p>
            </div>
          )}
          {selectedRun.failed_sources.length > 0 ? (
            <section className="admin-history-failures" aria-label="Failed sources">
              <header>
                <h3>Failed sources</h3>
                <span>{selectedRun.failed_sources.length}</span>
              </header>
              <ul>
                {selectedRun.failed_sources.map((source) => {
                  const failureDetails = getDiscoverySourceFailureDetails(source);
                  return (
                    <li key={`${selectedRun.run_id}-${source.source_id}`}>
                      <div className="admin-history-failure-heading">
                        <strong>{source.source_name || source.source_id}</strong>
                        <span>Failed</span>
                      </div>
                      {failureDetails.length > 0 ? (
                        <dl className="admin-history-failure-details">
                          {failureDetails.map(({ label, value }) => (
                            <div key={label}>
                              <dt>{label === 'HTTP' ? 'HTTP status' : label}</dt>
                              <dd>
                                {['Category', 'Stage', 'Page'].includes(label) ? humanizeEnum(value) : value}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      ) : (
                        <p>{formatDiscoverySourceFailure(source)}</p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : !selectedRun.error_summary && (
            <p className="admin-history-log-empty">No source errors were recorded for this run.</p>
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
  const sourceSummary = sources
    ? {
      total: sources.length,
      active: sources.filter((source) => source.active).length,
      errors: sources.filter((source) => source.status === 'failed').length,
    }
    : null;
  const sourceFilterCounts = {
    all: sourceSummary?.total ?? null,
    active: sourceSummary?.active ?? null,
    paused: null,
    errors: sourceSummary?.errors ?? null,
  };
  const sourceStats = [
    { key: 'total', label: 'Total sources', value: sourceSummary?.total ?? null, icon: Globe2 },
    { key: 'active', label: 'Active sources', value: sourceSummary?.active ?? null, icon: CircleCheck },
    { key: 'paused', label: 'Paused sources', value: null, icon: Clock3, note: 'Not tracked' },
    { key: 'errors', label: 'Sources with errors', value: sourceSummary?.errors ?? null, icon: ShieldAlert },
  ];
  const formatSourceCount = (value) => (
    Number.isInteger(value) && value >= 0 ? value.toLocaleString() : '—'
  );
  const statusLabels = {
    not_checked: 'Not checked',
    pending: 'Running',
    fetched: 'Checked',
    failed: 'Error',
    partial_failure: 'Partial failure',
    skipped: 'Skipped',
    inactive: 'Inactive',
    trust_review_required: 'Trust review',
  };
  const formatCheckedAt = (value) => {
    if (!value) return <span className="admin-source-never-checked">Never checked</span>;
    if (Number.isNaN(new Date(value).getTime())) return <span>Unknown</span>;
    const absoluteTime = formatAbsoluteTime(value);
    return (
      <time className="admin-source-checked-at" dateTime={value} title={absoluteTime}>
        <span>{formatRelativeTime(value) || absoluteTime}</span>
        <small>{absoluteTime}</small>
      </time>
    );
  };

  return (
    <div className="admin-sources-page">
      <header className="admin-discovery-page-header">
        <div>
          <div className="admin-sources-title">
            <h1>Discovery Sources</h1>
            <span className="admin-sources-total">{formatSourceCount(sourceSummary?.total)} sources</span>
          </div>
        </div>
        <div className="admin-sources-header-actions">
          <span className="admin-sources-readonly"><Globe2 size={13} aria-hidden="true" /> Curated registry</span>
          <button
            type="button"
            className="btn btn-primary admin-sources-add-button"
            disabled
            title="Sources are managed in the curated registry and cannot be added from Admin."
          >
            <Plus size={14} aria-hidden="true" /> Add source
          </button>
          <button type="button" className="btn btn-outline" onClick={retry}>Refresh</button>
        </div>
      </header>

      <section className="admin-sources-summary" aria-label="Source summary">
        {sourceStats.map((stat) => {
          const Icon = stat.icon;
          return (
            <div className={`admin-sources-stat is-${stat.key}`} key={stat.key}>
              <span className="admin-sources-stat-icon"><Icon size={16} aria-hidden="true" /></span>
              <div>
                <span className="admin-sources-stat-label">{stat.label}</span>
                <strong>{formatSourceCount(stat.value)}</strong>
                {stat.note && <small>{stat.note}</small>}
              </div>
            </div>
          );
        })}
      </section>

      <section className="admin-sources-card" aria-label="Discovery source registry">
        <div className="admin-sources-toolbar">
          <label className="admin-sources-filter">
            <span>Status</span>
            <span className="admin-sources-filter-control">
              <select
                value={filter}
                aria-label="Filter discovery sources"
                title="Paused sources cannot be filtered because the curated registry does not expose a pause state."
                onChange={(event) => { setFilter(event.target.value); setPage(0); }}
              >
                {['all', 'active', 'paused', 'errors'].map((value) => (
                  <option key={value} value={value} disabled={value === 'paused'}>
                    {value[0].toUpperCase() + value.slice(1)} ({formatSourceCount(sourceFilterCounts[value])})
                  </option>
                ))}
              </select>
              <ChevronDown size={14} aria-hidden="true" />
            </span>
          </label>
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

        <div className="admin-sources-note" role="note">
          <Info size={15} aria-hidden="true" />
          <p>
            Active means eligible under the curated source rules; run status reflects recorded history, not scheduler health. Candidate counts include all recorded review items from each source, not only pending items. Add, edit, and pause are unavailable.
          </p>
        </div>
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
                    <div className="admin-source-identity">
                      {/university|institution|college/i.test(source.category || '')
                        ? <Building2 size={16} aria-hidden="true" />
                        : <Globe2 size={16} aria-hidden="true" />}
                      <div>
                        <strong className="admin-source-name">{source.name}</strong>
                        <small>{source.country_or_region || source.official_domain}</small>
                      </div>
                    </div>
                  </td>
                  <td>
                    <a className="admin-source-url" href={source.source_url} target="_blank" rel="noreferrer" title={source.source_url}>
                      <span>{source.official_domain}</span>
                      <ExternalLink size={12} aria-hidden="true" />
                    </a>
                  </td>
                  <td><span className="admin-source-type">{humanizeEnum(source.category)}</span></td>
                  <td><span className={`admin-source-status is-${source.status}`}>{statusLabels[source.status] || 'Unknown'}</span></td>
                  <td>{formatCheckedAt(source.last_checked)}</td>
                  <td>
                    <span className="admin-source-review-count">
                      {Number.isFinite(source.review_candidates) ? source.review_candidates.toLocaleString() : '—'}
                    </span>
                  </td>
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
            <span className="admin-sources-pagination-range">
              <strong>
                Showing {visibleSources.length ? currentPage * SOURCE_PAGE_SIZE + 1 : 0}–{Math.min((currentPage + 1) * SOURCE_PAGE_SIZE, visibleSources.length)}
              </strong>
              <span> of {visibleSources.length.toLocaleString()} sources</span>
            </span>
            <div>
              <button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)} aria-label="Previous source page">
                <ArrowLeft size={14} aria-hidden="true" /> Previous
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

function VerificationDetails({ token, scholarshipId, onChanged, currentStatus }) {
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
  const completedChecks = VERIFICATION_CHECKLIST.filter(({ key }) => checks[key]).length;
  const verificationStatus = currentStatus
    || (scholarship?.verification_status === 'verified' ? 'verified' : 'unverified');
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
      {loading && (
        <div className="admin-verification-state" role="status">
          <span className="admin-verification-state-icon"><Clock3 size={19} aria-hidden="true" /></span>
          <h2>Loading verification workspace</h2>
          <p>Loading scholarship details...</p>
          <div className="admin-verification-state-skeleton" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        </div>
      )}
      {loadError && (
        <div className="admin-verification-state is-error" role="alert">
          <span className="admin-verification-state-icon"><ShieldAlert size={19} aria-hidden="true" /></span>
          <h2>Verification workspace unavailable</h2>
          <p>{loadError}</p>
          <button type="button" className="btn btn-outline" onClick={retry}>Try again</button>
        </div>
      )}
      {detail && (
        <>
          <header className="admin-verification-detail-header">
            <div className="admin-verification-detail-heading">
              <h2>Candidate Details</h2>
              <span className={`admin-verification-status is-${verificationStatus}`}>
                {humanizeEnum(verificationStatus)}
              </span>
            </div>
            <strong className="admin-verification-detail-title" title={scholarship.name}>{scholarship.name}</strong>
            <dl className="admin-verification-detail-meta">
              <div><dt>Country</dt><dd>{scholarship.country || '—'}</dd></div>
              <div><dt>Provider</dt><dd>{scholarship.provider || '—'}</dd></div>
            </dl>
          </header>
          {notice && <p className="admin-notice is-success" role="status">{notice}</p>}
          {actionError && <p className="admin-notice is-error" role="alert">{actionError}</p>}
          <div className="admin-verification-progress">
            <div className="admin-verification-progress-label">
              <span>Verification progress</span>
              <strong>{completedChecks}/{VERIFICATION_CHECKLIST.length}</strong>
            </div>
            <div
              className="admin-verification-progress-track"
              role="progressbar"
              aria-label="Verification checklist progress"
              aria-valuemin={0}
              aria-valuemax={VERIFICATION_CHECKLIST.length}
              aria-valuenow={completedChecks}
            >
              <span style={{ width: `${(completedChecks / VERIFICATION_CHECKLIST.length) * 100}%` }} />
            </div>
          </div>
          <h3 className="admin-verification-section-title">Verification checklist</h3>
          <div className="admin-verification-checklist">
            {VERIFICATION_CHECKLIST.map(({ key, label, note }) => (
              <label className={`admin-verification-check${checks[key] ? ' is-complete' : ''}`} key={key}>
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
            <span>Verification notes</span>
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
      {!loading && !loadError && !detail && (
        <p className="admin-verification-prompt">Scholarship details are unavailable.</p>
      )}
    </aside>
  );
}

function VerificationQueue({ token }) {
  const [status, setStatus] = useState('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [result, setResult] = useState(null);
  const [summaryStats, setSummaryStats] = useState(null);
  const [summaryError, setSummaryError] = useState('');
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [requestGuard] = useState(createLatestRequestGuard);
  const [summaryRequestGuard] = useState(createLatestRequestGuard);

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

  useEffect(() => {
    const requestId = summaryRequestGuard.begin();
    const recheckQuery = new URLSearchParams({
      skip: '0',
      limit: '1',
      archived: 'false',
      issue: 'verification_recheck',
    });
    Promise.allSettled([
      adminApi.summary(token),
      adminApi.list(token, recheckQuery.toString()),
    ]).then(([summaryResult, recheckResult]) => {
      if (!summaryRequestGuard.isCurrent(requestId)) return;
      const summary = summaryResult.status === 'fulfilled' ? summaryResult.value : null;
      const rechecks = recheckResult.status === 'fulfilled' ? recheckResult.value : null;
      const failures = [summaryResult, recheckResult]
        .filter((response) => response.status === 'rejected')
        .map((response) => (
          response.reason instanceof Error ? response.reason.message : String(response.reason)
        ));
      setSummaryStats({
        total: summary?.total ?? null,
        unverified: summary?.unverified ?? null,
        needsRecheck: rechecks?.total ?? null,
        verified: summary?.verified ?? null,
      });
      setSummaryError(failures.join(' '));
      setSummaryLoading(false);
    });
    return () => summaryRequestGuard.invalidate();
  }, [summaryRequestGuard, token, refresh]);

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
    setSummaryLoading(true);
    setSummaryError('');
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
  const selectedRow = rows.find((row) => row.id === selectedId);
  const filterCounts = {
    all: summaryStats?.total,
    unverified: summaryStats?.unverified,
    needs_recheck: summaryStats?.needsRecheck,
    verified: summaryStats?.verified,
  };
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
        </div>
        <button type="button" className="btn btn-outline" onClick={refreshList}>
          Refresh
        </button>
      </header>
      {summaryError && <RetryNotice message={summaryError} onRetry={refreshList} />}
      <section className="admin-verification-stats" aria-label="Verification summary" aria-busy={summaryLoading}>
        {[
          { key: 'total', label: 'Total Scholarships', value: summaryStats?.total, icon: BookOpen, tone: 'blue' },
          { key: 'unverified', label: 'Unverified', value: summaryStats?.unverified, icon: Clock3, tone: 'neutral' },
          { key: 'needsRecheck', label: 'Needs Recheck', value: summaryStats?.needsRecheck, icon: ShieldAlert, tone: 'amber' },
          { key: 'verified', label: 'Verified', value: summaryStats?.verified, icon: CircleCheck, tone: 'green' },
        ].map(({ key, label, value, icon: Icon, tone }) => (
          <article className={`admin-stat-card admin-verification-stat-card is-${tone}`} key={key}>
            <span className={`admin-stat-icon is-${tone}`}><Icon size={17} aria-hidden="true" /></span>
            <div><span>{label}</span><strong>{value ?? '—'}</strong></div>
          </article>
        ))}
      </section>
      <div className="admin-verification-workspace">
        <section className="admin-card admin-verification-list" aria-label="Scholarships to verify">
          <div className="admin-verification-list-heading">
            <div>
              <h2>Scholarships</h2>
              <p>Browse records and select one to verify.</p>
            </div>
            <span>
              {result
                ? `${formatReviewCount(result.total)} results`
                : loading ? 'Loading...' : 'Unavailable'}
            </span>
          </div>
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
                  <span className="admin-verification-filter-count">
                    {filterCounts[filter.value] ?? '—'}
                  </span>
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
              <colgroup>
                <col style={{ width: '5%' }} />
                <col style={{ width: '27%' }} />
                <col style={{ width: '18%' }} />
                <col style={{ width: '18%' }} />
                <col style={{ width: '17%' }} />
                <col style={{ width: '15%' }} />
              </colgroup>
              <thead>
                <tr>
                  <th><span className="admin-sr-only">Select for review</span></th>
                  <th>Scholarship</th>
                  <th>Provider</th>
                  <th>Last verified</th>
                  <th>Official source</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {!result && loading && Array.from({ length: 5 }, (_, index) => (
                  <tr className="admin-skeleton-row" key={`verification-skeleton-${index}`} aria-hidden="true">
                    <td><span className="admin-skeleton-checkbox" /></td>
                    <td><span className="admin-skeleton-line is-long" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                    <td><span className="admin-skeleton-line is-short" /></td>
                    <td><span className="admin-skeleton-line" /></td>
                    <td><span className="admin-skeleton-pill" /></td>
                  </tr>
                ))}
                {result && !loading && rows.length === 0 && (
                  <tr><td className="admin-verification-empty" colSpan="6">No scholarships match this filter.</td></tr>
                )}
                {result && !loading && rows.map((row) => {
                  const currentStatus = rowStatus(row);
                  return (
                    <tr key={row.id} className={selectedId === row.id ? 'is-selected' : ''}>
                      <td className="admin-verification-select-cell">
                        <input
                          type="checkbox"
                          checked={selectedId === row.id}
                          onChange={(event) => setSelectedId(event.target.checked ? row.id : null)}
                          aria-label={`Select ${row.name} for review`}
                        />
                      </td>
                      <td><strong title={row.name}>{row.name}</strong></td>
                      <td>
                        <span className="admin-verification-provider" title={row.provider || undefined}>
                          {row.provider || '—'}
                        </span>
                      </td>
                      <td>{row.last_verified_date ? formatRunTime(row.last_verified_date) : '—'}</td>
                      <td>
                        {row.official_source_url
                          ? <a href={row.official_source_url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>Official source</a>
                          : '—'}
                      </td>
                      <td><span className={`admin-verification-status is-${currentStatus}`}>{statusLabels[currentStatus]}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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
          ? <VerificationDetails
            key={selectedId}
            token={token}
            scholarshipId={selectedId}
            currentStatus={selectedRow ? rowStatus(selectedRow) : null}
            onChanged={refreshList}
          />
          : <VerificationDetailsEmpty />}
      </div>
    </div>
  );
}

function VerificationDetailsEmpty() {
  return (
    <aside className="admin-card admin-verification-details" aria-label="Verification checklist">
      <div className="admin-verification-empty-state">
        <span className="admin-verification-empty-icon">
          <ClipboardList size={20} aria-hidden="true" />
        </span>
        <h2>Select a scholarship to start verifying it.</h2>
        <p>Choose a record from the list to inspect its information and checklist.</p>
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
    records: 'Scholarships',
    duplicates: 'Duplicates',
    discovery: 'Automated Discovery',
    sources: 'Discovery Sources',
    reviews: 'Discovery Review Queue',
    verification: 'Verification',
    history: 'Discovery History',
    publications: 'Discovery Publications',
  };
  const title = sectionTitles[tab];

  return (
    <div className={`page-container admin-page${tab === 'records' ? ' admin-records-page' : ''}${tab === 'discovery' || tab === 'sources' ? ' admin-discovery-shell' : ''}${tab === 'reviews' ? ' admin-review-shell' : ''}${tab === 'verification' ? ' admin-verification-shell' : ''}${tab === 'duplicates' ? ' admin-duplicates-shell' : ''}${tab === 'history' ? ' admin-history-shell' : ''}`}>
      {tab !== 'discovery' && tab !== 'sources' && tab !== 'reviews' && tab !== 'verification' && tab !== 'duplicates' && tab !== 'history' && tab !== 'publications' && (
        <header className="admin-header">
          <div>
            <h1>{title}</h1>
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
            <summary className="admin-chevron-summary">
              <ChevronRight size={14} aria-hidden="true" />
              More filters{issue || archived ? ' · Active' : ''}
            </summary>
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
                      <Link className="admin-record-name" title={row.name} to={`/admin/scholarships/${row.id}`}>{row.name}</Link>
                      {row.issues.length > 0 && <small className="admin-record-issues" title={row.issues.map((item) => item.label).join(', ')}>
                        {row.issues.length} item{row.issues.length === 1 ? '' : 's'} need attention
                      </small>}
                    </td>
                    <td><span className="admin-record-value" title={row.provider || undefined}>{row.provider || '—'}</span></td>
                    <td>
                      <span
                        className="admin-record-value"
                        title={row.country?.replace(/\s*\(.*\)\s*$/, '') || undefined}
                      >
                        {row.country?.replace(/\s*\(.*\)\s*$/, '') || '—'}
                      </span>
                    </td>
                    <td><span className="admin-record-value" title={row.deadline || undefined}>{row.deadline || '—'}</span></td>
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
