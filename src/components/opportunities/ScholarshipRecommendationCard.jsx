import MatchRing from './MatchRing';
import { useScholarshipRecommendation } from '../../hooks/useProgramEligibility';
import { getCategoryTone, getExclusionLabel } from '../../services/eligibilityBadges';

const LIST_LENGTH = 4;

function ReasonList({ title, items }) {
  if (items.length === 0) return null;
  return (
    <>
      <strong>{title}</strong>
      <ul style={{ margin: '4px 0 12px', paddingLeft: '20px', fontSize: '0.86rem' }}>
        {items.slice(0, LIST_LENGTH).map((item) => <li key={item}>{item}</li>)}
      </ul>
    </>
  );
}

/** The personalized score for one scholarship and what it's made of. */
export default function ScholarshipRecommendationCard({ scholarshipId, programId }) {
  const { loading, state, data } = useScholarshipRecommendation(scholarshipId, programId);
  if (state === 'logged-out' || (!loading && state !== 'ok')) return null;

  return (
    <section className="scholarship-eligibility-result" aria-live="polite">
      <h2>Your recommendation score</h2>
      {loading && <p role="status">Working out your recommendation...</p>}
      {data && !data.recommended && (
        <>
          <div className="scholarship-eligibility-summary">
            <span className="program-status is-danger">Not recommended</span>
            <span>{getExclusionLabel(data)}</span>
          </div>
          <ReasonList title="Why" items={data.negative} />
        </>
      )}
      {data?.recommended && (
        <>
          <div className="scholarship-eligibility-summary">
            <MatchRing score={data.score} />
            <span className={`program-status is-${getCategoryTone(data.category)}`}>{data.category_label}</span>
            <span>{data.category_reason}</span>
          </div>
          {data.program_match
            ? <p className="scholarship-eligibility-note"><strong>{data.program_match.program_name}:</strong> {data.program_match.label}</p>
            : <p className="scholarship-eligibility-note">No program is selected, so program compatibility isn't part of this score.</p>}
          <ul className="scholarship-requirement-list is-score-list">
            {data.breakdown.map((item) => (
              <li key={item.dimension}>
                <span>{item.points} points</span>
                <div>
                  <strong>{item.label}</strong>
                  <small>Rated {Math.round(item.value * 100)}% · weight {item.weight}</small>
                </div>
              </li>
            ))}
          </ul>
          <ReasonList title="What helps" items={data.positive} />
          <ReasonList title="What to check" items={data.warnings} />
          <p className="scholarship-eligibility-note">
            <strong>Funding:</strong> {data.funding.label}. {data.funding.summary}.
          </p>
          <p className="scholarship-eligibility-note">
            This score shows how suitable the scholarship looks from its records. It isn't your chance of winning an award or being admitted.
          </p>
        </>
      )}
    </section>
  );
}
