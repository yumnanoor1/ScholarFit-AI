import React from 'react';

export default function Footer() {
  return (
    <footer style={{
      padding: '20px 24px',
      backgroundColor: 'var(--color-white)',
      borderTop: '1px solid var(--color-border)',
      fontSize: '0.82rem',
      color: 'var(--color-text-muted)',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginTop: 'auto'
    }}>
      <div>
        © {new Date().getFullYear()} <strong>FitScholar AI</strong> — Study Abroad & Scholarship Decision-Support System
      </div>
      <div style={{ display: 'flex', gap: '16px' }}>
        <span>Deterministic Matching Engine</span>
        <span>•</span>
        <span>FYP Demonstration Version</span>
      </div>
    </footer>
  );
}