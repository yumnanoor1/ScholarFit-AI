import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, Edit3 } from 'lucide-react';
import { useProfile } from '../context/ProfileContext';

export default function Dashboard() {
  const navigate = useNavigate();
  const { profile, matchStatistics } = useProfile();
  const firstName = profile.firstName || (profile.name || '').split(' ')[0] || 'there';

  const topOpportunities = [
    {
      name: 'Chevening Scholarship',
      country: 'United Kingdom',
      feasibility: 92,
      eligibility: 'STRONG',
      netCost: '$0',
      deadline: 'Oct 15',
      deadlineColor: '#D32F2F'
    },
    {
      name: 'Fulbright Student Program',
      country: 'United States',
      feasibility: 84,
      eligibility: 'STRONG',
      netCost: '$0',
      deadline: 'Nov 03',
      deadlineColor: 'inherit'
    },
    {
      name: 'DAAD Research Grant',
      country: 'Germany',
      feasibility: 71,
      eligibility: 'PARTIAL',
      netCost: '$4,200',
      deadline: 'Nov 20',
      deadlineColor: 'inherit'
    },
    {
      name: "Commonwealth Master's Scholarship",
      country: 'Canada',
      feasibility: 68,
      eligibility: 'PARTIAL',
      netCost: '$6,800',
      deadline: 'Dec 07',
      deadlineColor: 'inherit'
    }
  ];

  const upcomingDeadlines = [
    { name: 'Chevening', date: 'Oct 15, 2026', daysLeft: '12 days left', urgent: true },
    { name: 'Fulbright', date: 'Nov 03, 2026', daysLeft: '31 days left', urgent: false },
    { name: 'DAAD Master', date: 'Nov 20, 2026', daysLeft: '48 days left', urgent: false },
    { name: 'Commonwealth', date: 'Dec 07, 2026', daysLeft: '65 days left', urgent: false }
  ];

  return (
    <div className="page-container" style={{ maxWidth: '1160px', margin: '0 auto', padding: '32px 24px', backgroundColor: 'var(--color-bg)' }}>
      
      {/* 1. Header Row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '32px' }}>
        <div>
          <h1 style={{ fontSize: '2.2rem', fontFamily: 'serif', fontWeight: '600', color: 'var(--color-dark)', marginBottom: '8px' }}>
            Good morning, {firstName}
          </h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <span style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)' }}>Profile completeness</span>
            <div style={{ width: '120px', height: '4px', backgroundColor: '#E2E8F0', borderRadius: '2px', overflow: 'hidden' }}>
              <div style={{ width: `${profile.profileCompletionPercentage || 0}%`, height: '100%', backgroundColor: 'var(--color-dark)' }} />
            </div>
            <span style={{ fontSize: '0.82rem', fontWeight: 'bold', color: 'var(--color-dark)' }}>{profile.profileCompletionPercentage || 0}%</span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button style={{
            width: '40px',
            height: '40px',
            borderRadius: '50%',
            backgroundColor: '#FFFFFF',
            border: '1px solid var(--color-border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer'
          }}>
            <Bell size={18} color="var(--color-dark)" />
          </button>
          <button 
            className="btn btn-primary"
            onClick={() => navigate('/scholarships')}
            style={{ padding: '10px 20px', fontSize: '0.88rem', backgroundColor: '#1C2833', color: '#FFFFFF', borderRadius: '6px' }}
          >
            Find Scholarships
          </button>
        </div>
      </div>

      <hr style={{ border: 'none', borderTop: '1px solid #E2E8F0', marginBottom: '32px' }} />

      {/* 2. Key Metrics Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px', marginBottom: '40px' }}>
        <div style={{ borderRight: '1px solid #E2E8F0', paddingRight: '16px' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>Eligible</span>
          <div style={{ fontSize: '2.2rem', fontWeight: '600', color: 'var(--color-dark)', marginTop: '4px' }}>{matchStatistics.eligibleCount}</div>
        </div>
        <div style={{ borderRight: '1px solid #E2E8F0', paddingRight: '16px' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>Funded options</span>
          <div style={{ fontSize: '2.2rem', fontWeight: '600', color: 'var(--color-dark)', marginTop: '4px' }}>{matchStatistics.fundedCount}</div>
        </div>
        <div style={{ borderRight: '1px solid #E2E8F0', paddingRight: '16px' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>Median listed tuition</span>
          <div style={{ fontSize: '1.6rem', fontWeight: '600', color: 'var(--color-dark)', marginTop: '8px' }}>{matchStatistics.medianTuition}</div>
        </div>
        <div>
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>Next deadline</span>
          <div style={{ fontSize: '2.2rem', fontWeight: '600', color: 'var(--color-dark)', marginTop: '4px' }}>
            12 <span style={{ fontSize: '1rem', fontWeight: 'normal', color: 'var(--color-text-muted)' }}>days</span>
          </div>
        </div>
      </div>

      {/* 3. Main Dashboard Layout Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '32px', alignItems: 'start' }}>
        
        {/* Left Table Section */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--color-dark)' }}>Top opportunities</h3>
            <button 
              onClick={() => navigate('/scholarships')} 
              style={{ background: 'none', border: 'none', fontSize: '0.82rem', color: 'var(--color-text-muted)', cursor: 'pointer' }}
            >
              View all matching
            </button>
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.88rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0', color: 'var(--color-text-muted)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                <th style={{ padding: '12px 0', fontWeight: '600' }}>NAME</th>
                <th style={{ padding: '12px 0', fontWeight: '600' }}>COUNTRY</th>
                <th style={{ padding: '12px 0', fontWeight: '600' }}>FEASIBILITY</th>
                <th style={{ padding: '12px 0', fontWeight: '600' }}>ELIGIBILITY</th>
                <th style={{ padding: '12px 0', fontWeight: '600', textAlign: 'right' }}>NET COST</th>
                <th style={{ padding: '12px 0', fontWeight: '600', textAlign: 'right' }}>DEADLINE</th>
              </tr>
            </thead>
            <tbody>
              {topOpportunities.map((item, idx) => (
                <tr key={idx} style={{ borderBottom: '1px solid #F1F5F9' }}>
                  <td style={{ padding: '16px 0', fontWeight: '600', color: 'var(--color-dark)' }}>{item.name}</td>
                  <td style={{ padding: '16px 0', color: 'var(--color-text-muted)' }}>{item.country}</td>
                  <td style={{ padding: '16px 0' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ width: '20px', fontWeight: '600', fontSize: '0.82rem' }}>{item.feasibility}</span>
                      <div style={{ width: '60px', height: '4px', backgroundColor: '#E2E8F0', borderRadius: '2px', overflow: 'hidden' }}>
                        <div style={{
                          width: `${item.feasibility}%`,
                          height: '100%',
                          backgroundColor: item.feasibility >= 80 ? '#2E7D32' : '#D97706'
                        }} />
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: '16px 0' }}>
                    <span style={{
                      display: 'inline-block',
                      padding: '2px 10px',
                      borderRadius: '12px',
                      fontSize: '0.7rem',
                      fontWeight: '700',
                      border: item.eligibility === 'STRONG' ? '1px solid #A7F3D0' : '1px solid #FDE68A',
                      color: item.eligibility === 'STRONG' ? '#047857' : '#B45309',
                      backgroundColor: item.eligibility === 'STRONG' ? '#ECFDF5' : '#FFFBEB'
                    }}>
                      • {item.eligibility}
                    </span>
                  </td>
                  <td style={{ padding: '16px 0', textAlign: 'right', fontWeight: '600', color: 'var(--color-dark)' }}>{item.netCost}</td>
                  <td style={{ padding: '16px 0', textAlign: 'right', fontWeight: '600', color: item.deadlineColor }}>{item.deadline}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Right Sidebar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
          
          {/* Best Next Action Card */}
          <div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '16px' }}>Best next action</h3>
            <div style={{
              backgroundColor: '#FFFFFF',
              border: '1px solid #E2E8F0',
              borderRadius: '8px',
              padding: '20px'
            }}>
              <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
                <Edit3 size={18} color="var(--color-primary)" style={{ flexShrink: 0, marginTop: '2px' }} />
                <p style={{ fontSize: '0.85rem', color: 'var(--color-dark)', lineHeight: '1.5' }}>
                  Finish your <strong>personal statement</strong> for the Chevening Scholarship to improve your feasibility score by 15%.
                </p>
              </div>
              <button 
                className="btn" 
                onClick={() => navigate('/documents')}
                style={{
                  width: '100%',
                  backgroundColor: '#1C2833',
                  color: '#FFFFFF',
                  padding: '10px',
                  fontSize: '0.85rem',
                  fontWeight: '600',
                  borderRadius: '6px',
                  border: 'none',
                  cursor: 'pointer'
                }}
              >
                Continue Application
              </button>
            </div>
          </div>

          {/* Upcoming Deadlines Widget */}
          <div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '16px' }}>Upcoming deadlines</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {upcomingDeadlines.map((dl, idx) => (
                <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.85rem', paddingBottom: '10px', borderBottom: '1px solid #F1F5F9' }}>
                  <div>
                    <div style={{ fontWeight: '600', color: 'var(--color-dark)' }}>{dl.name}</div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)' }}>{dl.date}</div>
                  </div>
                  <span style={{ fontSize: '0.78rem', fontWeight: '600', color: dl.urgent ? '#D32F2F' : '#D97706' }}>
                    {dl.daysLeft}
                  </span>
                </div>
              ))}
            </div>
          </div>

        </div>

      </div>

    </div>
  );
}