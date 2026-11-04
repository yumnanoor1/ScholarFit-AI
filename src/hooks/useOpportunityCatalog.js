import { useEffect, useMemo, useState } from 'react';
import { apiService } from '../services/api';

/**
 * Backend scholarships keyed by frontend ID, for saved and compared records.
 * FastAPI Endpoint: GET /scholarships/
 */
export function useOpportunityCatalog() {
  const [state, setState] = useState({ items: [], loading: true, error: '' });

  useEffect(() => {
    let isCurrent = true;
    apiService.getMatchedScholarships()
      .then((scholarships) => {
        if (!isCurrent) return;
        setState({ items: scholarships, loading: false, error: '' });
      })
      .catch((error) => {
        console.error('Unable to load scholarships.', error);
        if (isCurrent) setState({ items: [], loading: false, error: 'Scholarships could not be loaded. Please try again later.' });
      });
    return () => { isCurrent = false; };
  }, []);

  const byId = useMemo(() => {
    const map = new Map();
    state.items.forEach((item) => map.set(item.id, item));
    return map;
  }, [state.items]);

  return {
    loading: state.loading,
    error: state.error,
    getOpportunity: (id) => byId.get(id) || null,
  };
}
