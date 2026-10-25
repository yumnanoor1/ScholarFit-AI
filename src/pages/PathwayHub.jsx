import TabNav from '../components/layout/TabNav';

const pathwayTabs = [
  { to: '/pathway', label: 'Roadmap' },
  { to: '/timeline', label: 'Task' },
];

export default function PathwayHub({ children }) {
  return (
    <>
      <TabNav tabs={pathwayTabs} label="Application sections" />
      {children}
    </>
  );
}
