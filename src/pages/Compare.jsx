import { useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, Bookmark, CalendarDays, ChartNoAxesColumnIncreasing, DollarSign, GitCompare, GraduationCap, Landmark, Languages, Lightbulb, MapPin, Search, Star } from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { mockScholarships, mockUniversities } from '../data/mockData';
import { GlowCard } from '../components/ui/spotlight-card';

export default function Compare() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const {
    isOpportunitySaved,
    toggleSaveOpportunity,
    savedOpportunities,
    comparisonOpportunityIds,
  } = useProfile();
  const compareIds = useMemo(
    () => (searchParams.get('ids') ?? comparisonOpportunityIds.join(','))
      .split(',')
      .filter(Boolean)
      .slice(0, 2),
    [searchParams, comparisonOpportunityIds],
  );
  const opportunities = useMemo(() => {
    const all = [
      ...mockUniversities.map((item) => ({ ...item, kind: 'program', title: item.program, organization: item.university })),
      ...mockScholarships.map((item) => ({ ...item, kind: 'scholarship', title: item.name, organization: item.provider })),
    ];
    return compareIds.map((id) => all.find((item) => item.id === id)).filter(Boolean);
  }, [compareIds]);

  return (
    <div className="page-container compare-page">
      <header className="compare-page-header">
        <div className="compare-page-title">
          <ChartNoAxesColumnIncreasing size={32} aria-hidden="true" />
          <div><h1>Opportunity Comparison</h1><p>Compare programs and scholarships side by side to make the right decision for your future.</p></div>
        </div>
        {opportunities.length > 0 && (
          <button type="button" className="compare-close-button" onClick={() => navigate(-1)}>Close</button>
        )}
      </header>
      <div className="compare-stat-row">
        <button type="button" className="compare-stat-card" onClick={() => navigate('/saved')}>
          <span className="compare-stat-icon"><Bookmark size={26} aria-hidden="true" /></span>
          <span className="compare-stat-body">
            <strong>{savedOpportunities.length}</strong>
            <span>Saved Items</span>
            <em>View saved items <ArrowRight size={14} aria-hidden="true" /></em>
          </span>
        </button>
        <button type="button" className="compare-stat-card is-green" onClick={() => navigate('/scholarships')}>
          <span className="compare-stat-icon"><GitCompare size={26} aria-hidden="true" /></span>
          <span className="compare-stat-body">
            <strong>{opportunities.length}</strong>
            <span>Selected for comparison</span>
            <em>Manage selection <ArrowRight size={14} aria-hidden="true" /></em>
          </span>
        </button>
      </div>
      {opportunities.length < 2 ? (
        <section className="card compare-empty">
          <div>
            <h2>{opportunities.length === 1 ? 'Select one more opportunity' : 'No comparison selected yet'}</h2>
            <p>Select two programs or scholarships from their opportunity cards to compare them side by side.</p>
            <div className="compare-empty-actions">
              <button type="button" className="btn btn-primary" onClick={() => navigate('/universities')}>
                <Search size={16} aria-hidden="true" /> Browse Opportunities <ArrowRight size={16} aria-hidden="true" />
              </button>
              <button type="button" className="btn btn-outline" onClick={() => navigate('/saved')}>
                <Bookmark size={16} aria-hidden="true" /> View Saved Items
              </button>
            </div>
          </div>
          <div className="compare-empty-art" aria-hidden="true">
            <span className="compare-art-card"><Landmark size={30} /></span>
            <span className="compare-art-vs">VS</span>
            <span className="compare-art-card is-green"><GraduationCap size={30} /></span>
          </div>
        </section>
      ) : (
        <div className="program-comparison-grid">
          {opportunities.map((opportunity) => {
            const isProgram = opportunity.kind === 'program';
            const metrics = [
              { label: isProgram ? 'Listed tuition' : 'Listed coverage', value: isProgram ? opportunity.tuition || 'Not listed' : opportunity.coverage || 'Not listed', Icon: DollarSign },
              { label: 'Mock profile fit', value: `${opportunity.matchScore ?? 'Unavailable'}%`, Icon: Star },
              { label: 'Listed deadline', value: opportunity.deadline || 'Not listed', Icon: CalendarDays },
              ...(isProgram ? [
                { label: 'CGPA requirement', value: opportunity.cgpaReq || 'Not listed', Icon: GraduationCap },
                { label: 'Language requirement', value: opportunity.englishReq || 'Not listed', Icon: Languages },
              ] : [{ label: 'Funding type', value: opportunity.type || 'Not listed', Icon: GraduationCap }]),
            ];
            const saved = isOpportunitySaved(opportunity.id);
            return (
              <GlowCard as="article" customSize key={opportunity.id} className="program-comparison-card">
                <header className="program-comparison-card-header">
                  <div>
                    <h2>{opportunity.title}</h2>
                    <p className="program-comparison-location"><MapPin size={15} aria-hidden="true" /> {opportunity.organization} · {opportunity.country}</p>
                  </div>
                </header>
                <dl className="program-comparison-metrics">
                  {metrics.map(({ label, value, Icon }) => (
                    <div key={label} className="program-comparison-metric">
                      <dt><Icon size={16} aria-hidden="true" /> {label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
                <p>Listing data and match scores are unverified demo data; confirm details with the provider.</p>
                <button type="button" className={`program-comparison-save${saved ? ' is-saved' : ''}`} aria-pressed={saved} onClick={() => toggleSaveOpportunity(opportunity.id)}>
                  <Star size={17} fill={saved ? 'currentColor' : 'none'} aria-hidden="true" />
                  {saved ? 'Saved' : 'Save opportunity'}
                </button>
              </GlowCard>
            );
          })}
        </div>
      )}
      <aside className="compare-tip">
        <Lightbulb size={22} aria-hidden="true" />
        <p><strong>Tip:</strong> Select up to two programs or scholarships using the Compare checkbox on their opportunity cards.</p>
      </aside>
    </div>
  );
}
