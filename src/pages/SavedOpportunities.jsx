import { AlertTriangle, Bookmark, Clock3, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useProfile } from '../context/ProfileContext';
import { useOpportunityCatalog } from '../hooks/useOpportunityCatalog';
import RetryButton from '../components/common/RetryButton';
import { getScholarshipLogo } from '../services/scholarshipLogos';
import { resolveSavedItem } from '../services/savedScholarshipsApi';
import SavedStatusNotice from '../components/opportunities/SavedStatusNotice';
import EmptyState from '../components/common/EmptyState';
import ScholarshipLogo from '../components/common/ScholarshipLogo';
import { GlowCard } from '../components/ui/spotlight-card';

export default function SavedOpportunities() {
  const navigate = useNavigate();
  const {
    savedOpportunities, savedRecords, hasSavedSnapshot, removedSaves,
    dismissRemovedSavedScholarships, savedStatus, toggleSaveOpportunity,
    selectedOpportunities, activeOpportunityId, selectOpportunity,
  } = useProfile();
  const catalog = useOpportunityCatalog();
  const savedItems = savedOpportunities
    .map((id) => resolveSavedItem(id, savedRecords, catalog.getOpportunity))
    .filter((item) => item?.kind === 'scholarship')
    .map((item) => ({
      ...item,
      title: item.name,
      organization: item.provider,
      tags: [item.type, item.degree].filter(Boolean),
      route: `/scholarships/${item.id}`,
    }));

  return (
    <div className="page-container saved-opportunities-page">
      <header className="saved-opportunities-header">
        <h1 className="page-title">Saved Scholarships <span>({savedItems.length})</span></h1>
        <p className="page-subtitle">Scholarships saved from the FitScholar catalogue.</p>
      </header>
      <SavedStatusNotice />
      {catalog.error && (
        <p className="saved-load-error" role="alert"><span>{catalog.error}</span><RetryButton /></p>
      )}
      {removedSaves.length > 0 && (
        <p className="saved-load-error" role="status">
          <span>{removedSaves.map((item) => item.name || 'A saved scholarship').join(', ')} is no longer available in the catalogue.</span>
          <button type="button" className="btn btn-outline" onClick={dismissRemovedSavedScholarships}>Dismiss</button>
        </p>
      )}
      {(savedStatus === 'loading' && !hasSavedSnapshot) || (catalog.loading && savedOpportunities.length > 0) ? (
        <p role="status">Loading saved scholarships...</p>
      ) : savedItems.length === 0 ? savedStatus === 'error' ? null : (
        <div className="saved-opportunity-empty-state">
          <EmptyState
            title="No saved scholarships"
            description="Save a scholarship to keep it here."
            actionLabel="Explore scholarships"
            onAction={() => navigate('/scholarships')}
          />
        </div>
      ) : (
        <div className="saved-opportunity-grid">
          {savedItems.map((item) => {
            const selected = selectedOpportunities.some((opportunity) => opportunity.id === item.id);
            return (
              <GlowCard as="article" customSize key={item.id} className="saved-opportunity-card">
                <div className="saved-opportunity-card-heading">
                  <ScholarshipLogo src={getScholarshipLogo(item)} size={44} />
                  <div className="saved-opportunity-title-wrap">
                    <h2>{item.title}</h2>
                    <p>{[item.organization || 'Provider not listed', item.country || 'Country not listed'].filter(Boolean).join(' · ')}</p>
                  </div>
                  <button type="button" className="saved-opportunity-bookmark" aria-label={`Remove ${item.title} from saved scholarships`} aria-pressed="true" onClick={() => toggleSaveOpportunity(item.id)}>
                    <Bookmark size={20} fill="currentColor" aria-hidden="true" />
                  </button>
                </div>
                <div className="saved-opportunity-image-wrap">
                  <img src="/images/graduation-students.jpg" alt="" aria-hidden="true" loading="lazy" decoding="async" />
                </div>
                <div className="saved-opportunity-tags">{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                {item.sourceStatus !== 'official-verified' && (
                  <p className="saved-unverified-warning"><AlertTriangle size={15} aria-hidden="true" /> This scholarship requires source verification.</p>
                )}
                <p className="saved-opportunity-deadline"><Clock3 size={15} aria-hidden="true" />{item.deadline ? `Deadline: ${item.deadline}` : 'Deadline information is not available'}</p>
                <div className="saved-opportunity-actions">
                  <button type="button" className="saved-opportunity-apply" onClick={() => selectOpportunity({ ...item, kind: 'scholarship' })}>
                    {activeOpportunityId === item.id ? 'Selected' : selected ? 'Select scholarship' : 'Prepare this scholarship'}
                  </button>
                  <button type="button" className="saved-opportunity-remove" onClick={() => navigate(item.route)}>View details</button>
                  <button type="button" className="saved-opportunity-remove" onClick={() => toggleSaveOpportunity(item.id)} aria-label={`Remove ${item.title} from saved scholarships`}>
                    <Trash2 size={15} aria-hidden="true" /> Remove
                  </button>
                </div>
              </GlowCard>
            );
          })}
        </div>
      )}
    </div>
  );
}
