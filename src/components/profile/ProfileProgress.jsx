import React from 'react';

export default function ProfileProgress({ percentage = 85 }) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', marginBottom: '6px' }}>
        <span style={{ fontWeight: '600', color: 'var(--color-dark)' }}>Profile Completeness</span>
        <strong style={{ color: 'var(--color-primary)' }}>{percentage}%</strong>
      </div>
      <div style={{ width: '100%', height: '8px', backgroundColor: '#E2E8F0', borderRadius: '4px', overflow: 'hidden' }}>
        <div style={{
          width: `${percentage}%`,
          height: '100%',
          backgroundColor: 'var(--color-primary)',
          transition: 'width 0.3s ease'
        }} />
      </div>
    </div>
  );
}