import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, ArrowRight, Bookmark, Check, CircleHelp,
  GraduationCap, Grid2X2, List, MapPin, Search, SlidersHorizontal, Wallet,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import { evaluateOpportunityEligibility, getOpportunityTitle } from '../services/opportunityJourney';

function hasFundingInformation(opportunity) {
  return Boolean(opportunity.coverage || opportunity.funding || opportunity.fundingOptions?.length);
}

function getOpportunityReason(opportunity, status) {
  if (opportunity.matchReason) return opportunity.matchReason;
  if (opportunity.kind === 'scholarship') return 'Review the provider’s published criteria and funding terms against your verified profile.';
  if (status === 'awaiting-verification') return 'Some requirement or profile details need verification before this match can be assessed.';
  return 'Review the program’s requirements against your verified academic and study profile.';
}

export default function Recommendations() {
  const navigate = useNavigate();
  const {
    profile,
    activeOpportunityId,
    selectedOpportunities,
    savedOpportunities,
    toggleSaveOpportunity,
    selectOpportunity,
    comparisonOpportunityIds,
    toggleComparisonOpportunity,
  } = useProfile();
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [category, setCategory] = useState('all');
  const [country, setCountry] = useState('all');
  const [funding, setFunding] = useState('all');
  const [sort, setSort] = useState('match-desc');
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState('list');
  const [expandedReasons, setExpandedReasons] = useState({});

  useEffect(() => {
    let isCurrent = true;
    Promise.all([apiService.getMatchedUniversities(), apiService.getMatchedScholarships()])
      .then(([programs, scholarships]) => {
        if (isCurrent) {
          setOpportunities([
            ...programs.map((item) => ({ ...item, kind: 'program' })),
            ...scholarships.map((item) => ({ ...item, kind: 'scholarship' })),
          ]);
        }
      })
      .catch((loadError) => {
        console.error('Unable to load recommendations.', loadError);
        if (isCurrent) setError('Matched opportunities could not be loaded. Please try again later.');
      })
      .finally(() => {
        if (isCurrent) setLoading(false);
      });
    return () => { isCurrent = false; };
  }, []);

  const countries = useMemo(
    () => [...new Set(opportunities.map((opportunity) => opportunity.country).filter(Boolean))].sort(),
    [opportunities],
  );
  const programs = opportunities.filter((opportunity) => opportunity.kind === 'program');
  const scholarships = opportunities.filter((opportunity) => opportunity.kind === 'scholarship');
  const visibleOpportunities = useMemo(() => {
    const query = search.trim().toLowerCase();
    return opportunities
      .filter((opportunity) => category === 'all'
        || (category === 'programs' && opportunity.kind === 'program')
        || (category === 'scholarships' && opportunity.kind === 'scholarship'))
      .filter((opportunity) => country === 'all' || opportunity.country === country)
      .filter((opportunity) => funding === 'all'
        || (funding === 'listed' && hasFundingInformation(opportunity))
        || (funding === 'not-listed' && !hasFundingInformation(opportunity)))
      .filter((opportunity) => !query || [
        getOpportunityTitle(opportunity),
        opportunity.university,
        opportunity.provider,
        opportunity.country,
      ].filter(Boolean).join(' ').toLowerCase().includes(query))
      .sort((first, second) => sort === 'match-asc'
        ? (Number(first.matchScore) || 0) - (Number(second.matchScore) || 0)
        : (Number(second.matchScore) || 0) - (Number(first.matchScore) || 0));
  }, [opportunities, category, country, funding, search, sort]);

  const selectForJourney = (opportunity) => {
    selectOpportunity(opportunity);
    navigate('/timeline');
  };

  const toggleCompare = (opportunity) => {
    if (!comparisonOpportunityIds.includes(opportunity.id) && comparisonOpportunityIds.length >= 2) {
      navigate('/compare');
      return;
    }
    toggleComparisonOpportunity(opportunity.id);
    navigate('/compare');
  };

  const getCostLabel = (opportunity, key) => {
    const cost = opportunity.financialData?.costs?.[key];
    const amountValue = Number(cost?.amount);
    if (!cost || cost.amount === '' || cost.amount == null || !Number.isFinite(amountValue)) return 'Not listed';
    const currency = /^[A-Za-z]{3}$/.test(cost.currency || '') ? cost.currency.toUpperCase() : 'USD';
    const amount = new Intl.NumberFormat('en', {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(amountValue);
    return `${amount}${cost.period === 'monthly' ? ' / month' : cost.period === 'yearly' ? ' / year' : ''}`;
  };

  const categories = [
    { id: 'all', label: 'All Matches', count: opportunities.length },
    { id: 'programs', label: "Master's Programs", count: programs.length },
    { id: 'scholarships', label: 'Scholarships', count: scholarships.length },
  ];

  return (
    <div className="page-container opportunity-recommendations-page">
      <section className="matched-toolbar" aria-label="Filter matched opportunities">
        <div className="matched-category-tabs" role="group" aria-label="Opportunity category">
          {categories.map((item) => (
            <button
              type="button"
              key={item.id}
              className={category === item.id ? 'is-active' : ''}
              aria-pressed={category === item.id}
              onClick={() => setCategory(item.id)}
            >
              {item.label}<span>{item.count}</span>
            </button>
          ))}
        </div>
        <label className="matched-filter-select">
          <MapPin size={15} aria-hidden="true" />
          <select value={country} onChange={(event) => setCountry(event.target.value)} aria-label="Filter by country">
            <option value="all">All Countries</option>
            {countries.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="matched-filter-select">
          <Wallet size={15} aria-hidden="true" />
          <select value={funding} onChange={(event) => setFunding(event.target.value)} aria-label="Filter by funding information">
            <option value="all">All Funding Types</option>
            <option value="listed">Funding information listed</option>
            <option value="not-listed">Funding not listed</option>
          </select>
        </label>
        <label className="matched-search">
          <Search size={15} aria-hidden="true" />
          <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search opportunities..." />
        </label>
        <label className="matched-sort">
          <SlidersHorizontal size={15} aria-hidden="true" />
          <span>Sort by</span>
          <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Sort opportunities by match score">
            <option value="match-desc">Match Score (High → Low)</option>
            <option value="match-asc">Match Score (Low → High)</option>
          </select>
        </label>
        <div className="matched-view-toggle" role="group" aria-label="Opportunity view">
          <button type="button" aria-label="List view" aria-pressed={viewMode === 'list'} className={viewMode === 'list' ? 'is-active' : ''} onClick={() => setViewMode('list')}>
            <List size={17} aria-hidden="true" />
          </button>
          <button type="button" aria-label="Grid view" aria-pressed={viewMode === 'grid'} className={viewMode === 'grid' ? 'is-active' : ''} onClick={() => setViewMode('grid')}>
            <Grid2X2 size={16} aria-hidden="true" />
          </button>
        </div>
      </section>

      {selectedOpportunities.length > 0 && (
        <p className="opportunity-selection-count">
          {selectedOpportunities.length} selected for application journeys
          {selectedOpportunities.some((item) => item.id === activeOpportunityId)
            ? ` · active: ${getOpportunityTitle(selectedOpportunities.find((item) => item.id === activeOpportunityId))}`
            : ' · no active opportunity'}
        </p>
      )}
      {loading && <p role="status">Loading matched opportunities...</p>}
      {error && <p className="disclaimer-box" role="alert">{error}</p>}
      {!loading && !error && visibleOpportunities.length === 0 && (
        <div className="matched-empty-state"><CircleHelp size={22} /><p>No matched opportunities found. Try changing the filters or search term.</p></div>
      )}

      <div className={`opportunity-recommendations-grid ${viewMode}-view`}>
        {visibleOpportunities.map((opportunity) => {
          const title = getOpportunityTitle(opportunity);
          const isActive = activeOpportunityId === opportunity.id;
          const isSaved = savedOpportunities.includes(opportunity.id);
          const isCompared = comparisonOpportunityIds.includes(opportunity.id);
          const compareLimitReached = comparisonOpportunityIds.length >= 2 && !isCompared;
          const eligibility = evaluateOpportunityEligibility(profile, opportunity);
          const isProgram = opportunity.kind === 'program';
          const organization = isProgram ? opportunity.university : opportunity.provider;
          const reasons = opportunity.matchReason
            ? [opportunity.matchReason]
            : [getOpportunityReason(opportunity, eligibility.status)];

          return (
            <article className="matched-opportunity-card" key={opportunity.id}>
              <div className="matched-card-top">
                <div className={`matched-opportunity-logo ${isProgram ? 'program-logo' : 'scholarship-logo'}`} aria-hidden="true">
                  {isProgram ? <GraduationCap size={25} /> : <span>{opportunity.provider?.slice(0, 4).toUpperCase() || 'FUND'}</span>}
                </div>
                <div className="matched-opportunity-identity">
                  <h2>{title}</h2>
                  <p><GraduationCap size={13} aria-hidden="true" /> {organization || 'Provider not listed'}</p>
                  <p><MapPin size={13} aria-hidden="true" /> {opportunity.country || 'Country not listed'}</p>
                  <span className={`matched-requirement-status ${eligibility.status === 'satisfied' ? 'is-satisfied' : 'is-warning'}`}>
                    {eligibility.status === 'satisfied'
                      ? <Check size={13} aria-hidden="true" />
                      : <AlertTriangle size={13} aria-hidden="true" />}
                    Requirements: {eligibility.status.replaceAll('-', ' ')}
                  </span>
                </div>
                <div className="matched-score">
                  <span className={`matched-score-ring ${isProgram ? '' : 'scholarship-score'}`}>{opportunity.matchScore ?? '—'}{opportunity.matchScore != null && '%'}</span>
                  <span>Match Score</span>
                </div>
                <button
                  type="button"
                  className={`matched-bookmark ${isSaved ? 'is-saved' : ''}`}
                  aria-label={`${isSaved ? 'Remove saved' : 'Save'} ${title}`}
                  aria-pressed={isSaved}
                  onClick={() => toggleSaveOpportunity(opportunity.id)}
                >
                  <Bookmark size={16} fill={isSaved ? 'currentColor' : 'none'} aria-hidden="true" />
                </button>
              </div>

              <div className="matched-card-content">
                <div className="matched-cost-stats" aria-label="Opportunity cost and deadline information">
                  <div><span>{isProgram ? 'Tuition' : 'Funding'}</span><strong>{isProgram ? opportunity.tuition || 'Not listed' : opportunity.coverage || 'Not listed'}</strong></div>
                  <div><span>Living cost</span><strong>{isProgram ? getCostLabel(opportunity, 'accommodationFood') : 'Not listed'}</strong></div>
                  <div><span>Deadline</span><strong>{opportunity.deadline || 'Not listed'}{opportunity.deadline && opportunity.deadlineStatus !== 'official-verified' ? ' · listed' : ''}</strong></div>
                </div>
                <section className="matched-reasons">
                  <button
                    type="button"
                    className="matched-reason-toggle"
                    aria-expanded={Boolean(expandedReasons[opportunity.id])}
                    aria-controls={`match-reason-${opportunity.id}`}
                    onClick={() => setExpandedReasons((current) => ({ ...current, [opportunity.id]: !current[opportunity.id] }))}
                  >
                    <Check size={14} aria-hidden="true" /> Why this match? <span>{expandedReasons[opportunity.id] ? '−' : '+'}</span>
                  </button>
                  {expandedReasons[opportunity.id] && (
                    <p id={`match-reason-${opportunity.id}`}>{reasons[0]}</p>
                  )}
                </section>
              </div>

              <footer className="matched-card-footer">
                <button
                  type="button"
                  className="matched-start-button"
                  aria-pressed={isActive}
                  onClick={() => selectForJourney(opportunity)}
                >
                  {isActive ? 'Selected' : 'Select'}
                  <ArrowRight size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="matched-compare-button"
                  aria-pressed={isCompared}
                  disabled={compareLimitReached}
                  onClick={() => toggleCompare(opportunity)}
                >
                  Compare
                </button>
              </footer>
            </article>
          );
        })}
      </div>
      <p className="matched-page-disclaimer">Match scores, requirements, costs, funding, and dates shown here are illustrative sample data. Verify details with the official university or scholarship provider.</p>
    </div>
  );
}
