import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { GlowCard } from '../components/ui/spotlight-card';
import { EMAIL_ALERTS_KEY, readEmailAlerts, writeUserStorage } from '../services/userStorage';

export default function Settings() {
  const { user } = useAuth();
  const [emailAlerts, setEmailAlerts] = useState(() => readEmailAlerts(user?.id));

  const updateEmailAlerts = (event) => {
    const nextValue = event.target.checked;
    if (writeUserStorage(EMAIL_ALERTS_KEY, user?.id, nextValue)) {
      setEmailAlerts(nextValue);
    } else {
      console.error('Unable to save the email alert preference.');
    }
  };

  return (
    <div className="page-container settings-page">
      <h1 className="page-title">Account & Platform Settings</h1>
      <p className="page-subtitle">Manage preferences and security settings.</p>

      <GlowCard customSize className="card settings-card">
        <h3>Notification Preferences</h3>
        <div style={{ margin: '16px 0', fontSize: '0.9rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input type="checkbox" checked={emailAlerts} onChange={updateEmailAlerts} /> Email alerts for upcoming application deadlines
          </label>
        </div>

        <h3 className="settings-section-gap">Security Options</h3>
        <div style={{ margin: '16px 0' }}>
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
            Password changes are unavailable in this demo account.
          </p>
        </div>
      </GlowCard>
    </div>
  );
}