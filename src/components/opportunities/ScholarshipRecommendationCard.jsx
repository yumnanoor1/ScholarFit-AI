import MatchRing from './MatchRing';
import { useScholarshipRecommendation } from '../../hooks/useScholarshipEligibility';
import { getCategoryTone, getExclusionLabel } from '../../services/eligibilityBadges';

const LIST_LENGTH = 4;

function ReasonList({ title, items }) {
  if (items.length === 0) return null;
  return (
    <details className="sd-reasons sd-details">
      <summary>{title} ({items.length})</summary>
      <ul>
        {items.slice(0, LIST_LENGTH).map((item) => <li key={item}>{item}</li>)}
      </ul>
    </details>
  );
}

/** The personalized score for one scholarship and what it's made of. */
export default function ScholarshipRecommendationCard({ scholarshipId }) {
  const { loading, state, data } = useScholarshipRecommendation(scholarshipId);
  if (state === 'logged-out' || (!loading && state !== 'ok')) return null;

  return (
    <section className="scholarship-eligibility-result" aria-live="polite">
      <h2>Your match</h2>
      {loading && <p role="status">Calculating match…</p>}
      {data && !data.recommended && (
        <>
          <div className="scholarship-eligibility-summary">
            <span className="program-status is-danger">Not recommended</span>
            <span>{getExclusionLabel(data)}</span>
          </div>
          <ReasonList title="Why not?" items={data.negative} />
        </>
      )}
      {data?.recommended && (
        <>
          <div className="scholarship-eligibility-summary">
            <MatchRing score={data.score} />
            <span className={`program-status is-${getCategoryTone(data.category)}`}>{data.category_label}</span>
            <span>{data.category_reason}</span>
          </div>
          <details className="sd-details">
            <summary>Score breakdown</summary>
            <ul className="scholarship-requirement-list is-score-list">
              {data.breakdown.map((item) => (
                <li key={item.dimension}>
                  <span>{item.points} pts</span>
                  <div>
                    <strong>{item.label}</strong>
                    <small>Rated {Math.round(item.value * 100)}% · weight {item.weight}</small>
                  </div>
                </li>
              ))}
            </ul>
          </details>
          <ReasonList title="What helps" items={data.positive} />
          <ReasonList title="What to check" items={data.warnings} />
          <details className="sd-details">
            <summary>About this score</summary>
            <p><strong>Funding:</strong> {data.funding.label}. {data.funding.summary}.</p>
            <p>This score reflects record fit, not your chance of winning or admission.</p>
          </details>
        </>
      )}
    </section>
  );
}
