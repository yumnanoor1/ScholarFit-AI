import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Bookmark, Briefcase, Building2, ChevronRight, Info } from 'lucide-react';
import { ComparisonSelectionBar, OpportunityCompareCheckbox } from '../components/opportunities/ComparisonControls';
import EligibilityBadge from '../components/opportunities/EligibilityBadge';
import ScholarshipFilters from '../components/opportunities/ScholarshipFilters';
import { getEligibilityLabel, getEligibilityReason, getScholarshipDeadlineLabel } from '../services/eligibilityBadges';
import { mapScholarshipToFrontend } from '../services/opportunityApi';
import { EMPTY_FILTERS, PAGE_SIZE, buildSearchQuery, getPageCount } from '../services/scholarshipSearch';
import MatchRing from '../components/opportunities/MatchRing';
import { apiService } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import SavedStatusNotice from '../components/opportunities/SavedStatusNotice';
import { useEligibilityProfileKey, useScholarshipEligibility } from '../hooks/useScholarshipEligibility';
import { getScholarshipLogo } from '../services/scholarshipLogos';
import ScholarshipLogo from '../components/common/ScholarshipLogo';
import './Universities.css';
import './Scholarships.css';

// Icon colour per funding type
const FUNDING_TONES = {
  'Fully Funded': 'blue',
  'Partially Funded': 'cyan',
  'Mixed Funding': 'cyan',
  'Tuition Only': 'navy',
  RA: 'cyan',
  Fellowship: 'navy',
};

// Shown above the table when eligibility can't be checked at all
const SEARCH_DELAY_MS = 300;

const ELIGIBILITY_NOTICES = {
  'logged-out': 'Log in to see which scholarships you are eligible for.',
  'no-profile': 'Complete your profile to see which scholarships you are eligible for.',
  error: 'Eligibility could not be checked right now. Please try again later.',
};

// "European Union (multi-country, hosted …)" -> "European Union" for rows
function shortCountry(country) {
  return String(country || '').replace(/\s*\(.*\)\s*$/, '') || country;
}

export default function Scholarships() {
  const navigate = useNavigate();
  const {
    savedOpportunities,
    toggleSaveOpportunity,
    activeOpportunityId,
    comparisonOpportunityIds,
  } = useProfile();

  const { token } = useAuth();
  const profileKey = useEligibilityProfileKey('scholarship');
  const eligibility = useScholarshipEligibility();
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [searchText, setSearchText] = useState('');
  const [sort, setSort] = useState('');
  const [page, setPage] = useState(1);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [options, setOptions] = useState(null);
  const [result, setResult] = useState(null);
  const [retry, setRetry] = useState(0);
  const query = buildSearchQuery(filters, { sort, page });
  const requestKey = `${token || ''}|${query}|${profileKey}|${retry}`;

  // Any change to what's being asked for goes back to the first page
  const changeFilters = useCallback((next) => { setFilters(next); setPage(1); }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      setFilters((current) => (current.q === searchText ? current : { ...current, q: searchText }));
      setPage((current) => (filters.q === searchText ? current : 1));
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [searchText, filters.q]);

  useEffect(() => {
    let isCurrent = true;
    apiService.getScholarshipFilterOptions()
      .then((data) => { if (isCurrent) setOptions(data); })
      .catch((error) => console.warn('Filter options are unavailable.', error?.message));
    return () => { isCurrent = false; };
  }, []);

  useEffect(() => {
    let isCurrent = true;
    apiService.searchScholarships(query, token)
      .then((data) => { if (isCurrent) setResult({ key: requestKey, data }); })
      .catch((error) => {
        console.error('Unable to search scholarships.', error);
        if (isCurrent) setResult({ key: requestKey, error: 'Scholarships could not be loaded. Please try again.' });
      });
    return () => { isCurrent = false; };
  }, [requestKey, query, token]);

  const current = result?.key === requestKey ? result : null;
  const loading = !current;
  const loadError = current?.error || '';
  const data = current?.data || null;
  // The last results stay in the count while a new search runs
  const total = data?.total ?? result?.data?.total ?? 0;
  const signedIn = Boolean(token);

  const visibleScholarships = (data?.items || []).map(({ scholarship, deadline, ...entry }) => {
    const item = mapScholarshipToFrontend(scholarship);
    return {
      ...item,
      ...entry,
      deadlineResult: deadline,
      kind: 'scholarship',
      title: item.name,
      fundingType: item.type,
      coverage: item.coverageSummary || item.coverage || 'Not listed',
      match: entry.score,
      evaluation: eligibility.getEvaluation(item.id),
      icon: item.type === 'RA' ? <Briefcase size={20} /> : <Building2 size={20} />,
      tone: FUNDING_TONES[item.type] || 'blue',
    };
  });

  const clearAll = () => {
    setSearchText('');
    changeFilters(EMPTY_FILTERS);
  };

  return (
    <div className="page-container scholarship-page" style={{ maxWidth: '1240px', margin: '0 auto', position: 'relative' }}>
      
      <ScholarshipFilters
        searchText={searchText}
        onSearchText={setSearchText}
        filters={filters}
        onChange={(next) => { setSearchText(next.q); changeFilters(next); }}
        options={options}
        sort={sort}
        onSortChange={(value) => { setSort(value); setPage(1); }}
        total={loadError ? null : total}
        loading={loading}
        signedIn={signedIn}
        open={filtersOpen}
        onToggle={() => setFiltersOpen((value) => !value)}
        onClear={clearAll}
      />

      <section className={comparisonOpportunityIds.length > 0 ? 'has-comparison-selection' : ''} aria-label="Scholarships" aria-live="polite">
        <SavedStatusNotice />
        {!loading && !loadError && eligibility.state && eligibility.state !== 'ok' && (
          <p className="university-notice" role="status">
            <Info size={16} aria-hidden="true" />
            <span>{ELIGIBILITY_NOTICES[eligibility.state] || ELIGIBILITY_NOTICES.error}</span>
            {eligibility.state === 'no-profile' && <Link to="/profile">Complete profile</Link>}
            {eligibility.state === 'logged-out' && <Link to="/login">Log in</Link>}
          </p>
        )}
        {data?.profile_incomplete && (
          <p className="university-notice" role="status">
            <Info size={16} aria-hidden="true" />
            <span>
              Your eligibility and scores use an incomplete profile
              {data.profile_gaps.length > 0 ? ` (missing: ${data.profile_gaps.map((gap) => gap.label.toLowerCase()).join(', ')})` : ''}.
            </span>
            <Link to="/profile">Update profile</Link>
          </p>
        )}
        {loading ? (
          <p className="university-message" role="status">Loading scholarships...</p>
        ) : loadError ? (
          <div className="university-message university-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="scholarships-clear" onClick={() => setRetry((value) => value + 1)}>Try again</button>
          </div>
        ) : visibleScholarships.length === 0 ? (
          <div className="university-message" role="status">
            <p>
              {total === 0 && options?.verification?.every((option) => option.value !== 'verified')
                ? 'No verified scholarships are currently available.'
                : 'No scholarships match this search. Try removing a filter or using fewer words.'}
            </p>
            <button type="button" className="scholarships-clear" onClick={clearAll}>Clear all filters</button>
          </div>
        ) : (
          <div className="program-list is-matches" role="list">
            <div className="program-list-head" aria-hidden="true">
              <span>Scholarship</span>
              <span>Coverage</span>
              <span>Deadline</span>
              <span>Match</span>
              <span>Eligibility</span>
              <span>Compare</span>
            </div>
            {visibleScholarships.map((item) => {
              const saved = savedOpportunities.includes(item.id);
              const deadline = getScholarshipDeadlineLabel(item.deadlineResult);
              const reason = eligibility.state === 'ok' ? getEligibilityReason(item.evaluation) : '';
              const openDetails = () => navigate(`/scholarships/${item.id}`);
              return (
                <div
                  key={item.id}
                  role="listitem"
                  className={`program-row ${activeOpportunityId === item.id ? 'is-active' : ''}`}
                  tabIndex={0}
                  aria-label={`${item.title}, ${item.provider || 'provider not listed'}, ${getEligibilityLabel(item.evaluation.status)}. Open details`}
                  onClick={openDetails}
                  onKeyDown={(event) => {
                    if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
                      event.preventDefault();
                      openDetails();
                    }
                  }}
                >
                  <div className="program-row-main">
                    <ScholarshipLogo
                      src={getScholarshipLogo(item)}
                      size={42}
                      bareFallback
                      fallback={<span className={`program-row-mark is-scholarship tone-${item.tone}`} aria-hidden="true">{item.icon}</span>}
                    />
                    <div className="program-row-copy">
                      <strong>{item.title}</strong>
                      <span>{[item.provider || 'Provider not listed', shortCountry(item.country)].filter(Boolean).join(' · ')}</span>
                      {item.fundingType && (
                        <span className="program-row-tags"><em className="is-scholarship">{item.fundingType}</em></span>
                      )}
                      <small>{item.verificationLabel}{item.lastVerified ? ` · last verified ${item.lastVerified}` : ''}</small>
                      {item.has_conflict && <small>Conflicting information on this record</small>}
                      {item.nationality_status === 'not_evaluated' && <small>Your citizenship needs a manual check</small>}
                      {item.matched_fields.length > 0 && <small>Found in: {item.matched_fields.join(', ')}</small>}
                    </div>
                  </div>
                  <div className="program-row-cell" data-label="Coverage">
                    <strong>{item.funding_label}</strong>
                    <small>{item.coverage}</small>
                  </div>
                  <div className="program-row-cell" data-label="Deadline">
                    <strong>{deadline ? deadline.label : item.deadline || 'Not listed'}</strong>
                    {deadline && <small>{deadline.note}</small>}
                  </div>
                  <div className="program-row-cell" data-label="Match">
                    <MatchRing score={item.match} />
                    {item.exclusions.length > 0 && <small>{item.exclusions[0].rule === 'closed' ? 'Closed' : 'Not suitable'}</small>}
                  </div>
                  <div className="program-row-cell" data-label="Eligibility">
                    <EligibilityBadge status={item.evaluation.status} />
                    {reason && <small className="program-row-reason">{reason}</small>}
                  </div>
                  <div className="program-row-actions" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                    <OpportunityCompareCheckbox opportunity={item} />
                    <button
                      type="button"
                      className={`program-row-save ${saved ? 'is-saved' : ''}`}
                      aria-label={`${saved ? 'Remove saved' : 'Save'} ${item.title}`}
                      aria-pressed={saved}
                      onClick={() => toggleSaveOpportunity(item.id)}
                    >
                      <Bookmark size={16} fill={saved ? 'currentColor' : 'none'} aria-hidden="true" />
                    </button>
                    <ChevronRight className="program-row-chevron" size={20} aria-hidden="true" />
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {!loading && !loadError && total > PAGE_SIZE && (
          <nav className="scholarships-pager" aria-label="Scholarship results pages">
            <button type="button" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>Previous</button>
            <span>Page {page} of {getPageCount(total)}</span>
            <button type="button" disabled={page >= getPageCount(total)} onClick={() => setPage((value) => value + 1)}>Next</button>
          </nav>
        )}
      </section>

      {comparisonOpportunityIds.length > 0 && <ComparisonSelectionBar />}
    </div>
  );
}