import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight, Award, Bookmark, CalendarDays, Check, CircleHelp,
  Compass, GraduationCap, MapPin, Search, SlidersHorizontal, Star, Wallet,
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
  } = useProfile();
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [category, setCategory] = useState('all');
  const [country, setCountry] = useState('all');
  const [funding, setFunding] = useState('all');
  const [sort, setSort] = useState('match-desc');
  const [search, setSearch] = useState('');

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
  const averageMatch = opportunities.length
    ? Math.round(opportunities.reduce((total, item) => total + (Number(item.matchScore) || 0), 0) / opportunities.length)
    : 0;

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

  const categories = [
    { id: 'all', label: 'All Matches', count: opportunities.length },
    { id: 'programs', label: "Master's Programs", count: programs.length },
    { id: 'scholarships', label: 'Scholarships', count: scholarships.length },
  ];

  return (
    <div className="page-container opportunity-recommendations-page">
      <header className="matched-page-header">
        <div className="matched-page-title">
          <span className="matched-page-title-icon"><Compass size={24} aria-hidden="true" /></span>
          <div>
            <h1>Matched Opportunities</h1>
            <p>Discover university programs and scholarship opportunities based on your profile.</p>
          </div>
        </div>
        <div className="matched-summary" aria-label="Opportunity match summary">
          <article>
            <span className="matched-summary-icon programs"><GraduationCap size={18} /></span>
            <div><strong>{programs.length}</strong><span>Matched Programs</span><small>Illustrative data</small></div>
          </article>
          <article>
            <span className="matched-summary-icon scholarships"><Award size={18} /></span>
            <div><strong>{scholarships.length}</strong><span>Matched Scholarships</span><small>Illustrative data</small></div>
          </article>
          <article>
            <span className="matched-summary-icon average"><Star size={18} /></span>
            <div><strong>{averageMatch}%</strong><span>Avg. Match Score</span><small>Illustrative data</small></div>
          </article>
        </div>
      </header>

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

      <div className="opportunity-recommendations-grid">
        {visibleOpportunities.map((opportunity) => {
          const title = getOpportunityTitle(opportunity);
          const isSelected = selectedOpportunities.some((item) => item.id === opportunity.id);
          const isActive = activeOpportunityId === opportunity.id;
          const isSaved = savedOpportunities.includes(opportunity.id);
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
                  <span className="matched-type-pill">{isProgram ? opportunity.degree || "Master's Program" : opportunity.type || 'Scholarship'}</span>
                </div>
                <div className="matched-score">
                  <span className={`matched-score-ring ${isProgram ? '' : 'scholarship-score'}`}>{opportunity.matchScore ?? '—'}{opportunity.matchScore != null && '%'}</span>
                  <span>Match Score</span>
                  <div className="matched-score-track"><span style={{ width: `${Math.min(Math.max(Number(opportunity.matchScore) || 0, 0), 100)}%` }} /></div>
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
                <section className="matched-reasons">
                  <h3>Why it matches your profile:</h3>
                  {reasons.map((reason, index) => (
                    <p key={`${opportunity.id}-reason-${index}`}><Check size={14} aria-hidden="true" /> {reason}</p>
                  ))}
                  <span className={`matched-eligibility ${eligibility.status}`}>
                    Profile requirements: {eligibility.status.replaceAll('-', ' ')}
                  </span>
                </section>
                <aside className="matched-funding-box">
                  <h3><Wallet size={14} aria-hidden="true" /> Funding Information <CircleHelp size={12} aria-label="Listing details are unverified" /></h3>
                  <p>{isProgram
                    ? `Listed tuition: ${opportunity.tuition || 'Not specified'}`
                    : opportunity.coverage || 'Funding coverage not specified'}
                  </p>
                  {isProgram && <p>Living cost: Not available</p>}
                  {!isProgram && <p>Funding listing is not a confirmed award.</p>}
                  <h3><CalendarDays size={14} aria-hidden="true" /> Deadline (if available)</h3>
                  <p>{opportunity.deadline || 'Not specified'}</p>
                  {opportunity.deadline && opportunity.deadlineStatus !== 'official-verified' && (
                    <small>Sample date · verify with provider</small>
                  )}
                </aside>
              </div>

              <footer className="matched-card-footer">
                <span className="matched-data-note">
                  {opportunity.sourceStatus === 'official-verified' ? 'Verified source data' : 'Sample data · verify with provider'}
                </span>
                <button
                  type="button"
                  className="matched-start-button"
                  aria-pressed={isActive}
                  onClick={() => selectForJourney(opportunity)}
                >
                  {isActive ? 'Selected · Open Timeline' : isSelected ? 'Select This Opportunity' : 'Select Opportunity'}
                  <ArrowRight size={14} aria-hidden="true" />
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
