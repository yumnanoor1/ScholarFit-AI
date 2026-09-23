import React from 'react';
import { GitBranch, CheckCircle, ArrowRight } from 'lucide-react';

export default function ApplicationPathway() {
  return (
    <div className="page-container">
      <h1 className="page-title">Application Pathway Selector</h1>
      <p className="page-subtitle">Determines optimal application sequencing to maximize admission and scholarship success.</p>

      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
          <GitBranch color="var(--color-primary)" />
          <h3>Pathway Strategy: Combined Application</h3>
        </div>

        <p style={{ fontSize: '0.88rem', color: 'var(--color-text-muted)', marginBottom: '24px' }}>
          For this institution, admission and departmental funding (RA/TA) are processed simultaneously using a single portal submission.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ padding: '12px', border: '1px solid var(--color-border)', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <CheckCircle color="var(--color-success)" size={20} />
            <span>Step 1: Secure Academic Recommendation Letters</span>
          </div>
          <div style={{ padding: '12px', border: '1px solid var(--color-border)', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <CheckCircle color="var(--color-success)" size={20} />
            <span>Step 2: Submit Application Form and Indicate Assistantship Interest</span>
          </div>
          <div style={{ padding: '12px', border: '1px solid var(--color-border)', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <ArrowRight color="var(--color-primary)" size={20} />
            <span>Step 3: Await Combined Faculty Evaluation Decision</span>
          </div>
        </div>
      </div>
    </div>
  );
}