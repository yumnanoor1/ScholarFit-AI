import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bookmark, Briefcase, Calculator, ChevronRight, CircleHelp, MapPin, Search, SlidersHorizontal, Wallet,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import SavedStatusNotice from '../components/opportunities/SavedStatusNotice';
import ScholarshipLogo from '../components/common/ScholarshipLogo';
import EligibilityBadge from '../components/opportunities/EligibilityBadge';
import {
  compareByRank, getCategoryTone, getExclusionLabel, getScholarshipDeadlineLabel,
} from '../services/eligibilityBadges';
import MatchRing from '../components/opportunities/MatchRing';
import { ComparisonSelectionBar, OpportunityCompareCheckbox } from '../components/opportunities/ComparisonControls';
import RetryButton from '../components/common/RetryButton';
import { apiService } from '../services/api';
import { getScholarshipLogo } from '../services/scholarshipLogos';
import { buildFinancialRouteState } from '../services/financialSelection';
import { useScholarshipEligibility, useScholarshipRecommendations } from '../hooks/useScholarshipEligibility';
import './Universities.css';

function hasFundingInformation(opportunity) {
  return Boolean(opportunity.coverage || opportunity.funding || opportunity.fundingOptions?.length);
}

export default function Recommendations() {
  const navigate = useNavigate();
  const {
    activeOpportunityId,
    isOpportunitySaved,
    selectOpportunity,
    toggleSaveOpportunity,
    comparisonOpportunityIds,
  } = useProfile();
  const [scholarships, setScholarships] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [country, setCountry] = useState('all');
  const [funding, setFunding] = useState('all');
  const [sort, setSort] = useState('match-desc');
  const [search, setSearch] = useState('');
  const scholarshipEligibility = useScholarshipEligibility();
  const recommendations = useScholarshipRecommendations();
  const isLoading = loading || scholarshipEligibility.loading || recommendations.loading;
  const excluded = recommendations.data?.excluded || [];

  useEffect(() => {
    let current = true;
    apiService.getMatchedScholarships()
      .then((items) => { if (current) setScholarships(items); })
      .catch((loadError) => {
        console.error('Unable to load scholarships for recommendations.', loadError);
        if (current) setError('Scholarships could not be loaded. Please try again later.');
      })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, []);

  const countries = useMemo(
    () => [...new Set(scholarships.map((item) => item.country).filter(Boolean))].sort(),
    [scholarships],
  );
  const rankedScholarships = useMemo(() => scholarships
    .map((item) => {
      const recommendation = recommendations.getRecommendation(item.id);
      return { ...item, recommendation, rank: recommendation?.rank ?? null, matchScore: recommendation?.score ?? null };
    })
    .filter((item) => item.recommendation?.recommended), [scholarships, recommendations]);
  const visibleScholarships = useMemo(() => {
    const query = search.trim().toLowerCase();
    return rankedScholarships
      .filter((item) => country === 'all' || item.country === country)
      .filter((item) => funding === 'all'
        || (funding === 'listed' && hasFundingInformation(item))
        || (funding === 'not-listed' && !hasFundingInformation(item)))
      .filter((item) => !query || [item.name, item.provider, item.country].filter(Boolean).join(' ').toLowerCase().includes(query))
      .sort((first, second) => sort === 'match-asc' ? compareByRank(second, first) : compareByRank(first, second));
  }, [rankedScholarships, country, funding, search, sort]);

  return (
    <div className="page-container opportunity-recommendations-page">
      <header className="cmp-header">
        <div className="cmp-header-copy">
          <h1>Scholarship Recommendations</h1>
          <p>Scholarship-only matches based on your saved profile and verified opportunity records.</p>
        </div>
      </header>
      <section className="matched-toolbar" aria-label="Filter scholarship recommendations">
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
            <option value="all">All funding information</option>
            <option value="listed">Funding information listed</option>
            <option value="not-listed">Funding not listed</option>
          </select>
        </label>
        <label className="matched-search">
          <Search size={15} aria-hidden="true" />
          <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search scholarships..." />
        </label>
        <label className="matched-sort">
          <SlidersHorizontal size={15} aria-hidden="true" />
          <span>Sort by</span>
          <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Sort scholarships">
            <option value="match-desc">Recommendation (Best first)</option>
            <option value="match-asc">Recommendation (Last first)</option>
          </select>
        </label>
      </section>
      <SavedStatusNotice />
      {isLoading && <p role="status">Loading scholarship recommendations…</p>}
      {error && <div className="disclaimer-box" role="alert"><p>{error}</p><RetryButton /></div>}
      {!isLoading && !error && recommendations.state === 'error' && (
        <div className="disclaimer-box" role="alert"><p>Scholarship recommendations could not be calculated. No fallback results are shown.</p><RetryButton /></div>
      )}
      {!isLoading && !error && recommendations.state === 'ok' && visibleScholarships.length === 0 && (
        <div className="matched-empty-state"><CircleHelp size={22} /><p>No recommended scholarships match these filters. Review excluded results for unmet or uncertain requirements.</p></div>
      )}

      {!isLoading && !error && recommendations.state === 'ok' && visibleScholarships.length > 0 && (
        <div className="match-list" role="list" aria-label="Scholarship recommendations">
          {visibleScholarships.map((opportunity) => {
            const title = opportunity.name;
            const recommendation = opportunity.recommendation;
            const eligibility = scholarshipEligibility.getEvaluation(opportunity.id);
            const deadline = getScholarshipDeadlineLabel(eligibility.deadline);
            const saved = isOpportunitySaved(opportunity.id);
            const openDetails = () => navigate(`/scholarships/${opportunity.id}`);
            const checkFinancialFeasibility = () => {
              selectOpportunity({ ...opportunity, kind: 'scholarship' });
              navigate('/financial', { state: buildFinancialRouteState({ scholarshipId: opportunity._numericId }) });
            };
            const ScholarshipIcon = opportunity.type === 'RA' ? Briefcase : Wallet;

            return (
              <article key={opportunity.id} className={`match-card ${activeOpportunityId === opportunity.id ? 'is-active' : ''}`} role="listitem">
                <header className="match-card-head">
                  <ScholarshipLogo src={getScholarshipLogo(opportunity)} size={48} bareFallback fallback={<span className="program-row-mark is-scholarship" aria-hidden="true"><ScholarshipIcon size={22} /></span>} />
                  <div className="match-card-title">
                    <h2>{title}</h2>
                    <p>{[opportunity.provider || 'Provider not listed', opportunity.country].filter(Boolean).join(' · ')}</p>
                    <div className="match-card-tags">
                      {recommendation && <span className={`program-status is-${getCategoryTone(recommendation.category)}`}>{recommendation.category_label}</span>}
                    </div>
                  </div>
                  <MatchRing score={recommendation?.score} />
                </header>
                <dl className="match-card-facts">
                  <div><dt>Funding</dt><dd><strong>{recommendation?.funding?.label || opportunity.coverageSummary || 'Not listed'}</strong></dd></div>
                  <div><dt>Deadline</dt><dd><strong>{deadline?.label || opportunity.deadline || 'Not listed'}</strong>{deadline?.note && <small>{deadline.note}</small>}</dd></div>
                  <div><dt>Eligibility</dt><dd><EligibilityBadge status={eligibility.status} /></dd></div>
                </dl>
                {recommendation?.positive?.length > 0 && <p className="scholarship-eligibility-note">{recommendation.positive[0]}</p>}
                <footer className="match-card-actions">
                  <OpportunityCompareCheckbox opportunity={{ ...opportunity, title }} />
                  <button type="button" className={`program-row-save ${saved ? 'is-saved' : ''}`} aria-label={`${saved ? 'Remove saved' : 'Save'} ${title}`} aria-pressed={saved} onClick={() => toggleSaveOpportunity(opportunity.id)}>
                    <Bookmark size={16} fill={saved ? 'currentColor' : 'none'} aria-hidden="true" />
                  </button>
                  <button type="button" className="match-card-financial" onClick={checkFinancialFeasibility}><Calculator size={14} aria-hidden="true" /> Check affordability</button>
                  <button type="button" className="match-card-open" onClick={openDetails}>View details <ChevronRight size={16} aria-hidden="true" /></button>
                </footer>
              </article>
            );
          })}
        </div>
      )}
      {!isLoading && excluded.length > 0 && (
        <details className="matched-page-disclaimer">
          <summary>Not recommended right now ({excluded.length})</summary>
          <ul>{excluded.map((item) => <li key={item.scholarship_id}><strong>{item.scholarship_name}:</strong> {getExclusionLabel(item)}</li>)}</ul>
        </details>
      )}
      <p className="matched-page-disclaimer">Scholarship scores describe suitability from the recorded information, not the chance of receiving an award. Verify current requirements and dates with the official provider.</p>
      {comparisonOpportunityIds.length > 0 && <ComparisonSelectionBar />}
    </div>
  );
}
