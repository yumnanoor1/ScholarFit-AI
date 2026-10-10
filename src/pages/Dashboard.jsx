import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useProfile } from '../context/ProfileContext';
import { GlowCard } from '../components/ui/spotlight-card';
import { getOpportunityProgress, getOpportunityTitle } from '../services/opportunityJourney';
import { apiService } from '../services/api';
import { getSelectedApplicationStrategy } from '../services/applicationWorkflow';
import './Dashboard.css';

const EMPTY_TASK_STATUSES = {};

export default function Dashboard() {
  const navigate = useNavigate();
  const {
    profile,
    matchStatistics,
    activeOpportunity,
    opportunityTaskStatuses,
  } = useProfile();
  const activeOpportunityId = activeOpportunity?.id;
  const activeOpportunityKind = activeOpportunity?.kind;
  const [pathwayResult, setPathwayResult] = useState(null);
  const firstName = profile.firstName || (profile.name || '').split(' ')[0] || 'there';
  const profileCompletion = Number(profile.profileCompletionPercentage) || 0;
  const statuses = activeOpportunity ? opportunityTaskStatuses[activeOpportunity.id] || EMPTY_TASK_STATUSES : EMPTY_TASK_STATUSES;

  useEffect(() => {
    if (!activeOpportunityId || activeOpportunityKind !== 'program') return undefined;
    let current = true;
    apiService.getApplicationPathway(
      activeOpportunityId,
      getSelectedApplicationStrategy(activeOpportunityId),
    ).then((result) => { if (current) setPathwayResult({ opportunityId: activeOpportunityId, value: result }); })
      .catch((error) => console.error('Unable to load selected opportunity pathway for dashboard.', error));
    return () => { current = false; };
  }, [activeOpportunityId, activeOpportunityKind]);

  const pathway = pathwayResult && pathwayResult.opportunityId === activeOpportunity?.id
    ? pathwayResult.value
    : null;

  const progress = useMemo(() => activeOpportunity
    ? getOpportunityProgress(activeOpportunity, statuses, pathway, profile)
    : { tasks: [], percentage: 0, completed: 0, nextTask: null },
  [activeOpportunity, statuses, pathway, profile]);

  return (
    <div className="dashboard-page mx-auto min-h-screen w-full max-w-[1440px]">
      <div className="dashboard-page-header flex flex-col justify-between gap-5 md:flex-row md:items-center">
        <div className="dashboard-greeting">
          <h1 className="text-2xl font-semibold tracking-normal text-slate-900 dark:text-white sm:text-3xl">Good morning, {firstName}</h1>
          <p className="text-sm text-slate-600 dark:text-slate-300">Explore Master's programs and scholarships, check your fit, and plan your preparation.</p>
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-slate-600 dark:text-slate-300">Profile completeness</span>
            <div className="h-2 w-40 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
              <div role="progressbar" aria-label="Profile completeness" aria-valuemin={0} aria-valuemax={100} aria-valuenow={profileCompletion} className="h-full rounded-full bg-blue-600 transition-[width]" style={{ width: `${profileCompletion}%` }} />
            </div>
            <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">{profileCompletion}%</span>
          </div>
        </div>
        <button onClick={() => navigate('/recommendations')} className="dashboard-explore-action rounded-xl bg-sky-700 px-4 py-3 text-sm font-semibold text-white shadow-xs transition hover:bg-sky-800">
          Explore matched opportunities
        </button>
      </div>

      {profileCompletion === 0 && (
        <GlowCard as="section" customSize className="dashboard-profile-prompt flex flex-col gap-4 rounded-2xl border border-sky-200 bg-sky-50 shadow-sm dark:border-sky-900 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">Complete your profile to improve matches</h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Add academic, test, and study preference details to improve your profile-based recommendations.</p>
          </div>
          <button onClick={() => navigate('/profile-setup')} className="dashboard-profile-action rounded-lg bg-sky-700 px-4 py-2.5 text-sm font-semibold text-white">Complete profile</button>
        </GlowCard>
      )}

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:-mx-4 xl:grid-cols-3" aria-label="Illustrative study opportunity insights">
        <GlowCard as="article" customSize className="flex min-h-32 flex-col items-center justify-center rounded-xl border border-slate-200 bg-white p-5 text-center shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <p className="text-sm font-medium text-slate-600 dark:text-slate-300">Potential program and scholarship matches</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{matchStatistics.eligibleCount}</p>
          <p className="mt-1 w-full whitespace-normal text-xs leading-5 text-slate-500 dark:text-slate-400">Sample profile matches, not verified eligibility</p>
        </GlowCard>
        <GlowCard as="article" customSize className="flex min-h-32 flex-col items-center justify-center rounded-xl border border-slate-200 bg-white p-5 text-center shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <p className="text-sm font-medium text-slate-600 dark:text-slate-300">Potential scholarship listings</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{matchStatistics.fundedCount}</p>
          <p className="mt-1 w-full whitespace-normal text-xs leading-5 text-slate-500 dark:text-slate-400">Sample listings, not awarded funding</p>
        </GlowCard>
        <GlowCard as="article" customSize className="flex min-h-32 flex-col items-center justify-center rounded-xl border border-slate-200 bg-white p-5 text-center shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <p className="text-sm font-medium text-slate-600 dark:text-slate-300">Median listed program tuition</p>
          <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">{matchStatistics.medianTuition}</p>
          <p className="mt-1 w-full whitespace-normal text-xs leading-5 text-slate-500 dark:text-slate-400">Sample estimate; confirm with the university</p>
        </GlowCard>
      </section>

      <section className="dashboard-opportunity-section" aria-labelledby="active-journey-title">
        <GlowCard as="article" customSize className="dashboard-opportunity-card">
          {activeOpportunity ? (
            <>
              <div className="dashboard-opportunity-header">
                <div className="dashboard-opportunity-identity">
                  <p className="dashboard-opportunity-eyebrow">Selected opportunity</p>
                  <h2 id="active-journey-title">{getOpportunityTitle(activeOpportunity)}</h2>
                  <p className="dashboard-opportunity-institution">
                    {activeOpportunity.university || activeOpportunity.provider || activeOpportunity.country}
                  </p>
                </div>
                <button
                  className="dashboard-opportunity-action"
                  onClick={() => navigate('/timeline')}
                >
                  View preparation plan
                  <span aria-hidden="true">→</span>
                </button>
              </div>

              <div className="dashboard-opportunity-details">
                <div className="dashboard-opportunity-detail dashboard-opportunity-progress">
                  <div className="dashboard-opportunity-detail-heading">
                    <span>Preparation progress</span>
                    <strong>{progress.percentage}%</strong>
                  </div>
                  <div
                    className="dashboard-opportunity-progress-track"
                    role="progressbar"
                    aria-label="Preparation progress"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={progress.percentage}
                  >
                    <span style={{ width: `${progress.percentage}%` }} />
                  </div>
                  <p>{progress.completed} of {progress.tasks.length} tasks complete</p>
                </div>

                <div className="dashboard-opportunity-detail">
                  <span className="dashboard-opportunity-detail-label">Next planning step</span>
                  <p className="dashboard-opportunity-detail-value">
                    {progress.nextTask?.title || 'No outstanding tasks available'}
                  </p>
                </div>

                <div className="dashboard-opportunity-detail">
                  <span className="dashboard-opportunity-detail-label">Nearest listed deadline</span>
                  <p className="dashboard-opportunity-detail-value">
                    {activeOpportunity.deadline || 'Not available'}
                  </p>
                  {activeOpportunity.deadline && activeOpportunity.deadlineStatus !== 'official-verified' && (
                    <span className="dashboard-opportunity-deadline-note">Unverified sample date</span>
                  )}
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="dashboard-opportunity-empty">
                <div>
                  <p className="dashboard-opportunity-eyebrow">Study opportunity</p>
                  <h2 id="active-journey-title">No study opportunity selected</h2>
                  <p className="dashboard-opportunity-institution">
                    Choose a Master's program or scholarship to see preparation steps and listed deadlines here.
                  </p>
                </div>
                <button
                  className="dashboard-opportunity-action"
                  onClick={() => navigate('/recommendations')}
                >
                  Find programs and scholarships
                  <span aria-hidden="true">→</span>
                </button>
              </div>
            </>
          )}
        </GlowCard>
      </section>
    </div>
  );
}
