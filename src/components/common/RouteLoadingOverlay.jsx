import { GraduationCap } from 'lucide-react';
import { useLocation } from 'react-router-dom';
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
        <span className="route-loading-mark" aria-hidden="true">
          <GraduationCap size={22} />
        </span>
        <span className="route-loading-spinner" aria-hidden="true" />
        <span className="route-loading-title">FitScholar AI</span>
        <span className="route-loading-message">Preparing your study journey…</span>
      </div>
    </div>
  );
}
