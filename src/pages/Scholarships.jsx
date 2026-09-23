import React, { useEffect, useState } from 'react';
import { apiService } from '../services/api';
import FundingCard from '../components/funding/FundingCard';

export default function Scholarships() {
  const [scholarships, setScholarships] = useState([]);

  useEffect(() => {
    apiService.getMatchedScholarships().then(setScholarships);
  }, []);

  return (
    <div className="page-container">
      <h1 className="page-title">Scholarship & Funding Matching</h1>
      <p className="page-subtitle">Fellowships, Research Assistantships (RA), Teaching Assistantships (TA), and Waivers.</p>

      <div className="grid-2">
        {scholarships.map(item => (
          <FundingCard key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}