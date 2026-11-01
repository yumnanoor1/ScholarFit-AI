import { useProfile } from '../../context/ProfileContext';
import { getSavedNotice } from '../../services/savedScholarshipsApi';

// Shown wherever scholarship bookmarks appear, so an unknown state never reads as "not saved"
export default function SavedStatusNotice() {
  const { savedStatus, hasSavedSnapshot, retrySavedOpportunities } = useProfile();
  const notice = getSavedNotice(savedStatus, hasSavedSnapshot);
  if (!notice) return null;
  if (notice.kind === 'loading') return <p className="saved-load-status" role="status">{notice.text}</p>;

  return (
    <p className="saved-load-error" role="alert">
      <span>{notice.text}</span>
      <button type="button" className="btn btn-outline" onClick={retrySavedOpportunities}>Try again</button>
    </p>
  );
}
