export const ONBOARDING_PATH = '/profile-setup';
export const PROFILE_DONE_PATH = '/profile-setup/complete';
export const HOME_PATH = '/dashboard';

export const LOADING_COMPLETION = { status: 'loading', required: true, complete: false, percent: 0, missing: [] };
export const FAILED_COMPLETION = { ...LOADING_COMPLETION, status: 'error' };

/** The API's own answer is the only thing that unlocks the app. Nothing saved in the browser can. */
export function canUseApp(completion) {
  return completion.status === 'ready' && (!completion.required || completion.complete);
}

/**
 * What a route should do for this student:
 *   'complete'    the app's features, for finished profiles
 *   'onboarding'  the setup pages, which a finished profile has no more need of
 *   'any'         pages open either way, such as profile editing, once the status is known
 * Returns 'wait', 'failed', 'allow', or the path to redirect to.
 */
export function decideAccess(completion, gate) {
  if (completion.status === 'loading') return 'wait';
  if (completion.status === 'error') return 'failed';
  if (gate === 'complete') return canUseApp(completion) ? 'allow' : ONBOARDING_PATH;
  if (gate === 'onboarding') return completion.complete ? HOME_PATH : 'allow';
  return 'allow';
}

/** Where someone goes after signing in. */
export function homePathFor(user, status) {
  if (user?.role === 'admin') return '/admin/scholarships';
  return status.complete ? HOME_PATH : ONBOARDING_PATH;
}
