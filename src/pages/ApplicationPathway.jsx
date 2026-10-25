import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  BadgeCheck,
  CalendarDays,
  Check,
  Circle,
  ClipboardList,
  FileText,
  Flag,
  GraduationCap,
  Info,
  LockKeyhole,
  Map,
  Plane,
  Search,
  UserRound,
  WalletCards,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import { mockApplicationPathways } from '../data/mockData';
import { getOpportunityTitle } from '../services/opportunityJourney';
import {
  DEFAULT_APPLICATION_STRATEGY,
  getPathwayTaskId,
  getSelectedApplicationStrategy,
  saveSelectedApplicationStrategy,
} from '../services/applicationWorkflow';
import './ApplicationPathway.css';

const STEP_ICONS = [
  UserRound,
  Search,
  ClipboardList,
  WalletCards,
  FileText,
  CalendarDays,
  FileText,
  Flag,
];

function JourneyIllustration() {
  return (
    <svg className="application-pathway-illustration" viewBox="0 0 520 190" aria-hidden="true">
      <defs>
        <linearGradient id="pathway-mountain-back" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#d7efff" />
          <stop offset="1" stopColor="#aad5fa" />
        </linearGradient>
        <linearGradient id="pathway-mountain-front" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#84c4f7" />
          <stop offset="1" stopColor="#3b8ce0" />
        </linearGradient>
      </defs>
      <path d="M0 190 108 104l48 41 91-94 75 75 55-47 143 111Z" fill="url(#pathway-mountain-back)" opacity=".72" />
      <path d="m122 190 111-117 54 58 45-38 92 97Z" fill="url(#pathway-mountain-front)" opacity=".76" />
      <path d="m214 190 75-91 40 43 24-23 69 71Z" fill="#5ba7ed" opacity=".72" />
      <path d="M159 52c66-42 107-35 147-22" fill="none" stroke="#77b8ed" strokeDasharray="5 7" strokeWidth="2" />
      <path d="m295 26 19 4-16 12 4-8-11-2Z" fill="#196bc2" />
      <path d="m382 36 15-15 2 17-8-5-10 3Z" fill="#fff" opacity=".95" />
      <path d="M389 36v27" stroke="#4b91d2" strokeWidth="2" />
    </svg>
  );
}

const JOURNEY_ROWS = [190, 80, 190];
const JOURNEY_ROW_TOPS = [0, 190, 270];
const JOURNEY_HEIGHT = 460;
const NODE_CENTER_Y = 40;

function getJourneyPosition(index, stepCount) {
  if (index < 4) return { row: 0, column: index };
  if (index === 4) return { row: 1, column: 3 };
  return { row: 2, column: Math.max(stepCount - index - 1, 0) };
}

function getJourneySegments(stepCount) {
  const points = Array.from({ length: stepCount }, (_, index) => {
    const { row, column } = getJourneyPosition(index, stepCount);
    return { x: ((column + 0.5) / 4) * 1000, y: JOURNEY_ROW_TOPS[row] + NODE_CENTER_Y };
  });

  return points.slice(1).map((point, index) => {
    const previous = points[index];
    if (previous.y === point.y) {
      return `M ${previous.x} ${previous.y} L ${point.x} ${point.y}`;
    }
    if (previous.x === point.x) {
      const bulge = Math.min(previous.x + 110, 995);
      return `M ${previous.x} ${previous.y} C ${bulge} ${previous.y}, ${bulge} ${point.y}, ${point.x} ${point.y}`;
    }
    const midY = (previous.y + point.y) / 2;
    return `M ${previous.x} ${previous.y} C ${previous.x} ${midY}, ${point.x + 60} ${point.y}, ${point.x} ${point.y}`;
  });
}

function createGenericPathway(opportunityId, strategy) {
  const applicationPlan = strategy === 'Scholarship First'
    ? 'Apply for the scholarship first, then apply to the university and follow both providers’ instructions for linking your applications.'
    : strategy === 'Combined Application'
      ? 'Apply through the combined university and funding process, following the provider’s instructions for requesting scholarship or assistantship consideration.'
      : 'Apply to the university first. After receiving an admission decision, apply for the scholarship unless the provider instructs otherwise.';

  return {
    opportunityId,
    type: strategy,
    steps: [
      { id: 'build-profile', title: 'Build Your Profile', description: 'Complete your academic, personal, and language details to create your profile.' },
      { id: 'explore-opportunities', title: 'Explore Opportunities', description: 'Discover universities, scholarships, and programs that match your goals.' },
      { id: 'compare-shortlist', title: 'Compare & Shortlist', description: 'Shortlist the best options based on your preferences and eligibility.' },
      { id: 'financial-feasibility', title: 'Financial Feasibility', description: 'Estimate tuition and living costs, review funding options, and check affordability.' },
      { id: 'plan-application', title: 'Plan Your Application', description: applicationPlan },
      { id: 'prepare-documents', title: 'Prepare Documents', description: 'Gather and organize the transcripts, statement of purpose, CV, and references required by the providers.' },
      { id: 'track-deadlines', title: 'Track Deadlines', description: 'Stay on top of application, scholarship, and supporting document deadlines.' },
      { id: 'application-ready', title: 'Application Ready', description: 'Review your applications and confirm each provider’s requirements before submitting.' },
    ],
  };
}

const STEP_DESCRIPTIONS = {
  'build-profile': 'Complete your academic, personal, and language details.',
  'explore-opportunities': 'Find programs and scholarships that match your goals.',
  'compare-shortlist': 'Compare options and choose the opportunities to pursue.',
  'financial-feasibility': 'Estimate study costs and review available funding.',
  'plan-application': 'Confirm whether to apply to the university or scholarship first.',
  'prepare-documents': 'Gather the transcripts, CV, essays, and references required.',
  'track-deadlines': 'Record and confirm each application and scholarship deadline.',
  'application-ready': 'Review provider requirements before submitting applications.',
};

function getStepDescription(step) {
  return STEP_DESCRIPTIONS[step.id] || step.description || 'Review the requirements and complete this part of your application plan.';
}

function JourneyStep({ step, index, stepCount, status, isNext, canUpdate, onToggle }) {
  const Icon = STEP_ICONS[index % STEP_ICONS.length];
  const completed = status === 'done';
  const { row, column } = getJourneyPosition(index, stepCount);
  const state = completed ? 'complete' : isNext ? 'current' : 'locked';

  return (
    <article
      className={`application-journey-step is-${state}`}
      style={{ gridColumn: column + 1, gridRow: row + 1 }}
    >
      <div className="application-journey-node">
        <Icon size={28} strokeWidth={2.2} aria-hidden="true" />
        <span className="application-journey-badge">
          {completed ? <Check size={13} strokeWidth={3} aria-hidden="true" /> : index + 1}
        </span>
      </div>
      <h2 className="application-journey-title">{step.title}</h2>
      <p className="application-journey-desc">{getStepDescription(step)}</p>
      <button
        type="button"
        className={`application-journey-chip is-${state}`}
        onClick={onToggle}
        disabled={!canUpdate || state === 'locked'}
        title={state === 'current' ? 'Mark this step as completed' : state === 'complete' ? 'Mark this step as not completed' : undefined}
      >
        {completed ? <BadgeCheck size={13} aria-hidden="true" /> : isNext ? <Circle size={12} aria-hidden="true" /> : <LockKeyhole size={12} aria-hidden="true" />}
        {completed ? 'Completed' : isNext ? 'In Progress' : 'Locked'}
      </button>
    </article>
  );
}

export default function ApplicationPathway() {
  const navigate = useNavigate();
  const {
    activeOpportunity,
    profile,
    opportunityTaskStatuses,
    setOpportunityTaskStatus,
    selectedOpportunities,
    setActiveOpportunity,
  } = useProfile();
  const activeOpportunityId = activeOpportunity?.id;
  const activeOpportunityKind = activeOpportunity?.kind;
  const [strategySelection, setStrategySelection] = useState(null);
  const [pathwayResult, setPathwayResult] = useState(null);
  const [error, setError] = useState('');
  const strategy = activeOpportunityId
    ? activeOpportunityKind === 'scholarship'
      ? activeOpportunity.pathway || DEFAULT_APPLICATION_STRATEGY
      : strategySelection?.opportunityId === activeOpportunityId
      ? strategySelection.value
      : getSelectedApplicationStrategy(activeOpportunityId)
    : DEFAULT_APPLICATION_STRATEGY;
  const strategies = activeOpportunityKind === 'program'
    ? [...new Set(mockApplicationPathways
      .filter((item) => item.universityId === activeOpportunityId)
      .map((item) => item.type))]
    : [];
  const statuses = activeOpportunity ? opportunityTaskStatuses[activeOpportunity.id] || {} : {};

  useEffect(() => {
    if (!activeOpportunityId || activeOpportunityKind !== 'program') return undefined;
    let current = true;
    apiService.getApplicationPathway(activeOpportunityId, strategy)
      .then((result) => { if (current) setPathwayResult({ opportunityId: activeOpportunityId, strategy, value: result }); })
      .catch((loadError) => {
        console.error('Unable to load the selected opportunity pathway.', loadError);
        if (current) setError('The application pathway could not be loaded.');
      });
    return () => { current = false; };
  }, [activeOpportunityId, activeOpportunityKind, strategy]);

  const pathway = pathwayResult &&
    pathwayResult.opportunityId === activeOpportunity?.id &&
    pathwayResult.strategy === strategy
    ? pathwayResult.value
    : null;
  const displayedPathway = pathway || createGenericPathway(activeOpportunity?.id || 'journey-preview', strategy);
  const steps = displayedPathway?.steps || [];
  const completedCount = steps.filter((step) => statuses[getPathwayTaskId(displayedPathway, step)] === 'done').length;
  const nextStepIndex = steps.findIndex((step) => statuses[getPathwayTaskId(displayedPathway, step)] !== 'done');
  const inProgressCount = nextStepIndex < 0 ? 0 : 1;
  const lockedCount = Math.max(steps.length - completedCount - inProgressCount, 0);
  const journeySegments = getJourneySegments(steps.length);
  const progressPercentage = steps.length ? (completedCount / steps.length) * 100 : 0;
  const academicProfile = (profile.verifiedProfile || profile.profileDraft || profile).academicBackground || {};
  const academicRequiredFields = [
    'currentDegree', 'degreeTitle', 'institution', 'institutionCountry', 'academicStatus',
    ...(academicProfile.academicStatus === 'studying' ? ['currentYear'] : []),
    'cgpa', 'gradingScale',
    ...(academicProfile.gradingScale === 'Other' ? ['customGradingScale'] : []),
    'degreeStartDate',
    ...(academicProfile.academicStatus === 'studying' ? ['expectedGraduationDate'] : ['graduationDate']),
  ];
  const academicFieldsRemaining = academicRequiredFields.filter((field) => {
    const value = academicProfile[field];
    return value === undefined || value === null || value === '';
  }).length;
  const nextStep = nextStepIndex >= 0 ? steps[nextStepIndex] : null;
  const nextAction = nextStep?.id === 'build-profile'
    ? {
      label: academicFieldsRemaining
        ? `Complete Academic Background (${academicFieldsRemaining} fields left)`
        : 'Review Academic Background',
      route: '/profile?edit=1&step=1',
    }
    : nextStep?.id === 'explore-opportunities'
      ? { label: 'Browse matching opportunities', route: '/recommendations' }
      : nextStep?.id === 'compare-shortlist'
        ? { label: 'Compare shortlisted options', route: '/compare' }
        : nextStep?.id === 'financial-feasibility'
          ? { label: 'Review your study budget', route: '/financial' }
          : nextStep?.id === 'prepare-documents'
            ? { label: 'Prepare required documents', route: '/documents' }
            : nextStep?.id === 'track-deadlines'
              ? { label: 'Review application tasks', route: '/timeline' }
              : nextStep
                ? { label: nextStep.title, route: '/timeline' }
                : null;
  const strategyExplanation = strategy === 'University First'
    ? 'Apply for university admission first, then submit a separate scholarship application, unless either provider gives different instructions.'
    : strategy === 'Scholarship First'
      ? 'Apply for the scholarship first, then follow its instructions for university admission and linking applications.'
      : 'Use the combined university and funding application process, following the provider’s instructions for scholarship consideration.';
  const selectedOpportunityLabel = activeOpportunity
    ? `${getOpportunityTitle(activeOpportunity)} · ${activeOpportunity.university || activeOpportunity.provider || activeOpportunity.country}`
    : '';

  const changeStrategy = (event) => {
    const nextStrategy = event.target.value;
    try {
      saveSelectedApplicationStrategy(activeOpportunity.id, nextStrategy);
      setStrategySelection({ opportunityId: activeOpportunity.id, value: nextStrategy });
      setError('');
    } catch (saveError) {
      console.error('Unable to save the selected application strategy.', saveError);
      setError('Your selected strategy could not be saved.');
    }
  };

  const updateStep = (step, completed) => {
    if (!activeOpportunity) return;
    try {
      setOpportunityTaskStatus(
        activeOpportunity.id,
        getPathwayTaskId(displayedPathway, step),
        completed ? 'done' : 'todo',
      );
      setError('');
    } catch (saveError) {
      console.error('Unable to save pathway task status.', saveError);
      setError('Pathway progress could not be saved.');
    }
  };

  return (
    <main className="application-pathway-page">
      <div className="application-pathway-columns">
        <div className="application-pathway-main">
          <header className="application-pathway-hero">
            <div className="application-pathway-hero-copy">
              <span className="application-pathway-eyebrow"><Plane size={16} /> Application Journey</span>
              <h1>Your Study Abroad Journey</h1>
              <p>Follow each step, complete your tasks and get closer to your dream university!</p>
            </div>
            <JourneyIllustration />
          </header>

          {activeOpportunity && (
            <div className="application-pathway-controls">
              <div className="application-pathway-selected">
                <GraduationCap size={15} aria-hidden="true" />
                {selectedOpportunities.length > 1 ? (
                  <label>
                    <span className="sr-only">Active opportunity</span>
                    <select
                      value={activeOpportunity.id}
                      onChange={(event) => setActiveOpportunity(event.target.value)}
                    >
                      {selectedOpportunities.map((opportunity) => (
                        <option key={opportunity.id} value={opportunity.id}>
                          {getOpportunityTitle(opportunity)}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : <span>{selectedOpportunityLabel}</span>}
              </div>
              {activeOpportunity && (
                <div className="application-pathway-strategy-group">
                  {strategies.length > 0 && (
                    <label className="application-pathway-strategy">
                      <span>Application strategy</span>
                      <select value={strategy} onChange={changeStrategy}>
                        {!strategies.includes(strategy) && <option value={strategy}>{strategy} (not available)</option>}
                        {strategies.map((item) => <option key={item}>{item}</option>)}
                      </select>
                    </label>
                  )}
                  <details className="application-pathway-strategy-help">
                    <summary aria-label={`Explain ${strategy}`}><Info size={15} aria-hidden="true" /></summary>
                    <p>{strategyExplanation}</p>
                  </details>
                </div>
              )}
            </div>
          )}
          {error && <p className="application-pathway-error" role="alert">{error}</p>}

          {steps.length > 0 ? (
            <>
              <section className="application-pathway-roadmap" aria-label="Application roadmap">
                <div
                  className="application-pathway-journey"
                  style={{
                    gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
                    gridTemplateRows: `${JOURNEY_ROWS[0]}px ${JOURNEY_ROWS[1]}px ${JOURNEY_ROWS[2]}px`,
                  }}
                >
                  <svg
                    className="application-pathway-journey-line"
                    viewBox={`0 0 1000 ${JOURNEY_HEIGHT}`}
                    preserveAspectRatio="none"
                    aria-hidden="true"
                  >
                    {journeySegments.map((segment, index) => {
                      const done = statuses[getPathwayTaskId(displayedPathway, steps[index])] === 'done';
                      return <path key={index} d={segment} className={done ? 'is-complete' : ''} />;
                    })}
                  </svg>
                  {steps.map((step, index) => {
                    const id = getPathwayTaskId(displayedPathway, step);
                    const status = statuses[id] || 'todo';
                    return (
                      <JourneyStep
                        key={id}
                        step={step}
                        index={index}
                        stepCount={steps.length}
                        status={status}
                        isNext={index === nextStepIndex}
                        canUpdate={Boolean(activeOpportunity)}
                        onToggle={() => updateStep(step, status !== 'done')}
                      />
                    );
                  })}
                </div>
              </section>
              <p className="application-pathway-note">
                {!activeOpportunity
                  ? 'Journey preview: select an opportunity to see its application strategy and track your progress.'
                  : strategy === 'University First'
                    ? 'University first: apply for admission before submitting a separate scholarship application, unless the official provider instructs otherwise.'
                    : strategy === 'Scholarship First'
                      ? 'Scholarship first: submit the scholarship application before applying to the university, unless the official provider instructs otherwise.'
                      : 'Combined application: apply through the combined university and funding process described by the provider.'}
                {activeOpportunity && ' Confirm application order, deadlines, and document requirements with the official provider.'}
              </p>
              {!activeOpportunity && (
                <button
                  type="button"
                  className="application-pathway-browse-button"
                  onClick={() => navigate('/recommendations')}
                >
                  Browse recommendations <ArrowRight size={14} aria-hidden="true" />
                </button>
              )}
            </>
          ) : (
            <section className="application-pathway-empty">
              <Map size={24} aria-hidden="true" />
              <h2>{activeOpportunity ? 'No pathway available yet' : 'Start your study abroad journey'}</h2>
              <p>
                {activeOpportunity
                  ? 'No application pathway is available for this opportunity and strategy. Confirm its application process with the provider.'
                  : 'Select an opportunity to view its application steps and track your progress.'}
              </p>
              {!activeOpportunity && (
                <button type="button" onClick={() => navigate('/recommendations')}>Browse recommendations <ArrowRight size={15} /></button>
              )}
            </section>
          )}
        </div>

        <aside className="application-pathway-rail" aria-label="Application progress">
          <section className="application-pathway-card">
            <h2 className="application-pathway-card-title">Next Level <ArrowRight size={16} aria-hidden="true" /></h2>
            <div className="application-pathway-next-card">
              <span className="application-pathway-next-number">{nextStepIndex >= 0 ? nextStepIndex + 1 : steps.length}</span>
              <div className="application-pathway-next-copy">
                <h3>{nextStep?.title || 'Journey complete!'}</h3>
                {nextStep && <p>{getStepDescription(nextStep)}</p>}
              </div>
              <div className="application-pathway-next-art" aria-hidden="true">
                <ClipboardList size={30} />
              </div>
              <button type="button" onClick={() => navigate(nextAction?.route || '/timeline')}>
                {nextAction?.label || 'Go to Application Plan'} <ArrowRight size={14} aria-hidden="true" />
              </button>
            </div>
          </section>

          <section className="application-pathway-card">
            <h2 className="application-pathway-card-title">Your Progress</h2>
            <div
              className="application-pathway-progress-ring"
              role="progressbar"
              aria-label="Application steps completed"
              aria-valuemin={0}
              aria-valuemax={steps.length || 1}
              aria-valuenow={completedCount}
              style={{
                '--journey-completed-angle': `${progressPercentage * 3.6}deg`,
                '--journey-current-angle': `${(progressPercentage + (steps.length ? (inProgressCount / steps.length) * 100 : 0)) * 3.6}deg`,
              }}
            >
              <div>
                <strong>{completedCount} / {steps.length}</strong>
                <span>Steps Completed</span>
              </div>
            </div>
            <ul className="application-pathway-legend">
              <li><span className="is-complete" />Completed <strong>{completedCount}</strong></li>
              <li><span className="is-current" />In Progress <strong>{inProgressCount}</strong></li>
              <li><span className="is-locked" />Locked <strong>{lockedCount}</strong></li>
            </ul>
          </section>

          <section className="application-pathway-encouragement">
            <p>Big dreams<br />take consistent steps.</p>
            <small>You’re doing great!</small>
            <Plane size={22} aria-hidden="true" />
            <div className="application-pathway-encouragement-mountains" aria-hidden="true" />
          </section>
        </aside>
      </div>
    </main>
  );
}
