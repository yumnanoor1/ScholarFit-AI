import { useState } from 'react';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import BrandLogo from '../components/common/BrandLogo';
import { AnimatedForm } from '../components/ui/modern-animated-sign-in';
import AuthBrandPanel from '../components/auth/AuthBrandPanel';
import { getProfileApi } from '../services/profileApi';

// Only someone with no profile yet needs the setup page
async function getHomePath({ user, token }) {
  if (user?.role === 'admin') return '/admin/scholarships';
  try {
    return (await getProfileApi(token)).exists ? '/dashboard' : '/profile-setup';
  } catch {
    return '/dashboard';
  }
}

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const requestedPath = location.state?.from?.pathname;
  const destination = typeof requestedPath === 'string' &&
    requestedPath.startsWith('/') &&
    !requestedPath.startsWith('//')
    ? requestedPath
    : null;

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // AnimatedForm has already checked required fields, email format and password length
  const handleSubmit = async () => {
    setLoading(true);
    setError('');
    setNotice('');

    try {
      const res = await login(email.trim(), password);
      if (res.success) {
        navigate(destination || await getHomePath(res), { replace: true });
      } else {
        setError(res?.error || 'Invalid credentials. Please check your email and password.');
      }
    } catch (err) {
      setError(err?.message || 'Failed to log in. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // Google sign-in needs a Google OAuth client and a backend endpoint; until then say so plainly
  const handleGoogleLogin = () => {
    setError('');
    setNotice('Google sign-in isn’t available yet. Please sign in with your email and password, or create an account.');
  };

  const handleForgotPassword = (event) => {
    event.preventDefault();
    navigate('/forgot-password', { state: { email: email.trim() } });
  };

  const fields = [
    {
      label: 'Email',
      name: 'email',
      required: true,
      type: 'email',
      placeholder: 'name@university.com',
      autoComplete: 'email',
      onChange: (event) => setEmail(event.target.value),
    },
    {
      label: 'Password',
      name: 'password',
      required: true,
      type: 'password',
      placeholder: 'Enter your password',
      autoComplete: 'current-password',
      onChange: (event) => setPassword(event.target.value),
    },
  ];

  return (
    <MotionConfig reducedMotion="user">
      <div className="tw-spacing flex min-h-[100dvh] bg-white">
        <AuthBrandPanel />

        {/* Right: sign-in form */}
        <main className="flex w-full flex-col items-center justify-center px-6 py-10 lg:w-1/2">
          <Link to="/" className="mb-8 lg:hidden" aria-label="FitScholars home">
            <BrandLogo height={56} alt="" />
          </Link>

          <AnimatedForm
            header="Welcome back"
            centerHeader
            fields={fields}
            googleLogin="Continue with Google"
            onGoogleLogin={handleGoogleLogin}
            submitButton="Sign in"
            submittingButton="Signing in…"
            isSubmitting={loading}
            errorField={error}
            onSubmit={handleSubmit}
            textVariantButton="Forgot password?"
            goTo={handleForgotPassword}
            footer={(
              <div className="flex flex-col items-center gap-3 text-sm">
                {notice && (
                  <p className="w-full rounded-md border border-(--brand-line) bg-(--brand-tint) px-3 py-2 text-(--brand-navy)" role="status">
                    {notice}
                  </p>
                )}
                <p className="text-(--color-text-muted)">
                  New to FitScholars?{' '}
                  <Link to="/register" className="font-semibold text-(--brand-blue) hover:underline">Create an account</Link>
                </p>
                <Link to="/" className="inline-flex items-center gap-1.5 text-(--color-text-muted) hover:text-(--color-dark)">
                  <ArrowLeft size={15} aria-hidden="true" /> Back to home
                </Link>
              </div>
            )}
          />
        </main>
      </div>
    </MotionConfig>
  );
}
