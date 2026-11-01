import { useEffect, useMemo, useState } from 'react';
import { apiService } from '../services/api';
import { mockScholarships, mockUniversities } from '../data/mockData';

// Older saved/compared IDs (univ-1, sch-1…) point at sample records that never existed in the backend
const LEGACY_SAMPLES = [
  ...mockUniversities.map((item) => ({ ...item, kind: 'program', sourceStatus: item.sourceStatus || 'unverified-sample' })),
  ...mockScholarships.map((item) => ({ ...item, kind: 'scholarship', title: item.name, sourceStatus: item.sourceStatus || 'unverified-sample' })),
];

/**
 * Backend programs and scholarships keyed by frontend ID, for pages that
 * look opportunities up by saved or compared ID.
 * FastAPI Endpoints: GET /programs/ + GET /universities/ + GET /scholarships/
 */
export function useOpportunityCatalog() {
  const [state, setState] = useState({ items: [], loading: true, error: '' });

  useEffect(() => {
    let isCurrent = true;
    Promise.allSettled([apiService.getMatchedUniversities(), apiService.getMatchedScholarships()])
      .then(([programs, scholarships]) => {
        if (!isCurrent) return;
        const items = [
          ...(programs.status === 'fulfilled' ? programs.value.map((item) => ({ ...item, kind: 'program' })) : []),
          ...(scholarships.status === 'fulfilled' ? scholarships.value : []),
        ];
        const failed = programs.status === 'rejected' || scholarships.status === 'rejected';
        if (failed) console.error('Unable to load opportunities.', programs.reason || scholarships.reason);
        setState({
          items,
          loading: false,
          error: failed ? 'Some opportunities could not be loaded. Please try again later.' : '',
        });
      });
    return () => { isCurrent = false; };
  }, []);

  const byId = useMemo(() => {
    const map = new Map(LEGACY_SAMPLES.map((item) => [item.id, item]));
    state.items.forEach((item) => map.set(item.id, item));
    return map;
  }, [state.items]);

  return {
    loading: state.loading,
    error: state.error,
    getOpportunity: (id) => byId.get(id) || null,
  };
}
