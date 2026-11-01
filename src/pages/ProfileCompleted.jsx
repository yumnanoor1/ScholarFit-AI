import { useEffect } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useProfile } from '../context/ProfileContext';
import { HOME_PATH, ONBOARDING_PATH, canUseApp } from '../services/profileAccess';
import './Profile.css';

const CONFIRMATION_MS = 2500;

export default function ProfileCompleted() {
  const navigate = useNavigate();
  const { state } = useLocation();
  const { completion } = useProfile();
  const justCompleted = Boolean(state?.justCompleted);

  useEffect(() => {
    if (!justCompleted) return undefined;
    const timer = setTimeout(() => navigate(HOME_PATH, { replace: true }), CONFIRMATION_MS);
    return () => clearTimeout(timer);
  }, [justCompleted, navigate]);

  if (!canUseApp(completion)) return <Navigate to={ONBOARDING_PATH} replace />;
  // A one-time confirmation, not a page to come back to
  if (!justCompleted) return <Navigate to={HOME_PATH} replace />;

  return (
    <div className="profile-completed-page">
      <section className="profile-completed-message">
        <CheckCircle2 size={72} strokeWidth={1.75} aria-hidden="true" />
        <h1>Your profile is complete</h1>
        <p>Everything is unlocked. You can update your profile at any time.</p>
        <button type="button" className="profile-summary-primary" onClick={() => navigate(HOME_PATH, { replace: true })}>
          Go to my dashboard
        </button>
      </section>
    </div>
  );
}
