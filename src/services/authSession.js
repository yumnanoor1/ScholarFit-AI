import { normalizeUser } from './authApi';

const TOKEN_KEY = 'fitscholar_token';
const USER_KEY = 'fitscholar_user';

/** Removes the sign-in only. Each student's saved data stays under their own keys. */
export function clearStoredSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function readStoredSession() {
  const storedToken = localStorage.getItem(TOKEN_KEY);
  const storedUser = localStorage.getItem(USER_KEY);

  if (!storedToken || !storedUser || storedToken.startsWith('mock_')) {
    if (storedToken && storedToken.startsWith('mock_')) clearStoredSession();
    return { user: null, token: null };
  }

  try {
    return { user: normalizeUser(JSON.parse(storedUser)), token: storedToken };
  } catch (error) {
    console.error('Failed to parse cached user data:', error);
    clearStoredSession();
    return { user: null, token: null };
  }
}

/** When a sign-in token expires, in milliseconds, or null when it can't be read. */
export function getTokenExpiry(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return Number.isFinite(payload.exp) ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

/**
 * Calls onRejected when the API refuses the token this browser is signed in with.
 * A late refusal of an older token is ignored, so it can't end a newer sign-in.
 * Returns a function that stops watching.
 */
export function watchRejectedSessions(onRejected) {
  const originalFetch = globalThis.fetch;
  const guardedFetch = async (input, init) => {
    const response = await originalFetch(input, init);
    if (response.status === 401) {
      const sentWith = new Headers(init?.headers).get('Authorization');
      if (sentWith && sentWith === `Bearer ${localStorage.getItem(TOKEN_KEY)}`) onRejected();
    }
    return response;
  };
  globalThis.fetch = guardedFetch;
  return () => {
    if (globalThis.fetch === guardedFetch) globalThis.fetch = originalFetch;
  };
}

/** True for a storage event from another tab that signed in or out. The user is written last. */
export function isSessionChange(event) {
  return event.key === USER_KEY || event.key === null;
}
