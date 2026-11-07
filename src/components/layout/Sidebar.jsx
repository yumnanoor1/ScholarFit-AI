import { startTransition } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  Award, Bookmark, Calculator, FileText, GitCompare,
  Home, LogOut,
  Settings, ShieldCheck, UserRound,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../context/ProfileContext';
import { HOME_PATH, ONBOARDING_PATH, canUseApp } from '../../services/profileAccess';
import BrandLogo from '../common/BrandLogo';

const navigationGroups = [
  {
    label: 'Discover',
    links: [
      { to: '/scholarships', label: 'Scholarships', icon: Award, match: ['/scholarships', '/recommendations'] },
      { to: '/saved', label: 'Saved', icon: Bookmark },
    ],
  },
  {
    label: 'Plan',
    links: [
      { to: '/compare', label: 'Compare', icon: GitCompare },
      { to: '/financial', label: 'Financial Planner', icon: Calculator },
      { to: '/documents', label: 'Documents', icon: FileText },
    ],
  },
];

function SidebarLink({ to, label, icon: Icon, match }) {
  const { pathname } = useLocation();
  const grouped = match?.some((path) => pathname === path || pathname.startsWith(`${path}/`));

  return (
    <NavLink
      to={to}
      className={({ isActive }) => `sidebar-link${(match ? grouped : isActive) ? ' active' : ''}`}
    >
      <Icon size={18} aria-hidden="true" />
      <span>{label}</span>
    </NavLink>
  );
}

export default function Sidebar() {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const { completion } = useProfile();
  // Features aren't listed until the API confirms they're available, so nothing here leads to a refusal
  const unlocked = canUseApp(completion);

  // Together, so ProtectedRoute doesn't record this page as somewhere to return to after login
  const handleLogout = () => {
    startTransition(() => {
      logout();
      navigate('/login', { replace: true });
    });
  };

  return (
    <aside className="sidebar">
      <NavLink to={unlocked ? HOME_PATH : ONBOARDING_PATH} className="sidebar-brand" aria-label={unlocked ? 'FitScholars dashboard' : 'Complete your profile'}>
        <BrandLogo tone="light" height={62} alt="" />
      </NavLink>

      <nav className="sidebar-nav" aria-label="Main navigation">
        <div className="sidebar-primary-links">
          {unlocked
            ? <SidebarLink to={HOME_PATH} label="Dashboard" icon={Home} />
            : <SidebarLink to={ONBOARDING_PATH} label="Complete profile" icon={Home} />}
          <SidebarLink to="/profile" label="My Profile" icon={UserRound} />
        </div>
        {unlocked && navigationGroups.map((group) => (
          <div className="sidebar-section" key={group.label}>
            <h2 className="sidebar-section-title">{group.label}</h2>
            {group.links.map((link) => <SidebarLink key={link.to} {...link} />)}
          </div>
        ))}
      </nav>

      <div className="sidebar-bottom">
        {user?.role === 'admin' && <SidebarLink to="/admin/scholarships" label="Administration" icon={ShieldCheck} />}
        {unlocked && <SidebarLink to="/settings" label="Settings" icon={Settings} />}
        <button type="button" className="sidebar-link sidebar-logout" onClick={handleLogout}>
          <LogOut size={18} aria-hidden="true" />
          <span>Log out</span>
        </button>
      </div>
    </aside>
  );
}
