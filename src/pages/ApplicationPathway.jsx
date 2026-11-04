import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight, CalendarDays, Check, Clock3, ExternalLink, FileText, ListChecks,
  Search, Sparkles, UserRound, Wallet,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import {
  JOURNEY_COMPLETED_STEPS_KEY, readUserStorage, writeUserStorage,
} from '../services/userStorage';
import './ApplicationPathway.css';

const JOURNEY_STEP_IDS = ['profile', 'explore', 'compare', 'finance', 'documents', 'deadlines'];

function getJourneyPosition(index) {
  const row = index < 3 ? 0 : 1;
  return { row, column: row === 0 ? index : 5 - index };
}

function getJourneySegments(stepCount) {
  const points = Array.from({ length: stepCount }, (_, index) => {
    const { row, column } = getJourneyPosition(index);
    return {
      x: ((column + 0.5) / 3) * 1000,
      y: row === 0 ? 36 : 266,
    };
  });

  return points.slice(1).map((point, index) => {
    const previous = points[index];
    if (previous.y === point.y) return `M ${previous.x} ${previous.y} L ${point.x} ${point.y}`;
    const midpoint = (previous.y + point.y) / 2;
    return `M ${previous.x} ${previous.y} C ${previous.x} ${midpoint}, ${point.x} ${midpoint}, ${point.x} ${point.y}`;
  });
}

function getUpcomingDeadlines(opportunities) {
  const today = new Date().toISOString().slice(0, 10);
  return opportunities
    .filter((item) => {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(item.deadlineDate || '')
        || item.deadlineDate < today
        || item.verificationStatus !== 'verified'
        || item.sourceStatus !== 'official-verified'
        || !item.sourceUrl
        || !item.lastVerified) return false;
      const timestamp = Date.parse(`${item.deadlineDate}T00:00:00Z`);
      return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === item.deadlineDate;
    })
    .sort((first, second) => first.deadlineDate.localeCompare(second.deadlineDate))
    .slice(0, 3);
}

function formatDeadlineDate(value) {
  return new Intl.DateTimeFormat('en', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${value}T00:00:00Z`));
}

function readCompletedStepIds(userId) {
  const completedIds = readUserStorage(JOURNEY_COMPLETED_STEPS_KEY, userId, []);
  return Array.isArray(completedIds) ? completedIds.filter((id) => JOURNEY_STEP_IDS.includes(id)) : [];
}

function JourneyStep({ step, onSelect, onToggle }) {
  const isComplete = step.status === 'done';
  const StateIcon = isComplete ? Check : Clock3;
  const statusLabel = isComplete ? 'Completed' : 'In Progress';
  const StepIcon = step.icon;

  return (
    <article className={`application-journey-step is-${step.status}`}>
      <button
        className="application-journey-content"
        type="button"
        onClick={() => onSelect(step.path)}
        aria-label={`Open ${step.title}. ${step.description}`}
      >
        <span className="application-journey-node" aria-hidden="true">
          <StepIcon size={27} strokeWidth={2.2} />
          <span className="application-journey-badge">
            {isComplete ? <Check size={12} strokeWidth={3} /> : step.number}
          </span>
        </span>
        <span className="application-journey-copy">
          <strong className="application-journey-title">{step.title}</strong>
          <span className="application-journey-desc">{step.description}</span>
        </span>
      </button>
      <label className={`application-pathway-step-status is-${step.status}`}>
        <input
          className="application-pathway-status-checkbox"
          type="checkbox"
          checked={isComplete}
          onChange={(event) => onToggle(step.id, event.target.checked)}
          aria-label={`Mark ${step.title} as ${isComplete ? 'in progress' : 'completed'}`}
        />
        <StateIcon size={12} aria-hidden="true" /> {statusLabel}
      </label>
      {step.deadlines?.length > 0 && (
        <details className="application-pathway-step-deadlines">
          <summary>View {step.deadlines.length} verified deadline{step.deadlines.length === 1 ? '' : 's'}</summary>
          <ul>
            {step.deadlines.map((deadline) => (
              <li key={deadline.id}>
                <span>{deadline.name}</span>
                <time dateTime={deadline.deadlineDate}>{formatDeadlineDate(deadline.deadlineDate)}</time>
                <small>Verified {formatDeadlineDate(deadline.lastVerified)}</small>
                <a href={deadline.sourceUrl} target="_blank" rel="noopener noreferrer" aria-label={`View official source for ${deadline.name}`}>
                  <ExternalLink size={12} aria-hidden="true" /> Official source
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

export default function ApplicationPathway() {
  const { user } = useAuth();
  return <ApplicationPathwayContent key={user?.id ?? 'anonymous'} userId={user?.id} />;
}

function ApplicationPathwayContent({ userId }) {
  const navigate = useNavigate();
  const {
    profile, savedOpportunities, comparisonOpportunityIds, documentRecords,
  } = useProfile();
  const [scholarships, setScholarships] = useState([]);
  const [completedStepIds, setCompletedStepIds] = useState(() => readCompletedStepIds(userId));
  const [deadlineLoadState, setDeadlineLoadState] = useState('loading');

  useEffect(() => {
    writeUserStorage(JOURNEY_COMPLETED_STEPS_KEY, userId, completedStepIds);
  }, [completedStepIds, userId]);

  useEffect(() => {
    let current = true;
    apiService.getMatchedScholarships()
      .then((items) => {
        if (!current) return;
        setScholarships(items);
        setDeadlineLoadState('ready');
      })
      .catch((error) => {
        console.error('Unable to load verified scholarship deadlines for the preparation journey.', error);
        if (current) setDeadlineLoadState('error');
      });
    return () => { current = false; };
  }, []);

  const deadlines = useMemo(() => getUpcomingDeadlines(scholarships), [scholarships]);
  const uploadedDocumentCount = Object.values(documentRecords)
    .filter(Boolean).length;
  const hasBudget = profile.approximateBudget !== '' && profile.approximateBudget != null;
  const savedScholarshipCount = Array.isArray(savedOpportunities)
    ? savedOpportunities.filter((id) => typeof id === 'string' && id.startsWith('sch-')).length
    : null;
  const steps = [
    {
      id: 'profile', number: 1, title: 'Complete Your Profile',
      description: 'Add your academic, personal, and English-language information.',
      path: '/profile', icon: UserRound,
    },
    {
      id: 'explore', number: 2, title: 'Explore Scholarships',
      description: savedScholarshipCount == null
        ? 'Discover scholarships and personalized matches.'
        : `${savedScholarshipCount} saved · Discover personalized matches.`,
      path: '/scholarships', icon: Search,
    },
    {
      id: 'compare', number: 3, title: 'Compare & Shortlist',
      description: `${comparisonOpportunityIds.length} selected · Compare funding, eligibility, deadlines & requirements.`,
      path: '/compare', icon: ListChecks,
    },
    {
      id: 'finance', number: 4, title: 'Check Funding & Affordability',
      description: hasBudget
        ? 'Review confirmed funding, available costs, and your saved budget.'
        : 'Review confirmed funding and available costs; add a budget when ready.',
      path: '/financial', icon: Wallet,
    },
    {
      id: 'documents', number: 5, title: 'Prepare Scholarship Documents',
      description: uploadedDocumentCount
        ? `${uploadedDocumentCount} document${uploadedDocumentCount === 1 ? '' : 's'} uploaded. Review provider requirements.`
        : 'Review provider requirements and prepare your scholarship documents.',
      path: '/documents', icon: FileText,
    },
    {
      id: 'deadlines', number: 6, title: 'Review Scholarship Deadlines',
      description: deadlineLoadState === 'loading'
        ? 'Loading verified scholarship deadlines…'
        : deadlineLoadState === 'error'
          ? 'Verified deadline information is temporarily unavailable.'
          : deadlines[0]
            ? `Next: ${deadlines[0].name} · ${formatDeadlineDate(deadlines[0].deadlineDate)}.`
            : 'No upcoming verified scholarship deadlines.',
      deadlines,
      path: '/scholarships', icon: CalendarDays,
    },
  ].map((step) => ({
    ...step,
    status: completedStepIds.includes(step.id) ? 'done' : 'in-progress',
  }));
  const handleToggleStep = (stepId, isComplete) => {
    setCompletedStepIds((current) => (
      isComplete
        ? [...new Set([...current, stepId])]
        : current.filter((id) => id !== stepId)
    ));
  };
  const completedCount = steps.filter((step) => step.status === 'done').length;
  const inProgressCount = steps.filter((step) => step.status === 'in-progress').length;
  const nextStep = steps.find((step) => step.status !== 'done');
  const handleStepSelect = (path) => navigate(path);

  return (
    <main className="application-pathway-page">
      <div className="application-pathway-columns">
        <div className="application-pathway-main">
          <header className="application-pathway-hero">
            <div className="application-pathway-hero-copy">
              <p className="application-pathway-eyebrow"><Sparkles size={15} aria-hidden="true" /> Scholarship Journey</p>
              <h1>Scholarship Preparation Journey</h1>
              <p>Discover, compare, and prepare for scholarships with confidence.</p>
            </div>
            <img className="application-pathway-photo" src="/images/study-abroad-banner.jpg" alt="" aria-hidden="true" />
          </header>

          <section className="application-pathway-journey-panel" aria-label="Scholarship preparation journey steps">
            <div className="application-pathway-journey is-overall-journey">
              <svg className="application-pathway-journey-line" viewBox="0 0 1000 420" preserveAspectRatio="none" aria-hidden="true">
                <defs>
                  <marker id="application-pathway-arrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
                    <path d="M1 1 L7 4.5 L1 8" />
                  </marker>
                </defs>
                {getJourneySegments(steps.length).map((segment, index) => (
                  <path key={index} d={segment} markerEnd="url(#application-pathway-arrow)" />
                ))}
              </svg>
              {steps.map((step, index) => {
                const position = getJourneyPosition(index);
                return (
                  <div
                    key={step.id}
                    className="application-pathway-journey-slot"
                    style={{ gridColumn: position.column + 1, gridRow: position.row + 1 }}
                  >
                    <JourneyStep step={step} onSelect={handleStepSelect} onToggle={handleToggleStep} />
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        <aside className="application-pathway-rail" aria-label="Journey progress">
          <section className="application-pathway-card application-pathway-next-level">
            <div className="application-pathway-rail-heading">
              <h2>Next Step</h2>
              <ArrowRight size={17} aria-hidden="true" />
            </div>
            {nextStep ? (
              <div className="application-pathway-next-card">
                <span className="application-pathway-next-number">{nextStep.number}</span>
                <div className="application-pathway-next-copy">
                  <h3>{nextStep.title}</h3>
                  <p>{nextStep.description}</p>
                </div>
                <button className="application-pathway-next-action" type="button" onClick={() => handleStepSelect(nextStep.path)}>
                  Go to {nextStep.title} <ArrowRight size={14} aria-hidden="true" />
                </button>
              </div>
            ) : <p className="application-pathway-all-complete">You’ve completed all six journey steps.</p>}
          </section>

          <section className="application-pathway-card application-pathway-progress-card">
            <h2 className="application-pathway-card-title">Your Progress</h2>
            <div
              className="application-pathway-progress-ring"
              role="progressbar"
              aria-label="Scholarship preparation steps completed"
              aria-valuemin={0}
              aria-valuemax={steps.length}
              aria-valuenow={completedCount}
              style={{
                '--journey-completed-angle': `${(completedCount / steps.length) * 360}deg`,
                '--journey-current-angle': `${((completedCount + inProgressCount) / steps.length) * 360}deg`,
              }}
            >
              <div><strong>{completedCount} / {steps.length}</strong><span>Steps Completed</span></div>
            </div>
            <ul className="application-pathway-legend">
              <li><span className="is-complete" />Completed<strong>{completedCount}</strong></li>
              <li><span className="is-current" />In Progress<strong>{inProgressCount}</strong></li>
            </ul>
          </section>

          <section className="application-pathway-encouragement" aria-label="Encouragement">
            <div>
              <h2>Big dreams take consistent steps.</h2>
              <p>You’re making progress.</p>
            </div>
            <Sparkles size={24} aria-hidden="true" />
          </section>
        </aside>
      </div>
    </main>
  );
}
