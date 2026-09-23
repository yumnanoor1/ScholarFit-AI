import React from 'react';
import { User, Bell, Search, GraduationCap } from 'lucide-react';

export default function Navbar({ user = { name: "Alexander Wright" } }) {
  return (
    <header style={{
      height: '64px',
      backgroundColor: 'var(--color-white)',
      borderBottom: '1px solid var(--color-border)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 24px',
      position: 'sticky',
      top: 0,
      zIndex: 100
    }}>
      {/* Search Input */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '300px', position: 'relative' }}>
        <Search size={16} color="var(--color-text-muted)" style={{ position: 'absolute', left: '10px' }} />
        <input 
          type="text" 
          placeholder="Search programs, scholarships..." 
          style={{
            width: '100%',
            padding: '8px 12px 8px 32px',
            borderRadius: '6px',
            border: '1px solid var(--color-border)',
            fontSize: '0.85rem',
            backgroundColor: 'var(--color-bg)',
            outline: 'none'
          }}
        />
      </div>

      {/* Right Side Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
        <div style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
          Academic Term: <strong style={{ color: 'var(--color-dark)' }}>2026 – 2027</strong>
        </div>

        <button style={{ background: 'none', border: 'none', cursor: 'pointer', position: 'relative' }}>
          <Bell size={20} color="var(--color-dark)" />
          <span style={{
            position: 'absolute',
            top: '-2px',
            right: '-2px',
            width: '8px',
            height: '8px',
            backgroundColor: 'var(--color-primary)',
            borderRadius: '50%'
          }} />
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', paddingLeft: '12px', borderLeft: '1px solid var(--color-border)' }}>
          <div style={{
            width: '34px',
            height: '34px',
            borderRadius: '50%',
            backgroundColor: 'var(--color-primary)',
            color: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <User size={18} />
          </div>
          <div>
            <div style={{ fontSize: '0.88rem', fontWeight: '600', color: 'var(--color-dark)' }}>{user.name}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Master's Applicant</div>
          </div>
        </div>
      </div>
    </header>
  );
}