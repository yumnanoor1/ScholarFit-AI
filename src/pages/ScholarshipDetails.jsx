import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Bookmark } from 'lucide-react';
import { apiService } from '../services/api';
import { evaluateOpportunityEligibility, getOpportunityTitle } from '../services/opportunityJourney';
import { useProfile } from '../context/ProfileContext';
import OfficialApplicationLink from '../components/opportunities/OfficialApplicationLink';
import EligibilityBadge from '../components/opportunities/EligibilityBadge';
import { useScholarshipEligibility } from '../hooks/useProgramEligibility';
import { getScholarshipDeadlineLabel } from '../services/eligibilityBadges';
import { fetchScholarshipPrograms, getSelectedProgramId, parseScholarshipId } from '../services/opportunityApi';
import ScholarshipProgramMatches from '../components/opportunities/ScholarshipProgramMatches';
import ScholarshipRecommendationCard from '../components/opportunities/ScholarshipRecommendationCard';
import { OpportunityCompareCheckbox } from '../components/opportunities/ComparisonControls';
import SavedStatusNotice from '../components/opportunities/SavedStatusNotice';
import './Universities.css';
import './UniversityDetails.css';

// Per-requirement result labels (the overall result uses EligibilityBadge)
const REQUIREMENT_LABELS = {
  satisfied: { label: 'Met', tone: 'success' },
  'not-satisfied': { label: 'Not met', tone: 'danger' },
  'missing-information': { label: 'Missing info', tone: 'warning' },
  'awaiting-verification': { label: 'Verify manually', tone: 'neutral' },
};

const UNAVAILABLE_NOTICES = {
  'logged-out': ['Log in to check your eligibility for this scholarship.', '/login', 'Log in'],
  'no-profile': ['Complete your profile to check your eligibility for this scholarship.', '/profile', 'Complete profile'],
};

export default function ScholarshipDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const {
    profile, activeOpportunityId, selectOpportunity, appliedOpportunityIds, markOpportunityApplied, isOpportunitySaved, toggleSaveOpportunity,
  } = useProfile();
  const [requestResult, setRequestResult] = useState(null);
  // Backend scholarships (sch-db-N) are evaluated by GET /eligibility/scholarships/{id}
  const isBackendId = parseScholarshipId(id) != null;
  const backendEligibility = useScholarshipEligibility(id);

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

  // Older sample scholarships keep the local check
  const eligibility = isBackendId ? backendEligibility.evaluation : evaluateOpportunityEligibility(profile, data);
  const eligibilityState = isBackendId ? backendEligibility.state : 'ok';
  const deadline = isBackendId ? getScholarshipDeadlineLabel(eligibility?.deadline) : null;
  const isActive = activeOpportunityId === data.id;
  const saved = isOpportunitySaved(data.id);
  // Backend records carry their own source status; old sample records do not
  const isBackend = data.sourceStatus === 'official-verified' || data.sourceStatus === 'unverified';
  const isVerified = data.sourceStatus === 'official-verified';
  const requirementRows = [
    ['Degree level', data.degree],
    ['Eligible nationalities', data.eligibleNationalities],
    ['Open to Pakistani students', data.pakistanEligible],
    ['Eligible fields', data.eligibleFields],
    ['Academic requirement', data.academicRequirement],
    ["Bachelor's degree", data.bachelorsRequirement],
    ['English requirement', data.englishRequirement],
    ['Work experience', data.workExperience],
    ['Age requirement', data.ageRequirement],
  ].filter(([, value]) => value);
  const applicationRows = [
    ...(data.deadlineRows || []),
    ['Application method', data.applicationMethod],
    ['Admission required first', data.admissionRequired],
    ['Nomination required', data.nominationRequired],
    ['Required documents', data.requiredDocumentsText],
    ['Application pathway', data.applicationPathwayText],
    ['Notes', data.notes],
  ].filter(([, value]) => value);

  return (
    <div className="page-container scholarship-detail-page">
      <button className="btn btn-outline" onClick={() => navigate('/scholarships')} style={{ marginBottom: '16px' }}>
        Back to Scholarships
      </button>
      <section className="card scholarship-detail-card">
        <h1 style={{ fontSize: '1.5rem', marginBottom: '4px' }}>{getOpportunityTitle(data)}</h1>
        <p style={{ color: 'var(--color-primary)', fontWeight: '600', marginBottom: '16px' }}>
          {data.provider || 'Provider not listed'} · {data.country || 'Country not listed'}
        </p>
        {data.archived && <p className="saved-unverified-warning">This scholarship is no longer listed, so its details may be out of date.</p>}
        {data.sourceStatus === 'unverified' && (
          <p className="saved-unverified-warning">This scholarship is currently unverified.</p>
        )}
        <div className="grid-2" style={{ fontSize: '0.9rem', marginBottom: '20px' }}>
          <div><strong>Funding type:</strong> {data.type || 'Not available'}</div>
          <div><strong>Funding scope:</strong> {data.coverage || 'Not available'}</div>
          <div>
            <strong>Application deadline:</strong> {data.deadline || 'Not available'}
            {isBackend ? '' : ' (unverified sample)'}
            {deadline && <> · <strong>{deadline.note}</strong></>}
          </div>
          {data.duration && <div><strong>Duration:</strong> {data.duration}</div>}
          {!isBackend && <div><strong>Profile fit:</strong> {data.matchScore ?? 'Unavailable'}% (mock match)</div>}
          {!isBackendId && <div><strong>Eligibility:</strong> {eligibility.message || 'Awaiting verification'}</div>}
        </div>

        {isBackendId && (
          <section className="scholarship-eligibility-result" aria-live="polite">
            <h2>Your eligibility</h2>
            {backendEligibility.loading ? (
              <p role="status">Checking your profile against this scholarship...</p>
            ) : eligibilityState !== 'ok' ? (
              <p className="university-notice" role="status">
                <span>{UNAVAILABLE_NOTICES[eligibilityState]?.[0] || eligibility?.message || 'Eligibility could not be checked right now.'}</span>
                {UNAVAILABLE_NOTICES[eligibilityState] && (
                  <Link to={UNAVAILABLE_NOTICES[eligibilityState][1]}>{UNAVAILABLE_NOTICES[eligibilityState][2]}</Link>
                )}
              </p>
            ) : (
              <>
                <div className="scholarship-eligibility-summary">
                  <EligibilityBadge status={eligibility.status} />
                  <span>{eligibility.summary}</span>
                </div>
                <ul className="scholarship-requirement-list">
                  {eligibility.requirements.map((item) => {
                    const badge = REQUIREMENT_LABELS[item.status] || REQUIREMENT_LABELS['awaiting-verification'];
                    return (
                      <li key={item.id}>
                        <span className={`program-status is-${badge.tone}`}>{badge.label}</span>
                        <div>
                          <strong>{item.label}</strong>
                          <p>{item.message}{item.scope === 'admission' ? ' (checked by the university during admission)' : ''}</p>
                          {item.sourceText && <small>Record says: {item.sourceText}</small>}
                        </div>
                      </li>
                    );
                  })}
                </ul>
                {eligibility.deadline?.message && eligibility.deadline.status !== 'closed' && (
                  <p className="scholarship-eligibility-note"><strong>Deadline:</strong> {eligibility.deadline.message}</p>
                )}
                {eligibility.notes.map((note) => <p key={note} className="scholarship-eligibility-note">{note}</p>)}
              </>
            )}
          </section>
        )}

        {isBackendId && <ScholarshipRecommendationCard scholarshipId={id} programId={getSelectedProgramId(activeOpportunityId)} />}

        {isBackendId && (
          <section className="scholarship-eligibility-result">
            <h2>Linked programs</h2>
            <ScholarshipProgramMatches load={fetchScholarshipPrograms} recordId={id} side="program" />
          </section>
        )}

        {data.duplicateOf && (
          <p className="scholarship-eligibility-note">
            This looks like the same scholarship as <Link to={`/scholarships/${data.duplicateOf}`}>another listing</Link>, which has fuller details.
          </p>
        )}

        {data.requirementSummaryRows && (
          <>
            <h2>Requirements at a glance</h2>
            <ul style={{ margin: '8px 0 20px', paddingLeft: '20px', fontSize: '0.9rem' }}>
              {data.requirementSummaryRows.map(([label, value]) => <li key={label}><strong>{label}:</strong> {value}</li>)}
            </ul>
          </>
        )}

        {(data.fundingRows || data.benefits?.length > 0) && <h2>What it covers</h2>}
        {data.fundingRows && (
          <ul style={{ margin: '8px 0 20px', paddingLeft: '20px', fontSize: '0.9rem' }}>
            {data.fundingRows.map(([label, value]) => <li key={label}><strong>{label}:</strong> {value}</li>)}
          </ul>
        )}
        {data.benefits?.length > 0 && (data.fundingRows ? (
          <details style={{ margin: '0 0 20px', fontSize: '0.9rem' }}>
            <summary>Original funding wording</summary>
            <ul style={{ margin: '8px 0 0', paddingLeft: '20px' }}>
              {data.benefits.map((benefit) => (
                <li key={benefit.label}><strong>{benefit.label}:</strong> {benefit.value}</li>
              ))}
            </ul>
          </details>
        ) : (
          <ul style={{ margin: '8px 0 20px', paddingLeft: '20px', fontSize: '0.9rem' }}>
            {data.benefits.map((benefit) => (
              <li key={benefit.label}><strong>{benefit.label}:</strong> {benefit.value}</li>
            ))}
          </ul>
        ))}

        {(!isBackendId || eligibilityState !== 'ok') && <h2>Requirements</h2>}
        {isBackendId && eligibilityState === 'ok' ? null : requirementRows.length > 0 ? (
          <ul style={{ margin: '8px 0 20px', paddingLeft: '20px', fontSize: '0.9rem' }}>
            {requirementRows.map(([label, value]) => <li key={label}><strong>{label}:</strong> {value}</li>)}
          </ul>
        ) : (
          <p>{eligibility.message || 'No structured scholarship requirements are available. Verify eligibility directly with the provider.'}</p>
        )}

        {applicationRows.length > 0 && (
          <>
            <h2>Applying</h2>
            <ul style={{ margin: '8px 0 20px', paddingLeft: '20px', fontSize: '0.9rem' }}>
              {applicationRows.map(([label, value]) => <li key={label}><strong>{label}:</strong> {value}</li>)}
            </ul>
          </>
        )}

        {data.officialLinks?.length > 0 && (
          <>
            <h2>Official links</h2>
            <ul style={{ margin: '8px 0 20px', paddingLeft: '20px', fontSize: '0.9rem' }}>
              {data.officialLinks.map((link) => (
                <li key={link.url}>
                  <strong>{link.label}:</strong> <a href={link.url} target="_blank" rel="noopener noreferrer">{link.url}</a>
                </li>
              ))}
            </ul>
          </>
        )}

        {isBackend ? (
          <>
            <p>
              {data.verificationText || (isVerified ? 'Recorded from the official source' : 'Not yet verified against the official source')}
              {data.sourceName ? ` (${data.sourceName})` : ''}
              {data.lastVerified ? `, last verified ${data.lastVerified}` : ''}.
              {' '}Confirm current terms and dates with the provider before applying.
            </p>
            {data.verificationNotes && <p>{data.verificationNotes}</p>}
          </>
        ) : (
          <p>Funding values and dates are sample listing data, not confirmed awards or official deadlines.</p>
        )}
        <div className="program-detail-actions">
          <button type="button" className="btn btn-primary" onClick={() => selectOpportunity({ ...data, kind: 'scholarship' })}>
            {isActive ? 'Currently in your journey' : 'Select this scholarship'}
          </button>
          {/* An archived scholarship can be removed from Saved but not newly added */}
          {(!data.archived || saved) && (
            <button
              type="button"
              className={`program-detail-icon-button ${saved ? 'is-saved' : ''}`}
              aria-pressed={saved}
              onClick={() => toggleSaveOpportunity(data.id)}
            >
              <Bookmark size={16} fill={saved ? 'currentColor' : 'none'} aria-hidden="true" /> {saved ? 'Saved' : 'Save'}
            </button>
          )}
          {!data.archived && <OpportunityCompareCheckbox opportunity={{ ...data, title: data.name }} />}
        </div>
        <SavedStatusNotice />
      </section>
      <OfficialApplicationLink
        opportunity={data}
        applied={appliedOpportunityIds.includes(data.id)}
        onToggleApplied={(value) => markOpportunityApplied(data.id, value)}
      />
    </div>
  );
}
