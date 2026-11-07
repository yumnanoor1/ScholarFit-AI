/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useAuth } from './AuthContext';
import { EMPTY_PROFILE } from '../data/profileModel';
import {
  ACTIVE_OPPORTUNITY_KEY,
  COMPARISON_OPPORTUNITIES_KEY,
  DOCUMENT_RECORDS_KEY,
  SAVED_OPPORTUNITIES_KEY,
  SELECTED_OPPORTUNITIES_KEY,
  readOpportunityData,
  readSavedLocally,
  readUserProfile,
  writeUserProfile,
  writeUserStorage,
} from '../services/userStorage';
import {
  createSavedQueue,
  dismissRemovedSaves,
  forgetLocalSave,
  forgetSavedRecord,
  getSaveErrorMessage,
  isBackendSavedId,
  loadSavedOpportunities,
  rememberSavedRecord,
  removeSavedScholarship,
  saveScholarship,
} from '../services/savedScholarshipsApi';
import {
  getProfileApi,
  getProfileStatusApi,
  createProfileApi,
  updateProfileApi,
  mapFrontendToBackendProfile,
  mapBackendToFrontendProfile,
} from '../services/profileApi';
import { FAILED_COMPLETION, LOADING_COMPLETION, canUseApp } from '../services/profileAccess';

export const ProfileContext = createContext(null);

const DEFAULT_PROFILE = {
  ...EMPTY_PROFILE,
  name: "",
  degree: "",
  degreeLevel: "",
  university: "",
  cgpa: "",
  graduationYear: "",
  englishTest: "",
  englishScore: "",
  skills: [],
  projects: [],
  researchExperience: "",
  fieldOfInterest: "",
  preferredCountries: [],
  preferredDegree: "Master's",
  fundingPreference: "",
  approximateBudget: "",
  profileCompletionPercentage: 0,
  profileSetupStep: 0,
  profileComplete: false,
};

function readSavedProfile(userId) {
  const savedProfile = readUserProfile(userId);
  return savedProfile ? { ...DEFAULT_PROFILE, ...savedProfile } : DEFAULT_PROFILE;
}

/** The saved profile with the API's status applied, which replaces whatever the browser had stored. */
function withCompletion(profile, status) {
  return {
    ...profile,
    profileComplete: status.complete,
    profileStatus: status.complete ? 'complete' : 'draft',
    profileCompletionPercentage: status.percent,
    verifiedProfile: status.complete ? profile.verifiedProfile : null,
  };
}

function getPreferredCountries(value) {
  const countries = Array.isArray(value) ? value : String(value || '').split(',');
  return countries.map((country) => country.trim().toLowerCase()).filter(Boolean);
}

export function ProfileProvider({ children }) {
  const { user, token } = useAuth();
  const userId = user?.id;
  const userName = user?.name || '';
  const userFullName = user?.full_name || '';
  const userEmail = user?.email || '';
  const [profile, setProfile] = useState(() => readSavedProfile(user?.id));
  const [hasBackendProfile, setHasBackendProfile] = useState(false);
  // Kept with the sign-in it belongs to, so a new sign-in is never judged by the previous one's status
  const [knownCompletion, setKnownCompletion] = useState({ token: null, value: LOADING_COMPLETION });
  const completion = knownCompletion.token === token ? knownCompletion.value : LOADING_COMPLETION;
  const appUnlocked = canUseApp(completion);
  const [initialData] = useState(() => readOpportunityData(userId));
  const [dataOwnerId, setDataOwnerId] = useState(userId);
  const [savedOpportunities, setSavedOpportunities] = useState(initialData.savedOpportunities);
  const [savedRecords, setSavedRecords] = useState(initialData.savedRecords);
  const [hasSavedSnapshot, setHasSavedSnapshot] = useState(initialData.hasSavedSnapshot);
  const [removedSaves, setRemovedSaves] = useState(initialData.removedSaves);
  const [savedStatus, setSavedStatus] = useState(token ? 'loading' : 'ready'); // loading | ready | error
  const [savedReloadCount, setSavedReloadCount] = useState(0);
  const [saveError, setSaveError] = useState('');
  const [comparisonOpportunityIds, setComparisonOpportunityIds] = useState(initialData.comparisonOpportunityIds);
  const [selectedOpportunities, setSelectedOpportunities] = useState(initialData.selectedOpportunities);
  const [activeOpportunityId, setActiveOpportunityId] = useState(initialData.activeOpportunityId);
  const [documentRecords, setDocumentRecords] = useState(initialData.documentRecords);
  const [loading, setLoading] = useState(false);

  // Swap during render, not in an effect, so the screen never shows the previous account's data
  if (dataOwnerId !== userId) {
    const data = readOpportunityData(userId);
    setDataOwnerId(userId);
    setProfile(readSavedProfile(userId));
    setHasBackendProfile(false);
    setSavedOpportunities(data.savedOpportunities);
    setSavedRecords(data.savedRecords);
    setHasSavedSnapshot(data.hasSavedSnapshot);
    setRemovedSaves(data.removedSaves);
    setSavedStatus(userId == null ? 'ready' : 'loading');
    setSaveError('');
    setComparisonOpportunityIds(data.comparisonOpportunityIds);
    setSelectedOpportunities(data.selectedOpportunities);
    setActiveOpportunityId(data.activeOpportunityId);
    setDocumentRecords(data.documentRecords);
  }

  // Saves can finish after the account changed; their result must not reach the new account
  const signedInUserId = useRef(userId);
  useEffect(() => {
    signedInUserId.current = userId;
  }, [userId]);
  const isStillSignedIn = () => userId != null && signedInUserId.current === userId;

  // Saved scholarships come from the database; a failed load keeps the last confirmed list on screen.
  // Each account has its own queue, so a slow request can't hold up or overwrite another account.
  const savedSync = useRef({ ownerId: undefined });
  const getSavedSync = (ownerId) => {
    if (savedSync.current.ownerId !== ownerId) {
      savedSync.current = { ownerId, enqueue: createSavedQueue(), inProgress: new Set() };
    }
    return savedSync.current;
  };
  useEffect(() => {
    // The API refuses this until the profile is finished
    if (!token || userId == null || !appUnlocked) return undefined;
    let isCurrent = true;
    getSavedSync(userId).enqueue(() => loadSavedOpportunities(token, userId))
      .then(({ ids, records, removed }) => {
        if (!isCurrent) return;
        setSavedOpportunities(ids);
        setSavedRecords(records);
        setHasSavedSnapshot(true);
        setRemovedSaves(removed);
        setSavedStatus('ready');
      })
      .catch((error) => {
        console.warn('Unable to load saved scholarships:', error?.message);
        if (isCurrent) setSavedStatus('error');
      });
    return () => {
      isCurrent = false;
    };
  }, [userId, token, savedReloadCount, appUnlocked]);

  useEffect(() => {
    if (!saveError) return undefined;
    const timer = setTimeout(() => setSaveError(''), 6000);
    return () => clearTimeout(timer);
  }, [saveError]);

  const retrySavedOpportunities = () => {
    if (savedStatus === 'loading') return;
    setSavedStatus('loading');
    setSavedReloadCount((count) => count + 1);
  };

  const dismissRemovedSavedScholarships = () => {
    dismissRemovedSaves(userId);
    setRemovedSaves([]);
  };

  // Fetch the authenticated student's profile from the backend on login / token availability
  useEffect(() => {
    let isCurrent = true;

    if (!token || userId == null) return;

    const cachedDraft = readSavedProfile(userId);
    const profileUser = { id: userId, name: userName, full_name: userFullName, email: userEmail };

    Promise.all([getProfileApi(token), getProfileStatusApi(token)])
      .then(([{ exists, data }, status]) => {
        if (!isCurrent) return;

        setKnownCompletion({ token, value: { ...status, status: 'ready' } });

        if (exists && data) {
          setHasBackendProfile(true);
          const mappedProfile = mapBackendToFrontendProfile(data, profileUser);
          const nextProfile = withCompletion({
            ...mappedProfile,
            profileDraft: cachedDraft.unsyncedDraft && cachedDraft.profileDraft?.personalInfo
              ? cachedDraft.profileDraft
              : mappedProfile.verifiedProfile,
            unsyncedDraft: Boolean(cachedDraft.unsyncedDraft),
          }, status);
          setProfile(nextProfile);
          writeUserProfile(userId, nextProfile);
        } else {
          // 404: Profile not yet created in PostgreSQL
          setHasBackendProfile(false);

          // Populate with user identity or existing in-progress local draft
          if (cachedDraft && (cachedDraft.profileComplete || cachedDraft.profileSetupStep > 0 || cachedDraft.extractedProfile)) {
            setProfile(withCompletion(cachedDraft, status));
          } else {
            const initial = {
              ...DEFAULT_PROFILE,
              name: userName || userFullName,
              email: userEmail,
              personalInfo: {
                ...DEFAULT_PROFILE.personalInfo,
                fullName: userName || userFullName,
                email: userEmail,
              },
            };
            setProfile(initial);
            writeUserProfile(userId, initial);
          }
        }
      })
      .catch((err) => {
        console.warn('Unable to reach backend profile endpoint:', err?.message);
        if (isCurrent) setKnownCompletion({ token, value: FAILED_COMPLETION });
      });

    return () => {
      isCurrent = false;
    };
  }, [userId, userName, userFullName, userEmail, token]);

  const refreshCompletion = async () => {
    const status = await getProfileStatusApi(token);
    if (isStillSignedIn()) setKnownCompletion({ token, value: { ...status, status: 'ready' } });
    return status;
  };

  const saveCvUpload = (fileInfo) => {
    if (!isStillSignedIn()) return;
    setProfile((current) => {
      const nextProfile = { ...current, cvUpload: fileInfo };
      writeUserProfile(userId, nextProfile);
      return nextProfile;
    });
  };

  const saveExtractedProfile = ({ extractedProfile, fieldStatuses, fileInfo }) => {
    if (!isStillSignedIn()) return;
    setProfile((current) => {
      const nextProfile = {
        ...current,
        ...extractedProfile,
        cvUpload: fileInfo,
        extractedProfile,
        profileDraft: extractedProfile,
        extractionFieldStatuses: fieldStatuses,
        fieldStatuses,
        profileMethod: 'cv',
        profileSetupStep: 0,
        profileComplete: false,
        profileCompletionPercentage: 0,
        verifiedProfile: null,
      };
      writeUserProfile(userId, nextProfile);
      return nextProfile;
    });
  };

  const updateProfile = async (updatedData, progress = { step: 0, complete: false }) => {
    if (!isStillSignedIn()) {
      return { success: false, error: 'Please sign in to save your profile.' };
    }
    setLoading(true);

    try {
      const personal = updatedData.personalInfo || {};
      const academic = updatedData.academicBackground || {};
      const english = updatedData.englishProficiency || {};
      const preferences = updatedData.studyPreferences || {};
      const fullName = personal.fullName || profile.name || user?.name || '';
      const preferredCountries = [
        ...(preferences.countries || []).filter((country) => country !== 'Other'),
        ...(preferences.otherCountry ? [preferences.otherCountry] : [])
      ];
      const chosenFunding = preferences.fundingPreferences || [];
      const overallScore = english.overallScore ?? '';
      const legacyEnglishTest = english.testType === 'TOEFL iBT' ? 'TOEFL' : english.testType || profile.englishTest;
      const graduationDate = academic.academicStatus === 'graduated'
        ? academic.graduationDate
        : academic.expectedGraduationDate;
      const approximateBudget = preferences.maxTuitionBudget !== undefined
        ? preferences.maxTuitionBudget === '' || preferences.maxTuitionBudget === null
          ? ''
          : `${preferences.currency || 'USD'} ${preferences.maxTuitionBudget} / year`
        : profile.approximateBudget;
      const targetFields = [
        ...(preferences.fields || []).filter((field) => field !== 'Other'),
        ...(preferences.customField ? [preferences.customField] : []),
      ];
      const isCvSource = progress.source === 'cv';

      const finalProfile = {
        ...profile,
        ...updatedData,
        name: fullName,
        firstName: fullName.split(' ')[0] || '',
        lastName: fullName.split(' ').slice(1).join(' '),
        email: personal.email || profile.email || user?.email || '',
        degree: academic.degreeTitle || academic.major || profile.degree,
        degreeLevel: academic.currentDegree || profile.degreeLevel,
        university: academic.institution || profile.university,
        cgpa: academic.cgpa !== undefined ? academic.cgpa : profile.cgpa,
        graduationYear: graduationDate || academic.currentYear || profile.graduationYear,
        englishTest: legacyEnglishTest,
        englishScore: english.testType === 'No Test / Not Taken'
          ? ''
          : english.overallScore !== undefined ? overallScore : profile.englishScore,
        fieldOfInterest: preferences.fields !== undefined
          ? targetFields.join(', ')
          : profile.fieldOfInterest,
        skills: [academic.technicalSkills, academic.programmingLanguages].filter(Boolean).join(', ').split(',').map((skill) => skill.trim()).filter(Boolean),
        projects: academic.projects !== undefined
          ? String(academic.projects || '').split(',').map((project) => project.trim()).filter(Boolean)
          : profile.projects,
        preferredCountries: preferences.countries ? preferredCountries : getPreferredCountries(profile.preferredCountries),
        preferredDegree: preferences.intendedDegree || preferences.preferredDegreeLevels?.[0] || profile.preferredDegree || '',
        fundingPreference: preferences.fundingPreference || profile.fundingPreference,
        fundingPreferences: chosenFunding,
        approximateBudget,
        profileCompletionPercentage: profile.profileCompletionPercentage,
        profileSetupStep: progress.complete ? 0 : progress.step + 1,
        profileComplete: profile.profileComplete,
        profileStatus: profile.profileStatus,
        profileMethod: isCvSource ? 'cv' : 'manual',
        cvUpload: isCvSource ? profile.cvUpload || null : null,
        extractedProfile: isCvSource ? profile.extractedProfile || null : null,
        extractionFieldStatuses: isCvSource ? profile.extractionFieldStatuses || {} : {},
        profileDraft: updatedData,
        fieldStatuses: progress.fieldStatuses || (isCvSource ? profile.fieldStatuses || {} : {}),
        verifiedProfile: progress.complete ? updatedData : profile.verifiedProfile,
      };

      let persisted = false;
      const currentUser = {
        name: user?.name || user?.full_name || '',
        full_name: user?.full_name || '',
        email: user?.email || '',
      };
      const applyPersistedResponse = (response) => {
        Object.assign(finalProfile, mapBackendToFrontendProfile(response, currentUser));
        persisted = true;
      };

      if (progress.complete) {
        if (token) {
          const backendPayload = mapFrontendToBackendProfile(updatedData, profile);

          if (hasBackendProfile) {
            applyPersistedResponse(await updateProfileApi(token, backendPayload));
          } else {
            try {
              applyPersistedResponse(await createProfileApi(token, backendPayload));
              if (isStillSignedIn()) setHasBackendProfile(true);
            } catch (createErr) {
              // If it already exists on server, gracefully switch to PUT update
              if (createErr.status === 400 && String(createErr.message).includes('already exists')) {
                applyPersistedResponse(await updateProfileApi(token, backendPayload));
                if (isStillSignedIn()) setHasBackendProfile(true);
              } else {
                throw createErr;
              }
            }
          }

          finalProfile.hasBackendProfile = true;
          // Finishing is the API's decision, made from what it stored
          let status;
          try {
            status = await refreshCompletion();
          } catch (statusError) {
            delete finalProfile.unsyncedDraft;
            writeUserProfile(userId, finalProfile);
            if (isStillSignedIn()) setProfile(finalProfile);
            return {
              success: false,
              persisted: true,
              error: `Your profile was saved, but its completion status could not be refreshed: ${statusError?.message || 'Please try again.'}`,
            };
          }
          Object.assign(finalProfile, withCompletion(finalProfile, status));
          if (status.required && !status.complete) {
            writeUserProfile(userId, finalProfile);
            if (isStillSignedIn()) setProfile(finalProfile);
            return {
              success: false,
              incomplete: true,
              error: `Your profile was saved, but still needs: ${status.missing.join(', ')}.`,
            };
          }
        }
      } else if (hasBackendProfile && token) {
        const backendPayload = mapFrontendToBackendProfile(updatedData, profile);
        applyPersistedResponse(await updateProfileApi(token, backendPayload));
        try {
          Object.assign(finalProfile, withCompletion(finalProfile, await refreshCompletion()));
        } catch (statusError) {
          delete finalProfile.unsyncedDraft;
          writeUserProfile(userId, finalProfile);
          if (isStillSignedIn()) setProfile(finalProfile);
          return {
            success: false,
            persisted: true,
            error: `Your changes were saved, but profile completion could not be refreshed: ${statusError?.message || 'Please try again.'}`,
          };
        }
      }

      if (!persisted) finalProfile.unsyncedDraft = true;
      else delete finalProfile.unsyncedDraft;
      writeUserProfile(userId, finalProfile);
      if (isStillSignedIn()) setProfile(finalProfile);

      return {
        success: true,
        persisted,
        profile: finalProfile,
      };
    } catch (err) {
      const unsyncedDraft = {
        ...profile,
        profileDraft: updatedData,
        unsyncedDraft: true,
      };
      writeUserProfile(userId, unsyncedDraft);
      if (isStillSignedIn()) setProfile(unsyncedDraft);
      console.error('Failed to save profile:', err?.message);
      return {
        success: false,
        error: err?.message || 'Your profile could not be saved. Please try again.',
      };
    } finally {
      setLoading(false);
    }
  };

  const toggleSaveOpportunity = async (id) => {
    if (!isStillSignedIn()) return;
    const removing = savedOpportunities.includes(id);

    if (!isBackendSavedId(id)) {
      const local = readSavedLocally(userId);
      writeUserStorage(SAVED_OPPORTUNITIES_KEY, userId, removing ? local.filter((savedId) => savedId !== id) : [...local, id]);
      setSavedOpportunities((prev) => (removing ? prev.filter((savedId) => savedId !== id) : [...prev, id]));
      return;
    }

    // The bookmark changes only after the database confirms it
    const { enqueue, inProgress } = getSavedSync(userId);
    if (inProgress.has(id)) return;
    inProgress.add(id);
    const dropSaved = () => {
      forgetLocalSave(userId, id);
      forgetSavedRecord(userId, id);
      if (!isStillSignedIn()) return;
      setSavedOpportunities((prev) => prev.filter((savedId) => savedId !== id));
      setSavedRecords((prev) => prev.filter((record) => `sch-db-${record.scholarship_id}` !== id));
    };
    try {
      const record = await enqueue(() => (removing ? removeSavedScholarship : saveScholarship)(token, id));
      if (removing) {
        dropSaved();
      } else {
        rememberSavedRecord(userId, record);
        if (isStillSignedIn()) {
          setSavedOpportunities((prev) => [...new Set([...prev, id])]);
          setSavedRecords((prev) => [...prev.filter((item) => item.scholarship_id !== record.scholarship_id), record]);
        }
      }
      if (isStillSignedIn()) setSaveError('');
    } catch (error) {
      console.warn('Unable to update saved scholarship:', error?.message);
      if (error?.status === 404) dropSaved(); // deleted, so it can't stay bookmarked
      if (isStillSignedIn()) setSaveError(getSaveErrorMessage(error, removing));
    } finally {
      inProgress.delete(id);
    }
  };

  const isOpportunitySaved = (id) => {
    return savedOpportunities.includes(id);
  };

  const toggleComparisonOpportunity = (id) => {
    if (typeof id !== 'string' || !id) {
      throw new Error('A comparison opportunity must have a stable ID.');
    }
    if (!/^sch-db-\d+$/.test(id)) throw new Error('Only persisted scholarships can be compared.');
    setComparisonOpportunityIds((current) => {
      const next = current.includes(id)
        ? current.filter((selectedId) => selectedId !== id)
        : current.length < 2
          ? [...current, id]
          : current;
      if (next !== current) writeUserStorage(COMPARISON_OPPORTUNITIES_KEY, userId, next);
      return next;
    });
  };

  const clearComparisonOpportunities = () => {
    writeUserStorage(COMPARISON_OPPORTUNITIES_KEY, userId, []);
    setComparisonOpportunityIds([]);
  };

  const activeOpportunity = selectedOpportunities.find((item) => item.id === activeOpportunityId) || null;
  const profileWithAccount = profile.name ? profile : {
    ...profile,
    name: user?.name || '',
    firstName: user?.name?.trim().split(/\s+/)[0] || '',
    email: user?.email || '',
  };

  const selectOpportunity = (opportunity) => {
    if (!opportunity || typeof opportunity.id !== 'string' || !/^sch-db-\d+$/.test(opportunity.id)) {
      throw new Error('Only a persisted scholarship can be selected for preparation.');
    }
    const snapshot = { ...opportunity, kind: 'scholarship' };
    const next = selectedOpportunities.some((item) => item.id === snapshot.id)
      ? selectedOpportunities.map((item) => item.id === snapshot.id ? snapshot : item)
      : [...selectedOpportunities, snapshot];
    writeUserStorage(SELECTED_OPPORTUNITIES_KEY, userId, next);
    setSelectedOpportunities(next);
    setActiveOpportunityId(snapshot.id);
    writeUserStorage(ACTIVE_OPPORTUNITY_KEY, userId, snapshot.id);
  };

  const setActiveOpportunity = (id) => {
    if (id !== null && !selectedOpportunities.some((item) => item.id === id)) {
      throw new Error('Only a selected opportunity can become active.');
    }
    setActiveOpportunityId(id);
    writeUserStorage(ACTIVE_OPPORTUNITY_KEY, userId, id);
  };

  const removeSelectedOpportunity = (id) => {
    const next = selectedOpportunities.filter((item) => item.id !== id);
    writeUserStorage(SELECTED_OPPORTUNITIES_KEY, userId, next);
    setSelectedOpportunities(next);
    if (activeOpportunityId === id) setActiveOpportunity(null);
  };

  // Stores file metadata only; file contents must go to backend storage. One record per document ID, shared by all opportunities.
  const saveDocumentRecord = (documentId, file) => {
    const previous = documentRecords[documentId];
    const record = {
      fileName: file.name,
      fileSize: file.size,
      uploadedAt: new Date().toISOString(),
      replacedCount: previous ? (previous.replacedCount || 0) + 1 : 0,
      status: 'awaiting-verification',
    };
    const next = { ...documentRecords, [documentId]: record };
    writeUserStorage(DOCUMENT_RECORDS_KEY, userId, next);
    setDocumentRecords(next);
  };

  const removeDocumentRecord = (documentId) => {
    const next = { ...documentRecords };
    delete next[documentId];
    writeUserStorage(DOCUMENT_RECORDS_KEY, userId, next);
    setDocumentRecords(next);
  };

  return (
    <ProfileContext.Provider value={{
      documentRecords,
      saveDocumentRecord,
      removeDocumentRecord,
      profile: profileWithAccount,
      completion,
      loading,
      hasBackendProfile,
      updateProfile,
      saveCvUpload,
      saveExtractedProfile,
      savedOpportunities,
      savedRecords,
      hasSavedSnapshot,
      removedSaves,
      dismissRemovedSavedScholarships,
      savedStatus,
      retrySavedOpportunities,
      toggleSaveOpportunity,
      isOpportunitySaved,
      comparisonOpportunityIds,
      toggleComparisonOpportunity,
      clearComparisonOpportunities,
      selectedOpportunities,
      activeOpportunityId,
      activeOpportunity,
      selectOpportunity,
      setActiveOpportunity,
      removeSelectedOpportunity,
    }}>
      {children}
      {saveError && <p className="save-error-notice" role="alert">{saveError}</p>}
    </ProfileContext.Provider>
  );
}

export function useProfile() {
  const context = useContext(ProfileContext);
  if (!context) {
    throw new Error('useProfile must be used within a ProfileProvider');
  }
  return context;
}
