import React from 'react';
import { useNavigate } from 'react-router-dom';
import RecommendationReason from './RecommendationReason';
import MatchScoreCard from '../matching/MatchScoreCard';
import RequirementStatus from '../matching/RequirementStatus';
import { ArrowRight, Building2, MapPin, Calendar } from 'lucide-react';

export default function RecommendationCard({
  id,
  title,
  university,
  country,
  deadline,
  eligibilityStatus = "Eligible",
  score = 92,
  reasons = [],
  missingReq = null,
  nextAction = "Submit preliminary application"
}) {
  const navigate = useNavigate();

  return (
    <div className="card" style={{ borderTop: '4px solid var(--color-primary)', marginBottom: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
        <div>
          <h3 style={{ fontSize: '1.15rem', color: 'var(--color-dark)', marginBottom: '4px' }}>
            {title}
          </h3>
          <p style={{ fontSize: '0.88rem', color: 'var(--color-primary)', fontWeight: '600', display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><Building2 size={14} /> {university}</span>
            <span>•</span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><MapPin size={14} /> {country}</span>
          </p>
        </div>

        <MatchScoreCard score={score} />
      </div>

      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '10px' }}>
        <RequirementStatus status={eligibilityStatus} />
        {deadline && (
          <span style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <Calendar size={13} /> Deadline: {deadline}
          </span>
        )}
      </div>

      <RecommendationReason reasons={reasons} missingReq={missingReq} />

      <div style={{
        marginTop: '16px',
        paddingTop: '12px',
        borderTop: '1px solid var(--color-border)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)' }}>
          <strong>Suggested Action:</strong> {nextAction}
        </div>
        <button 
          className="btn btn-outline" 
          onClick={() => navigate(`/universities/${id || 1}`)}
          style={{ fontSize: '0.82rem', padding: '6px 14px' }}
        >
          View Full Breakdown <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}