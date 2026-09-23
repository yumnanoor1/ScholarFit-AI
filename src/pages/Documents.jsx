import React, { useState } from 'react';
import { apiService } from '../services/api';
import { UploadCloud, FileCheck, AlertTriangle } from 'lucide-react';

export default function Documents() {
  const [extracted, setExtracted] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleFileUpload = async (e) => {
    if (!e.target.files[0]) return;
    setLoading(true);
    const data = await apiService.extractDocumentData(e.target.files[0]);
    setExtracted(data);
    setLoading(false);
  };

  return (
    <div className="page-container">
      <h1 className="page-title">Document Parsing & Analysis</h1>
      <p className="page-subtitle">Extract verified academic parameters from CVs and Official Transcripts.</p>

      <div className="disclaimer-box">
        <strong>Information Accuracy Disclaimer:</strong> Automated extraction assists data entry. Users must verify parsed fields prior to submitting eligibility checks.
      </div>

      <div className="card" style={{ textAlign: 'center', borderStyle: 'dashed', borderWidth: '2px', padding: '40px 20px' }}>
        <UploadCloud size={48} color="var(--color-primary)" style={{ marginBottom: '12px' }} />
        <h3>Upload Document for Analysis</h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', marginBottom: '16px' }}>
          Supports PDF CVs, Transcripts, and English score certificates
        </p>
        <input type="file" onChange={handleFileUpload} id="doc-upload" style={{ display: 'none' }} />
        <label htmlFor="doc-upload" className="btn btn-primary" style={{ cursor: 'pointer' }}>
          Select Document
        </label>
        {loading && <p style={{ fontSize: '0.85rem', marginTop: '12px' }}>Parsing document content...</p>}
      </div>

      {extracted && (
        <div className="card">
          <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
            <FileCheck color="var(--color-success)" /> Extracted Academic Credentials
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '0.9rem' }}>
            <div><strong>Degree Title:</strong> {extracted.extractedData.degreeFound}</div>
            <div><strong>Detected CGPA:</strong> {extracted.extractedData.cgpaFound}</div>
            <div><strong>Institution:</strong> {extracted.extractedData.institutionFound}</div>
          </div>

          <h4 style={{ marginTop: '20px', color: 'var(--color-warning)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <AlertTriangle size={18} /> Verification Gaps Identified
          </h4>
          <ul style={{ paddingLeft: '20px', fontSize: '0.85rem', marginTop: '8px' }}>
            {extracted.missingData.map((item, idx) => (
              <li key={idx} style={{ marginBottom: '4px' }}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}