import React from 'react';
import { Calendar, CheckCircle2, Clock, AlertCircle } from 'lucide-react';

export default function TimelineItem({ date, title, description, status = "upcoming", isLast = false }) {
  let badgeColor = "var(--color-primary)";
  let badgeBg = "#EBF3FA";
  let Icon = Clock;

  if (status === "completed") {
    badgeColor = "var(--color-success)";
    badgeBg = "#DCFCE7";
    Icon = CheckCircle2;
  } else if (status === "urgent") {
    badgeColor = "var(--color-danger)";
    badgeBg = "#FEF2F2";
    Icon = AlertCircle;
  }

  return (
    <div style={{ display: 'flex', gap: '16px', position: 'relative' }}>
      {/* Date Marker Column */}
      <div style={{ minWidth: '100px', textAlign: 'right', paddingTop: '2px' }}>
        <span style={{ fontSize: '0.8rem', fontWeight: 'bold', color: 'var(--color-primary)', display: 'block' }}>
          {date}
        </span>
        <span style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', textTransform: 'capitalize' }}>
          {status}
        </span>
      </div>

      {/* Visual Axis Line & Node */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{
          width: '28px',
          height: '28px',
          borderRadius: '50%',
          backgroundColor: badgeBg,
          color: badgeColor,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          zIndex: 1,
          border: `1px solid ${badgeColor}`
        }}>
          <Icon size={16} />
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

      {/* Detail Content */}
      <div style={{ paddingBottom: isLast ? '0' : '24px', flex: 1 }}>
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
