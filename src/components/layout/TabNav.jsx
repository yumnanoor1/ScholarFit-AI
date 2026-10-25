import { NavLink } from 'react-router-dom';

export default function TabNav({ tabs, label }) {
  return (
    <nav className="page-tabs" aria-label={label}>
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          className={({ isActive }) => `page-tab${isActive ? ' active' : ''}`}
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
