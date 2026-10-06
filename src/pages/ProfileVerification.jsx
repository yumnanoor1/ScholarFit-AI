import { useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import FormLayout01 from '@/components/ui/form-2';
import { useProfile } from '../context/ProfileContext';

export default function ProfileVerification() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { profile, updateProfile, loading } = useProfile();
  const [saveError, setSaveError] = useState('');

  if (!profile.extractedProfile) return <Navigate to="/profile-setup/cv" replace />;
  const stepParam = searchParams.get('step');
  const savedStep = stepParam === null ? null : Number(stepParam);
  const initialStep = savedStep !== null && Number.isInteger(savedStep)
    ? Math.min(Math.max(savedStep, 0), 3)
    : profile.profileSetupStep || 0;

  const handleSave = async (draft, progress) => {
    setSaveError('');
    try {
      const result = await updateProfile(draft, { ...progress, source: 'cv' });
      if (result?.success) return true;
      setSaveError('Your progress could not be saved. Please try again.');
      return false;
    } catch {
      setSaveError('Your progress could not be saved. Please try again.');
      return false;
    }
  };

  return (
    <FormLayout01
      onSave={handleSave}
      onComplete={() => navigate('/profile')}
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