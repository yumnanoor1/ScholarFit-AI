/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState } from 'react';

const AuthContext = createContext(null);

function readStoredSession() {
  const storedToken = localStorage.getItem('fitscholar_token');
  const storedUser = localStorage.getItem('fitscholar_user');

  if (!storedToken || !storedUser) return { user: null, token: null };

  try {
    return { user: JSON.parse(storedUser), token: storedToken };
  } catch (error) {
    console.error('Failed to parse cached user data:', error);
    localStorage.removeItem('fitscholar_token');
    localStorage.removeItem('fitscholar_user');
    return { user: null, token: null };
  }
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(readStoredSession);
  const [loading, setLoading] = useState(false);
  const { user, token } = session;

  // Temporary frontend mock login.
  // This can later be replaced with the real FastAPI API call.
  const login = async (email, password) => {
    void password;
    setLoading(true);

    return new Promise((resolve) => {
      setTimeout(() => {
        const mockAuthData = {
          user: {
            id: `usr_${Date.now()}`,
            name: email.split('@')[0] || 'User',
            email: email,
            role: 'student',
          },
          access_token: `mock_token_${Date.now()}`,
        };

        setSession({ user: mockAuthData.user, token: mockAuthData.access_token });

        localStorage.setItem(
          'fitscholar_token',
          mockAuthData.access_token
        );

        localStorage.setItem(
          'fitscholar_user',
          JSON.stringify(mockAuthData.user)
        );

        setLoading(false);

        resolve({
          success: true,
          user: mockAuthData.user,
        });
      }, 500);
    });
  };

  // Temporary frontend mock registration.
  // This can later be replaced with the real FastAPI API call.
  const register = async (name, email, password) => {
    void password;
    setLoading(true);

    return new Promise((resolve) => {
      setTimeout(() => {
        const newUser = {
          id: `usr_${Date.now()}`,
          name: name,
          email: email,
          role: 'student',
        };

        const mockToken = `mock_token_${Date.now()}`;

        setSession({ user: newUser, token: mockToken });

        localStorage.setItem(
          'fitscholar_token',
          mockToken
        );

        localStorage.setItem(
          'fitscholar_user',
          JSON.stringify(newUser)
        );

        setLoading(false);

        resolve({
          success: true,
          user: newUser,
        });
      }, 500);
    });
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