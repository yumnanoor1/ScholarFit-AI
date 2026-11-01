/** Small ring showing a recommendation score out of 100; a dash when there is no score. */
export default function MatchRing({ score }) {
  const value = Number(score);
  const hasScore = score != null && score !== '' && Number.isFinite(value);
  return (
    <span
      className={`match-ring ${hasScore ? '' : 'is-empty'}`}
      style={{ '--match': `${hasScore ? Math.min(Math.max(value, 0), 100) : 0}%` }}
      aria-label={hasScore ? `Recommendation score ${value} out of 100` : 'No recommendation score'}
    >
      <strong>{hasScore ? value : '—'}</strong>
    </span>
  );
}
