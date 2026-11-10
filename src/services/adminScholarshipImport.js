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
