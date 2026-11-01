import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Modal from '../components/common/Modal';
import BrandLogo from '../components/common/BrandLogo';
import AuthBrandPanel from '../components/auth/AuthBrandPanel';
import { AnimatedForm } from '../components/ui/modern-animated-sign-in';

const POLICY_TEXT = {
  terms: 'FitScholars helps you find and compare study-abroad programs and scholarships. Eligibility results are guidance based on published requirements, not an admission decision. Always confirm requirements, costs and deadlines with the official university or provider. FitScholars does not submit applications for you.',
  privacy: 'Your account (name, email) and the academic profile you enter are stored in the FitScholars database so we can match you with programs. Your password is stored only as a secure hash. We use your email for account messages such as password resets.',
};

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
  const [notice, setNotice] = useState('');
  const [policy, setPolicy] = useState(null);

  // AnimatedForm has already checked required fields, email format and password length
  const handleSubmit = async () => {
    setNotice('');
    if (password !== confirmPassword) {
      setError('The two passwords don’t match.');
      return;
    }
    if (!agreeTerms) {
      setError('Please agree to the Terms of Service and Privacy Policy.');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const res = await register(fullName.trim(), email.trim(), password);
      if (res.success) {
        navigate('/profile-setup');
      } else {
        setError(res?.error || 'Failed to create account. Please try again.');
      }
    } catch (err) {
      setError(err?.message || 'An error occurred during registration.');
    } finally {
      setLoading(false);
    }
  };

  // Google sign-up needs a Google OAuth client and a backend endpoint; until then say so plainly
  const handleGoogleRegister = () => {
    setError('');
    setNotice('Google sign-up isn’t available yet. Please create your account with your email and a password.');
  };

  const fields = [
    {
      label: 'Full name',
      name: 'full-name',
      required: true,
      type: 'text',
      placeholder: 'e.g. Ayesha Khan',
      autoComplete: 'name',
      onChange: (event) => setFullName(event.target.value),
    },
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
      placeholder: 'At least 6 characters',
      autoComplete: 'new-password',
      onChange: (event) => setPassword(event.target.value),
    },
    {
      label: 'Confirm password',
      name: 'confirm-password',
      required: true,
      type: 'password',
      placeholder: 'Enter it again',
      autoComplete: 'new-password',
      onChange: (event) => setConfirmPassword(event.target.value),
    },
  ];

  const termsCheckbox = (
    <label className="flex items-start gap-2.5 text-sm text-(--color-text-muted)">
      <input
        type="checkbox"
        checked={agreeTerms}
        onChange={(event) => setAgreeTerms(event.target.checked)}
        className="mt-0.5 size-4 shrink-0 cursor-pointer accent-(--brand-blue)"
      />
      <span>
        I agree to the{' '}
        <button type="button" className="font-semibold text-(--brand-blue) hover:cursor-pointer hover:underline" onClick={() => setPolicy('terms')}>
          Terms of Service
        </button>{' '}
        and{' '}
        <button type="button" className="font-semibold text-(--brand-blue) hover:cursor-pointer hover:underline" onClick={() => setPolicy('privacy')}>
          Privacy Policy
        </button>
      </span>
    </label>
  );

  return (
    <MotionConfig reducedMotion="user">
      <div className="tw-spacing flex min-h-[100dvh] bg-white">
        <AuthBrandPanel />

        <main className="flex w-full flex-col items-center justify-center px-6 py-10 lg:w-1/2">
          <Link to="/" className="mb-8 lg:hidden" aria-label="FitScholars home">
            <BrandLogo height={56} alt="" />
          </Link>

          <AnimatedForm
            header="Create your account"
            centerHeader
            fields={fields}
            googleLogin="Continue with Google"
            onGoogleLogin={handleGoogleRegister}
            beforeSubmit={termsCheckbox}
            submitButton="Create account"
            submittingButton="Creating account…"
            isSubmitting={loading}
            errorField={error}
            onSubmit={handleSubmit}
            footer={(
              <div className="flex flex-col items-center gap-3 text-sm">
                {notice && (
                  <p className="w-full rounded-md border border-(--brand-line) bg-(--brand-tint) px-3 py-2 text-(--brand-navy)" role="status">
                    {notice}
                  </p>
                )}
                <p className="text-(--color-text-muted)">
                  Already have an account?{' '}
                  <Link to="/login" className="font-semibold text-(--brand-blue) hover:underline">Sign in</Link>
                </p>
                <Link to="/" className="inline-flex items-center gap-1.5 text-(--color-text-muted) hover:text-(--color-dark)">
                  <ArrowLeft size={15} aria-hidden="true" /> Back to home
                </Link>
              </div>
            )}
          />
        </main>
      </div>

      <Modal
        isOpen={Boolean(policy)}
        onClose={() => setPolicy(null)}
        title={policy === 'terms' ? 'Terms of Service' : 'Privacy Policy'}
      >
        <p style={{ color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
          {policy ? POLICY_TEXT[policy] : ''}
        </p>
      </Modal>
    </MotionConfig>
  );
}
