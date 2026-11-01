import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import { ArrowLeft, CircleCheck, CircleAlert } from 'lucide-react';
import BrandLogo from '../components/common/BrandLogo';
import AuthBrandPanel from '../components/auth/AuthBrandPanel';
import { AnimatedForm } from '../components/ui/modern-animated-sign-in';
import { resetPassword } from '../services/authApi';
import { clearStoredSession } from '../services/authSession';

function ResultPanel({ icon: Icon, tone, title, text, action }) {
  return (
    <section className="mx-auto flex w-96 flex-col gap-4 max-md:w-full" aria-live="polite">
      <span className={`grid size-14 place-items-center rounded-2xl ${tone}`} aria-hidden="true">
        <Icon size={28} />
      </span>
      <h1 className="text-3xl font-bold text-(--color-dark)">{title}</h1>
      <p className="text-sm text-(--color-text-muted)">{text}</p>
      {action}
    </section>
  );
}

const primaryLink = 'mt-2 flex h-11 w-full items-center justify-center rounded-md bg-gradient-to-br from-(--brand-blue) to-(--brand-blue-hover) font-semibold text-white';

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  // AnimatedForm has already checked both fields are present and at least 6 characters
  const handleSubmit = async () => {
    if (password !== confirmPassword) {
      setError('The two passwords don’t match.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await resetPassword(token, password);
      // The server has ended every earlier sign-in, so open tabs go back to login now
      clearStoredSession();
      setDone(true);
    } catch (err) {
      setError(err?.message || 'Could not reset your password. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  let content;
  if (!token) {
    content = (
      <ResultPanel
        icon={CircleAlert}
        tone="bg-(--color-warning-bg) text-(--color-warning)"
        title="Reset link missing"
        text="This page needs the link from your password reset email. Request a new link to continue."
        action={<Link to="/forgot-password" className={primaryLink}>Request a new link</Link>}
      />
    );
  } else if (done) {
    content = (
      <ResultPanel
        icon={CircleCheck}
        tone="bg-(--color-success-bg) text-(--color-success)"
        title="Password updated"
        text="Your password has been reset. Sign in with your new password to continue your journey."
        action={<Link to="/login" className={primaryLink}>Sign in</Link>}
      />
    );
  } else {
    content = (
      <AnimatedForm
        header="Choose a new password"
        centerHeader
        subHeader="Use at least 6 characters. You’ll sign in with this password from now on."
        fields={[
          {
            label: 'New password',
            name: 'new-password',
            required: true,
            type: 'password',
            placeholder: 'Enter a new password',
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
        ]}
        submitButton="Reset password"
        submittingButton="Saving…"
        isSubmitting={loading}
        errorField={error}
        onSubmit={handleSubmit}
        footer={(
          <div className="flex flex-col items-center gap-3 text-sm">
            {error.includes('expired') && (
              <Link to="/forgot-password" className="font-semibold text-(--brand-blue) hover:underline">Request a new reset link</Link>
            )}
            <Link to="/login" className="inline-flex items-center gap-1.5 text-(--color-text-muted) hover:text-(--color-dark)">
              <ArrowLeft size={15} aria-hidden="true" /> Back to sign in
            </Link>
          </div>
        )}
      />
    );
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="tw-spacing flex min-h-[100dvh] bg-white">
        <AuthBrandPanel />
        <main className="flex w-full flex-col items-center justify-center px-6 py-10 lg:w-1/2">
          <Link to="/" className="mb-8 lg:hidden" aria-label="FitScholars home">
            <BrandLogo height={56} alt="" />
          </Link>
          {content}
        </main>
      </div>
    </MotionConfig>
  );
}
