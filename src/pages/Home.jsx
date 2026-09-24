import React from 'react';
import { useNavigate } from 'react-router-dom';
import { GraduationCap, Award, DollarSign, ArrowRight } from 'lucide-react';

export default function Home() {
  const navigate = useNavigate();

  return (
    <div style={{ backgroundColor: '#FFFFFF', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      
      {/* 1. Header Navigation */}
      <header style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '20px 48px',
        borderBottom: '1px solid #E5E7EB',
        backgroundColor: '#FFFFFF',
        position: 'sticky',
        top: 0,
        zIndex: 50
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }} onClick={() => navigate('/')}>
          <div style={{
            width: '28px',
            height: '28px',
            borderRadius: '6px',
            backgroundColor: 'var(--color-primary)',
            color: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 'bold',
            fontSize: '0.9rem'
          }}>
            F
          </div>
          <span style={{ fontWeight: '700', fontSize: '1.1rem', color: 'var(--color-dark)' }}>
            FitScholar <span style={{ color: 'var(--color-primary)', fontWeight: '400' }}>AI</span>
          </span>
        </div>

        <nav style={{ display: 'flex', alignItems: 'center', gap: '32px' }}>
          <a href="#features" style={{ color: 'var(--color-dark)', textDecoration: 'none', fontSize: '0.9rem', fontWeight: '500' }}>Features</a>
          <a href="#how-it-works" style={{ color: 'var(--color-dark)', textDecoration: 'none', fontSize: '0.9rem', fontWeight: '500' }}>How It Works</a>
          <button 
            className="btn btn-primary" 
            onClick={() => navigate('/login')}
            style={{ padding: '8px 20px', fontSize: '0.88rem' }}
          >
            Login
          </button>
        </nav>
      </header>

      {/* 2. Hero Section */}
      <section style={{
        textAlign: 'center',
        padding: '100px 20px 80px 20px',
        maxWidth: '900px',
        margin: '0 auto'
      }}>
        <h1 style={{
          fontSize: '3rem',
          fontWeight: '800',
          color: 'var(--color-dark)',
          lineHeight: '1.2',
          letterSpacing: '-0.5px',
          marginBottom: '20px'
        }}>
          Go from "I want to study abroad" to <span style={{ color: 'var(--color-primary)' }}>"I am going"</span>
        </h1>
        <p style={{
          fontSize: '1.1rem',
          color: 'var(--color-text-muted)',
          lineHeight: '1.6',
          maxWidth: '680px',
          margin: '0 auto 36px auto'
        }}>
          FitScholar AI matches your profile to the best universities, scholarships, and funding opportunities worldwide—saving you time, money, and stress.
        </p>
        <button 
          className="btn btn-primary" 
          onClick={() => navigate('/register')}
          style={{ padding: '14px 32px', fontSize: '1rem', borderRadius: '6px' }}
        >
          Get Started
        </button>
      </section>

      {/* 3. Problem Statement Section */}
      <section style={{
        textAlign: 'center',
        padding: '60px 20px',
        maxWidth: '800px',
        margin: '0 auto'
      }}>
        <h2 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '16px' }}>
          Studying abroad is complex. We make it simple.
        </h2>
        <p style={{ fontSize: '1rem', color: 'var(--color-text-muted)', lineHeight: '1.6' }}>
          Thousands of universities, countless scholarships, and endless application forms. Most students miss opportunities because they can't find them. FitScholar AI scans everything and surfaces only what fits you.
        </p>
      </section>

      {/* 4. How It Works Section */}
      <section id="how-it-works" style={{
        backgroundColor: 'var(--color-bg)',
        padding: '80px 20px',
        textAlign: 'center'
      }}>
        <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '48px' }}>
            How FitScholar AI works
          </h2>

          <div className="grid-3" style={{ gap: '30px' }}>
            {/* Step 1 */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: 'var(--color-primary)',
                color: '#FFFFFF',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 'bold',
                fontSize: '1.1rem',
                marginBottom: '20px'
              }}>
                1
              </div>
              <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '8px' }}>
                Create Your Profile
              </h3>
              <p style={{ fontSize: '0.88rem', color: 'var(--color-text-muted)', lineHeight: '1.5' }}>
                Share your grades, interests, budget, and abroad expectations in minutes.
              </p>
            </div>

            {/* Step 2 */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: 'var(--color-primary)',
                color: '#FFFFFF',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 'bold',
                fontSize: '1.1rem',
                marginBottom: '20px'
              }}>
                2
              </div>
              <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '8px' }}>
                Get Matched
              </h3>
              <p style={{ fontSize: '0.88rem', color: 'var(--color-text-muted)', lineHeight: '1.5' }}>
                Our AI ranks universities and scholarships by your real chance of success.
              </p>
            </div>

            {/* Step 3 */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: 'var(--color-primary)',
                color: '#FFFFFF',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 'bold',
                fontSize: '1.1rem',
                marginBottom: '20px'
              }}>
                3
              </div>
              <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '8px' }}>
                Apply Confidently
              </h3>
              <p style={{ fontSize: '0.88rem', color: 'var(--color-text-muted)', lineHeight: '1.5' }}>
                Track deadlines, get step-by-step guidance, and apply to the right place at the right time.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 5. Features Grid Section */}
      <section id="features" style={{ padding: '80px 20px', textAlign: 'center' }}>
        <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '48px' }}>
            Everything you need to go global
          </h2>

          <div className="grid-3" style={{ gap: '24px' }}>
            {/* Feature 1 */}
            <div className="card" style={{ textAlign: 'left', padding: '28px 24px' }}>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                backgroundColor: 'var(--color-hover-bg)',
                color: 'var(--color-primary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '16px'
              }}>
                <GraduationCap size={20} />
              </div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '8px' }}>
                University Matching
              </h3>
              <p style={{ fontSize: '0.88rem', color: 'var(--color-text-muted)', lineHeight: '1.5' }}>
                Find programs ranked by fit—not just prestige. See acceptance probability based on your profile.
              </p>
            </div>

            {/* Feature 2 */}
            <div className="card" style={{ textAlign: 'left', padding: '28px 24px' }}>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                backgroundColor: 'var(--color-hover-bg)',
                color: 'var(--color-primary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '16px'
              }}>
                <Award size={20} />
              </div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '8px' }}>
                Scholarship Finder
              </h3>
              <p style={{ fontSize: '0.88rem', color: 'var(--color-text-muted)', lineHeight: '1.5' }}>
                Discover fully-funded and partial scholarships you didn't know existed. Filter by eligibility and amount.
              </p>
            </div>

            {/* Feature 3 */}
            <div className="card" style={{ textAlign: 'left', padding: '28px 24px' }}>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                backgroundColor: 'var(--color-hover-bg)',
                color: 'var(--color-primary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '16px'
              }}>
                <DollarSign size={20} />
              </div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--color-dark)', marginBottom: '8px' }}>
                Funding Analysis
              </h3>
              <p style={{ fontSize: '0.88rem', color: 'var(--color-text-muted)', lineHeight: '1.5' }}>
                Understand real cost of attendance and compare net out-of-pocket expenses side by side.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 6. Dashboard Preview Card Section */}
      <section style={{ backgroundColor: 'var(--color-bg)', padding: '60px 20px' }}>
        <div style={{
          maxWidth: '900px',
          margin: '0 auto',
          backgroundColor: '#FFFFFF',
          borderRadius: '16px',
          padding: '32px',
          boxShadow: '0 8px 30px rgba(0,0,0,0.06)',
          border: '1px solid var(--color-border)'
        }}>
          {/* Mock Dashboard Wireframe Visual */}
          <div style={{
            backgroundColor: 'var(--color-dark)',
            borderRadius: '12px',
            padding: '24px',
            color: '#FFFFFF'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid #2D333F', paddingBottom: '12px' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--color-secondary)', fontWeight: 'bold' }}>FitScholar AI Dashboard</span>
              <span style={{ fontSize: '0.75rem', backgroundColor: '#2D333F', padding: '4px 10px', borderRadius: '12px', color: '#A0AEC0' }}>Live Analytics</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
              <div style={{ backgroundColor: '#252A34', padding: '12px', borderRadius: '6px', textAlign: 'center' }}>
                <div style={{ fontSize: '0.7rem', color: '#A0AEC0' }}>Match Rate</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 'bold', color: 'var(--color-secondary)', marginTop: '2px' }}>94%</div>
              </div>
              <div style={{ backgroundColor: '#252A34', padding: '12px', borderRadius: '6px', textAlign: 'center' }}>
                <div style={{ fontSize: '0.7rem', color: '#A0AEC0' }}>Eligible Programs</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 'bold', marginTop: '2px' }}>25</div>
              </div>
              <div style={{ backgroundColor: '#252A34', padding: '12px', borderRadius: '6px', textAlign: 'center' }}>
                <div style={{ fontSize: '0.7rem', color: '#A0AEC0' }}>Saved Funding</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 'bold', color: 'var(--color-success)', marginTop: '2px' }}>$15,000</div>
              </div>
              <div style={{ backgroundColor: '#252A34', padding: '12px', borderRadius: '6px', textAlign: 'center' }}>
                <div style={{ fontSize: '0.7rem', color: '#A0AEC0' }}>Deadlines</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 'bold', marginTop: '2px' }}>3 Active</div>
              </div>
            </div>

            <div style={{ backgroundColor: '#252A34', padding: '16px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: '0.9rem', fontWeight: 'bold' }}>Technical University of Munich</div>
                <div style={{ fontSize: '0.78rem', color: '#A0AEC0' }}>M.Sc. Informatics • Germany</div>
              </div>
              <span style={{ fontSize: '0.8rem', backgroundColor: 'var(--color-primary)', color: '#FFFFFF', padding: '4px 10px', borderRadius: '4px' }}>
                94% Match Score
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 7. Bottom Call to Action Section */}
      <section style={{ textAlign: 'center', padding: '80px 20px' }}>
        <h2 style={{ fontSize: '2rem', fontWeight: '800', color: 'var(--color-dark)', marginBottom: '12px' }}>
          Ready to find where you belong?
        </h2>
        <p style={{ fontSize: '1rem', color: 'var(--color-text-muted)', marginBottom: '28px' }}>
          Join thousands of students who used FitScholar AI to land their dream study abroad opportunity.
        </p>
        <button 
          className="btn btn-primary" 
          onClick={() => navigate('/register')}
          style={{ padding: '12px 28px', fontSize: '0.95rem' }}
        >
          Start Your Match
        </button>
      </section>

      {/* 8. Simple Footer */}
      <footer style={{
        marginTop: 'auto',
        borderTop: '1px solid #E5E7EB',
        padding: '24px 48px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontSize: '0.82rem',
        color: 'var(--color-text-muted)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontWeight: 'bold', color: 'var(--color-dark)' }}>FitScholar</span> AI
        </div>
        <div>
          © {new Date().getFullYear()} FitScholar AI. All rights reserved.
        </div>
      </footer>

    </div>
  );
}