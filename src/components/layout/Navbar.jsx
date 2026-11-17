import { ChevronDown, User, Search } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../context/ProfileContext';
import { canUseApp } from '../../services/profileAccess';
import AssistantChat from '../assistant/AssistantChat';

export default function Navbar() {
  const { user: authenticatedUser } = useAuth();
  const { completion } = useProfile();
  const displayName = authenticatedUser?.name?.trim() || 'Student';
  const initials = displayName.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase();

  return (
    <header className="navbar app-navbar">
      {canUseApp(completion) && (
        <div className="navbar-search">
          <Search size={16} color="var(--color-text-muted)" style={{ position: 'absolute', left: '10px' }} />
          <input
            type="text"
            placeholder="Search scholarships..."
          />
        </div>
      )}
      <div className="navbar-actions">
        <AssistantChat />

        <div className="navbar-user-profile">
          <div className="navbar-avatar">
            {initials || <User size={18} />}
          </div>
          <div className="navbar-user-copy">
            <div style={{ fontSize: '0.88rem', fontWeight: '600', color: 'var(--color-dark)' }}>{displayName}</div>
          </div>
          <ChevronDown size={13} aria-hidden="true" />
        </div>
      </div>
    </header>
  );
}