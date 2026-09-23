import React from 'react';
import { TrendingUp, AlertCircle } from 'lucide-react';

export default function ProfileImprovement() {
  return (
    <div className="page-container">
      <h1 className="page-title">Profile Improvement Recommendations</h1>
      <p className="page-subtitle">Targeted actions to improve eligibility matching probability.</p>

      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
          <TrendingUp color="var(--color-primary)" />
          <h3>Academic Optimization Guidance</h3>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ backgroundColor: '#F8FAFC', padding: '14px', borderRadius: '6px', borderLeft: '4px solid var(--color-primary)' }}>
            <strong>1. Increase Test Scores</strong>
            <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', marginTop: '4px' }}>
              Improving IELTS from 7.5 to 8.0 unlocks eligibility for highly competitive UK Master's scholarships.
            </p>
          </div>

          <div style={{ backgroundColor: '#F8FAFC', padding: '14px', borderRadius: '6px', borderLeft: '4px solid var(--color-primary)' }}>
            <strong>2. Formalize Research Credentials</strong>
            <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', marginTop: '4px' }}>
              Publishing a pre-print version of your undergraduate capstone paper increases RA matching suitability scores.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}