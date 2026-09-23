import React from 'react';
import FundingBadge from './FundingBadge';
import RequirementStatus from '../matching/RequirementStatus';
import MatchScoreCard from '../matching/MatchScoreCard';
import { Calendar, DollarSign, Building2, MapPin } from 'lucide-react';

export default function FundingCard({ item, onSaveToggle }) {
  if (!item) return null;

  return (
    <div className="card" style={{ borderLeft: '4px solid var(--color-secondary)', position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px' }}>
        <div>
          <h4 style={{ fontSize: '1.05rem', color: 'var(--color-dark)', marginBottom: '4px' }}>
            {item.name}
          </h4>
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><Building2 size={14} /> {item.provider}</span>
            <span>•</span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><MapPin size={14} /> {item.country}</span>
          </p>
        </div>

        {item.matchScore !== undefined && <MatchScore score={item.matchScore} />}
      </div>

      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', margin: '12px 0', flexWrap: 'wrap' }}>
        <FundingBadge type={item.type} />
        {item.eligibility && <RequirementStatus status={item.eligibility} />}
        {item.deadline && (
          <span style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <Calendar size={13} /> Deadline: {item.deadline}
          </span>
        )}
      </div>

      <div style={{
        backgroundColor: '#F8FAFC',
        padding: '10px 12px',
        borderRadius: '6px',
        fontSize: '0.88rem',
        color: 'var(--color-primary)',
        fontWeight: '600',
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        marginTop: '8px'
      }}>
        <DollarSign size={16} />
        <span>Coverage: {item.coverage}</span>
      </div>
    </div>
  );
}