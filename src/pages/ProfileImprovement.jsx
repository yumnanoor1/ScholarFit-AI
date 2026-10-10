import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle, ArrowRight, Bot, Check, CheckCircle2, Circle, Clock3, GraduationCap, Send, Sparkles, Target,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import {
  getOpportunityTimelineTasks,
  getOpportunityTitle,
} from '../services/opportunityJourney';
import { getSelectedApplicationStrategy } from '../services/applicationWorkflow';

const suggestedQuestions = [
  'How can I improve my scholarship chances?',
  'What requirements am I missing?',
  'What should I improve first?',
];
const EMPTY_TASK_STATUSES = {};

function responseFor(prompt, profile, opportunity, tasks) {
  const name = profile.firstName || profile.name?.split(/\s+/)[0] || 'there';
  if (!opportunity) return `Select a scholarship or program first, ${name}. I can then show guidance tied to that opportunity. This is demo guidance, not a live AI assessment.`;
  const relevantTasks = tasks.filter((task) => task.kind !== 'deadline');
  const firstOpenTask = relevantTasks.find((task) => task.status !== 'done');
  const title = getOpportunityTitle(opportunity);
  if (prompt.toLowerCase().includes('missing') || prompt.toLowerCase().includes('requirement')) {
    return relevantTasks.length
      ? `For ${title}, the available data shows ${relevantTasks.length} relevant next step(s). ${relevantTasks[0].title} is ${relevantTasks[0].reason}. Sample requirements still need confirmation with the official provider.`
      : `No structured requirements are available for ${title} in the current data, so I cannot identify official gaps. Check the provider's requirements directly.`;
  }
  if (prompt.toLowerCase().includes('first') || prompt.toLowerCase().includes('priorit')) {
    return firstOpenTask
      ? `Start with ${firstOpenTask.title}. ${firstOpenTask.reason} This is based only on the selected opportunity's currently available data.`
      : `There are no outstanding improvement tasks generated from the available data for ${title}. Verify official requirements and deadlines with the provider.`;
  }
  return `For ${title}, use the opportunity-specific next steps shown beside this chat. The available information is mock/unverified and does not establish eligibility or an award. Confirm requirements, deadlines, and funding details with the provider.`;
}

function formatMessageText(text) {
  return text.split('\n').map((line, index) => (
    <span className="improvement-message-line" key={`${index}-${line}`}>{line}</span>
  ));
}

function getTaskRoute(task, opportunity) {
  if (task.kind === 'document') return '/documents';
  if (task.kind === 'requirement') return '/profile?edit=1';
  if (task.kind === 'pathway') return '/pathway';
  return opportunity.kind === 'scholarship' ? `/scholarships/${opportunity.id}` : `/universities/${opportunity.id}`;
}

export default function ProfileImprovement() {
  const navigate = useNavigate();
  const {
    profile,
    activeOpportunity,
    opportunityTaskStatuses,
    setOpportunityTaskStatus,
  } = useProfile();
  const activeOpportunityId = activeOpportunity?.id;
  const activeOpportunityKind = activeOpportunity?.kind;
  const [pathwayResult, setPathwayResult] = useState(null);
  const [question, setQuestion] = useState('');
  const [sending, setSending] = useState(false);
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState('');
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (!activeOpportunityId || activeOpportunityKind !== 'program') return undefined;
    let current = true;
    apiService.getApplicationPathway(
      activeOpportunityId,
      getSelectedApplicationStrategy(activeOpportunityId),
    ).then((result) => { if (current) setPathwayResult({ opportunityId: activeOpportunityId, value: result }); })
      .catch((loadError) => {
        console.error('Unable to load opportunity pathway for profile guidance.', loadError);
        if (current) setError('Opportunity guidance could not be loaded.');
      });
    return () => { current = false; };
  }, [activeOpportunityId, activeOpportunityKind]);

  const pathway = pathwayResult && pathwayResult.opportunityId === activeOpportunity?.id
    ? pathwayResult.value
    : null;
  const taskStatuses = activeOpportunity ? opportunityTaskStatuses[activeOpportunity.id] || EMPTY_TASK_STATUSES : EMPTY_TASK_STATUSES;
  const allTasks = useMemo(() => activeOpportunity
    ? getOpportunityTimelineTasks(profile, activeOpportunity, pathway)
      .filter((task) => task.kind !== 'deadline')
      .map((task) => ({ ...task, status: taskStatuses[task.id] || task.status }))
    : [],
  [activeOpportunity, profile, pathway, taskStatuses]);
  const completedCount = allTasks.filter((task) => task.status === 'done').length;
  const completion = allTasks.length ? Math.round((completedCount / allTasks.length) * 100) : 0;
  const unresolvedRequirements = allTasks.filter((task) => task.kind === 'requirement' && task.status !== 'done');
  const firstName = profile.firstName || profile.name?.split(/\s+/)[0] || 'there';

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages, sending]);

  const handleSend = (suggestedQuestion) => {
    const prompt = (suggestedQuestion ?? question).trim();
    if (!prompt || sending) return;
    setQuestion('');
    setMessages((current) => [...current, { id: `${Date.now()}-user`, role: 'user', text: prompt }]);
    setSending(true);
    window.setTimeout(() => {
      const reply = responseFor(prompt, profile, activeOpportunity, allTasks);
      setMessages((current) => [...current, { id: `${Date.now()}-assistant`, role: 'assistant', text: reply }]);
      setSending(false);
    }, 500);
  };

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

  return (
    <div className="profile-improvement-page">
      <header className="improvement-header">
        <div><h1>Profile Improvement</h1></div>
        <div className="improvement-mode-badge"><Sparkles size={15} aria-hidden="true" /> Demo guidance</div>
      </header>
      {error && <p className="improvement-data-warning" role="alert"><AlertCircle size={16} />{error}</p>}

      <div className="improvement-layout">
        <section className="improvement-chat-panel" aria-label="Profile improvement chat">
          <div className="improvement-chat-heading">
            <div className="improvement-bot-avatar"><Bot size={20} aria-hidden="true" /></div>
            <div>
              <h2>Opportunity Improvement Assistant</h2>
              <p><span className="improvement-demo-dot" /> Profile-based demo · not connected to an AI service</p>
              {activeOpportunity && <p>Guidance for: {getOpportunityTitle(activeOpportunity)}</p>}
            </div>
          </div>
          <div className="improvement-chat-messages" aria-live="polite">
            <article className="improvement-message assistant">
              <div className="improvement-message-avatar"><Bot size={16} aria-hidden="true" /></div>
              <div className="improvement-bubble"><p>Hi {firstName}! Select an opportunity to get guidance tied to its available requirements and application steps.</p></div>
            </article>
            {messages.map((message) => (
              <article className={`improvement-message ${message.role}`} key={message.id}>
                {message.role === 'assistant' && <div className="improvement-message-avatar"><Bot size={16} aria-hidden="true" /></div>}
                <div className="improvement-bubble">
                  <p>{formatMessageText(message.text)}</p>
                  {message.role === 'assistant' && <span className="improvement-response-label">Demo response · not AI-generated</span>}
                </div>
              </article>
            ))}
            {sending && <article className="improvement-message assistant" role="status" aria-label="Preparing demo response"><div className="improvement-message-avatar"><Bot size={16} /></div><div className="improvement-bubble improvement-typing"><span /><span /><span /></div></article>}
            <div ref={messagesEndRef} />
          </div>
          <div className="improvement-suggestions">
            <p>Try asking</p>
            <div>{suggestedQuestions.map((prompt) => <button type="button" key={prompt} disabled={sending} onClick={() => handleSend(prompt)}>{prompt}<ArrowRight size={13} aria-hidden="true" /></button>)}</div>
          </div>
          <form className="improvement-composer" onSubmit={(event) => { event.preventDefault(); handleSend(); }}>
            <label className="sr-only" htmlFor="improvement-question">Ask about your profile</label>
            <input id="improvement-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about this opportunity..." disabled={sending} />
            <button type="submit" aria-label="Send message" disabled={!question.trim() || sending}><Send size={17} aria-hidden="true" /></button>
          </form>
        </section>

        <aside className="improvement-task-panel" aria-label="Personalized improvement tracker">
          <div className="improvement-task-heading">
            <div className="improvement-task-title"><span><Target size={18} aria-hidden="true" /></span><div><h2>Your next steps</h2><p>{activeOpportunity ? getOpportunityTitle(activeOpportunity) : 'Select an opportunity first'}</p></div></div>
            <span className="improvement-task-count">{completedCount}/{allTasks.length}</span>
          </div>
          <div className="improvement-progress"><div><span>Progress</span><strong>{completion}%</strong></div><div className="improvement-progress-track"><span style={{ width: `${completion}%` }} /></div></div>
          {!activeOpportunity && <p className="improvement-task-empty">Choose a program or scholarship to see its tasks.</p>}
          {activeOpportunity && unresolvedRequirements.length > 0 && (
            <section className="improvement-missing-section">
              <h3><AlertCircle size={15} aria-hidden="true" /> Requirements to review <span>{unresolvedRequirements.length}</span></h3>
              {unresolvedRequirements.map((task) => <button type="button" className="improvement-missing-item" key={task.id} onClick={() => handleTaskAction(task)}><span>{task.title}</span><ArrowRight size={14} aria-hidden="true" /></button>)}
            </section>
          )}
          <section className="improvement-tasks-section">
            <h3><GraduationCap size={15} aria-hidden="true" /> Opportunity tasks</h3>
            {activeOpportunity && allTasks.length === 0 && <p className="improvement-task-empty">No structured requirements or supported pathway steps are available for this opportunity. Check official sources directly.</p>}
            {allTasks.map((task, index) => {
              const verifiedRequirement = task.kind === 'requirement' && task.source === 'official-verified' && task.requirement?.required;
              const tag = verifiedRequirement ? 'Required' : task.kind === 'requirement' ? 'Verify source' : 'Suggested';
              const status = task.status;
              return (
                <article className={`improvement-task ${status === 'done' ? 'is-done' : ''}`} key={task.id}>
                  <div className="improvement-task-topline">
                    <span className={`improvement-task-type ${verifiedRequirement ? 'mandatory' : 'optional'}`}>{tag}</span>
                    <span className={`improvement-task-status ${status}`}>{status === 'done' ? <CheckCircle2 size={12} /> : status === 'in-progress' ? <Clock3 size={12} /> : <Circle size={12} />}{statusLabel(status)}</span>
                  </div>
                  <h4>{index + 1}. {task.title}</h4>
                  <p>{task.reason}</p>
                  <div className="improvement-task-actions">
                    {status !== 'done' && <button type="button" className="improvement-fix-button" onClick={() => handleTaskAction(task)}>Fix Now <ArrowRight size={13} aria-hidden="true" /></button>}
                    <button type="button" className="improvement-complete-button" onClick={() => updateTaskStatus(task, status === 'done' ? 'todo' : 'done')}>{status === 'done' ? 'Undo' : <><Check size={13} aria-hidden="true" /> Mark done</>}</button>
                  </div>
                </article>
              );
            })}
          </section>
        </aside>
      </div>
      <p className="improvement-page-note">Guidance uses the selected opportunity and available sample data. Completing a task updates its task status only; it does not verify an official requirement.</p>
    </div>
  );
}
