import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft, BookOpen, Bookmark, CalendarDays, CheckCircle2, CircleAlert, CircleHelp,
  Clock, FileText, Globe2, GraduationCap, Languages, Layers, Link2, ShieldCheck, Wallet,
} from 'lucide-react';
import { apiService } from '../services/api';
import { getOpportunityTitle } from '../services/opportunityJourney';
import { useProfile } from '../context/ProfileContext';
import OfficialApplicationLink from '../components/opportunities/OfficialApplicationLink';
import EligibilityBadge from '../components/opportunities/EligibilityBadge';
import { useScholarshipEligibility } from '../hooks/useScholarshipEligibility';
import { getScholarshipDeadlineLabel } from '../services/eligibilityBadges';
import { parseScholarshipId } from '../services/opportunityApi';
import ScholarshipRecommendationCard from '../components/opportunities/ScholarshipRecommendationCard';
import { OpportunityCompareCheckbox } from '../components/opportunities/ComparisonControls';
import SavedStatusNotice from '../components/opportunities/SavedStatusNotice';
import './Universities.css';
import './UniversityDetails.css';

// Per-requirement result labels (the overall result uses EligibilityBadge)
const REQUIREMENT_LABELS = {
  satisfied: { label: 'Met', tone: 'success', icon: CheckCircle2 },
  'not-satisfied': { label: 'Not met', tone: 'danger', icon: CircleAlert },
  'missing-information': { label: 'Missing info', tone: 'warning', icon: CircleAlert },
  'awaiting-verification': { label: 'Verify manually', tone: 'neutral', icon: CircleHelp },
};

const INFO_ICONS = [
  [/deadline|open|clos/i, CalendarDays],
  [/degree|academic|field|study/i, GraduationCap],
  [/english|language/i, Languages],
  [/nationality|citizen|country/i, Globe2],
  [/document|application|nomination/i, FileText],
  [/fund|tuition|stipend|travel|coverage/i, Wallet],
];

const UNAVAILABLE_NOTICES = {
  'logged-out': ['Log in to check eligibility.', '/login', 'Log in'],
  'no-profile': ['Complete your profile to check eligibility.', '/profile', 'Complete profile'],
};

function InfoValue({ value }) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (text.length <= 110) return text;
  const summary = `${text.slice(0, 107).replace(/\s+\S*$/, '')}…`;
  return (
    <details className="sd-value-details">
      <summary title={text}>{summary}</summary>
      <p>{text}</p>
    </details>
  );
}

function FactValue({ label, value }) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  let summary = '';

  if (label === 'Funding scope' && /full.*(?:participation|tuition)|(?:participation|tuition).*full/i.test(text)) {
    summary = 'Full tuition and participation costs covered.';
  } else if (label === 'Application deadline' && /individually by each (?:consortium|course)/i.test(text) && /october.*january/i.test(text)) {
    summary = 'Varies by course; applications usually open Oct–Jan.';
  } else if (label === 'Duration') {
    const match = text.match(/(\d+\s*[-–]\s*\d+)\s*academic years?.*?\(([\d,\sor]+)\s*ECTS credits?\)/i);
    if (match) summary = `${match[1].replace(/\s*-\s*/, '–')} years; ${match[2].replace(/\s+or\s+/i, ' or ')} ECTS.`;
  }

  if (!summary || summary === text) return <InfoValue value={value} />;
  return (
    <details className="sd-value-details">
      <summary>{summary}</summary>
      <p>{text}</p>
    </details>
  );
}

function InfoList({ rows }) {
  return (
    <dl className="sd-info">
      {rows.map(([label, value]) => {
        const Icon = INFO_ICONS.find(([pattern]) => pattern.test(label))?.[1] || BookOpen;
        return (
          <div key={label}>
            <dt><Icon size={14} aria-hidden="true" />{label}</dt>
            <dd><InfoValue value={value} /></dd>
          </div>
        );
      })}
    </dl>
  );
}

function CompactInfoList({ rows, previewCount = 4 }) {
  const preview = rows.slice(0, previewCount);
  const remaining = rows.slice(previewCount);
  return (
    <>
      <InfoList rows={preview} />
      {remaining.length > 0 && (
        <details className="sd-details">
          <summary>Show {remaining.length} more</summary>
          <InfoList rows={remaining} />
        </details>
      )}
    </>
  );
}

function Section({ title, icon: Icon = BookOpen, children }) {
  return (
    <section className="sd-section">
      <h2><Icon size={17} aria-hidden="true" />{title}</h2>
      {children}
    </section>
  );
}
export default function ScholarshipDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const {
    activeOpportunityId, selectOpportunity, isOpportunitySaved, toggleSaveOpportunity,
  } = useProfile();
  const [requestResult, setRequestResult] = useState(null);
  // Backend scholarships (sch-db-N) are evaluated by GET /eligibility/scholarships/{id}
  const isBackendId = parseScholarshipId(id) != null;
  const backendEligibility = useScholarshipEligibility(id);

  useEffect(() => {
    let cancelled = false;
    apiService.getOpportunityById(id).then((opportunity) => {
      if (!cancelled) setRequestResult({ id, data: opportunity?.kind === 'scholarship' ? opportunity : null });
    }).catch((error) => {
      console.error('Unable to load scholarship details.', error);
      if (!cancelled) setRequestResult({ id, error: 'Scholarship details could not be loaded.' });
    });
    return () => { cancelled = true; };
  }, [id]);

  const currentResult = requestResult?.id === id ? requestResult : null;
  const data = currentResult?.data || null;
  const loading = !currentResult;
  const loadError = currentResult?.error || '';
  if (loading) return <div className="page-container" role="status">Loading scholarship details...</div>;
  if (loadError) return <div className="page-container" role="alert">{loadError}</div>;
  if (!data) {
    return (
      <div className="page-container">
        <h1>Scholarship not found</h1>
        <p>This scholarship ID is not available in the current opportunity data.</p>
        <button className="btn btn-outline" onClick={() => navigate('/scholarships')}>Back to Scholarships</button>
      </div>
    );
  }

  const eligibility = backendEligibility.evaluation;
  const eligibilityState = backendEligibility.state;
  const deadline = getScholarshipDeadlineLabel(eligibility?.deadline);
  const isActive = activeOpportunityId === data.id;
  const saved = isOpportunitySaved(data.id);
  const requirementRows = [
    ['Degree level', data.degree],
    ['Eligible nationalities', data.eligibleNationalities],
    ['Open to Pakistani students', data.pakistanEligible],
    ['Eligible fields', data.eligibleFields],
    ['Academic requirement', data.academicRequirement],
    ["Bachelor's degree", data.bachelorsRequirement],
    ['English requirement', data.englishRequirement],
    ['Work experience', data.workExperience],
    ['Age requirement', data.ageRequirement],
  ].filter(([, value]) => value);
  const applicationRows = [
    ...(data.deadlineRows || []),
    ['Application method', data.applicationMethod],
    ['Admission required first', data.admissionRequired],
    ['Nomination required', data.nominationRequired],
    ['Required documents', data.requiredDocumentsText],
    ['Application pathway', data.applicationPathwayText],
    ['Notes', data.notes],
  ].filter(([, value]) => value);

  const benefitRows = (data.benefits || []).map((benefit) => [benefit.label, benefit.value]);
  const facts = [
    { label: 'Funding type', icon: Wallet, value: data.type || 'Not available' },
    { label: 'Funding scope', icon: Layers, value: data.coverage || 'Not available' },
    {
      label: 'Application deadline',
      icon: CalendarDays,
      value: deadline?.label || data.deadline || 'Not available',
      note: deadline?.note,
    },
    data.duration && { label: 'Duration', icon: Clock, value: data.duration },
  ].filter(Boolean);

  return (
    <div className="page-container scholarship-detail-page">
      <button type="button" className="sd-back" onClick={() => navigate('/scholarships')}>
        <ArrowLeft size={16} aria-hidden="true" /> Back to Scholarships
      </button>

      <header className="sd-hero">
        <h1 className="sd-title">{getOpportunityTitle(data)}</h1>
        <p className="sd-subtitle">{data.provider || 'Provider not listed'} · {data.country || 'Country not listed'}</p>
        <div className="sd-hero-actions">
          <button type="button" className="btn btn-primary" onClick={() => selectOpportunity({ ...data, kind: 'scholarship' })}>
            {isActive ? 'Currently in your journey' : 'Select this scholarship'}
          </button>
          {/* An archived scholarship can be removed from Saved but not newly added */}
          {(!data.archived || saved) && (
            <button
              type="button"
              className={`program-detail-icon-button ${saved ? 'is-saved' : ''}`}
              aria-pressed={saved}
              onClick={() => toggleSaveOpportunity(data.id)}
            >
              <Bookmark size={16} fill={saved ? 'currentColor' : 'none'} aria-hidden="true" /> {saved ? 'Saved' : 'Save'}
            </button>
          )}
          {!data.archived && <OpportunityCompareCheckbox opportunity={{ ...data, title: data.name }} />}
        </div>
      </header>

      <SavedStatusNotice />
      {data.archived && <p className="saved-unverified-warning">This scholarship is no longer listed, so its details may be out of date.</p>}
      {data.sourceStatus !== 'official-verified' && (
        <p className="saved-unverified-warning">Not verified. Check details with the provider before applying.</p>
      )}
      {data.duplicateOf && (
        <p className="scholarship-eligibility-note">
          Possible duplicate. <Link to={`/scholarships/${data.duplicateOf}`}>View the other listing</Link>.
        </p>
      )}

      <dl className="sd-facts">
        {facts.map(({ label, icon: Icon, value, note }) => (
          <div key={label}>
            <span className="sd-fact-icon" aria-hidden="true"><Icon size={18} /></span>
            <div>
              <dt>{label}</dt>
              <dd><FactValue label={label} value={value} /></dd>
              {note && <dd className="sd-fact-note"><InfoValue value={note} /></dd>}
            </div>
          </div>
        ))}
      </dl>

      <div className="sd-layout">
        <div className="sd-main">
          {isBackendId && (
            <section className="sd-section" aria-live="polite">
              <h2><ShieldCheck size={17} aria-hidden="true" />Your eligibility</h2>
              {backendEligibility.loading ? (
                <p role="status">Checking eligibility…</p>
              ) : eligibilityState !== 'ok' ? (
                <p className="university-notice" role="status">
                  <span>{UNAVAILABLE_NOTICES[eligibilityState]?.[0] || eligibility?.message || 'Eligibility could not be checked right now.'}</span>
                  {UNAVAILABLE_NOTICES[eligibilityState] && (
                    <Link to={UNAVAILABLE_NOTICES[eligibilityState][1]}>{UNAVAILABLE_NOTICES[eligibilityState][2]}</Link>
                  )}
                </p>
              ) : (
                <>
                  <div className="scholarship-eligibility-summary">
                    <EligibilityBadge status={eligibility.status} />
                    <span>{eligibility.summary}</span>
                  </div>
                  <ul className="scholarship-requirement-list">
                    {eligibility.requirements.map((item) => {
                      const badge = REQUIREMENT_LABELS[item.status] || REQUIREMENT_LABELS['awaiting-verification'];
                      const StatusIcon = badge.icon;
                      return (
                        <li key={item.id}>
                          <span className={`program-status is-${badge.tone}`}><StatusIcon size={13} aria-hidden="true" />{badge.label}</span>
                          <div>
                            <strong>{item.label}</strong>
                            {(item.message || item.sourceText) && (
                              <details className="sd-details">
                                <summary>Details</summary>
                                {item.message && <p>{item.message}</p>}
                                {item.sourceText && <p><strong>Source:</strong> {item.sourceText}</p>}
                              </details>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                  {eligibility.notes.length > 0 && (
                    <details className="sd-details">
                      <summary>{eligibility.notes.length} additional note{eligibility.notes.length === 1 ? '' : 's'}</summary>
                      <ul className="sd-note-list">{eligibility.notes.map((note) => <li key={note}>{note}</li>)}</ul>
                    </details>
                  )}
                </>
              )}
            </section>
          )}

          {isBackendId && <ScholarshipRecommendationCard scholarshipId={id} />}

          {data.requirementSummaryRows && (
            <Section title="Key requirements" icon={GraduationCap}>
              <CompactInfoList rows={data.requirementSummaryRows} previewCount={6} />
            </Section>
          )}

          {(data.fundingRows || benefitRows.length > 0) && (
            <Section title="What it covers" icon={Wallet}>
              <CompactInfoList rows={data.fundingRows || benefitRows} previewCount={4} />
              {data.fundingRows && benefitRows.length > 0 && (
                <details className="sd-details">
                  <summary>Original funding wording</summary>
                  <InfoList rows={benefitRows} />
                </details>
              )}
            </Section>
          )}

          {(!isBackendId || eligibilityState !== 'ok') && !data.requirementSummaryRows && (
            <Section title="Requirements" icon={GraduationCap}>
              {requirementRows.length > 0
                ? <CompactInfoList rows={requirementRows} previewCount={6} />
                : <p>{eligibility?.message || 'No structured scholarship requirements are available. Verify eligibility directly with the provider.'}</p>}
            </Section>
          )}

          {applicationRows.length > 0 && (
            <Section title="Applying" icon={FileText}>
              <CompactInfoList rows={applicationRows} previewCount={4} />
            </Section>
          )}

        </div>

        <aside className="sd-aside">
          <OfficialApplicationLink opportunity={data} />

          {data.officialLinks?.length > 0 && (
            <Section title="Official links" icon={Link2}>
              <ul className="sd-links">
                {data.officialLinks.map((link) => (
                  <li key={link.url}>
                    <a href={link.url} target="_blank" rel="noopener noreferrer">{link.label}</a>
                  </li>
                ))}
              </ul>
            </Section>
          )}

        </aside>
      </div>
    </div>
  );
}
