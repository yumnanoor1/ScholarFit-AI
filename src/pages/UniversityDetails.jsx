import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiService } from '../services/api';
import { evaluateOpportunityEligibility, getOpportunityTitle } from '../services/opportunityJourney';
import { useProfile } from '../context/ProfileContext';
import OfficialApplicationLink from '../components/opportunities/OfficialApplicationLink';

export default function UniversityDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { profile, activeOpportunityId, selectOpportunity, appliedOpportunityIds, markOpportunityApplied } = useProfile();
  const [requestResult, setRequestResult] = useState(null);

  useEffect(() => {
    let cancelled = false;
    apiService.getOpportunityById(id).then((opportunity) => {
      if (!cancelled) setRequestResult({ id, data: opportunity?.kind === 'program' ? opportunity : null });
    }).catch((error) => {
      console.error('Unable to load university program details.', error);
      if (!cancelled) setRequestResult({ id, error: 'Program details could not be loaded.' });
    });
    return () => { cancelled = true; };
  }, [id]);

  const currentResult = requestResult?.id === id ? requestResult : null;
  const data = currentResult?.data || null;
  const loading = !currentResult;
  const loadError = currentResult?.error || '';
  if (loading) return <div className="page-container" role="status">Loading program details...</div>;
  if (loadError) return <div className="page-container" role="alert">{loadError}</div>;
  if (!data) {
    return (
      <div className="page-container">
        <h1>Program not found</h1>
        <p>This program ID is not available in the current opportunity data.</p>
        <button className="btn btn-outline" onClick={() => navigate('/universities')}>Back to Universities</button>
      </div>
    );
  }

  const eligibility = evaluateOpportunityEligibility(profile, data);
  const isActive = activeOpportunityId === data.id;

  return (
    <div className="page-container">
      <button className="btn btn-outline" onClick={() => navigate('/universities')} style={{ marginBottom: '16px' }}>
        Back to Universities
      </button>
      <section className="card">
        <h1 style={{ fontSize: '1.6rem', color: 'var(--color-dark)' }}>{getOpportunityTitle(data)}</h1>
        <p style={{ color: 'var(--color-primary)', fontWeight: '600' }}>{data.university} · {data.country}</p>
        <p>Profile fit: {data.matchScore ?? 'Unavailable'}% (mock match; confirm with the institution).</p>
        <h2>Requirements check</h2>
        {eligibility.requirements.length ? (
          <ul>
            {eligibility.requirements.map((requirement) => (
              <li key={requirement.id}>
                {requirement.label}: {requirement.status.replaceAll('-', ' ')}
                {requirement.status === 'awaiting-verification' && ' — sample requirement or profile information needs verification.'}
              </li>
            ))}
          </ul>
        ) : <p>{eligibility.message}</p>}
        <h2>Deadline and cost data</h2>
        <p>Listed deadline: {data.deadline || 'Not available'} (unverified sample; confirm with the university).</p>
        <p>Listed tuition: {data.tuition || 'Not available'} (unverified sample; no living-cost or confirmed-funding data is available here).</p>
        <button type="button" className="btn btn-primary" onClick={() => selectOpportunity({ ...data, kind: 'program' })}>
          {isActive ? 'Currently in your journey' : 'Select this program'}
        </button>
      </section>
      <OfficialApplicationLink
        opportunity={data}
        applied={appliedOpportunityIds.includes(data.id)}
        onToggleApplied={(value) => markOpportunityApplied(data.id, value)}
      />
    </div>
  );
}
