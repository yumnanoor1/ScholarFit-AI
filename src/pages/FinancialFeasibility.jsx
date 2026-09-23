import React from 'react';
import CostBreakdown from '../components/financial/CostBreakdown';

export default function FinancialFeasibility() {
  return (
    <div className="page-container">
      <h1 className="page-title">Financial Feasibility Analysis</h1>
      <p className="page-subtitle">Calculation of total out-of-pocket tuition and living costs.</p>

      <div className="disclaimer-box">
        <strong>Cost Estimation Disclaimer:</strong> Calculated values represent general estimations based on official institution fee schedules and regional living indices.
      </div>

      <CostBreakdown tuition={28000} living={14000} funding={15000} />
    </div>
  );
}
