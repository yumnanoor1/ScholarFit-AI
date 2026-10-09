import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);

  // Initialize authentication from localStorage.
  // No automatic/demo user is created.
  useEffect(() => {
    const storedToken = localStorage.getItem('fitscholar_token');
    const storedUser = localStorage.getItem('fitscholar_user');

    if (storedToken && storedUser) {
      try {
        const parsedUser = JSON.parse(storedUser);

        setToken(storedToken);
        setUser(parsedUser);
      } catch (error) {
        console.error('Failed to parse cached user data:', error);

        localStorage.removeItem('fitscholar_token');
        localStorage.removeItem('fitscholar_user');

        setToken(null);
        setUser(null);
      }
    } else {
      // No stored session = logged out
      setToken(null);
      setUser(null);
    }

    setLoading(false);
  }, []);

  // Temporary frontend mock login.
  // This can later be replaced with the real FastAPI API call.
  const login = async (email, password) => {
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

        setUser(mockAuthData.user);
        setToken(mockAuthData.access_token);

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

        setUser(newUser);
        setToken(mockToken);

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
    setUser(null);
    setToken(null);

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