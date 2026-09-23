import React from 'react';
import { Calendar, Clock, AlertTriangle } from 'lucide-react';

export default function DeadlineCard({ title, provider, deadline, daysRemaining, category = "Scholarship" }) {
  const isUrgent = daysRemaining !== undefined && daysRemaining <= 30;

  return (
    <div className="card" style={{
      borderLeft: `4px solid ${isUrgent ? 'var(--color-danger)' : 'var(--color-primary)'}`,
      padding: '16px',
      marginBottom: '12px'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span style={{ fontSize: '0.75rem', fontWeight: 'bold', color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>
            {category}
          </span>
          <h4 style={{ fontSize: '0.98rem', color: 'var(--color-dark)', marginTop: '2px', marginBottom: '4px' }}>
            {title}
          </h4>
          <p style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)' }}>{provider}</p>
        </div>

        {daysRemaining !== undefined && (
          <span style={{
            fontSize: '0.75rem',
            fontWeight: 'bold',
            padding: '4px 8px',
            borderRadius: '4px',
            backgroundColor: isUrgent ? '#FEF2F2' : '#F1F5F9',
            color: isUrgent ? 'var(--color-danger)' : 'var(--color-dark)',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px'
          }}>
            {isUrgent && <AlertTriangle size={12} />}
            {daysRemaining} days left
          </span>
        )}
      </div>

      <div style={{
        marginTop: '12px',
        paddingTop: '8px',
        borderTop: '1px solid var(--color-border)',
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        fontSize: '0.82rem',
        color: 'var(--color-primary)',
        fontWeight: '600'
      }}>
        <Calendar size={14} />
        <span>Official Deadline: {deadline}</span>
      </div>
    </div>
  );
}