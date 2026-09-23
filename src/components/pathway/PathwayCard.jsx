import React from 'react';
import PathwaySteps from './PathwaySteps';
import { GitBranch, AlertTriangle } from 'lucide-react';

export default function PathwayCard({ type = "University First", steps = [], note = null }) {
  const isUnclear = type === "Unclear";

  return (
    <div className="card" style={{ borderTop: `4px solid ${isUnclear ? 'var(--color-warning)' : 'var(--color-primary)'}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
        {isUnclear ? (
          <AlertTriangle color="var(--color-warning)" size={20} />
        ) : (
          <GitBranch color="var(--color-primary)" size={20} />
        )}
        <h3 style={{ fontSize: '1.1rem', color: 'var(--color-dark)', margin: 0 }}>
          Application Pathway: {type}
        </h3>
      </div>

      {isUnclear ? (
        <div style={{
          backgroundColor: '#FEF3C7',
          color: '#92400E',
          padding: '12px 16px',
          borderRadius: '6px',
          fontSize: '0.88rem',
          marginTop: '12px'
        }}>
          <strong>Application pathway unclear — verify official instructions.</strong>
          <p style={{ margin: '4px 0 0 0', fontSize: '0.82rem' }}>
            Official portal guidelines do not explicitly separate funding and admission deadlines. Verify with university admissions directly.
          </p>
        </div>
      ) : (
        <>
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', marginBottom: '16px' }}>
            Follow this step-by-step sequence to ensure both admission and funding applications are submitted correctly.
          </p>
          <PathwaySteps steps={steps} />
        </>
      )}

      {note && !isUnclear && (
        <div style={{
          marginTop: '16px',
          paddingTop: '12px',
          borderTop: '1px solid var(--color-border)',
          fontSize: '0.8rem',
          color: 'var(--color-text-muted)',
          fontStyle: 'italic'
        }}>
          * {note}
        </div>
      )}
    </div>
  );
}
