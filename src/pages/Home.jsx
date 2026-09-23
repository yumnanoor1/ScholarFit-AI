import React from 'react';
import { useNavigate } from 'react-router-dom';
import { GraduationCap, Award, Compass, TrendingUp, ShieldCheck, ArrowRight } from 'lucide-react';

export default function Home() {
  const navigate = useNavigate();

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100vh' }}>
      {/* Hero Section */}
      <section style={{
        backgroundColor: 'var(--color-dark)',
        color: '#FFFFFF',
        padding: '80px 24px',
        textAlign: 'center'
      }}>
        <div style={{ maxWidth: '800px', margin: '0 auto' }}>
          <span style={{
            color: 'var(--color-secondary)',
            fontSize: '0.85rem',
            fontWeight: '600',
            textTransform: 'uppercase',
            letterSpacing: '1px'
          }}>
            Intelligent Decision-Support Platform
          </span>
          <h1 style={{ fontSize: '2.8rem', fontWeight: '800', margin: '16px 0 20px', lineHeight: '1.2' }}>
            FitScholar AI: Study Abroad & Scholarship Navigator
          </h1>
          <p style={{ fontSize: '1.1rem', color: '#A0AEC0', marginBottom: '32px', lineHeight: '1.6' }}>
            Evaluate university programs, eligibility, funding opportunities, application pathways, and financial feasibility—all powered by explainable decision-support algorithms.
          </p>
          <div style={{ display: 'flex', gap: '16px', justifyContent: 'center' }}>
            <button className="btn btn-primary" onClick={() => navigate('/register')} style={{ padding: '12px 28px', fontSize: '1rem' }}>
              Get Started <ArrowRight size={18} />
            </button>
            <button className="btn btn-outline" onClick={() => navigate('/login')} style={{ padding: '12px 28px', fontSize: '1rem', color: '#FFFFFF', borderColor: 'var(--color-secondary)' }}>
              Sign In
            </button>
          </div>
        </div>
      </section>

      {/* Decision Engine Value Flow */}
      <section style={{ maxWidth: '1200px', margin: '60px auto', padding: '0 24px' }}>
        <h2 style={{ textAlign: 'center', fontSize: '1.8rem', color: 'var(--color-dark)', marginBottom: '40px' }}>
          Decision Pipeline Architecture
        </h2>

        <div className="grid-3">
          <div className="card" style={{ textAlign: 'center', padding: '28px' }}>
            <Compass size={36} color="var(--color-primary)" style={{ marginBottom: '12px' }} />
            <h3 style={{ fontSize: '1.1rem', marginBottom: '8px' }}>1. Eligibility Matching</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
              Evaluates CGPA, language proficiency, research credentials, and prerequisite coverage.
            </p>
          </div>

          <div className="card" style={{ textAlign: 'center', padding: '28px' }}>
            <Award size={36} color="var(--color-primary)" style={{ marginBottom: '12px' }} />
            <h3 style={{ fontSize: '1.1rem', marginBottom: '8px' }}>2. Funding Analysis</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
              Matches scholarships, fellowships, RA/TA positions, and institutional tuition waivers.
            </p>
          </div>

          <div className="card" style={{ textAlign: 'center', padding: '28px' }}>
            <TrendingUp size={36} color="var(--color-primary)" style={{ marginBottom: '12px' }} />
            <h3 style={{ fontSize: '1.1rem', marginBottom: '8px' }}>3. Financial Feasibility</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
              Computes remaining out-of-pocket costs by balancing total expenses against funding.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}