import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ArrowLeft } from 'lucide-react';

export default function Register() {
  const navigate = useNavigate();
  const { register } = useAuth();

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!fullName || !email || !password || !confirmPassword) {
      setError('Please fill in all required fields.');
      return;
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    if (!agreeTerms) {
      setError('You must agree to the Terms of Service and Privacy Policy.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const res = await register(fullName, email, password);
      if (res.success) {
        navigate('/dashboard');
      } else {
        setError('Failed to create account. Please try again.');
      }
    } catch (err) {
      setError('An error occurred during registration.');
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
      padding: '40px 20px'
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
        Create your account
      </h1>
      <p style={{
        fontSize: '0.92rem',
        color: 'var(--color-text-muted)',
        marginBottom: '28px',
        textAlign: 'center'
      }}>
        Start your study abroad journey today
      </p>

      {/* Centered Register Card */}
      <div style={{
        backgroundColor: '#FFFFFF',
        borderRadius: '12px',
        width: '100%',
        maxWidth: '440px',
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
          {/* Full Name Field */}
          <div className="form-group" style={{ marginBottom: '18px' }}>
            <label style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--color-dark)', marginBottom: '8px', display: 'block' }}>
              Full Name
            </label>
            <input
              type="text"
              placeholder="John Doe"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
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

          {/* Email Field */}
          <div className="form-group" style={{ marginBottom: '18px' }}>
            <label style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--color-dark)', marginBottom: '8px', display: 'block' }}>
              Email Address
            </label>
            <input
              type="email"
              placeholder="name@example.com"
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
          <div className="form-group" style={{ marginBottom: '18px' }}>
            <label style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--color-dark)', marginBottom: '8px', display: 'block' }}>
              Password
            </label>
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

          {/* Confirm Password Field */}
          <div className="form-group" style={{ marginBottom: '18px' }}>
            <label style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--color-dark)', marginBottom: '8px', display: 'block' }}>
              Confirm Password
            </label>
            <input
              type="password"
              placeholder="••••••••"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
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

          {/* Terms & Privacy Agreement Checkbox */}
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', marginBottom: '24px' }}>
            <input
              type="checkbox"
              id="terms"
              checked={agreeTerms}
              onChange={(e) => setAgreeTerms(e.target.checked)}
              style={{ width: '16px', height: '16px', marginTop: '3px', accentColor: 'var(--color-primary)', cursor: 'pointer' }}
            />
            <label htmlFor="terms" style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)', cursor: 'pointer', lineHeight: '1.4' }}>
              I agree to the{' '}
              <a href="#terms" onClick={(e) => e.preventDefault()} style={{ color: 'var(--color-primary)', textDecoration: 'none' }}>
                Terms of Service
              </a>{' '}
              and{' '}
              <a href="#privacy" onClick={(e) => e.preventDefault()} style={{ color: 'var(--color-primary)', textDecoration: 'none' }}>
                Privacy Policy
              </a>
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
            {loading ? 'Creating Account...' : 'Create Account'}
          </button>
        </form>

        <hr style={{ border: 'none', borderTop: '1px solid var(--color-border-light)', margin: '28px 0 20px 0' }} />

        {/* Login Redirect */}
        <div style={{ textAlign: 'center', fontSize: '0.88rem', color: 'var(--color-text-muted)' }}>
          Already have an account?{' '}
          <Link to="/login" style={{ color: 'var(--color-primary)', fontWeight: '700', textDecoration: 'none', display: 'block', marginTop: '4px' }}>
            Log in
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