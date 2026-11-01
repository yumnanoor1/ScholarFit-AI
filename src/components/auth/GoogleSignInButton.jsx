import { useEffect, useRef, useState } from 'react';
import GoogleIcon from './GoogleIcon';
import { getGoogleClientId, loadGoogleIdentity } from '../../services/googleIdentity';

const MIN_WIDTH = 200;
const MAX_WIDTH = 400; // Google's limit for this button

/**
 * Google's own button, in popup mode. With no client ID, or if Google's script can't load, the
 * same-sized placeholder stays and says why when pressed, so the page never shows an empty gap.
 */
export default function GoogleSignInButton({ label, text = 'continue_with', onCredential, onUnavailable }) {
  const slot = useRef(null);
  const latestOnCredential = useRef(onCredential);
  const [unavailable, setUnavailable] = useState(() => !getGoogleClientId());

  useEffect(() => {
    latestOnCredential.current = onCredential;
  });

  useEffect(() => {
    const clientId = getGoogleClientId();
    if (!clientId) return undefined;
    let isCurrent = true;

    loadGoogleIdentity()
      .then((google) => {
        if (!isCurrent || !slot.current) return;
        google.accounts.id.initialize({
          client_id: clientId,
          callback: ({ credential }) => latestOnCredential.current(credential),
          ux_mode: 'popup',
          auto_select: false,
        });
        google.accounts.id.renderButton(slot.current, {
          type: 'standard',
          theme: 'outline',
          size: 'large',
          shape: 'rectangular',
          logo_alignment: 'center',
          text,
          width: Math.min(Math.max(slot.current.offsetWidth, MIN_WIDTH), MAX_WIDTH),
        });
      })
      .catch(() => {
        if (isCurrent) setUnavailable(true);
      });

    return () => {
      isCurrent = false;
    };
  }, [text]);

  if (unavailable) {
    return (
      <button
        className='relative h-11 w-full rounded-md border border-(--color-border-light) bg-white font-medium outline-hidden hover:cursor-pointer'
        type='button'
        onClick={onUnavailable}
      >
        <span className='flex h-full w-full items-center justify-center gap-3'>
          <GoogleIcon />
          {label}
        </span>
      </button>
    );
  }

  return <div ref={slot} className='flex min-h-11 w-full justify-center' />;
}
