import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertCircle, ArrowRight, ListChecks, Loader2, Sparkles, Target,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import { getImprovementQuery } from '../services/opportunityApi';
import {
  buildPersonalizedGuidanceActions,
  getOpportunityTitle,
} from '../services/opportunityJourney';
import RetryButton from '../components/common/RetryButton';

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

function relatedRoute(item) {
  return `/scholarships/sch-db-${item.id}`;
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
                {opportunity.source_url && (
                  <a href={opportunity.source_url} target="_blank" rel="noopener noreferrer">Official source</a>
                )}
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
  const { token } = useAuth();
  const { profile, activeOpportunity } = useProfile();
  const selectedQuery = getImprovementQuery(activeOpportunity);
  const [scopeChoice, setScopeChoice] = useState('all');
  const [filter, setFilter] = useState('all');
  const [guidance, setGuidance] = useState(null);

  // Refetches when the saved profile, the selection or the scope changes; older responses are dropped
  const query = scopeChoice === 'selected' && selectedQuery ? selectedQuery : null;
  const requestKey = JSON.stringify([token || '', query, profile]);
  useEffect(() => {
    let current = true;
    apiService.getProfileImprovements(query, token).then((result) => {
      if (current) setGuidance({ key: requestKey, ...result });
    });
    return () => { current = false; };
    // requestKey covers token and query
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  const current = guidance?.key === requestKey ? guidance : null;
  const data = current?.state === 'ok' ? current.data : null;
  const actionPlan = useMemo(() => buildPersonalizedGuidanceActions(data), [data]);
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

      <div className="improvement-layout">
        <section className="improvement-chat-panel" aria-label="Personal improvement guidance">
          <div className="improvement-chat-heading">
            <div className="improvement-bot-avatar"><ListChecks size={20} aria-hidden="true" /></div>
            <div>
              <h2>Your improvement guidance</h2>
              {data ? <p>{data.scope.description} · {data.summary.opportunities_evaluated} checked</p> : <p>Compared with scholarship requirements and source records</p>}
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

        <aside className="improvement-task-panel" aria-label="Prioritized personalized action plan">
          <div className="improvement-task-heading">
            <div className="improvement-task-title"><span><Target size={18} aria-hidden="true" /></span><div><h2>Prioritized action plan</h2><p>{data ? data.scope.description : 'Based on your saved profile'}</p></div></div>
          </div>
          {data && (
            <div className="improvement-summary-grid">
              <div><strong>{data.summary.eligible}</strong><span>Requirements met</span></div>
              <div><strong>{data.summary.not_eligible}</strong><span>Not eligible</span></div>
              <div><strong>{data.summary.missing_information}</strong><span>Missing information</span></div>
              <div><strong>{data.summary.not_evaluated}</strong><span>Verify manually</span></div>
            </div>
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
          {data && actionPlan.length === 0 && (
            <p className="improvement-task-empty" role="status">
              No next actions were identified from the information available. Confirm requirements and deadlines on official pages.
            </p>
          )}
          {data && actionPlan.slice(0, 6).map((action, index) => (
            <article className="improvement-task" key={action.id}>
              <div className="improvement-task-topline">
                <span className="improvement-task-type optional">{action.kind}</span>
                <span className={`improvement-tag is-${action.priority.toLowerCase()}`}>{action.priority} priority</span>
              </div>
              <h4>{index + 1}. {action.title}</h4>
              <p>{action.explanation}</p>
              <p><strong>Why it matters:</strong> {action.reason}</p>
              <p><strong>Next step:</strong> {action.nextStep}</p>
              {action.requirement && <p><strong>Supporting requirement:</strong> {action.requirement}</p>}
              {action.dueDate && <p><strong>Date:</strong> {action.dueDate}</p>}
              {action.completionCondition && <p><strong>Complete when:</strong> {action.completionCondition}</p>}
              {action.sourceUrl && (
                <p><a href={action.sourceUrl} target="_blank" rel="noopener noreferrer">Official source</a></p>
              )}
              {action.related?.length > 0 && (
                <p>{action.related.map((related, relatedIndex) => (
                  <span key={`${related.kind}-${related.id}`}>
                    {relatedIndex > 0 && ', '}
                    <Link to={relatedRoute(related)}>{related.name}</Link>
                  </span>
                ))}</p>
              )}
              <div className="improvement-task-actions">
                <Link className="improvement-fix-button" to={action.route}>Open next step <ArrowRight size={13} aria-hidden="true" /></Link>
              </div>
            </article>
          ))}
          {data && actionPlan.length > 6 && (
            <p className="improvement-task-empty">
              Showing the six highest-priority actions. Review all guidance on this page or visit <Link to="/recommendations">Recommendations</Link>.
            </p>
          )}
        </aside>
      </div>
      <p className="improvement-page-note">
        {data?.notes[0] || 'Addressing these gaps does not guarantee a scholarship.'} Confirm requirements on each official page.
      </p>
    </div>
  );
}
