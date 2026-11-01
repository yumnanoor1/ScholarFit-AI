import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { selectRelevantMatches } from '../../services/opportunityApi';
import { getMatchTone } from '../../services/eligibilityBadges';

const VERIFICATION_LABELS = { verified: 'Relationship verified', unverified: 'Relationship not verified' };

function Facts({ item, side }) {
  const facts = side === 'program'
    ? [item.university_name, item.country, item.degree_level]
    : [item.funding_type, item.scholarship_verification_status === 'unverified' ? 'Unverified scholarship' : null];
  return <small>{facts.filter(Boolean).join(' · ')}</small>;
}

/**
 * Scholarships and programs linked to each other, with the outcome and why.
 * side: which record each row names, "program" on a scholarship page and "scholarship" on a program page.
 */
export default function ScholarshipProgramMatches({ load, recordId, side }) {
  const [result, setResult] = useState(null);

  useEffect(() => {
    let cancelled = false;
    load(recordId)
      .then((items) => { if (!cancelled) setResult({ recordId, items: selectRelevantMatches(items) }); })
      .catch((error) => {
        console.error('Unable to load scholarship and program matches.', error);
        if (!cancelled) setResult({ recordId, failed: true });
      });
    return () => { cancelled = true; };
  }, [load, recordId]);

  const current = result?.recordId === recordId ? result : null;
  if (!current) return <p role="status">Checking linked {side}s...</p>;
  if (current.failed) return <p role="alert">Linked {side}s could not be loaded right now.</p>;
  if (current.items.length === 0) {
    return <p className="scholarship-eligibility-note">No {side} in FitScholars can be linked to this yet. This doesn't mean none exists.</p>;
  }

  return (
    <ul className="scholarship-requirement-list is-match-list">
      {current.items.map((item) => {
        const key = side === 'program' ? item.program_id : item.scholarship_id;
        const to = side === 'program' ? `/universities/${item.program_id}` : `/scholarships/sch-db-${item.scholarship_id}`;
        return (
          <li key={key}>
            <span className={`program-status is-${getMatchTone(item.outcome)}`}>{item.label}</span>
            <div>
              <strong><Link to={to}>{side === 'program' ? item.program_name : item.scholarship_name}</Link></strong>
              <Facts item={item} side={side} />
              <p>{item.explanation}</p>
              {item.evidence && <small>Evidence: {item.evidence}</small>}
              {item.notes && <small>{item.notes}</small>}
              {item.has_relationship && (
                <small>
                  {VERIFICATION_LABELS[item.relationship_verification_status]}
                  {item.last_verified ? `, checked ${item.last_verified}` : ''}
                  {item.source_url && <> · <a href={item.source_url} target="_blank" rel="noreferrer">Source</a></>}
                </small>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
