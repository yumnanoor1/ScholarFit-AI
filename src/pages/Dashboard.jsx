import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight, CalendarDays, Check, Clock3, Coins, GraduationCap, ListChecks, MapPin,
  Scale, ShieldCheck, Star, Wallet,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { getOpportunityProgress, getOpportunityTitle } from '../services/opportunityJourney';
import { apiService } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { getSelectedApplicationStrategy } from '../services/applicationWorkflow';
import { getProgramImage, getUniversityLogo } from '../services/programFit';
import { useProgramEligibility, useScholarshipEligibility, useScholarshipRecommendations } from '../hooks/useProgramEligibility';
import { ELIGIBILITY_SORT_ORDER } from '../services/eligibilityBadges';
import RetryButton from '../components/common/RetryButton';
import './Dashboard.css';

const EMPTY_TASK_STATUSES = {};
const NOT_LOADED = 'Couldn’t load right now';

// University logo for a match card; falls back to a campus photo, then the cap icon
function MatchThumbnail({ id, university }) {
  const logo = getUniversityLogo(university);
  const sources = [logo, getProgramImage(id)].filter(Boolean);
  const [failedCount, setFailedCount] = useState(0);
  const src = sources[failedCount];
  if (!src) {
    return <span className="dashboard-campus-placeholder" aria-hidden="true"><GraduationCap size={30} /></span>;
  }
  const isLogo = src === logo;
  return (
    <span className={isLogo ? 'dashboard-university-logo' : 'dashboard-campus-photo-wrap'}>
      <img
        className={isLogo ? '' : 'dashboard-campus-photo'}
        src={src}
        alt={isLogo ? `${university} logo` : ''}
        loading="lazy"
        decoding="async"
        onError={() => setFailedCount((count) => count + 1)}
      />
    </span>
  );
}
function getUpcomingDeadlines(opportunities) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return opportunities
    .filter((opportunity) => opportunity.deadline)
    .map((opportunity) => ({ opportunity, date: new Date(opportunity.deadline) }))
    .filter(({ date }) => !Number.isNaN(date.getTime()) && date >= today)
    .sort((first, second) => first.date - second.date)
    .slice(0, 3);
}

export default function Dashboard() {
  const navigate = useNavigate();
  const {
    profile,
    activeOpportunity,
    opportunityTaskStatuses,
    comparisonOpportunityIds,
    toggleComparisonOpportunity,
  } = useProfile();
  const { user } = useAuth();
  const userId = user?.id;
  const activeOpportunityId = activeOpportunity?.id;
  const activeOpportunityKind = activeOpportunity?.kind;
  const [pathwayResult, setPathwayResult] = useState(null);
  const [universities, setUniversities] = useState([]);
  const [scholarships, setScholarships] = useState([]);
  const [matchesError, setMatchesError] = useState('');
  const scholarshipEligibility = useScholarshipEligibility();
  const programEligibility = useProgramEligibility();
  const recommendations = useScholarshipRecommendations();
  const firstName = profile.firstName || (profile.name || '').trim().split(/\s+/)[0] || 'there';
  const profileCompletion = Math.max(0, Math.min(100, Number(profile.profileCompletionPercentage) || 0));
  const statuses = activeOpportunity
    ? opportunityTaskStatuses[activeOpportunity.id] || EMPTY_TASK_STATUSES
    : EMPTY_TASK_STATUSES;
  const pathway = pathwayResult && pathwayResult.opportunityId === activeOpportunityId
    ? pathwayResult.value
    : null;

  useEffect(() => {
    let current = true;
    Promise.all([apiService.getMatchedUniversities(), apiService.getMatchedScholarships()])
      .then(([programs, funding]) => {
        if (!current) return;
        setUniversities(programs);
        setScholarships(funding);
      })
      .catch((error) => {
        console.error('Unable to load dashboard matches.', error);
        if (current) setMatchesError('Matches could not be loaded. Please try again later.');
      });
    return () => { current = false; };
  }, []);

  useEffect(() => {
    if (!activeOpportunityId || activeOpportunityKind !== 'program') return undefined;
    let current = true;
    apiService.getApplicationPathway(
      activeOpportunityId,
      getSelectedApplicationStrategy(userId, activeOpportunityId),
    ).then((result) => {
      if (current) setPathwayResult({ opportunityId: activeOpportunityId, value: result });
    }).catch((error) => {
      console.error('Unable to load selected opportunity pathway for dashboard.', error);
    });
    return () => { current = false; };
  }, [userId, activeOpportunityId, activeOpportunityKind]);

  const progress = useMemo(() => activeOpportunity
    ? getOpportunityProgress(activeOpportunity, statuses, pathway, profile)
    : { tasks: [], percentage: 0, completed: 0, nextTask: null },
  [activeOpportunity, statuses, pathway, profile]);

  const preferredCountries = useMemo(
    () => (Array.isArray(profile.preferredCountries) ? profile.preferredCountries : String(profile.preferredCountries || '').split(','))
      .map((country) => country.trim().toLowerCase())
      .filter(Boolean),
    [profile.preferredCountries],
  );
  const { getEvaluation: getProgramEvaluation } = programEligibility;
  // The same eligibility order as the Programs page, with the student's preferred countries first
  const topMatches = useMemo(() => {
    const rank = (program) => {
      const country = String(program.country || '').toLowerCase();
      return [
        ELIGIBILITY_SORT_ORDER[getProgramEvaluation(program.id).status] ?? 4,
        preferredCountries.some((wanted) => country.includes(wanted)) ? 0 : 1,
      ];
    };
    return [...universities]
      .sort((first, second) => {
        const [firstStatus, firstCountry] = rank(first);
        const [secondStatus, secondCountry] = rank(second);
        return firstStatus - secondStatus || firstCountry - secondCountry;
      })
      .slice(0, 3);
  }, [universities, getProgramEvaluation, preferredCountries]);
  const bestRecommendation = profile.profileComplete ? recommendations.data?.recommendations?.[0] || null : null;
  // Stat tiles from the backend programs and scholarships, limited to the student's preferred countries
  const opportunityStats = useMemo(() => {
    const inPreferred = (country) => preferredCountries.length === 0
      || preferredCountries.some((wanted) => String(country || '').toLowerCase().includes(wanted));
    const tuitions = universities
      .filter((program) => inPreferred(program.country))
      .map((program) => Number(program.tuitionUsd))
      .filter((amount) => Number.isFinite(amount))
      .sort((a, b) => a - b);
    const middle = Math.floor(tuitions.length / 2);
    const median = tuitions.length === 0
      ? null
      : tuitions.length % 2 ? tuitions[middle] : (tuitions[middle - 1] + tuitions[middle]) / 2;
    return {
      fundedCount: profile.fundingPreference === 'Self-Funded'
        ? 0
        : scholarships.filter((scholarship) => inPreferred(scholarship.country)).length,
      medianTuition: median === null ? 'No matches' : `$${Math.round(median).toLocaleString()} / year`,
    };
  }, [universities, scholarships, preferredCountries, profile.fundingPreference]);

  // With backend eligibility: scholarships the student isn't ruled out of, and how many are confirmed
  const scholarshipCounts = useMemo(() => {
    if (scholarshipEligibility.state !== 'ok') return null;
    const statuses = scholarships.map((item) => scholarshipEligibility.getEvaluation(item.id).status);
    return {
      potential: statuses.filter((status) => status !== 'not-satisfied').length,
      eligible: statuses.filter((status) => status === 'satisfied').length,
    };
  }, [scholarships, scholarshipEligibility]);
  const potentialScholarships = scholarshipCounts ? scholarshipCounts.potential : opportunityStats.fundedCount;

  const upcomingDeadlines = useMemo(
    () => getUpcomingDeadlines([...universities, ...scholarships]),
    [universities, scholarships],
  );
  const nextTasks = progress.tasks
    .filter((task) => (statuses[task.id] || task.status) !== 'done')
    .sort((first, second) => Number((statuses[second.id] || second.status) === 'in-progress')
      - Number((statuses[first.id] || first.status) === 'in-progress'))
    .slice(0, 3);

  const handleCompare = (universityId) => {
    if (!comparisonOpportunityIds.includes(universityId) && comparisonOpportunityIds.length < 2) {
      toggleComparisonOpportunity(universityId);
    }
    navigate('/compare');
  };

  return (
    <div className="dashboard-page">
      <div className="dashboard-columns">
        <main className="dashboard-main">
          <section className="dashboard-hero" aria-labelledby="dashboard-welcome">
            <div className="dashboard-hero-copy">
              <h1 id="dashboard-welcome">Welcome back, {firstName} <span aria-hidden="true">👋</span></h1>
              <p>{profile.profileComplete ? 'Your profile is complete. See what fits you best.' : 'Complete your profile for better matches.'}</p>
              <button type="button" className="dashboard-hero-link" onClick={() => navigate(profile.profileComplete ? '/recommendations' : '/profile')}>
                {profile.profileComplete ? 'View my matches' : 'Complete profile'} <ArrowRight size={15} aria-hidden="true" />
              </button>
            </div>
            <div className="dashboard-hero-scene" aria-hidden="true">
              <img className="dashboard-hero-image" src="/images/study-abroad-banner.jpg" alt="" fetchPriority="high" />
            </div>
          </section>

          <section className="dashboard-stat-grid" aria-label="Study opportunity highlights">
            <button type="button" className="dashboard-stat-card tone-blue" aria-label={`Best match ${bestRecommendation ? `${bestRecommendation.score} out of 100` : 'unavailable'}. View matches`} onClick={() => navigate('/recommendations')}>
              <span className="dashboard-stat-icon stat-blue"><GraduationCap size={20} /></span>
              <span className="dashboard-stat-label">Best match</span>
              {bestRecommendation ? (
                <>
                  <strong>{bestRecommendation.score}/100</strong>
                  <span className="dashboard-stat-detail">{bestRecommendation.scholarship_name}</span>
                </>
              ) : (
                <><strong>—</strong><span className="dashboard-stat-detail">{matchesError || recommendations.state === 'error' ? NOT_LOADED : profile.profileComplete ? 'No matches yet' : 'Complete your profile to see matches'}</span></>
              )}
            </button>
            <button type="button" className="dashboard-stat-card tone-green" aria-label={`${matchesError ? 'Unavailable' : potentialScholarships} potential scholarships. Explore scholarships`} onClick={() => navigate('/scholarships')}>
              <span className="dashboard-stat-icon stat-green"><Star size={19} /></span>
              <span className="dashboard-stat-label">Potential scholarships</span>
              <strong>{matchesError ? '—' : potentialScholarships}</strong>
              <span className="dashboard-stat-detail">
                {matchesError ? NOT_LOADED : scholarshipCounts ? `${scholarshipCounts.eligible} confirmed eligible` : 'Explore funding options'}
              </span>
            </button>
            <button type="button" className="dashboard-stat-card tone-amber" aria-label="Upcoming listed deadline. View timeline" onClick={() => navigate('/timeline')}>
              <span className="dashboard-stat-icon stat-orange"><Clock3 size={19} /></span>
              <span className="dashboard-stat-label">Upcoming listed deadline</span>
              <strong>{upcomingDeadlines[0] ? upcomingDeadlines[0].opportunity.deadline : '—'}</strong>
              <span className="dashboard-stat-detail">
                {matchesError ? NOT_LOADED : upcomingDeadlines[0] ? 'View timeline and dates' : 'No upcoming dates listed'}
              </span>
            </button>
            <button type="button" className="dashboard-stat-card tone-cyan" aria-label="Typical listed tuition. Review financial feasibility" onClick={() => navigate('/financial')}>
              <span className="dashboard-stat-icon stat-cyan"><Coins size={19} /></span>
              <span className="dashboard-stat-label">Typical listed tuition</span>
              <strong>{matchesError ? '—' : opportunityStats.medianTuition}</strong>
              <span className="dashboard-stat-detail">{matchesError ? NOT_LOADED : 'Review financial feasibility'}</span>
            </button>
          </section>

          <section className="dashboard-matches" aria-labelledby="dashboard-matches-title">
            <div className="dashboard-section-heading">
              <div>
                <h2 id="dashboard-matches-title">Top matches for you</h2>
                <p>Programs ranked by your eligibility and preferred countries</p>
              </div>
              <button type="button" className="dashboard-text-link" onClick={() => navigate('/recommendations')}>
                View all <ArrowRight size={14} />
              </button>
            </div>

            {matchesError ? (
              <div className="dashboard-matches-message" role="alert"><p>{matchesError}</p><RetryButton /></div>
            ) : topMatches.length ? (
              <div className="dashboard-match-list">
                {topMatches.map((university) => {
                  const selectedForComparison = comparisonOpportunityIds.includes(university.id);
                  return (
                    <article className="dashboard-match-card" key={university.id}>
                      <MatchThumbnail id={university.id} university={university.university} />
                      <div className="dashboard-match-content">
                        <div className="dashboard-match-title-row">
                          <h3>{university.university}</h3>
                        </div>
                        <p className="dashboard-match-program">{university.program}</p>
                        <div className="dashboard-match-meta">
                          <span><MapPin size={13} />{university.country}</span>
                          <span><Wallet size={13} />{university.tuition || 'Tuition not listed'}</span>
                          {university.deadline && <span><CalendarDays size={13} />{university.deadline}</span>}
                        </div>
                        <div className="dashboard-match-actions">
                          <button type="button" className="btn btn-primary dashboard-button-primary" onClick={() => navigate(`/universities/${university.id}`)}>
                            View details
                          </button>
                          <button
                            type="button"
                            className={`dashboard-button-secondary${selectedForComparison ? ' is-selected' : ''}`}
                            onClick={() => handleCompare(university.id)}
                            aria-label={`${selectedForComparison ? 'Open comparison for' : 'Compare'} ${university.university}`}
                          >
                            {selectedForComparison ? <Check size={14} /> : <Scale size={14} />}
                            {selectedForComparison ? 'Selected' : 'Compare'}
                          </button>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="dashboard-matches-message">
                No program matches are available yet. <button type="button" onClick={() => navigate('/universities')}>Browse universities</button>
              </div>
            )}
            <p className="dashboard-data-note"><ShieldCheck size={13} /> Program details come from the FitScholars database; verify requirements with each provider.</p>
          </section>
        </main>

        <aside className="dashboard-rail" aria-label="Profile completeness, next tasks and deadlines">
          <section className="dashboard-profile-card" aria-labelledby="dashboard-profile-heading">
            <h2 id="dashboard-profile-heading">Profile completeness</h2>
            <div
              className="dashboard-profile-ring"
              role="progressbar"
              aria-label="Profile completeness"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={profileCompletion}
              style={{ '--profile-completion': `${profileCompletion}%` }}
            >
              <span>{profileCompletion}%</span>
            </div>
            <p>{profile.profileComplete ? 'Keep it up to date so your matches stay accurate.' : 'Complete your profile to get more relevant matches.'}</p>
            <button type="button" onClick={() => navigate('/profile')}>{profile.profileComplete ? 'Review profile' : 'Complete profile'} <ArrowRight size={14} /></button>
          </section>

          <section className="dashboard-next-tasks" aria-labelledby="dashboard-next-tasks-title">
            <div className="dashboard-rail-heading">
              <h2 id="dashboard-next-tasks-title"><span className="dashboard-rail-icon is-blue" aria-hidden="true"><ListChecks size={15} /></span>Next 3 tasks</h2>
              <button type="button" onClick={() => navigate('/timeline')}>Timeline <ArrowRight size={13} /></button>
            </div>
            {activeOpportunity ? (
              nextTasks.length ? (
                <ol>
                  {nextTasks.map((task) => (
                    <li key={task.id}>
                      <button type="button" onClick={() => navigate('/timeline')}>
                        <span>{task.title}</span>
                        <ArrowRight size={14} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ol>
              ) : <p>All listed tasks are complete.</p>
            ) : (
              <div className="dashboard-rail-empty">
                <p>Select an opportunity to see its preparation tasks.</p>
                <button type="button" onClick={() => navigate('/recommendations')}>Explore matches</button>
              </div>
            )}
          </section>

          <section className="dashboard-upcoming-deadlines" aria-labelledby="dashboard-deadlines-title">
            <div className="dashboard-rail-heading">
              <h2 id="dashboard-deadlines-title"><span className="dashboard-rail-icon is-amber" aria-hidden="true"><CalendarDays size={15} /></span>Upcoming deadlines</h2>
              <button type="button" onClick={() => navigate('/timeline')}>View all <ArrowRight size={13} /></button>
            </div>
            {upcomingDeadlines.length ? (
              <ul>
                {upcomingDeadlines.map(({ opportunity }) => (
                  <li key={opportunity.id}>
                    <span>{getOpportunityTitle(opportunity)}</span>
                    <strong>{opportunity.deadline}</strong>
                    <small>{opportunity.deadlineStatus === 'official-verified' ? 'Official date' : 'Listed date · verify with provider'}</small>
                  </li>
                ))}
              </ul>
            ) : <p>No upcoming dates are listed.</p>}
          </section>
        </aside>
      </div>
    </div>
  );
}
