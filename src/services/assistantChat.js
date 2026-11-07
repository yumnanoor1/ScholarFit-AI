export const WELCOME_TEXT =
  "Hi! I'm your FitScholar AI Assistant. I can help you improve your profile, understand scholarship requirements, and decide what to do next on your study-abroad journey.";

export const WELCOME_QUESTIONS = [
  'How can I improve my profile?',
  "What's my best next action?",
  'Why am I not eligible for a scholarship?',
  'Which requirements am I missing?',
  'How can I improve my chances of getting a scholarship?',
  'What are my best scholarship matches?',
];

export const STORAGE_KEY = 'fitscholar_assistant_chat';
const MAX_STORED_MESSAGES = 30;

export const EMPTY_CONTEXT = { topic: null, scholarship_id: null, shown_actions: [] };

export function canPersistConversation(ownerId, userId) {
  return userId != null && ownerId === userId;
}

export function validateAssistantReply(reply) {
  const isReply = reply
    && typeof reply === 'object'
    && typeof reply.summary === 'string'
    && typeof reply.intent === 'string'
    && reply.context
    && Array.isArray(reply.sections)
    && Array.isArray(reply.guidance)
    && Array.isArray(reply.suggestions)
    && Array.isArray(reply.notes);
  if (!isReply) throw new Error('The assistant returned an empty or incomplete response. Please retry.');
  return reply;
}

/** Where an assistant action button goes. The financial page gets IDs only when the assistant knows them. */
export function actionNavigation(action, buildFinancialRouteState) {
  if (!action?.route || !action.route.startsWith('/')) return null;
  if (action.route === '/financial' && action.state?.scholarshipId) {
    return { path: action.route, options: { state: buildFinancialRouteState(action.state) } };
  }
  return { path: action.route, options: undefined };
}

/** Explains a failed request in words a student can act on. */
export function describeAssistantError(error) {
  if (error?.status === 429) return 'You are sending messages very quickly. Please wait a minute and try again.';
  if (error?.status === 401) return 'Your session has ended. Please sign in again.';
  if (error?.status === 403) return 'The assistant is available once your profile is complete.';
  return error?.message || 'The assistant could not answer right now.';
}

/** Keeps the conversation for the signed-in student only; nothing is stored for anyone else. */
export function loadConversation(storage, userId) {
  try {
    const saved = JSON.parse(storage.getItem(STORAGE_KEY) || 'null');
    if (saved && saved.userId === userId && Array.isArray(saved.messages)) {
      const savedContext = { ...(saved.context || {}) };
      delete savedContext.program_id;
      delete savedContext.programId;
      return { messages: saved.messages, context: { ...EMPTY_CONTEXT, ...savedContext } };
    }
  } catch {
    // an unreadable saved chat is simply a new chat
  }
  return { messages: [], context: { ...EMPTY_CONTEXT } };
}

export function saveConversation(storage, userId, messages, context) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify({ userId, messages: messages.slice(-MAX_STORED_MESSAGES), context }));
  } catch {
    // storage may be full or blocked; the chat still works
  }
}

export function clearConversation(storage) {
  try {
    storage.removeItem(STORAGE_KEY);
  } catch {
    // nothing to clear
  }
}
