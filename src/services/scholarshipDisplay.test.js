import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mapScholarshipToFrontend } from './opportunityApi.js';
import {
  formatMoney,
  formatStipend,
  formatTuition,
  getAcademicSummary,
  getAudienceSummary,
  getCoverageSummary,
  getDeadlineRows,
  getEnglishSummary,
  getFundingRows,
  getOfficialLinks,
  getRequirementRows,
  getVerificationText,
} from './scholarshipDisplay.js';

const record = (overrides = {}) => ({
  id: 5,
  name: 'Test',
  verification_status: 'verified',
  official_url: 'https://home.example.org/ ; https://other.example.org/',
  structured_data_version: 1,
  ...overrides,
});
const row = (rows, label) => rows.find(([name]) => name === label)?.[1];

test('money keeps amount, currency and period together', () => {
  assert.equal(formatMoney(992, null, 'EUR', 'monthly'), 'EUR 992 per month');
  assert.equal(formatMoney(1712, 2000, 'GBP', 'monthly'), 'GBP 1,712-2,000 per month');
  assert.equal(formatMoney(null, 10000, 'EUR', 'annual'), 'EUR up to 10,000 per year');
  assert.equal(formatMoney(null, null, 'EUR', 'annual'), null);
});

test('an unspecified stipend is never shown as zero or as none', () => {
  assert.equal(formatStipend(record({ stipend_status: 'not_specified' })), 'Not specified');
  assert.equal(formatStipend(record()), 'Not specified');
  assert.equal(formatStipend(record({ stipend_status: 'none' })), 'Not provided');
  assert.equal(formatStipend(record({ stipend_status: 'provided' })), 'Provided; amount not confirmed');
});

test('approximate and conditional stipends say so', () => {
  assert.equal(formatStipend(record({ stipend_status: 'provided', stipend_amount: 30000, stipend_currency: 'EUR', stipend_period: 'annual', stipend_is_approximate: true })),
    'About EUR 30,000 per year');
  assert.equal(formatStipend(record({ stipend_status: 'conditional', stipend_amount_max: 10000, stipend_currency: 'EUR', stipend_period: 'annual' })),
    'Only some awards: EUR up to 10,000 per year');
});

test('tuition types read differently', () => {
  assert.equal(formatTuition(record({ tuition_coverage_type: 'full' })), 'Full tuition');
  assert.equal(formatTuition(record({ tuition_coverage_type: 'percentage', tuition_percent_min: 15, tuition_percent_max: 30 })), '15-30% of tuition');
  assert.equal(formatTuition(record({ tuition_coverage_type: 'fixed_amount', tuition_amount: 5000, tuition_currency: 'EUR', tuition_period: 'total' })), 'EUR 5,000 in total');
  assert.equal(formatTuition(record({ tuition_coverage_type: 'none' })), 'Not covered');
  assert.equal(formatTuition(record({ tuition_coverage_type: 'not_specified' })), 'Not specified');
});

test('funding rows separate missing information from confirmed exclusions', () => {
  const rows = getFundingRows(record({
    funding_level: 'tuition_only', tuition_coverage_type: 'full', stipend_status: 'none',
    accommodation_status: 'not_specified', health_insurance_status: 'covered', travel_status: 'covered',
    travel_amount: 2500, travel_currency: 'PLN', costs_not_covered: ['living_costs'],
  }));
  assert.equal(row(rows, 'Funding level'), 'Tuition only');
  assert.equal(row(rows, 'Accommodation'), 'Not specified');
  assert.equal(row(rows, 'Health insurance'), 'Covered');
  assert.equal(row(rows, 'Travel'), 'Covered: PLN 2,500 in total');
  assert.equal(row(rows, 'Stated as not covered'), 'Living costs');
  assert.equal(row(rows, 'Funding period'), 'Not specified');
});

test('tables get a short coverage summary', () => {
  assert.equal(getCoverageSummary(record({ tuition_coverage_type: 'full', stipend_status: 'provided', stipend_amount: 992, stipend_currency: 'EUR', stipend_period: 'monthly' })),
    'Full tuition · EUR 992 per month');
  assert.equal(getCoverageSummary(record({ tuition_coverage_type: 'not_specified', stipend_status: 'not_specified' })), 'Not specified');
});

test('nationality rules', () => {
  assert.equal(getAudienceSummary(record({ nationality_scope: 'all' })), 'All nationalities');
  assert.equal(getAudienceSummary(record({ nationality_scope: 'all_except', excluded_regions: ['EU', 'EEA'], excluded_countries: ['Suriname'] })), 'All except EU, EEA, Suriname');
  assert.equal(getAudienceSummary(record({ nationality_scope: 'listed', eligible_countries: ['India', 'Nepal'] })), 'Only citizens of: India, Nepal');
  assert.equal(getAudienceSummary(record({ nationality_scope: 'published_list', eligible_countries: ['Pakistan'] })), 'Published country list, including Pakistan');
  assert.equal(getAudienceSummary(record({ nationality_scope: 'not_specified' })), 'Not specified');
});

test('academic and language requirements', () => {
  assert.equal(getAcademicSummary(record({ min_gpa: 5, min_gpa_scale: 7 })), 'Minimum 5/7');
  assert.equal(getAcademicSummary(record({ min_percentage: 75 })), 'Minimum 75%');
  assert.equal(getAcademicSummary(record({ academic_condition: 'merit_based' })), 'Merit-based, with no fixed minimum');
  assert.equal(getAcademicSummary(record()), 'Not specified');
  assert.equal(getEnglishSummary(record({ english_requirement_type: 'test_required', min_ielts: 6.5 })), 'English test required: minimum IELTS 6.5');
  assert.equal(getEnglishSummary(record({ english_requirement_type: 'set_by_institution' })), 'Set by the university');
});

test('requirement rows distinguish no stated limit from a real limit', () => {
  const open = getRequirementRows(record({ discipline_scope: 'all' }));
  assert.equal(row(open, 'Age'), 'No limit stated');
  assert.equal(row(open, 'Gender'), 'No restriction stated');
  assert.equal(row(open, 'Fields of study'), 'All fields');
  const limited = getRequirementRows(record({
    max_age: 29, gender_restriction: 'women', discipline_scope: 'listed', eligible_disciplines: ['Architecture'],
    applicant_restrictions: ['second_masters_excluded'], residency_requirement: 'Must live in Pakistan.',
  }));
  assert.equal(row(limited, 'Age'), '29 or younger');
  assert.equal(row(limited, 'Gender'), 'Women only');
  assert.equal(row(limited, 'Fields of study'), 'Architecture');
  assert.equal(row(limited, 'Residency'), 'Must live in Pakistan.');
  assert.match(row(limited, 'Other conditions'), /second Master's/);
});

test('deadline rows show real dates and never invent one', () => {
  const fixed = getDeadlineRows(record({ deadline_type: 'fixed', application_open_date: '2026-01-10', application_deadline_date: '2026-02-20', application_cycle: '2026-2027', application_channel: 'direct' }));
  assert.equal(row(fixed, 'Opens'), '10 January 2026');
  assert.equal(row(fixed, 'Closes'), '20 February 2026');
  assert.equal(row(fixed, 'How to apply'), 'Apply directly');
  const annual = getDeadlineRows(record({ deadline_type: 'annual' }));
  assert.equal(row(annual, 'Closes'), undefined);
  assert.match(row(annual, 'Deadline type'), /exact date not confirmed/);
});

test('official links stay separate', () => {
  assert.deepEqual(getOfficialLinks(record({
    official_application_url: 'https://apply.example.org/', official_info_url: 'https://info.example.org/',
    additional_source_urls: ['https://extra.example.org/'],
  })).map((link) => link.label), ['Official application', 'Official scholarship information', 'Other source']);
  assert.deepEqual(getOfficialLinks(record()), []);
});

test('the Apply link prefers the application page', () => {
  const mapped = mapScholarshipToFrontend(record({ official_application_url: 'https://apply.example.org/', official_info_url: 'https://info.example.org/' }));
  assert.equal(mapped.applicationUrl, 'https://apply.example.org/');
  assert.equal(mapped.applicationUrlStatus, 'official-verified');
});

test('a home page stored as a source is not offered as the application', () => {
  const mapped = mapScholarshipToFrontend(record({ additional_source_urls: ['https://home.example.org/'] }));
  assert.equal(mapped.applicationUrl, null);
  assert.equal(mapped.applicationUrlStatus, 'unavailable');
});

test('unverified records never get an official link status', () => {
  const mapped = mapScholarshipToFrontend(record({ verification_status: 'unverified', official_info_url: 'https://info.example.org/' }));
  assert.equal(mapped.applicationUrlStatus, 'unavailable');
  assert.equal(mapped.sourceStatus, 'unverified');
});

test('records without structured fields keep working from their text', () => {
  const mapped = mapScholarshipToFrontend({ ...record(), structured_data_version: null, tuition_coverage: 'Full tuition waiver' });
  assert.equal(mapped.applicationUrl, 'https://home.example.org/');
  assert.equal(mapped.coverage, 'Full tuition waiver');
  assert.equal(mapped.coverageSummary, null);
  assert.equal(mapped.fundingRows, null);
  assert.equal(mapped.requirementSummaryRows, null);
  assert.equal(mapped.deadlineRows, null);
  assert.deepEqual(mapped.officialLinks, []);
});

test('the original wording stays available beside structured values', () => {
  const mapped = mapScholarshipToFrontend(record({ living_stipend: 'Yes - commonly around EUR 1,000', stipend_status: 'provided' }));
  assert.deepEqual(mapped.benefits, [{ label: 'Living stipend', value: 'Yes - commonly around EUR 1,000' }]);
  assert.equal(row(mapped.fundingRows, 'Stipend'), 'Provided; amount not confirmed');
});

test('verification labels follow the evidence', () => {
  assert.equal(getVerificationText(record({ verification_basis: 'official_source' })), 'Recorded from the official source');
  assert.equal(getVerificationText(record({ verification_basis: 'mixed_sources' })), 'Based on official and secondary sources');
  assert.equal(getVerificationText(record({ verification_basis: 'secondary_only' })), 'Based on secondary sources only');
  assert.equal(getVerificationText(record()), null);
});

test('duplicates point at the record they repeat', () => {
  assert.equal(mapScholarshipToFrontend(record({ duplicate_of_id: 1 })).duplicateOf, 'sch-db-1');
  assert.equal(mapScholarshipToFrontend(record()).duplicateOf, null);
});

test('comparison values use structured data and the real deadline date', () => {
  const mapped = mapScholarshipToFrontend(record({ min_percentage: 75, nationality_scope: 'all', english_requirement_type: 'not_specified', application_deadline_date: '2026-02-20' }));
  assert.equal(mapped.academicSummary, 'Minimum 75%');
  assert.equal(mapped.audienceSummary, 'All nationalities');
  assert.equal(mapped.englishSummary, 'Not specified');
  assert.equal(mapped.deadlineDate, '2026-02-20');
});
