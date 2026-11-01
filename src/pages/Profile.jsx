import { useState } from 'react';
import {
  CheckCircle2, Compass, GraduationCap, Languages, Mail, Pencil, Sparkles, UserRound,
} from 'lucide-react';
import FormLayout01 from '../components/profile/AcademicForm';
import { EMPTY_PROFILE, LAST_PROFILE_STEP, mergeProfile } from '@/data/profileModel';
import { ONBOARDING_PATH, PROFILE_DONE_PATH } from '../services/profileAccess';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { GlowCard } from '../components/ui/spotlight-card';
import { ProfileMissingNotice, ProfileSavedNotice } from '../components/profile/ProfileNotices';
import './Profile.css';

const sectionTitles = [
  'Personal Information',
  'Academic Background',
  'English Test Scores',
  'Study Preferences',
];

const sectionIcons = [UserRound, GraduationCap, Languages, Compass];

const NOT_PROVIDED = 'Not provided';

function displayValue(value) {
  if (Array.isArray(value)) return value.length ? value.join(', ') : NOT_PROVIDED;
  if (value === null || value === undefined || value === '') return NOT_PROVIDED;
  if (typeof value === 'object' && 'name' in value) return value.name;
  return String(value);
}

function getInitials(name) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  return parts.slice(0, 2).map((part) => part[0].toUpperCase()).join('');
}

function ProfileSection({ index, items, onEdit }) {
  const Icon = sectionIcons[index];
  const title = sectionTitles[index];
  const provided = items.filter(([, value]) => displayValue(value) !== NOT_PROVIDED).length;
  return (
    <GlowCard as="section" customSize className="profile-summary-section" aria-labelledby={`profile-section-${index}`}>
      <header className="profile-summary-section-header">
        <span className="profile-summary-section-icon" aria-hidden="true"><Icon size={18} /></span>
        <div className="profile-summary-section-copy">
          <h2 id={`profile-section-${index}`}>{title}</h2>
          <p>{provided} of {items.length} fields provided</p>
        </div>
        <button type="button" className="profile-summary-edit" onClick={onEdit} aria-label={`Edit ${title}`}>
          <Pencil size={14} aria-hidden="true" /> Edit
        </button>
      </header>
      <dl className="profile-summary-fields">
        {items.map(([label, value]) => {
          const text = displayValue(value);
          return (
            <div key={label} className="profile-summary-field">
              <dt>{label}</dt>
              <dd className={text === NOT_PROVIDED ? 'is-empty' : ''}>{text}</dd>
            </div>
          );
        })}
      </dl>
    </GlowCard>
  );
}

export default function Profile() {
  const { user } = useAuth();
  const { completion, profile, updateProfile, loading } = useProfile();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [saveError, setSaveError] = useState('');
  // Decided on arrival: a draft saved during onboarding can finish the profile on the server
  const [isFirstCompletion] = useState(() => !completion.complete);
  const isEditing = searchParams.get('edit') === '1';
  const returnTo = location.state?.returnTo || '/profile';
  const isCvEdit = searchParams.get('method') !== 'manual' && profile.profileMethod === 'cv';

  const handleSaveProfile = async (formData, progress) => {
    setSaveError('');
    try {
      const result = await updateProfile(formData, progress);
      if (result?.success) return true;
      // An edit that left the profile unfinished: onboarding explains what's missing
      if (result?.incomplete && !isFirstCompletion) {
        navigate(ONBOARDING_PATH, { replace: true });
        return false;
      }
      setSaveError(result?.error || 'Your profile could not be saved. Please try again.');
      return false;
    } catch (error) {
      setSaveError(error?.message || 'Your profile could not be saved. Please try again.');
      return false;
    }
  };

  const savedValues = profile.verifiedProfile || profile.profileDraft;
  const initialValues = savedValues?.personalInfo ? savedValues : mergeProfile({
    personalInfo: {
      ...EMPTY_PROFILE.personalInfo,
      fullName: user?.name || '',
      email: user?.email || '',
    },
  });

  if (profile.profileComplete && !isEditing) {
    const completedProfile = profile.verifiedProfile || profile;
    const personal = completedProfile.personalInfo || {};
    const academic = completedProfile.academicBackground || {};
    const english = completedProfile.englishProficiency || {};
    const preferences = completedProfile.studyPreferences || {};
    const editSection = (index) => navigate(`/profile?edit=1&step=${index}`);
    const fullName = personal.fullName || user?.name || '';
    const cgpaText = academic.cgpa && academic.gradingScale ? `${academic.cgpa} / ${academic.gradingScale}` : academic.cgpa;
    const hasEnglishScore = english.testType && english.testType !== 'No Test / Not Taken' && english.overallScore;
    const highlights = [
      ['Current degree', academic.currentDegree],
      ['CGPA / GPA', cgpaText],
      ['English test', hasEnglishScore ? `${english.testType} · ${english.overallScore}` : english.testType],
      ['Preferred countries', [...(preferences.countries || []).filter((country) => country !== 'Other'), preferences.otherCountry].filter(Boolean)],
    ];

    return (
      <div className="page-container profile-summary-page">
        <ProfileSavedNotice />
        <header className="page-header profile-summary-header">
          <div className="page-header-copy">
            <h1 className="page-title">Profile Complete</h1>
            <p className="page-subtitle">Your Master's profile is ready. Review your information or generate recommendations.</p>
          </div>
          <div className="profile-summary-actions">
            <button type="button" className="profile-summary-edit" onClick={() => navigate('/profile?edit=1')}>
              <Pencil size={14} aria-hidden="true" /> Edit Profile
            </button>
            <button type="button" className="profile-summary-primary" onClick={() => navigate('/recommendations')}>
              <Sparkles size={16} aria-hidden="true" /> Generate My Recommendations
            </button>
          </div>
        </header>

        <GlowCard as="section" customSize className="profile-summary-hero" aria-label="Profile overview">
          <div className="profile-summary-identity">
            <span className="profile-summary-avatar" aria-hidden="true">{getInitials(fullName)}</span>
            <div className="profile-summary-identity-copy">
              <h2>{fullName || NOT_PROVIDED}</h2>
              <p><Mail size={14} aria-hidden="true" /> {personal.email || user?.email || NOT_PROVIDED}</p>
              {(academic.degreeTitle || academic.institution) && (
                <p><GraduationCap size={14} aria-hidden="true" /> {[academic.degreeTitle, academic.institution].filter(Boolean).join(' · ')}</p>
              )}
            </div>
            <div className="profile-summary-progress" aria-label="Profile completion 100%">
              <div className="profile-summary-progress-label">
                <span><CheckCircle2 size={15} aria-hidden="true" /> Profile Completion</span>
                <strong>100%</strong>
              </div>
              <div className="profile-summary-progress-track"><div className="profile-summary-progress-fill" /></div>
            </div>
          </div>
          <dl className="profile-summary-highlights">
            {highlights.map(([label, value]) => {
              const text = displayValue(value);
              return (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd className={text === NOT_PROVIDED ? 'is-empty' : ''}>{text}</dd>
                </div>
              );
            })}
          </dl>
        </GlowCard>

        <div className="profile-summary-sections">
          <ProfileSection index={0} onEdit={() => editSection(0)} items={[
            ['Full name', personal.fullName], ['Email address', personal.email], ['Date of birth', personal.dateOfBirth],
            ['Gender', personal.gender], ['Country of citizenship', personal.citizenshipCountry], ['Current country', personal.currentCountry],
            ['City', personal.city], ['Phone number', personal.phoneNumber], ['Profile photo', personal.profilePhoto],
          ]} />
          <ProfileSection index={1} onEdit={() => editSection(1)} items={[
            ['Current degree', academic.currentDegree], ['Degree title', academic.degreeTitle], ['Major / field', academic.major],
            ['University / institution', academic.institution], ['Institution country', academic.institutionCountry],
            ['Study status', academic.academicStatus], ['Current semester / year', academic.currentYear],
            ['CGPA / GPA', cgpaText],
            ['Expected graduation', academic.expectedGraduationDate], ['Graduation date', academic.graduationDate],
            ['Relevant coursework', academic.relevantCoursework], ['Technical skills', academic.technicalSkills],
            ['Programming languages', academic.programmingLanguages], ['Certifications', academic.certifications],
            ['Projects / academic experience', academic.projects], ['Work experience', academic.workExperience],
            ['Academic transcript', academic.transcript],
          ]} />
          <ProfileSection index={2} onEdit={() => editSection(2)} items={[
            ['English test', english.testType], ['Test name', english.otherTestName], ['Overall score', english.overallScore],
            ['Listening', english.listening], ['Reading', english.reading], ['Writing', english.writing],
            ['Speaking', english.speaking], ['Test date', english.testDate],
            ["Bachelor's taught in English", english.mediumOfInstruction], ['MOI certificate', english.moiCertificate],
          ]} />
          <ProfileSection index={3} onEdit={() => editSection(3)} items={[
            ["Preferred Master's fields", [...(preferences.fields || []), preferences.customField].filter(Boolean)],
            ['Preferred countries', [...(preferences.countries || []).filter((country) => country !== 'Other'), preferences.otherCountry].filter(Boolean)],
            ['Preferred regions', preferences.regions], ['Preferred intake', preferences.intake], ['Study mode', preferences.studyMode],
            ['Program preference', preferences.programPreference], ['Funding preference', preferences.fundingPreferences],
            ['Maximum tuition budget', preferences.maxTuitionBudget && `${preferences.currency} ${preferences.maxTuitionBudget}`],
            ['Maximum living cost budget', preferences.maxLivingCostBudget && `${preferences.currency} ${preferences.maxLivingCostBudget}`],
            ['Program duration', preferences.duration], ['Additional preferences', preferences.additionalPreferences],
          ]} />
        </div>
      </div>
    );
  }

  const stepParam = searchParams.get('step');
  const requestedStep = stepParam === null ? null : Number(stepParam);
  const initialStep = requestedStep !== null && Number.isInteger(requestedStep)
    ? Math.min(Math.max(requestedStep, 0), LAST_PROFILE_STEP)
    : isFirstCompletion ? profile.profileSetupStep || 0 : 0;

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '0', padding: '0' }}>
      <FormLayout01
        onSave={handleSaveProfile}
        onComplete={() => {
          if (isFirstCompletion) navigate(PROFILE_DONE_PATH, { replace: true, state: { justCompleted: true } });
          else navigate(returnTo, { replace: true, state: { profileSaved: true } });
        }}
        onCancel={isFirstCompletion ? undefined : () => navigate(returnTo, { replace: true })}
        onStepChange={(step) => {
          const nextParams = new URLSearchParams(searchParams);
          nextParams.set('edit', '1');
          nextParams.set('step', String(step));
          setSearchParams(nextParams, { replace: true, state: location.state });
        }}
        editing={!isFirstCompletion}
        completionPercent={completion.percent}
        notice={isFirstCompletion && <ProfileMissingNotice />}
        onGenerateRecommendations={() => navigate('/recommendations')}
        initialValues={initialValues}
        initialStep={initialStep}
        isProfileComplete={profile.profileComplete && !isEditing}
        isSaving={loading}
        saveError={saveError}
        verificationMode={isCvEdit}
        fieldStatuses={isCvEdit ? profile.fieldStatuses || {} : {}}
      />
    </div>
  );
}