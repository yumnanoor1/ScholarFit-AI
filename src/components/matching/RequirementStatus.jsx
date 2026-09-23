import React from 'react';
import { CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';

export default function RequirementStatus({ status }) {
  let bgColor = "#E2E8F0";
  let textColor = "#475569";
  let Icon = AlertTriangle;

  if (status === "Eligible") {
    bgColor = "#DCFCE7";
    textColor = "var(--color-success)";
    Icon = CheckCircle2;
  } else if (status === "Not Eligible") {
    bgColor = "#FEE2E2";
    textColor = "var(--color-danger)";
    Icon = XCircle;
  } else if (status === "Requirements Missing") {
    bgColor = "#FEF3C7";
    textColor = "var(--color-warning)";
    Icon = AlertTriangle;
  }

  return (
    <span style={{
      backgroundColor: bgColor,
      color: textColor,
      padding: '4px 10px',
      borderRadius: '12px',
      fontSize: '0.75rem',
      fontWeight: 'bold',
      display: 'inline-flex',
      alignItems: 'center',
      gap: '5px'
    }}>
      <Icon size={14} />
      {status}
    </span>
  );
}