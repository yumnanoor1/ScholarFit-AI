import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bookmark, Briefcase, Building2, Calculator, ChevronRight, CircleHelp,
  GraduationCap, MapPin, Search, SlidersHorizontal, Wallet,
} from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import SavedStatusNotice from '../components/opportunities/SavedStatusNotice';
import UniversityLogo from '../components/common/UniversityLogo';
import EligibilityBadge from '../components/opportunities/EligibilityBadge';
import {
  compareByRank, getCategoryTone, getEligibilityLabel, getExclusionLabel, getMatchTone, getScholarshipDeadlineLabel,
} from '../services/eligibilityBadges';
import MatchRing from '../components/opportunities/MatchRing';
import { ComparisonSelectionBar, OpportunityCompareCheckbox } from '../components/opportunities/ComparisonControls';
import RetryButton from '../components/common/RetryButton';
import { apiService } from '../services/api';
import { getOpportunityTitle } from '../services/opportunityJourney';
import { getDeadlineInfo, getScholarshipLogo } from '../services/programFit';
import { getSelectedProgramId } from '../services/opportunityApi';
import { buildFinancialRouteState } from '../services/financialSelection';
import { useProgramEligibility, useScholarshipEligibility, useScholarshipRecommendations } from '../hooks/useProgramEligibility';
import './Universities.css';

function hasFundingInformation(opportunity) {
  return Boolean(opportunity.coverage || opportunity.funding || opportunity.fundingOptions?.length);
}

export default function Recommendations() {
  const navigate = useNavigate();
  const {
    activeOpportunityId,
    selectedOpportunities,
    isOpportunitySaved,
    selectOpportunity,
    toggleSaveOpportunity,
    comparisonOpportunityIds,
  } = useProfile();
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [category, setCategory] = useState('all');
  const [country, setCountry] = useState('all');
  const [funding, setFunding] = useState('all');
  const [sort, setSort] = useState('match-desc');
  const [search, setSearch] = useState('');
  const programEligibility = useProgramEligibility();
  const scholarshipEligibility = useScholarshipEligibility();
  // "" means the student chose no program; until they choose, the journey's active program applies
  const [programChoice, setProgramChoice] = useState(null);
  const selectedProgramId = programChoice === null ? getSelectedProgramId(activeOpportunityId) : getSelectedProgramId(programChoice);
  const recommendations = useScholarshipRecommendations(selectedProgramId);
  const isLoading = loading || programEligibility.loading || scholarshipEligibility.loading || recommendations.loading;
  const excluded = recommendations.data?.excluded || [];

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
  // Only ranked scholarships are matches; hard exclusions are listed apart below
  const rankedOpportunities = useMemo(() => opportunities
    .map((opportunity) => {
      if (opportunity.kind !== 'scholarship') return opportunity;
      const recommendation = recommendations.getRecommendation(opportunity.id);
      return { ...opportunity, recommendation, rank: recommendation?.rank ?? null, matchScore: recommendation?.score ?? null };
    })
    .filter((opportunity) => opportunity.kind !== 'scholarship' || opportunity.recommendation?.recommended), [opportunities, recommendations]);
  const scholarships = rankedOpportunities.filter((opportunity) => opportunity.kind === 'scholarship');
  const visibleOpportunities = useMemo(() => {
    const query = search.trim().toLowerCase();
    return rankedOpportunities
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
      .sort((first, second) => sort === 'match-asc' ? compareByRank(second, first) : compareByRank(first, second));
  }, [rankedOpportunities, category, country, funding, search, sort]);

  // A count of zero would read as "nothing matches you", which a failed request can't show
  const scoresFailed = Boolean(error) || recommendations.state === 'error';
  const categories = [
    { id: 'all', label: 'All Matches', count: scoresFailed ? null : programs.length + scholarships.length },
    { id: 'programs', label: "Master's Programs", count: error ? null : programs.length },
    { id: 'scholarships', label: 'Scholarships', count: scoresFailed ? null : scholarships.length },
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
              {item.label}<span>{item.count ?? '–'}</span>
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
        <label className="matched-filter-select">
          <GraduationCap size={15} aria-hidden="true" />
          <select value={selectedProgramId ?? ''} onChange={(event) => setProgramChoice(event.target.value)} aria-label="Rank scholarships for a program">
            <option value="">No program selected</option>
            {programs.map((item) => <option key={item.id} value={item.id}>{getOpportunityTitle(item)}, {item.university}</option>)}
          </select>
        </label>
        <label className="matched-search">
          <Search size={15} aria-hidden="true" />
          <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search opportunities..." />
        </label>
        <label className="matched-sort">
          <SlidersHorizontal size={15} aria-hidden="true" />
          <span>Sort by</span>
          <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Sort opportunities by recommendation rank">
            <option value="match-desc">Recommendation (Best first)</option>
            <option value="match-asc">Recommendation (Last first)</option>
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
      <SavedStatusNotice />
      {isLoading && <p role="status">Loading matched opportunities...</p>}
      {error && <div className="disclaimer-box" role="alert"><p>{error}</p><RetryButton /></div>}
      {!isLoading && !error && recommendations.state === 'error' && (
        <div className="disclaimer-box" role="alert"><p>Your scholarship matches could not be loaded, so only programs are shown.</p><RetryButton /></div>
      )}
      {!isLoading && !error && visibleOpportunities.length === 0 && (
        <div className="matched-empty-state"><CircleHelp size={22} /><p>No matched opportunities found. Try changing the filters or search term.</p></div>
      )}

      {!isLoading && !error && visibleOpportunities.length > 0 && (
        <div className="match-list" role="list" aria-label="Matched opportunities">
          {visibleOpportunities.map((opportunity) => {
            const title = getOpportunityTitle(opportunity);
            const isProgram = opportunity.kind === 'program';
            // Both come from the backend eligibility endpoints
            const eligibility = isProgram
              ? programEligibility.getEvaluation(opportunity.id)
              : scholarshipEligibility.getEvaluation(opportunity.id);
            const { recommendation } = opportunity;
            const organization = isProgram ? opportunity.university : opportunity.provider;
            const programDeadline = isProgram ? getDeadlineInfo(opportunity.deadline) : null;
            const deadline = isProgram
              ? programDeadline && { label: programDeadline.label, note: programDeadline.passed ? 'Passed' : `${programDeadline.days} days left` }
              : getScholarshipDeadlineLabel(eligibility.deadline);
            const saved = isOpportunitySaved(opportunity.id);
            const ScholarshipIcon = opportunity.type === 'RA' ? Briefcase : Building2;
            const openDetails = () => navigate(isProgram ? `/universities/${opportunity.id}` : `/scholarships/${opportunity.id}`);
            // The planner works on a program, so a scholarship is checked against the program chosen above
            const checkFinancialFeasibility = () => {
              if (isProgram) {
                selectOpportunity({ ...opportunity });
                navigate('/financial', { state: buildFinancialRouteState({ programId: opportunity._numericId ?? opportunity.id }) });
                return;
              }
              const program = programs.find((item) => getSelectedProgramId(item.id) === selectedProgramId);
              if (program) selectOpportunity({ ...program });
              navigate('/financial', {
                state: buildFinancialRouteState({ programId: selectedProgramId, scholarshipId: opportunity._numericId }),
              });
            };

            return (
              <div
                key={opportunity.id}
                role="listitem"
                className={`match-card ${activeOpportunityId === opportunity.id ? 'is-active' : ''}`}
                tabIndex={0}
                aria-label={`${title}, ${organization || 'provider not listed'}, ${getEligibilityLabel(eligibility.status)}. Open details`}
                onClick={openDetails}
                onKeyDown={(event) => {
                  if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
                    event.preventDefault();
                    openDetails();
                  }
                }}
              >
                <header className="match-card-head">
                  {isProgram
                    ? <UniversityLogo university={opportunity.university} size={48} fallback={<GraduationCap size={22} />} />
                    : <UniversityLogo src={getScholarshipLogo(opportunity)} size={48} bareFallback fallback={<span className="program-row-mark is-scholarship" aria-hidden="true"><ScholarshipIcon size={22} /></span>} />}
                  <div className="match-card-title">
                    <h2>{title}</h2>
                    <p>{[organization || 'Provider not listed', opportunity.country].filter(Boolean).join(' · ')}</p>
                    <div className="match-card-tags">
                      {isProgram && <span className="match-card-type is-program">Master&apos;s program</span>}
                      {recommendation && <span className={`program-status is-${getCategoryTone(recommendation.category)}`}>{recommendation.category_label}</span>}
                      {recommendation?.program_match && (
                        <span className={`program-status is-${getMatchTone(recommendation.program_match.outcome)}`}>{recommendation.program_match.label}</span>
                      )}
                    </div>
                  </div>
                  <MatchRing score={opportunity.matchScore} />
                </header>
                <dl className="match-card-facts">
                  <div>
                    <dt>Tuition / funding</dt>
                    <dd>
                      <strong>{isProgram ? opportunity.tuitionOriginal || opportunity.tuition || 'Not listed' : recommendation?.funding.label || 'Not listed'}</strong>
                      {isProgram && opportunity.tuitionAmount > 0 && opportunity.tuitionCurrency !== 'USD' && opportunity.tuition && (
                        <small>≈ {opportunity.tuition.replace(' / year', '')}</small>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Deadline</dt>
                    <dd>
                      <strong>{deadline ? deadline.label : opportunity.deadline || 'Not listed'}</strong>
                      {deadline && <small>{deadline.note}</small>}
                    </dd>
                  </div>
                  <div>
                    <dt>Eligibility</dt>
                    <dd>
                      <EligibilityBadge status={eligibility.status} />
                    </dd>
                  </div>
                </dl>
                <footer className="match-card-actions" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                  <OpportunityCompareCheckbox opportunity={{ ...opportunity, title }} />
                  <button
                    type="button"
                    className={`program-row-save ${saved ? 'is-saved' : ''}`}
                    aria-label={`${saved ? 'Remove saved' : 'Save'} ${title}`}
                    aria-pressed={saved}
                    onClick={() => toggleSaveOpportunity(opportunity.id)}
                  >
                    <Bookmark size={16} fill={saved ? 'currentColor' : 'none'} aria-hidden="true" />
                  </button>
                  <button type="button" className="match-card-financial" onClick={checkFinancialFeasibility}>
                    <Calculator size={14} aria-hidden="true" /> Check Financial Feasibility
                  </button>
                  <button type="button" className="match-card-open" onClick={openDetails}>
                    View details <ChevronRight size={16} aria-hidden="true" />
                  </button>
                </footer>
              </div>
            );
          })}
        </div>
      )}
      {!isLoading && excluded.length > 0 && (category !== 'programs') && (
        <details className="matched-page-disclaimer">
          <summary>Not recommended right now ({excluded.length})</summary>
          <ul>
            {excluded.map((item) => (
              <li key={item.scholarship_id}><strong>{item.scholarship_name}:</strong> {getExclusionLabel(item)}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="matched-page-disclaimer">Scholarship scores show how suitable an opportunity looks from its records. They aren't your chance of winning an award or being admitted. Program scores aren't available yet. Verify details with the official university or scholarship provider.</p>
      {comparisonOpportunityIds.length > 0 && <ComparisonSelectionBar />}
    </div>
  );
}
