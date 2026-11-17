export const SOURCE_VERIFICATION_MAX_AGE_DAYS = 180;

function currentDateString(today) {
  if (typeof today === 'string') return today;
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, '0');
  const day = String(today.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseIsoDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(timestamp) || new Date(timestamp).toISOString().slice(0, 10) !== value) return null;
  return timestamp;
}

function needsVerification(message, status = 'needs-verification') {
  return { status, label: status === 'outdated' ? 'Outdated · needs verification' : 'Needs verification', message };
}

export function getSourceEvidence({
  sourceUrl,
  lastVerified,
  verificationStatus,
  verificationBasis,
  today = new Date(),
}) {
  let url;
  try {
    url = new URL(sourceUrl);
  } catch {
    return needsVerification('No valid official source URL is recorded.');
  }
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname) {
    return needsVerification('No valid official source URL is recorded.');
  }

  const verifiedTimestamp = parseIsoDate(lastVerified);
  if (verifiedTimestamp === null) return needsVerification('No valid source verification date is recorded.');
  const todayTimestamp = parseIsoDate(currentDateString(today));
  if (todayTimestamp === null) return needsVerification('The current date could not be determined.');
  if (verifiedTimestamp > todayTimestamp) return needsVerification('The recorded source verification date is in the future.');
  const ageDays = (todayTimestamp - verifiedTimestamp) / 86_400_000;
  if (ageDays > SOURCE_VERIFICATION_MAX_AGE_DAYS) {
    return needsVerification(`The last recorded source check was ${lastVerified}; it is over ${SOURCE_VERIFICATION_MAX_AGE_DAYS} days old.`, 'outdated');
  }

  if (verificationStatus === undefined) {
    return {
      status: 'recorded',
      label: 'Verification status not tracked',
      message: `A source URL and check date (${lastVerified}) are recorded, but official-source verification status is not tracked.`,
    };
  }
  if (verificationStatus !== 'verified') {
    return needsVerification('This scholarship record has not been verified against its official source.');
  }
  if (verificationBasis !== 'official_source') {
    return needsVerification('This record is not confirmed from an official source.');
  }
  return {
    status: 'verified',
    label: 'Verified against official source',
    message: `Last verified ${lastVerified}.`,
  };
}
