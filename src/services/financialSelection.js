import { parseScholarshipId } from './opportunityApi.js';

export function isScholarshipOpportunity(opportunity) {
  return opportunity?.kind === 'scholarship' || String(opportunity?.id ?? '').startsWith('sch-');
}

function positiveInteger(value) {
  const number = Number(value);
  return value != null && value !== '' && Number.isInteger(number) && number > 0 ? number : null;
}

// Backend programs carry a numeric ID; older sample selections (univ-1 …) don't
export function getBackendProgramId(program) {
  if (!program || isScholarshipOpportunity(program)) return null;
  return positiveInteger(program._numericId ?? program.id);
}

/** Navigation state sent by the "Check Financial Feasibility" buttons. */
export function buildFinancialRouteState({ programId = null, scholarshipId = null, universityId = null } = {}) {
  return {
    programId: positiveInteger(programId),
    scholarshipId: positiveInteger(scholarshipId),
    universityId: positiveInteger(universityId),
  };
}

/**
 * Works out what the Financial Feasibility page should calculate.
 * Navigation state wins; without it the active selection is used, as when
 * the page is opened from the sidebar. A scholarship is never invented.
 */
export function resolveFinancialSelection({ routeState, activeOpportunity, selectedOpportunities = [] }) {
  const fromRoute = routeState && typeof routeState === 'object' && 'programId' in routeState;
  const candidates = [activeOpportunity, ...selectedOpportunities].filter(Boolean);

  const programId = fromRoute
    ? positiveInteger(routeState.programId)
    : getBackendProgramId(activeOpportunity) ?? candidates.map(getBackendProgramId).find(Boolean) ?? null;

  let scholarshipId;
  if (fromRoute) {
    scholarshipId = positiveInteger(routeState.scholarshipId);
  } else {
    const scholarship = isScholarshipOpportunity(activeOpportunity)
      ? activeOpportunity
      : selectedOpportunities.find((item) => parseScholarshipId(item.id) != null);
    scholarshipId = parseScholarshipId(scholarship?.id);
  }

  const program = programId
    ? candidates.find((item) => getBackendProgramId(item) === programId) || null
    : null;
  return { programId, scholarshipId: scholarshipId ?? null, universityId: fromRoute ? positiveInteger(routeState.universityId) : null, program };
}
