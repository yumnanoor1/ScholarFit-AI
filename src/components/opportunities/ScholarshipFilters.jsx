import { Search, SlidersHorizontal, X } from 'lucide-react';
import { ELIGIBILITY_OPTIONS, SORT_OPTIONS, getActiveFilters, removeFilterValue, toggleFilterValue } from '../../services/scholarshipSearch';

function ChipGroup({ legend, name, options, filters, onChange, disabled = false, hint }) {
  if (!options?.length) return null;
  return (
    <fieldset className="scholarships-filter-group" disabled={disabled}>
      <legend>{legend}</legend>
      <div className="scholarships-filter-options">
        {options.map((option) => (
          <label className="scholarships-filter-chip" key={option.value}>
            <input type="checkbox" checked={filters[name].includes(option.value)} onChange={() => onChange(toggleFilterValue(filters, name, option.value))} />
            <span>{option.label}</span>
            {option.count > 0 && <small>{option.count}</small>}
          </label>
        ))}
      </div>
      {hint && <p className="scholarships-filter-hint">{hint}</p>}
    </fieldset>
  );
}

/** Search, sorting and the collapsible filter panel of Explore Scholarships. */
export default function ScholarshipFilters({
  searchText, onSearchText, filters, onChange, options, programId, onProgramChange, sort, onSortChange, total, loading,
  signedIn, open, onToggle, onClear,
}) {
  const active = getActiveFilters(filters, options);
  const panelCount = active.filter((item) => item.key !== 'q').length + (programId != null ? 1 : 0);
  const discipline = filters.discipline[0] || '';
  const hasFilters = active.length > 0 || programId != null;

  return (
    <section className="scholarships-search" aria-label="Search and filter scholarships">
      <div className="scholarships-search-row">
        <label className="scholarships-search-input">
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            value={searchText}
            onChange={(event) => onSearchText(event.target.value)}
            placeholder="Search by name, provider, country, field..."
            aria-label="Search scholarships"
            maxLength={100}
          />
        </label>
        <label className="scholarships-sort-select">
          <span>Sort by</span>
          <select value={sort} onChange={(event) => onSortChange(event.target.value)} aria-label="Sort scholarships">
            {SORT_OPTIONS.filter((option) => signedIn || !option.needsLogin).map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <button type="button" className="scholarships-filter-toggle" aria-expanded={open} aria-controls="scholarship-filter-panel" onClick={onToggle}>
          <SlidersHorizontal size={15} aria-hidden="true" /> Filters{panelCount > 0 ? ` (${panelCount})` : ''}
        </button>
      </div>

      <div className="scholarships-result-line">
        <strong role="status">{loading ? 'Searching...' : total === null ? 'Results unavailable' : `${total} scholarship${total === 1 ? '' : 's'} found`}</strong>
        {active.map((item) => (
          <button type="button" className="scholarships-active-chip" key={`${item.key}-${item.value}`} onClick={() => onChange(removeFilterValue(filters, item.key, item.value))} aria-label={`Remove filter ${item.label}`}>
            {item.label} <X size={12} aria-hidden="true" />
          </button>
        ))}
        {hasFilters && <button type="button" className="scholarships-clear" onClick={onClear}>Clear all filters</button>}
      </div>

      {open && (
        <div className="scholarships-filter-bar" id="scholarship-filter-panel">
          <ChipGroup legend="Host country (where you'd study)" name="host_country" options={options?.host_countries} filters={filters} onChange={onChange} />
          <div className="scholarships-filter-group">
            <label className="scholarships-filter-field">
              <span>Your citizenship (who can apply)</span>
              <input
                type="text"
                list="scholarship-nationalities"
                value={filters.nationality}
                onChange={(event) => onChange({ ...filters, nationality: event.target.value })}
                placeholder="e.g. Pakistan"
                maxLength={80}
              />
              <datalist id="scholarship-nationalities">{options?.nationalities.map((name) => <option key={name} value={name} />)}</datalist>
            </label>
          </div>
          <ChipGroup legend="Nationality rule" name="nationality_scope" options={options?.nationality_scopes} filters={filters} onChange={onChange} />
          <ChipGroup legend="Degree level" name="degree" options={options?.degree_levels} filters={filters} onChange={onChange} />
          <div className="scholarships-filter-group">
            <label className="scholarships-filter-field">
              <span>Academic field</span>
              <select value={discipline} onChange={(event) => onChange({ ...filters, discipline: event.target.value ? [event.target.value] : [] })}>
                <option value="">Any field</option>
                {options?.disciplines.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
          </div>
          <ChipGroup legend="Academic requirement" name="academic_condition" options={options?.academic_conditions} filters={filters} onChange={onChange} />
          <ChipGroup legend="Funding" name="funding" options={options?.funding} filters={filters} onChange={onChange} />
          <ChipGroup legend="Must include" name="benefit" options={options?.benefits} filters={filters} onChange={onChange} />
          <ChipGroup legend="Application status" name="deadline" options={options?.deadlines} filters={filters} onChange={onChange} />
          <ChipGroup legend="Record quality" name="verification" options={options?.verification} filters={filters} onChange={onChange} />
          <ChipGroup
            legend="Your eligibility"
            name="eligibility"
            options={ELIGIBILITY_OPTIONS}
            filters={filters}
            onChange={onChange}
            disabled={!signedIn}
            hint={signedIn ? null : 'Log in to filter by your eligibility.'}
          />
          <div className="scholarships-filter-group">
            <label className="scholarships-filter-field">
              <span>Program you want to study</span>
              <select value={programId ?? ''} onChange={(event) => onProgramChange(event.target.value ? Number(event.target.value) : null)}>
                <option value="">No program selected</option>
                {options?.programs.map((item) => <option key={item.id} value={item.id}>{item.name}, {item.university}</option>)}
              </select>
            </label>
          </div>
          {programId != null && (
            <ChipGroup
              legend="Program compatibility"
              name="match"
              options={options?.match_outcomes}
              filters={filters}
              onChange={onChange}
              hint="Not a Match results are hidden unless you ask for them, and they aren't suitable for this program."
            />
          )}
        </div>
      )}
    </section>
  );
}
