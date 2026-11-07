// The scholarship form. Blank means "the record doesn't say": it's sent as null, never as 0, false or "".

const options = (...values) => values.map((value) => ({ value, label: value.replace(/_/g, ' ') }));
const BENEFIT = options('covered', 'via_stipend', 'partial', 'not_covered', 'not_specified');
const CURRENCY = options('EUR', 'GBP', 'AUD', 'USD', 'TRY', 'HUF', 'SEK', 'PLN', 'CZK', 'MYR');
const PERIOD = options('monthly', 'annual', 'total');

const text = (name, label, extra = {}) => ({ name, label, type: 'text', ...extra });
const area = (name, label, extra = {}) => ({ name, label, type: 'textarea', ...extra });
const num = (name, label, extra = {}) => ({ name, label, type: 'number', ...extra });
const whole = (name, label) => ({ name, label, type: 'integer' });
const date = (name, label) => ({ name, label, type: 'date' });
const pick = (name, label, choices) => ({ name, label, type: 'select', options: choices });
const lines = (name, label, hint = 'One per line') => ({ name, label, type: 'lines', hint });
const url = (name, label) => ({ name, label, type: 'url' });

export const FORM_SECTIONS = [
  {
    id: 'basic',
    title: 'Basic information',
    fields: [
      text('name', 'Scholarship name', { required: true }), text('provider', 'Provider'), area('study_type', 'Description'),
      text('country', 'Host country', { required: true }), pick('institution_scope', 'Institution scope', options('single_institution', 'participating_list', 'national')),
      text('host_institution', 'Host institution'),
    ],
  },
  {
    id: 'eligibility',
    title: 'Eligibility',
    fields: [
      area('eligible_nationalities', 'Eligible nationalities (original wording)'), area('pakistan_eligible', 'Open to Pakistan (original wording)'),
      pick('nationality_scope', 'Nationality scope', options('all', 'all_except', 'listed', 'published_list', 'not_specified')),
      lines('eligible_countries', 'Eligible countries'), lines('excluded_countries', 'Excluded countries'),
      lines('eligible_regions', 'Eligible regions'), lines('excluded_regions', 'Excluded regions'),
      text('degree_level', 'Degree level (original wording)'), lines('eligible_degree_levels', 'Degree levels'),
      area('bachelors_requirement', "Bachelor's requirement (original wording)"), text('required_previous_degree', 'Required previous degree'),
      area('eligible_fields', 'Eligible fields (original wording)'), pick('discipline_scope', 'Discipline scope', options('all', 'listed', 'restricted', 'varies', 'not_specified')),
      lines('eligible_disciplines', 'Eligible disciplines'),
      area('min_academic_requirement', 'Academic requirement (original wording)'),
      pick('academic_condition', 'Academic condition', options('numeric', 'degree_class', 'class_rank', 'merit_based', 'set_by_institution', 'not_specified')),
      num('min_gpa', 'Minimum GPA'), num('min_gpa_scale', 'GPA scale'), num('min_percentage', 'Minimum percentage'),
      area('english_requirement', 'English requirement (original wording)'),
      pick('english_requirement_type', 'English requirement type', options('test_required', 'set_by_institution', 'not_required', 'not_specified')),
      lines('accepted_english_tests', 'Accepted English tests'), num('min_ielts', 'Minimum IELTS'), num('min_toefl', 'Minimum TOEFL'), num('min_duolingo', 'Minimum Duolingo'),
      text('age_requirement', 'Age requirement (original wording)'), whole('min_age', 'Minimum age'), whole('max_age', 'Maximum age'),
      pick('gender_restriction', 'Gender restriction', options('women')), area('residency_requirement', 'Residency conditions'),
      lines('applicant_restrictions', 'Other restrictions', 'One restriction code per line'), area('work_experience', 'Work experience (original wording)'),
    ],
  },
  {
    id: 'funding',
    title: 'Funding',
    fields: [
      text('funding_type', 'Funding type (original wording)'), pick('funding_level', 'Funding level', options('full', 'partial', 'tuition_only', 'mixed', 'not_specified')),
      area('tuition_coverage', 'Tuition coverage (original wording)'),
      pick('tuition_coverage_type', 'Tuition coverage type', options('full', 'percentage', 'fixed_amount', 'tiered', 'conditional', 'none', 'not_specified')),
      num('tuition_percent_min', 'Tuition % from'), num('tuition_percent_max', 'Tuition % to'), num('tuition_amount', 'Tuition amount'), num('tuition_amount_max', 'Tuition amount up to'),
      pick('tuition_currency', 'Tuition currency', CURRENCY), pick('tuition_period', 'Tuition period', PERIOD),
      area('living_stipend', 'Living stipend (original wording)'),
      pick('stipend_status', 'Stipend status', options('provided', 'included_in_package', 'conditional', 'none', 'not_specified')),
      num('stipend_amount', 'Stipend amount'), num('stipend_amount_max', 'Stipend amount up to'), pick('stipend_currency', 'Stipend currency', CURRENCY), pick('stipend_period', 'Stipend period', PERIOD),
      { name: 'stipend_is_approximate', label: 'Stipend amount is approximate', type: 'boolean' },
      area('accommodation', 'Accommodation (original wording)'), pick('accommodation_status', 'Accommodation', BENEFIT),
      area('health_insurance', 'Health insurance (original wording)'), pick('health_insurance_status', 'Health insurance', BENEFIT),
      area('travel_airfare', 'Travel (original wording)'), pick('travel_status', 'Travel support', BENEFIT), num('travel_amount', 'Travel amount'), pick('travel_currency', 'Travel currency', CURRENCY),
      area('visa_support', 'Visa support'), area('other_benefits', 'Other benefits'), text('duration', 'Duration (original wording)'), whole('funding_duration_months', 'Funding duration (months)'),
      lines('costs_not_covered', 'Uncovered expenses', 'tuition or living_costs, one per line'),
    ],
  },
  {
    id: 'application',
    title: 'Application information',
    fields: [
      area('deadline', 'Deadline (original wording)'),
      pick('deadline_type', 'Deadline type', options('fixed', 'rolling', 'annual', 'varies_by_institution', 'no_separate_deadline', 'not_specified')),
      date('application_open_date', 'Opening date'), date('application_deadline_date', 'Closing date'), text('application_cycle', 'Application cycle'),
      url('official_info_url', 'Information URL'), url('official_application_url', 'Application URL'), lines('additional_source_urls', 'Other source URLs'),
      pick('application_channel', 'Application channel', options('direct', 'via_institution', 'nomination', 'automatic', 'not_specified')),
      area('application_method', 'Application method'), area('admission_required', 'Admission required'), area('nomination_required', 'Nomination required'),
      area('required_documents', 'Required documents (original wording)'), lines('required_documents_list', 'Required documents'),
      area('application_pathway', 'Application pathway'), area('notes', 'Notes'), text('source_name', 'Source name'), area('official_url', 'Original source links'),
    ],
  },
];

const FIELDS = FORM_SECTIONS.flatMap((section) => section.fields);

export const REVIEW_LABELS = {
  nationality: 'Nationality', degree: 'Degree', field: 'Field of study', academic: 'Academic requirement', english: 'English requirement',
  age: 'Age', funding: 'Funding', deadline: 'Deadline', documents: 'Required documents',
};

export function getOpenReviewGroups(flags) {
  return (flags || []).filter((flag) => flag.startsWith('review:')).map((flag) => flag.slice('review:'.length));
}

/** What the form inputs show for a record. Every value is a string, and "" is unknown. */
export function toFormValues(record) {
  return Object.fromEntries(FIELDS.map((field) => {
    const value = record?.[field.name];
    if (value == null) return [field.name, ''];
    if (field.type === 'lines') return [field.name, value.join('\n')];
    return [field.name, String(value)];
  }));
}

function parseField(field, raw) {
  const value = raw.trim();
  if (!value) return null;
  if (field.type === 'lines') return value.split('\n').map((line) => line.trim()).filter(Boolean);
  if (field.type === 'number' || field.type === 'integer') return Number(value);
  if (field.type === 'boolean') return value === 'true';
  return value;
}

/** Errors by field name, for what the browser can check before sending. */
export function validateForm(values) {
  const errors = {};
  FIELDS.forEach((field) => {
    const value = values[field.name].trim();
    if (field.required && !value) errors[field.name] = `${field.label} is required.`;
    if (!value) return;
    if ((field.type === 'number' || field.type === 'integer') && !Number.isFinite(Number(value))) errors[field.name] = 'Enter a number.';
    if (field.type === 'integer' && !Number.isInteger(Number(value))) errors[field.name] = 'Enter a whole number.';
    if (field.type === 'url' && !/^https?:\/\/\S+\.\S+$/.test(value)) errors[field.name] = 'Enter one full web address.';
  });
  return errors;
}

/** The request body. Every field is sent, and the backend records only what really changed. */
export function toPayload(values) {
  return Object.fromEntries(FIELDS.map((field) => [field.name, parseField(field, values[field.name])]));
}

export function isDirty(values, original) {
  return FIELDS.some((field) => values[field.name] !== original[field.name]);
}

export const ISSUE_FILTERS = [
  ['', 'All records'], ['attention', 'Needs attention'], ['conflict', 'Conflicting'], ['unverified', 'Unverified'],
  ['missing_official_source', 'No official source'], ['missing_application_url', 'No application link'], ['missing_deadline', 'Deadline missing'],
  ['missing_funding', 'Funding missing'], ['missing_eligibility', 'Eligibility missing'], ['never_verified', 'Never verified'],
  ['weak_evidence', 'Not fully officially sourced'],
  ['stale_verification', 'Verification old'], ['broken_url', 'Broken link'], ['duplicate', 'Duplicates'],
];
