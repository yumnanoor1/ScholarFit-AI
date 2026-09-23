import React, { useEffect, useState } from 'react';
import { apiService } from '../services/api';
import OpportunityCard from '../components/opportunities/OpportunityCard';

export default function Universities() {
  const [list, setList] = useState([]);
  const [filter, setFilter] = useState('All');

  useEffect(() => {
    apiService.getMatchedUniversities().then(setList);
  }, []);

  const filtered = list.filter(item => {
    if (filter === 'Eligible') return item.eligibilityStatus === 'Eligible';
    if (filter === 'Missing') return item.eligibilityStatus === 'Requirements Missing';
    return true;
  });

  return (
    <div className="page-container">
      <h1 className="page-title">University & Admission Matching</h1>
      <p className="page-subtitle">Academic programs evaluated deterministically against your qualifications.</p>

      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
        {['All', 'Eligible', 'Missing'].map(f => (
          <button 
            key={f}
            className={`btn ${filter === f ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setFilter(f)}
          >
            {f === 'All' ? 'All Matches' : f === 'Eligible' ? 'Eligible Only' : 'Missing Requirements'}
          </button>
        ))}
      </div>

      <div>
        {filtered.map(item => (
          <OpportunityCard key={item.id} data={item} />
        ))}
      </div>
    </div>
  );
}