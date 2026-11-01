// Filter state for Explore Scholarships. The backend does the filtering; this only describes the request.

export const PAGE_SIZE = 20;

export const EMPTY_FILTERS = {
  q: '',
  nationality: '',
  host_country: [],
  nationality_scope: [],
  degree: [],
  discipline: [],
  academic_condition: [],
  funding: [],
  benefit: [],
  deadline: [],
  verification: [],
  eligibility: [],
  match: [],
};

export const SORT_OPTIONS = [
  { value: '', label: 'Best match for the search' },
  { value: 'recommendation', label: 'Recommendation score', needsLogin: true },
  { value: 'name', label: 'Name (A-Z)' },
  { value: 'deadline', label: 'Deadline (earliest first)' },
  { value: 'funding', label: 'Funding (highest first)' },
  { value: 'country', label: 'Host country (A-Z)' },
  { value: 'verified', label: 'Recently verified' },
];

const ELIGIBILITY_LABELS = { eligible: 'Eligible', verify_manually: 'Verify manually', not_eligible: 'Not eligible' };

/** Query string for GET /scholarships/search. Empty values are left out. */
export function buildSearchQuery(filters, { programId = null, sort = '', page = 1 } = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (Array.isArray(value)) value.forEach((item) => params.append(key, item));
    else if (value.trim()) params.set(key, value.trim().replace(/\s+/g, ' '));
  });
  if (programId != null) params.set('program_id', String(programId));
  else params.delete('match');
  if (sort) params.set('sort', sort);
  params.set('skip', String((page - 1) * PAGE_SIZE));
  params.set('limit', String(PAGE_SIZE));
  return params.toString();
}

export function toggleFilterValue(filters, key, value) {
  const current = filters[key];
  return { ...filters, [key]: current.includes(value) ? current.filter((item) => item !== value) : [...current, value] };
}

/** Clears one active filter and keeps the others. */
export function removeFilterValue(filters, key, value) {
  return Array.isArray(filters[key]) ? { ...filters, [key]: filters[key].filter((item) => item !== value) } : { ...filters, [key]: '' };
}

function optionLabel(options, value) {
  return (options || []).find((item) => item.value === value)?.label || value;
}

/** One entry per active filter, for the chips above the results. */
export function getActiveFilters(filters, options) {
  const groups = {
    host_country: ['Host country', options?.host_countries], nationality_scope: ['Nationality rule', options?.nationality_scopes],
    degree: ['Degree', options?.degree_levels], discipline: ['Field', options?.disciplines],
    academic_condition: ['Academic rule', options?.academic_conditions], funding: ['Funding', options?.funding],
    benefit: ['Includes', options?.benefits], deadline: ['Deadline', options?.deadlines], verification: ['Records', options?.verification],
    match: ['Program', options?.match_outcomes],
  };
  const active = [];
  if (filters.q.trim()) active.push({ key: 'q', value: filters.q, label: `Search: ${filters.q.trim()}` });
  if (filters.nationality.trim()) active.push({ key: 'nationality', value: filters.nationality, label: `Citizen of: ${filters.nationality.trim()}` });
  Object.entries(groups).forEach(([key, [title, list]]) => {
    filters[key].forEach((value) => active.push({ key, value, label: `${title}: ${optionLabel(list, value)}` }));
  });
  filters.eligibility.forEach((value) => active.push({ key: 'eligibility', value, label: `Eligibility: ${ELIGIBILITY_LABELS[value]}` }));
  return active;
}

export const ELIGIBILITY_OPTIONS = Object.entries(ELIGIBILITY_LABELS).map(([value, label]) => ({ value, label }));

export function getPageCount(total) {
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}
