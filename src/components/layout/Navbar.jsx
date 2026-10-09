import { ChevronDown, User, Bell, Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

export default function Navbar() {
  const navigate = useNavigate();
  const { user: authenticatedUser } = useAuth();
  const displayName = authenticatedUser?.name?.trim() || 'Student';
  const initials = displayName.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase();

  return (
    <header className="navbar app-navbar">
      <div className="navbar-search">
        <Search size={16} color="var(--color-text-muted)" style={{ position: 'absolute', left: '10px' }} />
        <input
          type="text" 
          placeholder="Search universities, scholarships..." 
        />
      </div>
      <div className="navbar-actions">
        <div className="navbar-term" style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
          Academic Term: <strong style={{ color: 'var(--color-dark)' }}>2026 – 2027</strong>
        </div>

        <button type="button" aria-label="Open application timeline" onClick={() => navigate('/timeline')} style={{ background: 'none', border: 'none', cursor: 'pointer', position: 'relative' }}>
          <Bell size={20} color="var(--color-dark)" />
          <span style={{
            position: 'absolute',
            top: '-2px',
            right: '-2px',
            width: '8px',
            height: '8px',
            backgroundColor: 'var(--color-primary)',
            borderRadius: '50%'
          }} />
        </button>

        <div className="navbar-user-profile">
          <div className="navbar-avatar">
            {initials || <User size={18} />}
          </div>
          <div className="navbar-user-copy">
            <div style={{ fontSize: '0.88rem', fontWeight: '600', color: 'var(--color-dark)' }}>{displayName}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Master's Applicant</div>
          </div>
          <ChevronDown size={13} aria-hidden="true" />
        </div>
      </div>
    </header>
  );
}