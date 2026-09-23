import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);

  // Initialize Auth from localStorage (FastAPI JWT persistence pattern)
  useEffect(() => {
    const storedToken = localStorage.getItem('fitscholar_token');
    const storedUser = localStorage.getItem('fitscholar_user');

    if (storedToken && storedUser) {
      try {
        setToken(storedToken);
        setUser(JSON.parse(storedUser));
      } catch (e) {
        console.error('Failed to parse cached user data', e);
        localStorage.removeItem('fitscholar_token');
        localStorage.removeItem('fitscholar_user');
      }
    } else {
      // Default initial mock session for demonstration / FYP testing
      const mockUser = {
        id: "usr_991823",
        name: "Alexander Wright",
        email: "alexander.wright@university.edu",
        role: "student"
      };
      setUser(mockUser);
      setToken("mock_jwt_token_fitscholar_2026");
    }
    setLoading(false);
  }, []);

  const login = async (email, password) => {
    setLoading(true);
    // Simulate FastAPI JWT Authentication Endpoint call
    return new Promise((resolve) => {
      setTimeout(() => {
        const mockAuthData = {
          user: {
            id: "usr_991823",
            name: email.split('@')[0] || "Alexander Wright",
            email: email,
            role: "student"
          },
          access_token: "mock_jwt_token_fitscholar_2026"
        };

        setUser(mockAuthData.user);
        setToken(mockAuthData.access_token);
        localStorage.setItem('fitscholar_token', mockAuthData.access_token);
        localStorage.setItem('fitscholar_user', JSON.stringify(mockAuthData.user));
        setLoading(false);
        resolve({ success: true, user: mockAuthData.user });
      }, 500);
    });
  };

  const register = async (name, email, password) => {
    setLoading(true);
    // Simulate FastAPI User Registration Endpoint call
    return new Promise((resolve) => {
      setTimeout(() => {
        const newUser = {
          id: `usr_${Date.now()}`,
          name: name,
          email: email,
          role: "student"
        };

        setUser(newUser);
        setToken("mock_jwt_token_fitscholar_2026");
        localStorage.setItem('fitscholar_token', "mock_jwt_token_fitscholar_2026");
        localStorage.setItem('fitscholar_user', JSON.stringify(newUser));
        setLoading(false);
        resolve({ success: true, user: newUser });
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
    <AuthContext.Provider value={{ user, token, isAuthenticated: !!user, loading, login, register, logout }}>
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