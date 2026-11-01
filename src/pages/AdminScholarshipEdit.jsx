import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ExternalLink } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { adminApi } from '../services/adminApi';
import {
  FORM_SECTIONS, REVIEW_LABELS, getOpenReviewGroups, isDirty, toFormValues, toPayload, validateForm,
} from '../services/adminScholarshipForm';
import { getMatchTone } from '../services/eligibilityBadges';
import './AdminScholarships.css';

const SEVERITY_TONES = { high: 'danger', medium: 'warning', low: 'neutral' };
const FLAGS = [['conflicting_information', 'Conflicting information'], ['outdated_source', 'Outdated source'], ['broken_source', 'Broken source'], ['needs_reverification', 'Needs re-verification']];
const SOURCE_TONES = { ok: 'success', broken: 'danger', inconclusive: 'neutral', invalid: 'warning' };
const OUTCOMES = [['confirmed', 'Confirmed Match'], ['potential', 'Potential Match'], ['needs_verification', 'Needs Verification'], ['not_a_match', 'Not a Match']];
const LINK_TYPES = ['unconfirmed', 'named_program', 'all_programs_at_university', 'programs_meeting_stated_criteria'];
const EMPTY_LINK = { program_id: '', outcome: 'potential', relationship_type: 'unconfirmed', evidence: '', source_url: '', verification_status: 'unverified', last_verified: '', notes: '' };

function FormField({ field, value, error, onChange, universities }) {
  const id = `field-${field.name}`;
  const common = { id, value, onChange: (event) => onChange(field.name, event.target.value), 'aria-invalid': Boolean(error) };
  let input = <input {...common} type={field.type === 'date' ? 'date' : 'text'} inputMode={field.type === 'number' || field.type === 'integer' ? 'decimal' : undefined} />;
  if (field.type === 'textarea' || field.type === 'lines') input = <textarea {...common} rows={field.type === 'lines' ? 3 : 2} />;
  if (field.type === 'select') {
    input = <select {...common}><option value="">Not recorded</option>{field.options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>;
  }
  if (field.type === 'boolean') input = <select {...common}><option value="">Not recorded</option><option value="true">Yes</option><option value="false">No</option></select>;
  if (field.type === 'university') {
    input = <select {...common}><option value="">Not in the catalog</option>{universities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>;
  }
  return (
    <div className={`admin-field ${field.type === 'textarea' || field.type === 'lines' ? 'is-wide' : ''}`}>
      <label htmlFor={id}>{field.label}{field.required ? ' *' : ''}</label>
      {input}
      {field.hint && <small>{field.hint}</small>}
      {error && <small className="admin-field-error" role="alert">{error}</small>}
    </div>
  );
}

function VerificationPanel({ token, record, onDone, run }) {
  const [form, setForm] = useState({
    status: 'verified', basis: 'official_source', source_url: record.official_info_url || '', verified_on: '', notes: '', evidence_reviewed: false, acknowledge_conflicts: false,
  });
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const submit = () => run(async () => {
    onDone(await adminApi.verify(token, record.id, { ...form, source_url: form.source_url.trim() || null, verified_on: form.verified_on || null }));
    return 'Verification recorded.';
  });
  return (
    <section className="admin-card" aria-label="Verification">
      <h2>Verification</h2>
      <p className="admin-muted">
        Currently {record.verification_status} · basis {record.verification_basis || 'not recorded'} · last checked {record.last_verified_date || 'never'}.
        Having a URL isn't verification: record what you actually reviewed.
      </p>
      <div className="admin-grid">
        <div className="admin-field"><label htmlFor="v-status">Decision</label>
          <select id="v-status" value={form.status} onChange={(event) => set('status', event.target.value)}><option value="verified">Verified</option><option value="unverified">Unverified</option></select>
        </div>
        <div className="admin-field"><label htmlFor="v-basis">Source type</label>
          <select id="v-basis" value={form.basis} onChange={(event) => set('basis', event.target.value)}>
            <option value="official_source">Official source</option><option value="mixed_sources">Official and secondary sources</option>
            <option value="secondary_only">Secondary sources only</option><option value="not_verified">Not verified</option>
          </select>
        </div>
        <div className="admin-field"><label htmlFor="v-url">Source URL</label><input id="v-url" value={form.source_url} onChange={(event) => set('source_url', event.target.value)} /></div>
        <div className="admin-field"><label htmlFor="v-date">Date you checked it</label><input id="v-date" type="date" value={form.verified_on} onChange={(event) => set('verified_on', event.target.value)} /></div>
        <div className="admin-field is-wide"><label htmlFor="v-notes">Notes</label><textarea id="v-notes" rows={2} value={form.notes} onChange={(event) => set('notes', event.target.value)} /></div>
      </div>
      <label className="admin-check"><input type="checkbox" checked={form.evidence_reviewed} onChange={(event) => set('evidence_reviewed', event.target.checked)} /> I reviewed this evidence myself</label>
      <label className="admin-check"><input type="checkbox" checked={form.acknowledge_conflicts} onChange={(event) => set('acknowledge_conflicts', event.target.checked)} /> Verify despite the conflicts listed above</label>
      <div className="admin-actions"><button type="button" className="btn btn-primary" onClick={submit}>Save verification</button></div>
    </section>
  );
}

function SourcesPanel({ token, record, onDone, run }) {
  const flags = record.data_flags || [];
  const urls = [record.official_info_url, record.official_application_url, ...(record.additional_source_urls || [])].filter(Boolean);
  return (
    <section className="admin-card" aria-label="Sources and flags">
      <h2>Sources and flags</h2>
      <p className="admin-muted">A link check only asks whether a page answers. It never changes verification, and refusals count as inconclusive, not broken.</p>
      <ul className="admin-list">
        {urls.map((url) => {
          const check = (record.source_checks || []).find((item) => item.url === url);
          return (
            <li key={url}>
              <a href={url} target="_blank" rel="noreferrer">{url} <ExternalLink size={12} aria-hidden="true" /></a>
              {check
                ? <span className={`program-status is-${SOURCE_TONES[check.status]}`}>{check.status}</span>
                : <span className="program-status is-neutral">Not checked</span>}
              {check?.detail && <small>{check.detail}</small>}
            </li>
          );
        })}
        {urls.length === 0 && <li>No source URLs are recorded.</li>}
      </ul>
      <div className="admin-actions">
        <button type="button" className="btn btn-outline" disabled={urls.length === 0} onClick={() => run(async () => { onDone(await adminApi.checkSources(token, record.id)); return 'Links checked.'; })}>Check links now</button>
      </div>
      <div className="admin-flags">
        {FLAGS.map(([flag, label]) => (
          <label className="admin-check" key={flag}>
            <input
              type="checkbox"
              checked={flags.includes(flag)}
              onChange={(event) => run(async () => { onDone(await adminApi.flag(token, record.id, { flag, active: event.target.checked })); return 'Flag updated.'; })}
            /> {label}
          </label>
        ))}
      </div>
    </section>
  );
}

function RelationshipsPanel({ token, record, relationships, onDone, run }) {
  const [programs, setPrograms] = useState([]);
  const [form, setForm] = useState(EMPTY_LINK);
  const [removing, setRemoving] = useState(null);
  useEffect(() => { adminApi.programs(token).then(setPrograms).catch(() => setPrograms([])); }, [token]);
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const edit = (item) => setForm({
    program_id: String(item.program_id), outcome: item.outcome, relationship_type: item.relationship_type || 'unconfirmed', evidence: item.evidence || '',
    source_url: item.source_url || '', verification_status: item.relationship_verification_status || 'unverified', last_verified: item.last_verified || '', notes: item.notes || '',
  });
  const save = () => run(async () => {
    const { program_id: programId, ...body } = form;
    await adminApi.saveLink(token, record.id, programId, {
      ...body, evidence: body.evidence.trim() || null, source_url: body.source_url.trim() || null, last_verified: body.last_verified || null, notes: body.notes.trim() || null,
    });
    onDone(await adminApi.detail(token, record.id));
    setForm(EMPTY_LINK);
    return 'Relationship saved.';
  });
  const remove = (programId) => run(async () => {
    await adminApi.removeLink(token, record.id, programId);
    setRemoving(null);
    onDone(await adminApi.detail(token, record.id));
    return 'Relationship removed.';
  });
  return (
    <section className="admin-card" aria-label="Program relationships">
      <h2>Program relationships</h2>
      <p className="admin-muted">This is separate from the scholarship's own verification. A Confirmed Match needs evidence, a source and a checked date.</p>
      <ul className="admin-list">
        {relationships.map((item) => (
          <li key={item.program_id}>
            <span className={`program-status is-${getMatchTone(item.outcome)}`}>{item.label}</span>
            <span>{item.program_name}, {item.university_name}<small>{item.has_relationship ? item.evidence || 'No evidence recorded' : item.explanation}</small></span>
            {item.has_relationship && (
              <span className="admin-actions">
                <button type="button" className="admin-link" onClick={() => edit(item)}>Edit</button>
                {removing === item.program_id
                  ? <button type="button" className="admin-link is-danger" onClick={() => remove(item.program_id)}>Confirm removal</button>
                  : <button type="button" className="admin-link" onClick={() => setRemoving(item.program_id)}>Remove</button>}
              </span>
            )}
          </li>
        ))}
        {relationships.length === 0 && <li>No relationships yet.</li>}
      </ul>
      <h3>Add or update a relationship</h3>
      <div className="admin-grid">
        <div className="admin-field"><label htmlFor="l-program">Program</label>
          <select id="l-program" value={form.program_id} onChange={(event) => set('program_id', event.target.value)}>
            <option value="">Choose a program</option>
            {programs.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </div>
        <div className="admin-field"><label htmlFor="l-outcome">Outcome</label>
          <select id="l-outcome" value={form.outcome} onChange={(event) => set('outcome', event.target.value)}>{OUTCOMES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </div>
        <div className="admin-field"><label htmlFor="l-type">Coverage type</label>
          <select id="l-type" value={form.relationship_type} onChange={(event) => set('relationship_type', event.target.value)}>{LINK_TYPES.map((value) => <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>)}</select>
        </div>
        <div className="admin-field"><label htmlFor="l-status">Relationship verification</label>
          <select id="l-status" value={form.verification_status} onChange={(event) => set('verification_status', event.target.value)}><option value="unverified">Unverified</option><option value="verified">Verified</option></select>
        </div>
        <div className="admin-field"><label htmlFor="l-url">Source URL</label><input id="l-url" value={form.source_url} onChange={(event) => set('source_url', event.target.value)} /></div>
        <div className="admin-field"><label htmlFor="l-date">Date checked</label><input id="l-date" type="date" value={form.last_verified} onChange={(event) => set('last_verified', event.target.value)} /></div>
        <div className="admin-field is-wide"><label htmlFor="l-evidence">Evidence</label><textarea id="l-evidence" rows={2} value={form.evidence} onChange={(event) => set('evidence', event.target.value)} /></div>
        <div className="admin-field is-wide"><label htmlFor="l-notes">Notes</label><textarea id="l-notes" rows={2} value={form.notes} onChange={(event) => set('notes', event.target.value)} /></div>
      </div>
      <div className="admin-actions"><button type="button" className="btn btn-outline" disabled={!form.program_id} onClick={save}>Save relationship</button></div>
    </section>
  );
}

function ArchivePanel({ token, detail, onDone, run, onDeleted }) {
  const { scholarship: record, references } = detail;
  const [reason, setReason] = useState('');
  const [typed, setTyped] = useState('');
  const inUse = references.saved_by_students + references.program_links + references.duplicates_pointing_here > 0;
  return (
    <section className="admin-card is-danger" aria-label="Archive or delete">
      <h2>Archive or delete</h2>
      <p>
        Used by {references.saved_by_students} saved item{references.saved_by_students === 1 ? '' : 's'}, {references.program_links} program
        relationship{references.program_links === 1 ? '' : 's'} and {references.duplicates_pointing_here} duplicate record{references.duplicates_pointing_here === 1 ? '' : 's'}.
      </p>
      {record.archived ? (
        <>
          <p>Archived: {record.archive_reason}</p>
          <button type="button" className="btn btn-outline" onClick={() => run(async () => { onDone(await adminApi.restore(token, record.id)); return 'Record restored.'; })}>Restore to listings</button>
        </>
      ) : (
        <>
          <p className="admin-muted">Archiving removes this from Explore, My Matches and every other list. Its ID, saved items and relationships stay, and you can restore it.</p>
          <div className="admin-field is-wide"><label htmlFor="a-reason">Reason</label><input id="a-reason" value={reason} onChange={(event) => setReason(event.target.value)} /></div>
          <div className="admin-actions">
            <button type="button" className="btn btn-outline" disabled={reason.trim().length < 5} onClick={() => run(async () => { onDone(await adminApi.archive(token, record.id, reason)); setReason(''); return 'Record archived.'; })}>Archive this record</button>
          </div>
        </>
      )}
      {inUse ? <p className="admin-muted">Permanent deletion isn't available because this record is in use.</p> : (
        <>
          <p className="admin-muted">Nothing depends on this record, so it can be deleted for good. This can't be undone. Type its name to confirm.</p>
          <div className="admin-field is-wide"><label htmlFor="d-name">Scholarship name</label><input id="d-name" value={typed} onChange={(event) => setTyped(event.target.value)} /></div>
          <div className="admin-actions">
            <button type="button" className="btn btn-outline" disabled={typed !== record.name} onClick={() => run(async () => { await adminApi.remove(token, record.id); onDeleted(); return ''; })}>Delete permanently</button>
          </div>
        </>
      )}
    </section>
  );
}

export default function AdminScholarshipEdit() {
  const { id } = useParams();
  const isNew = id === undefined;
  const navigate = useNavigate();
  const { token } = useAuth();
  const [detail, setDetail] = useState(null);
  const [values, setValues] = useState(() => toFormValues(null));
  const [original, setOriginal] = useState(() => toFormValues(null));
  const [errors, setErrors] = useState({});
  const [reviewed, setReviewed] = useState([]);
  const [universities, setUniversities] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState(null);
  const [saving, setSaving] = useState(false);

  const apply = useCallback((data) => {
    setDetail(data);
    const form = toFormValues(data.scholarship);
    setValues(form);
    setOriginal(form);
    setReviewed([]);
  }, []);

  const load = useCallback(() => {
    if (isNew) return;
    adminApi.detail(token, id)
      .then((data) => { apply(data); setLoadError(''); })
      .catch((failure) => setLoadError(failure.message));
  }, [token, id, isNew, apply]);
  useEffect(load, [load]);
  useEffect(() => { adminApi.universities(token).then(setUniversities).catch(() => setUniversities([])); }, [token]);

  const dirty = isDirty(values, original);
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event) => { event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const run = async (action) => {
    setNotice(null);
    setSaving(true);
    try {
      const message = await action();
      if (message) setNotice({ tone: 'success', text: message });
    } catch (failure) {
      setNotice({ tone: 'error', text: failure.message });
    } finally {
      setSaving(false);
    }
  };

  const save = () => {
    const found = validateForm(values);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      setNotice({ tone: 'error', text: 'Fix the highlighted fields first.' });
      return;
    }
    run(async () => {
      if (isNew) {
        const created = await adminApi.create(token, toPayload(values));
        setOriginal(values);
        navigate(`/admin/scholarships/${created.id}`, { replace: true });
        return 'Scholarship created as unverified.';
      }
      const result = await adminApi.update(token, id, {
        ...toPayload(values), expected_version: detail.scholarship.record_version || 0, reviewed_groups: reviewed,
      });
      apply(await adminApi.detail(token, id));
      return result.warnings.length ? `Saved. ${result.warnings.join(' ')}` : 'Saved.';
    });
  };

  if (loadError) {
    return (
      <div className="page-container admin-page">
        <p className="admin-notice is-error" role="alert">{loadError} <button type="button" className="admin-link" onClick={load}>Try again</button></p>
        <Link to="/admin/scholarships">Back to records</Link>
      </div>
    );
  }
  if (!isNew && !detail) return <div className="page-container admin-page" role="status">Loading the record...</div>;

  const record = detail?.scholarship;
  const openGroups = getOpenReviewGroups(record?.data_flags);

  return (
    <div className="page-container admin-page">
      <Link className="admin-back" to="/admin/scholarships"><ArrowLeft size={15} aria-hidden="true" /> Back to records</Link>
      <header className="admin-header">
        <div>
          <h1>{isNew ? 'Add scholarship' : record.name}</h1>
          {!isNew && <p className="admin-muted">Record #{record.id} · {record.verification_status}{record.archived ? ' · archived' : ''}</p>}
          {isNew && <p className="admin-muted">New records start unverified. Leave anything you don't know blank.</p>}
        </div>
      </header>

      {notice && <p className={`admin-notice is-${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}>{notice.text}</p>}

      {!isNew && (
        <section className="admin-card" aria-label="Data quality">
          <h2>Data quality</h2>
          {detail.issues.length === 0 && <p>No problems found.</p>}
          <ul className="admin-list">
            {detail.issues.map((item) => (
              <li key={`${item.code}-${item.detail}`}>
                <span className={`program-status is-${SEVERITY_TONES[item.severity]}`}>{item.label}</span>
                <span>{item.detail}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {FORM_SECTIONS.map((section, index) => (
        <details className="admin-card" key={section.id} open={index === 0}>
          <summary>{section.title}</summary>
          <div className="admin-grid">
            {section.fields.map((field) => (
              <FormField
                key={field.name}
                field={field}
                value={values[field.name]}
                error={errors[field.name]}
                universities={universities}
                onChange={(name, value) => setValues((current) => ({ ...current, [name]: value }))}
              />
            ))}
          </div>
        </details>
      ))}

      {openGroups.length > 0 && (
        <section className="admin-card" aria-label="Held for review">
          <h2>Held for review</h2>
          <p className="admin-muted">Students get Verify Manually for this record until you've compared the wording with the structured values and confirmed they agree.</p>
          {openGroups.map((group) => (
            <label className="admin-check" key={group}>
              <input
                type="checkbox"
                checked={reviewed.includes(group)}
                onChange={(event) => setReviewed((current) => (event.target.checked ? [...current, group] : current.filter((item) => item !== group)))}
              /> {REVIEW_LABELS[group] || group}: wording and structured values agree
            </label>
          ))}
        </section>
      )}

      <div className="admin-save-bar">
        <button type="button" className="btn btn-primary" disabled={saving || (!dirty && reviewed.length === 0 && !isNew)} onClick={save}>{saving ? 'Saving...' : isNew ? 'Create scholarship' : 'Save changes'}</button>
        {dirty && <span className="admin-muted">Unsaved changes</span>}
      </div>

      {!isNew && (
        <>
          <VerificationPanel key={record.record_version} token={token} record={record} onDone={apply} run={run} />
          <SourcesPanel token={token} record={record} onDone={apply} run={run} />
          <RelationshipsPanel token={token} record={record} relationships={detail.relationships} onDone={apply} run={run} />
          <section className="admin-card" aria-label="Change history">
            <h2>Change history</h2>
            {detail.audit.length === 0 && <p>No administrative changes yet.</p>}
            <ul className="admin-list">
              {detail.audit.map((entry) => (
                <li key={entry.id}>
                  <span className="program-status is-neutral">{entry.action.replace(/_/g, ' ')}</span>
                  <span>
                    {entry.actor_email} · {new Date(entry.created_at).toLocaleString()}
                    {entry.note && <small>{entry.note}</small>}
                    {entry.changes && <small>Changed: {Object.keys(entry.changes).join(', ')}</small>}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          <ArchivePanel token={token} detail={detail} onDone={apply} run={run} onDeleted={() => navigate('/admin/scholarships', { replace: true })} />
        </>
      )}
    </div>
  );
}
