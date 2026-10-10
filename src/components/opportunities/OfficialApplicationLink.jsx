import { ExternalLink } from 'lucide-react';

function isHttpUrl(value) {
  try {
    return ['https:', 'http:'].includes(new URL(value).protocol);
  } catch {
    return false;
  }
}

// FitScholar AI never submits applications; this only links to the official portal when a verified URL exists.
export default function OfficialApplicationLink({ opportunity, applied, onToggleApplied }) {
  const verified = opportunity.applicationUrlStatus === 'official-verified' && isHttpUrl(opportunity.applicationUrl);
  return (
    <section className="official-application" aria-label="Official application">
      <h2>Apply on the official website</h2>
      <p>FitScholar AI does not submit applications. You must complete and submit your application yourself on the official website.</p>
      {verified ? (
        <a className="btn btn-primary" href={opportunity.applicationUrl} target="_blank" rel="noopener noreferrer">
          Apply on Official Website <ExternalLink size={14} aria-hidden="true" />
        </a>
      ) : (
        <p role="status">A verified official application link is not available yet for this opportunity. Check the provider&apos;s official website directly.</p>
      )}
      {onToggleApplied && (
        <label className="official-application-record">
          <input type="checkbox" checked={Boolean(applied)} onChange={(event) => onToggleApplied(event.target.checked)} />
          I have submitted this application myself (recorded by you; not checked by FitScholar AI)
        </label>
      )}
    </section>
  );
}
