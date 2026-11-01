// Turns structured scholarship fields into the rows pages show. A record without structured
// fields gives null, and the page keeps showing its original text.
// "Not specified" means the record doesn't say. It is never shown as "Not covered" or "None".
const NOT_SPECIFIED = 'Not specified';

const FUNDING_LEVELS = {
  full: 'Fully funded',
  partial: 'Partially funded',
  tuition_only: 'Tuition only',
  mixed: 'Mixed funding',
};
const BENEFIT_STATUS = {
  covered: 'Covered',
  via_stipend: 'Paid from the stipend',
  partial: 'Partly covered',
  not_covered: 'Not covered',
};
const PERIODS = { monthly: ' per month', annual: ' per year', total: ' in total' };
const ACADEMIC_CONDITIONS = {
  degree_class: 'Degree class requirement; see the original wording',
  class_rank: 'Class rank requirement; see the original wording',
  merit_based: 'Merit-based, with no fixed minimum',
  set_by_institution: 'Set by the university',
};
const ENGLISH_TYPES = {
  test_required: 'English test required',
  set_by_institution: 'Set by the university',
  not_required: 'Not required',
};
const DEADLINE_TYPES = {
  fixed: 'Fixed date',
  rolling: 'Rolling',
  annual: 'Repeats each year; exact date not confirmed',
  varies_by_institution: 'Varies by university or course',
  no_separate_deadline: 'No separate deadline',
};
const CHANNELS = {
  direct: 'Apply directly',
  via_institution: 'Apply through the university or course',
  nomination: 'Nomination required',
  automatic: 'Considered automatically when you apply for admission',
};
const RESTRICTIONS = {
  former_citizenship_excluded: 'Former citizens of the host country are excluded',
  nationality_cap: 'Limited places per nationality',
  dual_citizenship_excluded: 'Dual citizens of the host country are excluded',
  first_time_applicant: 'First-time applicants only',
  second_masters_excluded: 'Not for a second Master\'s',
  previous_scholarship_excluded: 'Previous holders of this award are excluded',
  high_income_study_excluded: 'Not after a year or more in a high-income country',
  other_funding_excluded: 'Limits on holding other funding',
  employee_excluded: 'Employees of the funder and their relatives are excluded',
  financial_need_required: 'Financial need must be shown',
  eu_tax_household_excluded: 'Households filing taxes in the EU are excluded',
  residency_required: 'Residency conditions apply',
  participating_institution_only: 'Participating universities or courses only',
  enrolled_student_required: 'Must be enrolled or about to enrol',
  fee_paying_only: 'Fee-paying students only',
  first_year_only: 'First-year applicants only',
  early_application_only: 'Early application round only',
  admission_test_required: 'Admission test required',
  minimum_work_experience: 'Work experience required',
  return_home_required: 'Must return home after the award',
};
const VERIFICATION = {
  official_source: 'Recorded from the official source',
  mixed_sources: 'Based on official and secondary sources',
  secondary_only: 'Based on secondary sources only',
  not_verified: 'Not yet verified against the official source',
};

const plainNumber = (value) => Number(value).toLocaleString('en-US');
const joined = (items) => (items?.length ? items.join(', ') : null);

export function formatMoney(amount, amountMax, currency, period) {
  const top = amountMax ?? null;
  if (amount == null && top == null) return null;
  const figure = amount != null && top != null
    ? `${plainNumber(amount)}-${plainNumber(top)}`
    : amount != null ? plainNumber(amount) : `up to ${plainNumber(top)}`;
  return `${currency} ${figure}${PERIODS[period] || ''}`;
}

export function formatTuition(item) {
  switch (item.tuition_coverage_type) {
    case 'full': return 'Full tuition';
    case 'percentage': return `${item.tuition_percent_min}-${item.tuition_percent_max}% of tuition`;
    case 'fixed_amount': return formatMoney(item.tuition_amount, item.tuition_amount_max, item.tuition_currency, item.tuition_period);
    case 'tiered': return 'Depends on the award level';
    case 'conditional': return 'Depends on the university';
    case 'none': return 'Not covered';
    default: return NOT_SPECIFIED;
  }
}

export function formatStipend(item) {
  const money = formatMoney(item.stipend_amount, item.stipend_amount_max, item.stipend_currency, item.stipend_period);
  const shown = money && item.stipend_is_approximate ? `About ${money}` : money;
  switch (item.stipend_status) {
    case 'provided': return shown || 'Provided; amount not confirmed';
    case 'included_in_package': return 'Included in the award amount';
    case 'conditional': return shown ? `Only some awards: ${shown}` : 'Only some awards';
    case 'none': return 'Not provided';
    default: return NOT_SPECIFIED;
  }
}

const benefit = (status) => BENEFIT_STATUS[status] || NOT_SPECIFIED;

export function getFundingRows(item) {
  if (!item.structured_data_version) return null;
  const travel = item.travel_amount != null
    ? `Covered: ${formatMoney(item.travel_amount, null, item.travel_currency, 'total')}`
    : benefit(item.travel_status);
  return [
    ['Funding level', FUNDING_LEVELS[item.funding_level] || NOT_SPECIFIED],
    ['Tuition', formatTuition(item)],
    ['Stipend', formatStipend(item)],
    ['Accommodation', benefit(item.accommodation_status)],
    ['Health insurance', benefit(item.health_insurance_status)],
    ['Travel', travel],
    ['Funding period', item.funding_duration_months ? `${item.funding_duration_months} months` : NOT_SPECIFIED],
    ...(item.costs_not_covered?.length
      ? [['Stated as not covered', item.costs_not_covered.map((cost) => (cost === 'living_costs' ? 'Living costs' : 'Tuition')).join(', ')]]
      : []),
  ];
}

/** One line for tables: the two facts students compare first. */
export function getCoverageSummary(item) {
  if (!item.structured_data_version) return null;
  const tuition = formatTuition(item);
  const stipend = formatStipend(item);
  return [
    tuition === NOT_SPECIFIED ? null : tuition,
    item.stipend_status === 'provided' || item.stipend_status === 'conditional' ? stipend : null,
  ].filter(Boolean).join(' · ') || NOT_SPECIFIED;
}

export function getAudienceSummary(item) {
  const excluded = joined([...(item.excluded_regions || []), ...(item.excluded_countries || [])]);
  const named = joined(item.eligible_countries);
  switch (item.nationality_scope) {
    case 'all': return 'All nationalities';
    case 'all_except': return excluded ? `All except ${excluded}` : 'All nationalities, with exclusions';
    case 'listed': return `Only citizens of: ${named}`;
    case 'published_list': return named ? `Published country list, including ${named}` : 'Published country list';
    default: return NOT_SPECIFIED;
  }
}

export function getAcademicSummary(item) {
  if (item.min_gpa != null) return `Minimum ${item.min_gpa}/${item.min_gpa_scale}`;
  if (item.min_percentage != null) return `Minimum ${item.min_percentage}%`;
  return ACADEMIC_CONDITIONS[item.academic_condition] || NOT_SPECIFIED;
}

export function getEnglishSummary(item) {
  const scores = [
    item.min_ielts != null ? `IELTS ${item.min_ielts}` : null,
    item.min_toefl != null ? `TOEFL ${item.min_toefl}` : null,
    item.min_duolingo != null ? `Duolingo ${item.min_duolingo}` : null,
  ].filter(Boolean).join(', ');
  const base = ENGLISH_TYPES[item.english_requirement_type] || NOT_SPECIFIED;
  return [base, scores ? `minimum ${scores}` : null].filter(Boolean).join(': ');
}

function getAgeSummary(item) {
  if (item.min_age != null && item.max_age != null) return `${item.min_age} to ${item.max_age}`;
  if (item.max_age != null) return `${item.max_age} or younger`;
  if (item.min_age != null) return `${item.min_age} or older`;
  return 'No limit stated';
}

const FIELD_SCOPES = { all: 'All fields', varies: 'Varies by course' };

function getFieldSummary(item) {
  const named = joined(item.eligible_disciplines);
  if (named) return named;
  if (item.discipline_scope === 'restricted') return 'Some fields only; see the original wording';
  return FIELD_SCOPES[item.discipline_scope] || NOT_SPECIFIED;
}

export function getRequirementRows(item) {
  if (!item.structured_data_version) return null;
  return [
    ['Who can apply', getAudienceSummary(item)],
    ['Degree level', joined(item.eligible_degree_levels) || NOT_SPECIFIED],
    ['Previous degree', item.required_previous_degree || NOT_SPECIFIED],
    ['Fields of study', getFieldSummary(item)],
    ['Academic requirement', getAcademicSummary(item)],
    ['English', getEnglishSummary(item)],
    ...(item.accepted_english_tests?.length ? [['Accepted tests', joined(item.accepted_english_tests)]] : []),
    ['Age', getAgeSummary(item)],
    ['Gender', item.gender_restriction === 'women' ? 'Women only' : 'No restriction stated'],
    ...(item.residency_requirement ? [['Residency', item.residency_requirement]] : []),
    ...(item.applicant_restrictions?.length
      ? [['Other conditions', item.applicant_restrictions.map((code) => RESTRICTIONS[code] || code).join('; ')]]
      : []),
  ];
}

const shortDate = (value) => new Date(`${value}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });

export function getDeadlineRows(item) {
  if (!item.structured_data_version) return null;
  return [
    ['Deadline type', DEADLINE_TYPES[item.deadline_type] || NOT_SPECIFIED],
    ...(item.application_cycle ? [['Application cycle', item.application_cycle]] : []),
    ...(item.application_open_date ? [['Opens', shortDate(item.application_open_date)]] : []),
    ...(item.application_deadline_date ? [['Closes', shortDate(item.application_deadline_date)]] : []),
    ['How to apply', CHANNELS[item.application_channel] || NOT_SPECIFIED],
  ];
}

export function getOfficialLinks(item) {
  return [
    item.official_application_url ? { label: 'Official application', url: item.official_application_url } : null,
    item.official_info_url ? { label: 'Official scholarship information', url: item.official_info_url } : null,
    ...(item.additional_source_urls || []).map((url) => ({ label: 'Other source', url })),
  ].filter(Boolean);
}

export function getVerificationText(item) {
  return VERIFICATION[item.verification_basis] || null;
}
