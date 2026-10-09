import { useNavigate } from 'react-router-dom';
import { CalendarDays, ChartNoAxesColumnIncreasing, Check, Clock3, DollarSign, GraduationCap, Languages, MapPin, Star, X } from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { mockUniversities } from '../data/mockData';
import { GlowCard } from '../components/ui/spotlight-card';

function getDeadlineStatus(deadline) {
  const date = new Date(deadline);
  if (Number.isNaN(date.getTime())) return null;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const daysLeft = Math.ceil((date - today) / 86400000);

  if (daysLeft < 0) return `${Math.abs(daysLeft)} days ago`;
  if (daysLeft === 0) return 'Today';
  return `In ${daysLeft} days`;
}

export default function Compare() {
  const navigate = useNavigate();
  const { isOpportunitySaved, toggleSaveOpportunity } = useProfile();

  return (
    <div className="page-container compare-page">
      <header className="compare-page-header">
        <div className="compare-page-title">
          <ChartNoAxesColumnIncreasing size={32} aria-hidden="true" />
          <div>
            <h1>Program Comparison</h1>
            <p>Compare tuition, admission requirements, and fit across programs.</p>
          </div>
        </div>
        <button type="button" className="compare-close-button" onClick={() => navigate(-1)}>
          <X size={16} aria-hidden="true" /> Close
        </button>
      </header>

      <div className="program-comparison-grid">
        {mockUniversities.map((program) => {
          const saved = isOpportunitySaved(program.id);
          const deadlineStatus = getDeadlineStatus(program.deadline);
          const metrics = [
            { label: 'Tuition', value: program.tuition, Icon: DollarSign },
            { label: 'Match score', value: `${program.matchScore}%`, Icon: Star, highlight: true },
            { label: 'Eligibility', value: program.eligibilityStatus, Icon: Check },
            { label: 'CGPA requirement', value: program.cgpaReq, Icon: GraduationCap },
            { label: 'English requirement', value: program.englishReq, Icon: Languages },
            { label: 'Application deadline', value: program.deadline, Icon: CalendarDays, detail: deadlineStatus, urgent: deadlineStatus && !deadlineStatus.includes('ago') && Number.parseInt(deadlineStatus.replace(/\D/g, ''), 10) < 30 },
          ];

          return (
            <GlowCard as="article" customSize key={program.id} className="program-comparison-card">
              <header className="program-comparison-card-header">
                <div>
                  <h2>{program.university}</h2>
                  <p className="program-comparison-location"><MapPin size={15} aria-hidden="true" /> {program.country}</p>
                  <p className="program-comparison-program">{program.program}</p>
                </div>
                <div className="program-comparison-score" aria-label={`Match score ${program.matchScore} percent`}>
                  <span>{program.matchScore}</span>
                </div>
              </header>

              <dl className="program-comparison-metrics">
                {metrics.map(({ label, value, Icon, highlight, detail, urgent }) => (
                  <div key={label} className="program-comparison-metric">
                    <dt><Icon size={16} aria-hidden="true" /> {label}</dt>
                    <dd className={`${highlight ? 'is-highlight' : ''} ${urgent ? 'is-urgent' : ''}`}>
                      <span>{value}</span>
                      {detail && <small><Clock3 size={12} aria-hidden="true" /> {detail}</small>}
                    </dd>
                  </div>
                ))}
              </dl>

              <button
                type="button"
                className={`program-comparison-save${saved ? ' is-saved' : ''}`}
                aria-pressed={saved}
                onClick={() => toggleSaveOpportunity(program.id)}
              >
                <Star size={17} fill={saved ? 'currentColor' : 'none'} aria-hidden="true" />
                {saved ? 'Added to My List' : 'Add to My List'}
              </button>
            </GlowCard>
          );
        })}
      </div>
    </div>
  );
}