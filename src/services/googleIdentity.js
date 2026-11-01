const GOOGLE_SCRIPT_URL = 'https://accounts.google.com/gsi/client';

let loading = null;

export function getGoogleClientId() {
  return (import.meta.env?.VITE_GOOGLE_CLIENT_ID || '').trim();
}

/** Loads Google Identity Services once, only on the pages that show the button. */
export function loadGoogleIdentity() {
  if (window.google?.accounts?.id) return Promise.resolve(window.google);
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = GOOGLE_SCRIPT_URL;
      script.async = true;
      script.onload = () => resolve(window.google);
      script.onerror = () => {
        loading = null;
        script.remove();
        reject(new Error('Google sign-in could not be loaded'));
      };
      document.head.appendChild(script);
    });
  }
  return loading;
}
