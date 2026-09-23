import React from 'react';

export default function PreferencesForm({ data, onChange, onSubmit, onBack }) {
  const handleCountriesChange = (e) => {
    const countriesArray = e.target.value.split(',').map(c => c.trim());
    onChange({ ...data, preferredCountries: countriesArray });
  };

  return (
    <div>
      <h3 style={{ fontSize: '1.1rem', marginBottom: '16px', color: 'var(--color-dark)' }}>4. Study Abroad Preferences</h3>

      <div className="form-group">
        <label>Preferred Countries / Destinations (Comma separated)</label>
        <input 
          type="text" 
          value={Array.isArray(data.preferredCountries) ? data.preferredCountries.join(', ') : data.preferredCountries || ''} 
          onChange={handleCountriesChange} 
          placeholder="e.g., Germany, United States, Canada"
        />
      </div>

      <div className="grid-2">
        <div className="form-group">
          <label>Target Degree Level</label>
          <select 
            value={data.preferredDegree || "Master's"} 
            onChange={(e) => onChange({ ...data, preferredDegree: e.target.value })}
          >
            <option>Master's</option>
            <option>PhD</option>
          </select>
        </div>

        <div className="form-group">
          <label>Funding Requirement</label>
          <select 
            value={data.fundingPreference || "Full Funding Required"} 
            onChange={(e) => onChange({ ...data, fundingPreference: e.target.value })}
          >
            <option>Full Funding Required</option>
            <option>Partial Funding Accepted</option>
            <option>Self-Funded</option>
          </select>
        </div>
      </div>

      <div className="form-group">
        <label>Approximate Self-Funded Budget (per year)</label>
        <input 
          type="text" 
          value={data.approximateBudget || ''} 
          onChange={(e) => onChange({ ...data, approximateBudget: e.target.value })} 
          placeholder="e.g., $5,000 / year"
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '20px' }}>
        <button type="button" className="btn btn-outline" onClick={onBack}>Back</button>
        <button type="button" className="btn btn-primary" onClick={onSubmit}>Save & Analyze Eligibility</button>
      </div>
    </div>
  );
}