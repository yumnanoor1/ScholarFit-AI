import TabNav from '../components/layout/TabNav';

const exploreTabs = [
  { to: '/universities', label: 'Programs' },
  { to: '/scholarships', label: 'Scholarships' },
  { to: '/recommendations', label: 'My Matches' },
];

export default function Explore({ children }) {
  return (
    <div className="explore-page">
      <header className="explore-section-header">
        <h1>Explore opportunities</h1>
        <p>Find programs and scholarships that match your profile.</p>
      </header>
      <TabNav tabs={exploreTabs} label="Explore sections" />
      {children}
    </div>
  );
}
