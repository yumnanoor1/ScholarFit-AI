/** fetch, with a readable message when the server can't be reached. Those failures have no status. */
export async function reachApi(url, options) {
  try {
    return await fetch(url, options);
  } catch {
    throw new Error('We couldn’t reach FitScholars. Check your connection and try again.');
  }
}
