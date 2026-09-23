import React from 'react';
import { CheckCircle2, Clock, AlertCircle } from 'lucide-react';

export default function StepItem({ stepNumber, title, description, status = "pending", isLast = false }) {
  let iconColor = "var(--color-primary)";
  let borderColor = "var(--color-border)";
  let Icon = Clock;

  if (status === "completed") {
    iconColor = "var(--color-success)";
    borderColor = "var(--color-success)";
    Icon = CheckCircle2;
  } else if (status === "unclear") {
    iconColor = "var(--color-warning)";
    borderColor = "var(--color-warning)";
    Icon = AlertCircle;
  }

  return (
    <div style={{ display: 'flex', gap: '16px', position: 'relative' }}>
      {/* Visual Timeline Marker & Line */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{
          width: '32px',
          height: '32px',
          borderRadius: '50%',
          backgroundColor: '#FFFFFF',
          border: `2px solid ${borderColor}`,
          color: iconColor,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '0.85rem',
          fontWeight: 'bold',
          flexShrink: 0,
          zIndex: 1
        }}>
          {status === "completed" ? <Icon size={18} /> : stepNumber}
        </div>
        {!isLast && (
          <div style={{
            width: '2px',
            flexGrow: 1,
            backgroundColor: 'var(--color-border)',
            margin: '4px 0'
          }} />
        )}
      </div>

      {/* Step Description Content */}
      <div style={{ paddingBottom: isLast ? '0' : '24px' }}>
        <h4 style={{ fontSize: '0.95rem', color: 'var(--color-dark)', marginBottom: '4px' }}>
          {title}
        </h4>
        {description && (
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', margin: 0, lineHeight: '1.4' }}>
            {description}
          </p>
        )}
      </div>
    </div>
  );
}
