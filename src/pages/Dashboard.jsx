import React, { useEffect, useState } from 'react';
import { apiService } from '../services/api';
import OpportunityCard from '../components/opportunities/OpportunityCard'
import ProfileProgress from '../components/profile/ProfileProgress';
import { ArrowRight, AlertCircle, Bookmark, DollarSign } from 'lucide-react';

export default function Dashboard() {
  const [profile, setProfile] = useState(null);
  const [universities, setUniversities] = useState([]);

  useEffect(() => {
    apiService.getProfile().then(setProfile);
    apiService.getMatchedUniversities().then(setUniversities);
  }, []);

  return (
    <div className="page-container">
      <h1 className="page-title">Decision Support Dashboard</h1>
      <p className="page-subtitle">Real-time overview of your program fit, eligibility status, and funding matching.</p>

      {/* Best Next Action Banner */}
      <div style={{
        backgroundColor: 'var(--color-dark)',
        color: '#FFFFFF',
        padding: '20px',
        borderRadius: '8px',
        marginBottom: '24px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
          <AlertCircle size={28} color="var(--color-secondary)" />
          <div>
            <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--color-secondary)', fontWeight: 'bold' }}>
              Best Next Action Recommendation
            </span>
            <p style={{ fontSize: '0.95rem', marginTop: '2px' }}>
              Complete your GRE quantitative score details in your profile to refine US university matching precision.
            </p>
          </div>
        </div>
        <button className="btn btn-secondary" style={{ flexShrink: 0 }}>Execute Action</button>
      </div>

      {/* Stats Summary Grid */}
      <div className="grid-3" style={{ marginBottom: '24px' }}>
        <div className="card">
          <ProfileProgress percentage={profile?.profileCompletionPercentage || 85} />
        </div>

        <div className="card" style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
          <Bookmark size={28} color="var(--color-primary)" />
          <div>
            <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>2 Saved</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>Target Programs Bookmarked</div>
          </div>
        </div>

        <div className="card" style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
          <DollarSign size={28} color="var(--color-success)" />
          <div>
            <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>$15,000 / yr</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>Matched Potential Funding</div>
          </div>
        </div>
      </div>

      <h2 style={{ fontSize: '1.2rem', marginBottom: '16px' }}>Top Recommended Matches</h2>
      <div>
        {universities.map(u => (
          <OpportunityCard key={u.id} data={u} />
        ))}
      </div>
    </div>
  );
}
