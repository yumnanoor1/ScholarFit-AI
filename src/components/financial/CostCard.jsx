import React from 'react';
import { DollarSign, AlertCircle } from 'lucide-react';

export default function CostCard({ label, amount, type = "expense", note = null }) {
  let accentColor = "var(--color-dark)";
  let bgColor = "#F8FAFC";

  if (type === "funding") {
    accentColor = "var(--color-success)";
    bgColor = "#DCFCE7";
  } else if (type === "remaining") {
    accentColor = amount > 0 ? "var(--color-danger)" : "var(--color-success)";
    bgColor = amount > 0 ? "#FEF2F2" : "#DCFCE7";
  }

  return (
    <div style={{
      backgroundColor: bgColor,
      border: '1px solid var(--color-border)',
      borderRadius: '8px',
      padding: '16px',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between'
    }}>
      <div>
        <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', fontWeight: '600', textTransform: 'uppercase' }}>
          {label}
        </span>
        <div style={{ fontSize: '1.4rem', fontWeight: '800', color: accentColor, marginTop: '4px' }}>
          ${amount.toLocaleString()} <span style={{ fontSize: '0.8rem', fontWeight: 'normal', color: 'var(--color-text-muted)' }}>/ year</span>
        </div>
      </div>

      {note && (
        <p style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
          <AlertCircle size={12} /> {note}
        </p>
      )}
    </div>
  );
}