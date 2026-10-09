import { useState } from 'react';
import FormLayout01 from '../components/profile/AcademicForm';
import { Button } from '@/components/ui/button';
import { EMPTY_PROFILE, mergeProfile } from '@/data/profileModel';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { GlowCard } from '../components/ui/spotlight-card';

const sectionTitles = [
  'Personal Information',
  'Academic Background',
  'English Test Scores',
  'Study Preferences',
];

function displayValue(value) {
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'Not provided';
  if (value === null || value === undefined || value === '') return 'Not provided';
  if (typeof value === 'object' && 'name' in value) return value.name;
  return String(value);
}

function ProfileSection({ title, items, onEdit }) {
  return (
    <GlowCard as="section" customSize className="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
        <Button type="button" variant="outline" size="sm" onClick={onEdit}>Edit</Button>
      </div>
      <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
        {items.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</dt>
            <dd className="mt-1 break-words text-sm text-slate-800 dark:text-slate-200">{displayValue(value)}</dd>
          </div>
        ))}
      </dl>
    </GlowCard>
  );
}

export default function Profile() {
  const { user } = useAuth();
  const { profile, updateProfile, loading } = useProfile();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [saveError, setSaveError] = useState('');
  const isEditing = searchParams.get('edit') === '1';
  const isCvEdit = searchParams.get('method') !== 'manual' && profile.profileMethod === 'cv';

  const handleSaveProfile = async (formData, progress) => {
    setSaveError('');
    try {
      const result = await updateProfile(formData, progress);
      if (result?.success) return true;
      setSaveError('Your profile could not be saved. Please try again.');
      return false;
    } catch {
      setSaveError('Your profile could not be saved. Please try again.');
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

    return (
      <div className="page-container" style={{ maxWidth: '1100px', paddingTop: '32px' }}>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="page-title">Profile Complete</h1>
            <p className="page-subtitle">Your Master's profile is ready. Review your information or generate recommendations.</p>
          </div>
          <Button onClick={() => navigate('/recommendations')}>Generate My Recommendations</Button>
        </div>
        <div className="mb-6 rounded-md border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/40">
          <div className="flex items-center justify-between text-sm font-medium text-emerald-900 dark:text-emerald-200">
            <span>Profile Completion</span><span>100%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-emerald-200 dark:bg-emerald-900">
            <div className="h-full w-full bg-emerald-700 dark:bg-emerald-400" />
          </div>
        </div>
        <div className="space-y-4">
          <ProfileSection title={sectionTitles[0]} onEdit={() => editSection(0)} items={[
            ['Full name', personal.fullName], ['Email address', personal.email], ['Date of birth', personal.dateOfBirth],
            ['Gender', personal.gender], ['Country of citizenship', personal.citizenshipCountry], ['Current country', personal.currentCountry],
            ['City', personal.city], ['Phone number', personal.phoneNumber], ['Profile photo', personal.profilePhoto],
          ]} />
          <ProfileSection title={sectionTitles[1]} onEdit={() => editSection(1)} items={[
            ['Current degree', academic.currentDegree], ['Degree title', academic.degreeTitle], ['Major / field', academic.major],
            ['University / institution', academic.institution], ['Institution country', academic.institutionCountry],
            ['Study status', academic.academicStatus], ['Current semester / year', academic.currentYear],
            ['CGPA / GPA', academic.cgpa && academic.gradingScale ? `${academic.cgpa} / ${academic.gradingScale}` : academic.cgpa],
            ['Expected graduation', academic.expectedGraduationDate], ['Graduation date', academic.graduationDate],
            ['Relevant coursework', academic.relevantCoursework], ['Technical skills', academic.technicalSkills],
            ['Programming languages', academic.programmingLanguages], ['Certifications', academic.certifications],
            ['Projects / academic experience', academic.projects], ['Academic transcript', academic.transcript],
          ]} />
          <ProfileSection title={sectionTitles[2]} onEdit={() => editSection(2)} items={[
            ['English test', english.testType], ['Test name', english.otherTestName], ['Overall score', english.overallScore],
            ['Listening', english.listening], ['Reading', english.reading], ['Writing', english.writing],
            ['Speaking', english.speaking], ['Test date', english.testDate],
            ["Bachelor's taught in English", english.mediumOfInstruction], ['MOI certificate', english.moiCertificate],
          ]} />
          <ProfileSection title={sectionTitles[3]} onEdit={() => editSection(3)} items={[
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
    ? Math.min(Math.max(requestedStep, 0), 3)
    : profile.profileSetupStep || 0;

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '0', padding: '0' }}>
      {saveError && (
        <p role="alert" style={{ maxWidth: '640px', margin: '0 auto 0.5rem', padding: '0 1.5rem', color: '#b42318' }}>
          {saveError}
        </p>
      )}
      <FormLayout01
        onSave={handleSaveProfile}
        onComplete={() => navigate('/profile')}
        onStepChange={(step) => {
          const nextParams = new URLSearchParams(searchParams);
          nextParams.set('edit', '1');
          nextParams.set('step', String(step));
          setSearchParams(nextParams, { replace: true });
        }}
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