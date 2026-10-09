import { useNavigate } from 'react-router-dom';
import RequirementStatus from '../matching/RequirementStatus';
import MatchScoreCard from '../matching/MatchScoreCard';
import SaveButton from './SaveButton';
import { Calendar } from 'lucide-react';
import { ChevronSmallRightIcon } from '../ui/ChevronSmallRightIcon';
import { GlowCard } from '../ui/spotlight-card';

export default function OpportunityCard({ data, onSaveToggle }) {
  const navigate = useNavigate();

  if (!data) return null;

  return (
    <GlowCard customSize className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px', position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h3 style={{ fontSize: '1.1rem', color: 'var(--color-dark)', marginBottom: '4px' }}>
            {data.program || data.name}
          </h3>
          <p style={{ fontSize: '0.88rem', color: 'var(--color-primary)', fontWeight: '600' }}>
            {data.university || data.provider} • {data.country}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {data.matchScore !== undefined && <MatchScoreCard score={data.matchScore} />}
          <SaveButton
            isSaved={data.saved}
            label={data.program || data.name || data.title}
            onToggle={() => onSaveToggle && onSaveToggle(data.id)}
          />
        </div>
      </div>

      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
        <RequirementStatus status={data.eligibilityStatus || data.eligibility} />
        {data.deadline && (
          <span style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <Calendar size={13} /> Deadline: {data.deadline}
          </span>
        )}
      </div>

      {data.matchReason && (
        <div style={{ fontSize: '0.85rem', backgroundColor: '#F8FAFC', padding: '10px 12px', borderRadius: '6px', borderLeft: '3px solid var(--color-secondary)' }}>
          <strong style={{ color: 'var(--color-dark)' }}>Why this match?</strong> {data.matchReason}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px', paddingTop: '10px', borderTop: '1px solid var(--color-border)' }}>
        <span style={{ fontSize: '0.85rem', fontWeight: '700', color: 'var(--color-dark)' }}>
          {data.tuition ? `Tuition: ${data.tuition}` : data.coverage ? `Coverage: ${data.coverage}` : ''}
        </span>
        <button 
          className="btn btn-outline" 
          onClick={() => navigate(`/universities/${data.id}`)}
          style={{ fontSize: '0.82rem', padding: '6px 14px' }}
        >
          View Details <ChevronSmallRightIcon size={14} aria-hidden="true" />
        </button>
      </div>
    </GlowCard>
  );
}