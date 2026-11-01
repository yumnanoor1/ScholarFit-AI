import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AlertTriangle, ArrowLeft, Bookmark, CalendarDays, CheckCircle2, CircleHelp, Clock3,
  ExternalLink, GraduationCap, Landmark, Languages, MapPin, ShieldCheck, Wallet, XCircle,
} from 'lucide-react';
import { apiService } from '../services/api';
import { fetchProgramScholarships } from '../services/opportunityApi';
import { getOpportunityTitle } from '../services/opportunityJourney';
import { useProfile } from '../context/ProfileContext';
import { useProgramEligibility } from '../hooks/useProgramEligibility';
import {
  describeRequirement, formatVerifiedDate, getBudgetFit, getCountryFit, getDeadlineInfo,
  getFieldFit, getProfileSnapshot, getUniversityLogo,
} from '../services/programFit';
import OfficialApplicationLink from '../components/opportunities/OfficialApplicationLink';
import { OpportunityCompareCheckbox } from '../components/opportunities/ComparisonControls';
import ScholarshipProgramMatches from '../components/opportunities/ScholarshipProgramMatches';
import './UniversityDetails.css';

const OVERALL = {
  satisfied: {
    tone: 'success', icon: CheckCircle2, title: 'You meet the published requirements',
    text: 'Your profile meets every structured minimum this program publishes. Admission is still decided by the university.',
  },
  'missing-information': {
    tone: 'warning', icon: AlertTriangle, title: 'Some profile information is missing',
    text: 'Add the missing details to your profile to see whether you meet every requirement.',
  },
  'not-satisfied': {
    tone: 'danger', icon: XCircle, title: 'You don’t meet every requirement yet',
    text: 'At least one published minimum is above what your profile shows. See the details below.',
  },
  'awaiting-verification': {
    tone: 'neutral', icon: CircleHelp, title: 'Check the requirements yourself',
    text: 'This program doesn’t publish a structured CGPA or English minimum, so it can’t be checked automatically.',
  },
};

const STATUS_ICON = {
  satisfied: { icon: CheckCircle2, tone: 'success', label: 'Met' },
  'not-satisfied': { icon: XCircle, tone: 'danger', label: 'Not met' },
  'missing-information': { icon: AlertTriangle, tone: 'warning', label: 'Missing info' },
  'awaiting-verification': { icon: CircleHelp, tone: 'neutral', label: 'Check' },
};

const FIT_TONE = { within: 'success', over: 'danger', unknown: 'neutral' };

// The seed descriptions end with "Other official sources: a ; b [Tuition in USD ... ]"
function splitDescription(description) {
  if (!description) return { text: '', sources: [], note: '' };
  let text = description;
  let note = '';
  const noteMatch = text.match(/\[([^\]]+)\]\s*$/);
  if (noteMatch) {
    note = noteMatch[1].trim();
    text = text.slice(0, noteMatch.index).trim();
  }
  let sources = [];
  const sourceIndex = text.indexOf('Other official sources:');
  if (sourceIndex >= 0) {
    sources = text.slice(sourceIndex + 'Other official sources:'.length).split(';').map((url) => url.trim()).filter((url) => /^https?:\/\//.test(url));
    text = text.slice(0, sourceIndex).trim();
  }
  return { text, sources, note };
}

// "tum.de/…/language-certificates" style label, so two pages on one site are distinguishable
function sourceLabel(url) {
  try {
    const { hostname, pathname } = new URL(url);
    const host = hostname.replace(/^www\./, '');
    const last = pathname.split('/').filter(Boolean).pop();
    if (!last) return host;
    const page = decodeURIComponent(last).replace(/\.(html?|pdf)$/i, '');
    return `${host}/…/${page.length > 34 ? `${page.slice(0, 34)}…` : page}`;
  } catch {
    return url;
  }
}

export default function UniversityDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const {
    profile, activeOpportunityId, selectOpportunity, appliedOpportunityIds, markOpportunityApplied,
    isOpportunitySaved, toggleSaveOpportunity,
  } = useProfile();
  const [requestResult, setRequestResult] = useState(null);
  const programEligibility = useProgramEligibility(id);

  useEffect(() => {
    let cancelled = false;
    apiService.getOpportunityById(id).then((opportunity) => {
      if (!cancelled) setRequestResult({ id, data: opportunity?.kind === 'program' ? opportunity : null });
    }).catch((error) => {
      console.error('Unable to load university program details.', error);
      if (!cancelled) setRequestResult({ id, error: 'Program details could not be loaded.' });
    });
    return () => { cancelled = true; };
  }, [id]);

  const currentResult = requestResult?.id === id ? requestResult : null;
  const data = currentResult?.data || null;
  const loading = !currentResult || programEligibility.loading;
  const loadError = currentResult?.error || '';
  if (loading) return <div className="page-container program-detail-state" role="status">Loading program details...</div>;
  if (loadError) return <div className="page-container program-detail-state" role="alert">{loadError}</div>;
  if (!data) {
    return (
      <div className="page-container program-detail-state">
        <h1>Program not found</h1>
        <p>This program ID is not available in the current opportunity data.</p>
        <button className="btn btn-outline" onClick={() => navigate('/universities')}>Back to programs</button>
      </div>
    );
  }

  const eligibility = programEligibility.evaluation;
  const overall = OVERALL[eligibility.status] || OVERALL['awaiting-verification'];
  const snapshot = getProfileSnapshot(profile);
  const preferenceChecks = [
    { key: 'budget', label: 'Tuition budget', icon: Wallet, ...getBudgetFit(data, snapshot) },
    { key: 'country', label: 'Preferred country', icon: MapPin, ...getCountryFit(data, snapshot) },
    { key: 'field', label: 'Preferred field', icon: GraduationCap, ...getFieldFit(data, snapshot) },
  ];
  const isActive = activeOpportunityId === data.id;
  const saved = isOpportunitySaved(data.id);
  const deadline = getDeadlineInfo(data.deadline);
  const verified = formatVerifiedDate(data.lastVerified);
  const { text: descriptionText, sources, note } = splitDescription(data.description);
  const backendNotes = eligibility.notes.filter((item) => !/^(Required degree|Program field)/.test(item));
  const facts = [
    { icon: Wallet, label: 'Tuition / year', value: data.tuitionOriginal || data.tuition || 'Not listed', hint: data.tuitionAmount > 0 && data.tuitionCurrency !== 'USD' && data.tuition ? `≈ ${data.tuition.replace(' / year', '')} (converted)` : null },
    { icon: CalendarDays, label: 'Next deadline', value: deadline ? deadline.label : data.deadline || 'Not listed', hint: deadline ? (deadline.passed ? 'Deadline passed' : `${deadline.days} days left`) : null },
    { icon: Clock3, label: 'Duration', value: data.duration || 'Not listed' },
    { icon: Languages, label: 'Language', value: data.language || 'Not listed' },
    { icon: GraduationCap, label: 'Degree', value: data.degree || 'Not listed' },
    { icon: ShieldCheck, label: 'Last verified', value: verified || 'Not recorded' },
  ];

  return (
    <div className="page-container program-detail">
      <Link to="/universities" className="program-detail-back"><ArrowLeft size={16} aria-hidden="true" /> Back to programs</Link>

      <header className="program-detail-hero">
        <span className={`program-detail-mark ${getUniversityLogo(data.university) ? 'has-logo' : ''}`} aria-hidden="true">
          {getUniversityLogo(data.university)
            ? <img src={getUniversityLogo(data.university)} alt="" decoding="async" />
            : <Landmark size={26} />}
        </span>
        <div className="program-detail-heading">
          <h1>{getOpportunityTitle(data)}</h1>
          <p>{data.university}{data.city ? ` · ${data.city}` : ''} · {data.country}</p>
          <div className="program-detail-tags">
            {data.degree && <span>{data.degree}</span>}
            {data.fieldOfStudy && <span>{data.fieldOfStudy}</span>}
            {data.language && <span>Taught in {data.language}</span>}
          </div>
        </div>
        <div className="program-detail-actions">
          <button type="button" className="btn btn-primary" onClick={() => selectOpportunity({ ...data, kind: 'program' })}>
            {isActive ? 'In your journey' : 'Start this journey'}
          </button>
          <button
            type="button"
            className={`program-detail-icon-button ${saved ? 'is-saved' : ''}`}
            aria-pressed={saved}
            onClick={() => toggleSaveOpportunity(data.id)}
          >
            <Bookmark size={16} fill={saved ? 'currentColor' : 'none'} aria-hidden="true" /> {saved ? 'Saved' : 'Save'}
          </button>
          <OpportunityCompareCheckbox opportunity={{ ...data, title: data.program }} />
          {data.sourceUrl && (
            <a className="program-detail-link" href={data.sourceUrl} target="_blank" rel="noopener noreferrer">
              Official program page <ExternalLink size={14} aria-hidden="true" />
            </a>
          )}
        </div>
      </header>

      <div className="program-detail-layout">
        <div className="program-detail-main">
          <section className="program-detail-card" aria-labelledby="fit-title">
            <h2 id="fit-title">Your fit for this program</h2>
            <div className={`program-fit-summary is-${overall.tone}`}>
              <overall.icon size={22} aria-hidden="true" />
              <div>
                <strong>{overall.title}</strong>
                <p>{eligibility.source === 'unavailable' ? eligibility.message : overall.text}</p>
              </div>
            </div>
            {eligibility.source === 'unavailable' && (
              <Link className="btn btn-outline program-fit-cta" to="/profile">Complete your profile</Link>
            )}

            {eligibility.requirements.length > 0 && (
              <div className="program-fit-table" role="table" aria-label="Requirements compared with your profile">
                <div className="program-fit-row is-head" role="row">
                  <span role="columnheader">Requirement</span>
                  <span role="columnheader">Program needs</span>
                  <span role="columnheader">Your profile</span>
                  <span role="columnheader">Status</span>
                </div>
                {eligibility.requirements.map((requirement) => {
                  const { needs, yours } = describeRequirement(requirement, data, snapshot);
                  const status = STATUS_ICON[requirement.status] || STATUS_ICON['awaiting-verification'];
                  return (
                    <div className="program-fit-row" role="row" key={requirement.id}>
                      <span role="cell" className="program-fit-name">{requirement.label}</span>
                      <span role="cell" data-label="Program needs">{needs}</span>
                      <span role="cell" data-label="Your profile">{yours}</span>
                      <span role="cell" className={`program-fit-status is-${status.tone}`}>
                        <status.icon size={15} aria-hidden="true" /> {status.label}
                      </span>
                      {requirement.message && <span className="program-fit-message">{requirement.message}</span>}
                    </div>
                  );
                })}
              </div>
            )}

            <h3 className="program-detail-subheading">Your preferences</h3>
            <ul className="program-pref-list">
              {preferenceChecks.map((check) => (
                <li key={check.key} className={`is-${FIT_TONE[check.status]}`}>
                  <span className="program-pref-icon" aria-hidden="true"><check.icon size={16} /></span>
                  <div>
                    <strong>{check.label}</strong>
                    <p>{check.message}</p>
                  </div>
                </li>
              ))}
            </ul>

            {backendNotes.length > 0 && (
              <ul className="program-detail-notes">
                {backendNotes.map((item) => <li key={item}>{item}</li>)}
              </ul>
            )}
          </section>

          <section className="program-detail-card" aria-labelledby="admission-title">
            <h2 id="admission-title">Admission details</h2>
            {data.requiredDegree && (
              <div className="program-detail-block">
                <h3>Required background</h3>
                <p>{data.requiredDegree}</p>
              </div>
            )}
            {descriptionText && (
              <div className="program-detail-block">
                <h3>Program information</h3>
                <p>{descriptionText}</p>
              </div>
            )}
            {note && <p className="program-detail-footnote">{note}</p>}
          </section>

          {/^\d+$/.test(id) && (
            <section className="program-detail-card" aria-labelledby="scholarships-title">
              <h2 id="scholarships-title">Scholarships for this program</h2>
              <ScholarshipProgramMatches load={fetchProgramScholarships} recordId={id} side="scholarship" />
            </section>
          )}
        </div>

        <aside className="program-detail-side">
          <section className="program-detail-card" aria-labelledby="facts-title">
            <h2 id="facts-title">Key facts</h2>
            <dl className="program-facts">
              {facts.map((fact) => (
                <div key={fact.label}>
                  <dt><fact.icon size={15} aria-hidden="true" /> {fact.label}</dt>
                  <dd>{fact.value}{fact.hint && <small>{fact.hint}</small>}</dd>
                </div>
              ))}
            </dl>
          </section>

          {(data.sourceUrl || sources.length > 0) && (
            <section className="program-detail-card" aria-labelledby="sources-title">
              <h2 id="sources-title">Official sources</h2>
              <ul className="program-sources">
                {[data.sourceUrl, ...sources].filter(Boolean).map((url) => (
                  <li key={url}>
                    <a href={url} target="_blank" rel="noopener noreferrer">
                      {sourceLabel(url)} <ExternalLink size={12} aria-hidden="true" />
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <OfficialApplicationLink
            opportunity={data}
            applied={appliedOpportunityIds.includes(data.id)}
            onToggleApplied={(value) => markOpportunityApplied(data.id, value)}
          />
        </aside>
      </div>
    </div>
  );
}
