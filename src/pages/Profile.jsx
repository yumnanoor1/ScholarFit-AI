import React, { useState } from 'react';
import ProfileProgress from '../components/profile/ProfileProgress';

export default function Profile() {
  const [step, setStep] = useState(1);

  return (
    <div className="page-container">
      <h1 className="page-title">Academic & Preference Profile</h1>
      <p className="page-subtitle">Configure verified credentials used for deterministic eligibility evaluation.</p>

      <div className="card" style={{ marginBottom: '20px' }}>
        <ProfileProgress percentage={step === 1 ? 33 : step === 2 ? 66 : 100} />
      </div>

      <div className="card">
        {step === 1 && (
          <div>
            <h3 style={{ marginBottom: '16px' }}>Academic Qualifications</h3>
            <div className="form-group">
              <label>Full Name</label>
              <input type="text" defaultValue="Alexander Wright" />
            </div>
            <div className="grid-2">
              <div className="form-group">
                <label>Degree Title</label>
                <input type="text" defaultValue="BS Computer Science" />
              </div>
              <div className="form-group">
                <label>CGPA (Scale 4.0)</label>
                <input type="text" defaultValue="3.65" />
              </div>
            </div>
            <div className="form-group">
              <label>Graduation University</label>
              <input type="text" defaultValue="National University of Sciences" />
            </div>
            <button className="btn btn-primary" onClick={() => setStep(2)}>Next: Language & Research</button>
          </div>
        )}

        {step === 2 && (
          <div>
            <h3 style={{ marginBottom: '16px' }}>Language & Research Background</h3>
            <div className="grid-2">
              <div className="form-group">
                <label>English Test Type</label>
                <select defaultValue="IELTS">
                  <option>IELTS</option>
                  <option>TOEFL iBT</option>
                  <option>Duolingo</option>
                </select>
              </div>
              <div className="form-group">
                <label>Overall Score</label>
                <input type="text" defaultValue="7.5" />
              </div>
            </div>
            <div className="form-group">
              <label>Research Projects / Publications</label>
              <textarea rows="3" defaultValue="Co-authored 1 conference paper on NLP for healthcare domain."></textarea>
            </div>
            <div style={{ display: 'flex', gap: '10px' }}>
              <button className="btn btn-outline" onClick={() => setStep(1)}>Back</button>
              <button className="btn btn-primary" onClick={() => setStep(3)}>Next: Preferences</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div>
            <h3 style={{ marginBottom: '16px' }}>Study Abroad Preferences</h3>
            <div className="form-group">
              <label>Target Countries</label>
              <input type="text" defaultValue="Germany, United States, Canada" />
            </div>
            <div className="form-group">
              <label>Funding Target</label>
              <select defaultValue="Full Funding Required">
                <option>Full Funding Required</option>
                <option>Partial Funding Accepted</option>
                <option>Self-Funded</option>
              </select>
            </div>
            <div style={{ display: 'flex', gap: '10px' }}>
              <button className="btn btn-outline" onClick={() => setStep(2)}>Back</button>
              <button className="btn btn-primary" onClick={() => alert("Profile updated successfully!")}>Save Profile</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}