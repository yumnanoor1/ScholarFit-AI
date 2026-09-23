import React from 'react';

export default function Settings() {
  return (
    <div className="page-container">
      <h1 className="page-title">Account & Platform Settings</h1>
      <p className="page-subtitle">Manage preferences and security settings.</p>

      <div className="card">
        <h3>Notification Preferences</h3>
        <div style={{ margin: '16px 0', fontSize: '0.9rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input type="checkbox" defaultChecked /> Email alerts for upcoming application deadlines
          </label>
        </div>

        <h3 style={{ marginTop: '24px' }}>Security Options</h3>
        <div style={{ margin: '16px 0' }}>
          <button className="btn btn-outline">Change Password</button>
        </div>
      </div>
    </div>
  );
}