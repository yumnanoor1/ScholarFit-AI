import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import { 
  Building2, 
  Award, 
  AlertCircle, 
  FileText, 
  Globe, 
  MessageSquare, 
  ArrowRight 
} from 'lucide-react';

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { profile } = useProfile();

  const userName = user?.name || profile?.name || "John";
  const completionPercentage = profile?.profileCompletionPercentage || 75;

  return (
    <div className="page-container" style={{ maxWidth: '1200px', margin: '0 auto', padding: '24px' }}>
      
      {/* Greeting Header */}
      <div style={{ textAlign: 'center', margin: '20px 0 36px 0' }}>
        <h1 style={{ fontSize: '2rem', fontWeight: '800', color: 'var(--color-dark)', marginBottom: '6px' }}>
          Good morning, {userName.split(' ')[0]}!
        </h1>
        <p style={{ fontSize: '1rem', color: 'var(--color-text-muted)' }}>
          Here's an update on your study abroad journey.
        </p>
      </div>

      {/* Main Dashboard Grid Structure */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: '24px', alignItems: 'start' }}>
        
        {/* Left Primary Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Profile Completion Card */}
          <div className="card" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: 'var(--color-dark)' }}>
                Profile Completion
              </h3>
              <span style={{
                backgroundColor: '#FEF3C7',
                color: '#D97706',
                padding: '4px 12px',
                borderRadius: '12px',
                fontSize: '0.8rem',
                fontWeight: '700'
              }}>
                {completionPercentage}% Complete
              </span>
            </div>

            {/* Progress Bar Container */}
            <div style={{
              width: '100%',
              height: '10px',
              backgroundColor: '#E2E8F0',
              borderRadius: '5px',
              overflow: 'hidden',
              marginBottom: '20px'
            }}>
              <div style={{
                width: `${completionPercentage}%`,
                height: '100%',
                backgroundColor: 'var(--color-primary)',
                borderRadius: '5px',
                transition: 'width 0.4s ease'
              }} />
            </div>

            {/* Best Next Action Sub-box */}
            <div style={{
              backgroundColor: '#F8FAFC',
              border: '1px solid var(--color-border-light)',
              borderRadius: '8px',
              padding: '16px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: '16px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  backgroundColor: '#E2E8F0',
                  color: 'var(--color-primary)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0
                }}>
                  <AlertCircle size={18} />
                </div>
                <div>
                  <h4 style={{ fontSize: '0.9rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '2px' }}>
                    Best Next Action
                  </h4>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)' }}>
                    Improve English language score or complete missing profile details.
                  </p>
                </div>
              </div>

              <button 
                className="btn btn-primary" 
                onClick={() => navigate('/profile')}
                style={{ padding: '8px 16px', fontSize: '0.85rem', flexShrink: 0 }}
              >
                Complete Now
              </button>
            </div>
          </div>

          {/* Matches & Scholarships Counter Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
            
            {/* Recommended Universities Card */}
            <div className="card" style={{ padding: '24px' }}>
              <div style={{
                width: '40px',
                height: '40px',
                borderRadius: '8px',
                backgroundColor: '#EBF3FA',
                color: 'var(--color-primary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '16px'
              }}>
                <Building2 size={22} />
              </div>
              <span style={{ fontSize: '0.88rem', color: 'var(--color-text-muted)', fontWeight: '500' }}>
                Recommended Universities
              </span>
              <div style={{ fontSize: '2rem', fontWeight: '800', color: 'var(--color-dark)', margin: '4px 0 12px 0' }}>
                5
              </div>
              <button 
                onClick={() => navigate('/universities')}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--color-primary)',
                  fontWeight: '600',
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                  padding: 0,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px'
                }}
              >
                View Matches →
              </button>
            </div>

            {/* Matching Scholarships Card */}
            <div className="card" style={{ padding: '24px' }}>
              <div style={{
                width: '40px',
                height: '40px',
                borderRadius: '8px',
                backgroundColor: '#DCFCE7',
                color: 'var(--color-success)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '16px'
              }}>
                <Award size={22} />
              </div>
              <span style={{ fontSize: '0.88rem', color: 'var(--color-text-muted)', fontWeight: '500' }}>
                Matching Scholarships
              </span>
              <div style={{ fontSize: '2rem', fontWeight: '800', color: 'var(--color-dark)', margin: '4px 0 12px 0' }}>
                8
              </div>
              <button 
                onClick={() => navigate('/scholarships')}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--color-success)',
                  fontWeight: '600',
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                  padding: 0,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px'
                }}
              >
                Explore Funding →
              </button>
            </div>

          </div>

          {/* Upcoming Deadlines Card */}
          <div className="card" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '20px' }}>
              Upcoming Deadlines
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              
              {/* Deadline Item 1 */}
              <div style={{
                border: '1px solid var(--color-border)',
                borderRadius: '8px',
                padding: '16px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <div style={{
                    backgroundColor: '#F1F5F9',
                    border: '1px solid var(--color-border-light)',
                    borderRadius: '6px',
                    padding: '8px 12px',
                    textAlign: 'center',
                    minWidth: '54px'
                  }}>
                    <div style={{ fontSize: '0.7rem', fontWeight: '700', color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>DEC</div>
                    <div style={{ fontSize: '1.2rem', fontWeight: '800', color: 'var(--color-dark)' }}>15</div>
                  </div>
                  <div>
                    <h4 style={{ fontSize: '0.95rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '2px' }}>
                      University of Toronto - Application
                    </h4>
                    <p style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)' }}>
                      Early Bird Deadline
                    </p>
                  </div>
                </div>
                <span style={{ fontSize: '0.82rem', fontWeight: '600', color: 'var(--color-text-muted)' }}>
                  12 Days Left
                </span>
              </div>

              {/* Deadline Item 2 */}
              <div style={{
                border: '1px solid var(--color-border)',
                borderRadius: '8px',
                padding: '16px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <div style={{
                    backgroundColor: '#F1F5F9',
                    border: '1px solid var(--color-border-light)',
                    borderRadius: '6px',
                    padding: '8px 12px',
                    textAlign: 'center',
                    minWidth: '54px'
                  }}>
                    <div style={{ fontSize: '0.7rem', fontWeight: '700', color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>JAN</div>
                    <div style={{ fontSize: '1.2rem', fontWeight: '800', color: 'var(--color-dark)' }}>05</div>
                  </div>
                  <div>
                    <h4 style={{ fontSize: '0.95rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '2px' }}>
                      Global Excellence Scholarship
                    </h4>
                    <p style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)' }}>
                      Supporting Documents Required
                    </p>
                  </div>
                </div>
                <span style={{ fontSize: '0.82rem', fontWeight: '600', color: 'var(--color-text-muted)' }}>
                  32 Days Left
                </span>
              </div>

            </div>
          </div>

        </div>

        {/* Right Secondary Sidebar Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Dark Funding Summary Card */}
          <div style={{
            backgroundColor: 'var(--color-dark)',
            color: '#FFFFFF',
            borderRadius: '12px',
            padding: '28px 24px',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
          }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: '700', marginBottom: '20px', color: '#FFFFFF' }}>
              Funding Summary
            </h3>

            <div style={{ marginBottom: '24px' }}>
              <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: '#A0AEC0', fontWeight: '700', letterSpacing: '0.5px' }}>
                POTENTIAL FUNDING
              </span>
              <div style={{ fontSize: '2.2rem', fontWeight: '800', color: '#FFFFFF', margin: '4px 0 2px 0' }}>
                $42,500
              </div>
              <p style={{ fontSize: '0.78rem', color: '#A0AEC0', fontStyle: 'italic' }}>
                Based on 8 matched scholarships
              </p>
            </div>

            <hr style={{ border: 'none', borderTop: '1px solid #2D333F', margin: '20px 0' }} />

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.9rem', marginBottom: '28px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: '#CBD5E1' }}>
                <span>Avg. Annual Tuition</span>
                <strong style={{ color: '#FFFFFF' }}>$28,000</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: '#CBD5E1' }}>
                <span>Living Expenses</span>
                <strong style={{ color: '#FFFFFF' }}>$15,000</strong>
              </div>
            </div>

            <button 
              className="btn"
              onClick={() => navigate('/financial')}
              style={{
                width: '100%',
                backgroundColor: 'var(--color-primary)',
                color: '#FFFFFF',
                padding: '12px',
                fontSize: '0.9rem',
                fontWeight: '600',
                borderRadius: '6px',
                border: 'none',
                cursor: 'pointer'
              }}
            >
              Detailed Financial Plan
            </button>
          </div>

          {/* Resources Card */}
          <div className="card" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '16px' }}>
              Resources
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              
              <div 
                onClick={() => navigate('/documents')}
                style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', color: 'var(--color-dark)', fontSize: '0.9rem', fontWeight: '500' }}
              >
                <FileText size={18} color="var(--color-text-muted)" />
                <span>Document Checklist</span>
              </div>

              <div 
                onClick={() => alert("Redirecting to visa requirement guidelines...")}
                style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', color: 'var(--color-dark)', fontSize: '0.9rem', fontWeight: '500' }}
              >
                <Globe size={18} color="var(--color-text-muted)" />
                <span>Visa Requirements</span>
              </div>

              <div 
                onClick={() => alert("Opening AI Counselor Chat...")}
                style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', color: 'var(--color-dark)', fontSize: '0.9rem', fontWeight: '500' }}
              >
                <MessageSquare size={18} color="var(--color-text-muted)" />
                <span>Counselor Chat</span>
              </div>

            </div>
          </div>

        </div>

      </div>

    </div>
  );
}