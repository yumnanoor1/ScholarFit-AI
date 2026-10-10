import { Bookmark, Building2, Clock3, GraduationCap, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useProfile } from '../context/ProfileContext';
import { mockScholarships, mockUniversities } from '../data/mockData';
import EmptyState from '../components/common/EmptyState';
import { GlowCard } from '../components/ui/spotlight-card';

const countryFlags = {
  Germany: '🇩🇪',
  'United States': '🇺🇸',
  Canada: '🇨🇦',
  'United Kingdom': '🇬🇧',
};

const universityImage = 'https://images.unsplash.com/photo-1562774053-701939374585?auto=format&fit=crop&w=1200&q=85';
const scholarshipImage = 'https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=1200&q=85';

export default function SavedOpportunities() {
  const navigate = useNavigate();
  const {
    savedOpportunities,
    toggleSaveOpportunity,
    selectedOpportunities,
    activeOpportunityId,
    selectOpportunity,
  } = useProfile();
  const savedItems = [
    ...mockUniversities
      .filter((item) => savedOpportunities.includes(item.id))
      .map((item) => ({
        ...item,
        title: item.program,
        organization: item.university,
        kind: 'university',
        tags: [item.degree, item.country].filter(Boolean),
        image: universityImage,
        route: `/universities/${item.id}`,
      })),
    ...mockScholarships
      .filter((item) => savedOpportunities.includes(item.id))
      .map((item) => ({
        ...item,
        title: item.name,
        organization: item.provider,
        kind: 'scholarship',
        tags: [item.type, item.coverage].filter(Boolean),
        image: scholarshipImage,
        route: `/scholarships/${item.id}`,
      })),
  ];

  return (
    <div className="page-container saved-opportunities-page">
      <header className="saved-opportunities-header">
        <h1 className="page-title">Saved Opportunities <span>({savedItems.length})</span></h1>
        <p className="page-subtitle">Your bookmarked universities, programs, and scholarships.</p>
      </header>

      {savedItems.length === 0 ? (
        <EmptyState
          title="No saved opportunities"
          description="Save universities or scholarships to keep them together here."
          actionLabel="Explore scholarships"
          onAction={() => navigate('/scholarships')}
        />
      ) : (
        <div className="saved-opportunity-grid">
          {savedItems.map((item) => {
            const ItemIcon = item.kind === 'university' ? Building2 : GraduationCap;
            const isSelected = selectedOpportunities.some((opportunity) => opportunity.id === item.id);
            return (
              <GlowCard as="article" customSize key={item.id} className="saved-opportunity-card">
                <div className="saved-opportunity-card-heading">
                  <div className="saved-opportunity-title-wrap">
                    <h2>{item.title}</h2>
                    <p>{item.organization} · {item.country} <span aria-hidden="true">{countryFlags[item.country]}</span></p>
                  </div>
                  <button
                    type="button"
                    className="saved-opportunity-bookmark"
                    aria-label={`Remove ${item.title} from saved opportunities`}
                    aria-pressed="true"
                    onClick={() => toggleSaveOpportunity(item.id)}
                  >
                    <Bookmark size={20} fill="currentColor" aria-hidden="true" />
                  </button>
                </div>

                <div className="saved-opportunity-image-wrap">
                  <div className="saved-opportunity-image-fallback" aria-hidden="true">
                    <ItemIcon size={34} />
                  </div>
                  <img
                    src={item.image}
                    alt={`${item.kind === 'university' ? 'Campus for' : 'Students receiving'} ${item.title}`}
                    loading="lazy"
                    onError={(event) => { event.currentTarget.style.display = 'none'; }}
                  />
                </div>

                <div className="saved-opportunity-tags">
                  {item.tags.map((tag) => <span key={tag}>{tag}</span>)}
                </div>

                <p className="saved-opportunity-deadline">
                  <Clock3 size={15} aria-hidden="true" />
                  {item.deadline ? `Deadline: ${item.deadline}` : 'Deadline not listed'}
                </p>

                <div className="saved-opportunity-actions">
                  <button type="button" className="saved-opportunity-apply" onClick={() => selectOpportunity({ ...item, kind: item.kind === 'scholarship' ? 'scholarship' : 'program' })}>
                    {activeOpportunityId === item.id ? 'Active journey' : isSelected ? 'Switch journey here' : 'Select for journey'}
                  </button>
                  <button type="button" className="saved-opportunity-remove" onClick={() => navigate(item.route)}>
                    View details
                  </button>
                  <button
                    type="button"
                    className="saved-opportunity-remove"
                    onClick={() => toggleSaveOpportunity(item.id)}
                    aria-label={`Remove ${item.title} from saved opportunities`}
                  >
                    <Trash2 size={15} aria-hidden="true" /> Remove
                  </button>
                </div>
              </GlowCard>
            );
          })}
        </div>
      )}
    </div>
  );
}