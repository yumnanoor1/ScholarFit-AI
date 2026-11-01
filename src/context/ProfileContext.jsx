/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useAuth } from './AuthContext';
import { EMPTY_PROFILE } from '../data/profileModel';
import { mockScholarships, mockUniversities } from '../data/mockData';
import { saveApplicationTaskStatuses } from '../services/applicationWorkflow';
import {
  ACTIVE_OPPORTUNITY_KEY,
  APPLIED_OPPORTUNITIES_KEY,
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
  createProfileApi,
  updateProfileApi,
  mapFrontendToBackendProfile,
  mapBackendToFrontendProfile,
} from '../services/profileApi';

const ProfileContext = createContext(null);

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

function getPreferredCountries(value) {
  const countries = Array.isArray(value) ? value : String(value || '').split(',');
  return countries.map((country) => country.trim().toLowerCase()).filter(Boolean);
}

function calculateMatchStatistics(profile) {
  const preferredCountries = getPreferredCountries(profile.preferredCountries);
  const preferredRegions = profile.studyPreferences?.regions || [];
  const hasProfileCriteria = profile.profileComplete ||
    Boolean(profile.cgpa || profile.englishScore || profile.fieldOfInterest || preferredCountries.length || preferredRegions.length);
  if (!hasProfileCriteria) {
    return { eligibleCount: 0, fundedCount: 0, medianTuition: 'No matches' };
  }

  const countriesByRegion = {
    Europe: ['germany', 'switzerland', 'netherlands', 'sweden', 'finland', 'austria', 'hungary', 'france', 'italy', 'united kingdom'],
    'North America': ['canada', 'united states', 'usa'],
    'Asia-Pacific': ['australia', 'new zealand', 'japan', 'singapore', 'south korea']
  };
  const countryMatches = (country) => (
    (preferredCountries.length === 0 && preferredRegions.length === 0) ||
    country === 'Global' ||
    preferredCountries.includes(country.toLowerCase()) ||
    preferredRegions.some((region) => countriesByRegion[region]?.includes(country.toLowerCase()))
  );
  const cgpa = Number.parseFloat(profile.cgpa);
  const testScore = Number.parseFloat(profile.englishScore);
  const testName = profile.englishTest || 'IELTS';

  const matchingUniversities = mockUniversities.filter((university) => {
    if (!countryMatches(university.country)) return false;
    if (profile.preferredDegree && university.degree !== profile.preferredDegree) return false;

    const requiredCgpa = Number.parseFloat(university.cgpaReq);
    if (Number.isFinite(cgpa) && Number.isFinite(requiredCgpa) && cgpa < requiredCgpa) return false;

    const scoreRequirement = university.englishReq.match(new RegExp(`${testName}\\s*(\\d+(?:\\.\\d+)?)`, 'i'));
    if (scoreRequirement && Number.isFinite(testScore) && testScore < Number(scoreRequirement[1])) return false;

    return true;
  });

  const fundedScholarships = mockScholarships.filter((scholarship) => (
    scholarship.eligibility === 'Eligible' &&
    scholarship.amount > 0 &&
    countryMatches(scholarship.country)
  ));
  const tuitionCosts = matchingUniversities
    .map((university) => Number(university.tuition.replace(/[^\d.]/g, '')))
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  const middle = Math.floor(tuitionCosts.length / 2);
  const medianTuition = tuitionCosts.length === 0
    ? null
    : tuitionCosts.length % 2 === 0
      ? (tuitionCosts[middle - 1] + tuitionCosts[middle]) / 2
      : tuitionCosts[middle];

  return {
    eligibleCount: matchingUniversities.length + fundedScholarships.length,
    fundedCount: profile.fundingPreference === 'Self-Funded' ? 0 : fundedScholarships.length,
    medianTuition: medianTuition === null
      ? 'No matches'
      : `$${Math.round(medianTuition).toLocaleString()} / year`
  };
}

export function ProfileProvider({ children }) {
  const { user, token } = useAuth();
  const userId = user?.id;
  const [profile, setProfile] = useState(() => readSavedProfile(user?.id));
  const [hasBackendProfile, setHasBackendProfile] = useState(false);
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
  const [appliedOpportunityIds, setAppliedOpportunityIds] = useState(initialData.appliedOpportunityIds);
  const [opportunityTaskStatuses, setOpportunityTaskStatuses] = useState(initialData.opportunityTaskStatuses);
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
    setAppliedOpportunityIds(data.appliedOpportunityIds);
    setOpportunityTaskStatuses(data.opportunityTaskStatuses);
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
    if (!token || userId == null) return undefined;
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
  }, [userId, token, savedReloadCount]);

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

    if (!token || !user) {
      setHasBackendProfile(false);
      return;
    }

    const cachedDraft = readSavedProfile(user.id);

    getProfileApi(token)
      .then(({ exists, data }) => {
        if (!isCurrent) return;

        if (exists && data) {
          setHasBackendProfile(true);
          const mappedProfile = mapBackendToFrontendProfile(data, user, cachedDraft);
          setProfile(mappedProfile);
          writeUserProfile(user.id, mappedProfile);
        } else {
          // 404: Profile not yet created in PostgreSQL
          setHasBackendProfile(false);

          // Populate with user identity or existing in-progress local draft
          if (cachedDraft && (cachedDraft.profileComplete || cachedDraft.profileSetupStep > 0 || cachedDraft.extractedProfile)) {
            setProfile(cachedDraft);
          } else {
            const initial = {
              ...DEFAULT_PROFILE,
              name: user.name || user.full_name || '',
              email: user.email || '',
              personalInfo: {
                ...DEFAULT_PROFILE.personalInfo,
                fullName: user.name || user.full_name || '',
                email: user.email || '',
              },
            };
            setProfile(initial);
            writeUserProfile(user.id, initial);
          }
        }
      })
      .catch((err) => {
        console.warn('Unable to reach backend profile endpoint:', err?.message);
      });

    return () => {
      isCurrent = false;
    };
  }, [user?.id, token]);

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
      const overallScore = english.overallScore || '';
      const legacyEnglishTest = english.testType === 'TOEFL iBT' ? 'TOEFL' : english.testType || profile.englishTest;
      const graduationDate = academic.academicStatus === 'graduated'
        ? academic.graduationDate
        : academic.expectedGraduationDate;
      const approximateBudget = preferences.maxTuitionBudget
        ? `${preferences.currency || 'USD'} ${preferences.maxTuitionBudget} / year`
        : profile.approximateBudget;
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
        cgpa: academic.cgpa || profile.cgpa,
        graduationYear: graduationDate || academic.currentYear || profile.graduationYear,
        englishTest: legacyEnglishTest,
        englishScore: english.testType === 'No Test / Not Taken' ? '' : overallScore || profile.englishScore,
        fieldOfInterest: preferences.fields?.filter((field) => field !== 'Other').join(', ') || preferences.customField || academic.major || profile.fieldOfInterest,
        skills: [academic.technicalSkills, academic.programmingLanguages].filter(Boolean).join(', ').split(',').map((skill) => skill.trim()).filter(Boolean),
        projects: academic.projects ? academic.projects.split(',').map((project) => project.trim()).filter(Boolean) : profile.projects,
        preferredCountries: preferences.countries ? preferredCountries : getPreferredCountries(profile.preferredCountries),
        preferredDegree: "Master's",
        fundingPreference: chosenFunding.join(', ') || profile.fundingPreference,
        approximateBudget,
        profileCompletionPercentage: progress.complete ? 100 : Math.round(((progress.step + 1) / 4) * 100),
        profileSetupStep: progress.complete ? 4 : progress.step + 1,
        profileComplete: Boolean(progress.complete),
        profileStatus: progress.complete ? 'complete' : 'draft',
        profileMethod: isCvSource ? 'cv' : 'manual',
        cvUpload: isCvSource ? profile.cvUpload || null : null,
        extractedProfile: isCvSource ? profile.extractedProfile || null : null,
        extractionFieldStatuses: isCvSource ? profile.extractionFieldStatuses || {} : {},
        profileDraft: updatedData,
        fieldStatuses: progress.fieldStatuses || (isCvSource ? profile.fieldStatuses || {} : {}),
        verifiedProfile: progress.complete ? updatedData : null,
      };

      // When the student submits their completed profile, persist to the real backend
      if (progress.complete) {
        if (token) {
          const backendPayload = mapFrontendToBackendProfile(updatedData, profile);

          if (hasBackendProfile) {
            await updateProfileApi(token, backendPayload);
          } else {
            try {
              await createProfileApi(token, backendPayload);
              if (isStillSignedIn()) setHasBackendProfile(true);
            } catch (createErr) {
              // If it already exists on server, gracefully switch to PUT update
              if (createErr.status === 400 && String(createErr.message).includes('already exists')) {
                await updateProfileApi(token, backendPayload);
                if (isStillSignedIn()) setHasBackendProfile(true);
              } else {
                throw createErr;
              }
            }
          }

          finalProfile.hasBackendProfile = true;
        }
      } else if (hasBackendProfile && token) {
        // If profile was already created in database, perform a best-effort update for drafts
        try {
          const backendPayload = mapFrontendToBackendProfile(updatedData, profile);
          await updateProfileApi(token, backendPayload);
        } catch {
          // Non-blocking for intermediate step drafts
        }
      }

      writeUserProfile(userId, finalProfile);
      if (isStillSignedIn()) setProfile(finalProfile);

      return {
        success: true,
        profile: finalProfile,
        matchStatistics: calculateMatchStatistics(finalProfile),
      };
    } catch (err) {
      console.error('Failed to save profile:', err);
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
    if (!opportunity || typeof opportunity.id !== 'string') {
      throw new Error('A selected opportunity must have a stable ID.');
    }
    const kind = opportunity.kind || (opportunity.id.startsWith('sch-') ? 'scholarship' : 'program');
    const snapshot = { ...opportunity, kind };
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

  const markOpportunityApplied = (id, applied) => {
    const next = applied
      ? [...new Set([...appliedOpportunityIds, id])]
      : appliedOpportunityIds.filter((item) => item !== id);
    writeUserStorage(APPLIED_OPPORTUNITIES_KEY, userId, next);
    setAppliedOpportunityIds(next);
  };

  const setOpportunityTaskStatus = (opportunityId, taskId, status) => {
    if (!['todo', 'in-progress', 'done'].includes(status)) {
      throw new Error(`Unsupported task status: ${status}`);
    }
    const next = {
      ...opportunityTaskStatuses,
      [opportunityId]: { ...opportunityTaskStatuses[opportunityId], [taskId]: status },
    };
    saveApplicationTaskStatuses(userId, opportunityId, next[opportunityId]);
    setOpportunityTaskStatuses(next);
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
      loading,
      hasBackendProfile,
      updateProfile,
      saveCvUpload,
      saveExtractedProfile,
      matchStatistics: calculateMatchStatistics(profileWithAccount),
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
      appliedOpportunityIds,
      markOpportunityApplied,
      opportunityTaskStatuses,
      setOpportunityTaskStatus,
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
