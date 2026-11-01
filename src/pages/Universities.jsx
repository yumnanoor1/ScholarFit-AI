import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  Bookmark,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Info,
  Landmark,
  Search,
  X,
  XCircle,
} from 'lucide-react';
import { apiService } from '../services/api';
import { useProfile } from '../context/ProfileContext';
import { useProgramEligibility } from '../hooks/useProgramEligibility';
import { getDeadlineInfo, getUniversityLogo } from '../services/programFit';
import { ComparisonSelectionBar, OpportunityCompareCheckbox } from '../components/opportunities/ComparisonControls';
import { ELIGIBILITY_SORT_ORDER } from '../services/eligibilityBadges';
import RetryButton from '../components/common/RetryButton';
import './Universities.css';

// Eligibility badge shown in each list row
const ELIGIBILITY_BADGES = {
  satisfied: { label: 'Eligible', tone: 'success', icon: CheckCircle2 },
  'missing-information': { label: 'Profile info missing', tone: 'warning', icon: AlertTriangle },
  'not-satisfied': { label: 'Not eligible', tone: 'danger', icon: XCircle },
  'awaiting-verification': { label: 'Verify manually', tone: 'neutral', icon: CircleHelp },
};

const tuitionRanges = [
  { value: 'all', label: 'Any tuition range', max: Infinity },
  { value: 'under-10000', label: 'Under $10,000 / year', max: 10000 },
  { value: '10000-25000', label: '$10,000–$25,000 / year', min: 10000, max: 25000 },
  { value: 'over-25000', label: 'Over $25,000 / year', min: 25000, max: Infinity },
];

function getAnnualTuition(tuition) {
  const amount = Number(String(tuition || '').replace(/[^\d.]/g, ''));
  return Number.isFinite(amount) ? amount : null;
}

// Shown above the list when eligibility can't be checked for any program
const ELIGIBILITY_NOTICES = {
  'logged-out': 'Log in to see which programs you are eligible for.',
  'no-profile': 'Complete your profile to see which programs you are eligible for.',
  'not-found': 'Eligibility is not available for these programs yet.',
  error: 'Eligibility could not be checked right now. Please try again later.',
};

export default function Universities() {
  const navigate = useNavigate();
  const {
    isOpportunitySaved,
    toggleSaveOpportunity,
    activeOpportunityId,
    comparisonOpportunityIds,
  } = useProfile();
  const [programs, setPrograms] = useState([]);
  const [scholarships, setScholarships] = useState([]);
  const [statusFilter, setStatusFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');
  const [countryFilter, setCountryFilter] = useState('All');
  const [tuitionFilter, setTuitionFilter] = useState('all');
  const [fundingFilter, setFundingFilter] = useState('all');
  const [sortBy, setSortBy] = useState('match');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [showSampleBanner, setShowSampleBanner] = useState(false);
  const eligibility = useProgramEligibility();
  const { getEvaluation } = eligibility;
  const isLoading = loading || eligibility.loading;

  useEffect(() => {
    let isCurrent = true;
    Promise.all([
      apiService.getMatchedUniversities(),
      apiService.getMatchedScholarships(),
    ])
      .then(([matchedPrograms, matchedScholarships]) => {
        if (!isCurrent) return;
        setPrograms(matchedPrograms);
        setScholarships(matchedScholarships);
        // Show sample-data banner only when mock fallback data is present
        const hasSampleData = matchedPrograms.some((p) => p.sourceStatus === 'unverified-sample');
        setShowSampleBanner(hasSampleData);
      })
      .catch((error) => {
        console.error('Unable to load university matches.', error);
        if (isCurrent) setLoadError('University matches could not be loaded. Please try again later.');
      })
      .finally(() => {
        if (isCurrent) setLoading(false);
      });
    return () => {
      isCurrent = false;
    };
  }, []);

  const countries = useMemo(
    () => [...new Set(programs.map((program) => program.country).filter(Boolean))].sort(),
    [programs],
  );

  const scholarshipsByCountry = useMemo(() => scholarships.reduce((grouped, scholarship) => {
    const country = scholarship.country;
    if (!country) return grouped;
    grouped[country] = [...(grouped[country] || []), scholarship];
    return grouped;
  }, {}), [scholarships]);

  const filteredPrograms = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    const tuitionRange = tuitionRanges.find((range) => range.value === tuitionFilter);

    return programs
      .filter((program) => {
        if (statusFilter !== 'All' && getEvaluation(program.id).status !== statusFilter) return false;
        if (countryFilter !== 'All' && program.country !== countryFilter) return false;
        if (query && !`${program.program} ${program.university} ${program.country}`.toLowerCase().includes(query)) return false;

        const tuition = getAnnualTuition(program.tuition);
        if (tuitionRange && tuitionFilter !== 'all') {
          if (tuition === null || tuition < (tuitionRange.min ?? 0) || tuition >= tuitionRange.max) return false;
        }

        const hasCountryFunding = (scholarshipsByCountry[program.country] || []).length > 0;
        if (fundingFilter === 'available' && !hasCountryFunding) return false;
        if (fundingFilter === 'none' && hasCountryFunding) return false;
        return true;
      })
      .sort((first, second) => {
        if (sortBy === 'tuition-asc' || sortBy === 'tuition-desc') {
          const difference = (getAnnualTuition(first.tuition) ?? Infinity) - (getAnnualTuition(second.tuition) ?? Infinity);
          return sortBy === 'tuition-asc' ? difference : -difference;
        }
        const statusDifference = ELIGIBILITY_SORT_ORDER[getEvaluation(first.id).status]
          - ELIGIBILITY_SORT_ORDER[getEvaluation(second.id).status];
        return statusDifference || (second.matchScore ?? 0) - (first.matchScore ?? 0);
      });
  }, [programs, getEvaluation, searchTerm, statusFilter, countryFilter, tuitionFilter, fundingFilter, sortBy, scholarshipsByCountry]);

  const statusCounts = programs.reduce((counts, program) => {
    const status = getEvaluation(program.id).status;
    counts[status] = (counts[status] || 0) + 1;
    return counts;
  }, {});
  const filterTabs = [
    { value: 'All', label: 'All matches', count: programs.length },
    { value: 'satisfied', label: 'Eligible', count: statusCounts.satisfied || 0 },
    { value: 'missing-information', label: 'Profile info missing', count: statusCounts['missing-information'] || 0 },
    { value: 'not-satisfied', label: 'Not eligible', count: statusCounts['not-satisfied'] || 0 },
    { value: 'awaiting-verification', label: 'Verify manually', count: statusCounts['awaiting-verification'] || 0 },
  ].filter((tab) => tab.value === 'All' || tab.count > 0 || tab.value === statusFilter);

  return (
    <div className="universities-page">
      <section className="university-filters" aria-label="Filter university matches">
        <div className="university-filter-controls">
          <label className="university-search">
            <Search size={16} aria-hidden="true" />
            <input
              type="search"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Search universities or programs..."
              aria-label="Search universities or programs"
            />
          </label>

          <select value={countryFilter} onChange={(event) => setCountryFilter(event.target.value)} aria-label="Filter by country">
            <option value="All">Country</option>
            {countries.map((country) => <option key={country} value={country}>{country}</option>)}
          </select>
          <select value={tuitionFilter} onChange={(event) => setTuitionFilter(event.target.value)} aria-label="Filter by tuition range">
            {tuitionRanges.map((range) => <option key={range.value} value={range.value}>{range.label}</option>)}
          </select>
          <select value={fundingFilter} onChange={(event) => setFundingFilter(event.target.value)} aria-label="Filter by country scholarship options">
            <option value="all">Funding</option>
            <option value="available">Country options listed</option>
            <option value="none">No country options listed</option>
          </select>
          <select value={sortBy} onChange={(event) => setSortBy(event.target.value)} aria-label="Sort university matches">
            <option value="match">Sort by: Best Match</option>
            <option value="tuition-asc">Sort by: Lowest Tuition</option>
            <option value="tuition-desc">Sort by: Highest Tuition</option>
          </select>
        </div>
        <div className="university-filter-row">
          <div className="university-filter-tabs" role="group" aria-label="Requirement status filter">
            {filterTabs.map((tab) => (
              <button
                key={tab.value}
                type="button"
                className={statusFilter === tab.value ? 'active' : ''}
                aria-label={`${tab.label} (${tab.count})`}
                aria-pressed={statusFilter === tab.value}
                onClick={() => setStatusFilter(tab.value)}
              >
                {tab.label}<span className="university-filter-count">{tab.count}</span>
              </button>
            ))}
          </div>
          {!isLoading && !loadError && (
            <p className="university-result-count">
              {filteredPrograms.length} {filteredPrograms.length === 1 ? 'program' : 'programs'}
            </p>
          )}
        </div>
      </section>

      {showSampleBanner && (
        <aside className="university-sample-banner" role="note">
          <Info size={15} aria-hidden="true" />
          <span>Sample data. Requirements need official verification.</span>
          <button type="button" aria-label="Dismiss sample data notice" onClick={() => setShowSampleBanner(false)}>
            <X size={15} aria-hidden="true" />
          </button>
        </aside>
      )}

      <section className="university-results" aria-label="Matched university programs" aria-live="polite">
        {isLoading && <p className="university-message">Loading university matches...</p>}
        {!isLoading && loadError && <div className="university-message university-error" role="alert"><p>{loadError}</p><RetryButton /></div>}
        {!isLoading && !loadError && programs.length > 0 && eligibility.state !== 'ok' && (
          <p className="university-notice" role="status">
            <Info size={16} aria-hidden="true" />
            <span>{ELIGIBILITY_NOTICES[eligibility.state] || ELIGIBILITY_NOTICES.error}</span>
            {eligibility.state === 'no-profile' && (
              <Link to="/profile">Complete profile <ChevronRight size={14} aria-hidden="true" /></Link>
            )}
          </p>
        )}
        {!isLoading && !loadError && filteredPrograms.length === 0 && (
          <p className="university-message">No programs match these filters. Try adjusting your search.</p>
        )}
        {!isLoading && !loadError && filteredPrograms.length > 0 && (
          <div className="program-list" role="list">
            <div className="program-list-head" aria-hidden="true">
              <span>Program</span>
              <span>Tuition / year</span>
              <span>Deadline</span>
              <span>Eligibility</span>
              <span>Compare</span>
            </div>
            {filteredPrograms.map((program) => {
              const evaluation = getEvaluation(program.id);
              const status = ELIGIBILITY_BADGES[evaluation.status] || ELIGIBILITY_BADGES['awaiting-verification'];
              const deadline = getDeadlineInfo(program.deadline);
              const saved = isOpportunitySaved(program.id);
              const openProgram = () => navigate(`/universities/${program.id}`);
              return (
                <div
                  key={program.id}
                  role="listitem"
                  className={`program-row ${activeOpportunityId === program.id ? 'is-active' : ''}`}
                  tabIndex={0}
                  aria-label={`${program.program} at ${program.university}, ${status.label}. Open details`}
                  onClick={openProgram}
                  onKeyDown={(event) => {
                    if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
                      event.preventDefault();
                      openProgram();
                    }
                  }}
                >
                  <div className="program-row-main">
                    <span className={`program-row-mark ${getUniversityLogo(program.university) ? 'has-logo' : ''}`} aria-hidden="true">
                      {getUniversityLogo(program.university)
                        ? <img src={getUniversityLogo(program.university)} alt="" loading="lazy" decoding="async" />
                        : <Landmark size={20} />}
                    </span>
                    <div className="program-row-copy">
                      <strong>{program.program}</strong>
                      <span>{program.university} · {program.country}</span>
                      {program.fieldOfStudy && (
                        <span className="program-row-tags"><em>{program.fieldOfStudy}</em></span>
                      )}
                    </div>
                  </div>
                  <div className="program-row-cell" data-label="Tuition / year">
                    <strong>{program.tuitionOriginal || program.tuition || 'Not listed'}</strong>
                    {program.tuitionAmount > 0 && program.tuitionCurrency !== 'USD' && program.tuition && <small>≈ {program.tuition.replace(' / year', '')}</small>}
                  </div>
                  <div className="program-row-cell" data-label="Deadline">
                    <strong>{deadline ? deadline.label : program.deadline || 'Not listed'}</strong>
                    {deadline && <small>{deadline.passed ? 'Passed' : `${deadline.days} days left`}</small>}
                  </div>
                  <div className="program-row-cell" data-label="Eligibility">
                    <span className={`program-status is-${status.tone}`}>
                      <status.icon size={14} aria-hidden="true" /> {status.label}
                    </span>
                  </div>
                  <div className="program-row-actions" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                    <OpportunityCompareCheckbox opportunity={{ ...program, title: program.program }} />
                    <button
                      type="button"
                      className={`program-row-save ${saved ? 'is-saved' : ''}`}
                      aria-label={`${saved ? 'Remove saved' : 'Save'} ${program.program}`}
                      aria-pressed={saved}
                      onClick={() => toggleSaveOpportunity(program.id)}
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
      </section>
      {comparisonOpportunityIds.length > 0 && <ComparisonSelectionBar />}
    </div>
  );
}
