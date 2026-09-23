import React from 'react';
import { DollarSign, Award, CheckCircle } from 'lucide-react';

export default function FundingSummary({ totalMatched = 2, totalEstimatedFunding = 15000, fundingPreference = "Full Funding Required" }) {
  return (
    <div className="card">
      <h3 style={{ fontSize: '1rem', color: 'var(--color-dark)', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Award color="var(--color-primary)" size={20} />
        Funding Matching Summary
      </h3>

      <div className="grid-3" style={{ gap: '12px' }}>
        <div style={{ backgroundColor: '#F8FAFC', padding: '12px', borderRadius: '6px', border: '1px solid var(--color-border)' }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', display: 'block' }}>Target Funding Model</span>
          <strong style={{ fontSize: '0.9rem', color: 'var(--color-dark)' }}>{fundingPreference}</strong>
        </div>

        <div style={{ backgroundColor: '#F8FAFC', padding: '12px', borderRadius: '6px', border: '1px solid var(--color-border)' }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', display: 'block' }}>Matched Opportunities</span>
          <strong style={{ fontSize: '0.9rem', color: 'var(--color-primary)' }}>{totalMatched} Active Grants/Positions</strong>
        </div>

        <div style={{ backgroundColor: '#DCFCE7', padding: '12px', borderRadius: '6px', border: '1px solid #BBF7D0' }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--color-success)', display: 'block', fontWeight: '600' }}>Estimated Annual Coverage</span>
          <strong style={{ fontSize: '1rem', color: 'var(--color-success)' }}>
            ${totalEstimatedFunding.toLocaleString()} / year
          </strong>
        </div>
      </div>
    </div>
  );
}