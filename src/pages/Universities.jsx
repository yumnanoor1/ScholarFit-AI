import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  Bookmark,
  CalendarDays,
  CheckCircle2,
  GraduationCap,
  Info,
  Landmark,
  Search,
  Wallet,
  X,
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
    documentRecords,
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
  const [showSampleBanner, setShowSampleBanner] = useState(false);

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

  const statusCounts = programs.reduce((counts, program) => {
    const status = evaluateOpportunityEligibility(profile, program).status;
    counts[status] = (counts[status] || 0) + 1;
    return counts;
  }, {});
  const filterTabs = [
    { value: 'All', label: 'All matches', count: programs.length },
    { value: 'satisfied', label: 'Verified', count: statusCounts.satisfied || 0 },
    { value: 'missing-information', label: 'Profile info missing', count: statusCounts['missing-information'] || 0 },
    { value: 'not-satisfied', label: 'Not satisfied', count: statusCounts['not-satisfied'] || 0 },
    { value: 'awaiting-verification', label: 'Awaiting verification', count: statusCounts['awaiting-verification'] || 0 },
  ];

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
          const cgpaStatus = evaluation.requirements.find((requirement) => requirement.field === 'cgpa')?.status;
          const englishStatus = evaluation.requirements.find((requirement) => requirement.field === 'englishScore')?.status;
          const requiredDocuments = program.requiredDocuments || [];
          const documentsPrepared = requiredDocuments.length > 0
            && requiredDocuments.every((document) => documentRecords[document.id]?.status === 'uploaded');
          return (
            <article className="university-program-card" key={program.id}>
              <div className="university-program-main">
                <div className="university-program-identity">
                  <span className="university-mark"><Landmark size={27} aria-hidden="true" /></span>
                  <div className="university-program-copy">
                    <h2>{program.program}</h2>
                    <p><GraduationCap size={14} aria-hidden="true" /> {program.university} <span>·</span> {program.country}</p>
                    <span className="university-degree-tag">{program.degree}</span>
                    <span className={`university-status ${isEligible ? 'is-eligible' : 'is-missing'}`}>
                      {isEligible ? <CheckCircle2 size={14} aria-hidden="true" /> : <AlertTriangle size={14} aria-hidden="true" />}
                      {statusLabel}
                    </span>
                  </div>
                </div>

                <div className="university-match">
                  <div
                    className="university-score-ring"
                    role="progressbar"
                    aria-label={`${program.program} sample match score`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={score}
                    style={{ '--match-score': `${Math.min(Math.max(score, 0), 100)}%` }}
                  >
                    <strong>{score}%</strong>
                  </div>
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
                    <div><span>Study duration</span><strong>{program.duration || 'Not listed'}</strong></div>
                  </div>
                  <div className="university-detail-metric">
                    <CalendarDays size={16} aria-hidden="true" />
                    <div><span>Listed deadline</span><strong>{program.deadline || 'Not listed'} · unverified sample</strong></div>
                  </div>
                </div>
                <div className="university-requirement-chips" aria-label="Profile requirement checklist">
                  <span className={cgpaStatus === 'satisfied' ? 'is-satisfied' : ''} title="CGPA status depends on official requirement verification">
                    {cgpaStatus === 'satisfied' ? '✓' : '?'} CGPA
                  </span>
                  <span className={englishStatus === 'satisfied' ? 'is-satisfied' : ''} title="English status depends on official requirement verification">
                    {englishStatus === 'satisfied' ? '✓' : '?'} English
                  </span>
                  <span className={documentsPrepared ? 'is-satisfied' : ''} title="Uploaded documents are not automatically verified">
                    {documentsPrepared ? '✓' : '?'} Documents
                  </span>
                </div>
              </div>

              <div className="university-card-footer">
                <button type="button" className="university-view-details" onClick={() => navigate(`/universities/${program.id}`)}>
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
                <div className="university-card-footer-tools">
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
            </article>
          );
        })}
      </section>
      {comparisonOpportunityIds.length > 0 && <ComparisonSelectionBar />}
    </div>
  );
}
