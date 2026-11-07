import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight, CheckCircle2, ChevronDown, ClipboardCheck, Search, UserRound,
} from 'lucide-react';
import BrandLogo from '../components/common/BrandLogo';
import './Home.css';

const navLinks = [
  ['About', '#about'],
  ['How It Works', '#how-it-works'],
  ['FAQ', '#faq'],
];

const aboutPoints = [
  'Scholarship eligibility checks',
  'Official scholarship source links',
  'Funding and affordability information',
  'Preparation steps for scholarship applications',
];

const steps = [
  { icon: UserRound, title: 'Create Your Profile', text: 'Add the academic, nationality, language, and funding information relevant to scholarship checks.' },
  { icon: Search, title: 'Explore Scholarships', text: 'Review scholarship eligibility, funding information, and source verification.' },
  { icon: ClipboardCheck, title: 'Prepare Your Application', text: 'Review official scholarship requirements, documents, application links, and verified deadlines.' },
];

const faqs = [
  {
    q: 'Where does scholarship information come from?',
    a: 'Scholarship records include their recorded source and verification details. Confirm current requirements, funding, and dates with the official provider.',
  },
  {
    q: 'Does an eligibility result guarantee a scholarship?',
    a: 'No. FitScholar checks the available stated scholarship requirements. Providers make the final award decisions.',
  },
  {
    q: 'Is FitScholars free for students?',
    a: 'Yes. Create an account, complete your profile, and explore scholarships and preparation guidance.',
  },
  {
    q: 'I have not taken IELTS or TOEFL yet. Can I still use it?',
    a: 'Yes. If a scholarship lists a language requirement and your profile lacks a comparable result, the check shows missing information rather than treating it as a failure.',
  },
];

function Doodle({ className }) {
  return (
    <svg className={className} viewBox="0 0 120 60" fill="none" aria-hidden="true">
      <path d="M4 40c14-26 30-26 34 0s22 26 30 0 24-28 36-6" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

// Adds is-visible once the element scrolls into view (used for the About photo pop-up)
function useRevealOnScroll() {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return undefined;
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    }, { threshold: 0.25 });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, visible];
}

export default function Home() {
  const navigate = useNavigate();
  const [aboutVisualRef, aboutVisualVisible] = useRevealOnScroll();

  return (
    <div className="home-page">
      {/* ---------- Header ---------- */}
      <header className="home-header">
        <div className="home-header-inner">
          <button type="button" className="home-brand" onClick={() => navigate('/')} aria-label="FitScholars home">
            <BrandLogo height={60} alt="" />
          </button>
          <nav className="home-nav" aria-label="Home navigation">
            {navLinks.map(([label, href]) => <a key={href} className="home-nav-link" href={href}>{label}</a>)}
          </nav>
          <div className="home-header-actions">
            <button type="button" className="home-text-button" onClick={() => navigate('/login')}>Log in</button>
            <button type="button" className="home-pill home-pill-outline" onClick={() => navigate('/register')}>Get started</button>
          </div>
        </div>
      </header>

      <main>
        {/* ---------- Hero ---------- */}
        <section className="home-hero" aria-labelledby="home-hero-title">
          {/* Diagonal band + blob, like the reference's orange band and purple shape */}
          <svg className="home-hero-band" viewBox="0 0 1440 520" preserveAspectRatio="none" aria-hidden="true">
            <path d="M0 470 L1080 150 C1200 112 1290 140 1340 230 L1440 420 L1440 520 L0 520 Z" />
          </svg>

          <div className="home-hero-inner">
            <div className="home-hero-copy">
              <h1 id="home-hero-title">
                Find your<br />scholarship<br />opportunities.
              </h1>
              <p className="home-hero-subtitle">
                Scholarship opportunities and funding information matched to your profile.
              </p>
              <div className="home-hero-actions">
                <button type="button" className="home-pill home-pill-dark" onClick={() => navigate('/register')}>
                  Get started
                </button>
                <a className="home-pill home-pill-outline" href="#how-it-works">Learn more</a>
              </div>

              <div className="home-hero-count">
                Scholarship eligibility · Funding · Preparation
              </div>
            </div>

            <div className="home-hero-visual">
              <svg className="home-ring-text" viewBox="0 0 500 500" aria-hidden="true">
                <defs>
                  <path id="home-ring-path" d="M250 250 m-212 0 a212 212 0 1 1 424 0 a212 212 0 1 1 -424 0" />
                </defs>
                <text>
                  <textPath href="#home-ring-path" startOffset="0" textLength="1325" lengthAdjust="spacing">
                    SCHOLARSHIPS • ELIGIBILITY CHECKS • FUNDING • PREPARATION •
                  </textPath>
                </text>
              </svg>
              <span className="home-hero-blob" aria-hidden="true" />
              <div className="home-hero-portrait">
                <img src="/images/graduation-students.jpg" alt="Graduates throwing their caps in the air" fetchPriority="high" />
              </div>

            </div>
          </div>

        </section>

        {/* ---------- About ---------- */}
        <section id="about" className="home-section home-about" aria-labelledby="home-about-title">
          <div ref={aboutVisualRef} className={`home-about-visual ${aboutVisualVisible ? 'is-visible' : ''}`}>
            <Doodle className="home-doodle home-doodle-about" />
            <div className="home-about-photo">
              <img src="/images/campus-building.jpg" alt="University campus building" loading="lazy" />
            </div>
          </div>
          <div className="home-about-copy">
            <h2 id="home-about-title">Plan your studies abroad with confidence</h2>
            <p>
              Scholarship information can be difficult to compare. FitScholar brings recorded requirements,
              funding, source status, and deadlines together, then explains how your profile compares.
            </p>
            <ul className="home-checklist">
              {aboutPoints.map((point) => (
                <li key={point}><span aria-hidden="true"><CheckCircle2 size={14} /></span>{point}</li>
              ))}
            </ul>
            <button type="button" className="home-button home-button-dark" onClick={() => navigate('/register')}>
              Create Free Profile <ArrowRight size={17} aria-hidden="true" />
            </button>
          </div>
        </section>

        {/* ---------- How it works ---------- */}
        <section id="how-it-works" className="home-section" aria-labelledby="home-steps-title">
          <div className="home-section-heading">
            <h2 id="home-steps-title">Three steps to your shortlist</h2>
            <p>From profile to application in one guided journey.</p>
          </div>
          <ol className="home-steps">
            {steps.map(({ icon: Icon, title, text }, index) => (
              <li key={title} className="home-step">
                <span className="home-step-number">0{index + 1}</span>
                <span className="home-step-icon" aria-hidden="true"><Icon size={26} /></span>
                <h3>{title}</h3>
                <p>{text}</p>
                <span className="home-step-tag">Step {index + 1}</span>
              </li>
            ))}
          </ol>
        </section>

        {/* ---------- CTA band ---------- */}
        <section className="home-cta-wrap" aria-labelledby="home-cta-title">
          <div className="home-cta">
            <h2 id="home-cta-title">Understand scholarship requirements, funding, and preparation steps.</h2>
            <button type="button" className="home-button home-button-light home-button-small" onClick={() => navigate('/register')}>
              Get Started
            </button>
          </div>
        </section>

        {/* ---------- FAQ (replaces the blog) ---------- */}
        <section id="faq" className="home-section home-faq" aria-labelledby="home-faq-title">
          <div className="home-section-heading">
            <h2 id="home-faq-title">Questions students ask us</h2>
          </div>
          <div className="home-faq-list">
            {faqs.map(({ q, a }, index) => (
              <details key={q} className="home-faq-item" open={index === 0}>
                <summary>{q}<ChevronDown size={18} aria-hidden="true" /></summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </section>
      </main>

      {/* ---------- Footer ---------- */}
      <footer className="home-footer">
        <div className="home-footer-inner">
          <div className="home-footer-brand">
            <BrandLogo tone="light" height={56} />
            <p>Study Abroad &amp; Scholarship Decision Support System</p>
          </div>
          <nav className="home-footer-links" aria-label="Footer navigation">
            {navLinks.map(([label, href]) => <a key={href} href={href}>{label}</a>)}
          </nav>
        </div>
        <p className="home-footer-note">
          © {new Date().getFullYear()} FitScholars. Confirm scholarship requirements, funding, and deadlines with the official provider.
        </p>
      </footer>
    </div>
  );
}
