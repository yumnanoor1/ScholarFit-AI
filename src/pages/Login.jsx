import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ArrowLeft } from 'lucide-react';

export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Please fill in all required fields.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const res = await login(email, password);
      if (res.success) {
        navigate('/dashboard');
      } else {
        setError('Invalid credentials. Please check your email and password.');
      }
    } catch (err) {
      setError('Failed to log in. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      backgroundColor: 'var(--color-bg)',
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      padding: '20px'
    }}>
      
      {/* Top Logo Icon */}
      <div style={{
        width: '44px',
        height: '44px',
        borderRadius: '10px',
        backgroundColor: 'var(--color-primary)',
        color: '#FFFFFF',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontWeight: 'bold',
        fontSize: '1.3rem',
        marginBottom: '16px'
      }}>
        F
      </div>

      {/* Header Titles */}
      <h1 style={{
        fontSize: '1.8rem',
        fontWeight: '700',
        color: 'var(--color-dark)',
        marginBottom: '6px',
        textAlign: 'center'
      }}>
        Welcome back
      </h1>
      <p style={{
        fontSize: '0.92rem',
        color: 'var(--color-text-muted)',
        marginBottom: '28px',
        textAlign: 'center'
      }}>
        Log in to your student dashboard
      </p>

      {/* Centered Login Card */}
      <div style={{
        backgroundColor: '#FFFFFF',
        borderRadius: '12px',
        width: '100%',
        maxWidth: '420px',
        padding: '36px 32px',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.04)',
        border: '1px solid var(--color-border-light)'
      }}>
        {error && (
          <div style={{
            backgroundColor: '#FEF2F2',
            color: 'var(--color-danger)',
            padding: '10px 14px',
            borderRadius: '6px',
            fontSize: '0.82rem',
            marginBottom: '16px',
            border: '1px solid #FCA5A5'
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {/* Email Field */}
          <div className="form-group" style={{ marginBottom: '20px' }}>
            <label style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--color-dark)', marginBottom: '8px', display: 'block' }}>
              Email Address
            </label>
            <input
              type="email"
              placeholder="name@university.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{
                width: '100%',
                padding: '11px 14px',
                borderRadius: '6px',
                border: '1px solid var(--color-border)',
                fontSize: '0.9rem',
                outline: 'none',
                backgroundColor: '#FFFFFF'
              }}
              required
            />
          </div>

          {/* Password Field */}
          <div className="form-group" style={{ marginBottom: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <label style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--color-dark)' }}>
                Password
              </label>
              <a 
                href="#forgot" 
                onClick={(e) => { e.preventDefault(); alert("Password reset link sent to your email."); }}
                style={{ fontSize: '0.82rem', color: 'var(--color-primary)', textDecoration: 'none', fontWeight: '500' }}
              >
                Forgot password?
              </a>
            </div>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{
                width: '100%',
                padding: '11px 14px',
                borderRadius: '6px',
                border: '1px solid var(--color-border)',
                fontSize: '0.9rem',
                outline: 'none',
                backgroundColor: '#FFFFFF'
              }}
              required
            />
          </div>

          {/* Remember Me Checkbox */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '24px' }}>
            <input
              type="checkbox"
              id="remember"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              style={{ width: '16px', height: '16px', accentColor: 'var(--color-primary)', cursor: 'pointer' }}
            />
            <label htmlFor="remember" style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', cursor: 'pointer', userSelect: 'none' }}>
              Remember me for 30 days
            </label>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading}
            className="btn btn-primary"
            style={{
              width: '100%',
              padding: '12px',
              fontSize: '0.95rem',
              fontWeight: '600',
              borderRadius: '6px',
              backgroundColor: 'var(--color-primary)',
              color: '#FFFFFF',
              border: 'none',
              cursor: loading ? 'not-allowed' : 'pointer'
            }}
          >
            {loading ? 'Signing in...' : 'Sign in to FitScholar'}
          </button>
        </form>

        <hr style={{ border: 'none', borderTop: '1px solid var(--color-border-light)', margin: '28px 0 20px 0' }} />

        {/* Register Redirect */}
        <div style={{ textAlign: 'center', fontSize: '0.88rem', color: 'var(--color-text-muted)' }}>
          Don't have an account?{' '}
          <Link to="/register" style={{ color: 'var(--color-primary)', fontWeight: '700', textDecoration: 'none', display: 'block', marginTop: '4px' }}>
            Register now
          </Link>
        </div>
      </div>

      {/* Back to Home Link */}
      <Link 
        to="/" 
        style={{
          marginTop: '28px',
          fontSize: '0.85rem',
          color: 'var(--color-text-muted)',
          textDecoration: 'none',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          fontWeight: '500'
        }}
      >
        <ArrowLeft size={16} /> Back to FitScholar Home
      </Link>

    </div>
  );
}