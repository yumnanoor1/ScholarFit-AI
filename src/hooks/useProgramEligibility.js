import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import { apiService } from '../services/api';
import { getUnavailableEligibility } from '../services/opportunityApi';

// The profile fields the backend evaluates. ProfileContext updates them only after the backend save resolves.
export function useEligibilityProfileKey(kind) {
  const { profile } = useProfile();
  const academic = profile?.academicBackground || {};
  const english = profile?.englishProficiency || {};
  const personal = profile?.personalInfo || {};

  return JSON.stringify([
    profile?.profileStatus,
    profile?.degreeLevel,
    profile?.cgpa,
    profile?.englishTest,
    profile?.englishScore,
    academic.currentDegree,
    academic.cgpa,
    academic.gradingScale,
    english.testType,
    english.overallScore,
    ...(kind === 'scholarship' ? [personal.citizenshipCountry, personal.dateOfBirth, academic.major] : []),
  ]);
}

/**
 * Shared loader for backend eligibility. Re-fetches only when the token, the item, or the
 * profile fields the backend evaluates change. Results from an older request are never
 * shown for a newer key.
 */
function useEligibility({ kind, id, fetchAll, fetchOne }) {
  const { token } = useAuth();
  const profileKey = useEligibilityProfileKey(kind);
  const requestKey = `${token || ''}|${id ?? 'all'}|${profileKey}`;
  const [response, setResponse] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const request = id == null ? fetchAll(token) : fetchOne(id, token);
    request.then((result) => {
      if (!cancelled) setResponse({ key: requestKey, ...result });
    });
    return () => { cancelled = true; };
  }, [requestKey, token, id, fetchAll, fetchOne]);

  const current = response?.key === requestKey ? response : null;
  const state = current?.state || null;
  const results = current?.results;

  const getEvaluation = useCallback((itemId) => {
    if (state !== 'ok') return getUnavailableEligibility(state || 'error', kind);
    if (results) return results[String(itemId)] || getUnavailableEligibility('not-found', kind);
    return current.evaluation || getUnavailableEligibility('not-found', kind);
  }, [state, results, current, kind]);

  return useMemo(() => ({
    loading: !current,
    state,
    getEvaluation,
    evaluation: id == null || !current ? null : getEvaluation(id),
  }), [current, state, getEvaluation, id]);
}

/**
 * Backend eligibility for the logged-in student.
 * - useProgramEligibility()          -> all programs (GET /eligibility/programs)
 * - useProgramEligibility(programId) -> one program  (GET /eligibility/programs/{id})
 */
export function useProgramEligibility(programId = null) {
  return useEligibility({
    kind: 'program',
    id: programId,
    fetchAll: apiService.getProgramEligibilities,
    fetchOne: apiService.getProgramEligibilityById,
  });
}

/**
 * Backend scholarship eligibility for the logged-in student.
 * - useScholarshipEligibility()   -> every verified scholarship (GET /eligibility/scholarships)
 * - useScholarshipEligibility(id) -> one scholarship, id like "sch-db-12" (GET /eligibility/scholarships/{id})
 */
export function useScholarshipEligibility(scholarshipId = null) {
  return useEligibility({
    kind: 'scholarship',
    id: scholarshipId,
    fetchAll: apiService.getScholarshipEligibilities,
    fetchOne: apiService.getScholarshipEligibilityById,
  });
}

/** Loads a recommendation result again whenever the student, the request or the profile changes. */
function useRecommendationRequest(requestId, load) {
  const { token } = useAuth();
  const profileKey = useEligibilityProfileKey('scholarship');
  const requestKey = `${token || ''}|${requestId}|${profileKey}`;
  const [response, setResponse] = useState(null);

  useEffect(() => {
    let cancelled = false;
    load(token).then((result) => {
      if (!cancelled) setResponse({ key: requestKey, ...result });
    });
    return () => { cancelled = true; };
  }, [requestKey, token, load]);

  const current = response?.key === requestKey ? response : null;
  return useMemo(() => ({ loading: !current, state: current?.state || null, data: current?.data || null }), [current]);
}

/** Scholarships ranked for the logged-in student (GET /recommendations/scholarships). */
export function useScholarshipRecommendations(programId = null) {
  const load = useCallback((token) => apiService.getRecommendations(programId, token), [programId]);
  const result = useRecommendationRequest(`list|${programId ?? ''}`, load);
  return useMemo(() => {
    const items = [...(result.data?.recommendations || []), ...(result.data?.excluded || [])];
    const byId = Object.fromEntries(items.map((item) => [`sch-db-${item.scholarship_id}`, item]));
    return { ...result, getRecommendation: (id) => byId[id] || null };
  }, [result]);
}

/** One scholarship's result (GET /recommendations/scholarships/{id}). */
export function useScholarshipRecommendation(id, programId = null) {
  const load = useCallback((token) => apiService.getScholarshipRecommendation(id, programId, token), [id, programId]);
  return useRecommendationRequest(`one|${id}|${programId ?? ''}`, load);
}

/**
 * Backend eligibility for a few scholarships by id, verified or not (the list endpoint leaves
 * unverified records out). Uses the same endpoint as the Scholarship Details page.
 */
export function useScholarshipEligibilities(ids) {
  const { token } = useAuth();
  const profileKey = useEligibilityProfileKey('scholarship');
  const idsKey = ids.join(',');
  const requestKey = `${token || ''}|${idsKey}|${profileKey}`;
  const [response, setResponse] = useState(null);

  useEffect(() => {
    if (!idsKey) return undefined;
    let cancelled = false;
    const list = idsKey.split(',');
    Promise.all(list.map((id) => apiService.getScholarshipEligibilityById(id, token))).then((results) => {
      if (!cancelled) setResponse({ key: requestKey, results: Object.fromEntries(list.map((id, index) => [id, results[index]])) });
    });
    return () => { cancelled = true; };
  }, [requestKey, idsKey, token]);

  const current = response?.key === requestKey ? response : null;

  const getEvaluation = useCallback((id) => {
    const result = current?.results[id];
    if (result?.state === 'ok') return result.evaluation;
    return getUnavailableEligibility(result?.state || (current ? 'not-found' : 'error'), 'scholarship');
  }, [current]);

  return useMemo(() => ({ loading: Boolean(idsKey) && !current, getEvaluation }), [idsKey, current, getEvaluation]);
}
