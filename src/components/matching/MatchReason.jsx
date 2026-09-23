import React from 'react';
import { HelpCircle } from 'lucide-react';

export default function MatchReason({ reason, title = "Why this match?" }) {
  if (!reason) return null;

  return (
    <div style={{
      backgroundColor: '#F8FAFC',
      borderLeft: '3px solid var(--color-secondary)',
      padding: '10px 14px',
      borderRadius: '0 6px 6px 0',
      fontSize: '0.85rem',
      color: 'var(--color-dark)',
      margin: '8px 0'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 'bold', marginBottom: '4px', color: 'var(--color-primary)' }}>
        <HelpCircle size={15} />
        <span>{title}</span>
      </div>
      <p style={{ margin: 0, color: 'var(--color-text-muted)', lineHeight: '1.4' }}>
        {reason}
      </p>
    </div>
  );
}