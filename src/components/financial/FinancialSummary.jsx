import React from 'react';
import CostCard from './CostCard';

export default function FinancialSummary({ tuition = 12000, living = 10000, funding = 15000 }) {
  const totalCost = tuition + living;
  const remaining = Math.max(0, totalCost - funding);

  return (
    <div>
      <div className="grid-3" style={{ gap: '16px' }}>
        <CostCard 
          label="Total Annual Expense" 
          amount={totalCost} 
          type="expense" 
          note="Includes Tuition + Living"
        />
        <CostCard 
          label="Available Funding" 
          amount={funding} 
          type="funding" 
          note="Scholarships & Assistantships"
        />
        <CostCard 
          label="Net Out-Of-Pocket" 
          amount={remaining} 
          type="remaining" 
          note={remaining === 0 ? "100% Fully Funded" : "Self-Funded Balance"}
        />
      </div>
    </div>
  );
}