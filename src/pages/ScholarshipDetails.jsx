import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiService } from '../services/api';
import { evaluateOpportunityEligibility, getOpportunityTitle } from '../services/opportunityJourney';
import { useProfile } from '../context/ProfileContext';
import OfficialApplicationLink from '../components/opportunities/OfficialApplicationLink';

export default function ScholarshipDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { profile, activeOpportunityId, selectOpportunity, appliedOpportunityIds, markOpportunityApplied } = useProfile();
  const [requestResult, setRequestResult] = useState(null);

  useEffect(() => {
    let cancelled = false;
    apiService.getOpportunityById(id).then((opportunity) => {
      if (!cancelled) setRequestResult({ id, data: opportunity?.kind === 'scholarship' ? opportunity : null });
    }).catch((error) => {
      console.error('Unable to load scholarship details.', error);
      if (!cancelled) setRequestResult({ id, error: 'Scholarship details could not be loaded.' });
    });
    return () => { cancelled = true; };
  }, [id]);

  const currentResult = requestResult?.id === id ? requestResult : null;
  const data = currentResult?.data || null;
  const loading = !currentResult;
  const loadError = currentResult?.error || '';
  if (loading) return <div className="page-container" role="status">Loading scholarship details...</div>;
  if (loadError) return <div className="page-container" role="alert">{loadError}</div>;
  if (!data) {
    return (
      <div className="page-container">
        <h1>Scholarship not found</h1>
        <p>This scholarship ID is not available in the current opportunity data.</p>
        <button className="btn btn-outline" onClick={() => navigate('/scholarships')}>Back to Scholarships</button>
      </div>
    );
  }

  const eligibility = evaluateOpportunityEligibility(profile, data);
  const isActive = activeOpportunityId === data.id;

  return (
    <div className="page-container">
      <button className="btn btn-outline" onClick={() => navigate('/scholarships')} style={{ marginBottom: '16px' }}>
        Back to Scholarships
      </button>
      <section className="card">
        <h1 style={{ fontSize: '1.5rem', marginBottom: '4px' }}>{getOpportunityTitle(data)}</h1>
        <p style={{ color: 'var(--color-primary)', fontWeight: '600', marginBottom: '16px' }}>
          {data.provider || 'Provider not listed'} · {data.country || 'Country not listed'}
        </p>
        <div className="grid-2" style={{ fontSize: '0.9rem', marginBottom: '20px' }}>
          <div><strong>Funding scope:</strong> {data.coverage || 'Not available'}</div>
          <div><strong>Application deadline:</strong> {data.deadline || 'Not available'} (unverified sample)</div>
          <div><strong>Profile fit:</strong> {data.matchScore ?? 'Unavailable'}% (mock match)</div>
          <div><strong>Eligibility:</strong> {eligibility.message || 'Awaiting verification'}</div>
        </div>
        <h2>Requirements</h2>
        <p>{eligibility.message || 'No structured scholarship requirements are available. Verify eligibility directly with the provider.'}</p>
        <p>Funding values and dates are sample listing data, not confirmed awards or official deadlines.</p>
        <button type="button" className="btn btn-primary" onClick={() => selectOpportunity({ ...data, kind: 'scholarship' })}>
          {isActive ? 'Currently in your journey' : 'Select this scholarship'}
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
