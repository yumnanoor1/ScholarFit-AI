import { getEligibilityBadge } from '../../services/eligibilityBadges';

export default function EligibilityBadge({ status }) {
  const badge = getEligibilityBadge(status);
  return (
    <span className={`program-status is-${badge.tone}`}>
      <badge.icon size={14} aria-hidden="true" /> {badge.label}
    </span>
  );
}
