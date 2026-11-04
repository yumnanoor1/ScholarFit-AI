import { Fragment, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowRight, Award, Bookmark, BookOpen, CalendarDays, Clock, Globe2, GraduationCap, Languages, MapPin, Plus, ShieldCheck, Wallet, X,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import SavedStatusNotice from '../components/opportunities/SavedStatusNotice';
import ScholarshipLogo from '../components/common/ScholarshipLogo';
import MatchRing from '../components/opportunities/MatchRing';
import { useOpportunityCatalog } from '../hooks/useOpportunityCatalog';
import { useScholarshipEligibilities, useScholarshipRecommendation } from '../hooks/useScholarshipEligibility';
import { getScholarshipDeadlineLabel } from '../services/eligibilityBadges';
import { parseScholarshipId } from '../services/opportunityApi';
import { getScholarshipLogo } from '../services/scholarshipLogos';
import './Universities.css';
import './Compare.css';

const ROWS = [
  { id: 'funding', group: 'Funding and deadlines', label: 'Funding coverage', icon: Wallet, value: (item) => getFundingType(item) },
  { id: 'deadline', group: 'Funding and deadlines', label: 'Application deadline', icon: CalendarDays, value: (item) => getScholarshipDeadlineLabel(item.evaluation?.deadline)?.label || item.deadline || item.deadlineRows?.[0]?.[1] },
  { id: 'duration', group: 'Funding and deadlines', label: 'Award duration', icon: Clock, value: (item) => item.duration },
  { id: 'academic', group: 'Requirements', label: 'Academic requirement', icon: GraduationCap, value: (item) => item.bachelorsRequirement || item.academicRequirement || item.degree },
  { id: 'english', group: 'Requirements', label: 'English requirement', icon: Languages, value: (item) => item.englishRequirement || item.englishSummary },
  { id: 'nationality', group: 'Requirements', label: 'Eligible nationalities', icon: Globe2, value: (item) => item.audienceSummary || item.eligibleNationalities || item.pakistanEligible },
  { id: 'fields', group: 'Requirements', label: 'Eligible fields', icon: BookOpen, value: (item) => item.eligibleFields },
];

const MONTHS = {
  january: 'JAN', jan: 'JAN', february: 'FEB', feb: 'FEB', march: 'MAR', mar: 'MAR',
  april: 'APR', apr: 'APR', may: 'MAY', june: 'JUN', jun: 'JUN',
  july: 'JUL', jul: 'JUL', august: 'AUG', aug: 'AUG',
  september: 'SEP', sept: 'SEP', sep: 'SEP', october: 'OCT', oct: 'OCT',
  november: 'NOV', nov: 'NOV', december: 'DEC', dec: 'DEC',
};

function getFundingType(item) {
  const fundingLevel = item.fundingRows?.find(([label]) => label.toLowerCase() === 'funding level')?.[1];
  const value = typeof item.type === 'string' && item.type.trim() ? item.type.trim() : fundingLevel;
  return typeof value === 'string' && value.trim() && !/^(not listed|not specified|n\/a|none)$/i.test(value.trim())
    ? value.trim()
    : 'Not listed';
}

function compactMonthRange(value) {
  const monthPattern = Object.keys(MONTHS).sort((a, b) => b.length - a.length).join('|');
  const found = [...String(value).matchAll(new RegExp(`\\b(${monthPattern})\\b`, 'gi'))];
  if (found.length !== 2) return value;
  return `${MONTHS[found[0][0].toLowerCase()]} – ${MONTHS[found[1][0].toLowerCase()]}`;
}

function getDeadlinePresentation(item, fallback) {
  const status = item.evaluation?.deadline;
  const evaluated = getScholarshipDeadlineLabel(status);
  const type = item.deadlineRows?.find(([label]) => label === 'Deadline type')?.[1];
  const cycle = item.deadlineRows?.find(([label]) => label === 'Application cycle')?.[1];
  const noSeparate = status?.status === 'no_separate_deadline' || /no separate deadline/i.test(type || '');
  if (noSeparate) return 'Programme-based';
  if (evaluated?.label && /\d/.test(evaluated.label)) return evaluated.label;
  if (cycle) return compactMonthRange(cycle);
  if (/varies/i.test(type || '')) return 'Programme-based';
  if (evaluated) return evaluated.label;
  return fallback || 'Not listed';
}

function getDurationPresentation(item, fallback) {
  const original = String(item.duration || fallback || '').trim();
  if (!original) return 'Not listed';
  const period = original.match(/\b(?:up to\s*)?\d+(?:\s*(?:-|–|to)\s*\d+)?\s*(?:academic\s+)?(?:years?|months?)\b/i);
  if (period) return period[0].replace(/(\d)\s*-\s*(\d)/g, '$1–$2').replace(/\s+/g, ' ');
  return original.split(/[.;(]/, 1)[0].trim() || 'Not listed';
}

function getAcademicPresentation(item, fallback) {
  const details = [...new Set([
    item.bachelorsRequirement, item.academicRequirement, item.degree, fallback,
  ].map((value) => String(value || '').trim())
    .filter((value) => value && !/^(not listed|not specified|n\/a|none)$/i.test(value)))];
  if (!details.length) return { main: 'Not listed', note: '', details: [] };

  const source = details.join(' ').replace(/^yes\s*[-–:]\s*/i, '');
  const normalized = source.toLowerCase();
  const isBachelorRequirement = /\bbachelor(?:['’]s|s)?\b/.test(normalized);
  const isRelevant = /\brelevant\b/.test(normalized);
  const isHonours = /\bhonou?rs?(?:[- ]level)?\b/.test(normalized);
  const isResearchMasters = /\bmaster(?:['’]s)?\s+by\s+research\b|\bresearch\s+master/.test(normalized);
  const isEquivalent = /\bequivalent\b/.test(normalized);
  const main = isBachelorRequirement
    ? `${isResearchMasters ? 'Research master’s: ' : ''}${isRelevant ? 'relevant ' : ''}${isHonours ? 'honours ' : ''}bachelor’s${isEquivalent ? ' or equivalent' : ''} required.`
    : (source.split(/[.;]/, 1)[0].trim().slice(0, 100) || 'Not listed');
  const notes = [];

  if (/\b(before|prior to).{0,35}(programme|program).{0,20}start\b|proof .{0,30}completed/.test(normalized)) {
    notes.push('May finish before the programme starts.');
  }
  if (/set individually|varies by|specific consortium|consortium\/course/.test(normalized)) {
    notes.push('Criteria vary by course.');
  }
  if (/merit/.test(normalized) && /research potential/.test(normalized)) {
    notes.push('Merit-based: grades and research potential.');
  }
  if (/no single eu-wide numeric threshold|no fixed public minimum gpa|no published minimum gpa/.test(normalized)) {
    notes.push(/gpa/.test(normalized) ? 'No fixed GPA.' : 'No EU-wide numeric cutoff.');
  }

  return { main, note: notes.join(' '), details };
}

function getEnglishPresentation(value) {
  const text = String(value || '').trim();
  if (!text || /^(not specified|not listed|unknown|n\/a)$/i.test(text)) return 'Not specified';
  if (/^(no\b|not required\b)/i.test(text)) return 'English proficiency not required';
  if (/^(yes\b|english proficiency required\b)|\bmust meet\b/i.test(text)) return 'English proficiency required';
  if (/^set (?:by the (?:university|institution)|individually)\b/i.test(text)) return 'Set by the university';
  return text.split(/[.;]/, 1)[0].trim() || 'Not specified';
}

function getNationalityPresentation(item, fallback) {
  const original = item.eligibleNationalities || item.audienceSummary || fallback || '';
  const normalized = original.toLowerCase();
  const main = /all nationalities|worldwide|all countries/.test(normalized)
    ? 'Worldwide eligibility'
    : /all except|exclusions/.test(normalized)
      ? 'Worldwide · exclusions apply'
      : /only citizens|published country list|listed/.test(normalized)
        ? 'Listed nationalities'
        : original && !/not specified/i.test(original) ? 'Nationality conditions apply' : 'Not listed';
  const pakistan = String(item.pakistanEligible || '').trim();
  const pakistanLower = pakistan.toLowerCase();
  const eligible = /^(yes|eligible|true|allowed|open)\b/.test(pakistanLower);
  const notEligible = /^(no|not eligible|ineligible|excluded|false)\b/.test(pakistanLower);
  return {
    main,
    pakistanLabel: eligible ? 'Pakistan: Eligible' : notEligible ? 'Pakistan: Not eligible' : pakistan ? `Pakistan: ${pakistan}` : '',
    pakistanEligible: eligible,
  };
}

function getEligibleFieldsSummary(value) {
  const text = String(value || '').trim();
  const programmes = text.match(/\b([\d,]+\+?)\s+joint master's programmes\b/i);
  const fields = text.match(/\b([\d,]+\+?)\s+broad fields of study\b/i);
  if (programmes && fields && /varies by consortium/i.test(text) && /Erasmus Mundus Catalogue/i.test(text)) {
    return `${programmes[1]} joint Master's programmes; ${fields[1]} broad fields, varying by consortium. Annual list: Erasmus Mundus Catalogue.`;
  }
  return text;
}

function MoreInfo({ label, children }) {
  return (
    <details className="cmp-more">
      <summary>{label}</summary>
      <div>{children}</div>
    </details>
  );
}

function ScholarshipMatchScore({ id }) {
  const { loading, state, data } = useScholarshipRecommendation(id);
  const profileIncomplete = state === 'profile-incomplete'
    || state === 'no-profile'
    || data?.eligibility?.status === 'missing_information';
  const categoryTone = profileIncomplete ? 'is-review' : ({
    strong: 'is-strong',
    good: 'is-good',
    possible: 'is-partial',
    needs_verification: 'is-review',
  }[data?.category] || 'is-unavailable');
  const hasScore = !loading && state === 'ok' && !profileIncomplete && Number.isFinite(data?.score);

  return (
    <div className={`cmp-match-score ${categoryTone}`}>
      <MatchRing score={hasScore ? data.score : null} />
    </div>
  );
}

function EligibilityCell({ item }) {
  return (
    <div className="cmp-cell cmp-cell-eligibility">
      <ScholarshipMatchScore id={item.id} />
    </div>
  );
}

function ComparisonCell({ row, value, item }) {
  if (row.id === 'funding') {
    return (
      <div className="cmp-cell cmp-cell-funding">
        <strong>{value.text || 'Not listed'}</strong>
      </div>
    );
  }

  if (row.id === 'deadline') {
    const deadline = getDeadlinePresentation(item, value.text);
    return (
      <div className="cmp-cell cmp-cell-deadline">
        <strong className="cmp-deadline-value">{deadline}</strong>
      </div>
    );
  }

  if (row.id === 'duration') {
    const duration = getDurationPresentation(item, value.text);
    return (
      <div className="cmp-cell cmp-cell-duration">
        <strong className="cmp-duration-value">{duration}</strong>
      </div>
    );
  }

  if (row.id === 'academic') {
    const academic = getAcademicPresentation(item, value.text);
    return (
      <div className="cmp-cell cmp-cell-academic">
        <strong title={academic.details.join(' ')}>{academic.main}</strong>
        {academic.note && <small>{academic.note}</small>}
        {academic.details.length > 0 && (
          <MoreInfo label="Details">
            <p>{academic.details.join(' ')}</p>
          </MoreInfo>
        )}
      </div>
    );
  }

  if (row.id === 'english') {
    return (
      <div className="cmp-cell cmp-cell-english">
        <strong className="cmp-english-value">{getEnglishPresentation(value.text)}</strong>
      </div>
    );
  }

  if (row.id === 'nationality') {
    const nationality = getNationalityPresentation(item, value.text);
    return (
      <div className="cmp-cell cmp-cell-nationality">
        <strong>{nationality.main}</strong>
        {nationality.pakistanLabel && (
          <strong className={nationality.pakistanEligible ? 'cmp-pakistan-eligible' : ''}>{nationality.pakistanLabel}</strong>
        )}
      </div>
    );
  }

  if (row.id === 'fields') {
    const fullFields = String(value.text || '').trim();
    const summary = getEligibleFieldsSummary(fullFields);
    const fields = summary !== fullFields
      ? [summary]
      : fullFields.split(/[;|,]/).map((field) => field.trim()).filter(Boolean);
    return (
      <div className="cmp-cell cmp-cell-fields">
        {fields.length > 0
          ? <div className="cmp-field-lines">{fields.slice(0, 4).map((field) => <span className={summary !== fullFields ? 'cmp-field-summary' : ''} key={field} title={summary !== fullFields ? fullFields : field}>{field}</span>)}</div>
          : <strong className="is-missing">Not listed</strong>}
        {fields.length > 4 && (
          <MoreInfo label={`+${fields.length - 4} more fields`}>
            <p>{fullFields}</p>
          </MoreInfo>
        )}
        {value.note && <small>{value.note}</small>}
      </div>
    );
  }

  return (
    <div className="cmp-cell">
      <strong className={value.text ? '' : 'is-missing'}>{value.text || 'Not listed'}</strong>
      {value.note && <small>{value.note}</small>}
    </div>
  );
}

function OpportunityMark({ item, size = 48 }) {
  return <ScholarshipLogo src={getScholarshipLogo(item)} size={size} bareFallback fallback={<span className="cmp-mark is-scholarship" style={{ '--mark-size': `${size}px` }} aria-hidden="true"><Award size={Math.round(size * 0.45)} /></span>} />;
}

export default function Compare() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    savedOpportunities,
    comparisonOpportunityIds, toggleComparisonOpportunity, clearComparisonOpportunities,
  } = useProfile();
  const compareIds = useMemo(() => {
    const requested = searchParams.get('ids') ?? comparisonOpportunityIds.join(',');
    return requested.split(',').filter((id) => parseScholarshipId(id) != null).slice(0, 2);
  }, [searchParams, comparisonOpportunityIds]);
  const catalog = useOpportunityCatalog();
  const eligibility = useScholarshipEligibilities(compareIds);
  const opportunities = compareIds
    .map((id) => catalog.getOpportunity(id))
    .filter((item) => item?.kind === 'scholarship')
    .map((item) => ({ ...item, title: item.name, organization: item.provider, evaluation: eligibility.getEvaluation(item.id) }));
  const complete = opportunities.length === 2;
  const groups = complete ? [...new Set(ROWS.map((row) => row.group))].map((group) => ({
    title: group,
    rows: ROWS.filter((row) => row.group === group)
      .map((row) => ({ ...row, values: opportunities.map((item) => ({ text: row.value(item), note: row.note?.(item) })) })),
  })).filter((group) => group.rows.length) : [];

  const remove = (id) => {
    if (comparisonOpportunityIds.includes(id)) toggleComparisonOpportunity(id);
    if (searchParams.get('ids')) {
      const rest = compareIds.filter((item) => item !== id);
      setSearchParams(rest.length ? { ids: rest.join(',') } : {}, { replace: true });
    }
  };
  const clear = () => {
    clearComparisonOpportunities();
    if (searchParams.get('ids')) setSearchParams({}, { replace: true });
  };

  return (
    <div className={`page-container cmp-page ${complete ? '' : 'is-waiting'}`}>
      <header className="cmp-header">
        <div className="cmp-header-copy">
          <h1>Compare scholarships</h1>
          <p>Funding, eligibility and deadlines at a glance.</p>
        </div>
        <div className="cmp-header-actions">
          <button type="button" className="cmp-ghost-button" onClick={() => navigate('/saved')}><Bookmark size={15} aria-hidden="true" /> Saved <span>{savedOpportunities.length}</span></button>
          {opportunities.length > 0 && <button type="button" className="cmp-ghost-button" onClick={clear}><X size={15} aria-hidden="true" /> Clear comparison</button>}
        </div>
      </header>
      <SavedStatusNotice />
      {catalog.loading && compareIds.length > 0 ? <p className="cmp-status" role="status">Loading your comparison…</p> : (
        <>
          {catalog.error && <p className="cmp-status" role="alert">{catalog.error}</p>}
          {!complete && (
            <section className="cmp-versus" aria-label="Scholarships being compared">
              {[0, 1].map((slot) => {
                const item = opportunities[slot];
                if (!item) {
                  return (
                    <div key={slot} className="cmp-slot is-empty">
                      <span className="cmp-slot-plus" aria-hidden="true"><Plus size={26} /></span>
                      <strong>{opportunities.length ? 'Add one more scholarship' : 'Add scholarships to compare'}</strong>
                      <p>Choose Compare on a scholarship in the catalogue.</p>
                      <button type="button" className="cmp-primary-button" onClick={() => navigate('/scholarships')}>Browse scholarships <ArrowRight size={15} aria-hidden="true" /></button>
                    </div>
                  );
                }
                return (
                  <article key={item.id} className="cmp-slot is-scholarship">
                    <button type="button" className="cmp-remove" onClick={() => remove(item.id)} aria-label={`Remove ${item.title}`}><X size={16} aria-hidden="true" /></button>
                    <OpportunityMark item={item} />
                    <span className="cmp-kind">Scholarship</span>
                    <h2>{item.title}</h2>
                    <p><MapPin size={14} aria-hidden="true" /> {[item.organization, item.country].filter(Boolean).join(' · ')}</p>
                  </article>
                );
              })}
            </section>
          )}
          {complete && (
            <section className="cmp-table" aria-label="Scholarship comparison">
              <div className="cmp-row is-head">
                <div className="cmp-row-label cmp-legend"><strong>Side by side</strong></div>
                {opportunities.map((item, index) => (
                  <article key={item.id} className={`cmp-head is-scholarship ${index === 0 ? 'is-first' : 'is-second'}`}>
                    <OpportunityMark item={item} />
                    <div className="cmp-head-copy"><span className="cmp-kind">Scholarship</span><h2>{item.title}</h2><p>{[item.organization, item.country].filter(Boolean).join(' · ')}</p></div>
                    <button type="button" className="cmp-remove" onClick={() => remove(item.id)} aria-label={`Remove ${item.title}`}><X size={15} aria-hidden="true" /></button>
                  </article>
                ))}
              </div>
              <div className="cmp-row is-eligibility">
                <div className="cmp-row-label"><ShieldCheck size={17} aria-hidden="true" /> Your eligibility</div>
                {opportunities.map((item) => <EligibilityCell key={item.id} item={item} />)}
              </div>
              {groups.map((group) => (
                <Fragment key={group.title}>
                  <h3 className="cmp-group">{group.title}</h3>
                  {group.rows.map((row) => (
                    <div key={row.label} className={`cmp-row is-${row.id}`}>
                      <div className="cmp-row-label"><row.icon size={17} aria-hidden="true" /> {row.label}</div>
                      {row.values.map((value, index) => (
                        <ComparisonCell key={opportunities[index].id} row={row} value={value} item={opportunities[index]} />
                      ))}
                    </div>
                  ))}
                </Fragment>
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}
