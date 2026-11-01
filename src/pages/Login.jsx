import { useEffect, useState } from 'react';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import BrandLogo from '../components/common/BrandLogo';
import { AnimatedForm } from '../components/ui/modern-animated-sign-in';
import AuthBrandPanel from '../components/auth/AuthBrandPanel';
import GoogleSignInButton from '../components/auth/GoogleSignInButton';
import { getHomePath } from '../services/homePath';

const LINK_NOTICE = 'An account already uses this email. Enter its password once to link your Google account.';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, loginWithGoogle, linkGoogle } = useAuth();
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
  // Set while waiting for the password that links this Google sign-in to an existing account
  const [linkCredential, setLinkCredential] = useState(location.state?.googleLink || null);
  const [notice, setNotice] = useState(linkCredential ? LINK_NOTICE : '');

  // A credential sent over from the register page must not stay in the browser's history
  useEffect(() => {
    if (location.state?.googleLink) navigate(location.pathname, { replace: true, state: null });
  }, [location, navigate]);

  // AnimatedForm has already checked required fields, email format and password length
  const handleSubmit = async () => {
    setLoading(true);
    setError('');
    if (!linkCredential) setNotice('');

    try {
      const res = linkCredential ? await linkGoogle(linkCredential, password) : await login(email.trim(), password);
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

  const handleGoogleCredential = async (credential) => {
    setLoading(true);
    setError('');
    setNotice('Signing in with Google…');

    const res = await loginWithGoogle(credential);
    if (res.success) {
      navigate(destination || await getHomePath(res), { replace: true });
      return;
    }
    setLoading(false);
    if (res.code === 'link_required') {
      setLinkCredential(credential);
      setNotice(LINK_NOTICE);
    } else {
      setNotice('');
      setError(res.error);
    }
  };

  const handleGoogleUnavailable = () => {
    setError('');
    setNotice('Google sign-in isn’t available right now. Please sign in with your email and password.');
  };

  const cancelLink = () => {
    setLinkCredential(null);
    setError('');
    setNotice('');
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
            header={linkCredential ? 'Link your Google account' : 'Welcome back'}
            centerHeader
            fields={linkCredential ? fields.filter((field) => field.name === 'password') : fields}
            googleButton={linkCredential ? null : (
              <GoogleSignInButton
                label="Continue with Google"
                onCredential={handleGoogleCredential}
                onUnavailable={handleGoogleUnavailable}
              />
            )}
            submitButton={linkCredential ? 'Link and sign in' : 'Sign in'}
            submittingButton={linkCredential ? 'Linking…' : 'Signing in…'}
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
                {linkCredential ? (
                  <button type="button" className="font-semibold text-(--brand-blue) hover:cursor-pointer hover:underline" onClick={cancelLink}>
                    Cancel and sign in another way
                  </button>
                ) : (
                  <p className="text-(--color-text-muted)">
                    New to FitScholars?{' '}
                    <Link to="/register" className="font-semibold text-(--brand-blue) hover:underline">Create an account</Link>
                  </p>
                )}
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
