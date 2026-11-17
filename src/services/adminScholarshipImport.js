import { FORM_SECTIONS } from './adminScholarshipForm.js';

export const IMPORT_FIELD_LABELS = Object.fromEntries(
  FORM_SECTIONS.flatMap((section) => section.fields.map((field) => [field.name, field.label])),
);

export function normalizeImportValue(value) {
  if (Array.isArray(value)) {
    return `array:${value.map(normalizeImportValue).sort().join('\u0000')}`;
  }
  if (typeof value === 'string') {
    return `text:${value.trim().replace(/\s+/g, ' ').toLowerCase()}`;
  }
  return `${typeof value}:${String(value)}`;
}

export function getImportFieldGroups(sources) {
  const groups = new Map();
  (sources || []).forEach((source, sourceIndex) => {
    Object.entries(source.fields || {}).forEach(([name, result]) => {
      if (result.status === 'not_found') return;
      if (!groups.has(name)) groups.set(name, { name, entries: [] });
      groups.get(name).entries.push({ sourceIndex, source: source.source, result });
    });
  });
  return [...groups.values()];
}

export function getImportConflicts(sources) {
  return getImportFieldGroups(sources).filter((group) => {
    const candidates = group.entries.filter((entry) => (
      entry.result.value !== null
      && entry.result.value !== undefined
      && entry.result.suggestion_valid !== false
    ));
    return new Set(candidates.map((entry) => normalizeImportValue(entry.result.value))).size > 1;
  });
}

export function importedValueToForm(value) {
  if (Array.isArray(value)) return value.join('\n');
  if (typeof value === 'boolean') return String(value);
  return value == null ? '' : String(value);
}

// --- when the official site refuses to be read ---------------------------

/** The category the backend uses when a site blocks automatic reading. */
export const SOURCE_BLOCKED_CATEGORY = 'source_blocked';

/**
 * What to show after a failed URL import.
 *
 * A refusal is not an error the administrator can retry their way out of, so
 * it gets a plain explanation and the three things that do work: paste the
 * text, upload the PDF, or fill the form in by hand. Any other failure keeps
 * its own message and offers no false choices.
 */
export function getImportFailureGuidance(error) {
  if (!error) return null;
  const blocked = error.category === SOURCE_BLOCKED_CATEGORY;
  if (!blocked) {
    return {
      blocked: false,
      message: error.message || 'The import failed.',
      offerFallbacks: false,
    };
  }
  const status = Number.isInteger(error.httpStatus) ? error.httpStatus : null;
  return {
    blocked: true,
    httpStatus: status,
    message: status
      ? `This website blocked automatic reading (HTTP ${status}). `
        + 'Paste the page text, upload the PDF, or fill in the details manually.'
      : 'This website blocked automatic reading. '
        + 'Paste the page text, upload the PDF, or fill in the details manually.',
    offerFallbacks: true,
  };
}

// --- a page that described more than one award ---------------------------

/**
 * The candidates a draft offers, if it offers a choice at all.
 *
 * A long page is read in sections, so sections can describe different awards.
 * The draft still carries a merged view; these are the individual awards, for
 * an administrator to pick between.
 */
export function getImportCandidates(source) {
  const candidates = source?.candidates;
  if (!Array.isArray(candidates) || candidates.length < 2) return [];
  return candidates.map((candidate, index) => ({
    index,
    label: candidate?.label || `Candidate ${index + 1}`,
    values: candidate?.values || {},
    fields: candidate?.fields || {},
    extractedCount: Object.values(candidate?.fields || {})
      .filter((field) => field?.status === 'extracted').length,
  }));
}

/**
 * The form patch for one chosen candidate.
 *
 * Only fields the candidate actually evidenced, and only where the form is
 * still empty, so choosing a candidate never silently overwrites something an
 * administrator typed.
 */
export function buildCandidatePatch(candidate, values = {}) {
  const patch = {};
  for (const [name, field] of Object.entries(candidate?.fields || {})) {
    if (field?.status !== 'extracted') continue;
    if (values[name]?.trim?.()) continue;
    patch[name] = importedValueToForm(field.value);
  }
  return patch;
}

/** How the page was read, for a one-line note. */
export function describeImportReading(source) {
  const chunks = Number(source?.chunk_count);
  if (!Number.isInteger(chunks) || chunks <= 1) return '';
  return `Read in ${chunks} sections because the page is long.`;
}
