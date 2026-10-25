import { NavLink, useLocation } from 'react-router-dom';
import {
  Bookmark, Calculator, FileText, GitCompare,
  GraduationCap, Home, Map, Plane,
  Settings, UserRound,
} from 'lucide-react';

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
      { to: '/compare', label: 'Compare Programs', icon: GitCompare },
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
  return (
    <aside className="sidebar">
      <NavLink to="/dashboard" className="sidebar-brand" aria-label="FitScholars dashboard">
        <span className="sidebar-brand-mark"><Plane size={23} aria-hidden="true" /></span>
        <span className="sidebar-brand-copy">
          <strong>FitScholars</strong>
          <small>Study Abroad &amp; Scholarship<br />Decision Support System</small>
        </span>
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
        <SidebarLink to="/settings" label="Settings" icon={Settings} />
      </div>
    </aside>
  );
}
