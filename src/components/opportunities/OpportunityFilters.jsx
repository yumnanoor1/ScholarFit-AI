import React from 'react';
import { Filter, Search } from 'lucide-react';

export default function OpportunityFilters({
  searchTerm,
  onSearchChange,
  statusFilter,
  onStatusChange,
  countryFilter,
  onCountryChange,
  countries = ["All", "Germany", "United States", "Canada", "United Kingdom"]
}) {
  return (
    <div className="card" style={{ marginBottom: '20px', padding: '16px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', fontSize: '0.9rem', fontWeight: '600' }}>
        <Filter size={18} color="var(--color-primary)" />
        <span>Filter & Search Opportunities</span>
      </div>

      <div className="grid-3" style={{ gap: '12px' }}>
        {/* Search */}
        <div style={{ position: 'relative' }}>
          <Search size={16} color="var(--color-text-muted)" style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)' }} />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search programs, fields..."
            style={{
              width: '100%',
              padding: '8px 12px 8px 32px',
              border: '1px solid var(--color-border)',
              borderRadius: '6px',
              fontSize: '0.85rem',
              backgroundColor: '#FFFFFF',
              outline: 'none'
            }}
          />
        </div>

        {/* Eligibility Filter */}
        <div>
          <select
            value={statusFilter}
            onChange={(e) => onStatusChange(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid var(--color-border)',
              borderRadius: '6px',
              fontSize: '0.85rem',
              backgroundColor: '#FFFFFF',
              outline: 'none'
            }}
          >
            <option value="All">All Eligibility Statuses</option>
            <option value="Eligible">Eligible Only</option>
            <option value="Requirements Missing">Requirements Missing</option>
            <option value="Not Eligible">Not Eligible</option>
          </select>
        </div>

        {/* Country Filter */}
        <div>
          <select
            value={countryFilter}
            onChange={(e) => onCountryChange(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid var(--color-border)',
              borderRadius: '6px',
              fontSize: '0.85rem',
              backgroundColor: '#FFFFFF',
              outline: 'none'
            }}
          >
            {countries.map((c, idx) => (
              <option key={idx} value={c}>
                {c === "All" ? "All Destination Countries" : c}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}