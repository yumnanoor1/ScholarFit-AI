import { useEffect, useState } from 'react';
import { AlertCircle, Check } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useProfile } from '../../context/ProfileContext';

/** Confirms an edit once. The flag is cleared at once so a refresh doesn't repeat it. */
export function ProfileSavedNotice() {
  const location = useLocation();
  const navigate = useNavigate();
  const [saved] = useState(() => Boolean(location.state?.profileSaved));

  useEffect(() => {
    if (location.state?.profileSaved) navigate(location.pathname, { replace: true, state: null });
  }, [location.pathname, location.state, navigate]);

  if (!saved) return null;
  return (
    <p role="status" className="profile-wizard-notice border border-emerald-200 bg-emerald-50 text-emerald-700">
      <Check size={16} aria-hidden="true" />Your profile changes have been saved.
    </p>
  );
}

/** Tells a student with a stored profile why they were sent back. A brand new account has nothing to explain. */
export function ProfileMissingNotice() {
  const { completion, hasBackendProfile } = useProfile();

  if (!hasBackendProfile || completion.complete || !completion.missing.length) return null;
  return (
    <p role="alert" className="profile-wizard-notice border border-amber-200 bg-amber-50 text-amber-800">
      <AlertCircle size={16} aria-hidden="true" />
      Your profile needs attention before you can use all features. Please complete: {completion.missing.join(', ')}.
    </p>
  );
}
