import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import { ArrowLeft, MailCheck } from 'lucide-react';
import BrandLogo from '../components/common/BrandLogo';
import AuthBrandPanel from '../components/auth/AuthBrandPanel';
import { AnimatedForm } from '../components/ui/modern-animated-sign-in';
import { requestPasswordReset } from '../services/authApi';

export default function ForgotPassword() {
  const location = useLocation();
  const [email, setEmail] = useState(location.state?.email || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [sentTo, setSentTo] = useState('');

  // AnimatedForm has already checked that the email is present and well formed
  const handleSubmit = async () => {
    setLoading(true);
    setError('');
    try {
      await requestPasswordReset(email);
      setSentTo(email.trim());
    } catch (err) {
      setError(err?.message || 'Could not send the reset link. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const footer = (
    <div className="flex flex-col items-center gap-3 text-sm">
      <Link to="/login" className="inline-flex items-center gap-1.5 font-semibold text-(--brand-blue) hover:underline">
        <ArrowLeft size={15} aria-hidden="true" /> Back to sign in
      </Link>
    </div>
  );

  return (
    <MotionConfig reducedMotion="user">
      <div className="tw-spacing flex min-h-[100dvh] bg-white">
        <AuthBrandPanel />

        <main className="flex w-full flex-col items-center justify-center px-6 py-10 lg:w-1/2">
          <Link to="/" className="mb-8 lg:hidden" aria-label="FitScholars home">
            <BrandLogo height={56} alt="" />
          </Link>

          {sentTo ? (
            <section className="mx-auto flex w-96 flex-col gap-4 max-md:w-full" aria-live="polite">
              <span className="grid size-14 place-items-center rounded-2xl bg-(--brand-tint) text-(--brand-blue)" aria-hidden="true">
                <MailCheck size={28} />
              </span>
              <h1 className="text-3xl font-bold text-(--color-dark)">Check your email</h1>
              <p className="text-sm text-(--color-text-muted)">
                If an account exists for <strong className="text-(--color-dark)">{sentTo}</strong>, we’ve sent a link to reset
                your password. The link works once and expires in 30 minutes.
              </p>
              <p className="text-sm text-(--color-text-muted)">
                Didn’t get it? Check your spam folder, or{' '}
                <button
                  type="button"
                  className="font-semibold text-(--brand-blue) hover:cursor-pointer hover:underline"
                  onClick={() => setSentTo('')}
                >
                  try a different email
                </button>.
              </p>
              <Link
                to="/login"
                className="mt-2 flex h-11 w-full items-center justify-center rounded-md bg-gradient-to-br from-(--brand-blue) to-(--brand-blue-hover) font-semibold text-white"
              >
                Back to sign in
              </Link>
            </section>
          ) : (
            <AnimatedForm
              header="Forgot your password?"
              centerHeader
              fields={[
                {
                  label: 'Email',
                  name: 'email',
                  required: true,
                  type: 'email',
                  placeholder: 'name@university.com',
                  autoComplete: 'email',
                  defaultValue: email,
                  onChange: (event) => setEmail(event.target.value),
                },
              ]}
              submitButton="Send reset link"
              submittingButton="Sending…"
              isSubmitting={loading}
              errorField={error}
              onSubmit={handleSubmit}
              footer={footer}
            />
          )}
        </main>
      </div>
    </MotionConfig>
  );
}
