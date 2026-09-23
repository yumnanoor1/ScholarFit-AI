import React from 'react';
import RecommendationCard from '../components/recommendations/RecommendationCard';

export default function Recommendations() {
  return (
    <div className="page-container">
      <h1 className="page-title">Explainable Decision Recommendations</h1>
      <p className="page-subtitle">Algorithmically matched options accompanied by transparent decision rationale.</p>

      <RecommendationCard 
        title="M.Sc. Informatics"
        university="Technical University of Munich"
        score={94}
        rationale="Strong alignment in Machine Learning course requirements, low-tuition structure matches financial preferences."
        missingReq={null}
      />

      <RecommendationCard 
        title="M.Sc. Computer Science"
        university="University of Toronto"
        score={78}
        rationale="High academic alignment, but requires securing external graduate funding to clear remaining balance."
        missingReq="CGPA is 0.05 under recommended program threshold."
      />
    </div>
  );
}