import React from 'react';
import { CheckCircle2, AlertTriangle, Lightbulb } from 'lucide-react';

export default function RecommendationReason({ reasons = [], missingReq = null }) {
  return (
    <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {/* Supporting Rationale */}
      {reasons && reasons.length > 0 && (
        <div style={{ backgroundColor: '#F8FAFC', padding: '10px 12px', borderRadius: '6px', fontSize: '0.85rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 'bold', color: 'var(--color-primary)', marginBottom: '4px' }}>
            <Lightbulb size={15} />
            <span>Why Recommended?</span>
          </div>
          <ul style={{ paddingLeft: '20px', margin: 0, color: 'var(--color-dark)' }}>
            {reasons.map((r, idx) => (
              <li key={idx} style={{ marginBottom: '2px' }}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Missing Requirements / Gaps */}
      {missingReq && (
        <div style={{ backgroundColor: '#FEF2F2', padding: '10px 12px', borderRadius: '6px', fontSize: '0.82rem', color: 'var(--color-danger)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 'bold', marginBottom: '2px' }}>
            <AlertTriangle size={15} color="var(--color-danger)" />
            <span>Actionable Gap Identified</span>
          </div>
          <p style={{ margin: 0 }}>{missingReq}</p>
        </div>
      )}
    </div>
  );
}