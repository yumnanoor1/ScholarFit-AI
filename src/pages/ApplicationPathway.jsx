import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Circle, GraduationCap } from 'lucide-react';
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

export default function ApplicationPathway() {
  const navigate = useNavigate();
  const {
    activeOpportunity,
    opportunityTaskStatuses,
    setOpportunityTaskStatus,
  } = useProfile();
  const activeOpportunityId = activeOpportunity?.id;
  const activeOpportunityKind = activeOpportunity?.kind;
  const [strategySelection, setStrategySelection] = useState(null);
  const [pathwayResult, setPathwayResult] = useState(null);
  const [error, setError] = useState('');
  const strategy = activeOpportunityId
    ? strategySelection?.opportunityId === activeOpportunityId
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

  if (!activeOpportunity) {
    return (
      <main className="page-container">
        <h1 className="page-title">Application Pathway</h1>
        <p>Select an opportunity first to view a supported application strategy.</p>
        <button className="btn btn-primary" onClick={() => navigate('/recommendations')}>Browse recommendations</button>
      </main>
    );
  }

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
    try {
      setOpportunityTaskStatus(
        activeOpportunity.id,
        getPathwayTaskId(pathway, step),
        completed ? 'done' : 'todo',
      );
      setError('');
    } catch (saveError) {
      console.error('Unable to save pathway task status.', saveError);
      setError('Pathway progress could not be saved.');
    }
  };

  return (
    <main className="page-container application-pathway-page">
      <header className="application-pathway-header">
        <div>
          <p className="application-pathway-eyebrow">SELECTED OPPORTUNITY</p>
          <h1>{getOpportunityTitle(activeOpportunity)}</h1>
          <p className="application-pathway-description">
            {activeOpportunity.university || activeOpportunity.provider || activeOpportunity.country}
          </p>
        </div>
        {strategies.length > 0 && (
          <label className="application-pathway-strategy">
            <span>Application strategy</span>
            <select value={strategy} onChange={changeStrategy}>
              {!strategies.includes(strategy) && <option value={strategy}>{strategy} (not available for this program)</option>}
              {strategies.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
        )}
      </header>
      {error && <p role="alert">{error}</p>}
      <p className="application-pathway-demo-note">Sample pathway steps only. Confirm process and document requirements with the opportunity provider. Document tracking is managed on the Documents page.</p>

      {!pathway ? (
        <section className="card">
          <p>No application pathway is currently provided for this selected opportunity and strategy.</p>
          <button className="btn btn-outline" onClick={() => navigate('/timeline')}>View available timeline tasks</button>
        </section>
      ) : (
        <>
          <div className="application-pathway-program">
            <GraduationCap size={17} aria-hidden="true" />
            <span>{getOpportunityTitle(activeOpportunity)}</span>
            <span aria-hidden="true">·</span>
            <span>{activeOpportunity.university || activeOpportunity.country}</span>
          </div>
          <div className="application-pathway-steps">
            {pathway.steps.map((step, index) => {
              const id = getPathwayTaskId(pathway, step);
              const status = statuses[id] || 'todo';
              const completed = status === 'done';
              return (
                <article className="application-pathway-step" key={id}>
                  <div className={`application-pathway-step-number${completed ? ' is-complete' : ''}`} aria-hidden="true">
                    {completed ? <CheckCircle2 size={18} /> : String(index + 1)}
                  </div>
                  <section className="application-pathway-step-card">
                    <div className="application-pathway-step-heading">
                      <div>
                        <p className="application-pathway-step-label">STEP {String(index + 1).padStart(2, '0')}</p>
                        <h2>{step.title}</h2>
                        <p className="application-pathway-step-description">{step.description}</p>
                      </div>
                      <span className={`application-pathway-status${completed ? ' is-complete' : ''}`}>
                        {completed ? <CheckCircle2 size={14} /> : <Circle size={14} />} {completed ? 'Completed' : 'To Do'}
                      </span>
                    </div>
                    <button className="btn btn-outline" onClick={() => updateStep(step, !completed)}>
                      {completed ? 'Mark To Do' : 'Mark Completed'}
                    </button>
                  </section>
                </article>
              );
            })}
          </div>
        </>
      )}
    </main>
  );
}
