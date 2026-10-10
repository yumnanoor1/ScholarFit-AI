import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Bookmark, 
  Building2, 
  Briefcase, 
  ChevronDown,
} from 'lucide-react';
import { ChevronSmallRightIcon } from '../components/ui/ChevronSmallRightIcon';
import { GlowCard } from '../components/ui/spotlight-card';
import { ComparisonSelectionBar, OpportunityCompareCheckbox } from '../components/opportunities/ComparisonControls';
import { mockScholarships } from '../data/mockData';
import { useProfile } from '../context/ProfileContext';
import { evaluateOpportunityEligibility } from '../services/opportunityJourney';
import './Scholarships.css';

export default function Scholarships() {
  const navigate = useNavigate();
  const {
    savedOpportunities,
    profile,
    toggleSaveOpportunity,
    selectedOpportunities,
    activeOpportunityId,
    selectOpportunity,
    comparisonOpportunityIds,
  } = useProfile();

  const [sortAscending, setSortAscending] = useState(false);
  const [selectedCountries, setSelectedCountries] = useState([]);
  const [selectedFundingTypes, setSelectedFundingTypes] = useState([]);
  const [expandedFilters, setExpandedFilters] = useState({ country: true, funding: true });

  const scholarshipsList = mockScholarships.map((item) => ({
    ...item,
    kind: 'scholarship',
    title: item.name,
    fundingType: item.type,
    coverage: item.coverage || 'Coverage not listed',
    deadlineBadge: item.deadline || 'Deadline not listed',
    match: item.matchScore,
    eligibility: evaluateOpportunityEligibility(profile, { ...item, kind: 'scholarship' }).status,
    icon: item.type === 'RA'
      ? <Briefcase size={20} color="var(--color-primary)" />
      : <Building2 size={20} color="var(--color-primary)" />,
  }));
  const countries = [...new Set(scholarshipsList.map((item) => item.country).filter(Boolean))].sort();
  const fundingTypes = [...new Set(scholarshipsList.map((item) => item.fundingType).filter(Boolean))];

  const toggleFilter = (setter, value) => {
    setter((current) => current.includes(value)
      ? current.filter((selected) => selected !== value)
      : [...current, value]);
  };

  const toggleFilterSection = (section) => {
    setExpandedFilters((current) => ({ ...current, [section]: !current[section] }));
  };

  const visibleScholarships = scholarshipsList
    .filter((item) => selectedCountries.length === 0 || selectedCountries.includes(item.country))
    .filter((item) => selectedFundingTypes.length === 0 || selectedFundingTypes.includes(item.fundingType))
    .sort((first, second) => sortAscending ? first.match - second.match : second.match - first.match);

  const handleSelectOpportunity = (item) => {
    selectOpportunity(item);
    navigate(`/scholarships/${item.id}`);
  };

  return (
    <div className="page-container scholarship-page" style={{ maxWidth: '1240px', margin: '0 auto', position: 'relative' }}>
      
      {/* Page Header Row */}
      <div className="scholarships-header">
        <div>
          <h1 style={{ fontSize: '2.4rem', fontFamily: 'serif', fontWeight: '600', color: 'var(--color-dark)', marginBottom: '4px' }}>
            Scholarships
          </h1>
          <p style={{ fontSize: '0.9rem', color: 'var(--color-text-muted)' }}>
            Showing {visibleScholarships.length} of {scholarshipsList.length} demo scholarships
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}>
          <span style={{ color: 'var(--color-text-muted)' }}>Sort by</span>
          <button type="button" onClick={() => setSortAscending((current) => !current)} aria-label={`Sort by match percentage, ${sortAscending ? 'ascending' : 'descending'}`} style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid var(--color-border)',
            borderRadius: '6px',
            padding: '8px 14px',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            fontWeight: '600',
            color: 'var(--color-dark)',
            cursor: 'pointer'
          }}>
            Match % {sortAscending ? '↑' : '↓'} <ChevronDown size={16} />
          </button>
        </div>
      </div>

      {/* Main Two-Column Layout */}
      <div className="scholarships-layout">
        
        {/* Left Filter Sidebar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', fontSize: '0.85rem' }}>
          
          {/* Country Filter */}
          <div>
            <button type="button" className="scholarship-filter-toggle" aria-expanded={expandedFilters.country} aria-controls="country-filter-options" onClick={() => toggleFilterSection('country')}>
              <span>COUNTRY</span>
              <ChevronSmallRightIcon size={14} aria-hidden="true" style={{ transform: expandedFilters.country ? 'rotate(-90deg)' : 'rotate(90deg)', transition: 'transform 180ms ease' }} />
            </button>
            {expandedFilters.country && <div id="country-filter-options" style={{ display: 'flex', flexDirection: 'column', gap: '8px', color: 'var(--color-dark)' }}>
              {countries.map((country) => (
                <label key={country} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                  <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <input type="checkbox" checked={selectedCountries.includes(country)} onChange={() => toggleFilter(setSelectedCountries, country)} /> {country}
                  </span>
                  <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>{scholarshipsList.filter((item) => item.country === country).length}</span>
                </label>
              ))}
            </div>}
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid #E2E8F0', margin: '4px 0' }} />

          {/* Funding Type Filter */}
          <div>
            <button type="button" className="scholarship-filter-toggle" aria-expanded={expandedFilters.funding} aria-controls="funding-filter-options" onClick={() => toggleFilterSection('funding')}>
              <span>FUNDING TYPE</span>
              <ChevronSmallRightIcon size={14} aria-hidden="true" style={{ transform: expandedFilters.funding ? 'rotate(-90deg)' : 'rotate(90deg)', transition: 'transform 180ms ease' }} />
            </button>
            {expandedFilters.funding && <div id="funding-filter-options" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {fundingTypes.map((type) => (
                <label key={type} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                  <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <input type="checkbox" checked={selectedFundingTypes.includes(type)} onChange={() => toggleFilter(setSelectedFundingTypes, type)} /> {type}
                  </span>
                  <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>{scholarshipsList.filter((item) => item.fundingType === type).length}</span>
                </label>
              ))}
            </div>}
          </div>

        </div>

        {/* Right Scholarship List */}
        <div className={`scholarships-results${comparisonOpportunityIds.length > 0 ? ' has-comparison-selection' : ''}`}>
          
          {visibleScholarships.map(item => {
            const isSaved = savedOpportunities.includes(item.id);
            const isJourneySelected = selectedOpportunities.some((opportunity) => opportunity.id === item.id);

            return (
              <GlowCard
                key={item.id}
                customSize
                className="scholarship-result-card"
                style={{
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #E2E8F0',
                  borderRadius: '12px',
                  boxShadow: '0 3px 10px rgba(0,0,0,0.04)'
                }}
              >
                <div className="scholarship-result-header">
                  <OpportunityCompareCheckbox opportunity={item} />
                  <span className="scholarship-result-icon">{item.icon}</span>
                  <div className="scholarship-result-identity">
                    <h3>{item.title}</h3>
                    <p>{item.provider || 'Provider not listed'}</p>
                  </div>
                  <span className={`scholarship-eligibility is-${item.eligibility}`}>
                    {item.eligibility.replaceAll('-', ' ')}
                  </span>
                  <div className="scholarship-match-score">
                    <strong>{item.match}%</strong>
                    <span>Match score</span>
                  </div>
                </div>

                <dl className="scholarship-result-details">
                  <div className="scholarship-result-country">
                    <dt>Country</dt>
                    <dd>{item.country || 'Not listed'}</dd>
                  </div>
                  <div className="scholarship-result-coverage">
                    <dt>Coverage listed</dt>
                    <dd>{item.coverage}</dd>
                  </div>
                  <div className="scholarship-result-deadline">
                    <dt>Deadline listed</dt>
                    <dd>{item.deadline || 'Not listed'}</dd>
                  </div>
                </dl>

                <div className="scholarship-result-actions">
                  <button
                    type="button"
                    className={`scholarship-save-button${isSaved ? ' is-saved' : ''}`}
                    aria-label={`${isSaved ? 'Unsave' : 'Save'} ${item.title}`}
                    aria-pressed={isSaved}
                    onClick={() => toggleSaveOpportunity(item.id)}
                  >
                    <Bookmark size={17} fill={isSaved ? 'currentColor' : 'none'} aria-hidden="true" />
                    <span>{isSaved ? 'Saved' : 'Save'}</span>
                  </button>
                  <div className="scholarship-result-action-buttons">
                    <button type="button" className="scholarship-select-button" onClick={() => handleSelectOpportunity(item)}>
                      {activeOpportunityId === item.id ? 'Viewing' : isJourneySelected ? 'Switch here' : 'Select'}
                    </button>
                    <button type="button" className="scholarship-details-button" onClick={() => navigate(`/scholarships/${item.id}`)}>
                      Details
                    </button>
                  </div>
                </div>
              </GlowCard>
            );
          })}

          {visibleScholarships.length === 0 && <p role="status">No demo scholarships match these filters.</p>}
        </div>

      </div>

      {comparisonOpportunityIds.length > 0 && <ComparisonSelectionBar />}
    </div>
  );
}