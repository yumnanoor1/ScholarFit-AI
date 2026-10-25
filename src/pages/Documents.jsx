import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ArrowDown, ArrowRight, FileText, GraduationCap, Upload, X } from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import {
  aggregateRequiredDocuments,
  getDocumentStatus,
  getOpportunityDocumentRequirements,
  getOpportunityTitle,
} from '../services/opportunityJourney';

const MAX_FILE_SIZE = 5 * 1024 * 1024;

const STATUS_LABELS = {
  missing: 'Missing',
  'awaiting-verification': 'Uploaded',
  uploaded: 'Verified',
};

function opportunityLabel(opportunity) {
  if (!opportunity) return '';
  const organization = opportunity.university || opportunity.provider || opportunity.country;
  return [getOpportunityTitle(opportunity), organization]
    .filter((value, index, values) => value && values.indexOf(value) === index)
    .join(' · ');
}

export default function Documents() {
  const {
    activeOpportunity,
    selectedOpportunities,
    setActiveOpportunity,
    documentRecords,
    saveDocumentRecord,
    removeDocumentRecord,
  } = useProfile();
  const { hash } = useLocation();
  const [uploadErrors, setUploadErrors] = useState({});
  const [draggingDocumentId, setDraggingDocumentId] = useState(null);
  const currentOpportunity = activeOpportunity || selectedOpportunities[0] || null;
  const opportunityOptions = selectedOpportunities.length
    ? selectedOpportunities
    : currentOpportunity ? [currentOpportunity] : [];
  const activeDocumentIds = useMemo(
    () => new Set(currentOpportunity ? getOpportunityDocumentRequirements(currentOpportunity).map((item) => item.id) : []),
    [currentOpportunity],
  );
  const requiredDocuments = useMemo(
    () => aggregateRequiredDocuments(currentOpportunity ? [currentOpportunity] : [])
      .sort((a, b) => {
        const statusOrder = { missing: 0, 'awaiting-verification': 1, uploaded: 2 };
        return statusOrder[getDocumentStatus(documentRecords[a.id])]
          - statusOrder[getDocumentStatus(documentRecords[b.id])];
      }),
    [currentOpportunity, documentRecords],
  );
  const uploadedCount = requiredDocuments.filter((item) => Boolean(documentRecords[item.id])).length;
  const progressPercentage = requiredDocuments.length
    ? (uploadedCount / requiredDocuments.length) * 100
    : 0;

  const handleFile = (documentId, file) => {
    if (!file) return;
    const isPdf = file.type === 'application/pdf' || (!file.type && /\.pdf$/i.test(file.name));
    if (!isPdf) {
      setUploadErrors((current) => ({ ...current, [documentId]: 'Choose a PDF file.' }));
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      setUploadErrors((current) => ({ ...current, [documentId]: 'File must be 5 MB or smaller.' }));
      return;
    }
    try {
      saveDocumentRecord(documentId, file);
      setUploadErrors((current) => ({ ...current, [documentId]: '' }));
    } catch (error) {
      console.error('Unable to save document metadata.', error);
      setUploadErrors((current) => ({ ...current, [documentId]: 'The document could not be added. Please try again.' }));
    }
  };

  const handleInputChange = (documentId, event) => {
    handleFile(documentId, event.target.files?.[0]);
    event.target.value = '';
  };

  const handleDrop = (documentId, event) => {
    event.preventDefault();
    setDraggingDocumentId(null);
    handleFile(documentId, event.dataTransfer.files?.[0]);
  };

  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'center' });
  }, [hash, requiredDocuments.length]);

  return (
    <div className="page-container documents-page">
      <header className="documents-heading">
        <div>
          <h1 className="page-title">Documents</h1>
          <p className="page-subtitle">Prepare the documents required by your selected opportunity. FitScholars does not submit applications.</p>
        </div>
        {currentOpportunity && (
          <div className="documents-opportunity">
            <GraduationCap size={16} aria-hidden="true" />
            <strong>For:</strong>
            {opportunityOptions.length > 1 ? (
              <label>
                <span className="sr-only">Change document opportunity</span>
                <select
                  value={currentOpportunity.id}
                  onChange={(event) => setActiveOpportunity(event.target.value)}
                >
                  {opportunityOptions.map((opportunity) => (
                    <option key={opportunity.id} value={opportunity.id}>
                      {opportunityLabel(opportunity)}
                    </option>
                  ))}
                </select>
                <ArrowDown size={13} aria-hidden="true" />
              </label>
            ) : <span>{opportunityLabel(currentOpportunity)}</span>}
          </div>
        )}
      </header>

      <section className="documents-container card" aria-labelledby="documents-required-title">
        <div className="documents-section-heading">
          <div>
            <h2 id="documents-required-title">Required documents</h2>
            <p>Accepted format: PDF · Maximum file size: 5 MB</p>
          </div>
          {requiredDocuments.length > 0 && (
            <span className="documents-progress-label">{uploadedCount} of {requiredDocuments.length} uploaded</span>
          )}
        </div>
        {requiredDocuments.length > 0 && (
          <div
            className="documents-progress-track"
            role="progressbar"
            aria-label="Documents uploaded"
            aria-valuemin={0}
            aria-valuemax={requiredDocuments.length}
            aria-valuenow={uploadedCount}
          >
            <span style={{ width: `${progressPercentage}%` }} />
          </div>
        )}

        {!currentOpportunity ? (
          <p className="documents-empty">Select an opportunity to see its documented requirements.</p>
        ) : requiredDocuments.length ? (
          <>
            <ul className="document-list">
              {requiredDocuments.map((item) => {
                const record = documentRecords[item.id];
                const status = getDocumentStatus(record);
                const isRequiredForActive = activeDocumentIds.has(item.id);
                const inputId = `doc-input-${item.id}`;
                const uploadError = uploadErrors[item.id];
                return (
                  <li
                    id={`doc-${item.id}`}
                    key={item.id}
                    className={`document-item${status === 'missing' ? ' is-missing' : ''}${isRequiredForActive ? ' is-required' : ''}`}
                  >
                    <div className="document-item-info">
                      <div className="document-item-heading">
                        <FileText size={17} aria-hidden="true" />
                        <strong>{item.name}</strong>
                        <span className={`document-status document-status-${status}`}>{STATUS_LABELS[status]}</span>
                        {isRequiredForActive && <span className="document-required-chip">Required</span>}
                      </div>
                      {item.sourceStatus === 'unverified-sample' && (
                        <p className="document-item-note">Sample requirement · confirm with the official provider</p>
                      )}
                      {record && (
                        <p className="document-record">
                          {record.fileName} · added {new Date(record.uploadedAt).toLocaleDateString()} · FitScholars stores file metadata only
                        </p>
                      )}
                      {uploadError && <p className="document-upload-error" role="alert">{uploadError}</p>}
                    </div>
                    <div className="document-item-controls">
                      <input
                        type="file"
                        id={inputId}
                        className="document-file-input sr-only"
                        accept=".pdf,application/pdf"
                        onChange={(event) => handleInputChange(item.id, event)}
                      />
                      <label
                        htmlFor={inputId}
                        className={`document-dropzone${draggingDocumentId === item.id ? ' is-dragging' : ''}`}
                        onDragEnter={(event) => {
                          event.preventDefault();
                          setDraggingDocumentId(item.id);
                        }}
                        onDragOver={(event) => event.preventDefault()}
                        onDragLeave={(event) => {
                          if (!event.currentTarget.contains(event.relatedTarget)) setDraggingDocumentId(null);
                        }}
                        onDrop={(event) => handleDrop(item.id, event)}
                      >
                        <Upload size={15} aria-hidden="true" />
                        <span>{record ? 'Replace PDF' : 'Choose or drop PDF'}</span>
                      </label>
                      {record && (
                        <button
                          type="button"
                          className="btn btn-danger"
                          onClick={() => removeDocumentRecord(item.id)}
                        >
                          <X size={14} aria-hidden="true" /> Remove
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
            <aside className="documents-help" aria-label="Document writing help">
              <strong>Need help preparing a document?</strong>
              <a
                href="https://owl.purdue.edu/owl/job_search_writing/preparing_an_application/writing_the_personal_statement"
                target="_blank"
                rel="noreferrer"
              >
                How to write a statement of purpose <ArrowRight size={14} aria-hidden="true" />
              </a>
            </aside>
            <p className="documents-upload-note">This demo records file metadata only. Upload the actual files through each university or scholarship’s official application portal.</p>
          </>
        ) : (
          <p className="documents-empty">No opportunity-specific document requirements are available. No generic checklist is being assumed.</p>
        )}
      </section>
    </div>
  );
}
