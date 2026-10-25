/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useState } from 'react';
import {
  loginUser,
  registerUser,
  getCurrentUser,
  normalizeUser,
} from '../services/authApi';

const AuthContext = createContext(null);

function readStoredSession() {
  const storedToken = localStorage.getItem('fitscholar_token');
  const storedUser = localStorage.getItem('fitscholar_user');

  if (!storedToken || !storedUser || storedToken.startsWith('mock_')) {
    if (storedToken && storedToken.startsWith('mock_')) {
      localStorage.removeItem('fitscholar_token');
      localStorage.removeItem('fitscholar_user');
    }
    return { user: null, token: null };
  }

  try {
    return { user: normalizeUser(JSON.parse(storedUser)), token: storedToken };
  } catch (error) {
    console.error('Failed to parse cached user data:', error);
    localStorage.removeItem('fitscholar_token');
    localStorage.removeItem('fitscholar_user');
    return { user: null, token: null };
  }
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(readStoredSession);
  const [loading, setLoading] = useState(() => Boolean(session.token));
  const { user, token } = session;

  useEffect(() => {
    let isCurrent = true;

    if (!session.token) {
      setLoading(false);
      return;
    }

    getCurrentUser(session.token)
      .then((verifiedUser) => {
        if (!isCurrent) return;
        setSession({ user: verifiedUser, token: session.token });
        localStorage.setItem('fitscholar_user', JSON.stringify(verifiedUser));
      })
      .catch((error) => {
        console.warn('Stored session is invalid or expired:', error?.message);
        if (!isCurrent) return;
        localStorage.removeItem('fitscholar_token');
        localStorage.removeItem('fitscholar_user');
        setSession({ user: null, token: null });
      })
      .finally(() => {
        if (isCurrent) {
          setLoading(false);
        }
      });

    return () => {
      isCurrent = false;
    };
  }, []);

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

  const logout = () => {
    setSession({ user: null, token: null });

    localStorage.removeItem('fitscholar_token');
    localStorage.removeItem('fitscholar_user');
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
