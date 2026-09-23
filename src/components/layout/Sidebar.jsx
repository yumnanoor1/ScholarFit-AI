import React from 'react';
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
    <aside style={{
      width: '250px',
      backgroundColor: 'var(--color-dark)',
      color: '#FFFFFF',
      display: 'flex',
      flexDirection: 'column',
      flexShrink: 0,
      minHeight: '100vh'
    }}>
      {/* Brand Header */}
      <div style={{ padding: '20px 24px', borderBottom: '1px solid #2D333F' }}>
        <h2 style={{ fontSize: '1.2rem', color: '#FFFFFF', fontWeight: 'bold' }}>FitScholar AI</h2>
        <p style={{ fontSize: '0.75rem', color: 'var(--color-secondary)', marginTop: '2px' }}>
          Decision-Support System
        </p>
      </div>

      {/* Navigation Links */}
      <nav style={{ flex: 1, padding: '12px 0', overflowY: 'auto' }}>
        {links.map((link) => {
          const Icon = link.icon;
          return (
            <NavLink
              key={link.to}
              to={link.to}
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '11px 24px',
                color: isActive ? '#FFFFFF' : '#A0AEC0',
                backgroundColor: isActive ? 'var(--color-primary)' : 'transparent',
                textDecoration: 'none',
                fontSize: '0.88rem',
                fontWeight: isActive ? '600' : '400',
                borderLeft: isActive ? '4px solid var(--color-secondary)' : '4px solid transparent',
                transition: 'background-color 0.2s ease, color 0.2s ease'
              })}
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