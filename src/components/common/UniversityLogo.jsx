import { useState } from 'react';
import { GraduationCap } from 'lucide-react';
import { getUniversityLogo } from '../../services/programFit';
import './UniversityLogo.css';

/**
 * University logo on a white tile. Falls back to `fallback` (default: a cap icon)
 * when we have no logo for that university or the image fails to load.
 * Pass `src` to use a specific image instead of looking up `university`.
 * With `bareFallback`, the fallback is rendered as-is instead of inside the tile.
 */
export default function UniversityLogo({ university, src, size = 40, fallback, bareFallback = false, className = '' }) {
  const logo = src ?? getUniversityLogo(university);
  const [failed, setFailed] = useState(false);
  const showLogo = logo && !failed;

  if (!showLogo && bareFallback && fallback) return fallback;

  return (
    <span
      className={`university-logo-tile ${showLogo ? 'has-logo' : ''} ${className}`.trim()}
      style={{ '--logo-size': `${size}px` }}
      aria-hidden="true"
    >
      {showLogo
        ? <img src={logo} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
        : fallback ?? <GraduationCap size={Math.round(size * 0.48)} />}
    </span>
  );
}
