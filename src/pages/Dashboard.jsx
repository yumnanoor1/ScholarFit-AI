import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight, CalendarDays, Check, Clock3, Coins, GraduationCap, MapPin,
  Scale, ShieldCheck, Star, Wallet,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { getOpportunityProgress, getOpportunityTitle } from '../services/opportunityJourney';
import { apiService } from '../services/api';
import { getSelectedApplicationStrategy } from '../services/applicationWorkflow';
import './Dashboard.css';

const EMPTY_TASK_STATUSES = {};
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
    matchStatistics,
    activeOpportunity,
    opportunityTaskStatuses,
    comparisonOpportunityIds,
    toggleComparisonOpportunity,
  } = useProfile();
  const activeOpportunityId = activeOpportunity?.id;
  const activeOpportunityKind = activeOpportunity?.kind;
  const [pathwayResult, setPathwayResult] = useState(null);
  const [universities, setUniversities] = useState([]);
  const [scholarships, setScholarships] = useState([]);
  const [matchesError, setMatchesError] = useState('');
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
      getSelectedApplicationStrategy(activeOpportunityId),
    ).then((result) => {
      if (current) setPathwayResult({ opportunityId: activeOpportunityId, value: result });
    }).catch((error) => {
      console.error('Unable to load selected opportunity pathway for dashboard.', error);
    });
    return () => { current = false; };
  }, [activeOpportunityId, activeOpportunityKind]);

  const progress = useMemo(() => activeOpportunity
    ? getOpportunityProgress(activeOpportunity, statuses, pathway, profile)
    : { tasks: [], percentage: 0, completed: 0, nextTask: null },
  [activeOpportunity, statuses, pathway, profile]);

  useEffect(() => {
    if (!activeOpportunityId || activeOpportunityKind !== 'program') return undefined;
    let current = true;
    apiService.getApplicationPathway(
      activeOpportunityId,
      getSelectedApplicationStrategy(activeOpportunityId),
    ).then((result) => {
      if (current) setPathwayResult({ opportunityId: activeOpportunityId, value: result });
    }).catch((error) => {
      console.error('Unable to load selected opportunity pathway for dashboard.', error);
    });
    return () => { current = false; };
  }, [activeOpportunityId, activeOpportunityKind]);

  const sortedUniversities = useMemo(
    () => [...universities].sort((first, second) => (Number(second.matchScore) || 0) - (Number(first.matchScore) || 0)),
    [universities],
  );
  const topMatches = sortedUniversities.slice(0, 3);
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
              <p>Complete your profile for better matches.</p>
              <button type="button" className="dashboard-hero-link" onClick={() => navigate('/profile')}>
                Complete profile <ArrowRight size={15} aria-hidden="true" />
              </button>
            </div>
            <div className="dashboard-hero-scene" aria-hidden="true">
              <img className="dashboard-hero-image" src="/images/study-abroad-banner.jpg" alt="" fetchPriority="high" />
            </div>
          </section>

          <section className="dashboard-stat-grid" aria-label="Study opportunity highlights">
            <button type="button" className="dashboard-stat-card" aria-label={`Best match ${sortedUniversities[0]?.matchScore ?? 'unavailable'} percent. View matches`} onClick={() => navigate('/recommendations')}>
              <span className="dashboard-stat-icon stat-blue"><GraduationCap size={20} /></span>
              <span className="dashboard-stat-label">Best match</span>
              {sortedUniversities[0] ? (
                <>
                  <strong>{sortedUniversities[0].matchScore ?? '—'}%</strong>
                  <span className="dashboard-stat-detail">{sortedUniversities[0].university}</span>
                </>
              ) : (
                <><strong>—</strong><span className="dashboard-stat-detail">No program matches yet</span></>
              )}
            </button>
            <button type="button" className="dashboard-stat-card" aria-label={`${matchStatistics.fundedCount} potential scholarships. Explore scholarships`} onClick={() => navigate('/scholarships')}>
              <span className="dashboard-stat-icon stat-purple"><Star size={19} /></span>
              <span className="dashboard-stat-label">Potential scholarships</span>
              <strong>{matchStatistics.fundedCount}</strong>
              <span className="dashboard-stat-detail">Explore funding options</span>
            </button>
            <button type="button" className="dashboard-stat-card" aria-label="Upcoming listed deadline. View timeline" onClick={() => navigate('/timeline')}>
              <span className="dashboard-stat-icon stat-orange"><Clock3 size={19} /></span>
              <span className="dashboard-stat-label">Upcoming listed deadline</span>
              <strong>{upcomingDeadlines[0] ? upcomingDeadlines[0].opportunity.deadline : '—'}</strong>
              <span className="dashboard-stat-detail">
                {upcomingDeadlines[0] ? 'View timeline and dates' : 'No upcoming dates listed'}
              </span>
            </button>
            <button type="button" className="dashboard-stat-card" aria-label="Typical listed tuition. Review financial feasibility" onClick={() => navigate('/financial')}>
              <span className="dashboard-stat-icon stat-cyan"><Coins size={19} /></span>
              <span className="dashboard-stat-label">Typical listed tuition</span>
              <strong>{matchStatistics.medianTuition}</strong>
              <span className="dashboard-stat-detail">Review financial feasibility</span>
            </button>
          </section>

          <section className="dashboard-matches" aria-labelledby="dashboard-matches-title">
            <div className="dashboard-section-heading">
              <div>
                <h2 id="dashboard-matches-title">Top matches for you</h2>
                <p>Programs selected using your profile</p>
              </div>
              <button type="button" className="dashboard-text-link" onClick={() => navigate('/recommendations')}>
                View all <ArrowRight size={14} />
              </button>
            </div>

            {matchesError ? (
              <p className="dashboard-matches-message" role="status">{matchesError}</p>
            ) : topMatches.length ? (
              <div className="dashboard-match-list">
                {topMatches.map((university) => {
                  const selectedForComparison = comparisonOpportunityIds.includes(university.id);
                  return (
                    <article className="dashboard-match-card" key={university.id}>
                      <span className="dashboard-campus-placeholder" aria-hidden="true"><GraduationCap size={30} /></span>
                      <div className="dashboard-match-content">
                        <div className="dashboard-match-title-row">
                          <h3>{university.university}</h3>
                          <span className="dashboard-match-score">{university.matchScore ?? '—'}% match</span>
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
                      <span className="dashboard-match-sample">Sample</span>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="dashboard-matches-message">
                No program matches are available yet. <button type="button" onClick={() => navigate('/universities')}>Browse universities</button>
              </div>
            )}
            <p className="dashboard-data-note"><ShieldCheck size={13} /> Match scores and program details are sample estimates; verify requirements with each provider.</p>
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
            <p>Complete your profile to get more relevant matches.</p>
            <button type="button" onClick={() => navigate('/profile')}>Complete profile <ArrowRight size={14} /></button>
          </section>

          <section className="dashboard-next-tasks" aria-labelledby="dashboard-next-tasks-title">
            <div className="dashboard-rail-heading">
              <h2 id="dashboard-next-tasks-title">Next 3 tasks</h2>
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
              <h2 id="dashboard-deadlines-title">Upcoming deadlines</h2>
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
