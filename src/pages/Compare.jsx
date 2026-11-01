import { useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowRight, Award, Bookmark, Briefcase, Building2, CalendarDays, Check, Clock, DollarSign,
  GraduationCap, Languages, MapPin, Plus, Search, ShieldCheck, Trophy, X,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import SavedStatusNotice from '../components/opportunities/SavedStatusNotice';
import UniversityLogo from '../components/common/UniversityLogo';
import EligibilityBadge from '../components/opportunities/EligibilityBadge';
import { useOpportunityCatalog } from '../hooks/useOpportunityCatalog';
import { useProgramEligibility, useScholarshipEligibilities } from '../hooks/useProgramEligibility';
import { getEligibilityReason, getScholarshipDeadlineLabel } from '../services/eligibilityBadges';
import { parseScholarshipId } from '../services/opportunityApi';
import { getDeadlineInfo, getScholarshipLogo } from '../services/programFit';
import './Universities.css';
import './Compare.css';

function parseIelts(item) {
  if (item.minIelts != null) return Number(item.minIelts);
  const match = String(item.englishReq || '').match(/IELTS\s*(\d+(?:\.\d+)?)/i);
  return match ? Number(match[1]) : null;
}

function parseTuitionUsd(item) {
  if (item.tuitionUsd != null) return Number(item.tuitionUsd);
  const amount = Number(String(item.tuition || '').replace(/[^\d.]/g, ''));
  return item.tuition && Number.isFinite(amount) ? amount : null;
}

function formatDeadline(item) {
  // Scholarships use the deadline the eligibility engine worked out, so it matches the details page
  if (item.evaluation?.deadline) {
    const label = getScholarshipDeadlineLabel(item.evaluation.deadline);
    return label ? { text: label.label, note: label.note } : { text: item.deadline || null };
  }
  const info = getDeadlineInfo(item.deadlineDate || item.deadline);
  if (!info) return { text: item.deadline || null };
  return { text: info.label, note: info.passed ? 'Deadline passed' : `${info.days} days left` };
}

/**
 * Rows of the comparison table. Each row returns, per opportunity, a display value
 * and optionally a number used to mark the better side ("lower" wins).
 */
const ROWS = [
  {
    id: 'cost',
    label: 'Tuition / funding',
    icon: DollarSign,
    better: 'lower',
    betterLabel: 'Lower cost',
    value: (item) => (item.kind === 'scholarship'
      ? { text: item.coverageSummary || item.coverage, note: item.type }
      : {
        text: item.tuitionOriginal || item.tuition,
        note: item.tuitionAmount === 0
          ? null
          : item.tuitionOriginal && item.tuition && item.tuitionCurrency !== 'USD' ? `≈ ${item.tuition}` : 'per year',
        number: parseTuitionUsd(item),
      }),
  },
  { id: 'deadline', label: 'Application deadline', icon: CalendarDays, value: formatDeadline },
  {
    id: 'duration',
    label: 'Duration',
    icon: Clock,
    value: (item) => ({ text: item.duration || (item.durationMonths ? `${item.durationMonths} months` : null) }),
  },
  {
    id: 'academic',
    label: 'Academic requirement',
    icon: GraduationCap,
    better: 'lower',
    betterLabel: 'Easier to meet',
    value: (item) => (item.kind === 'scholarship'
      ? { text: item.academicSummary || item.academicRequirement }
      : { text: item.cgpaReq ? `Minimum CGPA ${item.cgpaReq}` : null, number: item.cgpaReq ? Number(item.cgpaReq) : null }),
  },
  {
    id: 'english',
    label: 'English requirement',
    icon: Languages,
    better: 'lower',
    betterLabel: 'Easier to meet',
    value: (item) => (item.kind === 'scholarship'
      ? { text: item.englishSummary || item.englishRequirement }
      : { text: item.englishReq, note: item.language ? `Taught in ${item.language}` : null, number: parseIelts(item) }),
  },
  {
    id: 'audience',
    label: 'Who can apply',
    icon: Award,
    value: (item) => (item.kind === 'scholarship'
      ? { text: item.audienceSummary || item.eligibleNationalities }
      : { text: item.requiredDegree || item.fieldOfStudy, note: item.degree }),
  },
];

// Index of the opportunity with the better number, or -1 when they can't be compared fairly
function betterIndex(row, values) {
  if (!row.better) return -1;
  const numbers = values.map((value) => value.number);
  if (numbers.some((number) => number == null || !Number.isFinite(number)) || numbers[0] === numbers[1]) return -1;
  return numbers[0] < numbers[1] ? 0 : 1;
}

function OpportunityMark({ item, size = 56 }) {
  const Icon = item.type === 'RA' ? Briefcase : Building2;
  return item.kind === 'scholarship'
    ? (
      <UniversityLogo
        src={getScholarshipLogo(item)}
        size={size}
        bareFallback
        fallback={<span className="cmp-mark is-scholarship" style={{ '--mark-size': `${size}px` }} aria-hidden="true"><Icon size={Math.round(size * 0.45)} /></span>}
      />
    )
    : <UniversityLogo university={item.university} size={size} fallback={<GraduationCap size={Math.round(size * 0.45)} />} />;
}

export default function Compare() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    isOpportunitySaved,
    toggleSaveOpportunity,
    savedOpportunities,
    comparisonOpportunityIds,
    toggleComparisonOpportunity,
    clearComparisonOpportunities,
    activeOpportunityId,
    selectOpportunity,
  } = useProfile();
  const compareIds = useMemo(
    () => (searchParams.get('ids') ?? comparisonOpportunityIds.join(','))
      .split(',')
      .filter(Boolean)
      .slice(0, 2),
    [searchParams, comparisonOpportunityIds],
  );
  const catalog = useOpportunityCatalog();
  const programEligibility = useProgramEligibility();
  const scholarshipEligibility = useScholarshipEligibilities(compareIds.filter((id) => parseScholarshipId(id) != null));
  // Compared IDs resolved against backend programs and scholarships (older sample IDs still resolve)
  const opportunities = compareIds
    .map((id) => catalog.getOpportunity(id))
    .filter(Boolean)
    .map((item) => (item.kind === 'scholarship'
      ? { ...item, title: item.name, organization: item.provider, evaluation: scholarshipEligibility.getEvaluation(item.id) }
      : { ...item, kind: 'program', title: item.program, organization: item.university, evaluation: programEligibility.getEvaluation(item.id) }));

  const removeOpportunity = (id) => {
    if (comparisonOpportunityIds.includes(id)) toggleComparisonOpportunity(id);
    if (searchParams.get('ids')) {
      const rest = compareIds.filter((item) => item !== id);
      setSearchParams(rest.length ? { ids: rest.join(',') } : {}, { replace: true });
    }
  };
  const clearAll = () => {
    clearComparisonOpportunities();
    if (searchParams.get('ids')) setSearchParams({}, { replace: true });
  };
  const detailsRoute = (item) => (item.kind === 'scholarship' ? `/scholarships/${item.id}` : `/universities/${item.id}`);
  const isComplete = opportunities.length === 2;
  const usesSampleData = opportunities.some((item) => item.sourceStatus === 'unverified-sample');

  return (
    <div className={`page-container cmp-page ${isComplete ? '' : 'is-waiting'}`}>
      <header className="cmp-header">
        <div className="cmp-header-copy">
          <h1>Compare opportunities</h1>
          <p>Put two programs or scholarships next to each other and see where they differ.</p>
        </div>
        <div className="cmp-header-actions">
          <button type="button" className="cmp-ghost-button" onClick={() => navigate('/saved')}>
            <Bookmark size={15} aria-hidden="true" /> Saved <span>{savedOpportunities.length}</span>
          </button>
          {opportunities.length > 0 && (
            <button type="button" className="cmp-ghost-button" onClick={clearAll}>
              <X size={15} aria-hidden="true" /> Clear comparison
            </button>
          )}
        </div>
      </header>
      <SavedStatusNotice />

      {catalog.loading && compareIds.length > 0 ? (
        <p className="cmp-status" role="status">Loading your comparison...</p>
      ) : (
        <>
          {/* The two opportunities facing each other; empty slots invite a pick */}
          <section className="cmp-versus" aria-label="Opportunities being compared">
            {[0, 1].map((slot) => {
              const item = opportunities[slot];
              if (!item) {
                return (
                  <div key={`empty-${slot}`} className="cmp-slot is-empty">
                    <span className="cmp-slot-plus" aria-hidden="true"><Plus size={26} /></span>
                    <strong>{slot === 0 || opportunities.length === 0 ? 'Add an opportunity' : 'Add one more to compare'}</strong>
                    <p>Tick <em>Compare</em> on any program or scholarship in Explore.</p>
                    <div className="cmp-slot-actions">
                      <button type="button" className="cmp-primary-button" onClick={() => navigate('/universities')}>
                        <Search size={15} aria-hidden="true" /> Browse programs
                      </button>
                      <button type="button" className="cmp-ghost-button" onClick={() => navigate('/scholarships')}>
                        Scholarships
                      </button>
                    </div>
                  </div>
                );
              }
              return (
                <article key={item.id} className={`cmp-slot is-${item.kind}`}>
                  <button type="button" className="cmp-remove" onClick={() => removeOpportunity(item.id)} aria-label={`Remove ${item.title} from comparison`}>
                    <X size={16} aria-hidden="true" />
                  </button>
                  <OpportunityMark item={item} />
                  <span className="cmp-kind">{item.kind === 'scholarship' ? 'Scholarship' : "Master's program"}</span>
                  <h2>{item.title}</h2>
                  <p><MapPin size={14} aria-hidden="true" /> {[item.organization, item.country].filter(Boolean).join(' · ')}</p>
                </article>
              );
            })}
            <span className="cmp-vs" aria-hidden="true">VS</span>
          </section>

          {isComplete && (
            <>
              <section className="cmp-table" aria-label="Comparison details">
                <div className="cmp-row is-eligibility">
                  <div className="cmp-row-label"><ShieldCheck size={17} aria-hidden="true" /> Your eligibility</div>
                  {opportunities.map((item) => (
                    <div key={item.id} className="cmp-cell">
                      <EligibilityBadge status={item.evaluation.status} />
                      {item.kind === 'scholarship' && !scholarshipEligibility.loading && <small>{getEligibilityReason(item.evaluation)}</small>}
                    </div>
                  ))}
                </div>
                {ROWS.map((row) => {
                  const values = opportunities.map((item) => row.value(item));
                  if (values.every((value) => !value.text)) return null;
                  const winner = betterIndex(row, values);
                  return (
                    <div key={row.id} className="cmp-row">
                      <div className="cmp-row-label"><row.icon size={17} aria-hidden="true" /> {row.label}</div>
                      {values.map((value, index) => (
                        <div key={opportunities[index].id} className={`cmp-cell ${winner === index ? 'is-better' : ''}`}>
                          <strong className={value.text ? '' : 'is-missing'}>{value.text || 'Not listed'}</strong>
                          {value.note && <small>{value.note}</small>}
                          {winner === index && <span className="cmp-better"><Trophy size={12} aria-hidden="true" /> {row.betterLabel}</span>}
                        </div>
                      ))}
                    </div>
                  );
                })}
                <div className="cmp-row is-actions">
                  <div className="cmp-row-label" aria-hidden="true" />
                  {opportunities.map((item) => {
                    const saved = isOpportunitySaved(item.id);
                    const isActive = activeOpportunityId === item.id;
                    return (
                      <div key={item.id} className="cmp-cell cmp-actions">
                        <button type="button" className="cmp-primary-button" onClick={() => navigate(detailsRoute(item))}>
                          View details <ArrowRight size={15} aria-hidden="true" />
                        </button>
                        <div className="cmp-actions-row">
                          <button
                            type="button"
                            className={`cmp-ghost-button ${isActive ? 'is-on' : ''}`}
                            aria-pressed={isActive}
                            onClick={() => selectOpportunity({ ...item })}
                          >
                            {isActive ? <><Check size={15} aria-hidden="true" /> In your journey</> : 'Select for journey'}
                          </button>
                          <button
                            type="button"
                            className={`cmp-icon-button ${saved ? 'is-on' : ''}`}
                            aria-pressed={saved}
                            aria-label={`${saved ? 'Remove saved' : 'Save'} ${item.title}`}
                            onClick={() => toggleSaveOpportunity(item.id)}
                          >
                            <Bookmark size={16} fill={saved ? 'currentColor' : 'none'} aria-hidden="true" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
              <p className="cmp-footnote">
                {usesSampleData
                  ? 'Some of this listing data is unverified demo data; confirm details with each provider.'
                  : 'Listing data comes from the FitScholars database. “Lower cost” and “Easier to meet” only compare listed values; confirm current details with each provider.'}
              </p>
            </>
          )}
        </>
      )}
    </div>
  );
}
