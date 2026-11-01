import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GraduationCap, Minus, RotateCcw, Send, Trash2, X } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../context/ProfileContext';
import { apiService } from '../../services/api';
import { buildFinancialRouteState } from '../../services/financialSelection';
import { decideAccess } from '../../services/profileAccess';
import {
  EMPTY_CONTEXT,
  WELCOME_QUESTIONS,
  WELCOME_TEXT,
  actionNavigation,
  canPersistConversation,
  clearConversation,
  describeAssistantError,
  loadConversation,
  saveConversation,
  validateAssistantReply,
} from '../../services/assistantChat';
import './AssistantChat.css';

let nextId = 1;
const newId = () => `m${Date.now()}-${nextId++}`;

const KIND_LABELS = { required: 'Required', manual_check: 'Check manually', optional: 'Optional' };

function ActionButton({ action, onGo }) {
  if (!action) return null;
  return (
    <button type="button" className="assistant-action" onClick={() => onGo(action)}>
      {action.label}
    </button>
  );
}

function ReplyView({ reply, onGo, onAsk }) {
  return (
    <div className="assistant-reply">
      <div className="assistant-reply-intro">
        {reply.title && <h3 className="assistant-reply-title">{reply.title}</h3>}
        <p className="assistant-reply-summary">{reply.summary}</p>
      </div>
      {(reply.priority || reply.deadline) && (
        <div className="assistant-meta">
          {reply.priority && <span className={`assistant-badge is-${reply.priority.toLowerCase()}`}>{reply.priority} priority</span>}
          {reply.deadline && <span className="assistant-badge">Deadline {reply.deadline}</span>}
        </div>
      )}
      {reply.guidance.length > 0 && (
        <section className="assistant-guidance">
          <div className="assistant-section-heading">
            <h4>Profile guidance</h4>
            <span>{reply.guidance.length} {reply.guidance.length === 1 ? 'item' : 'items'}</span>
          </div>
          <div className="assistant-guidance-list">
            {reply.guidance.map((item) => (
              <article className="assistant-card" key={item.id}>
                <div className="assistant-card-head">
                  <div>
                    <h5>{item.title}</h5>
                    <span className={`assistant-kind is-${item.kind}`}>{KIND_LABELS[item.kind]}</span>
                  </div>
                  <span className={`assistant-badge is-${item.priority.toLowerCase()}`}>{item.priority}</span>
                </div>
                <dl className="assistant-details">
                  <div><dt>Your status</dt><dd>{item.status}</dd></div>
                  {item.target && <div><dt>Target</dt><dd>{item.target}</dd></div>}
                  <div><dt>Why it matters</dt><dd>{item.why}</dd></div>
                  <div><dt>Next step</dt><dd>{item.steps}</dd></div>
                  {item.benefit && <div><dt>Expected benefit</dt><dd>{item.benefit}</dd></div>}
                </dl>
                <ActionButton action={item.action} onGo={onGo} />
              </article>
            ))}
          </div>
        </section>
      )}
      {reply.sections.map((section) => (
        <section className="assistant-response-section" key={section.heading}>
          <h4>{section.heading}</h4>
          <ul>{section.items.map((text) => <li key={text}>{text}</li>)}</ul>
        </section>
      ))}
      {reply.action && (
        <div className="assistant-reply-actions">
          <ActionButton action={reply.action} onGo={onGo} />
        </div>
      )}
      {reply.notes.length > 0 && <p className="assistant-note">{reply.notes.join(' ')}</p>}
      {reply.suggestions.length > 0 && (
        <section className="assistant-followups">
          <h4>Continue the conversation</h4>
          <div className="assistant-chips">
            {reply.suggestions.map((text) => (
              <button type="button" key={text} onClick={() => onAsk(text)}>{text}</button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default function AssistantChat() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { completion } = useProfile();
  const allowed = user?.role !== 'admin' && decideAccess(completion, 'complete') === 'allow';

  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [context, setContext] = useState(EMPTY_CONTEXT);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [conversationOwner, setConversationOwner] = useState(null);
  const listRef = useRef(null);
  const inputRef = useRef(null);
  const triggerRef = useRef(null);
  const [windowTop, setWindowTop] = useState(72);
  const userId = user?.id ?? null;

  useLayoutEffect(() => {
    const navbar = triggerRef.current?.closest('.app-navbar');
    if (!navbar) return undefined;
    const updatePosition = () => setWindowTop(Math.ceil(navbar.getBoundingClientRect().bottom + 8));
    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    const observer = new ResizeObserver(updatePosition);
    observer.observe(navbar);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const saved = loadConversation(window.sessionStorage, userId);
    setMessages(saved.messages);
    setContext(saved.context);
    setConversationOwner(userId);
  }, [userId]);

  useEffect(() => {
    if (canPersistConversation(conversationOwner, userId)) {
      saveConversation(window.sessionStorage, userId, messages, context);
    }
  }, [messages, context, userId, conversationOwner]);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, sending, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const send = useCallback(async (text, { retryOf } = {}) => {
    const question = text.trim();
    if (!question || sending) return;
    setDraft('');
    setSending(true);
    setMessages((current) => [
      ...current.filter((message) => message.id !== retryOf),
      ...(retryOf ? [] : [{ id: newId(), role: 'user', text: question }]),
    ]);
    try {
      const reply = validateAssistantReply(await apiService.askAssistant(question, context));
      setContext(reply.context);
      setMessages((current) => [...current, { id: newId(), role: 'assistant', reply }]);
    } catch (error) {
      setMessages((current) => [...current, { id: newId(), role: 'error', text: describeAssistantError(error), retryText: question }]);
    } finally {
      setSending(false);
    }
  }, [context, sending]);

  const go = useCallback((action) => {
    const target = actionNavigation(action, buildFinancialRouteState);
    if (!target) return;
    navigate(target.path, target.options);
    if (window.matchMedia?.('(max-width: 640px)').matches) setOpen(false);
  }, [navigate]);

  const clear = () => {
    clearConversation(window.sessionStorage);
    setMessages([]);
    setContext(EMPTY_CONTEXT);
  };

  if (!allowed) return null;

  return (
    <div className="assistant-root">
      <section
        className={`assistant-window${open ? ' is-open' : ''}`}
        id="fitscholar-assistant-window"
        style={{ top: `${windowTop}px`, '--assistant-window-top': `${windowTop}px` }}
        role="dialog"
        aria-label="FitScholar AI Assistant"
        aria-hidden={!open}
      >
        <header className="assistant-header">
          <span className="assistant-avatar"><GraduationCap size={18} /></span>
          <div>
            <strong>FitScholar AI Assistant</strong>
            <small>Based on your saved profile</small>
          </div>
          <div className="assistant-tools">
            <button type="button" onClick={clear} aria-label="Clear conversation" title="Clear conversation" disabled={!messages.length}><Trash2 size={16} /></button>
            <button type="button" onClick={() => setOpen(false)} aria-label="Minimize assistant" title="Minimize"><Minus size={16} /></button>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close assistant" title="Close"><X size={16} /></button>
          </div>
        </header>

        <div className="assistant-messages" ref={listRef} aria-live="polite">
          <div className="assistant-welcome">
            <span className="assistant-eyebrow">YOUR STUDY-ABROAD COPILOT</span>
            <p>{WELCOME_TEXT}</p>
            {messages.length === 0 && (
              <div className="assistant-suggested">
                <h3>Suggested questions</h3>
                <div className="assistant-chips is-suggested">
                  {WELCOME_QUESTIONS.map((text) => (
                    <button type="button" key={text} onClick={() => send(text)}>{text}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
          {messages.map((message) => (
            <div key={message.id} className={`assistant-message-row is-${message.role}`}>
              {message.role !== 'user' && <span className="assistant-message-avatar" aria-hidden="true"><GraduationCap size={15} /></span>}
              <div className={`assistant-bubble is-${message.role}`}>
                {message.role === 'assistant' ? (
                  <ReplyView reply={message.reply} onGo={go} onAsk={send} />
                ) : (
                  <p>{message.text}</p>
                )}
                {message.role === 'error' && (
                  <button type="button" className="assistant-action" onClick={() => send(message.retryText, { retryOf: message.id })}>
                    <RotateCcw size={14} /> Retry
                  </button>
                )}
              </div>
            </div>
          ))}
          {sending && (
            <div className="assistant-message-row is-assistant" aria-label="The assistant is typing">
              <span className="assistant-message-avatar" aria-hidden="true"><GraduationCap size={15} /></span>
              <div className="assistant-bubble is-assistant assistant-typing-bubble">
                <span className="assistant-typing"><i /><i /><i /></span>
              </div>
            </div>
          )}
        </div>

        <form
          className="assistant-form"
          onSubmit={(event) => { event.preventDefault(); send(draft); }}
        >
          <input
            ref={inputRef}
            value={draft}
            maxLength={500}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask about your profile or scholarships"
            aria-label="Your question"
          />
          <button type="submit" disabled={sending || !draft.trim()} aria-label="Send"><Send size={16} /></button>
        </form>
      </section>

      <button
        ref={triggerRef}
        type="button"
        className="assistant-navbar-trigger"
        onClick={() => setOpen(true)}
        aria-label="Open FitScholar AI Assistant"
        title="FitScholar AI Assistant"
        aria-expanded={open}
        aria-controls="fitscholar-assistant-window"
      >
        <GraduationCap size={24} />
      </button>
    </div>
  );
}
