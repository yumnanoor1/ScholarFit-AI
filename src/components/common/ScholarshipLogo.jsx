import { useState } from 'react';
import { GraduationCap } from 'lucide-react';
import './ScholarshipLogo.css';

/**
 * Scholarship provider logo on a white tile. Falls back to a cap icon when no
 * provider image is available or the image fails to load.
 * With `bareFallback`, the fallback is rendered as-is instead of inside the tile.
 */
export default function ScholarshipLogo({ src, size = 40, fallback, bareFallback = false, className = '' }) {
  const logo = src;
  const [failed, setFailed] = useState(false);
  const showLogo = logo && !failed;

  if (!showLogo && bareFallback && fallback) return fallback;

  return (
    <span
      className={`scholarship-logo-tile ${showLogo ? 'has-logo' : ''} ${className}`.trim()}
      style={{ '--logo-size': `${size}px` }}
      aria-hidden="true"
    >
      {showLogo
        ? <img src={logo} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
        : fallback ?? <GraduationCap size={Math.round(size * 0.48)} />}
    </span>
  );
}
