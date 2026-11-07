import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight, CalendarDays, Check, Clock3, Scale, ShieldCheck, Star, Wallet,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import { useScholarshipEligibility, useScholarshipRecommendations } from '../hooks/useScholarshipEligibility';
import { getOpportunityTitle } from '../services/opportunityJourney';
import { getScholarshipLogo } from '../services/scholarshipLogos';
import ScholarshipLogo from '../components/common/ScholarshipLogo';
import RetryButton from '../components/common/RetryButton';
import './Dashboard.css';

function getUpcomingDeadlines(opportunities) {
  const today = new Date().toISOString().slice(0, 10);
  return opportunities
    .filter((item) => item.deadlineDate && item.deadlineDate >= today
      && item.verificationStatus === 'verified' && item.sourceUrl && item.lastVerified)
    .sort((first, second) => first.deadlineDate.localeCompare(second.deadlineDate))
    .slice(0, 3);
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { profile, comparisonOpportunityIds, toggleComparisonOpportunity } = useProfile();
  const [scholarships, setScholarships] = useState([]);
  const [loadError, setLoadError] = useState('');
  const eligibility = useScholarshipEligibility();
  const recommendations = useScholarshipRecommendations();
  const firstName = profile.firstName || (profile.name || '').trim().split(/\s+/)[0] || 'there';
  const profileCompletion = Math.max(0, Math.min(100, Number(profile.profileCompletionPercentage) || 0));

  useEffect(() => {
    let current = true;
    apiService.getMatchedScholarships()
      .then((items) => { if (current) setScholarships(items); })
      .catch((error) => {
        console.error('Unable to load dashboard scholarships.', error);
        if (current) setLoadError('Scholarships could not be loaded. Please try again later.');
      });
    return () => { current = false; };
  }, []);

  const ranked = useMemo(() => (recommendations.data?.recommendations || [])
    .map((item) => {
      const scholarship = scholarships.find((record) => record._numericId === item.scholarship_id);
      return scholarship ? { ...scholarship, recommendation: item } : null;
    })
    .filter(Boolean)
    .slice(0, 3), [recommendations.data, scholarships]);
  const best = ranked[0] || null;
  const potentialCount = eligibility.state === 'ok'
    ? scholarships.filter((item) => eligibility.getEvaluation(item.id).status !== 'not-satisfied').length
    : null;
  const deadlines = useMemo(() => getUpcomingDeadlines(scholarships), [scholarships]);

  const handleCompare = (id) => {
    if (!comparisonOpportunityIds.includes(id) && comparisonOpportunityIds.length < 2) toggleComparisonOpportunity(id);
    navigate('/compare');
  };

  return (
    <div className="dashboard-page">
      <div className="dashboard-columns">
        <main className="dashboard-main">
          <section className="dashboard-hero" aria-labelledby="dashboard-welcome">
            <div className="dashboard-hero-copy">
              <h1 id="dashboard-welcome">Welcome back, {firstName} <span aria-hidden="true">👋</span></h1>
              <p>{profile.profileComplete ? 'Your scholarship guidance uses your saved profile.' : 'Complete your profile for more useful scholarship matches.'}</p>
              <button type="button" className="dashboard-hero-link" onClick={() => navigate(profile.profileComplete ? '/recommendations' : '/profile')}>
                {profile.profileComplete ? 'View scholarship matches' : 'Complete profile'} <ArrowRight size={15} aria-hidden="true" />
              </button>
            </div>
            <div className="dashboard-hero-scene" aria-hidden="true">
              <img className="dashboard-hero-image" src="/images/study-abroad-banner.jpg" alt="" fetchPriority="high" />
            </div>
          </section>

          <section className="dashboard-stat-grid" aria-label="Scholarship highlights">
            <button type="button" className="dashboard-stat-card tone-blue" onClick={() => navigate('/recommendations')}>
              <span className="dashboard-stat-icon stat-blue"><Star size={19} /></span>
              <span className="dashboard-stat-label">Top scholarship match</span>
              <strong>{best ? `${best.recommendation.score ?? '—'}/100` : '—'}</strong>
              <span className="dashboard-stat-detail">{loadError || recommendations.state === 'error' ? 'Recommendations unavailable' : best?.name || 'No recommended scholarships yet'}</span>
            </button>
            <button type="button" className="dashboard-stat-card tone-green" onClick={() => navigate('/scholarships')}>
              <span className="dashboard-stat-icon stat-green"><Star size={19} /></span>
              <span className="dashboard-stat-label">Potential scholarships</span>
              <strong>{potentialCount == null ? '—' : potentialCount}</strong>
              <span className="dashboard-stat-detail">{eligibility.state === 'ok' ? 'Not ruled out by current checks' : 'Eligibility not assessed'}</span>
            </button>
            <button type="button" className="dashboard-stat-card tone-amber" onClick={() => navigate('/recommendations')}>
              <span className="dashboard-stat-icon stat-orange"><Clock3 size={19} /></span>
              <span className="dashboard-stat-label">Next verified deadline</span>
              <strong>{deadlines[0]?.deadlineDate || '—'}</strong>
              <span className="dashboard-stat-detail">{deadlines[0]?.name || 'No verified upcoming date listed'}</span>
            </button>
            <button type="button" className="dashboard-stat-card tone-cyan" onClick={() => navigate('/financial')}>
              <span className="dashboard-stat-icon stat-cyan"><Wallet size={19} /></span>
              <span className="dashboard-stat-label">Financial feasibility</span>
              <strong>Review</strong>
              <span className="dashboard-stat-detail">Use scholarship funding and available cost records</span>
            </button>
          </section>

          <section className="dashboard-matches" aria-labelledby="dashboard-matches-title">
            <div className="dashboard-section-heading">
              <div>
                <h2 id="dashboard-matches-title">Scholarship matches for you</h2>
                <p>Ranked from your profile and scholarship requirements</p>
              </div>
              <button type="button" className="dashboard-text-link" onClick={() => navigate('/recommendations')}>View all <ArrowRight size={14} /></button>
            </div>
            {loadError || recommendations.state === 'error' ? (
              <div className="dashboard-matches-message" role="alert"><p>{loadError || 'Scholarship recommendations could not be loaded.'}</p><RetryButton /></div>
            ) : ranked.length ? (
              <div className="dashboard-match-list">
                {ranked.map((scholarship) => {
                  const selected = comparisonOpportunityIds.includes(scholarship.id);
                  return (
                    <article className="dashboard-match-card" key={scholarship.id}>
                      <ScholarshipLogo
                        src={getScholarshipLogo(scholarship)}
                        size={82}
                        className="dashboard-scholarship-logo"
                        fallback={<Star size={24} />}
                      />
                      <div className="dashboard-match-content">
                        <div className="dashboard-match-title-row"><h3>{getOpportunityTitle(scholarship)}</h3></div>
                        <p className="dashboard-match-program">{scholarship.provider || 'Provider not listed'}</p>
                        <div className="dashboard-match-meta">
                          <span>{scholarship.country || 'Country not listed'}</span>
                          <span>{scholarship.recommendation.funding?.label || 'Funding not confirmed'}</span>
                          {scholarship.deadlineDate && <span><CalendarDays size={13} />{scholarship.deadlineDate}</span>}
                        </div>
                        <div className="dashboard-match-actions">
                          <button type="button" className="btn btn-primary dashboard-button-primary" onClick={() => navigate(`/scholarships/${scholarship.id}`)}>View details</button>
                          <button type="button" className={`dashboard-button-secondary${selected ? ' is-selected' : ''}`} onClick={() => handleCompare(scholarship.id)} aria-label={`${selected ? 'Open comparison for' : 'Compare'} ${scholarship.name}`}>
                            {selected ? <Check size={14} /> : <Scale size={14} />}{selected ? 'Selected' : 'Compare'}
                          </button>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="dashboard-matches-message">No scholarship recommendations are currently available.</div>
            )}
            <p className="dashboard-data-note"><ShieldCheck size={13} /> Check source status and confirm current terms with the official scholarship provider.</p>
          </section>
        </main>

        <aside className="dashboard-rail" aria-label="Profile completeness and verified deadlines">
          <section className="dashboard-profile-card" aria-labelledby="dashboard-profile-heading">
            <h2 id="dashboard-profile-heading">Profile completeness</h2>
            <div className="dashboard-profile-ring" role="progressbar" aria-label="Profile completeness" aria-valuemin={0} aria-valuemax={100} aria-valuenow={profileCompletion} style={{ '--profile-completion': `${profileCompletion}%` }}>
              <span>{profileCompletion}%</span>
            </div>
            <p>{profile.profileComplete ? 'Keep your information current so scholarship checks stay relevant.' : 'Complete your profile to get more relevant scholarship matches.'}</p>
            <button type="button" onClick={() => navigate('/profile')}>{profile.profileComplete ? 'Review profile' : 'Complete profile'} <ArrowRight size={14} /></button>
          </section>
          <section className="dashboard-upcoming-deadlines" aria-labelledby="dashboard-deadlines-title">
            <div className="dashboard-rail-heading">
              <h2 id="dashboard-deadlines-title"><span className="dashboard-rail-icon is-amber" aria-hidden="true"><CalendarDays size={15} /></span>Verified deadlines</h2>
            </div>
            {deadlines.length ? (
              <ul>{deadlines.map((item) => <li key={item.id}><span>{item.name}</span><strong>{item.deadlineDate}</strong><small>Verified source record</small></li>)}</ul>
            ) : <p>No verified upcoming deadlines are listed.</p>}
          </section>
        </aside>
      </div>
    </div>
  );
}
