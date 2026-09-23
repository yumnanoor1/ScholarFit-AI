import React from 'react';
import TimelineItem from './TimelineItem';
import { Calendar } from 'lucide-react';

export default function Timeline({ items = [] }) {
  if (!items || items.length === 0) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
        <Calendar size={36} color="var(--color-secondary)" style={{ marginBottom: '10px' }} />
        <h4 style={{ fontSize: '1rem', color: 'var(--color-dark)', marginBottom: '4px' }}>No Milestone Dates Scheduled</h4>
        <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
          Save universities and scholarships to auto-populate your academic preparation timeline.
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      <h3 style={{ fontSize: '1.1rem', color: 'var(--color-dark)', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Calendar size={20} color="var(--color-primary)" />
        Academic Preparation & Application Schedule
      </h3>

      <div style={{ marginTop: '16px' }}>
        {items.map((item, idx) => (
          <TimelineItem
            key={idx}
            date={item.date}
            title={item.title}
            description={item.description}
            status={item.status || "upcoming"}
            isLast={idx === items.length - 1}
          />
        ))}
      </div>
    </div>
  );
}