/**
 * FitScholars logo.
 * tone="dark"  -> navy wordmark, for white/light backgrounds
 * tone="light" -> white wordmark, for navy/dark backgrounds
 */
const LOGO_SOURCES = {
  dark: '/images/fitscholars-logo.png',
  light: '/images/fitscholars-logo-light.png',
};

// Intrinsic size of the trimmed logo files (keeps layout stable while loading)
const LOGO_WIDTH = 1164;
const LOGO_HEIGHT = 426;

export default function BrandLogo({ tone = 'dark', height = 40, className = '', alt = 'FitScholars' }) {
  return (
    <img
      className={`brand-logo ${className}`.trim()}
      src={LOGO_SOURCES[tone] || LOGO_SOURCES.dark}
      alt={alt}
      width={Math.round((LOGO_WIDTH / LOGO_HEIGHT) * height)}
      height={height}
      decoding="async"
      style={{ height, width: 'auto', display: 'block' }}
    />
  );
}
