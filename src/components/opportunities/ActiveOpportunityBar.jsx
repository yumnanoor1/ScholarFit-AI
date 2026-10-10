import { useNavigate } from 'react-router-dom';
import { ArrowRight, BriefcaseBusiness, GraduationCap, X } from 'lucide-react';
import { useProfile } from '../../context/ProfileContext';
import { getOpportunityOrganization, getOpportunityTitle } from '../../services/opportunityJourney';

export default function ActiveOpportunityBar() {
  const navigate = useNavigate();
  const {
    selectedOpportunities,
    activeOpportunity,
    activeOpportunityId,
    setActiveOpportunity,
    removeSelectedOpportunity,
    appliedOpportunityIds,
    markOpportunityApplied,
  } = useProfile();

  if (!activeOpportunity) return null;

  const isApplied = appliedOpportunityIds.includes(activeOpportunity.id);
  const OpportunityIcon = activeOpportunity.kind === 'scholarship' ? BriefcaseBusiness : GraduationCap;

  return (
    <section className="active-opportunity-bar" aria-label="Active application opportunity">
      <OpportunityIcon size={18} aria-hidden="true" />
      <div className="active-opportunity-copy">
        <span>Active opportunity</span>
        <strong>{getOpportunityTitle(activeOpportunity)}</strong>
        <small>{getOpportunityOrganization(activeOpportunity)}{activeOpportunity.country ? ` · ${activeOpportunity.country}` : ''}</small>
      </div>
      {selectedOpportunities.length > 1 && (
        <label className="active-opportunity-switch">
          <span className="sr-only">Switch active opportunity</span>
          <select value={activeOpportunityId} onChange={(event) => setActiveOpportunity(event.target.value)}>
            {selectedOpportunities.map((opportunity) => (
              <option key={opportunity.id} value={opportunity.id}>{getOpportunityTitle(opportunity)}</option>
            ))}
          </select>
        </label>
      )}
      <button
        type="button"
        className={`active-opportunity-applied ${isApplied ? 'is-applied' : ''}`}
        aria-pressed={isApplied}
        onClick={() => markOpportunityApplied(activeOpportunity.id, !isApplied)}
      >
        {isApplied ? 'Applied' : 'Mark applied'}
      </button>
      <button type="button" className="active-opportunity-open" onClick={() => navigate('/timeline')} aria-label="Open active opportunity timeline">
        <ArrowRight size={15} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="active-opportunity-remove"
        onClick={() => removeSelectedOpportunity(activeOpportunity.id)}
        aria-label={`Remove ${getOpportunityTitle(activeOpportunity)} from selected opportunities`}
        title="Remove from selected opportunities"
      >
        <X size={15} aria-hidden="true" />
      </button>
    </section>
  );
}
