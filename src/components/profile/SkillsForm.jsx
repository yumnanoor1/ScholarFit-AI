import React from 'react';

export default function SkillsForm({ data, onChange, onNext, onBack }) {
  const handleSkillsChange = (e) => {
    const skillsArray = e.target.value.split(',').map(s => s.trim());
    onChange({ ...data, skills: skillsArray });
  };

  const handleProjectsChange = (e) => {
    const projectsArray = e.target.value.split(',').map(p => p.trim());
    onChange({ ...data, projects: projectsArray });
  };

  return (
    <div>
      <h3 style={{ fontSize: '1.1rem', marginBottom: '16px', color: 'var(--color-dark)' }}>3. Skills & Key Projects</h3>

      <div className="form-group">
        <label>Technical Skills (Comma separated)</label>
        <input 
          type="text" 
          value={Array.isArray(data.skills) ? data.skills.join(', ') : data.skills || ''} 
          onChange={handleSkillsChange} 
          placeholder="e.g., Python, Machine Learning, Data Structures, React"
        />
      </div>

      <div className="form-group">
        <label>Key Capstone or Course Projects (Comma separated)</label>
        <input 
          type="text" 
          value={Array.isArray(data.projects) ? data.projects.join(', ') : data.projects || ''} 
          onChange={handleProjectsChange} 
          placeholder="e.g., AI Image Classifier, Automated Grading System"
        />
      </div>

      <div className="form-group">
        <label>Field / Domain of Interest</label>
        <input 
          type="text" 
          value={data.fieldOfInterest || ''} 
          onChange={(e) => onChange({ ...data, fieldOfInterest: e.target.value })} 
          placeholder="e.g., Computer Science & AI, Data Science"
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '20px' }}>
        <button type="button" className="btn btn-outline" onClick={onBack}>Back</button>
        <button type="button" className="btn btn-primary" onClick={onNext}>Next: Preferences</button>
      </div>
    </div>
  );
}