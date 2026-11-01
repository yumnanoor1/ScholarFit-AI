import { useState } from 'react';
import { Pencil } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import { GlowCard } from '../components/ui/spotlight-card';
import { ProfileSavedNotice } from '../components/profile/ProfileNotices';
import { EMAIL_ALERTS_KEY, readEmailAlerts, writeUserStorage } from '../services/userStorage';
import './Settings.css';

export default function Settings() {
  const { user } = useAuth();
  const { completion } = useProfile();
  const navigate = useNavigate();
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
      <header className="settings-page-header">
        <h1 className="page-title">Account & Platform Settings</h1>
        <p className="page-subtitle">Manage your profile, notifications, and account security.</p>
      </header>

      <ProfileSavedNotice />

      <div className="settings-sections">
        <GlowCard as="section" customSize className="card settings-card" aria-labelledby="settings-profile-title">
          <div className="settings-section-header">
            <div>
              <h2 id="settings-profile-title" className="settings-section-title">Profile</h2>
              <p className="settings-section-copy">Keep your academic and study information up to date.</p>
            </div>
            <span className="settings-completion">{completion.percent}% complete</span>
          </div>
          <div className="settings-profile-row">
            <p>Update your personal details, academic background, study preferences, and language scores.</p>
            <button type="button" className="profile-summary-primary" onClick={() => navigate('/profile?edit=1', { state: { returnTo: '/settings' } })}>
              <Pencil size={15} aria-hidden="true" /> Edit Profile
            </button>
          </div>
        </GlowCard>

        <GlowCard as="section" customSize className="card settings-card" aria-labelledby="settings-notifications-title">
          <div className="settings-section-header">
            <div>
              <h2 id="settings-notifications-title" className="settings-section-title">Notifications</h2>
              <p className="settings-section-copy">Choose which application reminders you receive.</p>
            </div>
          </div>
          <label className="settings-preference">
            <input type="checkbox" checked={emailAlerts} onChange={updateEmailAlerts} />
            <span>
              <span className="settings-preference-title">Application deadline alerts</span>
              <span className="settings-preference-description">Get email reminders for upcoming application deadlines.</span>
            </span>
          </label>
        </GlowCard>

        <GlowCard as="section" customSize className="card settings-card" aria-labelledby="settings-security-title">
          <div className="settings-section-header">
            <div>
              <h2 id="settings-security-title" className="settings-section-title">Security</h2>
              <p className="settings-section-copy">Manage access to your account.</p>
            </div>
          </div>
          <p className="settings-security-note">Password changes are unavailable in this demo account.</p>
        </GlowCard>
      </div>
    </div>
  );
}