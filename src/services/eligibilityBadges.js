import { AlertTriangle, CheckCircle2, CircleHelp, XCircle } from 'lucide-react';

// Shared scholarship eligibility labels and colors
export const ELIGIBILITY_BADGES = {
  satisfied: { label: 'Eligible', tone: 'success', icon: CheckCircle2 },
  'missing-information': { label: 'Profile info missing', tone: 'warning', icon: AlertTriangle },
  'not-satisfied': { label: 'Not eligible', tone: 'danger', icon: XCircle },
  'awaiting-verification': { label: 'Verify manually', tone: 'neutral', icon: CircleHelp },
};

// "Best Match" order: met requirements first, unmet requirements last
export const ELIGIBILITY_SORT_ORDER = {
  satisfied: 0,
  'missing-information': 1,
  'awaiting-verification': 2,
  'not-satisfied': 3,
};

export function getEligibilityBadge(status) {
  return ELIGIBILITY_BADGES[status] || ELIGIBILITY_BADGES['awaiting-verification'];
}

export function getEligibilityLabel(status) {
  return getEligibilityBadge(status).label;
}

// Recommendation categories: never green unless the student is confirmed eligible
const CATEGORY_TONES = { strong: 'success', good: 'success', possible: 'warning', needs_verification: 'neutral' };

export function getCategoryTone(category) {
  return CATEGORY_TONES[category] || 'neutral';
}

/** Why a scholarship left the recommendations, in a short phrase. */
export function getExclusionLabel(recommendation) {
  const labels = { not_eligible: 'Not eligible', closed: 'Applications closed' };
  return (recommendation?.exclusions || []).map((item) => labels[item.rule]).join(' · ');
}

/** Lists the recommended ones in rank order, then whatever has no rank. */
export function compareByRank(first, second) {
  return (first.rank ?? Infinity) - (second.rank ?? Infinity) || 0;
}

/** One short line explaining a result: the first unmet, then missing, then manual requirement. */
export function getEligibilityReason(evaluation) {
  const requirements = evaluation?.requirements || [];
  const first = (status) => requirements.find((item) => item.status === status);
  const unmet = first('not-satisfied');
  if (unmet) return `${unmet.label}: not met`;
  const missing = first('missing-information');
  if (missing) return `Add to profile: ${missing.label.toLowerCase()}`;
  const manual = requirements.filter((item) => item.status === 'awaiting-verification');
  if (manual.length) return `${manual.length} to verify: ${manual.map((item) => item.label.toLowerCase()).join(', ')}`;
  if (evaluation?.status === 'satisfied') return 'Meets the stated requirements';
  return evaluation?.message || '';
}

/** Deadline from a backend scholarship evaluation, for table cells. Null when unknown. */
export function getScholarshipDeadlineLabel(deadline) {
  if (!deadline) return null;
  const format = (day) => new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
    .format(new Date(`${day}T00:00:00Z`));
  if (deadline.status === 'no_separate_deadline') return { label: 'No separate scholarship deadline', note: 'Check the official application instructions' };
  if (deadline.status === 'rolling') return { label: 'Rolling', note: 'No fixed closing date' };
  if (deadline.status === 'upcoming' && deadline.opens_on) {
    return { label: `Opens ${format(deadline.opens_on)}`, note: `Opens in ${deadline.days_left} days` };
  }
  if (!deadline.date) return null;
  const label = format(deadline.date);
  if (deadline.status === 'open') return { label, note: `${deadline.days_left} days left` };
  return { label, note: 'Closed · check next cycle' };
}
