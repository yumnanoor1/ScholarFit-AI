import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle, ArrowRight, CalendarDays, CheckCircle2, Circle, Clock3,
  FileText, GraduationCap,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import { mockApplicationPathways } from '../data/mockData';
import {
  getDocumentStatus,
  getOpportunityProgress,
  getOpportunityTitle,
} from '../services/opportunityJourney';
import OfficialApplicationLink from '../components/opportunities/OfficialApplicationLink';
import {
  DEFAULT_APPLICATION_STRATEGY,
  getSelectedApplicationStrategy,
  saveSelectedApplicationStrategy,
} from '../services/applicationWorkflow';
import './Timeline.css';

const EMPTY_TASK_STATUSES = {};

function formatDate(value) {
  if (!value) return 'Date unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
}

function taskRoute(task, opportunity) {
  if (task.kind === 'document') return `/documents#doc-${task.documentId}`;
  if (task.kind === 'requirement') {
    return opportunity.kind === 'scholarship'
      ? `/scholarships/${opportunity.id}`
      : `/universities/${opportunity.id}`;
  }
  if (task.kind === 'pathway') return '/pathway';
  return opportunity.kind === 'scholarship' ? `/scholarships/${opportunity.id}` : `/universities/${opportunity.id}`;
}

function TimelineTaskCard({
  task,
  status,
  opportunity,
  documentRecords,
  onStatusChange,
  onUpdate,
  onNavigate,
}) {
  const due = task.dueDate ? new Date(task.dueDate) : null;
  const overdue = due && !Number.isNaN(due.getTime()) && due < new Date() && status !== 'done';
  const nextStatus = status === 'todo' ? 'in-progress' : status === 'in-progress' ? 'done' : 'todo';
  const sourceLabel = task.source === 'official-verified'
    ? 'Officially verified'
    : task.source === 'unverified-sample' || task.source === 'pathway-sample'
      ? 'Sample data · verify with provider'
      : task.source;

  return (
    <article className={`timeline-task-card ${status === 'in-progress' ? 'is-in-progress' : ''}`}>
      <div className="timeline-task-card-top">
        <span className={`timeline-task-status ${status}`}>
          {status === 'done' ? 'Completed' : status === 'in-progress' ? 'In progress' : 'To do'}
        </span>
        {task.dueDate && (
          <span className={`timeline-task-date ${overdue ? 'is-overdue' : ''}`}>
            <CalendarDays size={13} aria-hidden="true" />
            {overdue ? 'Past listed date' : 'Listed date'}: {formatDate(task.dueDate)}
          </span>
        )}
      </div>
      <h3>{task.title}</h3>
      <p className="timeline-task-reason">{task.reason}</p>
      {task.kind === 'document' && (
        <p className="timeline-task-document-status">
          Document status: {({ missing: 'Missing', 'awaiting-verification': 'Awaiting verification', uploaded: 'Uploaded & verified' }[getDocumentStatus(documentRecords[task.documentId])])}.
          Completing this task does not verify the document.
        </p>
      )}
      {sourceLabel && <p className="timeline-task-source">{sourceLabel}</p>}
      <div className="timeline-task-controls">
        <button
          type="button"
          className="timeline-task-related"
          onClick={() => onNavigate(taskRoute(task, opportunity))}
        >
          {task.kind === 'document' ? 'Open documents' : 'View details'}
          <ArrowRight size={14} aria-hidden="true" />
        </button>
        <label className="sr-only" htmlFor={`timeline-status-${task.id}`}>Status for {task.title}</label>
        <select
          id={`timeline-status-${task.id}`}
          value={status}
          onChange={(event) => onStatusChange(event.target.value)}
        >
          <option value="todo">To do</option>
          <option value="in-progress">In progress</option>
          <option value="done">Completed</option>
        </select>
        <button
          type="button"
          className="timeline-task-primary"
          onClick={() => onUpdate(nextStatus)}
        >
          {status === 'todo' ? 'Start task' : status === 'in-progress' ? 'Complete task' : 'Reopen'}
        </button>
      </div>
    </article>
  );
}

export default function Timeline() {
  const navigate = useNavigate();
  const {
    profile,
    activeOpportunity,
    documentRecords,
    appliedOpportunityIds,
    markOpportunityApplied,
    opportunityTaskStatuses,
    setOpportunityTaskStatus,
  } = useProfile();
  const activeOpportunityId = activeOpportunity?.id;
  const [strategySelection, setStrategySelection] = useState(null);
  const [pathwayResult, setPathwayResult] = useState(null);
  const [pathwayError, setPathwayError] = useState(null);
  const [storageError, setStorageError] = useState('');
  const strategy = activeOpportunityId
    ? strategySelection?.opportunityId === activeOpportunityId
      ? strategySelection.value
      : getSelectedApplicationStrategy(activeOpportunityId)
    : DEFAULT_APPLICATION_STRATEGY;
  const activeStatuses = activeOpportunityId
    ? opportunityTaskStatuses[activeOpportunityId] || EMPTY_TASK_STATUSES
    : EMPTY_TASK_STATUSES;
  const availableStrategies = activeOpportunity?.kind === 'program'
    ? [...new Set(mockApplicationPathways
      .filter((item) => item.universityId === activeOpportunityId)
      .map((item) => item.type))]
    : [];

  useEffect(() => {
    if (!activeOpportunityId) return undefined;
    let current = true;
    apiService.getApplicationPathway(activeOpportunityId, strategy)
      .then((result) => { if (current) setPathwayResult({ opportunityId: activeOpportunityId, strategy, value: result }); })
      .catch((error) => {
        console.error('Unable to load selected opportunity pathway.', error);
        if (current) setPathwayError({ opportunityId: activeOpportunityId, strategy, message: 'The selected opportunity pathway could not be loaded.' });
      })
    return () => { current = false; };
  }, [activeOpportunityId, strategy]);

  const pathway = pathwayResult &&
    pathwayResult.opportunityId === activeOpportunityId &&
    pathwayResult.strategy === strategy
    ? pathwayResult.value
    : null;
  const pathwayLoaded = Boolean(
    pathwayResult &&
    pathwayResult.opportunityId === activeOpportunityId &&
    pathwayResult.strategy === strategy
  );
  const loading = Boolean(activeOpportunity && !pathwayLoaded && !(pathwayError?.opportunityId === activeOpportunity.id && pathwayError.strategy === strategy));
  const loadError = pathwayError &&
    pathwayError.opportunityId === activeOpportunity?.id &&
    pathwayError.strategy === strategy
    ? pathwayError.message
    : '';

  const progress = useMemo(() => activeOpportunity
    ? getOpportunityProgress(activeOpportunity, activeStatuses, pathway, profile)
    : { tasks: [], percentage: 0, completed: 0, nextTask: null },
  [activeOpportunity, activeStatuses, pathway, profile]);

  const changeStrategy = (event) => {
    const nextStrategy = event.target.value;
    try {
      saveSelectedApplicationStrategy(activeOpportunity.id, nextStrategy);
      setStrategySelection({ opportunityId: activeOpportunity.id, value: nextStrategy });
      setPathwayError(null);
    } catch (error) {
      console.error('Unable to save application strategy.', error);
      setStorageError('Your strategy could not be saved in this browser.');
    }
  };

  const updateTask = (task, status) => {
    try {
      setOpportunityTaskStatus(activeOpportunity.id, task.id, status);
      setStorageError('');
    } catch (error) {
      console.error('Unable to save application task status.', error);
      setStorageError('Task progress could not be saved.');
    }
  };

  if (!activeOpportunity) {
    return (
      <main className="page-container application-timeline-page">
        <header className="timeline-page-heading">
          <div>
            <span className="timeline-eyebrow">STUDY OPPORTUNITY PLANNING</span>
            <h1>Application Timeline</h1>
            <p>Organize preparation tasks and review listed dates for a Master's program or scholarship.</p>
          </div>
        </header>
        <section className="timeline-empty-state card">
          <span className="timeline-empty-icon"><GraduationCap size={24} aria-hidden="true" /></span>
          <h2>Select an opportunity to build your preparation timeline</h2>
          <p>Choose a Master's program or scholarship to see its requirements, document preparation, supported steps, and available dates.</p>
          <button type="button" onClick={() => navigate('/recommendations')}>
            Explore matched opportunities <ArrowRight size={16} aria-hidden="true" />
          </button>
        </section>
      </main>
    );
  }

  const now = new Date();
  const datedOpen = progress.tasks
    .map((task) => ({ task, due: task.dueDate ? new Date(task.dueDate) : null }))
    .filter(({ task, due }) => due && !Number.isNaN(due.getTime()) && (activeStatuses[task.id] || task.status) !== 'done');
  const overdueCount = datedOpen.filter(({ due }) => due < now).length;
  const nextDeadline = datedOpen.filter(({ due }) => due >= now).sort((a, b) => a.due - b.due)[0] || null;
  const getTaskStatus = (task) => activeStatuses[task.id] || task.status;
  const inProgressTasks = progress.tasks.filter((task) => getTaskStatus(task) === 'in-progress');
  const upcomingTasks = progress.tasks.filter((task) => getTaskStatus(task) === 'todo');
  const completedTasks = progress.tasks.filter((task) => getTaskStatus(task) === 'done');
  const opportunityLocation = [
    activeOpportunity.university || activeOpportunity.provider,
    activeOpportunity.country,
  ].filter(Boolean).join(' · ');

  return (
    <main className="page-container application-timeline-page">
      <header className="timeline-page-heading">
        <div>
          <span className="timeline-eyebrow">STUDY OPPORTUNITY PLANNING</span>
          <h1>Application Timeline</h1>
          <p>
            {getOpportunityTitle(activeOpportunity)}
            {opportunityLocation && <> · {opportunityLocation}</>}
          </p>
        </div>
        {availableStrategies.length > 0 && (
          <label className="timeline-strategy">
            <span>Preparation strategy</span>
            <select value={strategy} onChange={changeStrategy}>
              {!availableStrategies.includes(strategy) && <option value={strategy}>{strategy} (not available for this program)</option>}
              {availableStrategies.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
        )}
      </header>
      {(storageError || loadError) && (
        <p className="timeline-feedback is-error" role="alert">{storageError || loadError}</p>
      )}
      {loading && <p className="timeline-feedback" role="status">Loading preparation tasks...</p>}

      <div className="timeline-dashboard-grid">
        <section className="timeline-progress-panel card" aria-label="Preparation progress">
          <span className="timeline-panel-eyebrow">YOUR PREPARATION</span>
          <h2>Preparation journey</h2>
          <div
            className="timeline-progress-ring"
            role="progressbar"
            aria-label="Preparation progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress.percentage}
            style={{ '--timeline-progress': `${progress.percentage}%` }}
          >
            <div>
              <strong>{progress.percentage}%</strong>
              <span>complete</span>
            </div>
          </div>
          <p className="timeline-progress-count">{progress.completed} of {progress.tasks.length} tasks completed</p>
          <div className="timeline-next-step">
            <span>Next recommended step</span>
            <strong>{progress.nextTask?.title || 'No outstanding steps listed'}</strong>
          </div>
          <div className="timeline-deadline-summary">
            <CalendarDays size={16} aria-hidden="true" />
            <span>
              {overdueCount > 0 ? `${overdueCount} past listed date${overdueCount === 1 ? '' : 's'}` : 'Next listed date'}
              <strong>
                {nextDeadline
                  ? `${formatDate(nextDeadline.task.dueDate)} · ${nextDeadline.task.source === 'official-verified' ? 'officially verified' : 'unverified sample'}`
                  : 'None provided'}
              </strong>
            </span>
          </div>
          <div className="timeline-milestones">
            <h3>Preparation checklist</h3>
            {progress.tasks.length ? progress.tasks.map((task) => {
              const status = getTaskStatus(task);
              return (
                <div className={`timeline-milestone ${status}`} key={task.id}>
                  <span className="timeline-milestone-icon">
                    {status === 'done'
                      ? <CheckCircle2 size={16} aria-hidden="true" />
                      : status === 'in-progress'
                        ? <Clock3 size={16} aria-hidden="true" />
                        : <Circle size={16} aria-hidden="true" />}
                  </span>
                  <span>{task.title}</span>
                </div>
              );
            }) : (
              <p className="timeline-no-tasks">No preparation steps are available from the current opportunity data.</p>
            )}
          </div>
        </section>

        <section className="timeline-task-column" aria-labelledby="timeline-active-title">
          <div className="timeline-column-heading">
            <span className="timeline-column-icon active"><Clock3 size={17} aria-hidden="true" /></span>
            <div>
              <h2 id="timeline-active-title">In progress</h2>
              <p>Preparation steps you have started</p>
            </div>
            <span className="timeline-column-count">{inProgressTasks.length}</span>
          </div>
          {inProgressTasks.length ? inProgressTasks.map((task) => (
            <TimelineTaskCard
              key={task.id}
              task={task}
              status="in-progress"
              opportunity={activeOpportunity}
              documentRecords={documentRecords}
              onStatusChange={(status) => updateTask(task, status)}
              onUpdate={(status) => updateTask(task, status)}
              onNavigate={navigate}
            />
          )) : (
            <div className="timeline-lane-empty">
              <Circle size={18} aria-hidden="true" />
              <p>No preparation steps in progress.</p>
            </div>
          )}
        </section>

        <section className="timeline-task-column" aria-labelledby="timeline-upcoming-title">
          <div className="timeline-column-heading">
            <span className="timeline-column-icon upcoming"><FileText size={17} aria-hidden="true" /></span>
            <div>
              <h2 id="timeline-upcoming-title">Upcoming preparation</h2>
              <p>Requirements, documents, and next steps</p>
            </div>
            <span className="timeline-column-count">{upcomingTasks.length}</span>
          </div>
          {upcomingTasks.length ? upcomingTasks.map((task) => (
            <TimelineTaskCard
              key={task.id}
              task={task}
              status="todo"
              opportunity={activeOpportunity}
              documentRecords={documentRecords}
              onStatusChange={(status) => updateTask(task, status)}
              onUpdate={(status) => updateTask(task, status)}
              onNavigate={navigate}
            />
          )) : (
            <div className="timeline-lane-empty">
              <CheckCircle2 size={18} aria-hidden="true" />
              <p>No upcoming preparation steps are listed.</p>
            </div>
          )}
          {completedTasks.length > 0 && (
            <div className="timeline-completed-summary">
              <CheckCircle2 size={16} aria-hidden="true" />
              {completedTasks.length} preparation step{completedTasks.length === 1 ? '' : 's'} completed
            </div>
          )}
        </section>
      </div>
      <p className="timeline-source-note">
        <AlertCircle size={15} aria-hidden="true" />
        Listed dates and requirements depend on available opportunity data. Verify details with the official university or scholarship provider; no application is submitted from this page.
      </p>
      <OfficialApplicationLink
        opportunity={activeOpportunity}
        applied={appliedOpportunityIds.includes(activeOpportunity.id)}
        onToggleApplied={(value) => markOpportunityApplied(activeOpportunity.id, value)}
      />
    </main>
  );
}
