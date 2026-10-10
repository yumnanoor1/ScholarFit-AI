import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  Bookmark,
  CalendarDays,
  CheckCircle2,
  CircleHelp,
  GraduationCap,
  Landmark,
  Search,
  Wallet,
} from 'lucide-react';
import { apiService } from '../services/api';
import { useProfile } from '../context/ProfileContext';
import { evaluateOpportunityEligibility } from '../services/opportunityJourney';
import { ComparisonSelectionBar, OpportunityCompareCheckbox } from '../components/opportunities/ComparisonControls';

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

export default function Universities() {
  const navigate = useNavigate();
  const {
    profile,
    isOpportunitySaved,
    toggleSaveOpportunity,
    selectedOpportunities,
    activeOpportunityId,
    selectOpportunity,
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
        if (statusFilter !== 'All' && evaluateOpportunityEligibility(profile, program).status !== statusFilter) return false;
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
        return (second.matchScore ?? 0) - (first.matchScore ?? 0);
      });
  }, [programs, profile, searchTerm, statusFilter, countryFilter, tuitionFilter, fundingFilter, sortBy, scholarshipsByCountry]);

  const eligibleCount = programs.filter((program) => evaluateOpportunityEligibility(profile, program).status === 'satisfied').length;
  const savedCount = programs.filter((program) => isOpportunitySaved(program.id)).length;
  const filterTabs = [
    { value: 'All', label: 'All Matches' },
    { value: 'satisfied', label: 'Verified satisfied' },
    { value: 'missing-information', label: 'Missing profile information' },
    { value: 'not-satisfied', label: 'Not satisfied' },
    { value: 'awaiting-verification', label: 'Awaiting verification' },
  ];

  return (
    <div className="universities-page">
      <header className="universities-header">
        <div>
          <p className="universities-breadcrumb">FITSCHOLAR AI <span>/</span> OPPORTUNITIES</p>
          <h1>University &amp; Admission Matching</h1>
          <p className="universities-subtitle">Sample program matches. Requirement statuses use the shared profile check and may need official verification.</p>
        </div>
        <span className="universities-info" title="Match scores are based on your academic profile and preferences, not a guarantee of admission.">
          <CircleHelp size={18} aria-hidden="true" />
          <span className="universities-info-tooltip">Match scores are based on your academic profile and preferences, not a guarantee of admission.</span>
        </span>
      </header>

      <section className="university-stats" aria-label="University match summary">
        <article className="university-stat">
          <span className="university-stat-icon programs"><GraduationCap size={20} aria-hidden="true" /></span>
          <div><p>Programs Found</p><strong>{programs.length}</strong></div>
        </article>
        <article className="university-stat">
          <span className="university-stat-icon eligible"><CheckCircle2 size={20} aria-hidden="true" /></span>
          <div><p>Verified Satisfied</p><strong>{eligibleCount}</strong></div>
        </article>
        <article className="university-stat">
          <span className="university-stat-icon saved"><Bookmark size={20} aria-hidden="true" /></span>
          <div><p>Saved Programs</p><strong>{savedCount}</strong></div>
        </article>
      </section>

      <section className="university-filters" aria-label="Filter university matches">
        <div className="university-filter-tabs" role="group" aria-label="Requirement status filter">
          {filterTabs.map((tab) => (
            <button
              key={tab.value}
              type="button"
              className={statusFilter === tab.value ? 'active' : ''}
              aria-pressed={statusFilter === tab.value}
              onClick={() => setStatusFilter(tab.value)}
            >
              {tab.label}
            </button>
          ))}
        </div>

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
      </section>

      <section className="university-results" aria-label="Matched university programs" aria-live="polite">
        {loading && <p className="university-message">Loading university matches...</p>}
        {!loading && loadError && <p className="university-message university-error" role="alert">{loadError}</p>}
        {!loading && !loadError && filteredPrograms.length === 0 && (
          <p className="university-message">No programs match these filters. Try adjusting your search.</p>
        )}
        {!loading && !loadError && filteredPrograms.map((program) => {
          const evaluation = evaluateOpportunityEligibility(profile, program);
          const isEligible = evaluation.status === 'satisfied';
          const statusLabel = evaluation.status.replaceAll('-', ' ');
          const countryScholarships = scholarshipsByCountry[program.country] || [];
          const score = program.matchScore ?? 0;
          return (
            <article className="university-program-card" key={program.id}>
              <div className="university-program-main">
                <div className="university-program-identity">
                  <span className="university-mark"><Landmark size={27} aria-hidden="true" /></span>
                  <div className="university-program-copy">
                    <h2>{program.program}</h2>
                    <p><GraduationCap size={14} aria-hidden="true" /> {program.university} <span>·</span> {program.country}</p>
                    <span className="university-degree-tag">{program.degree}</span>
                  </div>
                </div>

                <div className="university-match">
                  <div><strong>{score}%</strong><span>Sample Match Score</span></div>
                  <div className="university-match-track" role="progressbar" aria-label={`${program.program} match score`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={score}>
                    <span style={{ width: `${Math.min(Math.max(score, 0), 100)}%` }} />
                  </div>
                </div>

                <div className="university-program-actions">
                  <span className={`university-status ${isEligible ? 'is-eligible' : 'is-missing'}`}>
                    {isEligible ? <CheckCircle2 size={14} aria-hidden="true" /> : <AlertTriangle size={14} aria-hidden="true" />}
                    {statusLabel}
                  </span>
                  <OpportunityCompareCheckbox opportunity={{ ...program, title: program.program }} />
                  <button
                    type="button"
                    className={`university-save ${isOpportunitySaved(program.id) ? 'is-saved' : ''}`}
                    aria-label={`${isOpportunitySaved(program.id) ? 'Remove saved' : 'Save'} ${program.program}`}
                    aria-pressed={isOpportunitySaved(program.id)}
                    onClick={() => toggleSaveOpportunity(program.id)}
                  >
                    <Bookmark size={15} fill={isOpportunitySaved(program.id) ? 'currentColor' : 'none'} aria-hidden="true" />
                    {isOpportunitySaved(program.id) ? 'Saved' : 'Save'}
                  </button>
                </div>
              </div>

              <div className="university-program-details">
                <div className="university-detail-metrics">
                  <div className="university-detail-metric">
                    <Wallet size={16} aria-hidden="true" />
                    <div><span>Listed tuition / year</span><strong>{program.tuition || 'Not listed'} · unverified sample</strong></div>
                  </div>
                  <div className="university-detail-metric">
                    <GraduationCap size={16} aria-hidden="true" />
                    <div>
                      <span>Same-country scholarship listings</span>
                      <strong className={countryScholarships.length ? 'funding-listed' : ''}>
                        {countryScholarships.length ? `${countryScholarships.length} listed; not confirmed for this program` : 'None listed'}
                      </strong>
                    </div>
                  </div>
                  <div className="university-detail-metric">
                    <CalendarDays size={16} aria-hidden="true" />
                    <div><span>Listed deadline</span><strong>{program.deadline || 'Not listed'} · unverified sample</strong></div>
                  </div>
                </div>
                <aside className={`university-match-reason ${isEligible ? 'reason-eligible' : 'reason-missing'}`}>
                  {isEligible ? <CheckCircle2 size={16} aria-hidden="true" /> : <AlertTriangle size={16} aria-hidden="true" />}
                  <div>
                    <strong>{isEligible ? 'Requirement status' : 'Requirement status'}</strong>
                    <p>{evaluation.message || `Shared profile check: ${statusLabel}. Sample criteria and dates require official confirmation.`}</p>
                  </div>
                </aside>
              </div>

              <div className="university-card-footer">
                <button type="button" onClick={() => navigate(`/universities/${program.id}`)}>
                  View Details <span aria-hidden="true">→</span>
                </button>
                {countryScholarships.length > 0 && (
                  <button type="button" className="university-scholarship-link" onClick={() => navigate('/scholarships')}>
                    View {countryScholarships.length} country scholarship {countryScholarships.length === 1 ? 'option' : 'options'}
                  </button>
                )}
                <button
                  type="button"
                  className="university-scholarship-link"
                  onClick={() => selectOpportunity({ ...program, kind: 'program' })}
                >
                  {activeOpportunityId === program.id
                    ? 'Viewing this opportunity'
                    : selectedOpportunities.some((item) => item.id === program.id) ? 'Switch journey here' : 'Start this journey'}
                </button>
              </div>
            </article>
          );
        })}
      </section>
      <p className="university-disclaimer">* Match scores and opportunity data are sample data, not verified admissions decisions. Confirm requirements, deadlines, tuition, and funding with the university and scholarship provider.</p>
      {comparisonOpportunityIds.length > 0 && <ComparisonSelectionBar />}
    </div>
  );
}
