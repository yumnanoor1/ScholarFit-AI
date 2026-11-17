import { parseScholarshipId } from './opportunityApi.js';

function isScholarship(opportunity) {
  return opportunity?.kind === 'scholarship' || parseScholarshipId(opportunity?.id) != null;
}

export function buildFinancialRouteState({ scholarshipId = null } = {}) {
  const numericId = scholarshipId == null ? null : Number(scholarshipId);
  return { scholarshipId: Number.isInteger(numericId) && numericId > 0 ? numericId : null };
}

export function resolveFinancialSelection({ routeState, activeOpportunity, selectedOpportunities = [] }) {
  const fromRoute = routeState && typeof routeState === 'object' && 'scholarshipId' in routeState;
  const candidates = [activeOpportunity, ...selectedOpportunities].filter(isScholarship);
  const selected = fromRoute
    ? routeState.scholarshipId
    : candidates[0]?.id;
  const scholarshipId = parseScholarshipId(selected) ?? (
    Number.isInteger(Number(selected)) && Number(selected) > 0 ? Number(selected) : null
  );
  return { scholarshipId };
}
