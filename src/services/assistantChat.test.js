import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  EMPTY_CONTEXT,
  STORAGE_KEY,
  WELCOME_QUESTIONS,
  actionNavigation,
  canPersistConversation,
  clearConversation,
  describeAssistantError,
  loadConversation,
  saveConversation,
  validateAssistantReply,
} from './assistantChat.js';
import { buildFinancialRouteState } from './financialSelection.js';
import { askAssistant } from './opportunityApi.js';

function fakeStorage() {
  const data = new Map();
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, value),
    removeItem: (key) => data.delete(key),
  };
}

test('offers the suggested questions', () => {
  assert.equal(WELCOME_QUESTIONS.length, 6);
  assert.equal(WELCOME_QUESTIONS[1], "What's my best next action?");
  assert.equal(WELCOME_QUESTIONS[5], 'What are my best scholarship matches?');
});

test('action buttons navigate to existing routes', () => {
  assert.deepEqual(actionNavigation({ label: 'x', route: '/documents' }, buildFinancialRouteState), { path: '/documents', options: undefined });
  assert.deepEqual(actionNavigation({ label: 'x', route: '/recommendations' }, buildFinancialRouteState), { path: '/recommendations', options: undefined });
  assert.equal(actionNavigation({ label: 'x', route: 'https://evil.example' }, buildFinancialRouteState), null);
  assert.equal(actionNavigation(null, buildFinancialRouteState), null);
});

test('financial action passes only a known scholarship ID', () => {
  const withIds = actionNavigation({ route: '/financial', state: { programId: 4, scholarshipId: 6 } }, buildFinancialRouteState);
  assert.deepEqual(withIds.options.state, { scholarshipId: 6 });
  const programOnly = actionNavigation({ route: '/financial', state: { programId: 4 } }, buildFinancialRouteState);
  assert.equal(programOnly.options, undefined);
  const without = actionNavigation({ route: '/financial', state: null }, buildFinancialRouteState);
  assert.equal(without.options, undefined);
});

test('conversation is kept per student and can be cleared', () => {
  const storage = fakeStorage();
  const context = { ...EMPTY_CONTEXT, topic: 'eligibility', scholarship_id: 3 };
  saveConversation(storage, 7, [{ role: 'user', text: 'hi' }], context);
  assert.equal(loadConversation(storage, 7).messages.length, 1);
  assert.equal(loadConversation(storage, 7).context.scholarship_id, 3);
  assert.equal(loadConversation(storage, 8).messages.length, 0);
  clearConversation(storage);
  assert.equal(storage.getItem(STORAGE_KEY), null);
});

test('conversation is not written until the current account history is loaded', () => {
  assert.equal(canPersistConversation(7, 7), true);
  assert.equal(canPersistConversation(7, 8), false);
  assert.equal(canPersistConversation(null, 8), false);
  assert.equal(canPersistConversation(7, null), false);
});

test('an unreadable saved conversation starts fresh', () => {
  const storage = fakeStorage();
  storage.setItem(STORAGE_KEY, '{oops');
  assert.deepEqual(loadConversation(storage, 1), { messages: [], context: EMPTY_CONTEXT });
});

test('errors are explained', () => {
  assert.match(describeAssistantError({ status: 429 }), /wait/i);
  assert.match(describeAssistantError({ status: 403 }), /profile/i);
  assert.equal(describeAssistantError({ message: 'Boom' }), 'Boom');
});

test('empty or incomplete API replies become retryable errors', () => {
  assert.throws(() => validateAssistantReply(null), /empty or incomplete response/);
  assert.throws(() => validateAssistantReply({ summary: 'partial' }), /empty or incomplete response/);
  const reply = {
    intent: 'help',
    summary: 'Hello',
    context: EMPTY_CONTEXT,
    sections: [],
    guidance: [],
    suggestions: [],
    notes: [],
  };
  assert.equal(validateAssistantReply(reply), reply);
});

test('assistant API failures retain their status for retry messaging', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 503,
    json: async () => ({ detail: 'Assistant service unavailable' }),
  });
  try {
    await assert.rejects(askAssistant('test-token', 'Hello'), (error) => {
      assert.equal(error.status, 503);
      assert.equal(error.message, 'Assistant service unavailable');
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('an empty successful API body is caught by reply validation', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => null,
  });
  try {
    const reply = await askAssistant('test-token', 'Hello');
    assert.throws(() => validateAssistantReply(reply), /empty or incomplete response/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
