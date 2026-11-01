import { useLocation } from 'react-router-dom';
import BrandLogo from './BrandLogo';
import './RouteLoadingOverlay.css';

export default function RouteLoadingOverlay() {
  const { pathname } = useLocation();

  return (
    <div
      key={pathname}
      className="route-loading-overlay"
      role="status"
      aria-live="polite"
      aria-label="Loading page"
    >
      <div className="route-loading-card">
        <BrandLogo height={48} alt="FitScholars" />
        <span className="route-loading-spinner" aria-hidden="true" />
        <span className="route-loading-message">Preparing your study journey…</span>
      </div>
    </div>
  );
}
