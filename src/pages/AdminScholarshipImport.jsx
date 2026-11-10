import { useEffect, useMemo, useRef, useState } from 'react';
import { adminApi } from '../services/adminApi';
import {
  getImportConflicts, getImportFieldGroups, importedValueToForm, IMPORT_FIELD_LABELS,
} from '../services/adminScholarshipImport';

function statusTone(status) {
  if (status === 'extracted') return 'success';
  if (status === 'uncertain') return 'warning';
  return 'neutral';
}

function fieldValueLabel(value) {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export default function AdminScholarshipImport({ token, values, onApply, onStatusChange }) {
  const [sourceType, setSourceType] = useState('webpage');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState(null);
  const [sources, setSources] = useState([]);
  const [resolutions, setResolutions] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const fileInput = useRef(null);

  const groups = useMemo(() => getImportFieldGroups(sources), [sources]);
  const conflicts = useMemo(() => getImportConflicts(sources), [sources]);
  const unresolvedCount = conflicts.filter((group) => !Object.hasOwn(resolutions, group.name)).length;

  useEffect(() => {
    onStatusChange({ sourceCount: sources.length, conflictsResolved: unresolvedCount === 0 });
  }, [onStatusChange, sources.length, unresolvedCount]);

  const extract = async () => {
    setError('');
    if (sourceType === 'pdf_upload' && !file) {
      setError('Choose a PDF document first.');
      return;
    }
    if (sourceType !== 'pdf_upload') {
      let parsed;
      try {
        parsed = new URL(url.trim());
      } catch {
        setError('Enter a complete webpage or PDF URL.');
        return;
      }
      if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
        setError('Use an HTTP or HTTPS URL without embedded credentials.');
        return;
      }
    }

    setLoading(true);
    try {
      const result = await adminApi.extractScholarshipSource(token, {
        sourceType,
        url: sourceType === 'pdf_upload' ? undefined : url.trim(),
        file: sourceType === 'pdf_upload' ? file : undefined,
      });
      setSources((current) => [...current, result]);
      setResolutions({});
      setUrl('');
      setFile(null);
      if (fileInput.current) fileInput.current.value = '';
      setError('');
    } catch (failure) {
      setError(failure.message);
    } finally {
      setLoading(false);
    }
  };

  const applyNonConflicting = () => {
    const conflicted = new Set(conflicts.map((group) => group.name));
    const patch = {};
    groups.forEach((group) => {
      if (conflicted.has(group.name)) return;
      const extracted = group.entries.find((entry) => entry.result.status === 'extracted');
      if (extracted && !values[group.name]?.trim()) {
        patch[group.name] = importedValueToForm(extracted.result.value);
      }
    });
    onApply(patch);
  };

  const applyResolvedConflicts = () => {
    const patch = {};
    conflicts.forEach((group) => {
      if (resolutions[group.name] === -1) {
        patch[group.name] = '';
        return;
      }
      const selected = group.entries.find((entry) => entry.sourceIndex === resolutions[group.name]);
      if (selected) patch[group.name] = importedValueToForm(selected.result.value);
    });
    onApply(patch);
  };

  const applySuggestion = (name, value) => onApply({ [name]: importedValueToForm(value) });

  return (
    <section className="admin-card admin-import" aria-label="Import scholarship information">
      <h2>Import scholarship information</h2>
      <p className="admin-muted">
        Import creates a review draft only. It does not create, verify, approve, or index a scholarship.
        Confirm all details against the source before using the existing Create action.
      </p>
      <div className="admin-import-methods" role="group" aria-label="Import method">
        {[
          ['webpage', 'Webpage URL'],
          ['pdf_url', 'PDF URL'],
          ['pdf_upload', 'Upload PDF'],
        ].map(([value, label]) => (
          <label className="admin-check" key={value}>
            <input
              type="radio"
              name="scholarship-import-method"
              value={value}
              checked={sourceType === value}
              onChange={() => { setSourceType(value); setError(''); }}
            /> {label}
          </label>
        ))}
      </div>
      {sourceType === 'pdf_upload' ? (
        <div className="admin-field admin-import-input">
          <label htmlFor="scholarship-import-file">PDF document</label>
          <input
            id="scholarship-import-file"
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
            aria-invalid={Boolean(error)}
          />
          <small>PDF signature, file size, readability, and page limits are checked by the server.</small>
        </div>
      ) : (
        <div className="admin-field admin-import-input">
          <label htmlFor="scholarship-import-url">{sourceType === 'pdf_url' ? 'PDF URL' : 'Webpage URL'}</label>
          <input
            id="scholarship-import-url"
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://example.org/scholarship"
            aria-invalid={Boolean(error)}
          />
        </div>
      )}
      {error && <p className="admin-field-error" role="alert">{error}</p>}
      <div className="admin-actions">
        <button type="button" className="btn btn-outline" onClick={extract} disabled={loading}>
          {loading ? 'Fetching and extracting...' : 'Extract draft'}
        </button>
        {loading && <span className="admin-muted" role="status">The source is being checked and processed.</span>}
      </div>

      {sources.length > 0 && (
        <>
          <div className="admin-import-summary">
            <h3>Imported sources</h3>
            <ul className="admin-list">
              {sources.map((source, sourceIndex) => {
                const counts = Object.values(source.fields).reduce((total, field) => {
                  total[field.status] += 1;
                  return total;
                }, { extracted: 0, uncertain: 0, not_found: 0 });
                return (
                  <li key={`${source.source.url || source.source.label}-${sourceIndex}`}>
                    <span className="program-status is-neutral">{source.source.kind.replace(/_/g, ' ')}</span>
                    <strong>{source.source.label}</strong>
                    {source.source.url && <a href={source.source.url} target="_blank" rel="noreferrer">{source.source.url}</a>}
                    <small>{source.source.content_type}{source.source.page_count ? ` · ${source.source.page_count} PDF pages` : ''}</small>
                    <small>{counts.extracted} extracted · {counts.uncertain} uncertain · {counts.not_found} not found</small>
                    {source.warnings.map((warning) => <small key={warning} className="admin-field-error">{warning}</small>)}
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="admin-actions">
            <button type="button" className="btn btn-outline" onClick={applyNonConflicting} disabled={!groups.length}>
              Apply non-conflicting values to blank fields
            </button>
          </div>

          {conflicts.length > 0 && (
            <section className="admin-import-conflicts" aria-label="Conflicting source information">
              <h3>Conflicting source information</h3>
              <p className="admin-muted">Choose which source value to place in the form for each conflict. Unresolved conflicts block creation.</p>
              {conflicts.map((group) => (
                <fieldset className="admin-import-conflict" key={group.name}>
                  <legend>{IMPORT_FIELD_LABELS[group.name] || group.name}</legend>
                  {group.entries.filter((entry) => (
                    entry.result.value !== null
                    && entry.result.value !== undefined
                    && entry.result.suggestion_valid !== false
                  )).map((entry) => (
                    <label className="admin-check" key={`${group.name}-${entry.sourceIndex}`}>
                      <input
                        type="radio"
                        name={`import-conflict-${group.name}`}
                        checked={resolutions[group.name] === entry.sourceIndex}
                        onChange={() => setResolutions((current) => ({ ...current, [group.name]: entry.sourceIndex }))}
                      />
                      {entry.source.label}: {fieldValueLabel(entry.result.value)}
                    </label>
                  ))}
                  <label className="admin-check">
                    <input
                      type="radio"
                      name={`import-conflict-${group.name}`}
                      checked={resolutions[group.name] === -1}
                      onChange={() => setResolutions((current) => ({ ...current, [group.name]: -1 }))}
                    />
                    Leave this field blank for manual review
                  </label>
                </fieldset>
              ))}
              <button
                type="button"
                className="btn btn-outline"
                onClick={applyResolvedConflicts}
                disabled={unresolvedCount > 0}
              >
                Apply selected conflict values
              </button>
            </section>
          )}

          <details className="admin-import-evidence">
            <summary>Review field evidence and extraction status</summary>
            {sources.map((source, sourceIndex) => (
              <section key={`${source.source.label}-${sourceIndex}`} aria-label={`Evidence from ${source.source.label}`}>
                <h3>{source.source.label}</h3>
                <ul className="admin-list">
                  {Object.entries(source.fields).map(([name, result]) => (
                    <li className="admin-import-evidence-row" key={name}>
                      <span className={`program-status is-${statusTone(result.status)}`}>{result.status.replace(/_/g, ' ')}</span>
                      <strong>{IMPORT_FIELD_LABELS[name] || name}</strong>
                      {result.value !== null && result.value !== undefined && (
                        <code>{fieldValueLabel(result.value)}</code>
                      )}
                      {result.confidence && <small>Confidence: {result.confidence}</small>}
                      {result.source_label && <small>Source: {result.source_label}</small>}
                      {result.source_url && <a href={result.source_url} target="_blank" rel="noreferrer">Source URL</a>}
                      {result.page_number && <small>PDF page {result.page_number}</small>}
                      {result.evidence_excerpt && <blockquote>{result.evidence_excerpt}</blockquote>}
                      {result.note && <small>{result.note}</small>}
                      {result.status === 'uncertain' && result.suggestion_valid && result.value !== null && result.value !== undefined && (
                        <button type="button" className="admin-link" onClick={() => applySuggestion(name, result.value)}>
                          Use this suggestion
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </details>
          {conflicts.length > 0 && unresolvedCount > 0 && (
            <p className="admin-notice is-error" role="alert">{unresolvedCount} source conflict{unresolvedCount === 1 ? '' : 's'} still need a decision.</p>
          )}
        </>
      )}
    </section>
  );
}
