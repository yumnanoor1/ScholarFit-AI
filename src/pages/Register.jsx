import { useState } from 'react';
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
  const [googleLoading, setGoogleLoading] = useState(false);
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
        navigate('/profile-setup');
      } else {
        setError('Failed to create account. Please try again.');
      }
    } catch {
      setError('An error occurred during registration.');
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleRegister = async () => {
    setGoogleLoading(true);
    setError('');

    try {
      // Connect your Google authentication function here.
      // Example:
      // const res = await registerWithGoogle();
      // if (res.success) navigate('/profile-setup');

      // Temporary placeholder
      alert('Google Sign-Up will be connected here.');
    } catch {
      setError('Failed to sign up with Google. Please try again.');
    } finally {
      setGoogleLoading(false);
    }
  };

  return (
    <div
      style={{
        backgroundColor: 'var(--color-bg)',
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '40px 20px'
      }}
    >

      {/* Top Logo Icon */}
      <div
        style={{
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
        }}
      >
        F
      </div>

      {/* Header Titles */}
      <h1
        style={{
          fontSize: '1.8rem',
          fontWeight: '700',
          color: 'var(--color-dark)',
          marginBottom: '6px',
          textAlign: 'center'
        }}
      >
        Create your account
      </h1>

      <p
        style={{
          fontSize: '0.92rem',
          color: 'var(--color-text-muted)',
          marginBottom: '28px',
          textAlign: 'center'
        }}
      >
        Start your study abroad journey today
      </p>

      {/* Register Card */}
      <div
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: '12px',
          width: '100%',
          maxWidth: '440px',
          padding: '36px 32px',
          boxShadow: '0 4px 20px rgba(0, 0, 0, 0.04)',
          border: '1px solid var(--color-border-light)'
        }}
      >

        {/* Error Message */}
        {error && (
          <div
            style={{
              backgroundColor: '#FEF2F2',
              color: 'var(--color-danger)',
              padding: '10px 14px',
              borderRadius: '6px',
              fontSize: '0.82rem',
              marginBottom: '16px',
              border: '1px solid #FCA5A5'
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>

          {/* Full Name */}
          <div style={{ marginBottom: '18px' }}>
            <label
              style={{
                fontSize: '0.85rem',
                fontWeight: '600',
                color: 'var(--color-dark)',
                marginBottom: '8px',
                display: 'block'
              }}
            >
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

          {/* Email */}
          <div style={{ marginBottom: '18px' }}>
            <label
              style={{
                fontSize: '0.85rem',
                fontWeight: '600',
                color: 'var(--color-dark)',
                marginBottom: '8px',
                display: 'block'
              }}
            >
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

          {/* Password */}
          <div style={{ marginBottom: '18px' }}>
            <label
              style={{
                fontSize: '0.85rem',
                fontWeight: '600',
                color: 'var(--color-dark)',
                marginBottom: '8px',
                display: 'block'
              }}
            >
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

          {/* Confirm Password */}
          <div style={{ marginBottom: '18px' }}>
            <label
              style={{
                fontSize: '0.85rem',
                fontWeight: '600',
                color: 'var(--color-dark)',
                marginBottom: '8px',
                display: 'block'
              }}
            >
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

          {/* Terms & Privacy */}
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '10px',
              marginBottom: '24px'
            }}
          >
            <input
              type="checkbox"
              id="terms"
              checked={agreeTerms}
              onChange={(e) => setAgreeTerms(e.target.checked)}
              style={{
                width: '16px',
                height: '16px',
                marginTop: '3px',
                accentColor: 'var(--color-primary)',
                cursor: 'pointer'
              }}
            />

            <label
              htmlFor="terms"
              style={{
                fontSize: '0.82rem',
                color: 'var(--color-text-muted)',
                cursor: 'pointer',
                lineHeight: '1.4'
              }}
            >
              I agree to the{' '}
              <a
                href="#terms"
                onClick={(e) => e.preventDefault()}
                style={{
                  color: 'var(--color-primary)',
                  textDecoration: 'none'
                }}
              >
                Terms of Service
              </a>{' '}
              and{' '}
              <a
                href="#privacy"
                onClick={(e) => e.preventDefault()}
                style={{
                  color: 'var(--color-primary)',
                  textDecoration: 'none'
                }}
              >
                Privacy Policy
              </a>
            </label>
          </div>

          {/* Create Account */}
          <button
            type="submit"
            disabled={loading || googleLoading}
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

        {/* OR Divider */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            margin: '24px 0'
          }}
        >
          <div
            style={{
              flex: 1,
              height: '1px',
              backgroundColor: 'var(--color-border-light)'
            }}
          />

          <span
            style={{
              fontSize: '0.78rem',
              color: 'var(--color-text-muted)',
              fontWeight: '500'
            }}
          >
            OR
          </span>

          <div
            style={{
              flex: 1,
              height: '1px',
              backgroundColor: 'var(--color-border-light)'
            }}
          />
        </div>

        {/* Continue with Google */}
        <button
          type="button"
          onClick={handleGoogleRegister}
          disabled={loading || googleLoading}
          style={{
            width: '100%',
            padding: '11px 14px',
            fontSize: '0.92rem',
            fontWeight: '600',
            borderRadius: '6px',
            backgroundColor: '#FFFFFF',
            color: 'var(--color-dark)',
            border: '1px solid var(--color-border)',
            cursor: googleLoading ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '10px'
          }}
        >
          {/* Google Icon */}
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              fill="#4285F4"
              d="M21.35 12.27c0-.78-.07-1.53-.22-2.27H12v4.3h5.24a4.48 4.48 0 0 1-1.94 2.94v2.45h3.14c1.84-1.7 2.91-4.2 2.91-7.42z"
            />
            <path
              fill="#34A853"
              d="M12 21.6c2.63 0 4.84-.87 6.45-2.35l-3.14-2.45c-.87.58-1.98.92-3.31.92-2.54 0-4.69-1.72-5.46-4.03H3.3v2.53A9.74 9.74 0 0 0 12 21.6z"
            />
            <path
              fill="#FBBC05"
              d="M6.54 13.69A5.84 5.84 0 0 1 6.23 12c0-.59.1-1.16.31-1.69V7.78H3.3A9.74 9.74 0 0 0 2.25 12c0 1.57.38 3.05 1.05 4.22l3.24-2.53z"
            />
            <path
              fill="#EA4335"
              d="M12 6.28c1.43 0 2.72.49 3.73 1.45l2.8-2.8C16.83 3.39 14.63 2.4 12 2.4a9.74 9.74 0 0 0-8.7 5.38l3.24 2.53C7.31 8 9.46 6.28 12 6.28z"
            />
          </svg>

          {googleLoading
            ? 'Connecting to Google...'
            : 'Continue with Google'}
        </button>

        <hr
          style={{
            border: 'none',
            borderTop: '1px solid var(--color-border-light)',
            margin: '28px 0 20px 0'
          }}
        />

        {/* Login Redirect */}
        <div
          style={{
            textAlign: 'center',
            fontSize: '0.88rem',
            color: 'var(--color-text-muted)'
          }}
        >
          Already have an account?{' '}

          <Link
            to="/login"
            style={{
              color: 'var(--color-primary)',
              fontWeight: '700',
              textDecoration: 'none',
              display: 'block',
              marginTop: '4px'
            }}
          >
            Log in
          </Link>
        </div>

      </div>

      {/* Back to Home */}
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
        <ArrowLeft size={16} />
        Back to FitScholar Home
      </Link>

    </div>
  );
}