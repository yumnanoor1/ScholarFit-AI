import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Bookmark, 
  Building2, 
  GraduationCap, 
  Briefcase, 
  Globe, 
  ChevronDown,
  ArrowRight
} from 'lucide-react';

export default function Scholarships() {
  const navigate = useNavigate();

  // Selected scholarships state for comparison bar
  const [selectedIds, setSelectedIds] = useState(['1', '2']);
  const [savedIds, setSavedIds] = useState([]);

  // Mock list of scholarships matching screenshot
  const scholarshipsList = [
    {
      id: '1',
      title: 'Fulbright Student Program',
      provider: 'U.S. Department of State',
      country: 'United States',
      coverage: 'Full tuition + stipend',
      notes: '+$1,500/mo allowance',
      deadlineBadge: 'Due in 12 days',
      deadlineUrgent: true,
      match: 94,
      eligibility: 'STRONG',
      icon: <Building2 size={20} color="var(--color-primary)" />
    },
    {
      id: '2',
      title: 'Chevening Scholarship',
      provider: 'UK Foreign & Commonwealth Office',
      country: 'United Kingdom',
      coverage: 'Full tuition + housing',
      notes: 'Flight coverage included',
      deadlineBadge: 'Due in 31 days',
      deadlineUrgent: true,
      match: 92,
      eligibility: 'STRONG',
      icon: <GraduationCap size={20} color="var(--color-primary)" />
    },
    {
      id: '3',
      title: 'DAAD Research Grant',
      provider: 'German Academic Exchange Service',
      country: 'Germany',
      coverage: '$1,200/mo Stipend',
      notes: 'Excludes tuition fees',
      deadlineBadge: 'Due in 48 days',
      deadlineUrgent: false,
      match: 71,
      eligibility: 'PARTIAL',
      icon: <Briefcase size={20} color="var(--color-primary)" />
    },
    {
      id: '4',
      title: "Commonwealth Master's ...",
      provider: 'Commonwealth Scholarship Commi...',
      country: 'United Kingdom',
      coverage: 'Tuition only',
      notes: 'Self-funded living costs',
      deadlineBadge: 'Due in 65 days',
      deadlineUrgent: false,
      match: 64,
      eligibility: 'PARTIAL',
      icon: <Globe size={20} color="var(--color-primary)" />
    },
    {
      id: '5',
      title: 'Rotary Foundation Grant',
      provider: 'The Rotary Foundation',
      country: 'Global',
      coverage: '$30,000 Flat Grant',
      notes: 'One-time payment',
      deadlineBadge: 'Next Cycle',
      deadlineUrgent: false,
      match: 58,
      eligibility: 'BROAD',
      icon: <Globe size={20} color="var(--color-primary)" />
    }
  ];

  const toggleSelect = (id) => {
    setSelectedIds(prev => 
      prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
    );
  };

  const toggleSave = (id) => {
    setSavedIds(prev => 
      prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
    );
  };

  return (
    <div className="page-container" style={{ maxWidth: '1240px', margin: '0 auto', padding: '32px 24px', position: 'relative' }}>
      
      {/* Page Header Row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '32px' }}>
        <div>
          <h1 style={{ fontSize: '2.4rem', fontFamily: 'serif', fontWeight: '600', color: 'var(--color-dark)', marginBottom: '4px' }}>
            Scholarships
          </h1>
          <p style={{ fontSize: '0.9rem', color: 'var(--color-text-muted)' }}>
            48 scholarships available for your profile
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}>
          <span style={{ color: 'var(--color-text-muted)' }}>Sort by</span>
          <button style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid var(--color-border)',
            borderRadius: '6px',
            padding: '8px 14px',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            fontWeight: '600',
            color: 'var(--color-dark)',
            cursor: 'pointer'
          }}>
            Match % <ChevronDown size={16} />
          </button>
        </div>
      </div>

      {/* Main Two-Column Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: '36px', alignItems: 'start' }}>
        
        {/* Left Filter Sidebar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', fontSize: '0.85rem' }}>
          
          {/* Country Filter */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: '700', color: 'var(--color-dark)', fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '12px', letterSpacing: '0.5px' }}>
              <span>COUNTRY</span>
              <span>^</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', color: 'var(--color-dark)' }}>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" /> United Kingdom
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>12</span>
              </label>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', fontWeight: '600' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" defaultChecked /> United States
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>18</span>
              </label>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" /> Germany
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>8</span>
              </label>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" /> Canada
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>10</span>
              </label>
            </div>
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid #E2E8F0', margin: '4px 0' }} />

          {/* Funding Type Filter */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: '700', color: 'var(--color-dark)', fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '12px', letterSpacing: '0.5px' }}>
              <span>FUNDING TYPE</span>
              <span>^</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', fontWeight: '600' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" defaultChecked /> Full Funding
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>14</span>
              </label>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" /> Tuition only
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>22</span>
              </label>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" /> Stipend only
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>6</span>
              </label>
            </div>
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid #E2E8F0', margin: '4px 0' }} />

          {/* Degree Level Filter */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: '700', color: 'var(--color-dark)', fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '12px', letterSpacing: '0.5px' }}>
              <span>DEGREE LEVEL</span>
              <span>^</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" /> Undergraduate
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>12</span>
              </label>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', fontWeight: '600' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" defaultChecked /> Master's
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>28</span>
              </label>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="checkbox" /> PhD / Research
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem' }}>8</span>
              </label>
            </div>
          </div>

        </div>

        {/* Right Scholarship List */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          
          {scholarshipsList.map(item => {
            const isSelected = selectedIds.includes(item.id);
            const isSaved = savedIds.includes(item.id);

            return (
              <div 
                key={item.id}
                style={{
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #E2E8F0',
                  borderRadius: '10px',
                  padding: '20px 24px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '20px',
                  boxShadow: '0 2px 4px rgba(0,0,0,0.02)'
                }}
              >
                {/* Checkbox */}
                <input 
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => toggleSelect(item.id)}
                  style={{ width: '18px', height: '18px', cursor: 'pointer', accentColor: 'var(--color-dark)' }}
                />

                {/* Institution Icon */}
                <div style={{
                  width: '44px',
                  height: '44px',
                  borderRadius: '8px',
                  backgroundColor: '#F8FAFC',
                  border: '1px solid #E2E8F0',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0
                }}>
                  {item.icon}
                </div>

                {/* Title & Provider */}
                <div style={{ flex: 1.2 }}>
                  <h3 style={{ fontSize: '1rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '2px' }}>
                    {item.title}
                  </h3>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)' }}>
                    {item.provider}
                  </p>
                </div>

                {/* Country */}
                <div style={{ flex: 0.8, fontSize: '0.88rem', color: 'var(--color-text-muted)' }}>
                  {item.country}
                </div>

                {/* Coverage Details */}
                <div style={{ flex: 1.2 }}>
                  <div style={{ fontWeight: '700', fontSize: '0.88rem', color: 'var(--color-dark)' }}>
                    {item.coverage}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: item.deadlineUrgent ? '#B91C1C' : 'var(--color-text-muted)' }}>
                    {item.notes || item.deadlineBadge}
                  </div>
                </div>

                {/* Due Date Badge */}
                {item.deadlineBadge && (
                  <div style={{
                    backgroundColor: item.deadlineUrgent ? '#FEE2E2' : '#F1F5F9',
                    color: item.deadlineUrgent ? '#991B1B' : 'var(--color-text-muted)',
                    fontSize: '0.72rem',
                    fontWeight: '600',
                    padding: '4px 8px',
                    borderRadius: '4px',
                    textAlign: 'center',
                    minWidth: '70px'
                  }}>
                    {item.deadlineBadge}
                  </div>
                )}

                {/* Match Score */}
                <div style={{ textAlign: 'center', minWidth: '50px' }}>
                  <div style={{ fontSize: '1rem', fontWeight: '800', color: '#047857' }}>
                    {item.match}%
                  </div>
                  <div style={{ fontSize: '0.68rem', color: 'var(--color-text-muted)', fontWeight: 'bold' }}>
                    MATCH
                  </div>
                </div>

                {/* Eligibility Tag */}
                <div style={{ minWidth: '90px' }}>
                  <span style={{
                    display: 'inline-block',
                    padding: '3px 10px',
                    borderRadius: '12px',
                    fontSize: '0.7rem',
                    fontWeight: '700',
                    border: item.eligibility === 'STRONG' ? '1px solid #A7F3D0' : item.eligibility === 'PARTIAL' ? '1px solid #FDE68A' : '1px solid #E2E8F0',
                    color: item.eligibility === 'STRONG' ? '#047857' : item.eligibility === 'PARTIAL' ? '#B45309' : '#475569',
                    backgroundColor: item.eligibility === 'STRONG' ? '#ECFDF5' : item.eligibility === 'PARTIAL' ? '#FFFBEB' : '#F8FAFC'
                  }}>
                    • {item.eligibility}
                  </span>
                </div>

                {/* Bookmark Icon */}
                <button 
                  onClick={() => toggleSave(item.id)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: isSaved ? 'var(--color-primary)' : '#94A3B8' }}
                >
                  <Bookmark size={18} fill={isSaved ? 'var(--color-primary)' : 'none'} />
                </button>
              </div>
            );
          })}

          {/* Load More Button */}
          <div style={{ textAlign: 'center', marginTop: '20px' }}>
            <button className="btn btn-outline" style={{ padding: '10px 24px', fontSize: '0.88rem', backgroundColor: '#FFFFFF' }}>
              Load more scholarships
            </button>
          </div>

        </div>

      </div>

      {/* Floating Bottom Comparison Bar */}
      {selectedIds.length >= 2 && (
        <div style={{
          position: 'fixed',
          bottom: '30px',
          left: '50%',
          transform: 'translateX(-50%)',
          backgroundColor: '#1E293B',
          color: '#FFFFFF',
          padding: '16px 24px',
          borderRadius: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '32px',
          boxShadow: '0 10px 25px rgba(0,0,0,0.2)',
          zIndex: 1000
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ display: 'flex', gap: '-8px' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '6px', backgroundColor: '#334155', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Building2 size={16} />
              </div>
              <div style={{ width: '32px', height: '32px', borderRadius: '6px', backgroundColor: '#475569', display: 'flex', alignItems: 'center', justifyContent: 'center', marginLeft: '-8px' }}>
                <GraduationCap size={16} />
              </div>
            </div>
            <div>
              <div style={{ fontWeight: '700', fontSize: '0.88rem' }}>{selectedIds.length} scholarships selected</div>
              <div style={{ fontSize: '0.75rem', color: '#94A3B8' }}>Compare eligibility and costs side-by-side</div>
            </div>
          </div>

          <button 
            onClick={() => setSelectedIds([])}
            style={{ background: 'none', border: 'none', color: '#94A3B8', fontSize: '0.82rem', cursor: 'pointer' }}
          >
            Clear all
          </button>

          <button 
            className="btn"
            onClick={() => navigate('/compare')}
            style={{
              backgroundColor: '#FFFFFF',
              color: '#0F172A',
              fontWeight: '700',
              padding: '10px 20px',
              borderRadius: '6px',
              fontSize: '0.88rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            Compare Now <ArrowRight size={16} />
          </button>
        </div>
      )}

    </div>
  );
}