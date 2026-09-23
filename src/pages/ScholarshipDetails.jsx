import React from 'react';
import { useNavigate } from 'react-router-dom';

export default function ScholarshipDetails() {
  const navigate = useNavigate();

  return (
    <div className="page-container">
      <button className="btn btn-outline" onClick={() => navigate(-1)} style={{ marginBottom: '16px' }}>
        ← Back to Scholarships
      </button>

      <div className="card">
        <h1 style={{ fontSize: '1.5rem', marginBottom: '4px' }}>DAAD EPOS Scholarship</h1>
        <p style={{ color: 'var(--color-primary)', fontWeight: '600', marginBottom: '16px' }}>
          German Academic Exchange Service • Germany
        </p>

        <div className="grid-2" style={{ fontSize: '0.9rem', marginBottom: '20px' }}>
          <div><strong>Funding Scope:</strong> Full Tuition + €934/month Living Stipend</div>
          <div><strong>Application Deadline:</strong> Oct 31, 2025</div>
          <div><strong>Eligibility Status:</strong> Eligible</div>
          <div><strong>Application Pathway:</strong> University First</div>
        </div>

        <h3>Program Mandates</h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', marginTop: '6px', lineHeight: '1.6' }}>
          Candidates must possess at least two years of professional experience following their Bachelor degree completion. Academic records must demonstrate upper tier percentile performance.
        </p>
      </div>
    </div>
  );
}