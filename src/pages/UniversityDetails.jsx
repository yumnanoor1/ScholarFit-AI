import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiService } from '../services/api';
import RequirementStatus from '../components/matching/RequirementStatus';
import CostBreakdown from '../components/financial/CostBreakdown';
import MatchScoreCard from '../components/matching/MatchScoreCard';

export default function UniversityDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);

  useEffect(() => {
    apiService.getMatchedUniversities().then(list => {
      const match = list.find(u => u.id === id) || list[0];
      setData(match);
    });
  }, [id]);

  if (!data) return <div className="page-container">Loading program details...</div>;

  return (
    <div className="page-container">
      <button className="btn btn-outline" onClick={() => navigate(-1)} style={{ marginBottom: '16px' }}>
        ← Back to Universities
      </button>

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h1 style={{ fontSize: '1.6rem', color: 'var(--color-dark)' }}>{data.program}</h1>
            <p style={{ color: 'var(--color-primary)', fontWeight: '600' }}>{data.university} • {data.country}</p>
          </div>
          <MatchScoreCard score={data.matchScore} />
        </div>

        <div style={{ display: 'flex', gap: '12px', margin: '16px 0' }}>
          <RequirementStatus status={data.eligibilityStatus} />
          <span style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>Verified Term: 2026 - 2027</span>
        </div>

        <h3 style={{ marginTop: '20px', fontSize: '1rem' }}>Requirements Evaluation</h3>
        <ul style={{ paddingLeft: '20px', margin: '10px 0', fontSize: '0.9rem' }}>
          <li style={{ color: data.cgpaReqSatisfied ? 'var(--color-success)' : 'var(--color-danger)', marginBottom: '6px' }}>
            CGPA Threshold: Required {data.cgpaReq} (Your Score: 3.65)
          </li>
          <li style={{ color: data.englishReqSatisfied ? 'var(--color-success)' : 'var(--color-danger)' }}>
            Language Proficiency: Required {data.englishReq} (Your Score: IELTS 7.5)
          </li>
        </ul>
      </div>

      <CostBreakdown tuition={12000} living={10000} funding={15000} />
    </div>
  );
}