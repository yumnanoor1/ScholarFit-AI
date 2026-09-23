import React from 'react';

export default function AcademicForm({ data, onChange, onNext }) {
  return (
    <div>
      <h3 style={{ fontSize: '1.1rem', marginBottom: '16px', color: 'var(--color-dark)' }}>1. Academic Qualifications</h3>
      
      <div className="form-group">
        <label>Full Name</label>
        <input 
          type="text" 
          value={data.name || ''} 
          onChange={(e) => onChange({ ...data, name: e.target.value })} 
          placeholder="e.g., Alexander Wright"
        />
      </div>

      <div className="grid-2">
        <div className="form-group">
          <label>Current/Completed Degree</label>
          <input 
            type="text" 
            value={data.degree || ''} 
            onChange={(e) => onChange({ ...data, degree: e.target.value })} 
            placeholder="e.g., BS Computer Science"
          />
        </div>

        <div className="form-group">
          <label>Degree Level</label>
          <select 
            value={data.degreeLevel || "Bachelor's"} 
            onChange={(e) => onChange({ ...data, degreeLevel: e.target.value })}
          >
            <option>Bachelor's</option>
            <option>Master's</option>
          </select>
        </div>
      </div>

      <div className="grid-2">
        <div className="form-group">
          <label>Graduation University</label>
          <input 
            type="text" 
            value={data.university || ''} 
            onChange={(e) => onChange({ ...data, university: e.target.value })} 
            placeholder="e.g., National University of Sciences"
          />
        </div>

        <div className="form-group">
          <label>CGPA (Scale 4.0)</label>
          <input 
            type="text" 
            value={data.cgpa || ''} 
            onChange={(e) => onChange({ ...data, cgpa: e.target.value })} 
            placeholder="e.g., 3.65"
          />
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '20px' }}>
        <button type="button" className="btn btn-primary" onClick={onNext}>
          Next: Language & Research
        </button>
      </div>
    </div>
  );
}