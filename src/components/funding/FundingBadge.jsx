import React from 'react';
import { Award, GraduationCap, DollarSign, Briefcase } from 'lucide-react';

export default function FundingBadge({ type }) {
  let bgColor = '#E2E8F0';
  let textColor = '#334155';
  let Icon = Award;

  if (type === 'Scholarship') {
    bgColor = '#EBF3FA';
    textColor = 'var(--color-primary)';
    Icon = Award;
  } else if (type === 'RA' || type === 'TA' || type === 'Fellowship') {
    bgColor = '#DCFCE7';
    textColor = 'var(--color-success)';
    Icon = type === 'Fellowship' ? GraduationCap : Briefcase;
  } else if (type === 'Tuition Waiver') {
    bgColor = '#FEF3C7';
    textColor = 'var(--color-warning)';
    Icon = DollarSign;
  }

  return (
    <span style={{
      backgroundColor: bgColor,
      color: textColor,
      padding: '4px 10px',
      borderRadius: '6px',
      fontSize: '0.75rem',
      fontWeight: 'bold',
      display: 'inline-flex',
      alignItems: 'center',
      gap: '4px'
    }}>
      <Icon size={13} />
      {type}
    </span>
  );
}