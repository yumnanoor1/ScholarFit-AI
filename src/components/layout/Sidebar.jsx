import { startTransition } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  Bookmark, Calculator, FileText, GitCompare,
  GraduationCap, Home, LogOut, Map,
  Settings, ShieldCheck, UserRound,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import BrandLogo from '../common/BrandLogo';

const navigationGroups = [
  {
    label: 'Discover',
    links: [
      { to: '/universities', label: 'Explore', icon: GraduationCap, match: ['/universities', '/scholarships', '/recommendations'] },
      { to: '/saved', label: 'Saved', icon: Bookmark },
    ],
  },
  {
    label: 'Plan',
    links: [
      { to: '/compare', label: 'Compare', icon: GitCompare },
      { to: '/financial', label: 'Financial Planner', icon: Calculator },
      { to: '/pathway', label: 'Application Pathway', icon: Map, match: ['/pathway', '/timeline'] },
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

  // Together, so ProtectedRoute doesn't record this page as somewhere to return to after login
  const handleLogout = () => {
    startTransition(() => {
      logout();
      navigate('/login', { replace: true });
    });
  };

  return (
    <aside className="sidebar">
      <NavLink to="/dashboard" className="sidebar-brand" aria-label="FitScholars dashboard">
        <BrandLogo tone="light" height={62} alt="" />
      </NavLink>

      <nav className="sidebar-nav" aria-label="Main navigation">
        <div className="sidebar-primary-links">
          <SidebarLink to="/dashboard" label="Dashboard" icon={Home} />
          <SidebarLink to="/profile" label="My Profile" icon={UserRound} />
        </div>
        {navigationGroups.map((group) => (
          <div className="sidebar-section" key={group.label}>
            <h2 className="sidebar-section-title">{group.label}</h2>
            {group.links.map((link) => <SidebarLink key={link.to} {...link} />)}
          </div>
        ))}
      </nav>

      <div className="sidebar-bottom">
        {user?.role === 'admin' && <SidebarLink to="/admin/scholarships" label="Administration" icon={ShieldCheck} />}
        <SidebarLink to="/settings" label="Settings" icon={Settings} />
        <button type="button" className="sidebar-link sidebar-logout" onClick={handleLogout}>
          <LogOut size={18} aria-hidden="true" />
          <span>Log out</span>
        </button>
      </div>
    </aside>
  );
}
