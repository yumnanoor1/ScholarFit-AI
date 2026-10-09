import { useNavigate } from 'react-router-dom';
import { GraduationCap, Award, DollarSign } from 'lucide-react';
import { AuroraHero } from '@/components/ui/aurora-hero-bg';
import { GlowCard } from '../components/ui/spotlight-card';

export default function Home() {
  const navigate = useNavigate();

  return (
    <AuroraHero className="home-page-aurora min-h-screen flex-col items-stretch justify-start overflow-hidden bg-slate-950">
    <div className="min-h-screen w-full" style={{ display: 'flex', flexDirection: 'column', color: '#F8FAFC' }}>
      {/* 1. Header Navigation */}
      <header className="home-header" style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: '1px solid rgba(255,255,255,0.14)',
        backgroundColor: 'rgba(15,23,42,0.35)',
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
          <span style={{ fontWeight: '700', fontSize: '1.1rem', color: '#F8FAFC' }}>
            FitScholar <span style={{ color: '#C4B5FD', fontWeight: '400' }}>AI</span>
          </span>
        </div>

        <nav className="home-nav">
          <a className="home-nav-link" href="#features" style={{ color: '#E2E8F0', textDecoration: 'none', fontSize: '0.9rem', fontWeight: '500' }}>Features</a>
          <a className="home-nav-link" href="#how-it-works" style={{ color: '#E2E8F0', textDecoration: 'none', fontSize: '0.9rem', fontWeight: '500' }}>How It Works</a>
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
      <section className="home-centered-hero flex flex-col items-center justify-center px-5 py-20 text-center">
        <div className="mx-auto max-w-4xl">
          <h1 className="text-4xl font-extrabold leading-tight text-white sm:text-6xl lg:text-7xl">
            Your Master&apos;s Journey Starts Here
          </h1>
          <p className="mx-auto mb-8 mt-6 max-w-2xl text-base leading-relaxed text-slate-200 sm:text-xl">
            Find Master&apos;s programs, scholarships, and funding that fit your academic profile and goals.
          </p>
          <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
            <button className="btn btn-primary" onClick={() => navigate('/register')} style={{ padding: '14px 32px', fontSize: '1rem', borderRadius: '6px' }}>
              Get Started
            </button>
            <button className="btn btn-outline" onClick={() => document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' })} style={{ padding: '14px 28px', color: '#F8FAFC', borderColor: 'rgba(255,255,255,0.55)' }}>
              Explore Features
            </button>
          </div>
        </div>
      </section>

      {/* 3. Problem Statement Section */}
      <section style={{
        textAlign: 'center',
        padding: '60px 20px',
        maxWidth: '800px',
        margin: '0 auto'
      }}>
        <h2 style={{ fontSize: '1.8rem', fontWeight: '700', color: '#F8FAFC', marginBottom: '16px' }}>
          Studying abroad is complex. We make it simple.
        </h2>
        <p style={{ fontSize: '1rem', color: '#CBD5E1', lineHeight: '1.6' }}>
          Thousands of universities, countless scholarships, and endless application forms. Most students miss opportunities because they can't find them. FitScholar AI scans everything and surfaces only what fits you.
        </p>
      </section>

      {/* 4. How It Works Section */}
      <section id="how-it-works" style={{
        padding: '80px 20px',
        textAlign: 'center'
      }}>
        <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '1.8rem', fontWeight: '700', color: '#F8FAFC', marginBottom: '48px' }}>
            How FitScholar AI works
          </h2>

          <div className="grid-3" style={{ gap: '30px' }}>
            {/* Step 1 */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: 'rgba(139,92,246,0.72)',
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
              <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: '#F8FAFC', marginBottom: '8px' }}>
                Create Your Profile
              </h3>
              <p style={{ fontSize: '0.88rem', color: '#CBD5E1', lineHeight: '1.5' }}>
                Share your grades, interests, budget, and abroad expectations in minutes.
              </p>
            </div>

            {/* Step 2 */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: 'rgba(59,130,246,0.72)',
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
              <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: '#F8FAFC', marginBottom: '8px' }}>
                Get Matched
              </h3>
              <p style={{ fontSize: '0.88rem', color: '#CBD5E1', lineHeight: '1.5' }}>
                Our AI ranks universities and scholarships by your real chance of success.
              </p>
            </div>

            {/* Step 3 */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: 'rgba(236,72,153,0.72)',
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
              <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: '#F8FAFC', marginBottom: '8px' }}>
                Apply Confidently
              </h3>
              <p style={{ fontSize: '0.88rem', color: '#CBD5E1', lineHeight: '1.5' }}>
                Track deadlines, get step-by-step guidance, and apply to the right place at the right time.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 5. Features Grid Section */}
      <section id="features" style={{ padding: '80px 20px', textAlign: 'center' }}>
        <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '1.8rem', fontWeight: '700', color: '#F8FAFC', marginBottom: '48px' }}>
            Everything you need to go global
          </h2>

          <div className="grid-3" style={{ gap: '24px' }}>
            {/* Feature 1 */}
            <GlowCard customSize className="card" style={{ textAlign: 'left', padding: '28px 24px', backgroundColor: 'rgba(15,23,42,0.68)', border: '1px solid rgba(255,255,255,0.14)', color: '#F8FAFC' }}>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                backgroundColor: 'rgba(255,255,255,0.1)',
                color: '#C4B5FD',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '16px'
              }}>
                <GraduationCap size={20} />
              </div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: '#F8FAFC', marginBottom: '8px' }}>
                University Matching
              </h3>
              <p style={{ fontSize: '0.88rem', color: '#CBD5E1', lineHeight: '1.5' }}>
                Find programs ranked by fit—not just prestige. See acceptance probability based on your profile.
              </p>
            </GlowCard>

            {/* Feature 2 */}
            <GlowCard customSize className="card" style={{ textAlign: 'left', padding: '28px 24px', backgroundColor: 'rgba(15,23,42,0.68)', border: '1px solid rgba(255,255,255,0.14)', color: '#F8FAFC' }}>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                backgroundColor: 'rgba(255,255,255,0.1)',
                color: '#C4B5FD',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '16px'
              }}>
                <Award size={20} />
              </div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: '#F8FAFC', marginBottom: '8px' }}>
                Scholarship Finder
              </h3>
              <p style={{ fontSize: '0.88rem', color: '#CBD5E1', lineHeight: '1.5' }}>
                Discover fully-funded and partial scholarships you didn't know existed. Filter by eligibility and amount.
              </p>
            </GlowCard>

            {/* Feature 3 */}
            <GlowCard customSize className="card" style={{ textAlign: 'left', padding: '28px 24px', backgroundColor: 'rgba(15,23,42,0.68)', border: '1px solid rgba(255,255,255,0.14)', color: '#F8FAFC' }}>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                backgroundColor: 'rgba(255,255,255,0.1)',
                color: '#C4B5FD',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '16px'
              }}>
                <DollarSign size={20} />
              </div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: '700', color: '#F8FAFC', marginBottom: '8px' }}>
                Funding Analysis
              </h3>
              <p style={{ fontSize: '0.88rem', color: '#CBD5E1', lineHeight: '1.5' }}>
                Understand real cost of attendance and compare net out-of-pocket expenses side by side.
              </p>
            </GlowCard>
          </div>
        </div>
      </section>

      {/* 7. Bottom Call to Action Section */}
      <section style={{ textAlign: 'center', padding: '80px 20px' }}>
        <h2 style={{ fontSize: '2rem', fontWeight: '800', color: '#F8FAFC', marginBottom: '12px' }}>
          Ready to find where you belong?
        </h2>
        <p style={{ fontSize: '1rem', color: '#CBD5E1', marginBottom: '28px' }}>
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

    </div>
    </AuroraHero>
  );
}