import React from 'react';

export default function Compare() {
  return (
    <div className="page-container">
      <h1 className="page-title">Program Side-by-Side Comparison</h1>
      <p className="page-subtitle">Comparative evaluation of options against key eligibility metrics.</p>

      <div className="card" style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
              <th style={{ padding: '12px' }}>Feature</th>
              <th style={{ padding: '12px' }}>TU Munich (Germany)</th>
              <th style={{ padding: '12px' }}>Univ of Toronto (Canada)</th>
            </tr>
          </thead>
          <tbody>
            <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
              <td style={{ padding: '12px', fontWeight: 'bold' }}>Fit Score</td>
              <td style={{ padding: '12px', color: 'var(--color-success)' }}>94% Fit</td>
              <td style={{ padding: '12px', color: 'var(--color-warning)' }}>78% Fit</td>
            </tr>
            <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
              <td style={{ padding: '12px', fontWeight: 'bold' }}>Estimated Tuition</td>
              <td style={{ padding: '12px' }}>$600 / yr</td>
              <td style={{ padding: '12px' }}>$28,000 / yr</td>
            </tr>
            <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
              <td style={{ padding: '12px', fontWeight: 'bold' }}>Eligibility Status</td>
              <td style={{ padding: '12px' }}>Eligible</td>
              <td style={{ padding: '12px' }}>Requirements Missing</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}