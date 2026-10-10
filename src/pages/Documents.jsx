import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { GlowCard } from '../components/ui/spotlight-card';
import { useProfile } from '../context/ProfileContext';
import {
  aggregateRequiredDocuments,
  getDocumentStatus,
  getOpportunityDocumentRequirements,
  getOpportunityTitle,
} from '../services/opportunityJourney';

const STATUS_LABELS = {
  missing: 'Missing',
  'awaiting-verification': 'Awaiting verification',
  uploaded: 'Uploaded & verified',
};

export default function Documents() {
  const {
    activeOpportunity,
    selectedOpportunities,
    documentRecords,
    saveDocumentRecord,
    removeDocumentRecord,
  } = useProfile();
  const { hash } = useLocation();

  const handleRequiredUpload = (documentId, event) => {
    const file = event.target.files[0];
    event.target.value = '';
    if (file) saveDocumentRecord(documentId, file);
  };

  const activeDocumentIds = new Set(
    activeOpportunity ? getOpportunityDocumentRequirements(activeOpportunity).map((item) => item.id) : [],
  );
  const requiredDocuments = aggregateRequiredDocuments(selectedOpportunities)
    .sort((a, b) => Number(activeDocumentIds.has(b.id)) - Number(activeDocumentIds.has(a.id)));

  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'center' });
  }, [hash, requiredDocuments.length]);

  return (
    <div className="page-container">
      <h1 className="page-title">Documents</h1>
      <p className="page-subtitle">One place to prepare the documents your selected opportunities require. FitScholar AI does not submit applications; upload files on each official website yourself.</p>

      <GlowCard customSize className="card">
        <h2>Required documents</h2>
        {!selectedOpportunities.length ? (
          <p>Select an opportunity to see its documented requirements.</p>
        ) : requiredDocuments.length ? (
          <ul className="document-list">
            {requiredDocuments.map((item) => {
              const record = documentRecords[item.id];
              const status = getDocumentStatus(record);
              const inputId = `doc-input-${item.id}`;
              return (
                <li id={`doc-${item.id}`} key={item.id} className="document-item">
                  <div>
                    <strong>{item.name}</strong>
                    {' · '}<span className={`document-status document-status-${status}`}>{STATUS_LABELS[status]}</span>
                    {item.sourceStatus === 'unverified-sample' && <span> · sample requirement</span>}
                    {record && <p>{record.fileName} · uploaded {new Date(record.uploadedAt).toLocaleDateString()} (file metadata only in this demo)</p>}
                    <p>Required by: {item.requiredBy.map((opportunity) => (
                      opportunity.id === activeOpportunity?.id ? `${opportunity.title} (active)` : opportunity.title
                    )).join(', ')}</p>
                  </div>
                  <div>
                    <input type="file" id={inputId} style={{ display: 'none' }} onChange={(event) => handleRequiredUpload(item.id, event)} />
                    <label htmlFor={inputId} className="btn btn-outline" style={{ cursor: 'pointer' }}>
                      {record ? 'Replace' : 'Upload'}
                    </label>
                    {record && <button type="button" className="btn btn-outline" onClick={() => removeDocumentRecord(item.id)}>Remove</button>}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p>No opportunity-specific document requirements are available for your selected opportunities. No generic checklist is being assumed.</p>
        )}
        {activeOpportunity && <p>Active opportunity: {getOpportunityTitle(activeOpportunity)}</p>}
      </GlowCard>

    </div>
  );
}