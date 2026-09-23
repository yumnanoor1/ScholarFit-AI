import React from 'react';

export default function LanguageForm({ data, onChange, onNext, onBack }) {
  return (
    <div>
      <h3 style={{ fontSize: '1.1rem', marginBottom: '16px', color: 'var(--color-dark)' }}>2. Language & Research Background</h3>

      <div className="grid-2">
        <div className="form-group">
          <label>English Proficiency Test</label>
          <select 
            value={data.englishTest || 'IELTS'} 
            onChange={(e) => onChange({ ...data, englishTest: e.target.value })}
          >
            <option value="IELTS">IELTS</option>
            <option value="TOEFL">TOEFL iBT</option>
            <option value="Duolingo">Duolingo English Test</option>
            <option value="None">Not Taken Yet</option>
          </select>
        </div>

        <div className="form-group">
          <label>Overall Test Score</label>
          <input 
            type="text" 
            value={data.englishScore || ''} 
            onChange={(e) => onChange({ ...data, englishScore: e.target.value })} 
            placeholder="e.g., 7.5 or 100"
          />
        </div>
      </div>

      <div className="form-group">
        <label>Research Experience / Publications</label>
        <textarea 
          rows="3" 
          value={data.researchExperience || ''} 
          onChange={(e) => onChange({ ...data, researchExperience: e.target.value })} 
          placeholder="Mention conference papers, journal articles, or lab research experience..."
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '20px' }}>
        <button type="button" className="btn btn-outline" onClick={onBack}>Back</button>
        <button type="button" className="btn btn-primary" onClick={onNext}>Next: Skills & Projects</button>
      </div>
    </div>
  );
}