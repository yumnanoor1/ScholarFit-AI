import { NavLink } from 'react-router-dom';
import { 
  LayoutDashboard, User, FileText, GraduationCap, Award, 
  Bookmark, GitCompare, DollarSign, GitBranch, Compass, 
  Calendar, TrendingUp, Settings 
} from 'lucide-react';

export default function Sidebar() {
  const links = [
    { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { to: "/profile", label: "My Profile", icon: User },
    { to: "/documents", label: "Documents", icon: FileText },
    { to: "/universities", label: "Universities", icon: GraduationCap },
    { to: "/scholarships", label: "Scholarships", icon: Award },
    { to: "/saved", label: "Saved Items", icon: Bookmark },
    { to: "/compare", label: "Compare Programs", icon: GitCompare },
    { to: "/financial", label: "Financial Feasibility", icon: DollarSign },
    { to: "/pathway", label: "Application Pathway", icon: GitBranch },
    { to: "/recommendations", label: "Recommendations", icon: Compass },
    { to: "/timeline", label: "Timeline", icon: Calendar },
    { to: "/improvement", label: "Profile Improvement", icon: TrendingUp },
    { to: "/settings", label: "Settings", icon: Settings },
  ];

  return (
    <aside className="sidebar">
      {/* Brand Header */}
      <div className="sidebar-brand">
        <h2 style={{ fontSize: '1.2rem', color: '#FFFFFF', fontWeight: 'bold' }}>FitScholar AI</h2>
        <p style={{ fontSize: '0.75rem', color: 'var(--color-secondary)', marginTop: '2px' }}>
          Decision-Support System
        </p>
      </div>

      {/* Navigation Links */}
      <nav className="sidebar-nav" aria-label="Main navigation">
        {links.map((link) => {
          const Icon = link.icon;
          return (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}
            >
              <Icon size={18} />
              <span>{link.label}</span>
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}