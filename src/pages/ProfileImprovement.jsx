import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertCircle, ArrowRight, Check, CheckCircle2, Circle, Clock3, GraduationCap, ListChecks, Loader2, Sparkles, Target,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import { useScholarshipRecommendations } from '../hooks/useProgramEligibility';
import { apiService } from '../services/api';
import { getImprovementQuery } from '../services/opportunityApi';
import {
  getOpportunityTimelineTasks,
  getOpportunityTitle,
} from '../services/opportunityJourney';
import { getSelectedApplicationStrategy } from '../services/applicationWorkflow';
import RetryButton from '../components/common/RetryButton';

const EMPTY_TASK_STATUSES = {};
const RELATED_PREVIEW = 6;
const PRIORITIES = ['High', 'Medium', 'Low'];

const FILTERS = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'first', label: 'What should I improve first?', match: (item) => item.priority === 'High' },
  { id: 'missing', label: 'What am I missing?', match: (item) => item.result_type === 'missing_information' },
  { id: 'unmet', label: 'What don’t I meet?', match: (item) => item.result_type === 'unmet' },
  { id: 'verify', label: 'What should I verify?', match: (item) => item.result_type === 'manual_verification' },
];
const RESULT_LABELS = {
  unmet: 'Requirement not met',
  missing_information: 'Missing information',
  manual_verification: 'Verify manually',
  optional: 'Optional',
};
const ACTION_LABELS = {
  achievable: 'You can act on this',
  manual_verification: 'Needs a manual check',
  not_changeable: 'Can’t realistically change',
};
const STATUS_NOTICES = {
  'logged-out': ['Log in to see guidance based on your profile.', '/login', 'Log in'],
  'no-profile': ['Complete your profile to get personal guidance.', '/profile', 'Complete profile'],
  'not-found': ['This opportunity is no longer available.', null, null],
  error: ['Guidance could not be loaded. Please try again later.', null, null],
};

function getTaskRoute(task, opportunity) {
  if (task.kind === 'document') return '/documents';
  if (task.kind === 'pathway') return '/pathway';
  return opportunity.kind === 'scholarship' ? `/scholarships/${opportunity.id}` : `/universities/${opportunity.id}`;
}

function relatedRoute(item) {
  return item.kind === 'scholarship' ? `/scholarships/sch-db-${item.id}` : `/universities/${item.id}`;
}

function Recommendation({ item }) {
  const [showAll, setShowAll] = useState(false);
  const related = showAll ? item.related : item.related.slice(0, RELATED_PREVIEW);
  return (
    <details className="improvement-recommendation">
      <summary>
        <div className="improvement-tag-row">
          <span className={`improvement-tag is-${item.priority.toLowerCase()}`}>{item.priority} priority</span>
          <span className="improvement-tag">{RESULT_LABELS[item.result_type]}</span>
          {item.related.length > 0 && <span className="improvement-tag">{item.related.length} {item.related.length === 1 ? 'opportunity' : 'opportunities'}</span>}
        </div>
        <h4>{item.title}</h4>
        <p>{item.gap}</p>
      </summary>
      <div className="improvement-recommendation-body">
        <dl>
          <div><dt>Next step</dt><dd>{item.suggested_action}</dd></div>
          <div><dt>Why it matters</dt><dd>{item.why_it_matters}</dd></div>
          {item.requirement && <div><dt>Requirement</dt><dd>{item.requirement}</dd></div>}
          <div><dt>What we checked</dt><dd>{item.profile_information}. {item.comparison}</dd></div>
          <div><dt>Can you change it?</dt><dd>{ACTION_LABELS[item.actionability]}</dd></div>
          {item.expected_benefit && <div><dt>Expected benefit</dt><dd>{item.expected_benefit}</dd></div>}
        </dl>
        {related.length > 0 && (
          <ul className="improvement-related">
            {related.map((opportunity) => (
              <li key={`${opportunity.kind}-${opportunity.id}`}>
                <Link to={relatedRoute(opportunity)}>{opportunity.name}</Link>
                {opportunity.organization && <small>{opportunity.organization}</small>}
                <small>{opportunity.result}</small>
                {opportunity.requirement_text && <small>Record says: {opportunity.requirement_text}</small>}
              </li>
            ))}
          </ul>
        )}
        {item.related.length > RELATED_PREVIEW && (
          <button type="button" className="improvement-complete-button" onClick={() => setShowAll((value) => !value)}>
            {showAll ? 'Show fewer' : `Show all ${item.related.length}`}
          </button>
        )}
        <Link className="improvement-fix-button" to={item.action_route}>Take action <ArrowRight size={13} aria-hidden="true" /></Link>
      </div>
    </details>
  );
}

export default function ProfileImprovement() {
  const navigate = useNavigate();
  const { token, user } = useAuth();
  const userId = user?.id;
  const {
    profile,
    activeOpportunity,
    opportunityTaskStatuses,
    setOpportunityTaskStatus,
  } = useProfile();
  const activeOpportunityId = activeOpportunity?.id;
  const activeOpportunityKind = activeOpportunity?.kind;
  const selectedQuery = getImprovementQuery(activeOpportunity);
  const [scopeChoice, setScopeChoice] = useState('all');
  const [filter, setFilter] = useState('all');
  const [pathwayResult, setPathwayResult] = useState(null);
  const [guidance, setGuidance] = useState(null);
  const [error, setError] = useState('');
  const profileGaps = useScholarshipRecommendations().data?.profile_gaps || [];

  // Refetches when the saved profile, the selection or the scope changes; older responses are dropped
  const query = scopeChoice === 'selected' && selectedQuery ? selectedQuery : null;
  const requestKey = JSON.stringify([
    token || '', query, profile?.profileStatus, profile?.personalInfo, profile?.academicBackground,
    profile?.englishProficiency, profile?.studyPreferences,
  ]);
  useEffect(() => {
    let current = true;
    apiService.getProfileImprovements(query, token).then((result) => {
      if (current) setGuidance({ key: requestKey, ...result });
    });
    return () => { current = false; };
    // requestKey covers token and query
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  useEffect(() => {
    if (!activeOpportunityId || activeOpportunityKind !== 'program') return undefined;
    let current = true;
    apiService.getApplicationPathway(
      activeOpportunityId,
      getSelectedApplicationStrategy(userId, activeOpportunityId),
    ).then((result) => { if (current) setPathwayResult({ opportunityId: activeOpportunityId, value: result }); })
      .catch((loadError) => {
        console.error('Unable to load opportunity pathway for profile guidance.', loadError);
        if (current) setError('Opportunity tasks could not be loaded.');
      });
    return () => { current = false; };
  }, [userId, activeOpportunityId, activeOpportunityKind]);

  const pathway = pathwayResult && pathwayResult.opportunityId === activeOpportunity?.id
    ? pathwayResult.value
    : null;
  const taskStatuses = activeOpportunity ? opportunityTaskStatuses[activeOpportunity.id] || EMPTY_TASK_STATUSES : EMPTY_TASK_STATUSES;
  // Requirements now come from the backend guidance; these are the application steps
  const allTasks = useMemo(() => activeOpportunity
    ? getOpportunityTimelineTasks(profile, activeOpportunity, pathway)
      .filter((task) => task.kind !== 'deadline' && task.kind !== 'requirement')
      .map((task) => ({ ...task, status: taskStatuses[task.id] || task.status }))
    : [],
  [activeOpportunity, profile, pathway, taskStatuses]);
  const completedCount = allTasks.filter((task) => task.status === 'done').length;
  const completion = allTasks.length ? Math.round((completedCount / allTasks.length) * 100) : 0;

  const updateTaskStatus = (task, status) => {
    try {
      setOpportunityTaskStatus(activeOpportunity.id, task.id, status);
      setError('');
    } catch (statusError) {
      console.error('Unable to save improvement task status.', statusError);
      setError('Task progress could not be saved.');
    }
  };

  const handleTaskAction = (task) => {
    if (task.status === 'todo') updateTaskStatus(task, 'in-progress');
    navigate(getTaskRoute(task, activeOpportunity));
  };

  const statusLabel = (status) => status === 'done' ? 'Done' : status === 'in-progress' ? 'In progress' : 'To do';

  const current = guidance?.key === requestKey ? guidance : null;
  const data = current?.state === 'ok' ? current.data : null;
  const notice = current && current.state !== 'ok' ? STATUS_NOTICES[current.state] || STATUS_NOTICES.error : null;
  const activeFilter = FILTERS.find((item) => item.id === filter) || FILTERS[0];
  const visible = (data?.recommendations || []).filter(activeFilter.match);
  const groups = (data?.categories || [])
    .map((category) => ({ name: category.name, items: visible.filter((item) => item.category === category.name) }))
    .filter((group) => group.items.length > 0)
    // Items arrive sorted by priority, so the category with the most urgent one comes first
    .sort((first, second) => PRIORITIES.indexOf(first.items[0].priority) - PRIORITIES.indexOf(second.items[0].priority));

  return (
    <div className="profile-improvement-page">
      <header className="improvement-header">
        <div><h1>Profile Improvement</h1></div>
        <div className="improvement-mode-badge"><Sparkles size={15} aria-hidden="true" /> Based on your saved profile</div>
      </header>
      {error && <p className="improvement-data-warning" role="alert"><AlertCircle size={16} />{error}</p>}

      <div className="improvement-layout">
        <section className="improvement-chat-panel" aria-label="Personal improvement guidance">
          <div className="improvement-chat-heading">
            <div className="improvement-bot-avatar"><ListChecks size={20} aria-hidden="true" /></div>
            <div>
              <h2>Your improvement guidance</h2>
              {data ? <p>{data.scope.description} · {data.summary.opportunities_evaluated} checked</p> : <p>Compared with real program and scholarship requirements</p>}
            </div>
          </div>
          <div className="improvement-guidance-tools">
            {selectedQuery && (
              <div className="improvement-filter-row" role="group" aria-label="Guidance scope">
                <button type="button" className={scopeChoice === 'all' ? 'is-active' : ''} aria-pressed={scopeChoice === 'all'} onClick={() => setScopeChoice('all')}>My opportunities</button>
                <button type="button" className={scopeChoice === 'selected' ? 'is-active' : ''} aria-pressed={scopeChoice === 'selected'} onClick={() => setScopeChoice('selected')}>{getOpportunityTitle(activeOpportunity)}</button>
              </div>
            )}
            <div className="improvement-filter-row" role="group" aria-label="Filter recommendations">
              {FILTERS.map((item) => (
                <button type="button" key={item.id} className={filter === item.id ? 'is-active' : ''} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>{item.label}</button>
              ))}
            </div>
          </div>
          <div className="improvement-guidance-list" aria-live="polite">
            {!current && <p className="improvement-state" role="status"><Loader2 size={20} className="fin-spin" aria-hidden="true" /> Checking your profile…</p>}
            {notice && (
              <p className="improvement-state" role={current.state === 'error' ? 'alert' : 'status'}>
                {notice[0]} {notice[1] && <Link to={notice[1]}>{notice[2]}</Link>}
              </p>
            )}
            {current?.state === 'error' && <RetryButton />}
            {data && groups.length === 0 && (
              <p className="improvement-state" role="status">
                {data.recommendations.length === 0
                  ? 'No gaps found for the requirements FitScholars can check. Always confirm details on the official pages.'
                  : 'Nothing matches this filter.'}
              </p>
            )}
            {groups.map((group) => (
              <section className="improvement-category" key={group.name}>
                <h3>{group.name}</h3>
                {group.items.map((item) => <Recommendation key={item.id} item={item} />)}
              </section>
            ))}
          </div>
        </section>

        <aside className="improvement-task-panel" aria-label="Personalized improvement tracker">
          <div className="improvement-task-heading">
            <div className="improvement-task-title"><span><Target size={18} aria-hidden="true" /></span><div><h2>Your next steps</h2><p>{data ? data.scope.description : 'Eligibility overview'}</p></div></div>
          </div>
          {data && (
            <div className="improvement-summary-grid">
              <div><strong>{data.summary.eligible}</strong><span>Requirements met</span></div>
              <div><strong>{data.summary.not_eligible}</strong><span>Not eligible</span></div>
              <div><strong>{data.summary.missing_information}</strong><span>Missing information</span></div>
              <div><strong>{data.summary.not_evaluated}</strong><span>Verify manually</span></div>
            </div>
          )}
          {profileGaps.length > 0 && (
            <section className="improvement-missing-section">
              <h3><AlertCircle size={15} aria-hidden="true" /> Improve your recommendations</h3>
              {profileGaps.map((gap) => (
                <p className="improvement-task-empty" key={gap.field}>
                  <strong>{gap.label}:</strong> needed to check {gap.scholarships_affected} scholarship{gap.scholarships_affected === 1 ? '' : 's'}
                </p>
              ))}
              <p className="improvement-task-empty">Adding these makes your scores more accurate. It doesn't mean you'll be eligible. <Link to="/profile">Update your profile</Link></p>
            </section>
          )}
          {data && query && data.opportunities[0] && (
            <section className="improvement-missing-section">
              <h3><AlertCircle size={15} aria-hidden="true" /> Requirement results</h3>
              {[['Met', data.opportunities[0].satisfied], ['Not met', data.opportunities[0].unmet],
                ['Missing information', data.opportunities[0].missing_information], ['Verify manually', data.opportunities[0].manual_verification]]
                .filter(([, items]) => items.length > 0)
                .map(([label, items]) => <p className="improvement-task-empty" key={label}><strong>{label}:</strong> {items.map((item) => item.requirement).join(', ')}</p>)}
            </section>
          )}
          {activeOpportunity && allTasks.length > 0 && (
            <>
              <div className="improvement-progress"><div><span>Application steps</span><strong>{completedCount}/{allTasks.length}</strong></div><div className="improvement-progress-track"><span style={{ width: `${completion}%` }} /></div></div>
              <section className="improvement-tasks-section">
                <h3><GraduationCap size={15} aria-hidden="true" /> {getOpportunityTitle(activeOpportunity)}</h3>
                {allTasks.map((task, index) => {
                  const status = task.status;
                  return (
                    <article className={`improvement-task ${status === 'done' ? 'is-done' : ''}`} key={task.id}>
                      <div className="improvement-task-topline">
                        <span className="improvement-task-type optional">Step</span>
                        <span className={`improvement-task-status ${status}`}>{status === 'done' ? <CheckCircle2 size={12} /> : status === 'in-progress' ? <Clock3 size={12} /> : <Circle size={12} />}{statusLabel(status)}</span>
                      </div>
                      <h4>{index + 1}. {task.title}</h4>
                      <p>{task.reason}</p>
                      <div className="improvement-task-actions">
                        {status !== 'done' && <button type="button" className="improvement-fix-button" onClick={() => handleTaskAction(task)}>Open <ArrowRight size={13} aria-hidden="true" /></button>}
                        <button type="button" className="improvement-complete-button" onClick={() => updateTaskStatus(task, status === 'done' ? 'todo' : 'done')}>{status === 'done' ? 'Undo' : <><Check size={13} aria-hidden="true" /> Mark done</>}</button>
                      </div>
                    </article>
                  );
                })}
              </section>
            </>
          )}
        </aside>
      </div>
      <p className="improvement-page-note">
        {data?.notes[0] || 'Addressing these gaps does not guarantee admission or a scholarship.'} Confirm requirements on each official page.
      </p>
    </div>
  );
}
