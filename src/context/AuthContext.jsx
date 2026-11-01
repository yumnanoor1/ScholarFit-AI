/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import {
  loginUser,
  registerUser,
  getCurrentUser,
  googleSignIn,
  linkGoogleAccount,
} from '../services/authApi';
import {
  clearStoredSession, getTokenExpiry, isSessionChange, readStoredSession, watchRejectedSessions,
} from '../services/authSession';

const AuthContext = createContext(null);
const MAX_TIMER_MS = 2 ** 31 - 1;
const RECHECK_GAP_MS = 30 * 1000;

export function AuthProvider({ children }) {
  const [session, setSession] = useState(readStoredSession);
  const [loading, setLoading] = useState(() => Boolean(session.token));
  const { user, token } = session;
  const [initialToken] = useState(() => session.token);

  // Removing the stored sign-in is what tells every other tab
  const endSession = useCallback(() => {
    clearStoredSession();
    setSession({ user: null, token: null });
    setLoading(false);
  }, []);

  useEffect(() => watchRejectedSessions(endSession), [endSession]);

  useEffect(() => {
    let isCurrent = true;

    if (!initialToken) return undefined;

    // A reply that arrives after logout or a new login must not touch the current session
    const isSessionUnchanged = () => isCurrent && localStorage.getItem('fitscholar_token') === initialToken;

    getCurrentUser(initialToken)
      .then((verifiedUser) => {
        if (!isSessionUnchanged()) return;
        setSession({ user: verifiedUser, token: initialToken });
        localStorage.setItem('fitscholar_user', JSON.stringify(verifiedUser));
      })
      .catch((error) => {
        console.warn('Stored session could not be verified:', error?.message);
        // Only a refusal ends the session. An outage keeps it, and the pages report the failure
        if (error?.status === 401 && isSessionUnchanged()) endSession();
      })
      .finally(() => {
        if (isCurrent) {
          setLoading(false);
        }
      });

    return () => {
      isCurrent = false;
    };
  }, [initialToken, endSession]);

  // Other tabs, and pages restored by the browser's back button, follow the stored session
  useEffect(() => {
    const syncSession = () => {
      const nextSession = readStoredSession();
      setSession(nextSession);
      if (!nextSession.token) setLoading(false);
    };
    const handleStorage = (event) => {
      if (isSessionChange(event)) syncSession();
    };
    const handlePageShow = (event) => {
      if (event.persisted) syncSession();
    };

    window.addEventListener('storage', handleStorage);
    window.addEventListener('pageshow', handlePageShow);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener('pageshow', handlePageShow);
    };
  }, []);

  // A sign-in that expires while the app is open ends here. Coming back to the tab or waking
  // the laptop asks the server too, in case the session was ended elsewhere
  useEffect(() => {
    if (!token) return undefined;
    const expiry = getTokenExpiry(token);
    let lastChecked = Date.now();
    const endIfExpired = () => {
      if (expiry === null || Date.now() < expiry) return false;
      endSession();
      return true;
    };
    const recheck = () => {
      if (document.visibilityState !== 'visible' || endIfExpired() || Date.now() - lastChecked < RECHECK_GAP_MS) return;
      lastChecked = Date.now();
      getCurrentUser(token).catch(() => {});
    };
    const timer = expiry === null
      ? null
      : window.setTimeout(endIfExpired, Math.min(Math.max(expiry - Date.now(), 0) + 1000, MAX_TIMER_MS));
    document.addEventListener('visibilitychange', recheck);
    window.addEventListener('focus', recheck);
    window.addEventListener('online', recheck);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', recheck);
      window.removeEventListener('focus', recheck);
      window.removeEventListener('online', recheck);
    };
  }, [token, endSession]);

  const login = async (email, password) => {
    setLoading(true);

    try {
      const tokenData = await loginUser(email, password);
      const accessToken = tokenData.access_token;
      const verifiedUser = await getCurrentUser(accessToken);

      localStorage.setItem('fitscholar_token', accessToken);
      localStorage.setItem('fitscholar_user', JSON.stringify(verifiedUser));

      setSession({ user: verifiedUser, token: accessToken });

      return {
        success: true,
        user: verifiedUser,
        token: accessToken,
      };
    } catch (err) {
      return {
        success: false,
        error: err?.message || 'Incorrect email or password.',
      };
    } finally {
      setLoading(false);
    }
  };

  const register = async (name, email, password) => {
    setLoading(true);

    try {
      await registerUser(name, email, password);

      const tokenData = await loginUser(email, password);
      const accessToken = tokenData.access_token;
      const verifiedUser = await getCurrentUser(accessToken);

      localStorage.setItem('fitscholar_token', accessToken);
      localStorage.setItem('fitscholar_user', JSON.stringify(verifiedUser));

      setSession({ user: verifiedUser, token: accessToken });

      return {
        success: true,
        user: verifiedUser,
      };
    } catch (err) {
      return {
        success: false,
        error: err?.message || 'Failed to create account. Please try again.',
      };
    } finally {
      setLoading(false);
    }
  };

  // The same session as a password login: the API's token, stored the same way, which every tab follows
  const startGoogleSession = async (requestToken) => {
    setLoading(true);

    try {
      const tokenData = await requestToken();
      const accessToken = tokenData.access_token;
      const verifiedUser = await getCurrentUser(accessToken);

      localStorage.setItem('fitscholar_token', accessToken);
      localStorage.setItem('fitscholar_user', JSON.stringify(verifiedUser));

      setSession({ user: verifiedUser, token: accessToken });

      return {
        success: true,
        user: verifiedUser,
        token: accessToken,
      };
    } catch (err) {
      return {
        success: false,
        code: err?.code,
        error: err?.message || 'Google sign-in failed. Please try again.',
      };
    } finally {
      setLoading(false);
    }
  };

  const loginWithGoogle = (credential) => startGoogleSession(() => googleSignIn(credential));

  const linkGoogle = (credential, password) => startGoogleSession(() => linkGoogleAccount(credential, password));

  const logout = () => {
    setSession({ user: null, token: null });
    setLoading(false);
    clearStoredSession();
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!user && !!token,
        loading,
        login,
        register,
        loginWithGoogle,
        linkGoogle,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }

  return context;
}
