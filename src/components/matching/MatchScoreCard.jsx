import React from 'react';

export default function MatchScoreCard({ score = 85, label = "Match Score" }) {
  let scoreColor = "var(--color-primary)";
  if (score >= 90) scoreColor = "var(--color-success)";
  else if (score < 75) scoreColor = "var(--color-warning)";

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      backgroundColor: '#FFFFFF',
      padding: '8px 12px',
      borderRadius: '8px',
      border: '1px solid var(--color-border)'
    }}>
      <div style={{
        width: '44px',
        height: '44px',
        borderRadius: '50%',
        backgroundColor: scoreColor,
        color: '#FFFFFF',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontWeight: 'bold',
        fontSize: '0.9rem',
        boxShadow: '0 2px 4px rgba(0,0,0,0.08)'
      }}>
        {score}%
      </div>
      <div>
        <span style={{ fontSize: '0.85rem', fontWeight: 'bold', color: 'var(--color-dark)', display: 'block' }}>
          {label}
        </span>
        <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
          Academic & Funding Fit
        </span>
      </div>
    </div>
  );
}