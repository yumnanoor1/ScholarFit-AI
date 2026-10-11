import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { GlowCard } from '../components/ui/spotlight-card';

export default function Settings() {
  const { user } = useAuth();
  const preferenceKey = `fitscholar.settings.emailDeadlineAlerts.v1.${user?.id || 'anonymous'}`;
  const [emailAlerts, setEmailAlerts] = useState(() => {
    try {
      const storedPreference = localStorage.getItem(preferenceKey);
      if (storedPreference === null) return true;
      if (storedPreference === 'true') return true;
      if (storedPreference === 'false') return false;
      console.error('Ignoring an invalid stored email alert preference.');
      return true;
    } catch (error) {
      console.error('Unable to read the email alert preference.', error);
      return true;
    }
  });

  const updateEmailAlerts = (event) => {
    const nextValue = event.target.checked;
    try {
      localStorage.setItem(preferenceKey, String(nextValue));
      setEmailAlerts(nextValue);
    } catch (error) {
      console.error('Unable to save the email alert preference.', error);
    }
  };

  return (
    <div className="page-container">
      <h1 className="page-title">Account & Platform Settings</h1>
      <p className="page-subtitle">Manage preferences and security settings.</p>

      <GlowCard customSize className="card">
        <h3>Notification Preferences</h3>
        <div style={{ margin: '16px 0', fontSize: '0.9rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input type="checkbox" checked={emailAlerts} onChange={updateEmailAlerts} /> Email alerts for upcoming application deadlines
          </label>
        </div>

        <h3 style={{ marginTop: '24px' }}>Security Options</h3>
        <div style={{ margin: '16px 0' }}>
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
            Password changes are unavailable in this demo account.
          </p>
        </div>
      </GlowCard>
    </div>
  );
}