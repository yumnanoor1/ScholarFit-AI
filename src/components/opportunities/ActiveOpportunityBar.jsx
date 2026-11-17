import { BriefcaseBusiness, X } from 'lucide-react';
import { useProfile } from '../../context/ProfileContext';
import ScholarshipLogo from '../common/ScholarshipLogo';
import { getScholarshipLogo } from '../../services/scholarshipLogos';
import { getOpportunityOrganization, getOpportunityTitle } from '../../services/opportunityJourney';

export default function ActiveOpportunityBar() {
  const { selectedOpportunities, activeOpportunity, activeOpportunityId, setActiveOpportunity, removeSelectedOpportunity } = useProfile();

  if (!activeOpportunity || activeOpportunity.kind !== 'scholarship') return null;

  const OpportunityIcon = BriefcaseBusiness;

  return (
    <section className="active-opportunity-bar" aria-label="Selected scholarship">
      <ScholarshipLogo src={getScholarshipLogo(activeOpportunity)} size={30} fallback={<OpportunityIcon size={16} />} />
      <div className="active-opportunity-copy">
        <span>Selected scholarship</span>
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
