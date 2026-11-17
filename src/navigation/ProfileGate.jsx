import { Navigate, Outlet } from 'react-router-dom';
import Loader from '../components/common/Loader';
import RetryButton from '../components/common/RetryButton';
import { useProfile } from '../context/ProfileContext';
import { decideAccess } from '../services/profileAccess';

/** Decides who sees a page from the API's profile status. The real check is on every backend request. */
export default function ProfileGate({ gate = 'complete' }) {
  const { completion } = useProfile();
  const access = decideAccess(completion, gate);

  if (access === 'wait') return <Loader message="Checking your profile..." />;
  if (access === 'failed') {
    return (
      <div className="page-container profile-gate-error" role="alert">
        <h1>We couldn’t check your profile</h1>
        <p>Please check your connection and try again.</p>
        <RetryButton />
      </div>
    );
  }
  if (access !== 'allow') return <Navigate to={access} replace />;
  return <Outlet />;
}
