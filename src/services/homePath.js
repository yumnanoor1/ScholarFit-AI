import { getProfileStatusApi } from './profileApi';
import { HOME_PATH, homePathFor } from './profileAccess';

/** Where someone goes after signing in. If the status can't be read, the dashboard's own gate decides. */
export async function getHomePath({ user, token }) {
  try {
    return homePathFor(user, await getProfileStatusApi(token));
  } catch {
    return user?.role === 'admin' ? homePathFor(user, {}) : HOME_PATH;
  }
}
