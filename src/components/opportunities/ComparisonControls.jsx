import { useNavigate } from 'react-router-dom';
import { GitCompare } from 'lucide-react';
import { useProfile } from '../../context/ProfileContext';
import './ComparisonControls.css';

export function OpportunityCompareCheckbox({ opportunity }) {
  const { comparisonOpportunityIds, toggleComparisonOpportunity } = useProfile();
  const checked = comparisonOpportunityIds.includes(opportunity.id);
  const limitReached = comparisonOpportunityIds.length === 2 && !checked;

  return (
    <label className="opportunity-compare-select">
      <input
        type="checkbox"
        checked={checked}
        disabled={limitReached}
        aria-label={`${checked ? 'Remove' : 'Add'} ${opportunity.title} ${checked ? 'from' : 'to'} comparison`}
        onChange={() => toggleComparisonOpportunity(opportunity.id)}
      />
      <span>Compare</span>
    </label>
  );
}

export function ComparisonSelectionBar() {
  const navigate = useNavigate();
  const {
    comparisonOpportunityIds,
    clearComparisonOpportunities,
  } = useProfile();
  const canCompare = comparisonOpportunityIds.length === 2;

  if (comparisonOpportunityIds.length === 0) return null;

  return (
    <div className="comparison-selection-bar" role="region" aria-label="Comparison selection">
      <GitCompare size={22} aria-hidden="true" />
      <div className="comparison-selection-status" aria-live="polite">
        <strong>{comparisonOpportunityIds.length} of 2 options selected</strong>
        <span>{canCompare ? 'Ready to compare side by side' : 'Choose one more option to compare'}</span>
      </div>
      <button
        type="button"
        className="comparison-selection-submit"
        disabled={!canCompare}
        onClick={() => navigate(`/compare?ids=${encodeURIComponent(comparisonOpportunityIds.join(','))}`)}
      >
        Compare selected
      </button>
      <button
        type="button"
        className="comparison-selection-clear"
        onClick={clearComparisonOpportunities}
      >
        Clear
      </button>
    </div>
  );
}
