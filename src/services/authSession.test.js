// Loads the real JSX through Vite, because node --test can't read it directly.
import { after, before, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { Buffer } from 'node:buffer';
import { fileURLToPath } from 'node:url';
import { createElement as h } from 'react';
import { renderToString } from 'react-dom/server';
import { Route, Routes, StaticRouter } from 'react-router-dom';
import { createServer } from 'vite';

const USER_A = JSON.stringify({ id: 7, email: 'a@example.com', full_name: 'Student A' });
let vite;
let session;
let AuthProvider;
let ProfileProvider;
let ProtectedRoute;
let Sidebar;

function fakeStorage() {
  const items = new Map();
  return {
    items,
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => items.set(key, String(value)),
    removeItem: (key) => items.delete(key),
  };
}

function render(path, children) {
  return renderToString(h(StaticRouter, { location: path }, h(AuthProvider, null, children)));
}

const protectedPage = () => render('/dashboard', h(Routes, null,
  h(Route, { element: h(ProtectedRoute) },
    h(Route, { path: '/dashboard', element: h('main', null, 'Private account page') }))));

before(async () => {
  vite = await createServer({
    configFile: false, // the project's CSS plugins aren't needed here and take over a minute
    envDir: fileURLToPath(new URL('.', import.meta.url)), // not the project's .env: results mustn't depend on it
    server: { middlewareMode: true, hmr: false, ws: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
    appType: 'custom',
    logLevel: 'silent',
  });
  session = await vite.ssrLoadModule('/src/services/authSession.js');
  ({ AuthProvider } = await vite.ssrLoadModule('/src/context/AuthContext.jsx'));
  ({ ProfileProvider } = await vite.ssrLoadModule('/src/context/ProfileContext.jsx'));
  ({ default: ProtectedRoute } = await vite.ssrLoadModule('/src/navigation/ProtectedRoute.jsx'));
  ({ default: Sidebar } = await vite.ssrLoadModule('/src/components/layout/Sidebar.jsx'));
});

after(async () => {
  await vite.close();
});

beforeEach(() => {
  Object.defineProperty(globalThis, 'localStorage', { value: fakeStorage(), configurable: true, writable: true });
});

test('token expiry is read from the token, and a damaged token has none', () => {
  const payload = Buffer.from(JSON.stringify({ sub: '7', exp: 1800000000 })).toString('base64url');
  assert.equal(session.getTokenExpiry(`header.${payload}.signature`), 1800000000000);
  assert.equal(session.getTokenExpiry('not-a-token'), null);
  assert.equal(session.getTokenExpiry(`header.${Buffer.from('{}').toString('base64url')}.signature`), null);
});

function replyWith(status, body) {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: status < 400, status, json: async () => body };
  };
  return { calls, stop: () => { globalThis.fetch = original; } };
}

test('Google sign-in sends only the credential', async () => {
  const { googleSignIn } = await vite.ssrLoadModule('/src/services/authApi.js');
  const reply = replyWith(200, { access_token: 'token', token_type: 'bearer' });
  assert.equal((await googleSignIn('google-credential')).access_token, 'token');
  assert.match(reply.calls[0].url, /\/auth\/google$/);
  assert.deepEqual(JSON.parse(reply.calls[0].options.body), { credential: 'google-credential' });
  reply.stop();
});

test('an unlinked account is reported by code, with a readable message', async () => {
  const { googleSignIn } = await vite.ssrLoadModule('/src/services/authApi.js');
  const reply = replyWith(409, { detail: { code: 'link_required', message: 'Enter its password once.' } });
  await assert.rejects(googleSignIn('google-credential'), (error) => error.code === 'link_required' && error.status === 409 && error.message === 'Enter its password once.');
  reply.stop();
});

test('linking sends the credential and the password', async () => {
  const { linkGoogleAccount } = await vite.ssrLoadModule('/src/services/authApi.js');
  const reply = replyWith(200, { access_token: 'token', token_type: 'bearer' });
  await linkGoogleAccount('google-credential', 'Original-1');
  assert.match(reply.calls[0].url, /\/auth\/google\/link$/);
  assert.deepEqual(JSON.parse(reply.calls[0].options.body), { credential: 'google-credential', password: 'Original-1' });
  reply.stop();
});

test('without a client ID the Google button stays as a same-sized placeholder', async () => {
  const { default: GoogleSignInButton } = await vite.ssrLoadModule('/src/components/auth/GoogleSignInButton.jsx');
  const html = renderToString(h(GoogleSignInButton, { label: 'Continue with Google', onCredential() {}, onUnavailable() {} }));
  assert.match(html, /Continue with Google/);
  assert.match(html, /h-11 w-full/);
});

function watchWith(status) {
  const original = globalThis.fetch;
  let rejected = 0;
  globalThis.fetch = async () => ({ status });
  const stop = session.watchRejectedSessions(() => { rejected += 1; });
  return { rejected: () => rejected, stop: () => { stop(); globalThis.fetch = original; } };
}

test('a refused current token ends the session', async () => {
  localStorage.setItem('fitscholar_token', 'current');
  const watch = watchWith(401);
  await fetch('/profile/', { headers: { Authorization: 'Bearer current' } });
  assert.equal(watch.rejected(), 1);
  watch.stop();
});

test('a late refusal of an older token leaves the newer sign-in alone', async () => {
  localStorage.setItem('fitscholar_token', 'newer');
  const watch = watchWith(401);
  await fetch('/profile/', { headers: { Authorization: 'Bearer older' } });
  assert.equal(watch.rejected(), 0);
  watch.stop();
});

test('failed logins and other errors do not end a session', async () => {
  localStorage.setItem('fitscholar_token', 'current');
  const refused = watchWith(401);
  await fetch('/auth/login', { method: 'POST' });
  assert.equal(refused.rejected(), 0);
  refused.stop();
  const broken = watchWith(500);
  await fetch('/profile/', { headers: { Authorization: 'Bearer current' } });
  assert.equal(broken.rejected(), 0);
  broken.stop();
});

test('session cleanup removes the sign-in and nothing else', () => {
  localStorage.setItem('fitscholar_token', 'real-token');
  localStorage.setItem('fitscholar_user', USER_A);
  localStorage.setItem('fitscholar.savedOpportunities.v1.7', '["sch-db-1"]');
  localStorage.setItem('fitscholar.savedOpportunities.v1.12', '["sch-db-2"]');
  localStorage.setItem('fitscholar.profile.v2.12', '{"name":"Student B"}');

  session.clearStoredSession();

  assert.deepEqual(session.readStoredSession(), { user: null, token: null });
  assert.deepEqual([...localStorage.items.keys()].sort(), [
    'fitscholar.profile.v2.12',
    'fitscholar.savedOpportunities.v1.12',
    'fitscholar.savedOpportunities.v1.7',
  ]);
});

test('a stored session loads with its user', () => {
  localStorage.setItem('fitscholar_token', 'real-token');
  localStorage.setItem('fitscholar_user', USER_A);
  const stored = session.readStoredSession();
  assert.equal(stored.token, 'real-token');
  assert.equal(stored.user.id, 7);
});

test('invalid stored sessions are cleared', () => {
  localStorage.setItem('fitscholar_token', 'mock_token');
  localStorage.setItem('fitscholar_user', USER_A);
  assert.deepEqual(session.readStoredSession(), { user: null, token: null });
  assert.equal(localStorage.items.size, 0);

  localStorage.setItem('fitscholar_token', 'real-token');
  localStorage.setItem('fitscholar_user', 'not json');
  const log = console.error;
  console.error = () => {};
  assert.deepEqual(session.readStoredSession(), { user: null, token: null });
  console.error = log;
  assert.equal(localStorage.items.size, 0);
});

test('a token without a user is not a session', () => {
  localStorage.setItem('fitscholar_token', 'real-token');
  assert.deepEqual(session.readStoredSession(), { user: null, token: null });
});

test('other tabs react to sign-in changes only', () => {
  assert.equal(session.isSessionChange({ key: 'fitscholar_user' }), true);
  assert.equal(session.isSessionChange({ key: null }), true); // localStorage.clear()
  assert.equal(session.isSessionChange({ key: 'fitscholar_token' }), false); // the user follows it
  assert.equal(session.isSessionChange({ key: 'fitscholar.savedOpportunities.v1.7' }), false);
});

test('a protected page never renders when signed out', () => {
  assert.doesNotMatch(protectedPage(), /Private account page/);
});

test('a protected page never renders before the session is verified', () => {
  localStorage.setItem('fitscholar_token', 'real-token');
  localStorage.setItem('fitscholar_user', USER_A);
  const html = protectedPage();
  assert.doesNotMatch(html, /Private account page/);
  assert.match(html, /Checking your session/);
});

test('the sidebar offers a keyboard-reachable Log out button', () => {
  const html = render('/dashboard', h(ProfileProvider, null, h(Sidebar)));
  assert.match(html, /<button type="button" class="sidebar-link sidebar-logout">/);
  assert.match(html, /Log out/);
});
