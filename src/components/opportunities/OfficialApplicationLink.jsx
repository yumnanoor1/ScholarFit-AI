import { ExternalLink } from 'lucide-react';

function isHttpUrl(value) {
  try {
    return ['https:', 'http:'].includes(new URL(value).protocol);
  } catch {
    return false;
  }
}

// FitScholars never submits applications; this only links to the official portal when a verified URL exists.
export default function OfficialApplicationLink({ opportunity }) {
  const verified = opportunity.applicationUrlStatus === 'official-verified' && isHttpUrl(opportunity.applicationUrl);
  return (
    <section className="official-application" aria-label="Official application">
      <h2><ExternalLink size={17} aria-hidden="true" />Official application</h2>
      <p>Apply directly with the provider. FitScholar does not submit applications.</p>
      {verified ? (
        <a className="btn btn-primary" href={opportunity.applicationUrl} target="_blank" rel="noopener noreferrer">
          Apply officially <ExternalLink size={14} aria-hidden="true" />
        </a>
      ) : (
        <p role="status">No verified application link. Visit the provider&apos;s official website.</p>
      )}
    </section>
  );
}
