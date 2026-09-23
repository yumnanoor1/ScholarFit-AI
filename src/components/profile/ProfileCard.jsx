import React from 'react';
import ProfileProgress from './ProfileProgress';
import { User, GraduationCap, Award, MapPin } from 'lucide-react';

export default function ProfileCard({ profile }) {
  if (!profile) return null;

  return (
    <div className="card">
      <div style={{ display: 'flex', gap: '16px', alignItems: 'center', marginBottom: '16px' }}>
        <div style={{
          width: '56px',
          height: '56px',
          borderRadius: '50%',
          backgroundColor: 'var(--color-primary)',
          color: '#FFFFFF',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0
        }}>
          <User size={28} />
        </div>
        <div>
          <h2 style={{ fontSize: '1.2rem', color: 'var(--color-dark)' }}>{profile.name}</h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>{profile.degree} • {profile.university}</p>
        </div>
      </div>

      <div style={{ marginBottom: '16px' }}>
        <ProfileProgress percentage={profile.profileCompletionPercentage || 85} />
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: '12px',
        paddingTop: '12px',
        borderTop: '1px solid var(--color-border)',
        fontSize: '0.85rem'
      }}>
        <div>
          <span style={{ color: 'var(--color-text-muted)', display: 'block' }}>CGPA</span>
          <strong>{profile.cgpa} / 4.0</strong>
        </div>
        <div>
          <span style={{ color: 'var(--color-text-muted)', display: 'block' }}>Test Score</span>
          <strong>{profile.englishTest}: {profile.englishScore}</strong>
        </div>
        <div>
          <span style={{ color: 'var(--color-text-muted)', display: 'block' }}>Funding Need</span>
          <strong>{profile.fundingPreference}</strong>
        </div>
      </div>
    </div>
  );
}