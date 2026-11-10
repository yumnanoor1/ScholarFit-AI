import { startTransition } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  Award, Bookmark, Calculator, Copy, FileText, GitCompare, Globe2, History, Home,
  LayoutDashboard, ListChecks, LogOut, Radar, Route, Settings, ShieldCheck, UserRound,
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
      { to: '/application-pathway', label: 'Pathway', icon: Route },
    ],
  },
];

function SidebarLink({ to, label, icon: Icon, match, section: targetSection }) {
  const { pathname, search } = useLocation();
  const grouped = match?.some((path) => pathname === path || pathname.startsWith(`${path}/`));
  const section = targetSection || to.match(/[?&]section=([^&]+)/)?.[1];
  const currentSection = new URLSearchParams(search).get('section') || 'dashboard';
  const sectionActive = section
    ? pathname === '/admin/scholarships' && currentSection === section
    : pathname === '/admin/scholarships' && currentSection === 'dashboard';

  return (
    <NavLink
      to={to}
      className={({ isActive }) => `sidebar-link${(section ? sectionActive : match ? grouped : isActive) ? ' active' : ''}`}
    >
      <Icon size={18} aria-hidden="true" />
      <span>{label}</span>
    </NavLink>
  );
}

function SidebarPlaceholder({ label, icon: Icon }) {
  return (
    <div className="sidebar-link sidebar-link-disabled" aria-disabled="true" title={`${label} is coming soon`}>
      <Icon size={18} aria-hidden="true" />
      <span>{label}</span>
      <small>SOON</small>
    </div>
  );
}

const adminNavigationGroups = [
  {
    label: 'Manage',
    links: [
      { to: '/admin/scholarships', label: 'Dashboard', icon: LayoutDashboard, section: 'dashboard' },
      { to: '/admin/scholarships?section=records', label: 'Scholarships', icon: Award, section: 'records' },
    ],
  },
  {
    label: 'Discovery',
    links: [
      { to: '/admin/scholarships?section=discovery', label: 'Automated Discovery', icon: Radar, section: 'discovery' },
      { to: '/admin/scholarships?section=sources', label: 'Discovery Sources', icon: Globe2, section: 'sources' },
      { to: '/admin/scholarships?section=reviews', label: 'Review Queue', icon: ListChecks, section: 'reviews' },
      { to: '/admin/scholarships?section=duplicates', label: 'Duplicates', icon: Copy, section: 'duplicates' },
      { to: '/admin/scholarships?section=verification', label: 'Verification', icon: ShieldCheck, section: 'verification' },
      { to: '/admin/scholarships?section=history', label: 'Discovery History', icon: History, section: 'history' },
    ],
  },
];

export default function Sidebar() {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const { completion } = useProfile();
  const isAdmin = user?.role === 'admin';
  const adminName = user?.name || user?.full_name || 'Admin';
  const adminInitials = user?.name || user?.full_name
    ? adminName.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase()
    : 'AD';
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
    <aside className={`sidebar${isAdmin ? ' is-admin-sidebar' : ''}`}>
      <NavLink
        to={isAdmin ? '/admin/scholarships' : unlocked ? HOME_PATH : ONBOARDING_PATH}
        className="sidebar-brand"
        aria-label={isAdmin ? 'Admin dashboard' : unlocked ? 'FitScholars dashboard' : 'Complete your profile'}
      >
        <BrandLogo tone="light" height={isAdmin ? 36 : 62} alt="" />
      </NavLink>

      <nav className="sidebar-nav" aria-label={isAdmin ? 'Admin navigation' : 'Main navigation'}>
        {isAdmin ? adminNavigationGroups.map((group) => (
          <div className="sidebar-section" key={group.label}>
            <h2 className="sidebar-section-title">{group.label}</h2>
            {group.links.map((link) => link.disabled
              ? <SidebarPlaceholder key={link.label} {...link} />
              : <SidebarLink key={link.to} {...link} />)}
          </div>
        )) : (
          <>
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
          </>
        )}
      </nav>

      <div className="sidebar-bottom">
        {unlocked && <SidebarLink to="/settings" label="Settings" icon={Settings} />}
        <button type="button" className="sidebar-link sidebar-logout" onClick={handleLogout}>
          <LogOut size={18} aria-hidden="true" />
          <span>Log out</span>
        </button>
        {isAdmin && (
          <div className="sidebar-admin-profile">
            <span>{adminInitials}</span>
            <div><strong>{adminName}</strong><small>Administrator</small></div>
          </div>
        )}
      </div>
    </aside>
  );
}
