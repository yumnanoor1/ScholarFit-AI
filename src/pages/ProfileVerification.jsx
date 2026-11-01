import { useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import FormLayout01 from '../components/profile/AcademicForm';
import { useProfile } from '../context/ProfileContext';
import { LAST_PROFILE_STEP } from '../data/profileModel';
import { HOME_PATH, PROFILE_DONE_PATH } from '../services/profileAccess';

export default function ProfileVerification() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { completion, profile, updateProfile, loading } = useProfile();
  const [saveError, setSaveError] = useState('');
  const [isFirstCompletion] = useState(() => !completion.complete);

  // Checked once, on arrival: a draft saved during this review can finish the profile on the server
  if (!isFirstCompletion) return <Navigate to={HOME_PATH} replace />;
  if (!profile.extractedProfile) return <Navigate to="/profile-setup/cv" replace />;
  const stepParam = searchParams.get('step');
  const savedStep = stepParam === null ? null : Number(stepParam);
  const initialStep = savedStep !== null && Number.isInteger(savedStep)
    ? Math.min(Math.max(savedStep, 0), LAST_PROFILE_STEP)
    : profile.profileSetupStep || 0;

  const handleSave = async (draft, progress) => {
    setSaveError('');
    try {
      const result = await updateProfile(draft, { ...progress, source: 'cv' });
      if (result?.success) return true;
      setSaveError(result?.error || 'Your progress could not be saved. Please try again.');
      return false;
    } catch (error) {
      setSaveError(error?.message || 'Your progress could not be saved. Please try again.');
      return false;
    }
  };

  return (
    <FormLayout01
      onSave={handleSave}
      onComplete={() => navigate(PROFILE_DONE_PATH, { replace: true, state: { justCompleted: true } })}
      onStepChange={(step) => setSearchParams({ step: String(step) }, { replace: true })}
      onGenerateRecommendations={() => navigate('/recommendations')}
      initialValues={profile.profileDraft || profile.extractedProfile}
      initialStep={initialStep}
      isProfileComplete={profile.profileComplete || false}
      isSaving={loading}
      saveError={saveError}
      verificationMode
      requiresReviewConfirmation
      fieldStatuses={profile.fieldStatuses || profile.extractionFieldStatuses || {}}
      finalButtonLabel="Confirm & Save Profile"
    />
  );
}